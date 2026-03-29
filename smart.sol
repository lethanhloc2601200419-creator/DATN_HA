// SPDX-License-Identifier: MIT
pragma solidity ^0.8.18;

/**
 * @title CharityTransparentPlatform
 * @dev Pool ETH chung toàn hệ thống (không theo campaign)
 */
contract CharityTransparentPlatform {
    address public admin;

    uint256 public exchangePool; // Pool ETH chung

    struct Campaign {
        address payable organizationAddress;
        string organizationName;
        uint256 totalFund;
        uint256 totalGasSubsidized;
        uint256 totalDisbursed;
        bool isActive;
    }

    mapping(uint256 => Campaign) public campaigns;

    event CampaignCreated(uint256 indexed cid, address orgAddress, string orgName);
    event GasSubsidized(uint256 indexed cid, address user, uint256 amountG);
    event Donated(uint256 indexed cid, address indexed donor, uint256 amount);
    event Disbursed(uint256 indexed cid, uint256 amount, address recipient);s
    event GasRecovered(uint256 indexed cid, uint256 amount);
    event ExchangePoolDeposited(uint256 amount, uint256 newBalance);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Error: Chi Admin moi co quyen");
        _;
    }

    constructor() {
        admin = msg.sender;
    }

    function initCampaign(uint256 _cid, string memory _orgName, address payable _orgAddress) public {
        require(!campaigns[_cid].isActive, "Error: Chien dich da ton tai");
        require(_orgAddress != address(0), "Error: Dia chi vi khong hop le");

        Campaign storage c = campaigns[_cid];
        c.organizationAddress = _orgAddress;
        c.organizationName = _orgName;
        c.isActive = true;

        emit CampaignCreated(_cid, _orgAddress, _orgName);
    }

    /**
     * @dev Admin nạp ETH vào Pool chung.
     */
    function depositExchangePool() public payable onlyAdmin {
        require(msg.value > 0, "Error: So tien nap phai > 0");
        exchangePool += msg.value;
        emit ExchangePoolDeposited(msg.value, exchangePool);
    }

    /**
     * @dev Backend gọi sau VNPay thành công.
     * Chuyển ETH (E + G) từ Pool chung sang ví User.
     */
    function sendEthToUser(
        uint256 _cid,
        address payable _user,
        uint256 _amountE,
        uint256 _amountG
    ) public onlyAdmin {
        Campaign storage c = campaigns[_cid];
        require(c.isActive, "Error: Chien dich da dong hoac khong ton tai");

        uint256 totalNeeded = _amountE + _amountG;
        require(exchangePool >= totalNeeded, "Error: Pool khong du ETH de doi");

        exchangePool -= totalNeeded;
        c.totalGasSubsidized += _amountG;

        (bool success, ) = _user.call{value: totalNeeded}("");
        require(success, "Error: Chuyen ETH cho User that bai");

        emit GasSubsidized(_cid, _user, _amountG);
    }

    function donate(uint256 _cid) public payable {
        Campaign storage c = campaigns[_cid];
        require(c.isActive, "Error: Chien dich da dong hoac khong ton tai");
        require(msg.value > 0, "Error: So tien ung ho phai lon hon 0");

        c.totalFund += msg.value;
        emit Donated(_cid, msg.sender, msg.value);
    }

    function executeDisbursement(uint256 _cid, uint256 _amount) public onlyAdmin {
        Campaign storage c = campaigns[_cid];
        uint256 availableToWithdraw = c.totalFund - c.totalGasSubsidized - c.totalDisbursed;
        require(_amount <= availableToWithdraw, "Error: So tien vuot qua han muc sau khi tru phi Gas");

        c.totalDisbursed += _amount;
        (bool success, ) = c.organizationAddress.call{value: _amount}("");
        require(success, "Error: Giai ngan cho to chuc that bai");

        emit Disbursed(_cid, _amount, c.organizationAddress);
    }

    function withdrawGasRecovery(uint256 _cid) public onlyAdmin {
        Campaign storage c = campaigns[_cid];
        uint256 amountToRecover = c.totalGasSubsidized;
        require(address(this).balance >= amountToRecover, "Error: So du hop dong khong du de hoan phi");

        c.totalGasSubsidized = 0;
        (bool success, ) = payable(admin).call{value: amountToRecover}("");
        require(success, "Error: Thu hoi phi Gas that bai");

        emit GasRecovered(_cid, amountToRecover);
    }

    function getAvailableBalance(uint256 _cid) public view returns (uint256) {
        Campaign storage c = campaigns[_cid];
        uint256 cost = c.totalGasSubsidized + c.totalDisbursed;
        if (c.totalFund <= cost) return 0;
        return c.totalFund - cost;
    }

    receive() external payable {}
}
