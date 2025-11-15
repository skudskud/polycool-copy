"""
Bridge Configuration
Centralized configuration for bridge operations
Uses settings.py for environment variables
"""
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class BridgeConfig:
    """Bridge configuration using centralized settings"""

    # Solana Configuration
    SOLANA_RPC_URL = settings.web3.solana_rpc_url
    JUPITER_API_KEY = settings.web3.jupiter_api_key

    # deBridge API Configuration
    DEBRIDGE_API_URL = "https://api.dln.trade/v1.0"
    DEBRIDGE_API_KEY = getattr(settings.web3, 'debridge_api_key', None) or ""

    # Chain IDs
    SOLANA_CHAIN_ID = "7565164"  # Solana chain ID in deBridge
    POLYGON_CHAIN_ID = "137"     # Polygon chain ID

    # Token Addresses
    # Solana
    SOL_TOKEN_ADDRESS = "So11111111111111111111111111111111111111112"  # Native SOL
    SOL_MINT = "So11111111111111111111111111111111111111112"  # Native SOL (Jupiter format)
    USDC_SOLANA_ADDRESS = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC on Solana
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC on Solana (Jupiter format)

    # Polygon
    USDC_E_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
    POL_TOKEN_ADDRESS = "0x0000000000000000000000000000000000000000"  # POL native (zero address for deBridge)
    WPOL_ADDRESS = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"  # WPOL (Wrapped POL)
    NATIVE_POL_ADDRESS = "0x0000000000000000000000000000000000001010"  # POL native (system address)

    # QuickSwap Configuration (Polygon)
    QUICKSWAP_ROUTER_V2 = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"  # QuickSwap Router
    QUICKSWAP_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32"

    # Bridge Settings
    MIN_POL_RESERVE = 3.0  # Minimum POL to keep for gas fees
    MAX_SLIPPAGE_PERCENT = 1.0  # 1% max slippage for QuickSwap
    DEBRIDGE_SLIPPAGE_BPS = 3000  # 3000 basis points = 30% slippage for deBridge/Jupiter PreSwap
    BRIDGE_CONFIRMATION_TIMEOUT = 30  # 30 seconds timeout for bridge confirmation
    MIN_SOL_FOR_BRIDGE = 0.1  # Minimum SOL required to start bridge

    # Gas Settings
    POLYGON_GAS_PRICE_GWEI = 150  # Increased for faster confirmation
    SOLANA_PRIORITY_FEE = 5000  # Lamports for priority fee

    # Reserve amounts
    DEBRIDGE_FEE_RESERVE = 0.02  # Reserve SOL for deBridge transaction fees (reduced to use more USDC for variable fees)
    MIN_POL_FOR_GAS = 3.0  # Minimum POL to keep for gas on Polygon (was 2.5, updated to 3.0)

    @classmethod
    def get_debridge_headers(cls) -> dict:
        """Get headers for deBridge API requests"""
        headers = {
            "Content-Type": "application/json",
        }
        if cls.DEBRIDGE_API_KEY:
            headers["Authorization"] = f"Bearer {cls.DEBRIDGE_API_KEY}"
        return headers
