// SPDX-License-Identifier: MIT
pragma solidity ^0.8.18;

/**
 * @title CharityTransparentPlatform (v2 - Async Flow)
 * @dev
 *  Luồng mới:
 *    1) User thanh toán qua VNPay (KHÔNG cần MetaMask).
 *    2) Backend gọi recordBankDonation() để ghi sao kê NH lên blockchain (minh bạch).
 *    3) Backend (ví Admin) gọi donateOnBehalf() để nạp ETH tương ứng thay user
 *       → ETH đi thẳng từ ví Admin vào contract của campaign.
 *    4) Backend gọi recordGasCost() để ghi nhận phí gas A+B đã chi
 *       (để lúc giải ngân contract biết trừ đúng số tiền).
 *    5) Khi đủ điều kiện + vote, admin gọi executeDisbursement():
 *       available = totalFund - totalGasCost - totalDisbursed - totalAdminRecovered
 *       ETH chuyển thẳng từ contract → ví tổ chức (1 lần duy nhất).
 *    6) Nếu gas C dự trù còn dư, admin có thể withdrawGasRecovery().
 */
contract CharityTransparentPlatform {
    address public admin;

    struct Campaign {
        address payable organizationAddress;
        string organizationName;
        uint256 totalFund;           // Tổng ETH đã nạp cho campaign (donate + donateOnBehalf)
        uint256 totalGasCost;        // Tổng phí gas admin đã chi (gas A + B + ...) - trừ khi giải ngân
        uint256 totalDisbursed;      // Đã giải ngân cho tổ chức
        uint256 totalAdminRecovered; // Admin đã thu hồi gas dự trù còn dư
        bool isActive;
    }

    mapping(uint256 => Campaign) public campaigns;

    // ===== EVENTS =====
    event CampaignCreated(uint256 indexed cid, address orgAddress, string orgName);

    // Giao dịch A: ghi sao kê NH (chỉ emit event, không lưu storage để tiết kiệm gas)
    event BankDonationRecorded(
        uint256 indexed cid,
        address indexed donorAddress,   // ví user nếu có, hoặc address(0)
        string donorName,
        uint256 amountVND,
        string vnpayRef,
        uint256 timestamp
    );

    // Giao dịch B: admin nạp ETH thay user (onBehalf=true), hoặc user tự ký donate (onBehalf=false)
    event Donated(
        uint256 indexed cid,
        address indexed donor,
        uint256 amount,
        bool onBehalf
    );

    // Record gas A/B đã chi để trừ khi giải ngân
    event GasCostRecorded(uint256 indexed cid, uint256 amount, string reason);

    event Disbursed(uint256 indexed cid, uint256 amount, address recipient);
    event GasRecovered(uint256 indexed cid, uint256 amount);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Error: Chi Admin moi co quyen");
        _;
    }

    constructor() {
        admin = msg.sender;
    }

    // =====================================================
    // 1. INIT CAMPAIGN
    // =====================================================
    function initCampaign(
        uint256 _cid,
        string memory _orgName,
        address payable _orgAddress
    ) public {
        require(!campaigns[_cid].isActive, "Error: Chien dich da ton tai");
        require(_orgAddress != address(0), "Error: Dia chi vi khong hop le");

        Campaign storage c = campaigns[_cid];
        c.organizationAddress = _orgAddress;
        c.organizationName = _orgName;
        c.isActive = true;

        emit CampaignCreated(_cid, _orgAddress, _orgName);
    }

    // =====================================================
    // 2. GIAO DỊCH A: GHI SAO KÊ NGÂN HÀNG LÊN BLOCKCHAIN
    //    Chỉ emit event (không lưu storage) -> rẻ gas.
    //    Hash giao dịch này hiện trên trang cảm ơn -> user click Etherscan verify.
    // =====================================================
    function recordBankDonation(
        uint256 _cid,
        address _donorAddress,
        string memory _donorName,
        uint256 _amountVND,
        string memory _vnpayRef,
        uint256 _timestamp
    ) public onlyAdmin {
        require(campaigns[_cid].isActive, "Error: Chien dich da dong hoac khong ton tai");
        require(_amountVND > 0, "Error: So tien VND phai > 0");

        emit BankDonationRecorded(
            _cid,
            _donorAddress,
            _donorName,
            _amountVND,
            _vnpayRef,
            _timestamp
        );
    }

    // =====================================================
    // 3. GIAO DỊCH B: ADMIN NẠP ETH THAY USER
    //    ETH đi từ ví Admin (msg.sender) -> contract (msg.value).
    //    Ghi nhận là "user X đã ủng hộ" qua event.
    // =====================================================
    function donateOnBehalf(uint256 _cid, address _donorAddress) public payable onlyAdmin {
        Campaign storage c = campaigns[_cid];
        require(c.isActive, "Error: Chien dich da dong hoac khong ton tai");
        require(msg.value > 0, "Error: So tien ung ho phai lon hon 0");

        c.totalFund += msg.value;
        emit Donated(_cid, _donorAddress, msg.value, true);
    }

    // =====================================================
    // 4. GHI NHẬN PHÍ GAS ĐÃ CHI (để trừ khi giải ngân)
    //    _reason: "bank_record" (gas A) / "donate_onbehalf" (gas B) / "reserve_disbursement" (gas C)
    //    _amount: tính bằng wei (quy đổi từ VND sang wei theo tỉ giá ETH hiện tại)
    // =====================================================
    function recordGasCost(
        uint256 _cid,
        uint256 _amount,
        string memory _reason
    ) public onlyAdmin {
        Campaign storage c = campaigns[_cid];
        require(c.isActive, "Error: Chien dich da dong hoac khong ton tai");
        require(_amount > 0, "Error: Amount phai > 0");

        c.totalGasCost += _amount;
        emit GasCostRecorded(_cid, _amount, _reason);
    }

    // =====================================================
    // 5. FALLBACK: USER TỰ KÝ ỦNG HỘ (nếu có MetaMask)
    //    Giữ lại cho trường hợp dùng cao cấp. Luồng chính là donateOnBehalf.
    // =====================================================
    function donate(uint256 _cid) public payable {
        Campaign storage c = campaigns[_cid];
        require(c.isActive, "Error: Chien dich da dong hoac khong ton tai");
        require(msg.value > 0, "Error: So tien ung ho phai lon hon 0");

        c.totalFund += msg.value;
        emit Donated(_cid, msg.sender, msg.value, false);
    }

    // =====================================================
    // 6. GIẢI NGÂN
    //    available = totalFund - totalGasCost - totalDisbursed - totalAdminRecovered
    //    ETH chuyển thẳng từ contract -> ví tổ chức.
    // =====================================================
    function executeDisbursement(uint256 _cid, uint256 _amount) public onlyAdmin {
        Campaign storage c = campaigns[_cid];
        require(_amount > 0, "Error: Amount phai > 0");
        uint256 availableToWithdraw = getAvailableBalance(_cid);
        require(_amount <= availableToWithdraw, "Error: So tien vuot qua han muc sau khi tru phi Gas");

        c.totalDisbursed += _amount;
        (bool success, ) = c.organizationAddress.call{value: _amount}("");
        require(success, "Error: Giai ngan cho to chuc that bai");

        emit Disbursed(_cid, _amount, c.organizationAddress);
    }

    // =====================================================
    // 7. ADMIN THU HỒI GAS DỰ TRÙ CÒN DƯ
    //    Sau khi giải ngân, contract vẫn giữ phần ETH tương ứng với totalGasCost
    //    (vì recordGasCost chỉ tăng counter, không chuyển ETH ra).
    //    Admin gọi hàm này để reclaim lại số ETH đó (bù cho gas đã chi ngoài đời thực).
    // =====================================================
    function withdrawGasRecovery(uint256 _cid, uint256 _amount) public onlyAdmin {
        Campaign storage c = campaigns[_cid];
        require(_amount > 0, "Error: Amount phai > 0");
        uint256 remaining = c.totalFund - c.totalDisbursed - c.totalAdminRecovered;
        require(_amount <= remaining, "Error: Vuot qua so du kha dung");
        require(address(this).balance >= _amount, "Error: So du hop dong khong du de hoan phi");

        c.totalAdminRecovered += _amount;
        (bool success, ) = payable(admin).call{value: _amount}("");
        require(success, "Error: Thu hoi phi Gas that bai");

        emit GasRecovered(_cid, _amount);
    }

    // =====================================================
    // 8. VIEW HELPERS
    // =====================================================
    function getAvailableBalance(uint256 _cid) public view returns (uint256) {
        Campaign storage c = campaigns[_cid];
        uint256 cost = c.totalGasCost + c.totalDisbursed + c.totalAdminRecovered;
        if (c.totalFund <= cost) return 0;
        return c.totalFund - cost;
    }

    function getCampaignStats(uint256 _cid) public view returns (
        uint256 totalFund,
        uint256 totalGasCost,
        uint256 totalDisbursed,
        uint256 totalAdminRecovered,
        uint256 available,
        bool isActive
    ) {
        Campaign storage c = campaigns[_cid];
        totalFund = c.totalFund;
        totalGasCost = c.totalGasCost;
        totalDisbursed = c.totalDisbursed;
        totalAdminRecovered = c.totalAdminRecovered;
        available = getAvailableBalance(_cid);
        isActive = c.isActive;
    }

    receive() external payable {}
}
