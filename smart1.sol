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
    /// @notice Địa chỉ contract DCPManager (smart2.sol) — duy nhất được phép mint/burn.
    address public manager;

    event ManagerUpdated(address indexed oldManager, address indexed newManager);

    /// @dev Khoá hàm chỉ cho phép smart2 (manager) gọi.
    modifier onlyManager() {
        require(msg.sender == manager, "VNDT: chi co DCPManager moi duoc goi");
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

    /// @notice Đúc token. Chỉ DCPManager gọi được (thông qua recordDonation).
    function mint(address to, uint256 amount) external onlyManager {
        _mint(to, amount);
    }

    /// @notice Đốt token. Chỉ DCPManager gọi được (giữ lại cho logic tương lai).
    function burn(address from, uint256 amount) external onlyManager {
        _burn(from, amount);
    }
}
