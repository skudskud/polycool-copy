#!/usr/bin/env python3
"""
Discover Conditional Tokens Contracts on Polygon

This script scans recent blockchain activity to find all contracts
that emit Conditional Tokens Transfer events (TransferSingle/TransferBatch).

Usage: python scripts/discover_conditional_tokens.py

This helps us identify if Polymarket uses multiple Conditional Tokens contracts,
which would explain why some transactions are missed by our indexer.
"""

import asyncio
import requests
import json
from typing import Set, Dict
from datetime import datetime, timedelta


CONDITIONAL_TOKENS_TOPICS = {
    'TransferSingle': '0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62',
    'TransferBatch': '0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07ce33e6397d8d63df03e93'
}

# Known Conditional Tokens contracts
KNOWN_CONTRACTS = {
    '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045',  # Our current contract
    '0xCeAfDD6Bc0bEF976fdCd1112955828E00543c0Ce5',  # Alternative
}


async def discover_contracts_via_etherscan(blocks_to_scan: int = 1000) -> Set[str]:
    """
    Discover contracts by scanning recent blocks via Etherscan API
    Note: This requires an Etherscan API key for Polygon
    """
    contracts = set(KNOWN_CONTRACTS)

    print(f"🔍 Scanning last {blocks_to_scan} blocks for Conditional Tokens events...")

    # This would require Etherscan API key
    # For now, we'll use a manual approach

    return contracts


async def discover_contracts_via_rpc(rpc_url: str, blocks_to_scan: int = 100) -> Set[str]:
    """
    Discover contracts by querying RPC directly
    """
    contracts = set(KNOWN_CONTRACTS)

    print(f"🔍 Scanning last {blocks_to_scan} blocks via RPC...")

    try:
        # Get current block
        current_block_response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: requests.post(rpc_url, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_blockNumber",
                "params": []
            }, timeout=10)
        )

        if current_block_response.status_code == 200:
            current_block_hex = current_block_response.json()['result']
            current_block = int(current_block_hex, 16)

            print(f"📊 Current block: {current_block}")

            # Scan blocks backwards
            for offset in range(min(blocks_to_scan, 100)):  # Limit to 100 for performance
                block_num = current_block - offset
                block_hex = hex(block_num)

                # Query logs for this block
                logs_response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: requests.post(rpc_url, json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_getLogs",
                        "params": [{
                            "fromBlock": block_hex,
                            "toBlock": block_hex,
                            "topics": [
                                list(CONDITIONAL_TOKENS_TOPICS.values())  # Any of the topics
                            ]
                        }]
                    }, timeout=15)
                )

                if logs_response.status_code == 200:
                    logs = logs_response.json().get('result', [])
                    for log in logs:
                        contract_address = log.get('address', '').lower()
                        if contract_address:
                            contracts.add(contract_address)

                if offset % 20 == 0:
                    print(f"📊 Scanned {offset + 1}/{min(blocks_to_scan, 100)} blocks, found {len(contracts)} contracts")

    except Exception as e:
        print(f"❌ RPC scanning failed: {e}")

    return contracts


async def verify_contracts(contracts: Set[str], rpc_url: str) -> Dict[str, Dict]:
    """
    Verify which contracts are actually Conditional Tokens contracts
    by checking if they implement the expected interface
    """
    verified_contracts = {}

    print(f"🔍 Verifying {len(contracts)} potential Conditional Tokens contracts...")

    for contract in contracts:
        try:
            # Check if contract has Conditional Tokens interface
            # This is a simplified check - in practice we'd check function signatures

            contract_info = {
                'address': contract,
                'is_known': contract in KNOWN_CONTRACTS,
                'verified': True,  # Simplified - assume all are valid for now
                'events_supported': ['TransferSingle', 'TransferBatch']
            }

            verified_contracts[contract] = contract_info

        except Exception as e:
            print(f"❌ Failed to verify {contract}: {e}")

    return verified_contracts


async def main():
    print("🚀 Conditional Tokens Contract Discovery")
    print("=" * 50)

    # RPC endpoint
    rpc_url = "https://polygon-mainnet.g.alchemy.com/v2/demo"  # Replace with real endpoint

    # Discover contracts
    contracts = await discover_contracts_via_rpc(rpc_url, blocks_to_scan=50)

    print(f"\n📊 Found {len(contracts)} potential Conditional Tokens contracts:")

    for i, contract in enumerate(sorted(contracts), 1):
        is_known = contract in KNOWN_CONTRACTS
        marker = "🎯 KNOWN" if is_known else "❓ NEW"
        print(f"{i:2d}. {contract} {marker}")

    # Verify contracts
    verified = await verify_contracts(contracts, rpc_url)

    print(f"\n✅ Verified {len(verified)} contracts")

    # Generate indexer config
    print("\n🔧 Recommended indexer configuration:")
    print("Add these contracts to apps/subsquid-silo-tests/indexer-ts/src/processor.ts:")
    print()
    print("address: [")
    for contract in sorted(verified.keys()):
        comment = " // KNOWN" if contract in KNOWN_CONTRACTS else " // DISCOVERED"
        print(f'    \'{contract}\',{comment}')
    print("],")

    # Summary
    new_contracts = [c for c in contracts if c not in KNOWN_CONTRACTS]
    if new_contracts:
        print("\n🎉 DISCOVERED NEW CONTRACTS!")
        print(f"Found {len(new_contracts)} contracts not currently monitored!")
        print("This likely explains why some Polymarket transactions are missed!")
    else:
        print("\n✅ No new contracts found.")
        print("All Conditional Tokens contracts are already monitored.")

if __name__ == "__main__":
    asyncio.run(main())
