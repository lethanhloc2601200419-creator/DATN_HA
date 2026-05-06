"""
Blockchain service — ADMIN RELAYER (GAS STATION) PATTERN.

Tất cả các giao dịch on-chain (recordDonation, donateOnBehalf,
recordBankDonation, executeDisbursement, withdrawGasRecovery...) đều được:
    1) Ký bằng private key của ví Admin (settings.WALLET_PRIVATE_KEY)
    2) Gửi trực tiếp lên Sepolia qua eth_sendRawTransaction
    3) Admin trả gas fee bằng ETH của chính mình, sau đó thu hồi qua
       withdrawGasRecovery trên contract.

Đây KHÔNG phải ERC-4337 / Paymaster. Đây là "meta-transaction qua trung gian
tin cậy" (trusted relayer) — đơn giản hơn, không cần bundler/EntryPoint,
và tương thích với contract hiện tại (modifier `onlyAdmin` yêu cầu
msg.sender == admin).

Gas pricing: ưu tiên EIP-1559 động (maxFeePerGas = 2*baseFee + priority)
— chỉ dùng legacy gasPrice nếu settings.ADMIN_GAS_PRICE_GWEI được set thủ công.

Error surfacing: _send_transaction pre-flight bằng eth_call để bắt revert
reason TRƯỚC khi burn gas; nếu tx mined nhưng revert, replay eth_call tại
blockNumber đó để lấy reason thật — không còn generic "thao tác thất bại" nuốt lỗi.
"""
from decimal import Decimal
import time
from web3 import Web3
from django.conf import settings
import requests as http_req
from web3.exceptions import LogTopicError, ContractLogicError

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

        # 2. Load Smart Contract
        self.contract = self.w3.eth.contract(
            address=settings.SMART_CONTRACT_ADDRESS,
            abi=settings.SMART_CONTRACT_ABI
        )
        self.admin_address = self.w3.eth.account.from_key(settings.WALLET_PRIVATE_KEY).address

        try:
            if self.admin_address.lower() != settings.WALLET_ADDRESS.lower():
                print(f"⚠️ [BLOCKCHAIN] WALLET_ADDRESS không khớp private key: {settings.WALLET_ADDRESS} != {self.admin_address}")
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
            print(f"⚠️ [GAS] Không lấy được baseFeePerGas, fallback legacy gasPrice: {exc}")

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
        contract_address = self.contract.address
        fn_name = getattr(function_call, 'fn_name', 'unknown')

        print(
            f"ℹ️ [TX/PRE] fn={fn_name} chainId={chain_id} contract={contract_address} "
            f"admin={self.admin_address} value_wei={value_wei} gas_limit={gas_limit}"
        )

        # ----- Pre-flight eth_call: phát hiện revert TRƯỚC khi burn gas -----
        # web3.py sẽ raise ContractLogicError với revert reason đã decode.
        try:
            function_call.call({
                'from': self.admin_address,
                'value': int(value_wei) if value_wei else 0,
            })
        except ContractLogicError as exc:
            print(f"❌ [TX/PREFLIGHT] Contract revert trước khi gửi: {exc}")
            # Ném tiếp với prefix rõ ràng để view layer log thẳng ra Railway.
            raise ContractLogicError(f"Pre-flight revert on {fn_name}: {exc}") from exc
        except Exception as exc:
            # RPC/network lỗi thì không chặn — chỉ log, vẫn thử gửi tx thật.
            print(f"⚠️ [TX/PREFLIGHT] eth_call lỗi ngoài EVM, bỏ qua: {type(exc).__name__}: {exc}")

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
            print(f"ℹ️ [TX] nonce={nonce} {gas_summary}")

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
                    print(f"❌ [TX] Mined but reverted. tx={tx_hash_hex} reason={reason}")
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
                    print(f"⚠️ [TX RETRY {attempt+1}/{max_retries}] {msg[:80]}... Đợi 5s rồi thử lại.")
                    time.sleep(5)
                    continue
                print(f"❌ [TX] {type(e).__name__}: {e}")
                raise

        # Về mặt lý thuyết không reach, nhưng để an toàn:
        if last_exc:
            raise last_exc

    # --- CÁC HÀM NGHIỆP VỤ ---

    # 1. Khởi tạo chiến dịch trên Blockchain (gọi khi Admin DUYỆT chiến dịch)
    def init_campaign(self, campaign_id, org_name, org_address):
        func = self.contract.functions.initCampaign(
            campaign_id, org_name, self.w3.to_checksum_address(org_address)
        )
        return self._send_transaction(func)

    # 2. LUỒNG MỚI: Ghi sao kê ngân hàng lên blockchain (Giao dịch A)
    def record_bank_donation(self, campaign_id, donor_address, donor_name, amount_vnd,
                             vnpay_ref, timestamp_unix):
        """
        Giao dịch A trong luồng async:
        Ghi sao kê NH lên blockchain như một event để minh bạch.
        donor_address có thể là ZERO_ADDRESS nếu user không có ví MetaMask.
        """
        addr = self.w3.to_checksum_address(donor_address) if donor_address else ZERO_ADDRESS
        func = self.contract.functions.recordBankDonation(
            int(campaign_id),
            addr,
            str(donor_name or ''),
            int(amount_vnd),
            str(vnpay_ref or ''),
            int(timestamp_unix),
        )
        return self._send_transaction(func)

    # 3. LUỒNG MỚI: Admin tự động nạp ETH thay user vào contract (Giao dịch B)
    def donate_on_behalf(self, campaign_id, donor_address, amount_e_wei):
        """
        Giao dịch B trong luồng async:
        Admin wallet gọi donateOnBehalf, ETH đi thẳng từ ví Admin vào contract.
        User KHÔNG cần MetaMask.
        """
        addr = self.w3.to_checksum_address(donor_address) if donor_address else ZERO_ADDRESS
        func = self.contract.functions.donateOnBehalf(int(campaign_id), addr)
        return self._send_transaction(func, value_wei=int(amount_e_wei))

    # 4. LUỒNG MỚI: Ghi nhận gas đã chi lên contract để trừ khi giải ngân
    def record_gas_cost(self, campaign_id, amount_wei, reason):
        """
        Ghi gas A+B hoặc gas giải ngân dự trù lên contract.
        Giúp contract biết tổng phí admin đã chi → khi giải ngân trừ ra.
        """
        func = self.contract.functions.recordGasCost(
            int(campaign_id), int(amount_wei), str(reason or '')
        )
        return self._send_transaction(func)

    # 5. Thực thi giải ngân (sau khi vote thông qua)
    def execute_disbursement(self, campaign_id, amount_wei):
        func = self.contract.functions.executeDisbursement(campaign_id, int(amount_wei))
        return self._send_transaction(func)

    def withdraw_gas_recovery(self, campaign_id, amount_wei):
        func = self.contract.functions.withdrawGasRecovery(campaign_id, int(amount_wei))
        return self._send_transaction(func)

    def is_campaign_active(self, campaign_id):
        try:
            c = self.contract.functions.campaigns(campaign_id).call()
            return bool(c[6])
        except Exception:
            return False

    def get_campaign_onchain_stats(self, campaign_id, use_cache=True):
        """
        Lay thong tin on-chain cua 1 chien dich (cached 2 min).
        Su dung getCampaignStats() (v2):
            (totalFund, totalGasCost, totalDisbursed, totalAdminRecovered, available, isActive)
        """
        now = time.time()
        if use_cache and campaign_id in _stats_cache:
            cached = _stats_cache[campaign_id]
            if now - cached['ts'] < _STATS_CACHE_TTL:
                return cached['value']

        # Try new getCampaignStats() first, fallback to campaigns() mapping
        try:
            result = self.contract.functions.getCampaignStats(campaign_id).call()
            stats = {
                'organization_address': None,
                'organization_name': None,
                'total_fund_wei': int(result[0]),
                'total_gas_cost_wei': int(result[1]),
                # Backward-compat alias
                'total_gas_subsidized_wei': int(result[1]),
                'total_disbursed_wei': int(result[2]),
                'total_admin_recovered_wei': int(result[3]),
                'available_wei': int(result[4]),
                'is_active': bool(result[5]),
            }
            # Enrich with org name/address from campaigns() mapping
            try:
                c = self.contract.functions.campaigns(campaign_id).call()
                stats['organization_address'] = c[0]
                stats['organization_name'] = c[1]
            except Exception:
                pass
        except Exception:
            # Fallback: dùng campaigns() mapping cũ
            c = self.contract.functions.campaigns(campaign_id).call()
            total_fund = int(c[2])
            total_gas_cost = int(c[3])
            total_disbursed = int(c[4])
            total_admin_recovered = int(c[5])
            available = max(0, total_fund - total_gas_cost - total_disbursed - total_admin_recovered)
            stats = {
                'organization_address': c[0],
                'organization_name': c[1],
                'total_fund_wei': total_fund,
                'total_gas_cost_wei': total_gas_cost,
                'total_gas_subsidized_wei': total_gas_cost,
                'total_disbursed_wei': total_disbursed,
                'total_admin_recovered_wei': total_admin_recovered,
                'available_wei': available,
                'is_active': bool(c[6]),
            }

        _stats_cache[campaign_id] = {'value': stats, 'ts': now}
        return stats

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

    def get_fallback_donor_address(self):
        return self.w3.to_checksum_address(self.admin_address)

    def trigger_record_donation(self, campaign_id, donor_address, fiat_amount):
        """
        Phase 2 bridge:
        Gọi trực tiếp DCPManager.recordDonation(campaignId, donor, fiatAmount)
        và đợi receipt để chắc chắn giao dịch đã vào chain trước khi trả về.
        """
        donor = donor_address or self.admin_address
        donor_checksum = self.w3.to_checksum_address(donor)
        func = self.contract.functions.recordDonation(
            int(campaign_id),
            donor_checksum,
            int(fiat_amount),
        )
        # _send_transaction() giờ đã tự replay eth_call nếu receipt.status != 1
        # và raise ContractLogicError với reason thật. Không cần fallback generic nữa.
        tx_result = self._send_transaction(
            func,
            gas_limit=300000,
            wait_for_receipt=True,
        )
        return tx_result

    def get_disbursement_approver_wallets(self):
        return {
            'admin_wallet': self.w3.to_checksum_address(self.contract.functions.adminWallet().call()),
            'supervisor_wallet': self.w3.to_checksum_address(self.contract.functions.supervisorWallet().call()),
        }

    def get_campaign_disbursement_meta(self, campaign_id):
        campaign_state = self.contract.functions.campaigns(int(campaign_id)).call()
        return {
            'organization': campaign_state[0],
            'current_amount': int(campaign_state[1]),
            'is_disbursed': bool(campaign_state[2]),
            'ipfs_cid': campaign_state[3],
            'approvals': int(campaign_state[4]),
        }

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
            print(f"📈 Tỉ giá ETH/VND hiện tại: {rate:,.0f} VNĐ (cached 5 min)")
            _rate_cache['value'] = rate
            _rate_cache['ts'] = now
            return rate
    except Exception as e:
        print(f"⚠️ Không lấy được tỉ giá từ CoinGecko: {e}")

    if _rate_cache['value'] is not None:
        return _rate_cache['value']
    return Decimal('60000000')


def invalidate_campaign_cache(campaign_id):
    """Xóa cache on-chain stats cho campaign (gọi sau khi ghi giao dịch)"""
    _stats_cache.pop(campaign_id, None)
