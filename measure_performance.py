import time
import requests
from web3 import Web3
import os
from dotenv import load_dotenv

load_dotenv('E:/hadoantn/Ha/.env')

# IPFS Pinata
PINATA_API_KEY = os.getenv('PINATA_API_KEY')
PINATA_API_SECRET = os.getenv('PINATA_API_SECRET')

# Web3
RPC_URL = os.getenv('SEPOLIA_RPC_URL')
PRIVATE_KEY = os.getenv('ADMIN_PRIVATE_KEY')
WALLET = os.getenv('WALLET_ADDRESS')

from web3.middleware import ExtraDataToPOAMiddleware

w3 = Web3(Web3.HTTPProvider(RPC_URL))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

def measure_ipfs():
    url = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
    headers = {
        "pinata_api_key": PINATA_API_KEY,
        "pinata_secret_api_key": PINATA_API_SECRET,
        "Content-Type": "application/json"
    }
    data = {
        "pinataContent": {
            "test": "performance_measurement",
            "timestamp": time.time()
        }
    }
    start = time.time()
    try:
        res = requests.post(url, json=data, headers=headers, timeout=10)
        end = time.time()
        if res.status_code == 200:
            return end - start
    except Exception as e:
        print(f"IPFS error: {e}")
    return -1

def measure_sepolia():
    start = time.time()
    nonce = w3.eth.get_transaction_count(WALLET)
    tx = {
        'nonce': nonce,
        'to': WALLET,
        'value': 0,
        'gas': 21000,
        'gasPrice': w3.eth.gas_price,
        'chainId': 11155111
    }
    signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    # Wait for receipt
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    end = time.time()
    return end - start

def main():
    print("Bắt đầu đo lường 5 lần...")
    results = []
    
    for i in range(5):
        print(f"Lần {i+1}...")
        ipfs_time = measure_ipfs()
        print(f"  - IPFS: {ipfs_time:.2f}s")
        
        try:
            sep_time = measure_sepolia()
            print(f"  - Sepolia: {sep_time:.2f}s")
        except Exception as e:
            print(f"  - Sepolia error: {e}")
            sep_time = -1
            
        results.append((ipfs_time, sep_time))
        time.sleep(1)
        
    print("\n[FINAL_RESULTS]")
    for r in results:
        print(f"{r[0]:.2f},{r[1]:.2f}")

if __name__ == '__main__':
    main()
