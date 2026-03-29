from decimal import Decimal
from web3 import Web3
from django.conf import settings
import requests as http_req

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

        try:
            pk_addr = self.w3.eth.account.from_key(settings.WALLET_PRIVATE_KEY).address
            if pk_addr.lower() != settings.WALLET_ADDRESS.lower():
                print(f"⚠️ [BLOCKCHAIN] WALLET_ADDRESS không khớp private key: {settings.WALLET_ADDRESS} != {pk_addr}")
        except Exception:
            pass

    # Hàm gửi giao dịch (Dùng chung cho cả Donate và Rút tiền)
    def _send_transaction(self, function_call, value_wei=0, max_retries=3):
        gas_price = self.w3.eth.gas_price
        min_bump = int(5 * 10**9)  # 5 gwei fallback to replace pending

        for attempt in range(max_retries + 1):
            nonce = self.w3.eth.get_transaction_count(settings.WALLET_ADDRESS, 'pending')
            tx_data = function_call.build_transaction({
                'chainId': 11155111,
                'gas': 2000000,
                'gasPrice': int(gas_price),
                'nonce': nonce,
                'value': int(value_wei) if value_wei else 0,
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx_data, settings.WALLET_PRIVATE_KEY)
            try:
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                return self.w3.to_hex(tx_hash)
            except ValueError as e:
                msg = str(e).lower()
                if attempt < max_retries:
                    if 'replacement transaction underpriced' in msg:
                        gas_price = max(int(gas_price * 2), min_bump)
                        continue
                    if 'nonce too low' in msg:
                        gas_price = max(int(self.w3.eth.gas_price * 1.3), int(gas_price * 1.5))
                        continue
                raise

    # --- CÁC HÀM NGHIỆP VỤ ---

    # 1. Khởi tạo chiến dịch trên Blockchain (gọi khi Admin DUYỆT chiến dịch)
    def init_campaign(self, campaign_id, org_name, org_address):
        func = self.contract.functions.initCampaign(campaign_id, org_name, self.w3.to_checksum_address(org_address))
        return self._send_transaction(func)

    # 2. Admin cấp phát ETH cho user sau VNPay
    def send_eth_to_user(self, campaign_id, user_address, amount_e_wei, amount_g_wei):
        func = self.contract.functions.sendEthToUser(
            campaign_id,
            self.w3.to_checksum_address(user_address),
            int(amount_e_wei),
            int(amount_g_wei),
        )
        return self._send_transaction(func)

    # 3. Thực thi giải ngân (sau khi vote thông qua)
    def execute_disbursement(self, campaign_id, amount_wei):
        func = self.contract.functions.executeDisbursement(campaign_id, int(amount_wei))
        return self._send_transaction(func)

    def deposit_exchange_pool(self, amount_wei):
        func = self.contract.functions.depositExchangePool()
        return self._send_transaction(func, value_wei=int(amount_wei))

    def admin_has_pending_tx(self):
        latest = self.w3.eth.get_transaction_count(settings.WALLET_ADDRESS, 'latest')
        pending = self.w3.eth.get_transaction_count(settings.WALLET_ADDRESS, 'pending')
        return pending > latest

    def is_campaign_active(self, campaign_id):
        try:
            c = self.contract.functions.campaigns(campaign_id).call()
            return bool(c[6])
        except Exception:
            return False

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


def get_eth_vnd_rate():
    """Lấy tỉ giá ETH/VND realtime từ CoinGecko API (miễn phí)"""
    try:
        response = http_req.get(
            'https://api.coingecko.com/api/v3/simple/price',
            params={'ids': 'ethereum', 'vs_currencies': 'vnd'},
            timeout=10,
        )
        if response.ok:
            data = response.json()
            rate = Decimal(str(data['ethereum']['vnd']))
            print(f"📈 Tỉ giá ETH/VND hiện tại: {rate:,.0f} VNĐ")
            return rate
    except Exception as e:
        print(f"⚠️ Không lấy được tỉ giá từ CoinGecko: {e}")
    return Decimal('60000000')
