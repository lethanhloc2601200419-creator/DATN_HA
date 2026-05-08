// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// ============================================================
//  smart3.sol — DisbursementExecutor (Layer-2 Finalization)
// ------------------------------------------------------------
//  Vai trò: "tầng thực thi" cho luồng giải ngân 2-layer (Web3 + Fiat).
//  Tầng này HOẠT ĐỘNG SONG SONG với smart2.sol (không thay thế):
//
//      smart2.sol = "đề xuất + multisig on-chain 3-of-3" (luồng cũ, gasless UserOp).
//      smart3.sol = "multisig qua chữ ký EIP-712 off-chain + burn-with-bankTxId".
//
//  Luồng dùng smart3 (Phase 1-4 theo spec yêu cầu):
//    ┌──────────────────────────────────────────────────────────┐
//    │ PHASE 1 (off-chain): Tổ chức tạo proposal + IPFS CID     │
//    │ PHASE 2 (off-chain): 3 bên ký EIP-712 bằng MetaMask      │
//    │                      → Backend gom v,r,s vào DB          │
//    │ PHASE 3a (on-chain): Admin gọi recordMultisigApproval()  │
//    │                      → contract ecrecover 3 sigs         │
//    │                      → emit MultisigConfirmed            │
//    │ PHASE 3b (off-chain): Admin bấm "Execute" → gọi PayOS    │
//    │                       Payout API → chờ webhook           │
//    │ PHASE 4 (on-chain):   Admin gọi finalizeBurnWithBankTx() │
//    │                       → smart1.burnWithBankTx() đốt VNDT │
//    │                       từ multisig vault + lưu bankTxId   │
//    │                       → emit DisbursementFinalized       │
//    └──────────────────────────────────────────────────────────┘
//
//  Thiết kế:
//    - Ví Admin (relayer) trả gas cho CẢ 2 giao dịch on-chain (3a + 4).
//    - 3 approvers (Organization, Supervisor, Admin) KHÔNG cần ETH — chỉ ký
//      typed-data bằng MetaMask (UX gasless).
//    - State chống replay: mỗi proposalId chỉ confirm + finalize 1 lần.
//    - nonce per-signer (theo role) tránh replay cross-proposal cùng format.
// ============================================================

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

/// @dev Interface VNDT (smart1.sol) — cần `burnWithBankTx` mới bổ sung.
interface IVNDTBurner {
    function burnWithBankTx(
        address from,
        uint256 amount,
        string calldata bankTxId,
        uint256 campaignId,
        uint256 proposalId
    ) external;
}

/// @dev Interface DCPManager (smart2.sol) — chỉ đọc wallet roles + getCampaign.
interface IDCPManagerRead {
    function adminWallet() external view returns (address);
    function supervisorWallet() external view returns (address);
    function getCampaign(uint256 _campaignId)
        external
        view
        returns (
            address organization,
            address multisigVault,
            uint256 currentAmount,
            bool    isDisbursed,
            string memory ipfsCid,
            uint8  approvals
        );
}

contract DisbursementExecutor is Ownable {
    using ECDSA for bytes32;

    // -------------------------------------------
    // 1. Liên kết các contract anh em
    // -------------------------------------------
    IVNDTBurner    public immutable vndt;         // smart1.sol
    IDCPManagerRead public immutable dcpManager;  // smart2.sol

    // -------------------------------------------
    // 2. EIP-712 domain
    // -------------------------------------------
    bytes32 public constant EIP712_DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );

    // Struct approver ký:
    //   DisbursementApproval(
    //     uint256 proposalId,
    //     uint256 campaignId,
    //     uint256 amount,
    //     address recipient,
    //     string  ipfsCid,
    //     uint256 deadline,
    //     uint256 nonce,
    //     string  role
    //   )
    bytes32 public constant APPROVAL_TYPEHASH = keccak256(
        "DisbursementApproval(uint256 proposalId,uint256 campaignId,uint256 amount,address recipient,string ipfsCid,uint256 deadline,uint256 nonce,string role)"
    );

    bytes32 public immutable DOMAIN_SEPARATOR;

    // -------------------------------------------
    // 3. Proposal state
    // -------------------------------------------
    enum Stage { None, MultisigConfirmed, Finalized }

    struct ProposalRecord {
        Stage stage;
        uint256 campaignId;
        uint256 amount;
        address recipient;       // address on-chain thụ hưởng (multisig vault hoặc tổ chức)
        bytes32 approvalDigest;  // hash typed-data đã verify
        string bankTxId;         // set ở phase 4
    }

    mapping(uint256 => ProposalRecord) public proposals;
    // Prevent replay: mỗi (signer, nonce) chỉ dùng 1 lần.
    mapping(address => mapping(uint256 => bool)) public usedNonces;

    // -------------------------------------------
    // 4. Events
    // -------------------------------------------
    event MultisigConfirmed(
        uint256 indexed proposalId,
        uint256 indexed campaignId,
        uint256 amount,
        string  ipfsCid,
        address organization,
        address supervisor,
        address admin
    );

    event DisbursementFinalized(
        uint256 indexed proposalId,
        uint256 indexed campaignId,
        uint256 amount,
        string  bankTxId,
        address multisigVault
    );

    // -------------------------------------------
    // 5. Constructor
    // -------------------------------------------
    constructor(address _vndt, address _dcpManager) Ownable(msg.sender) {
        require(_vndt != address(0), "DE: vndt = 0");
        require(_dcpManager != address(0), "DE: dcpManager = 0");
        vndt = IVNDTBurner(_vndt);
        dcpManager = IDCPManagerRead(_dcpManager);

        DOMAIN_SEPARATOR = keccak256(abi.encode(
            EIP712_DOMAIN_TYPEHASH,
            keccak256(bytes("DisbursementExecutor")),
            keccak256(bytes("1")),
            block.chainid,
            address(this)
        ));
    }

    // -------------------------------------------
    // 6. Payload + Signature structs
    // -------------------------------------------
    /**
     * @dev Gom 6 trường "shared" mà cả 3 approver phải ký identical
     *      vào 1 struct. Lý do: Solidity giới hạn 16 local-slot per-function
     *      ("stack too deep") — truyền qua calldata struct chỉ chiếm 1 slot
     *      (pointer), giải phóng stack cho 3 bộ sig verification.
     */
    struct DisbursementPayload {
        uint256 proposalId;
        uint256 campaignId;
        uint256 amount;
        address recipient;
        string  ipfsCid;
        uint256 deadline;
    }

    struct SigBundle {
        bytes orgSig;
        bytes supervisorSig;
        bytes adminSig;
        uint256 orgNonce;
        uint256 supervisorNonce;
        uint256 adminNonce;
    }

    // -------------------------------------------
    // 7. Typed-data hashing
    // -------------------------------------------
    function _hashApproval(
        DisbursementPayload calldata payload,
        uint256 nonce,
        string memory role
    ) internal view returns (bytes32) {
        bytes32 structHash = keccak256(abi.encode(
            APPROVAL_TYPEHASH,
            payload.proposalId,
            payload.campaignId,
            payload.amount,
            payload.recipient,
            keccak256(bytes(payload.ipfsCid)),
            payload.deadline,
            nonce,
            keccak256(bytes(role))
        ));
        return keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));
    }

    /// @notice Giúp frontend test hash khớp với backend trước khi ký.
    function getApprovalDigest(
        DisbursementPayload calldata payload,
        uint256 nonce,
        string calldata role
    ) external view returns (bytes32) {
        return _hashApproval(payload, nonce, role);
    }

    // -------------------------------------------
    // 8. Phase 3a — Record 3 chữ ký EIP-712
    // -------------------------------------------
    /**
     * @notice Admin relayer gọi sau khi thu thập đủ 3 chữ ký off-chain.
     *         Contract verify ecrecover 3 sigs → emit MultisigConfirmed.
     * @dev    Tất cả 3 chữ ký phải cùng payload (proposalId, campaignId, amount,
     *         recipient, ipfsCid, deadline). Chỉ `nonce` và `role` khác nhau
     *         per-signer.
     */
    function recordMultisigApproval(
        DisbursementPayload calldata payload,
        SigBundle calldata sigs
    ) external onlyOwner {
        require(payload.proposalId > 0, "DE: proposalId = 0");
        require(payload.campaignId > 0, "DE: campaignId = 0");
        require(payload.amount > 0, "DE: amount = 0");
        require(payload.recipient != address(0), "DE: recipient = 0");
        require(block.timestamp <= payload.deadline, "DE: signatures expired");

        ProposalRecord storage p = proposals[payload.proposalId];
        require(p.stage == Stage.None, "DE: da confirm truoc do");

        // Nạp roles từ smart2.sol (single source of truth).
        (address organization, address multisigVault, , bool isDisbursed, , ) =
            dcpManager.getCampaign(payload.campaignId);
        require(organization != address(0), "DE: campaign khong ton tai");
        require(!isDisbursed, "DE: campaign da giai ngan");
        require(multisigVault != address(0), "DE: multisig vault = 0");

        address admin = dcpManager.adminWallet();
        address supervisor = dcpManager.supervisorWallet();

        // Verify + consume 3 chữ ký trong 1 helper để giảm stack.
        _verifyAndConsume(payload, sigs.orgSig,        sigs.orgNonce,        "organization", organization);
        _verifyAndConsume(payload, sigs.supervisorSig, sigs.supervisorNonce, "supervisor",   supervisor);
        bytes32 admDigest =
            _verifyAndConsume(payload, sigs.adminSig,  sigs.adminNonce,      "admin",        admin);

        // Ghi nhận approval → chuyển sang Ready_to_Payout off-chain.
        p.stage = Stage.MultisigConfirmed;
        p.campaignId = payload.campaignId;
        p.amount = payload.amount;
        p.recipient = payload.recipient;
        p.approvalDigest = admDigest;

        emit MultisigConfirmed(
            payload.proposalId,
            payload.campaignId,
            payload.amount,
            payload.ipfsCid,
            organization,
            supervisor,
            admin
        );
    }

    /**
     * @dev Verify EIP-712 signature của `expectedSigner` cho `payload` +
     *      (nonce, role) rồi mark nonce đã dùng. Revert nếu sig sai hoặc
     *      nonce đã consume. Trả về digest để caller tái dùng (tiết kiệm
     *      re-hash).
     */
    function _verifyAndConsume(
        DisbursementPayload calldata payload,
        bytes calldata sig,
        uint256 nonce,
        string memory role,
        address expectedSigner
    ) internal returns (bytes32 digest) {
        digest = _hashApproval(payload, nonce, role);
        require(_recover(digest, sig) == expectedSigner, "DE: sig khong hop le");
        require(!usedNonces[expectedSigner][nonce], "DE: nonce da dung");
        usedNonces[expectedSigner][nonce] = true;
    }

    // -------------------------------------------
    // 9. Phase 4 — Finalize burn with bankTxId
    // -------------------------------------------
    /**
     * @notice Gọi sau khi PayOS webhook xác nhận đã chuyển fiat thành công.
     *         Backend extract bankTxId từ webhook → truyền vào đây → burn
     *         exactly `amount` VNDT từ multisig vault + ghi bankTxId on-chain
     *         như proof immutable.
     * @param  multisigVault  địa chỉ vault chứa VNDT (đọc từ smart2 để cross-check).
     * @param  bankTxId       Bank Transaction ID do PayOS trả về (audit trail).
     */
    function finalizeBurnWithBankTx(
        uint256 proposalId,
        address multisigVault,
        string calldata bankTxId
    ) external onlyOwner {
        ProposalRecord storage p = proposals[proposalId];
        require(p.stage == Stage.MultisigConfirmed, "DE: chua confirm multisig");
        require(bytes(bankTxId).length > 0, "DE: bankTxId rong");

        // Double-check multisigVault khớp với smart2 (tránh admin mistype).
        (, address vaultOnChain, , , , ) = dcpManager.getCampaign(p.campaignId);
        require(vaultOnChain == multisigVault, "DE: vault khong khop smart2");

        // Gọi burn trên smart1 — smart1 phải đã `setBurner(address(this))` trước.
        vndt.burnWithBankTx(
            multisigVault,
            p.amount,
            bankTxId,
            p.campaignId,
            proposalId
        );

        p.stage = Stage.Finalized;
        p.bankTxId = bankTxId;

        emit DisbursementFinalized(
            proposalId,
            p.campaignId,
            p.amount,
            bankTxId,
            multisigVault
        );
    }

    // -------------------------------------------
    // 10. View helpers
    // -------------------------------------------
    function getProposal(uint256 proposalId)
        external
        view
        returns (
            uint8   stage,
            uint256 campaignId,
            uint256 amount,
            address recipient,
            string memory bankTxId
        )
    {
        ProposalRecord storage p = proposals[proposalId];
        return (uint8(p.stage), p.campaignId, p.amount, p.recipient, p.bankTxId);
    }

    // -------------------------------------------
    // 11. Internal
    // -------------------------------------------
    function _recover(bytes32 digest, bytes memory sig) internal pure returns (address) {
        return ECDSA.recover(digest, sig);
    }
}







