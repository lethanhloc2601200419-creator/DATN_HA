// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

// ==========================================
// 1. CONTRACT TOKEN VNDT (Tỉ lệ 1:1 với VNĐ)
// ==========================================
contract VNDT is ERC20, Ownable {
    // Truyền msg.sender làm owner khởi tạo cho thư viện Ownable
    constructor() ERC20("VND Token", "VNDT") Ownable(msg.sender) {}

    // Chỉ Admin (Contract quản lý) mới có quyền gọi hàm đúc/đốt token
    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    function burn(address from, uint256 amount) external onlyOwner {
        _burn(from, amount);
    }
}

// ==========================================
// 2. CONTRACT QUẢN LÝ DỰ ÁN & GIẢI NGÂN (DCPManager)
// ==========================================
contract DCPManager is Ownable {
    VNDT public token;

    address public supervisorWallet; // Cơ quan giám sát
    address public treasuryWallet;   // Quỹ duy trì hệ thống (nhận phí)
    address public adminWallet;      // Backend Django (Ví gọi lệnh)

    // [ĐÃ SỬA]: Chuyển từ "constant" (cố định 3) sang biến linh hoạt, mặc định là 0%
    uint256 public platformFee = 0;

    struct Campaign {
        address organization;
        uint256 currentAmount;
        bool isDisbursed;
        string ipfsCid;
        uint8 approvals;
        mapping(address => bool) hasApproved;
    }

    mapping(uint256 => Campaign) public campaigns;
    // [ĐÃ SỬA]: campaignCount giờ chỉ là counter thống kê, KHÔNG dùng để sinh ID nữa.
    // Backend Django truyền thẳng Campaign.id (Postgres PK) vào createCampaign để
    // on-chain ID khớp 100% với DB, tránh phải mapping ngược qua event.
    uint256 public campaignCount;

    // Lưu trữ quyền lực Vote của từng người dùng cho từng dự án (Quadratic Funding Data)
    mapping(uint256 => mapping(address => uint256)) public donorContributions;

    // Các Event để Webhook Django lắng nghe và đồng bộ Database
    event CampaignCreated(uint256 indexed campaignId, address organization);
    event DonationRecorded(uint256 indexed campaignId, address indexed donor, uint256 netAmount, uint256 fee);
    event DisbursementProposed(uint256 indexed campaignId, string ipfsCid);
    event DisbursementApproved(uint256 indexed campaignId, address approver);
    event DisbursedAndBurned(uint256 indexed campaignId, uint256 amountBurned, string ipfsCid);

    // Khi Deploy, ông cần truyền vào 2 địa chỉ ví: 1 của Giám sát, 1 của Quỹ nền tảng
    constructor(address _supervisor, address _treasury) Ownable(msg.sender) {
        token = new VNDT(); // Tự động đúc contract VNDT ngay khi khởi tạo
        adminWallet = msg.sender;
        supervisorWallet = _supervisor;
        treasuryWallet = _treasury;
    }

    // Lấy địa chỉ contract của Token VNDT
    function getTokenAddress() external view returns (address) {
        return address(token);
    }

    // [THÊM MỚI]: Hàm để cấu hình phí linh hoạt. Sau này ông thích thu phí thì gọi hàm này.
    function setPlatformFee(uint256 _fee) external onlyOwner {
        require(_fee <= 10, "Phi khong duoc vuot qua 10%");
        platformFee = _fee;
    }

    // ------------------------------------------
    // LUỒNG 1: TẠO DỰ ÁN
    // [ĐÃ SỬA]: Nhận trực tiếp _campaignId từ backend (Django Campaign.id)
    // → on-chain ID = Django PK, không cần parse event để map ngược.
    // ------------------------------------------
    function createCampaign(uint256 _campaignId, address _organization) external onlyOwner {
        require(_campaignId > 0, "Campaign ID phai > 0");
        require(_organization != address(0), "Dia chi to chuc khong hop le");
        // Dùng organization khác address(0) làm cờ tồn tại, tránh tạo trùng.
        require(campaigns[_campaignId].organization == address(0), "Chien dich da ton tai");

        Campaign storage c = campaigns[_campaignId];
        c.organization = _organization;
        campaignCount++; // chỉ tăng counter thống kê
        emit CampaignCreated(_campaignId, _organization);
    }

    // ------------------------------------------
    // LUỒNG 2: NGƯỜI DÙNG NẠP VNĐ -> ĐÚC TOKEN
    // Backend gọi hàm này khi PayOS báo nhận được tiền VNĐ
    // ------------------------------------------
    function recordDonation(uint256 _campaignId, address _donor, uint256 _fiatAmount) external onlyOwner {
        // [ĐÃ SỬA]: Check tồn tại qua organization != address(0) thay vì so với campaignCount
        // (vì _campaignId giờ là Django PK, không còn tuần tự).
        require(campaigns[_campaignId].organization != address(0), "Chien dich khong ton tai");
        require(!campaigns[_campaignId].isDisbursed, "Chien dich da giai ngan");

        // [ĐÃ SỬA]: Tính toán phí dựa trên biến platformFee (đang là 0)
        uint256 fee = 0;
        uint256 netAmount = _fiatAmount;

        if (platformFee > 0) {
            fee = (_fiatAmount * platformFee) / 100;
            netAmount = _fiatAmount - fee;
            token.mint(treasuryWallet, fee); // Đúc phần phí đẩy về quỹ
        }

        // Đúc tiền thực nhận và lưu trữ tại Contract này (đóng vai trò như kho bạc)
        token.mint(address(this), netAmount);

        // Ghi nhận số dư cho dự án & quyền lực vote cho người dùng
        campaigns[_campaignId].currentAmount += netAmount;
        donorContributions[_campaignId][_donor] += netAmount;

        emit DonationRecorded(_campaignId, _donor, netAmount, fee);
    }

    // ------------------------------------------
    // LUỒNG 3: MINH BẠCH & GIẢI NGÂN (Multisig)
    // ------------------------------------------

    // Tổ chức tải hóa đơn lên IPFS và đề xuất giải ngân
    function proposeDisbursement(uint256 _campaignId, string memory _ipfsCid) external {
        Campaign storage c = campaigns[_campaignId];
        require(c.organization != address(0), "Chien dich khong ton tai");
        require(msg.sender == c.organization || msg.sender == adminWallet || msg.sender == supervisorWallet, "Khong co quyen");
        require(!c.isDisbursed, "Da giai ngan");

        c.ipfsCid = _ipfsCid;
        emit DisbursementProposed(_campaignId, _ipfsCid);
    }

    // Ký duyệt giải ngân (Cần 3 chữ ký)
    function approveDisbursement(uint256 _campaignId) external {
        Campaign storage c = campaigns[_campaignId];
        require(c.organization != address(0), "Chien dich khong ton tai");
        require(!c.isDisbursed, "Da giai ngan");
        require(msg.sender == c.organization || msg.sender == adminWallet || msg.sender == supervisorWallet, "Khong co quyen");
        require(!c.hasApproved[msg.sender], "Vi nay da ky roi");

        c.hasApproved[msg.sender] = true;
        c.approvals++;

        emit DisbursementApproved(_campaignId, msg.sender);

        // Nếu đủ 3 bên (Tổ chức, Admin, Giám sát) cùng gật đầu -> Kích hoạt giải ngân
        if (c.approvals >= 3) {
            _executeDisbursement(_campaignId);
        }
    }

    // Nội bộ tự động đốt token và chốt sổ
    function _executeDisbursement(uint256 _campaignId) internal {
        Campaign storage c = campaigns[_campaignId];
        c.isDisbursed = true;
        uint256 amountToBurn = c.currentAmount;

        // Đốt lượng token trong kho bạc tương ứng để cân bằng với việc tiền VNĐ sẽ được xả từ ngân hàng ra
        token.burn(address(this), amountToBurn);

        // Bắn event để Django biết lệnh đốt thành công -> Gọi API ngân hàng chuyển tiền thật
        emit DisbursedAndBurned(_campaignId, amountToBurn, c.ipfsCid);
    }
}
