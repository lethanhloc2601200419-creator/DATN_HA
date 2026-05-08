# Project knowledge

This file gives Codebuff context about your project: goals, commands, conventions, and gotchas.

## Quickstart
- Setup: `pip install -r requirements.txt`, cấu hình `.env` (DB + Web3 + PayOS).
- Dev: `python manage.py migrate && python manage.py runserver`
- Test: chưa có unit test tự động.

## Architecture

### Apps
- `admin_panel/` — CMS + toàn bộ quản lý admin (tổ chức, chiến dịch, giải ngân).
- `client/` — UI donor, PayOS Payment, Web3Auth/Biconomy auth, blockchain listener.

### Key directories
- `admin_panel/views.py` — Tất cả view admin, bao gồm V3 2-layer disbursement.
- `admin_panel/signals.py` — auto-sync Campaign → blockchain khi duyệt.
- `admin_panel/blockchain_utils.py` — `sync_single_campaign(campaign_id)`.
- `client/blockchain.py` — `BlockchainService` (smart2 + smart3 + VNDT).
- `client/payos_payout.py` — PayOS Payout adapter (mock, có TODO real integration).
- `smart1.sol` — VNDT ERC20 + `burnWithBankTx` (mới, gate bởi burner role).
- `smart2.sol` — DCPManager (campaign + donate + multisig legacy 3-of-3).
- `smart3.sol` — DisbursementExecutor (EIP-712 multisig + finalizeBurnWithBankTx).

### Data flow
- Donor VND → PayOS Payment → webhook → `recordDonation(campaign, donor, multisig, fiatAmount)` on-chain → VNDT mint vào multisig vault + SBT badge cho donor.
- Giải ngân V3: Phase 1 (proposal + IPFS) → Phase 2 (3 EIP-712 sigs off-chain) → Phase 3a (admin relay on-chain) → Phase 3b (PayOS Payout) → Phase 4 (burn on-chain với bankTxId).

## V3 2-LAYER DISBURSEMENT (GASLESS MULTISIG + PAYOS + BURN)

### Smart contracts mới
- `smart3.sol::DisbursementExecutor`:
  - `recordMultisigApproval(...)`: nhận 3 sigs EIP-712 (org, supervisor, admin) + verify bằng `ecrecover` → emit `MultisigConfirmed`.
  - `finalizeBurnWithBankTx(proposalId, multisigVault, bankTxId)`: gọi VNDT.burnWithBankTx → emit `DisbursementFinalized`.
- `smart1.sol` thêm `burner` role + `burnWithBankTx(from, amount, bankTxId, campaignId, proposalId)`.

### Deployed contracts (Sepolia)
| # | Contract | Address | ABI file |
|---|---|---|---|
| smart1 | VNDT (ERC20 + burnWithBankTx) | `0x05D913ECd54aC20401b096B10d0F4202098B38a4` | `blockchain_assets/vndt_abi.json` |
| smart2 | DCPManager (campaigns/donations) | `0x4F36121cC411c2e6Bea4e4a66C4BE78F3cc048E7` | `blockchain_assets/contract_abi.json` |
| smart3 | DisbursementExecutor (EIP-712 multisig) | `0x725aC680F90Ff7cf723B50aCA1B05e7F4028624c` | `blockchain_assets/smart3_abi.json` |

Defaults nằm trong `doantn/settings.py` và có thể override bằng env vars `CONTRACT_ADDRESS`, `VNDT_TOKEN_ADDRESS`, `SMART3_CONTRACT_ADDRESS`.

### Deploy / re-deploy checklist
1. **Deploy `smart3.sol` bằng CHÍNH ví `settings.WALLET_ADDRESS`** (backend relayer). Vì cả `recordMultisigApproval` và `finalizeBurnWithBankTx` đều là `onlyOwner` — nếu deploy từ ví khác, backend sẽ revert khi gọi. Constructor: `(_vndt=<smart1 addr>, _dcpManager=<smart2 addr>)`.
2. Trên smart1 gọi `setBurner(<smart3 addr>)` để cho phép smart3 burn VNDT của vault.
3. Copy ABI smart3 → `blockchain_assets/smart3_abi.json` (đã có sẵn cho bản deploy hiện tại).
4. Nếu re-deploy, override env `SMART3_CONTRACT_ADDRESS=0x...` (hoặc cập nhật default trong `settings.py`).
5. Requirements: `eth-account>=0.10` (cho `encode_typed_data`).

### EIP-712 domain (khớp với deployed smart3)
- `name`: `"DCP Disbursement"`
- `version`: `"1"`
- `chainId`: từ RPC (`settings.BLOCKCHAIN_PROVIDER_URL`, Sepolia=11155111)
- `verifyingContract`: `SMART3_CONTRACT_ADDRESS`
- Primary type: `Approval(uint256 proposalId,uint256 campaignId,uint256 amount,address recipient,string ipfsCid,uint256 deadline,uint256 nonce,string role)`
- `role` ∈ `{"org", "supervisor", "admin"}`; `nonce` random unique per-signer.

### Webhook → burn data flow (Phase 3b → Phase 4)
1. PayOS gọi `POST /admin/api/v3/payos/payout-webhook/` với `{referenceId=payos_payout_id, bankTxId, status}`.
2. View verify HMAC → set `v3_status='fiat_transferred'`, lưu `bank_tx_id`.
3. `transaction.on_commit` spawn daemon thread `_run_finalize_burn_safe(proposal_id)`.
4. Thread gọi `BlockchainService.finalize_burn_with_bank_tx(proposal_id, multisig_vault, bank_tx_id)` → smart3 gọi VNDT.burnWithBankTx → emit `DisbursementFinalized`.
5. On success: `v3_status='completed_audited'`, lưu `burn_tx_hash`.
6. On failure: log + set `payout_error` (không revert `fiat_transferred` — audit chỉ tracking off-chain).

### Dev: mô phỏng webhook
`POST /admin/api/v3/disbursement/<pk>/simulate-webhook/` (mock mode) sẽ tạo fake PayOS webhook với `bank_tx_id` giả → trigger toàn bộ Phase 4.

### Django models
- `DisbursementProposal` mở rộng: `v3_status`, `multisig_confirmed_tx_hash`, `payos_payout_id`, `bank_tx_id`, `fiat_transferred_at`, `burn_tx_hash`, `signature_deadline`, `payout_error`.
- `DisbursementSignature`: lưu 3 chữ ký EIP-712 (unique per `(proposal, role)`).
- Migration: `0027_v3_disbursement_eip712.py`.

### V3 workflow endpoints (admin_panel/urls.py)
- `GET  /admin/api/v3/disbursement/<pk>/sign-payload/?role=...` → EIP-712 typed-data.
- `POST /admin/api/v3/disbursement/submit-signature/` → FE gửi sig, backend verify + lưu.
- `POST /admin/api/v3/disbursement/<pk>/relay-multisig/` → admin gom 3 sigs → gọi smart3 (1 tx).
- `POST /admin/api/v3/disbursement/<pk>/trigger-payout/` → gọi PayOS Payout (mock).
- `POST /admin/api/v3/payos/payout-webhook/` → PayOS gọi về sau khi bank transfer xong.
- `POST /admin/api/v3/disbursement/<pk>/simulate-webhook/` → [DEV] giả webhook để test burn.

### Frontend
- `admin_panel/static/admin_panel/js/v3-disbursement-sign.js` expose `window.V3Disbursement.signAs(id, role)`, `relayMultisig(id)`, `triggerPayout(id)`, `simulateWebhook(id)`.
- Template `quanly_giaingan.html` cần include script này và thêm buttons — **chưa tự động thêm**; dev tự nối UI.

### V3 status state machine
```
v3_not_started → pending_multisig → ready_to_payout
                → payout_processing → fiat_transferred
                → completed_audited
                (any)   → payout_failed
```

### PayOS Payout
- Hiện tại MOCK (`client/payos_payout.py::PAYOS_PAYOUT_MOCK = True`).
- Real integration: implement `request_payout` + `verify_webhook_signature` theo doc PayOS.
- Webhook sign: HMAC-SHA256 của canonical form với `PAYOS_PAYOUT_WEBHOOK_SECRET`.

## Conventions
- Vietnamese comment + UI.
- Admin Relayer pattern: mọi on-chain write ký bằng `WALLET_PRIVATE_KEY`.
- Luồng V3 KHÔNG thay thế V2 (smart2 approveDisbursement) — chạy song song.
- Django signals + `transaction.on_commit` cho background threads tránh stale reads.
- Luôn dùng `BlockchainService._send_transaction` (pre-flight eth_call, EIP-1559 gas).

## Things to avoid
- Đừng gọi trực tiếp `smart3` nếu chưa `setBurner` trên smart1 — sẽ revert.
- Đừng đổi `v3_status` thủ công qua admin — dùng endpoint để giữ invariant.
- PayOS Payout MOCK: đừng deploy production khi chưa implement real API.
- **KHÔNG được edit `Organization.wallet_address` sau khi campaign đã `createCampaign` on-chain**. Lý do: smart3 đọc `organization` từ smart2 (`dcpManager.getCampaign`) làm single-source-of-truth. Nếu Django DB lưu ví mới nhưng on-chain vẫn là ví cũ → backend verify EIP-712 sig theo ví DB (mới) nhưng smart3 `ecrecover` theo ví on-chain (cũ) → revert `DE: sig khong hop le`.
- **Đẫc biệt: deadline của EIP-712 signature phải DETERMINISTIC across 3 approvers.** Hiện `_get_proposal_v3_eip712_payload` derive từ `proposal.created_at + 7 days`. Không được dynamic-override per-request hoặc dùng `time.time()` — sẽ khiến 3 sigs sai payload → relay revert.
