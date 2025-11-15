#!/usr/bin/env python3
"""
QuickSwap DEX Client for Polygon
Handles POL → USDC.e swaps on QuickSwap
"""

import time
from typing import Dict, Optional, Tuple
from web3 import Web3
from eth_account import Account
from .config import (
    QUICKSWAP_ROUTER_V2,
    USDC_E_POLYGON,
    POL_TOKEN_ADDRESS,
    MIN_POL_RESERVE,
    MAX_SLIPPAGE_PERCENT,
    POLYGON_GAS_PRICE_GWEI
)

# QuickSwap Router V2 ABI (minimal, just what we need)
QUICKSWAP_ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokens",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"}
        ],
        "name": "getAmountsOut",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Wrapped POL (WPOL) address on Polygon
WPOL_ADDRESS = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"


class QuickSwapClient:
    """Client for QuickSwap DEX operations on Polygon"""

    def __init__(self, rpc_url: str = "https://polygon-rpc.com"):
        """Initialize QuickSwap client"""
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))

        # Initialize router contract
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(QUICKSWAP_ROUTER_V2),
            abi=QUICKSWAP_ROUTER_ABI
        )

        print(f"✅ QuickSwap client initialized")
        print(f"   Router: {QUICKSWAP_ROUTER_V2}")
        print(f"   Network: {'Connected' if self.w3.is_connected() else 'Disconnected'}")

    def get_pol_balance(self, address: str) -> float:
        """
        Get POL balance for an address

        Args:
            address: Polygon address

        Returns:
            Balance in POL
        """
        try:
            balance_wei = self.w3.eth.get_balance(Web3.to_checksum_address(address))
            balance_pol = self.w3.from_wei(balance_wei, 'ether')

            print(f"💰 POL balance for {address[:10]}...: {balance_pol} POL")
            return float(balance_pol)

        except Exception as e:
            print(f"❌ Error getting POL balance: {e}")
            return 0.0

    def get_usdc_balance(self, address: str) -> float:
        """
        Get USDC.e balance for an address

        Args:
            address: Polygon address

        Returns:
            Balance in USDC.e
        """
        try:
            # ERC20 balanceOf ABI
            erc20_abi = [
                {
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function"
                }
            ]

            usdc_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(USDC_E_POLYGON),
                abi=erc20_abi
            )

            balance = usdc_contract.functions.balanceOf(
                Web3.to_checksum_address(address)
            ).call()

            # USDC.e has 6 decimals
            balance_usdc = balance / 1_000_000

            print(f"💵 USDC.e balance for {address[:10]}...: {balance_usdc} USDC")
            return balance_usdc

        except Exception as e:
            print(f"❌ Error getting USDC balance: {e}")
            return 0.0

    def get_swap_quote(self, pol_amount: float) -> Optional[Dict]:
        """
        Get quote for POL → USDC.e swap

        Args:
            pol_amount: Amount of POL to swap

        Returns:
            Quote with expected USDC output
        """
        try:
            # Convert POL to wei
            pol_wei = self.w3.to_wei(pol_amount, 'ether')

            # Path: POL (native) → WPOL → USDC.e
            path = [
                Web3.to_checksum_address(WPOL_ADDRESS),
                Web3.to_checksum_address(USDC_E_POLYGON)
            ]

            print(f"📊 Getting swap quote for {pol_amount} POL...")

            # Get amounts out from router
            amounts = self.router.functions.getAmountsOut(pol_wei, path).call()

            # amounts[1] is the USDC output (6 decimals)
            usdc_out = amounts[1] / 1_000_000

            # Calculate with slippage
            min_usdc_out = usdc_out * (1 - MAX_SLIPPAGE_PERCENT / 100)

            quote = {
                'pol_in': pol_amount,
                'usdc_out': usdc_out,
                'min_usdc_out': min_usdc_out,
                'slippage_percent': MAX_SLIPPAGE_PERCENT,
                'path': path,
                'timestamp': int(time.time())
            }

            print(f"✅ Quote: {pol_amount} POL → {usdc_out:.2f} USDC.e")
            print(f"   Min output (with {MAX_SLIPPAGE_PERCENT}% slippage): {min_usdc_out:.2f} USDC.e")

            return quote

        except Exception as e:
            print(f"❌ Error getting swap quote: {e}")
            return None

    def swap_pol_to_usdc(
        self,
        pol_amount: float,
        recipient_address: str,
        private_key: str,
        min_usdc_out: Optional[float] = None
    ) -> Optional[str]:
        """
        Execute POL → USDC.e swap on QuickSwap

        Args:
            pol_amount: Amount of POL to swap
            recipient_address: Address to receive USDC.e
            private_key: Private key to sign transaction
            min_usdc_out: Minimum USDC to accept (or None for auto-calculation)

        Returns:
            Transaction hash if successful
        """
        try:
            print(f"🔄 Executing swap: {pol_amount} POL → USDC.e")

            # Get quote if min_usdc_out not provided
            if min_usdc_out is None:
                quote = self.get_swap_quote(pol_amount)
                if not quote:
                    return None
                min_usdc_out = quote['min_usdc_out']
                path = quote['path']
            else:
                path = [
                    Web3.to_checksum_address(WPOL_ADDRESS),
                    Web3.to_checksum_address(USDC_E_POLYGON)
                ]

            # Convert amounts
            pol_wei = self.w3.to_wei(pol_amount, 'ether')
            min_usdc_wei = int(min_usdc_out * 1_000_000)  # USDC has 6 decimals

            # Get account from private key
            account = Account.from_key(private_key)

            # Build transaction
            deadline = int(time.time()) + 600  # 10 minutes from now

            tx = self.router.functions.swapExactETHForTokens(
                min_usdc_wei,
                path,
                Web3.to_checksum_address(recipient_address),
                deadline
            ).build_transaction({
                'from': account.address,
                'value': pol_wei,
                'gas': 300000,
                'gasPrice': self.w3.to_wei(POLYGON_GAS_PRICE_GWEI, 'gwei'),
                'nonce': self.w3.eth.get_transaction_count(account.address),
            })

            # Sign transaction
            signed_tx = account.sign_transaction(tx)

            # Send transaction
            print(f"📡 Broadcasting swap transaction...")
            # web3.py v6+ uses 'raw_transaction' instead of 'rawTransaction'
            raw_tx = signed_tx.raw_transaction if hasattr(signed_tx, 'raw_transaction') else signed_tx.rawTransaction
            tx_hash = self.w3.eth.send_raw_transaction(raw_tx)

            print(f"✅ Swap transaction sent!")
            print(f"   Hash: {tx_hash.hex()}")
            print(f"   View on Polygonscan: https://polygonscan.com/tx/{tx_hash.hex()}")

            # Wait for receipt
            print(f"⏳ Waiting for confirmation...")
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt['status'] == 1:
                print(f"✅ Swap confirmed!")
                return tx_hash.hex()
            else:
                print(f"❌ Swap transaction failed")
                return None

        except Exception as e:
            print(f"❌ Error executing swap: {e}")
            return None

    def auto_swap_excess_pol(
        self,
        address: str,
        private_key: str,
        reserve_pol: float = MIN_POL_RESERVE
    ) -> Optional[Tuple[float, str]]:
        """
        Automatically swap (POL_balance - reserve) → USDC.e

        Args:
            address: Wallet address
            private_key: Private key for signing
            reserve_pol: Amount of POL to keep for gas

        Returns:
            Tuple of (swapped_amount, tx_hash) if successful
        """
        try:
            # Get current POL balance
            pol_balance = self.get_pol_balance(address)

            # Calculate swappable amount
            swappable_pol = pol_balance - reserve_pol

            if swappable_pol <= 0:
                print(f"⚠️ No POL to swap (balance: {pol_balance}, reserve: {reserve_pol})")
                return None

            print(f"🔄 Auto-swapping {swappable_pol} POL (keeping {reserve_pol} POL for gas)")

            # Execute swap
            tx_hash = self.swap_pol_to_usdc(
                pol_amount=swappable_pol,
                recipient_address=address,
                private_key=private_key
            )

            if tx_hash:
                return (swappable_pol, tx_hash)

            return None

        except Exception as e:
            print(f"❌ Error in auto-swap: {e}")
            return None


# Global QuickSwap client instance
quickswap_client = QuickSwapClient()
