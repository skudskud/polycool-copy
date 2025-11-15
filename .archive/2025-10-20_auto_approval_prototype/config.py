#!/usr/bin/env python3
"""
Auto-Approval Prototype Configuration
Isolated test configuration for event-driven wallet funding detection
"""

# Blockchain Configuration - Using Alchemy (better rate limits)
POLYGON_RPC_HTTP = "https://polygon-mainnet.g.alchemy.com/v2/demo"
POLYGON_RPC_WSS = "wss://polygon-mainnet.g.alchemy.com/v2/demo"
CHAIN_ID = 137  # Polygon Mainnet

# Contract Addresses (Polygon Mainnet)
USDC_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e
POLYMARKET_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# Exchange contracts to approve (from official docs)
EXCHANGE_CONTRACTS = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",  # Main exchange
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",  # Neg risk markets
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",  # Neg risk adapter
]

# Funding Requirements - MODIFIED FOR TESTING
MIN_USDC_BALANCE = 0.0   # Skip USDC.e requirement for testing
MIN_POL_BALANCE = 0.01   # 0.01 POL minimum for gas

# Event Monitoring Configuration
EVENT_CHECK_INTERVAL = 5  # Check for new events every 5 seconds (avoid rate limits)
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY = 5  # seconds

# Logging Configuration
LOG_LEVEL = "INFO"
ENABLE_DEBUG_LOGS = True

# Test Configuration
TEST_WALLET_STORAGE = "test_wallet.json"
TEST_LOG_FILE = "test_results/prototype_test.log"
