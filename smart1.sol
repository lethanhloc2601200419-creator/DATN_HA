// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// ============================================================
//  smart1.sol — VNDT TOKEN (ERC20)
// ------------------------------------------------------------
//  Vai trò : "Tiền tệ số" của nền tảng, tỉ lệ 1:1 với VNĐ.
//  Nguyên lý "Double Integrity":
//      - Deploy TRƯỚC smart2 (DCPManager).
//      - Sau khi deploy smart2, owner gọi `setManager(smart2Address)`
//        để khoá quyền mint/burn vào đúng 1 contract quản lý.
//      - Từ đó chỉ có smart2 mới có thể phát hành / huỷ token →
//        đảm bảo không thể mint lậu ngoài luồng chính thức của dApp.
// ============================================================

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract VNDT is ERC20, Ownable {
    /// @notice Địa chỉ contract DCPManager (smart2.sol) — duy nhất được phép mint.
    ///         Đồng thời vẫn giữ quyền burn cho backward-compat với `burn()` cũ.
    address public manager;

    /// @notice [V3] Địa chỉ contract DisbursementExecutor (smart3.sol) —
    ///         có quyền burn token từ multisig vault kèm bankTxId để lưu
    ///         proof-of-payout on-chain. Gán qua `setBurner()`.
    ///         KHÔNG có quyền mint — chỉ burn.
    address public burner;

    event ManagerUpdated(address indexed oldManager, address indexed newManager);
    event BurnerUpdated(address indexed oldBurner, address indexed newBurner);

    /// @notice Phát hành khi smart3 đốt token kèm Bank Transaction ID.
    ///         Dùng làm audit trail immutable giữa fiat (PayOS) và on-chain.
    event TokensBurnedWithBankTx(
        address indexed from,
        uint256 amount,
        string  bankTxId,
        uint256 indexed campaignId,
        uint256 indexed proposalId
    );

    /// @dev Khoá hàm chỉ cho phép smart2 (manager) gọi.
    modifier onlyManager() {
        require(msg.sender == manager, "VNDT: chi co DCPManager moi duoc goi");
        _;
    }

    /// @dev Khoá hàm cho phép smart2 (manager) HOẶC smart3 (burner) gọi.
    modifier onlyManagerOrBurner() {
        require(
            msg.sender == manager || msg.sender == burner,
            "VNDT: chi manager hoac burner moi duoc goi"
        );
        _;
    }

    /**
     * @param initialOwner Ví sẽ nhận quyền Ownable (thường là ví deploy / admin relayer
     *                     của backend). Owner CHỈ có quyền duy nhất là `setManager`;
     *                     không có quyền mint/burn.
     */
    constructor(address initialOwner) ERC20("VND Token", "VNDT") Ownable(initialOwner) {}

    /**
     * @notice Liên kết (hoặc đổi) địa chỉ DCPManager được phép phát hành token.
     * @dev    Thường gọi đúng 1 lần sau khi deploy smart2.sol.
     *
     *         ⚠️  RỦI RO DRIFT: owner vẫn có thể re-point `manager` sang địa chỉ
     *         khác bất kỳ lúc nào, phá "Double Integrity" invariant. Để làm
     *         manager bất biến tuyệt đối sau khi link, sau cách này phải gọi
     *         `renounceOwnership()` để không ai đổi được nữa. Hoặc chuyển quyền
     *         owner sang 1 ví multisig / DAO của chính người vận hành dự án.
     */
    function setManager(address _manager) external onlyOwner {
        require(_manager != address(0), "VNDT: manager = 0 khong hop le");
        emit ManagerUpdated(manager, _manager);
        manager = _manager;
    }

    /**
     * @notice [V3] Gán địa chỉ DisbursementExecutor (smart3.sol) được phép burn
     *         token từ multisig vault khi finalize giải ngân với bankTxId.
     *         Cho phép set = address(0) để tạm thời revoke quyền burn của smart3.
     */
    function setBurner(address _burner) external onlyOwner {
        emit BurnerUpdated(burner, _burner);
        burner = _burner;
    }

    /// @notice Đúc token. Chỉ DCPManager gọi được (thông qua recordDonation).
    function mint(address to, uint256 amount) external onlyManager {
        _mint(to, amount);
    }

    /// @notice Đốt token cũ — manager-only, không có metadata bankTx.
    ///         Giữ lại cho backward-compat (smart2 có thể gọi khi cần).
    function burn(address from, uint256 amount) external onlyManager {
        _burn(from, amount);
    }

    /**
     * @notice [V3] Đốt token KÈM bankTxId để lưu audit trail on-chain.
     *         Được gọi bởi smart3.finalizeBurnWithBankTx() sau khi PayOS
     *         xác nhận đã chuyển fiat thành công. Event phát hành mang
     *         `bankTxId` + `campaignId` + `proposalId` cho cross-reference
     *         với record PayOS off-chain.
     *
     * @param from        Địa chỉ giữ token (thường là multisig vault của campaign).
     * @param amount      Số token cần burn (đã tính theo 18 decimals).
     * @param bankTxId    ID giao dịch ngân hàng do PayOS Payout API trả về.
     * @param campaignId  Campaign.id (Django PK) để phục vụ indexer.
     * @param proposalId  DisbursementProposal.id (Django PK) để phục vụ indexer.
     */
    function burnWithBankTx(
        address from,
        uint256 amount,
        string calldata bankTxId,
        uint256 campaignId,
        uint256 proposalId
    ) external onlyManagerOrBurner {
        require(from != address(0), "VNDT: from = 0 khong hop le");
        require(amount > 0, "VNDT: amount phai > 0");
        require(bytes(bankTxId).length > 0, "VNDT: bankTxId rong");

        _burn(from, amount);

        emit TokensBurnedWithBankTx(from, amount, bankTxId, campaignId, proposalId);
    }
}
