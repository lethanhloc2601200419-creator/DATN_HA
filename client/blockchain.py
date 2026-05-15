"""
Blockchain service — ADMIN RELAYER (GAS STATION) PATTERN.

Contract hiện tại: DCPManager v4 ("Double Integrity" — 2 contract tách rời).
    - smart1.sol (VNDT)       : ERC20 token, mint/burn khoá theo `manager` =
                                 address của smart2. Backend KHÔNG bao giờ gọi
                                 mint trực tiếp ở đây.
    - smart2.sol (DCPManager) : ERC721 Soulbound Badge + quản lý campaign.
                                 recordDonation sẽ tự gọi VNDT.mint(multisig)
                                 và _safeMint(donor, badgeId).

Các function on-chain (smart2):
    - createCampaign(uint256 _cid, address _org, address _multisigVault) onlyOwner
    - recordDonation(uint256 _cid, address _donor, address _multisig,
                     uint256 _fiatAmount) onlyOwner
    - proposeDisbursement(uint256 _cid, string _ipfsCid)
    - approveDisbursement(uint256 _cid)  -- đủ 3 chữ ký (org + admin + supervisor)
      → tự động _executeDisbursement (CHỈ chốt sổ; KHÔNG burn token; donor giữ
        SBT mãi mãi như proof-of-donation).
    - View: getCampaign(uint256) → (organization, multisigVault, currentAmount,
                                    isDisbursed, ipfsCid, approvals)

Admin Relayer pattern: mọi giao dịch write đều được
    1) Ký bằng private key của ví Admin (settings.WALLET_PRIVATE_KEY)
    2) Gửi trực tiếp lên Sepolia qua eth_sendRawTransaction
    3) Admin trả gas fee bằng ETH của chính mình.

Đây KHÔNG phải ERC-4337 / Paymaster. Đây là "meta-transaction qua trung gian
tin cậy" (trusted relayer) — đơn giản hơn, không cần bundler/EntryPoint.
Tương thích với contract hiện tại: `onlyOwner` yêu cầu msg.sender == owner
(= địa chỉ deploy = WALLET_ADDRESS của backend).

Gas pricing: ưu tiên EIP-1559 động (maxFeePerGas = 2*baseFee + priority)
— chỉ dùng legacy gasPrice nếu settings.ADMIN_GAS_PRICE_GWEI được set thủ công.

Error surfacing: _send_transaction pre-flight bằng eth_call để bắt revert
reason TRƯỚC khi burn gas; nếu tx mined nhưng revert, replay eth_call tại
blockNumber đó để lấy reason thật — không còn generic "thao tác thất bại" nuốt lỗi.

CÁC HÀM OBSOLETE (contract cũ v2, không còn tồn tại trên v3):
    initCampaign, donateOnBehalf, recordBankDonation, recordGasCost,
    withdrawGasRecovery, getCampaignStats, executeDisbursement,
    deposit_exchange_pool.
Nếu code cũ gọi → sẽ raise ABIFunctionNotFound hoặc NotImplementedError
(xem các stub bên dưới).
"""
from decimal import Decimal
import time
from web3 import Web3
from django.conf import settings
import requests as http_req
from web3.exceptions import LogTopicError, ContractLogicError

# Hệ số quy đổi VND → đơn vị 18-decimals của VNDT (ERC20).
_VNDT_DECIMALS = Decimal(10) ** 18

# Module-level caches to avoid repeated network calls
_rate_cache = {'value': None, 'ts': 0}
_stats_cache = {}  # {campaign_id: {'value': stats_dict, 'ts': timestamp}}
_RATE_CACHE_TTL = 300   # 5 minutes
_STATS_CACHE_TTL = 120  # 2 minutes

# Địa chỉ zero dùng khi user ủng hộ qua VNPay không có ví MetaMask
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class BlockchainService:
    def __init__(self):
        # 1. Kết nối mạng Sepolia
        self.w3 = Web3(Web3.HTTPProvider(settings.WEB3_PROVIDER_URL))

        if not self.w3.is_connected():
            raise Exception("Không thể kết nối tới mạng Blockchain Sepolia!")

        # 2. Load Smart Contract — DCPManager (smart2.sol)
        self.contract = self.w3.eth.contract(
            address=settings.SMART_CONTRACT_ADDRESS,
            abi=settings.SMART_CONTRACT_ABI
        )

        # 2b. Load VNDT token contract (smart1.sol) — read-only side-channel
        # cho việc kiểm tra balance/totalSupply. Backend KHÔNG mint trực tiếp
        # ở đây vì manager đã được khoá về smart2 trên on-chain.
        vndt_addr = getattr(settings, 'VNDT_TOKEN_ADDRESS', None)
        vndt_abi = getattr(settings, 'VNDT_ABI', None)
        if vndt_addr and vndt_abi:
            try:
                self.vndt_contract = self.w3.eth.contract(
                    address=self.w3.to_checksum_address(vndt_addr),
                    abi=vndt_abi,
                )
            except Exception as exc:
                print(f"⚠️ [BLOCKCHAIN] Không load được VNDT contract: {exc}", flush=True)
                self.vndt_contract = None
        else:
            self.vndt_contract = None

        self.admin_address = self.w3.eth.account.from_key(settings.WALLET_PRIVATE_KEY).address

        try:
            if self.admin_address.lower() != settings.WALLET_ADDRESS.lower():
                print(f"⚠️ [BLOCKCHAIN] WALLET_ADDRESS không khớp private key: {settings.WALLET_ADDRESS} != {self.admin_address}", flush=True)
        except Exception:
            pass

    # ---------- Gas helpers ----------
    def _build_gas_fields(self):
        """
        Trả về dict gas fields cho build_transaction().
        - Nếu ADMIN_GAS_PRICE_GWEI được set → dùng legacy gasPrice (override chủ động).
        - Ngược lại → ưu tiên EIP-1559 (maxFeePerGas / maxPriorityFeePerGas),
          fallback sang legacy gasPrice nếu node không trả về baseFee.
        """
        fixed_gwei = getattr(settings, 'ADMIN_GAS_PRICE_GWEI', None)
        if fixed_gwei:
            return {'gasPrice': int(self.w3.to_wei(fixed_gwei, 'gwei'))}

        # EIP-1559 path: baseFee * 2 + priority fee → đảm bảo tx được mine trên Sepolia
        try:
            latest = self.w3.eth.get_block('latest')
            base_fee = latest.get('baseFeePerGas')
            if base_fee:
                try:
                    priority_fee = int(self.w3.eth.max_priority_fee)
                except Exception:
                    priority_fee = self.w3.to_wei(1.5, 'gwei')
                # max_fee = 2 * baseFee + priority, đủ buffer cho biến động baseFee
                max_fee = int(base_fee) * 2 + priority_fee
                return {
                    'maxFeePerGas': max_fee,
                    'maxPriorityFeePerGas': priority_fee,
                }
        except Exception as exc:
            print(f"⚠️ [GAS] Không lấy được baseFeePerGas, fallback legacy gasPrice: {exc}", flush=True)

        return {'gasPrice': int(self.w3.eth.gas_price)}

    def _extract_revert_reason(self, tx_data, block_identifier='latest'):
        """
        Replay giao dịch bằng eth_call để lấy lý do revert thật từ EVM.
        Gọi khi receipt.status == 0 (tx đã mine nhưng revert).
        """
        replay_data = {
            'from': tx_data.get('from', self.admin_address),
            'to': tx_data['to'],
            'data': tx_data.get('data', tx_data.get('input', '0x')),
            'value': tx_data.get('value', 0),
            'gas': tx_data.get('gas'),
        }
        try:
            self.w3.eth.call(replay_data, block_identifier=block_identifier)
            return 'unknown revert (eth_call did not raise)'
        except ContractLogicError as exc:
            return f'ContractLogicError: {exc}'
        except Exception as exc:
            return f'{type(exc).__name__}: {exc}'

    # Hàm gửi giao dịch (Dùng chung cho cả Donate và Rút tiền)
    def _send_transaction(self, function_call, value_wei=0, max_retries=3, gas_limit=2000000, wait_for_receipt=False):
        chain_id = self.w3.eth.chain_id
        contract_address = function_call.address
        fn_name = getattr(function_call, 'fn_name', 'unknown')

        print(
            f"ℹ️ [TX/PRE] fn={fn_name} chainId={chain_id} contract={contract_address} "
            f"admin={self.admin_address} value_wei={value_wei} gas_limit={gas_limit}",
            flush=True
        )

        # ----- Pre-flight eth_call: phát hiện revert TRƯỚC khi burn gas -----
        # web3.py sẽ raise ContractLogicError với revert reason đã decode.
        try:
            function_call.call({
                'from': self.admin_address,
                'value': int(value_wei) if value_wei else 0,
            })
        except ContractLogicError as exc:
            print(f"❌ [TX/PREFLIGHT] Contract revert trước khi gửi: {exc}", flush=True)
            # Ném tiếp với prefix rõ ràng để view layer log thẳng ra Railway.
            raise ContractLogicError(f"Pre-flight revert on {fn_name}: {exc}") from exc
        except Exception as exc:
            # RPC/network lỗi thì không chặn — chỉ log, vẫn thử gửi tx thật.
            print(f"⚠️ [TX/PREFLIGHT] eth_call lỗi ngoài EVM, bỏ qua: {type(exc).__name__}: {exc}", flush=True)

        last_exc = None
        for attempt in range(max_retries + 1):
            nonce = self.w3.eth.get_transaction_count(self.admin_address, 'pending')
            gas_fields = self._build_gas_fields()
            tx_data = function_call.build_transaction({
                'chainId': chain_id,
                'gas': gas_limit,
                'nonce': nonce,
                'value': int(value_wei) if value_wei else 0,
                **gas_fields,
            })
            gas_summary = (
                f"gasPrice={tx_data['gasPrice']}" if 'gasPrice' in tx_data
                else f"maxFeePerGas={tx_data.get('maxFeePerGas')} maxPriority={tx_data.get('maxPriorityFeePerGas')}"
            )
            print(f"ℹ️ [TX] nonce={nonce} {gas_summary}", flush=True)

            signed_tx = self.w3.eth.account.sign_transaction(tx_data, settings.WALLET_PRIVATE_KEY)
            try:
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                tx_hash_hex = self.w3.to_hex(tx_hash)
                if not wait_for_receipt:
                    return tx_hash_hex

                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash_hex, timeout=180)
                if int(receipt.status) != 1:
                    # Tx đã mine nhưng revert → replay để lấy reason thật.
                    reason = self._extract_revert_reason(
                        tx_data,
                        block_identifier=receipt.blockNumber,
                    )
                    print(f"❌ [TX] Mined but reverted. tx={tx_hash_hex} reason={reason}", flush=True)
                    raise ContractLogicError(
                        f"{fn_name} reverted on-chain (tx={tx_hash_hex}): {reason}"
                    )
                return {
                    'tx_hash': tx_hash_hex,
                    'receipt': receipt,
                    'status': receipt.status,
                }
            except ContractLogicError:
                # Đã có reason rõ ràng, không retry.
                raise
            except Exception as e:
                last_exc = e
                msg = str(e).lower()
                if attempt < max_retries and ('nonce too low' in msg or 'replacement transaction underpriced' in msg):
                    print(f"⚠️ [TX RETRY {attempt+1}/{max_retries}] {msg[:80]}... Đợi 5s rồi thử lại.", flush=True)
                    time.sleep(5)
                    continue
                print(f"❌ [TX] {type(e).__name__}: {e}", flush=True)
                raise

        # Về mặt lý thuyết không reach, nhưng để an toàn:
        if last_exc:
            raise last_exc

    # --- CÁC HÀM NGHIỆP VỤ ---

    # ==========================================================
    # 1. TẠO CHIẾN DỊCH ON-CHAIN
    # ==========================================================
    def trigger_create_campaign(self, campaign_id, org_address, multisig_vault=None):
        """
        Gọi `createCampaign(uint256 _cid, address _org, address _multisigVault)`
        trên contract DCPManager v4.

        - `campaign_id`   : Django Campaign.id (Postgres PK) → dùng trực tiếp làm
                            on-chain ID.
        - `org_address`   : địa chỉ ví của tổ chức (Organization.wallet_address) —
                            dùng cho multisig 3 chữ ký lúc giải ngân.
        - `multisig_vault`: ví nhận token VNDT khi có donation. Hiện tại MVP
                            mặc định trùng `org_address` (nếu None) — có thể
                            tách thành ví riêng nếu sau này cần.

        Trả về dict {tx_hash, receipt, status} khi tx đã mine thành công.
        """
        if not org_address:
            raise ValueError("org_address không được để trống khi tạo campaign on-chain.")
        org_checksum = self.w3.to_checksum_address(org_address)
        # MVP: nếu chưa cấu hình multisig riêng, dùng chính ví tổ chức làm vault.
        vault_raw = multisig_vault or org_address
        vault_checksum = self.w3.to_checksum_address(vault_raw)

        func = self.contract.functions.createCampaign(
            int(campaign_id),
            org_checksum,
            vault_checksum,
        )
        # Gas limit ~250k đủ cho createCampaign (set struct + emit event).
        return self._send_transaction(
            func,
            gas_limit=250000,
            wait_for_receipt=True,
        )

    # Backward-compat alias: code cũ vẫn gọi init_campaign(cid, name, address).
    # Tham số `org_name` bị bỏ vì contract v3+ không lưu name nữa.
    def init_campaign(self, campaign_id, org_name=None, org_address=None):
        """
        [DEPRECATED] Alias cho trigger_create_campaign. Contract v4 không còn
        lưu org_name nên tham số này bị bỏ qua (giữ để code cũ khỏi vỡ).
        Không truyền multisig → mặc định = org_address.
        """
        return self.trigger_create_campaign(campaign_id, org_address)

    # ==========================================================
    # 2. VIEW: KIỂM TRA / LẤY STATE CHIẾN DỊCH
    # ==========================================================
    def is_campaign_active(self, campaign_id):
        """
        Contract v4: campaign "tồn tại" ⇔ getCampaign(cid).organization != 0x0.
        "active" ở đây nghĩa là đã được createCampaign và chưa bị giải ngân.
        """
        try:
            c = self.contract.functions.getCampaign(int(campaign_id)).call()
            # v4 tuple: (organization, multisigVault, currentAmount, isDisbursed, ipfsCid, approvals)
            org = c[0]
            is_disbursed = bool(c[3])
            return bool(org and org != ZERO_ADDRESS) and not is_disbursed
        except Exception:
            return False

    def get_campaign_onchain_stats(self, campaign_id, use_cache=True):
        """
        Lấy thông tin on-chain của 1 chiến dịch (cached 2 min).

        Contract v4 shape (getCampaign):
            (organization, multisigVault, currentAmount, isDisbursed, ipfsCid, approvals)

        `currentAmount` là số token VNDT NET (đã trừ phí, đơn vị 18 decimals).
        Để hiển thị VND "người dùng", chia cho 10^18.

        Các key legacy (total_gas_cost_wei, total_admin_recovered_wei, available_wei…)
        được giữ = 0 để code view cũ không bị KeyError. Sẽ dọn ở lần refactor tới.
        """
        now = time.time()
        if use_cache and campaign_id in _stats_cache:
            cached = _stats_cache[campaign_id]
            if now - cached['ts'] < _STATS_CACHE_TTL:
                return cached['value']

        c = self.contract.functions.getCampaign(int(campaign_id)).call()
        organization = c[0]
        multisig_vault = c[1]
        current_amount_18 = int(c[2])         # token units (18 decimals)
        is_disbursed = bool(c[3])
        ipfs_cid = c[4]
        approvals = int(c[5])

        # Quy đổi về VND "face value" — chia cho 10^18.
        current_amount_vnd = int(Decimal(current_amount_18) / _VNDT_DECIMALS)

        exists = bool(organization and organization != ZERO_ADDRESS)

        stats = {
            'organization_address': organization if exists else None,
            'organization_name': None,        # contract v4 không lưu name
            'multisig_vault_address': multisig_vault if exists else None,
            'current_amount_vnd': current_amount_vnd,
            'current_amount_raw': current_amount_18,  # 18-decimals raw value
            'is_disbursed': is_disbursed,
            'ipfs_cid': ipfs_cid,
            'approvals': approvals,
            'is_active': exists and not is_disbursed,
            'exists': exists,
            # ===== Các key legacy, KHÔNG còn ý nghĩa ở v4 =====
            'total_fund_wei': 0,
            'total_gas_cost_wei': 0,
            'total_gas_subsidized_wei': 0,
            'total_disbursed_wei': 0,
            'total_admin_recovered_wei': 0,
            'available_wei': 0,
        }

        _stats_cache[campaign_id] = {'value': stats, 'ts': now}
        return stats

    # ==========================================================
    # 3. LEGACY / OBSOLETE — contract v3 KHÔNG còn các function này.
    # Gọi sẽ raise NotImplementedError với hướng dẫn migration.
    # blockchain_processor.py (luồng async cũ) phụ thuộc các hàm này
    # và đã nghỉ dùng — không bị kích hoạt trong luồng hiện tại.
    # ==========================================================
    _V3_REMOVED_MSG = (
        "Function này đã bị gỡ khỏi DCPManager v3. "
        "Luồng mới: createCampaign → recordDonation → propose/approveDisbursement. "
        "Nếu đang chạy code cũ, hãy gỡ lệnh gọi này."
    )

    def record_bank_donation(self, *args, **kwargs):
        raise NotImplementedError(f"record_bank_donation(): {self._V3_REMOVED_MSG}")

    def donate_on_behalf(self, *args, **kwargs):
        raise NotImplementedError(f"donate_on_behalf(): {self._V3_REMOVED_MSG}")

    def record_gas_cost(self, *args, **kwargs):
        raise NotImplementedError(f"record_gas_cost(): {self._V3_REMOVED_MSG}")

    def execute_disbursement(self, *args, **kwargs):
        # v3 tự động thực thi bên trong approveDisbursement khi đủ 3 chữ ký.
        raise NotImplementedError(
            "execute_disbursement(): Contract v3 tự động burn/giải ngân trong "
            "approveDisbursement khi đủ 3 chữ ký (org + admin + supervisor). "
            "Gọi approve_disbursement() thay thế."
        )

    def withdraw_gas_recovery(self, *args, **kwargs):
        raise NotImplementedError(f"withdraw_gas_recovery(): {self._V3_REMOVED_MSG}")

    def deposit_exchange_pool(self, *args, **kwargs):
        raise NotImplementedError(f"deposit_exchange_pool(): {self._V3_REMOVED_MSG}")

    # ==========================================================
    # 4. GIẢI NGÂN (V3) — propose + approve
    # ==========================================================
    def propose_disbursement(self, campaign_id, ipfs_cid):
        func = self.contract.functions.proposeDisbursement(
            int(campaign_id), str(ipfs_cid or '')
        )
        return self._send_transaction(func, gas_limit=200000, wait_for_receipt=True)

    def approve_disbursement(self, campaign_id):
        """Đủ 3 chữ ký (org + admin + supervisor) → contract tự burn token."""
        func = self.contract.functions.approveDisbursement(int(campaign_id))
        return self._send_transaction(func, gas_limit=300000, wait_for_receipt=True)

    # 6. Lấy phí gas thực tế từ transaction receipt
    def get_transaction_gas_fee(self, tx_hash):
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        gas_used = receipt['gasUsed']
        effective_gas_price = receipt.get('effectiveGasPrice', self.w3.eth.gas_price)
        gas_fee_wei = gas_used * effective_gas_price
        gas_fee_eth = Decimal(str(gas_fee_wei)) / Decimal('1000000000000000000')
        return {
            'gas_used': gas_used,
            'gas_price_gwei': round(effective_gas_price / 10**9, 4),
            'gas_fee_wei': gas_fee_wei,
            'gas_fee_eth': gas_fee_eth,
        }

    # Cache treasuryWallet để tránh RPC call mỗi lần anonymous donation.
    _treasury_cache = None

    def get_fallback_donor_address(self):
        """
        [V4 — mint-to-donor]
        Với contract V4 token được mint THẲNG cho address này, nên KHÔNG được
        fallback về admin_address (admin sẽ tích token từ các quyên góp ẩn danh,
        đi ngược yêu cầu minh bạch).

        Thay vào đó dùng `treasuryWallet` trên contract làm "sink" cho các
        donation không có ví donor. Treasury là ví trung lập do chính contract
        công bố, donor ẩn danh có thể tra cứu được.
        """
        if BlockchainService._treasury_cache is None:
            try:
                BlockchainService._treasury_cache = self.w3.to_checksum_address(
                    self.contract.functions.treasuryWallet().call()
                )
            except Exception as exc:
                print(f"⚠️ [FALLBACK] Không đọc được treasuryWallet, tạm dùng admin: {exc}", flush=True)
                return self.w3.to_checksum_address(self.admin_address)
        return BlockchainService._treasury_cache

    def trigger_record_donation(self, campaign_id, donor_address, multisig_address, fiat_amount):
        """
        Gọi `DCPManager.recordDonation(_cid, _donor, _multisigAddress, _fiatAmount)`
        và đợi receipt để chắc chắn giao dịch đã vào chain trước khi trả về.

        - `_donor`     → ví nhận **SBT badge** (proof-of-donation, không transfer được).
        - `_multisig`  → ví nhận **token VNDT** (kho ký quỹ của campaign). Phải
                         khớp với `multisigVault` đã set lúc createCampaign,
                         nếu không contract sẽ revert.
        - `_fiatAmount`→ số VND face value, sẽ được nhân 10^18 để khớp
                         với 18-decimals của VNDT (Etherscan hiển thị "2000.0 VNDT"
                         thay vì "0.000000000000002 VNDT").

        Nếu `donor_address` rỗng → dùng treasuryWallet làm sink (tuyệt đối
        KHÔNG dùng admin_address để tránh admin tích badge ẩn danh).
        """
        if not multisig_address:
            raise ValueError(
                "multisig_address không được để trống — phải khớp "
                "campaign.organization.wallet_address đã set khi createCampaign."
            )

        donor = donor_address or self.get_fallback_donor_address()
        donor_checksum = self.w3.to_checksum_address(donor)
        multisig_checksum = self.w3.to_checksum_address(multisig_address)

        # Chuyển fiat_amount (VND face value) → số nguyên 18 decimals.
        # Dùng Decimal (đã import ở top file) để tránh sai số float khi amount
        # là kiểu float/str.
        amount_18 = int(Decimal(str(fiat_amount)) * _VNDT_DECIMALS)

        func = self.contract.functions.recordDonation(
            int(campaign_id),
            donor_checksum,
            multisig_checksum,
            amount_18,
        )
        # Gas tăng nhẹ vì contract v4 mint cả ERC20 (cho multisig) + ERC721 SBT (cho donor).
        tx_result = self._send_transaction(
            func,
            gas_limit=400000,
            wait_for_receipt=True,
        )
        return tx_result

    def get_disbursement_approver_wallets(self):
        return {
            'admin_wallet': self.w3.to_checksum_address(self.contract.functions.adminWallet().call()),
            'supervisor_wallet': self.w3.to_checksum_address(self.contract.functions.supervisorWallet().call()),
        }

    def get_campaign_disbursement_meta(self, campaign_id):
        campaign_state = self.contract.functions.getCampaign(int(campaign_id)).call()
        # v4 tuple: (organization, multisigVault, currentAmount, isDisbursed, ipfsCid, approvals)
        return {
            'organization': campaign_state[0],
            'multisig_vault': campaign_state[1],
            'current_amount': int(campaign_state[2]),
            'is_disbursed': bool(campaign_state[3]),
            'ipfs_cid': campaign_state[4],
            'approvals': int(campaign_state[5]),
        }

    # ==========================================================
    # 5. [V3] SMART3 — EIP-712 MULTISIG + BURN WITH BANK TX
    # ==========================================================
    #
    # Luồng V3 (chạy song song, không thay luồng cũ smart2 ở trên):
    #   Phase 3a: recordMultisigApproval(proposalId, ..., SigBundle)
    #             → contract ecrecover 3 sigs → emit MultisigConfirmed.
    #   Phase 4 : finalizeBurnWithBankTx(proposalId, multisigVault, bankTxId)
    #             → contract gọi VNDT.burnWithBankTx → emit DisbursementFinalized.
    #
    # Để dùng được:
    #   1. Deploy smart3.sol với constructor(_vndt, _dcpManager).
    #   2. Ở smart1 (VNDT), gọi setBurner(<smart3_address>).
    #   3. Set settings.SMART3_CONTRACT_ADDRESS + SMART3_CONTRACT_ABI.
    # ==========================================================

    @property
    def smart3_contract(self):
        """
        Lazy-load contract smart3. Trả về None nếu chưa cấu hình —
        caller phải check trước khi gọi để fail-fast với message dễ debug.
        """
        if getattr(self, '_smart3_contract_cache', None) is not None:
            return self._smart3_contract_cache
        addr = getattr(settings, 'SMART3_CONTRACT_ADDRESS', None)
        abi = getattr(settings, 'SMART3_CONTRACT_ABI', None)
        if not addr or not abi:
            self._smart3_contract_cache = None
            return None
        self._smart3_contract_cache = self.w3.eth.contract(
            address=self.w3.to_checksum_address(addr),
            abi=abi,
        )
        return self._smart3_contract_cache

    def build_eip712_typed_data(self, proposal_id, campaign_id, amount_raw,
                                recipient, ipfs_cid, deadline, nonce, role):
        """
        Build payload EIP-712 typed-data để frontend ký bằng
        `eth_signTypedData_v4`. Trả về dict có cấu trúc đúng chuẩn MetaMask.

        - `amount_raw` là số nguyên 18-decimals (đã nhân 10^18 ở caller).
        - `role` ∈ {'organization', 'supervisor', 'admin'} — phải khớp
          exact với cách smart3 hash (case-sensitive bytes).
        """
        verifying_contract = getattr(settings, 'SMART3_CONTRACT_ADDRESS', '')
        if not verifying_contract:
            raise RuntimeError(
                "SMART3_CONTRACT_ADDRESS chưa cấu hình — không build được EIP-712 payload."
            )
        return {
            'types': {
                'EIP712Domain': [
                    {'name': 'name', 'type': 'string'},
                    {'name': 'version', 'type': 'string'},
                    {'name': 'chainId', 'type': 'uint256'},
                    {'name': 'verifyingContract', 'type': 'address'},
                ],
                'DisbursementApproval': [
                    {'name': 'proposalId', 'type': 'uint256'},
                    {'name': 'campaignId', 'type': 'uint256'},
                    {'name': 'amount', 'type': 'uint256'},
                    {'name': 'recipient', 'type': 'address'},
                    {'name': 'ipfsCid', 'type': 'string'},
                    {'name': 'deadline', 'type': 'uint256'},
                    {'name': 'nonce', 'type': 'uint256'},
                    {'name': 'role', 'type': 'string'},
                ],
            },
            'primaryType': 'DisbursementApproval',
            'domain': {
                'name': 'DisbursementExecutor',
                'version': '1',
                'chainId': 11155111,  # Sepolia chainId
                'verifyingContract': self.w3.to_checksum_address(verifying_contract),
            },
            'message': {
                'proposalId': str(int(proposal_id)),
                'campaignId': str(int(campaign_id)),
                'amount': str(int(amount_raw)),
                'recipient': self.w3.to_checksum_address(recipient),
                'ipfsCid': str(ipfs_cid or ''),
                'deadline': str(int(deadline)),
                'nonce': str(int(nonce)),
                'role': str(role),
            },
        }

    def recover_eip712_signer(self, typed_data, signature):
        """
        Recover address từ typed-data + signature để verify TRƯỚC khi lưu DB.
        Dùng eth_account.messages.encode_typed_data (web3.py >=6).
        """
        from eth_account import Account
        from eth_account.messages import encode_typed_data
        message = encode_typed_data(full_message=typed_data)
        return Account.recover_message(message, signature=signature)

    def record_multisig_approval(
        self, proposal_id, campaign_id, amount_raw, recipient, ipfs_cid,
        deadline, org_sig, supervisor_sig, admin_sig,
        org_nonce, supervisor_nonce, admin_nonce,
    ):
        """
        Phase 3a: Admin relayer submit 3 chữ ký EIP-712 lên smart3.
        Contract verify bằng ecrecover → emit MultisigConfirmed.
        Trả về dict {tx_hash, receipt, status}.
        """
        if self.smart3_contract is None:
            raise RuntimeError(
                "smart3 contract chưa cấu hình. Set SMART3_CONTRACT_ADDRESS + "
                "SMART3_CONTRACT_ABI trong settings."
            )
        # Struct DisbursementPayload (6 "shared" fields that all 3 approvers
        # signed identically). Solidity refactor từ 6 flat params → struct
        # để fix "stack too deep" khi verify 3 chữ ký trong cùng function.
        # Web3.py accept Solidity struct như positional tuple theo đúng
        # thứ tự field đã khai báo trong .sol.
        payload_tuple = (
            int(proposal_id),
            int(campaign_id),
            int(amount_raw),
            self.w3.to_checksum_address(recipient),
            str(ipfs_cid or ''),
            int(deadline),
        )
        def _sig_to_bytes(s):
            # Handle both '0x...' and '0X...' prefixes (MetaMask uses lowercase,
            # but some wallets/tests use uppercase) + bare hex.
            if s.lower().startswith('0x'):
                s = s[2:]
            return bytes.fromhex(s)
        sig_bundle = (
            _sig_to_bytes(org_sig),
            _sig_to_bytes(supervisor_sig),
            _sig_to_bytes(admin_sig),
            int(org_nonce),
            int(supervisor_nonce),
            int(admin_nonce),
        )
        func = self.smart3_contract.functions.recordMultisigApproval(
            payload_tuple,
            sig_bundle,
        )
        return self._send_transaction(func, gas_limit=500000, wait_for_receipt=True)

    def finalize_burn_with_bank_tx(self, proposal_id, multisig_vault, bank_tx_id):
        """
        Phase 4: Sau khi PayOS webhook báo success, admin relayer gọi
        smart3.finalizeBurnWithBankTx → smart3 gọi VNDT.burnWithBankTx
        → burn token + emit event audit chứa bankTxId.
        """
        if self.smart3_contract is None:
            raise RuntimeError("smart3 contract chưa cấu hình.")
        func = self.smart3_contract.functions.finalizeBurnWithBankTx(
            int(proposal_id),
            self.w3.to_checksum_address(multisig_vault),
            str(bank_tx_id),
        )
        return self._send_transaction(func, gas_limit=300000, wait_for_receipt=True)

    # ==========================================================
    # 5b. PUBLIC WRAPPER — finalize_disbursement(proposal, bank_tx_id)
    # ----------------------------------------------------------
    # API thân thiện hơn cho PayOS webhook layer: nhận proposal Django
    # instance + bankTxId, tự derive multisigVault từ Organization và
    # gọi smart3.finalizeBurnWithBankTx. Trả về tx_hash hex string.
    #
    # Khác với finalize_burn_with_bank_tx (low-level: cần multisig_vault
    # rời), method này phù hợp cho callers chỉ có proposal object.
    # ==========================================================
    def finalize_disbursement(self, proposal, bank_tx_id):
        """
        High-level wrapper: gọi smart3.finalizeBurnWithBankTx(proposalId,
        multisigVault, bankTxId), wait receipt (timeout ~60s qua
        _send_transaction.wait_for_receipt=True), return tx_hash string.

        Args:
            proposal: DisbursementProposal Django instance (cần có
                      proposal.id và proposal.campaign.organization.wallet_address).
            bank_tx_id: str — Bank Transaction ID nhận từ PayOS webhook.

        Returns:
            str — tx_hash hex (vd '0xabc...').

        Raises:
            ValueError nếu thiếu thông tin (multisig_vault).
            ContractLogicError nếu tx revert on-chain.
            RuntimeError nếu smart3 chưa cấu hình.
        """
        if not bank_tx_id:
            raise ValueError("bank_tx_id không được để trống.")
        campaign = getattr(proposal, 'campaign', None)
        org = getattr(campaign, 'organization', None) if campaign else None
        multisig_vault = getattr(org, 'wallet_address', None) if org else None
        if not multisig_vault:
            raise ValueError(
                f"Proposal #{proposal.id} không xác định được multisig_vault "
                "(campaign.organization.wallet_address rỗng)."
            )
        result = self.finalize_burn_with_bank_tx(
            proposal_id=proposal.id,
            multisig_vault=multisig_vault,
            bank_tx_id=bank_tx_id,
        )
        # _send_transaction(wait_for_receipt=True) trả dict {tx_hash, receipt, status}.
        if isinstance(result, dict):
            tx_hash = result.get('tx_hash')
        else:
            tx_hash = result
        if not tx_hash:
            raise RuntimeError(
                f"finalize_disbursement không nhận được tx_hash từ smart3 (proposal #{proposal.id})."
            )
        print(f"✅ [BLOCKCHAIN] finalize_disbursement proposal={proposal.id} tx={tx_hash}", flush=True)
        return str(tx_hash)

    def get_disbursed_and_burned_events(self, campaign_id=None, from_block=None, to_block='latest'):
        filters = {}
        if campaign_id is not None:
            filters['campaignId'] = int(campaign_id)
        try:
            return self.contract.events.DisbursedAndBurned.get_logs(
                from_block=from_block or 0,
                to_block=to_block,
                argument_filters=filters,
            )
        except (ValueError, LogTopicError):
            return []


def get_eth_vnd_rate():
    """Lấy tỉ giá ETH/VND realtime từ CoinGecko API (cached 5 min)"""
    now = time.time()
    if _rate_cache['value'] is not None and now - _rate_cache['ts'] < _RATE_CACHE_TTL:
        return _rate_cache['value']

    try:
        response = http_req.get(
            'https://api.coingecko.com/api/v3/simple/price',
            params={'ids': 'ethereum', 'vs_currencies': 'vnd'},
            timeout=10,
        )
        if response.ok:
            data = response.json()
            rate = Decimal(str(data['ethereum']['vnd']))
            print(f"📈 Tỉ giá ETH/VND hiện tại: {rate:,.0f} VNĐ (cached 5 min)", flush=True)
            _rate_cache['value'] = rate
            _rate_cache['ts'] = now
            return rate
    except Exception as e:
        print(f"⚠️ Không lấy được tỉ giá từ CoinGecko: {e}", flush=True)

    if _rate_cache['value'] is not None:
        return _rate_cache['value']
    return Decimal('60000000')


def invalidate_campaign_cache(campaign_id):
    """Xóa cache on-chain stats cho campaign (gọi sau khi ghi giao dịch)"""
    _stats_cache.pop(campaign_id, None)
