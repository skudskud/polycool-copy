#!/usr/bin/env python3
from web3 import Web3
from datetime import datetime

POLYGON_RPC = "https://polygon-rpc.com"
w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))

# Check failed tx block
block_number = 78618113
block = w3.eth.get_block(block_number)
timestamp = datetime.fromtimestamp(block['timestamp'])

print(f"Block {block_number}:")
print(f"  Timestamp: {timestamp} UTC")
print(f"  Transactions: {len(block['transactions'])}")
