# 📋 TIẾN ĐỘ TRIỂN KHAI LUỒNG ASYNC MỚI

> **Mục tiêu:** User ủng hộ qua VNPay (không cần MetaMask). Admin wallet tự động thực hiện 2 giao dịch blockchain song song (A: ghi sao kê NH, B: nạp ETH vào contract). Khi giải ngân, trừ tổng gas A+B+C đã cộng dồn.

---

## 🎯 SMART CONTRACT MỚI

- **Địa chỉ:** `0x75e935BA323DdC5f248B9EA206251C6E319396df`
- **Network:** Sepolia
- **Các hàm chính:**
  - `recordBankDonation(cid, donorAddress, donorName, amountVND, vnpayRef, timestamp)` — Giao dịch A
  - `donateOnBehalf(cid, donorAddress) payable` — Giao dịch B (admin nạp ETH thay user)
  - `recordGasCost(cid, amount, reason)` — Ghi nhận gas đã chi
  - `executeDisbursement(cid, amount)` — Giải ngân
  - `withdrawGasRecovery(cid, amount)` — Admin thu hồi gas dự trù dư
  - `getCampaignStats(cid)` — View trả 6 giá trị: totalFund, totalGasCost, totalDisbursed, totalAdminRecovered, available, isActive

---

## 📝 DANH SÁCH CÔNG VIỆC

### Backend - Config

- [x] **[1]** Update `doantn/settings.py`: thay `SMART_CONTRACT_ADDRESS` + `SMART_CONTRACT_ABI` mới ✅

### Backend - Database

- [x] **[2]** Migration `0020_donation_bank_record_gas_vnd_and_more.py` đã apply thành công ✅
  - `bank_record_tx_hash` — Tx hash giao dịch A (recordBankDonation)
  - `donate_onbehalf_tx_hash` — Tx hash giao dịch B (donateOnBehalf)
  - `bank_record_gas_wei`, `bank_record_gas_vnd` — Gas A thực tế
  - `donate_onbehalf_gas_wei`, `donate_onbehalf_gas_vnd` — Gas B thực tế
  - `record_gascost_tx_hash` — Tx hash ghi gas cost lên contract
  - `total_admin_gas_wei`, `total_admin_gas_vnd` — Tổng gas A+B

### Backend - Service Layer

- [x] **[3]** Refactor `client/blockchain.py` ✅
  - Thêm `record_bank_donation()`, `donate_on_behalf()`, `record_gas_cost()`
  - `get_campaign_onchain_stats()` dùng `getCampaignStats()` ABI mới với `total_gas_cost_wei`
  - Backward-compat alias `total_gas_subsidized_wei`
  - Thêm `ZERO_ADDRESS` constant cho user không có MetaMask

- [x] **[4]** Refactor `client/blockchain_processor.py` ✅
  - Pipeline mới: A `recordBankDonation` → B `donateOnBehalf` → C `recordGasCost(gas_A + gas_B)`
  - Xóa logic `sendEthToUser`
  - Lưu đầy đủ các field mới + backward-compat với field cũ

### Backend - Views

- [x] **[5]** Refactor `client/views.py` — `ungho` ✅
  - Bỏ kiểm tra bắt buộc `donor_wallet_address` khi VNPay
  - MetaMask hoàn toàn optional

- [x] **[6]** Refactor `client/views.py` — `vnpay_return` ✅
  - Trả `bank_record_tx_hash`, `donate_onbehalf_tx_hash` vào context (thay `send_eth_tx_hash`)
  - Bỏ context ABI/MetaMask không còn dùng

- [x] **[7]** Refactor `client/views.py` — `api_donation_blockchain_status` ✅
  - Trả về 2 tx hash A + B + `total_admin_gas_vnd`
  - Bỏ `is_user_signed`

### Frontend

- [x] **[8]** Refactor `client/templates/client/payment_success.html` ✅
  - UI polling với 2 giao dịch A + B riêng biệt
  - Bỏ hoàn toàn nút "Ký MetaMask" và ethers.js
  - Link Etherscan cho mỗi tx hash, status pending → confirmed
  - Nút "Retry blockchain" khi failed

- [x] **[9]** Refactor `client/templates/client/ungho.html` ✅
  - MetaMask đưa vào `<details>` (optional)
  - Alert "Không cần MetaMask!" hiển thị rõ ràng

### Backend - Disbursement

- [x] **[10]** Update `admin_panel/disbursement_utils.py` ✅
  - `estimate_gas_per_tx_vnd` bao gồm cả gas A+B trong max calculation

- [x] **[11]** Update `client/views.py` — `chitiet_chiendich` ✅
  - Dùng `total_gas_cost_wei` từ contract (tránh double-count gas DB + on-chain)
  - Fix: chỉ 1 phí dự trù (bỏ `est_recovery_gas_vnd`)
  - `onchain_available_vnd` = totalFund - totalGasCost - totalDisbursed - totalAdminRecovered - est_disbursement

### Validation

- [x] **[12]** Django check pass ✅
- [x] **[13]** Code-reviewer approve (sau 2 vòng review + fix) ✅

---

## 🚀 PHASE 5: NÂNG CẤP TRẢI NGHIỆM & RIÊNG TƯ

- [x] **[14] Thiết kế & Tài liệu:** Tạo file `andanh.md` và lên kế hoạch xử lý Masking dữ liệu. ✅
- [x] **[15] Cập nhật UI Ungho:** Thêm nút gạt "Ủng hộ ẩn danh" vào `ungho.html`. ✅
- [x] **[16] Xử lý Logic Backend:** Refactor hàm `ungho` để nhận diện flag ẩn danh và thực hiện Masking (Name/Email). ✅
- [x] **[17] Tích hợp PayOS:** Cập nhật hàm tạo link thanh toán để gửi thông tin ẩn danh sang PayOS. ✅
- [x] **[18] Kiểm thử & Hoàn thiện:** Test luồng đăng nhập + ẩn danh, kiểm tra hiển thị tại PayOS và Sao kê. ✅

---

## 📊 LUỒNG TỔNG QUAN (ĐÃ TRIỂN KHAI XONG)

```
User thanh toán VNPay (KHÔNG cần MetaMask)
    ↓
Frontend: "✅ Thanh toán thành công" (ngay lập tức)
    ↓
Backend spawn thread nền:
    [A] recordBankDonation(cid, donor, name, amountVND, vnpayRef, ts)
        → Lấy tx_hash A → lưu DB → user thấy hash ngay
        → Wait receipt → lấy gas A thực tế
    [B] donateOnBehalf(cid, donor) payable=amount_e_wei
        → Lấy tx_hash B → lưu DB → user thấy hash ngay
        → Wait receipt → lấy gas B thực tế
    [C] recordGasCost(cid, gas_A + gas_B, "auto_fund_donation_X")
        → Ghi tổng gas lên contract để trừ khi giải ngân
    → blockchain_status = 'confirmed'
    ↓
Frontend polling phát hiện confirmed
    ↓
UI hiện đầy đủ 2 hash Etherscan + gas đã chi
```

---

## 🚀 GIẢI NGÂN (formula mới)

```
net_receivable = totalFund_on_chain
                - totalGasCost_on_chain   (gas A+B đã ghi qua recordGasCost)
                - totalDisbursed          (đã giải ngân trước đó)
                - totalAdminRecovered     (admin đã thu hồi gas dư)
                - est_disbursement_gas    (1 gas dự trù cho lần executeDisbursement sắp tới)
```

Admin vote đủ → `executeDisbursement(cid, amount)` → ETH đi thẳng từ contract → ví tổ chức.
Sau giải ngân, admin có thể gọi `withdrawGasRecovery` để thu hồi phần ETH tương ứng `totalGasCost` + gas C dự trù còn dư.

---

## 💡 LƯU Ý RUNTIME

1. **Chạy backup worker** để đảm bảo donations không bị kẹt khi Django reload:
   ```bash
   python manage.py process_pending_donations --loop --sleep=60
   ```

2. **Admin wallet cần có ETH** trong ví để tự động nạp `donateOnBehalf` — mỗi donation VNPay sẽ tiêu ETH = (amount_VND / ETH_VND_rate) + gas A+B.

3. **Gas 0.1 Gwei + timeout 10 phút** — cho phép mạng Sepolia lúc nào cũng có thể pick up tx low-gas, không fail sớm.

4. **Dead code đã clean:**
   - Removed: `gas_admin_auto_vnd` (dead var), double-count `est_recovery_gas_vnd`
   - Còn giữ (backward compat cho donation cũ): `gas_admin_sendeth_vnd`, `api_confirm_donation`, `_save_gas_fee_to_donation`
