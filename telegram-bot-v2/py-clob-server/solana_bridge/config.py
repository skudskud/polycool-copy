"""
Configuration for Solana Bridge Integration
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from parent directory (py-clob-server/)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# Solana Configuration
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
SOLANA_ADDRESS = os.getenv("SOLANA_ADDRESS", "")
SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY", "")

# Jupiter API (may require API key for production)
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "")

# deBridge API Configuration
DEBRIDGE_API_URL = "https://api.dln.trade/v1.0"
DEBRIDGE_API_KEY = os.getenv("DEBRIDGE_API_KEY", "")  # Optional

# Chain IDs
SOLANA_CHAIN_ID = "7565164"  # Solana chain ID in deBridge
POLYGON_CHAIN_ID = "137"     # Polygon chain ID

# Token Addresses
# Solana
SOL_TOKEN_ADDRESS = "So11111111111111111111111111111111111111112"  # Native SOL

# Polygon
USDC_E_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
POL_TOKEN_ADDRESS = "0x0000000000000000000000000000000000000000"  # POL natif (zero address pour deBridge)
WPOL_ADDRESS = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"  # WPOL (Wrapped POL)
NATIVE_POL_ADDRESS = "0x0000000000000000000000000000000000001010"  # POL natif (adresse système Polygon)

# QuickSwap Configuration (Polygon)
QUICKSWAP_ROUTER_V2 = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"  # QuickSwap Router
QUICKSWAP_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32"

# Bridge Settings
MIN_POL_RESERVE = 3  # Minimum POL to keep for gas fees
MAX_SLIPPAGE_PERCENT = 1.0  # 1% max slippage for QuickSwap
DEBRIDGE_SLIPPAGE_BPS = 3000  # 3000 basis points = 30% slippage pour deBridge/Jupiter PreSwap (éviter erreur 6024)
BRIDGE_CONFIRMATION_TIMEOUT = 30  # 30 seconds timeout for bridge confirmation

# Gas Settings
POLYGON_GAS_PRICE_GWEI = 150  # Increased for faster confirmation (was 50)
SOLANA_PRIORITY_FEE = 5000  # Lamports for priority fee

# Storage
SOLANA_WALLET_STORAGE_FILE = "solana_wallets.json"
BRIDGE_TRANSACTIONS_FILE = "bridge_transactions.json"
