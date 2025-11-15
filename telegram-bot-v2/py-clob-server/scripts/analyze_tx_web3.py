#!/usr/bin/env python3
"""
Analyze redeem transactions using Web3.py directly
"""
from web3 import Web3
import sys

# Polygon RPC
POLYGON_RPC = "https://polygon-rpc.com"

# Transaction hashes
FAILED_TX = "0x1a05d029e973a4d6a38565bd34bac95d25e84a5ae0811efd0077c2a59023c785"  # My bot - FAILED
SUCCESS_TX = "0x360198d0964a7c6b0bc4130b95fd435f2a4aedc4b1d9ce8787beacaf6f46d272"  # Not my bot - SUCCESS

# Method signatures
METHOD_SIGS = {
    "0x26c41411": "redeemPositions(address,bytes32,bytes32,uint256[])",
    "0x095ea7b3": "approve(address,uint256)",
    "0xa9059cbb": "transfer(address,uint256)",
}

def analyze_tx(w3, tx_hash: str, label: str):
    """Analyze a transaction"""
    print(f"\n{'='*100}")
    print(f"{label}")
    print(f"TX: {tx_hash}")
    print(f"{'='*100}")

    try:
        # Get transaction
        tx = w3.eth.get_transaction(tx_hash)

        print(f"\n📊 TRANSACTION:")
        print(f"   From:         {tx['from']}")
        print(f"   To:           {tx['to']}")
        print(f"   Value:        {tx['value']} wei ({w3.from_wei(tx['value'], 'ether')} MATIC)")
        print(f"   Gas Limit:    {tx['gas']:,}")
        print(f"   Gas Price:    {tx['gasPrice']:,} wei")
        print(f"   Nonce:        {tx['nonce']}")
        print(f"   Block:        {tx.get('blockNumber', 'Pending')}")

        # Decode input
        input_data = tx['input'].hex()
        method_id = input_data[:10]
        method_name = METHOD_SIGS.get(method_id, f"Unknown ({method_id})")

        print(f"\n📝 METHOD CALL:")
        print(f"   Method ID:    {method_id}")
        print(f"   Method:       {method_name}")
        print(f"   Input Length: {len(input_data)} chars ({len(input_data) // 2} bytes)")

        # Get receipt
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)

            status = "✅ SUCCESS" if receipt['status'] == 1 else "❌ FAILED"
            print(f"\n💰 RECEIPT:")
            print(f"   Status:       {status}")
            print(f"   Block:        {receipt['blockNumber']}")
            print(f"   Gas Used:     {receipt['gasUsed']:,} / {tx['gas']:,} ({receipt['gasUsed']/tx['gas']*100:.1f}%)")
            print(f"   Logs/Events:  {len(receipt['logs'])} events")

            # Show first few events
            for i, log in enumerate(receipt['logs'][:3]):
                print(f"      Event {i}: Address={log['address']}, Topics={len(log['topics'])}")

        except Exception as e:
            print(f"\n⚠️ Could not get receipt: {e}")

        return {
            'tx': tx,
            'input': input_data,
            'method_id': method_id,
            'receipt': receipt if 'receipt' in locals() else None
        }

    except Exception as e:
        print(f"❌ Error analyzing transaction: {e}")
        return None

def compare_inputs(input1: str, input2: str):
    """Compare two transaction inputs"""
    print(f"\n{'='*100}")
    print("🔄 INPUT COMPARISON")
    print(f"{'='*100}")

    method1 = input1[:10]
    method2 = input2[:10]

    print(f"\n   Method IDs Match: {method1 == method2} ({method1} vs {method2})")

    params1 = input1[10:]
    params2 = input2[10:]

    print(f"\n   Params Match: {params1 == params2}")
    print(f"   Params Length: {len(params1)} vs {len(params2)} chars")

    if params1 != params2:
        print(f"\n   Finding first difference...")
        # Compare in 64-char chunks (32 bytes = 1 EVM word)
        for i in range(0, min(len(params1), len(params2)), 64):
            chunk1 = params1[i:i+64]
            chunk2 = params2[i:i+64]

            if chunk1 != chunk2:
                print(f"\n   ❌ DIFFERENCE at position {i//64} (byte offset {i//2}):")
                print(f"      Failed:  {chunk1}")
                print(f"      Success: {chunk2}")

                # Try to interpret as different types
                try:
                    val1 = int(chunk1, 16)
                    val2 = int(chunk2, 16)
                    print(f"      As uint256: {val1} vs {val2}")
                except:
                    pass

                print()  # Add spacing

                # Show next few chunks for context
                for j in range(1, 3):
                    next_i = i + j*64
                    if next_i < min(len(params1), len(params2)):
                        print(f"   Position {next_i//64}:")
                        print(f"      Failed:  {params1[next_i:next_i+64]}")
                        print(f"      Success: {params2[next_i:next_i+64]}")

                break
        else:
            # One is longer
            if len(params1) != len(params2):
                print(f"\n   ⚠️ Different lengths!")
                longer = params1 if len(params1) > len(params2) else params2
                shorter = params2 if len(params1) > len(params2) else params1
                extra = longer[len(shorter):]
                print(f"      Extra data: {extra[:128]}...")

def main():
    print("\n🔍 ANALYZING REDEEM TRANSACTIONS WITH WEB3.PY")

    # Connect to Polygon
    print(f"\n🔗 Connecting to Polygon RPC...")
    w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))

    if not w3.is_connected():
        print(f"❌ Failed to connect to Polygon RPC")
        return

    print(f"✅ Connected! Chain ID: {w3.eth.chain_id}")

    # Analyze failed transaction
    failed = analyze_tx(w3, FAILED_TX, "❌ FAILED TRANSACTION (My Bot - Nov 4 12:30-12:45PM)")

    # Analyze successful transaction
    success = analyze_tx(w3, SUCCESS_TX, "✅ SUCCESS TRANSACTION (Not My Bot - Nov 5 6:45-7AM)")

    # Compare
    if failed and success:
        print(f"\n{'='*100}")
        print("📊 HIGH-LEVEL COMPARISON")
        print(f"{'='*100}")

        print(f"\n🏦 Contract Called:")
        print(f"   Failed:  {failed['tx']['to']}")
        print(f"   Success: {success['tx']['to']}")
        print(f"   Same Contract: {failed['tx']['to'] == success['tx']['to']}")

        print(f"\n🔧 Method Called:")
        print(f"   Failed:  {METHOD_SIGS.get(failed['method_id'], failed['method_id'])}")
        print(f"   Success: {METHOD_SIGS.get(success['method_id'], success['method_id'])}")
        print(f"   Same Method: {failed['method_id'] == success['method_id']}")

        # Compare inputs in detail
        compare_inputs(failed['input'], success['input'])

        # Final summary
        print(f"\n{'='*100}")
        print("📋 SUMMARY")
        print(f"{'='*100}")

        if failed['receipt'] and success['receipt']:
            print(f"\n   ❌ Failed TX:  {failed['receipt']['status']} (status={failed['receipt']['status']})")
            print(f"   ✅ Success TX: {success['receipt']['status']} (status={success['receipt']['status']})")

            print(f"\n   Gas Usage:")
            print(f"      Failed:  {failed['receipt']['gasUsed']:,}")
            print(f"      Success: {success['receipt']['gasUsed']:,}")

if __name__ == "__main__":
    main()
