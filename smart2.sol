// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// ============================================================
//  smart2.sol — DCPManager + Soulbound Achievement Badge (SBT)
// ------------------------------------------------------------
//  Vai trò kép ("Double Integrity"):
//    1) Trung tâm quản lý dự án: tạo campaign, ghi nhận quyên góp,
//       đề xuất & duyệt giải ngân (multisig 3 chữ ký).
//    2) Phát hành "Huy hiệu Thành tựu" dưới dạng ERC721 Soulbound —
//       token KHÔNG thể chuyển/bán, gắn vĩnh viễn với ví donor như
//       bằng chứng đóng góp minh bạch on-chain.
//
//  Luồng tiền "Double Integrity" tại recordDonation:
//      A) Gọi VNDT(smart1).mint(multisigAddress, amount)
//         → ký quỹ token vào kho đa-ký của chiến dịch.
//      B) _safeMint(donor, nextTokenId)
//         → thưởng huy hiệu SBT cho donor.
//      C) Cập nhật mappings phục vụ Quadratic Funding:
//         - donorContributions[cid][donor]  → tổng đóng góp 1 donor / 1 campaign
//         - uniqueDonors[cid]               → số ví duy nhất đã ủng hộ
//         - campaignRaised[cid]             → tổng quỹ đã huy động
//
//  Thứ tự deploy:
//      1. Deploy smart1.sol (VNDT), lấy address A.
//      2. Deploy smart2.sol với constructor(A, supervisor, treasury).
//      3. Gọi VNDT(A).setManager(smart2Address) để khoá quyền mint.
// ============================================================

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @dev Interface rút gọn của smart1.sol (VNDT) — smart2 chỉ dùng mint.
/// (burn được giữ trên smart1 nhưng không gọi từ smart2, nên không khai báo ở đây
///  để giữ ABI gọn.)
interface IVNDT {
    function mint(address to, uint256 amount) external;
}

contract DCPManager is ERC721, Ownable {
    // -------------------------------------------
    // 1. Tham chiếu token VNDT (smart1.sol)
    // -------------------------------------------
    IVNDT public immutable vndt;

    // -------------------------------------------
    // 2. Ví vai trò hệ thống
    // -------------------------------------------
    address public supervisorWallet; // Cơ quan giám sát
    address public treasuryWallet;   // Quỹ duy trì hệ thống
    address public adminWallet;      // Backend Django (relayer)

    // Phí nền tảng (0 ~ 10%). Nếu > 0, fee được mint cho treasuryWallet.
    uint256 public platformFee = 0;

    // -------------------------------------------
    // 3. Campaign state
    // -------------------------------------------
    struct Campaign {
        address organization;     // Ví đại diện tổ chức xin giải ngân
        address multisigVault;    // Kho đa-ký của chiến dịch (nhận VNDT)
        uint256 currentAmount;    // Tổng VNDT đã mint cho campaign này
        bool    isDisbursed;      // Đã chốt giải ngân chưa
        string  ipfsCid;          // Hash chứng từ giải ngân
        uint8   approvals;        // Số chữ ký đã có
        mapping(address => bool) hasApproved;
    }

    mapping(uint256 => Campaign) private _campaigns;
    uint256 public campaignCount;

    // -------------------------------------------
    // 4. Dữ liệu phục vụ Quadratic Funding
    // -------------------------------------------
    /// @notice Tổng số wei (18 decimals) một donor đã đóng vào 1 campaign.
    mapping(uint256 => mapping(address => uint256)) public donorContributions;

    /// @notice Tổng huy động của mỗi campaign (= sum donor mint — không tính fee).
    mapping(uint256 => uint256) public campaignRaised;

    /// @notice Đếm ví duy nhất đã ủng hộ mỗi campaign (dùng cho QF weight).
    mapping(uint256 => uint256) public uniqueDonors;


    // -------------------------------------------
    // 5. Soulbound Badge (ERC721) state
    // -------------------------------------------
    /// @notice Tổng số SBT đã phát hành (dùng làm tokenId tiếp theo, tăng dần từ 1).
    uint256 public totalBadges;

    /// @notice badgeCampaign[tokenId] → campaignId mà huy hiệu này vinh danh.
    mapping(uint256 => uint256) public badgeCampaign;

    /// @notice badgeAmount[tokenId] → số VNDT (wei) donor đã đóng để nhận huy hiệu đó.
    mapping(uint256 => uint256) public badgeAmount;

    /// @dev tokenURI tuỳ chỉnh cho mỗi badge (set bởi owner, optional).
    mapping(uint256 => string) private _badgeURI;

    /// @dev Base URI mặc định cho metadata — ví dụ "ipfs://<cid>/".
    string private _baseURIStorage;

    // -------------------------------------------
    // 6. Events
    // -------------------------------------------
    event CampaignCreated(uint256 indexed campaignId, address organization, address multisigVault);
    event DonationRecorded(
        uint256 indexed campaignId,
        address indexed donor,
        address indexed multisigVault,
        uint256 netAmount,
        uint256 fee,
        uint256 badgeTokenId
    );
    event DisbursementProposed(uint256 indexed campaignId, string ipfsCid);
    event DisbursementApproved(uint256 indexed campaignId, address approver);
    event DisbursedAndBurned(uint256 indexed campaignId, uint256 amountDisbursed, string ipfsCid);
    event BadgeMinted(address indexed donor, uint256 indexed tokenId, uint256 indexed campaignId, uint256 amount);

    // -------------------------------------------
    // 7. Constructor
    // -------------------------------------------
    /**
     * @param _vndt        Địa chỉ contract smart1.sol (VNDT) đã deploy.
     * @param _supervisor  Ví giám sát (1 trong 3 chữ ký giải ngân).
     * @param _treasury    Ví nhận phí nền tảng.
     */
    constructor(address _vndt, address _supervisor, address _treasury)
        ERC721("Donation Achievement Badge", "DAB")
        Ownable(msg.sender)
    {
        require(_vndt != address(0), "DCP: VNDT = 0");
        require(_supervisor != address(0), "DCP: supervisor = 0");
        require(_treasury != address(0), "DCP: treasury = 0");

        vndt = IVNDT(_vndt);
        adminWallet = msg.sender;
        supervisorWallet = _supervisor;
        treasuryWallet = _treasury;
    }

    // -------------------------------------------
    // 8. Admin config
    // -------------------------------------------
    /**
     * @notice Cập nhật phí nền tảng.
     * @param _fee Đơn vị PHẦN TRĂM (0-10), không phải basis points.
     *             VD: `_fee = 3` nghĩa là 3%. Đặt = 0 để tắt phí.
     */
    function setPlatformFee(uint256 _fee) external onlyOwner {
        require(_fee <= 10, "Phi khong duoc vuot qua 10%");
        platformFee = _fee;
    }

    function setSupervisorWallet(address _s) external onlyOwner {
        require(_s != address(0), "DCP: supervisor = 0");
        supervisorWallet = _s;
    }

    function setTreasuryWallet(address _t) external onlyOwner {
        require(_t != address(0), "DCP: treasury = 0");
        treasuryWallet = _t;
    }

    function setBaseURI(string calldata baseURI_) external onlyOwner {
        _baseURIStorage = baseURI_;
    }

    function setBadgeURI(uint256 tokenId, string calldata uri) external onlyOwner {
        require(_ownerOf(tokenId) != address(0), "DCP: token khong ton tai");
        _badgeURI[tokenId] = uri;
    }

    // -------------------------------------------
    // 9. Luồng 1 — Tạo dự án
    // -------------------------------------------
    /**
     * @notice Tạo campaign on-chain, gắn với Django Campaign.id + ví multisig riêng.
     * @param _campaignId    ID đồng nhất với Postgres PK của Django.
     * @param _organization  Ví đại diện tổ chức.
     * @param _multisigVault Ví đa-ký của chiến dịch — nơi nhận token VNDT đã mint.
     *                       Nếu bạn chưa có hệ thống multisig riêng cho từng campaign,
     *                       tạm thời có thể dùng `_organization` hoặc `address(this)`.
     */
    function createCampaign(
        uint256 _campaignId,
        address _organization,
        address _multisigVault
    ) external onlyOwner {
        require(_campaignId > 0, "Campaign ID phai > 0");
        require(_organization != address(0), "To chuc = 0 khong hop le");
        require(_multisigVault != address(0), "Multisig = 0 khong hop le");
        require(_campaigns[_campaignId].organization == address(0), "Chien dich da ton tai");

        Campaign storage c = _campaigns[_campaignId];
        c.organization = _organization;
        c.multisigVault = _multisigVault;
        campaignCount++;

        emit CampaignCreated(_campaignId, _organization, _multisigVault);
    }

    // -------------------------------------------
    // 10. Luồng 2 — Ghi nhận quyên góp (core)
    // -------------------------------------------
    /**
     * @notice Backend gọi sau khi PayOS xác nhận đã nhận VNĐ thật.
     * @dev    "Double Integrity":
     *           A) mint VNDT cho multisig  → kho bạc của campaign nắm tiền
     *           B) _safeMint SBT cho donor → huy hiệu vinh danh không thể chuyển
     *           C) update QF mappings      → phục vụ tính matching pool
     * @param _campaignId       ID campaign đã createCampaign trước đó.
     * @param _donor            Ví donor (Web3Auth / smart account).
     * @param _multisigAddress  Ví multisig nhận VNDT. Phải khớp với multisigVault đã
     *                          gán lúc createCampaign — chống admin đổi đích mint.
     * @param _fiatAmount       Số wei (18 decimals) tương ứng fiat (VND * 10^18).
     */
    function recordDonation(
        uint256 _campaignId,
        address _donor,
        address _multisigAddress,
        uint256 _fiatAmount
    ) external onlyOwner {
        Campaign storage c = _campaigns[_campaignId];
        require(c.organization != address(0), "Chien dich khong ton tai");
        require(!c.isDisbursed, "Chien dich da giai ngan");
        require(_donor != address(0), "Donor = 0 khong hop le");
        require(_multisigAddress != address(0), "Multisig = 0 khong hop le");
        require(_multisigAddress == c.multisigVault, "Multisig khong khop campaign");
        require(_fiatAmount > 0, "Amount phai > 0");

        // -- Phí nền tảng (nếu có) --
        uint256 fee = 0;
        uint256 netAmount = _fiatAmount;
        if (platformFee > 0) {
            fee = (_fiatAmount * platformFee) / 100;
            netAmount = _fiatAmount - fee;
            vndt.mint(treasuryWallet, fee);
        }

        // -- A) Ký quỹ VNDT vào multisig của campaign --
        vndt.mint(_multisigAddress, netAmount);

        // -- C1) Cập nhật sổ sách QF (checks-effects-interactions: trước _safeMint
        //        vì ERC721Receiver có thể reentrant) --
        c.currentAmount += netAmount;
        campaignRaised[_campaignId] += netAmount;
        // Detect first-time donor TRƯỚC khi cộng dồn — tiết kiệm 1 SSTORE so với
        // giữ mapping _hasDonatedOnce riêng.
        if (donorContributions[_campaignId][_donor] == 0) {
            uniqueDonors[_campaignId] += 1;
        }
        donorContributions[_campaignId][_donor] += netAmount;

        // -- B) Phát hành Soulbound Badge --
        totalBadges += 1;
        uint256 newTokenId = totalBadges;
        badgeCampaign[newTokenId] = _campaignId;
        badgeAmount[newTokenId] = netAmount;
        _safeMint(_donor, newTokenId);

        emit BadgeMinted(_donor, newTokenId, _campaignId, netAmount);
        emit DonationRecorded(_campaignId, _donor, _multisigAddress, netAmount, fee, newTokenId);
    }

    // -------------------------------------------
    // 11. Luồng 3 — Đề xuất & duyệt giải ngân (multisig 3/3)
    // -------------------------------------------
    function proposeDisbursement(uint256 _campaignId, string memory _ipfsCid) external {
        Campaign storage c = _campaigns[_campaignId];
        require(c.organization != address(0), "Chien dich khong ton tai");
        require(!c.isDisbursed, "Da giai ngan");
        require(
            msg.sender == c.organization ||
            msg.sender == adminWallet ||
            msg.sender == supervisorWallet,
            "Khong co quyen"
        );

        c.ipfsCid = _ipfsCid;
        emit DisbursementProposed(_campaignId, _ipfsCid);
    }

    function approveDisbursement(uint256 _campaignId) external {
        Campaign storage c = _campaigns[_campaignId];
        require(c.organization != address(0), "Chien dich khong ton tai");
        require(!c.isDisbursed, "Da giai ngan");
        require(
            msg.sender == c.organization ||
            msg.sender == adminWallet ||
            msg.sender == supervisorWallet,
            "Khong co quyen"
        );
        require(!c.hasApproved[msg.sender], "Vi nay da ky roi");

        c.hasApproved[msg.sender] = true;
        c.approvals++;

        emit DisbursementApproved(_campaignId, msg.sender);

        if (c.approvals >= 3) {
            _executeDisbursement(_campaignId);
        }
    }

    /// @dev Chốt sổ giải ngân. Token VNDT ở multisig được xử lý off-chain (multisig
    /// owners tự quyết burn / chuyển ra giữ làm record). Không tự động burn để tránh
    /// xung đột với governance của multisig.
    function _executeDisbursement(uint256 _campaignId) internal {
        Campaign storage c = _campaigns[_campaignId];
        c.isDisbursed = true;
        emit DisbursedAndBurned(_campaignId, c.currentAmount, c.ipfsCid);
    }

    // -------------------------------------------
    // 12. View helpers
    // -------------------------------------------
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
        )
    {
        Campaign storage c = _campaigns[_campaignId];
        return (c.organization, c.multisigVault, c.currentAmount, c.isDisbursed, c.ipfsCid, c.approvals);
    }

    function hasApproved(uint256 _campaignId, address approver) external view returns (bool) {
        return _campaigns[_campaignId].hasApproved[approver];
    }

    function getTokenAddress() external view returns (address) {
        return address(vndt);
    }

    // -------------------------------------------
    // 13. SOULBOUND LOGIC — khoá chuyển nhượng
    // -------------------------------------------
    /**
     * @dev OpenZeppelin v5 thay thế _beforeTokenTransfer bằng _update. Chặn mọi
     *      chuyển nhượng (from != 0 && to != 0) → SBT chỉ có thể mint (from==0)
     *      hoặc burn (to==0). Người dùng KHÔNG thể transfer/sell huy hiệu.
     */
    function _update(address to, uint256 tokenId, address auth)
        internal
        override
        returns (address)
    {
        address from = _ownerOf(tokenId);
        if (from != address(0) && to != address(0)) {
            revert("SBT: khong the chuyen nhuong huy hieu");
        }
        return super._update(to, tokenId, auth);
    }

    /// @dev Chặn cả approve + setApprovalForAll (không cần thiết với SBT).
    function approve(address, uint256) public pure override {
        revert("SBT: approve bi vo hieu hoa");
    }

    function setApprovalForAll(address, bool) public pure override {
        revert("SBT: setApprovalForAll bi vo hieu hoa");
    }

    // -------------------------------------------
    // 14. Metadata
    // -------------------------------------------
    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        require(_ownerOf(tokenId) != address(0), "DCP: token khong ton tai");
        string memory custom = _badgeURI[tokenId];
        if (bytes(custom).length > 0) {
            return custom;
        }
        return super.tokenURI(tokenId);
    }

    function _baseURI() internal view override returns (string memory) {
        return _baseURIStorage;
    }
}
