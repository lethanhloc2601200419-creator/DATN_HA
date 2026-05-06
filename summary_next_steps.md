# Summary For Next Account

## Goal
Chuyen he thong sang luong moi: VNPay chi ghi nhan giao dich on-chain, khong cap ETH cho user, khong can MetaMask user. Giai ngan chi 1 lan cho to chuc, admin duoc hoan phi gas (recordDonation + executeDisbursement + gas tx thu hoi).

## Smart Contract
File: `smart.sol` da sua theo luong moi:
- `initCampaign`
- `recordDonation`
- `executeDisbursement`
- `withdrawGasRecovery`

Sau khi deploy, cap nhat `SMART_CONTRACT_ADDRESS` + `SMART_CONTRACT_ABI` trong `doantn/settings.py`.

## Can sua trong code

1) `client/blockchain.py`
   - Bo/khong dung: `sendEthToUser`, `donate`, `depositExchangePool`
   - Them: `record_donation`, `execute_disbursement`, `withdraw_gas_recovery`

2) `client/views.py`
   - VNPay return: chi goi `recordDonation`
   - Bo tinh E/G, bo MetaMask user
   - Khong hien nut xac nhan MetaMask

3) UI
   - `client/templates/client/ungho.html`: bo ket noi MetaMask
   - `client/templates/client/payment_success.html`: bo nut xac nhan MetaMask

4) Giai ngan
   - `admin_panel/disbursement_utils.py`: 
     - executeDisbursement
     - sau do withdrawGasRecovery
   - tinh `net_available` = tong quyen gop - (gas ghi donate + gas disbursement + gas thu hoi)

5) Quan ly giao dien
   - `admin_panel/templates/admin_panel/quanly_giaingan.html`: hien so du kha dung sau khi tru gas

## Prompt cho acc moi
Xem trong chat cu, hoac dung prompt sau:
```
Ban la Codex. He thong Django /home/locwara/Ha/doantn.
Toi da doi chien luoc: VNPay chi ghi nhan giao dich on-chain (recordDonation), khong cap ETH user, khong can MetaMask user.
Giai ngan: executeDisbursement 1 lan.
Admin duoc hoan phi gas (recordDonation + executeDisbursement + gas tx thu hoi).
Smart.sol da sua theo huong nay.
Sau khi toi gui smart address + ABI, hay cap nhat:
1) doantn/settings.py
2) client/blockchain.py (recordDonation, executeDisbursement, withdrawGasRecovery)
3) client/views.py (VNPay return chi goi recordDonation)
4) UI bo MetaMask user
5) disbursement_utils.py (executeDisbursement + withdrawGasRecovery; tinh net_available tru gas)
```
