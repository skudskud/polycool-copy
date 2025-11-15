"""
Solana Bridge Integration Module
Handles SOL → USDC.e/POL bridging via deBridge
"""

from .solana_wallet_manager import SolanaWalletManager, solana_wallet_manager
from .debridge_client import DeBridgeClient, debridge_client
from .solana_transaction import SolanaTransactionBuilder
from .quickswap_client import QuickSwapClient, quickswap_client
from .bridge_orchestrator import BridgeOrchestrator, bridge_orchestrator

__all__ = [
    'SolanaWalletManager',
    'solana_wallet_manager',
    'DeBridgeClient',
    'debridge_client',
    'SolanaTransactionBuilder',
    'QuickSwapClient',
    'quickswap_client',
    'BridgeOrchestrator',
    'bridge_orchestrator',
]
