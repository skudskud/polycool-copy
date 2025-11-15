#!/usr/bin/env python3
"""
Analyze the two redeem transactions to find differences
"""
import requests
from web3 import Web3

# Transaction hashes
FAILED_TX = "0x1a05d029e973a4d6a38565bd34bac95d25e84a5ae0811efd0077c2a59023c785"  # My bot - FAILED
SUCCESS_TX = "0x360198d0964a7c6b0bc4130b95fd435f2a4aedc4b1d9ce8787beacaf6f46d272"  # Not my bot - WORKED

# PolygonScan API
POLYGONSCAN_API = "https://api.polygonscan.com/api"
API_KEY = "YourApiKeyToken"  # Free tier works

def get_tx_details(tx_hash: str):
    """Get transaction details from PolygonScan"""
    url = f"{POLYGONSCAN_API}?module=proxy&action=eth_getTransactionByHash&txhash={tx_hash}&apikey={API_KEY}"
    response = requests.get(url)
    data = response.json()
    return data.get('result', {})

def get_tx_receipt(tx_hash: str):
    """Get transaction receipt"""
    url = f"{POLYGONSCAN_API}?module=proxy&action=eth_getTransactionReceipt&txhash={tx_hash}&apikey={API_KEY}"
    response = requests.get(url)
    data = response.json()
    return data.get('result', {})

def decode_input_data(input_data: str):
    """Decode transaction input data"""
    w3 = Web3()

    # Method ID (first 4 bytes)
    method_id = input_data[:10]

    # Function signature database
    method_signatures = {
        "0x26c41411": "redeemPositions(address,bytes32,bytes32,uint256[])",
        "0x095ea7b3": "approve(address,uint256)",
        "0xa9059cbb": "transfer(address,uint256)",
    }

    method_name = method_signatures.get(method_id, "Unknown")

    return {
        "method_id": method_id,
        "method_name": method_name,
        "raw_input": input_data
    }

def analyze_transaction(tx_hash: str, label: str):
    """Analyze a transaction"""
    print(f"\n{'='*80}")
    print(f"{label}: {tx_hash}")
    print(f"{'='*80}")

    # Get transaction details
    tx = get_tx_details(tx_hash)
    receipt = get_tx_receipt(tx_hash)

    if not tx:
        print(f"❌ Could not fetch transaction details")
        return

    print(f"\n📊 TRANSACTION DETAILS:")
    print(f"   From:     {tx.get('from')}")
    print(f"   To:       {tx.get('to')}")
    print(f"   Value:    {int(tx.get('value', '0x0'), 16)} wei")
    print(f"   Gas:      {int(tx.get('gas', '0x0'), 16)}")
    print(f"   Gas Price: {int(tx.get('gasPrice', '0x0'), 16)}")
    print(f"   Nonce:    {int(tx.get('nonce', '0x0'), 16)}")

    # Decode input
    input_data = tx.get('input', '')
    decoded = decode_input_data(input_data)
    print(f"\n📝 INPUT DATA:")
    print(f"   Method ID:   {decoded['method_id']}")
    print(f"   Method Name: {decoded['method_name']}")
    print(f"   Raw Input Length: {len(input_data)} chars")

    # Receipt
    if receipt:
        status = int(receipt.get('status', '0x0'), 16)
        print(f"\n✅ RECEIPT:")
        print(f"   Status:     {'✅ SUCCESS' if status == 1 else '❌ FAILED'}")
        print(f"   Block:      {int(receipt.get('blockNumber', '0x0'), 16)}")
        print(f"   Gas Used:   {int(receipt.get('gasUsed', '0x0'), 16)}")

        # Logs (events)
        logs = receipt.get('logs', [])
        print(f"   Events:     {len(logs)} events emitted")
        for i, log in enumerate(logs[:5]):  # Show first 5
            print(f"      [{i}] Address: {log.get('address')}, Topics: {len(log.get('topics', []))}")

    return {
        'tx': tx,
        'receipt': receipt,
        'decoded': decoded
    }

def main():
    print("\n🔍 ANALYZING REDEEM TRANSACTIONS")
    print("="*80)

    # Analyze failed transaction (my bot)
    failed = analyze_transaction(FAILED_TX, "FAILED TX (My Bot)")

    # Analyze successful transaction (competitor)
    success = analyze_transaction(SUCCESS_TX, "SUCCESS TX (Not My Bot)")

    # Compare
    print(f"\n{'='*80}")
    print("🔄 COMPARISON")
    print(f"{'='*80}")

    if failed and success:
        print(f"\n📍 Contract Called:")
        print(f"   Failed:  {failed['tx'].get('to')}")
        print(f"   Success: {success['tx'].get('to')}")

        print(f"\n🔧 Method Called:")
        print(f"   Failed:  {failed['decoded']['method_name']}")
        print(f"   Success: {success['decoded']['method_name']}")

        print(f"\n💰 Value Sent:")
        print(f"   Failed:  {int(failed['tx'].get('value', '0x0'), 16)} wei")
        print(f"   Success: {int(success['tx'].get('value', '0x0'), 16)} wei")

        print(f"\n⛽ Gas:")
        print(f"   Failed:  {int(failed['tx'].get('gas', '0x0'), 16)}")
        print(f"   Success: {int(success['tx'].get('gas', '0x0'), 16)}")

        # Input data comparison
        failed_input = failed['tx'].get('input', '')
        success_input = success['tx'].get('input', '')

        print(f"\n📝 Input Data Length:")
        print(f"   Failed:  {len(failed_input)} chars")
        print(f"   Success: {len(success_input)} chars")

        # Extract parameters (skip method ID, decode rest)
        if len(failed_input) > 10 and len(success_input) > 10:
            failed_params = failed_input[10:]
            success_params = success_input[10:]

            print(f"\n🔢 Parameters Match: {failed_params == success_params}")

            # Show first difference
            if failed_params != success_params:
                for i in range(0, min(len(failed_params), len(success_params)), 64):
                    chunk_f = failed_params[i:i+64]
                    chunk_s = success_params[i:i+64]
                    if chunk_f != chunk_s:
                        print(f"\n   First difference at position {i}:")
                        print(f"      Failed:  {chunk_f}")
                        print(f"      Success: {chunk_s}")
                        break

if __name__ == "__main__":
    main()
