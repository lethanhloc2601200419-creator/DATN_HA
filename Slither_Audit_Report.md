## 6. Kiểm thử và đánh giá bảo mật Hợp đồng thông minh (Smart Contract)

### 6.1. Mục đích và sự cần thiết của việc kiểm thử
Trong kiến trúc của hệ thống, Hợp đồng thông minh (Smart Contract) đóng vai trò cốt lõi trong việc quản lý token (VNDT), lưu trữ bằng chứng giao dịch và thực hiện giải ngân. Do tính chất "không thể thay đổi" (immutable) sau khi đã triển khai lên Blockchain, bất kỳ lỗ hổng bảo mật nào trong mã nguồn cũng có thể dẫn đến việc mất mát tài sản kỹ thuật số vĩnh viễn và phá vỡ logic nghiệp vụ của hệ thống. 
Do đó, việc kiểm thử tĩnh (Static Analysis) để rà soát tự động các lỗ hổng bảo mật phổ biến (như Reentrancy, Access Control, Overflow...) trước khi triển khai (deploy) là bước bắt buộc và cực kỳ quan trọng.

### 6.2. Công cụ kiểm thử
Đồ án sử dụng **Slither** – một framework phân tích tĩnh mã nguồn Solidity mạnh mẽ được phát triển bởi Trail of Bits. Slither có khả năng quét mã nguồn và phát hiện các lỗ hổng dựa trên hơn 100 bộ quy tắc (detectors) đã được định nghĩa sẵn, giúp phát hiện sớm các rủi ro bảo mật tiềm ẩn.

### 6.3. Quy trình thực hiện
Quá trình đánh giá được thực hiện thông qua môi trường ảo (Virtual Environment) để cài đặt công cụ và quét các tệp mã nguồn. Các lệnh thực thi cơ bản:
```bash
# 1. Cài đặt thư viện phụ thuộc của dự án
npm install @openzeppelin/contracts

# 2. Cài đặt Slither 
pip install slither-analyzer

# 3. Chạy lệnh phân tích cho từng Hợp đồng
slither smart1.sol --solc-remaps "@openzeppelin/=node_modules/@openzeppelin/"
slither smart2.sol --solc-remaps "@openzeppelin/=node_modules/@openzeppelin/"
slither smart3.sol --solc-remaps "@openzeppelin/=node_modules/@openzeppelin/"
```

### 6.4. Kết quả phân tích và Đánh giá rủi ro

Dưới đây là kết quả phân tích 3 Hợp đồng thông minh cốt lõi của hệ thống, bao gồm cảnh báo do Slither phát hiện và phương án giải trình (tại sao hệ thống vẫn an toàn).

#### 6.4.1. Hợp đồng VNDT Token (`smart1.sol`)
Hợp đồng chịu trách nhiệm khởi tạo (mint) và đốt (burn) Token VNDT với cơ chế cấp quyền quản lý chặt chẽ.

| Loại cảnh báo / Dẫn chứng (Detector) | Mô tả chi tiết lỗi phát hiện | Mức độ rủi ro | Đánh giá ảnh hưởng và Giải trình |
| :--- | :--- | :---: | :--- |
| **Missing Zero-Address Validation**<br/>*(Detector: missing-zero-check)*<br/>`VNDT.setBurner(address)._burner` lacks a zero-check | Hàm `setBurner` không kiểm tra giá trị địa chỉ đầu vào có phải là địa chỉ rỗng (`0x0...`) hay không. | Thấp | **Ảnh hưởng:** Nếu truyền nhầm địa chỉ `0x0`, chức năng giải ngân (burn) có thể bị vô hiệu hóa.<br/>**Giải trình:** Hàm này được bảo vệ bởi modifier `onlyOwner` (chỉ quản trị viên cấp cao nhất mới gọi được). Do đó, rủi ro tấn công từ bên ngoài là 0. Quản trị viên chỉ cần thao tác cẩn trọng khi cấp quyền. |
| **Naming Convention & Pragma Version**<br/>*(Detector: naming-convention)* | Các tham số truyền vào như `_manager`, `_burner` không tuân thủ chuẩn đặt tên mixedCase. Sử dụng nhiều phiên bản compiler khác nhau. | Không có | **Ảnh hưởng:** Không ảnh hưởng đến logic và bảo mật.<br/>**Giải trình:** Đây chỉ là cảnh báo về chuẩn viết code (Best Practices). Hệ thống sử dụng kết hợp các thư viện OpenZeppelin có phiên bản pragma cũ/mới khác nhau. |

#### 6.4.2. Hợp đồng DCPManager (`smart2.sol`)
Hợp đồng chịu trách nhiệm đề xuất chiến dịch, ghi nhận quyên góp và cơ chế Multisig On-chain.

| Loại cảnh báo / Dẫn chứng (Detector) | Mô tả chi tiết lỗi phát hiện | Mức độ rủi ro | Đánh giá ảnh hưởng và Giải trình |
| :--- | :--- | :---: | :--- |
| **Immutable States**<br/>*(Detector: immutable-states)*<br/>`DCPManager.adminWallet` should be immutable | Biến `adminWallet` được khởi tạo một lần duy nhất trong hàm khởi tạo (constructor) nhưng không được khai báo từ khóa `immutable`. | Tối ưu hóa | **Ảnh hưởng:** Gây tiêu tốn thêm một lượng nhỏ phí Gas khi đọc biến này.<br/>**Giải trình:** Khai báo biến thành `immutable` chỉ có tác dụng tiết kiệm chi phí Gas (Gas Optimization), hoàn toàn không phải là lỗ hổng bảo mật. Sẽ được tối ưu ở phiên bản sau. |
| **Too Many Digits**<br/>*(Detector: too-many-digits)* | Các hàm thư viện toán học của OpenZeppelin (`Bytes.sol`, `Math.sol`) sử dụng các hằng số nhị phân/hexa quá dài. | Không có | **Ảnh hưởng:** Không ảnh hưởng đến hệ thống.<br/>**Giải trình:** Đây là mã nguồn tối ưu toán học cấp thấp do OpenZeppelin viết. Không cần thiết và không nên sửa đổi. |

#### 6.4.3. Hợp đồng DisbursementExecutor (`smart3.sol`)
Hợp đồng quản lý luồng giải ngân đa chữ ký ngoại tuyến (EIP-712) Layer-2.

| Loại cảnh báo / Dẫn chứng (Detector) | Mô tả chi tiết lỗi phát hiện | Mức độ rủi ro | Đánh giá ảnh hưởng và Giải trình |
| :--- | :--- | :---: | :--- |
| **Reentrancy (CEI Pattern Violation)**<br/>*(Detector: reentrancy-no-eth)*<br/>`vndt.burnWithBankTx(...)` followed by `p.stage = Stage.Finalized` | Hàm `finalizeBurnWithBankTx` gọi một hàm ngoại vi trước khi cập nhật biến trạng thái (`p.stage`), vi phạm nguyên tắc Checks-Effects-Interactions (CEI). | Thấp | **Ảnh hưởng:** Lỗ hổng Reentrancy cổ điển (rút tiền liên tục trước khi cập nhật số dư).<br/>**Giải trình:** Rủi ro chỉ xảy ra khi gọi đến hợp đồng độc hại bên ngoài. Ở đây, hợp đồng ngoại vi là `smart1.sol` (VNDT Token) do chính hệ thống triển khai và kiểm soát tuyệt đối. Việc tấn công Reentrancy không thể xảy ra. Tuy nhiên, nhóm sẽ tuân thủ nguyên tắc CEI trong lần triển khai tới. |
| **Block Timestamp**<br/>*(Detector: timestamp)*<br/>`uses timestamp for comparisons` | Sử dụng biến thời gian của khối (`block.timestamp`) để kiểm tra thời gian hết hạn (deadline) của chữ ký EIP-712. | Thấp | **Ảnh hưởng:** Thợ đào (Validator) có thể thao túng thời gian của khối để đánh lừa hệ thống.<br/>**Giải trình:** Thợ đào chỉ có thể thao túng thời gian sai số từ vài giây đến 1-2 phút. Tuy nhiên, thời hạn chữ ký của hệ thống (deadline) thường được tính bằng hàng giờ hoặc ngày. Do đó, mức sai số nhỏ này không thể được sử dụng để trục lợi hay tấn công hệ thống. |
| **Unused Return Values**<br/>*(Detector: unused-return)*<br/>`ignores return value by dcpManager.getCampaign()` | Hàm lấy thông tin chiến dịch trả về 6 giá trị, nhưng hợp đồng chỉ lấy 2 giá trị cần thiết và bỏ qua 4 giá trị còn lại. | Không có | **Ảnh hưởng:** Giúp tiết kiệm bộ nhớ trên máy ảo EVM.<br/>**Giải trình:** Đây là kỹ thuật lập trình tối ưu hóa. Lược bỏ các biến thừa giúp giảm tải ngăn xếp (Stack), tiết kiệm đáng kể phí Gas giao dịch. |

### 6.5. Kết luận chung
Sau quá trình quét tĩnh tự động với Slither (thực thi trên hơn 100 bộ dò/detectors khác nhau), **Hệ thống Hợp đồng thông minh của đồ án (smart1, smart2, smart3) KHÔNG tồn tại các lỗ hổng bảo mật nghiêm trọng** (như rò rỉ khóa riêng tư, phá vỡ kiểm soát quyền truy cập - Access Control, hay lỗ hổng thất thoát tài sản). 

Hầu hết các cảnh báo được trả về đều thuộc nhóm Tối ưu phí Gas, Best Practices, hoặc các vi phạm tiêu chuẩn (Reentrancy, Timestamp) nhưng trong ngữ cảnh của mô hình hệ thống hiện tại là hoàn toàn an toàn (Unexploitable). Các hợp đồng thông minh đảm bảo đủ độ tin cậy để triển khai lên mạng lưới Blockchain thực tế.
