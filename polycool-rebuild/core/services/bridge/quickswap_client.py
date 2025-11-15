"""
QuickSwap Client - POL to USDC.e Swap on Polygon
Handles POL → USDC.e swaps on QuickSwap DEX
Adapted from telegram-bot-v2 for new architecture
"""
import time
from typing import Dict, Optional, Tuple
from web3 import Web3
from eth_account import Account

from .config import BridgeConfig
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Try to import web3 middleware with fallbacks
try:
    from web3.middleware import geth_poa_middleware
except ImportError:
    # Fallback for newer web3 versions
    try:
        from web3.middleware.geth_poa import geth_poa_middleware
    except ImportError:
        # Last resort fallback
        geth_poa_middleware = None
        logger.warning("⚠️ geth_poa_middleware not available, Polygon RPC calls may fail")

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


class QuickSwapClient:
    """QuickSwap client for POL → USDC.e swaps on Polygon"""

    def __init__(self, rpc_url: Optional[str] = None):
        """Initialize QuickSwap client"""
        self.rpc_url = rpc_url or settings.web3.polygon_rpc_url
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

        # Inject POA middleware for Polygon (required for extraData handling)
        if geth_poa_middleware is not None:
            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        else:
            logger.warning("⚠️ Skipping geth_poa_middleware injection - Polygon RPC may have issues")

        if not self.w3.is_connected():
            raise RuntimeError(f"Failed to connect to Polygon RPC: {self.rpc_url}")

        # Initialize router contract
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(BridgeConfig.QUICKSWAP_ROUTER_V2),
            abi=QUICKSWAP_ROUTER_ABI
        )

        logger.info(f"✅ QuickSwap client initialized (POA middleware enabled)")
        logger.info(f"   Router: {BridgeConfig.QUICKSWAP_ROUTER_V2}")

    def get_pol_balance(self, address: str) -> float:
        """Get POL balance for an address"""
        try:
            balance_wei = self.w3.eth.get_balance(Web3.to_checksum_address(address))
            balance_pol = self.w3.from_wei(balance_wei, 'ether')
            return float(balance_pol)
        except Exception as e:
            logger.error(f"❌ Error fetching POL balance: {e}")
            return 0.0

    def get_usdc_e_balance(self, address: str) -> float:
        """Get USDC.e balance for an address"""
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
                address=Web3.to_checksum_address(BridgeConfig.USDC_E_POLYGON),
                abi=erc20_abi
            )

            balance = usdc_contract.functions.balanceOf(
                Web3.to_checksum_address(address)
            ).call()

            # USDC.e has 6 decimals
            balance_usdc = balance / 1_000_000
            return balance_usdc

        except Exception as e:
            logger.error(f"❌ Error getting USDC.e balance: {e}")
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

            # For POL → USDC.e, we need to go through WPOL (Wrapped POL)
            # Path: WPOL → USDC.e (since we're sending POL as value, it gets wrapped automatically)
            path = [
                Web3.to_checksum_address(BridgeConfig.WPOL_ADDRESS),  # WPOL
                Web3.to_checksum_address(BridgeConfig.USDC_E_POLYGON)  # USDC.e
            ]

            logger.info(f"📊 Getting swap quote for {pol_amount} POL...")
            logger.info(f"   Path: POL (native) → WPOL → USDC.e")

            # Get amounts out from router
            amounts = self.router.functions.getAmountsOut(pol_wei, path).call()

            # amounts[1] is the USDC output (6 decimals)
            usdc_out = amounts[1] / 1_000_000

            # Calculate with slippage
            min_usdc_out = usdc_out * (1 - BridgeConfig.MAX_SLIPPAGE_PERCENT / 100)

            quote = {
                'pol_in': pol_amount,
                'usdc_out': usdc_out,
                'min_usdc_out': min_usdc_out,
                'slippage_percent': BridgeConfig.MAX_SLIPPAGE_PERCENT,
                'path': path,
                'timestamp': int(time.time())
            }

            logger.info(f"✅ Quote: {pol_amount} POL → {usdc_out:.2f} USDC.e")
            logger.info(f"   Min output (with {BridgeConfig.MAX_SLIPPAGE_PERCENT}% slippage): {min_usdc_out:.2f} USDC.e")

            return quote

        except Exception as e:
            logger.error(f"❌ Error getting swap quote: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def swap_pol_to_usdc_e(
        self,
        polygon_address: str,
        polygon_private_key: str,
        pol_amount: float,
        slippage_percent: Optional[float] = None
    ) -> Optional[Dict]:
        """
        Execute POL → USDC.e swap on QuickSwap

        Args:
            polygon_address: Polygon wallet address
            polygon_private_key: Polygon private key (decrypted)
            pol_amount: Amount of POL to swap
            slippage_percent: Slippage tolerance (default: from config)

        Returns:
            Dict with success, tx_hash, and usdc_e_received, or None if failed
        """
        try:
            logger.info(f"🔄 Executing swap: {pol_amount:.4f} POL → USDC.e")

            # Use config slippage if not provided
            if slippage_percent is None:
                slippage_percent = BridgeConfig.MAX_SLIPPAGE_PERCENT

            # Get quote
            quote = self.get_swap_quote(pol_amount)
            if not quote:
                logger.error("❌ Failed to get swap quote")
                return None

            min_usdc_out = quote['min_usdc_out']
            path = quote['path']

            # Convert amounts
            pol_wei = self.w3.to_wei(pol_amount, 'ether')
            min_usdc_wei = int(min_usdc_out * 1_000_000)  # USDC has 6 decimals

            # Get account from private key
            account = Account.from_key(polygon_private_key)

            # Verify address matches
            if account.address.lower() != polygon_address.lower():
                logger.error(f"❌ Address mismatch: {account.address} != {polygon_address}")
                return None

            # Check POL balance to ensure we have enough for swap + gas
            pol_balance_wei = self.w3.eth.get_balance(account.address)
            pol_balance = self.w3.from_wei(pol_balance_wei, 'ether')
            logger.info(f"💰 Current POL balance: {pol_balance:.4f} POL")

            # Verify we have enough POL for the swap
            if pol_balance < pol_amount:
                logger.error(f"❌ Insufficient POL balance: {pol_balance:.4f} < {pol_amount:.4f}")
                return None

            # Build transaction
            deadline = int(time.time()) + 600  # 10 minutes from now

            # Get current gas price using EIP-1559 (Polygon uses dynamic base fee)
            try:
                # Get base fee from pending block
                base_fee_wei = self.w3.eth.get_block('pending')['baseFeePerGas']
                base_fee_gwei = float(self.w3.from_wei(base_fee_wei, 'gwei'))

                # Get recommended priority fee from network (if available)
                try:
                    # Try to get the network-recommended max priority fee
                    max_priority_fee_wei = self.w3.eth.max_priority_fee
                    max_priority_fee_gwei = float(self.w3.from_wei(max_priority_fee_wei, 'gwei'))
                    priority_fee_gwei = max(max_priority_fee_gwei, 30.0)  # Minimum 30 gwei
                    logger.info(f"⛽ Using network-recommended priority fee: {max_priority_fee_gwei:.1f} gwei")
                except:
                    # Fallback to Polygon-typical priority fee (30-50 gwei)
                    priority_fee_gwei = 40.0
                    logger.info(f"⛽ Using fallback priority fee: {priority_fee_gwei:.1f} gwei")

                # maxFeePerGas = baseFee + priorityFee + buffer (10 gwei buffer)
                max_fee_per_gas_gwei = base_fee_gwei + priority_fee_gwei + 10
                max_fee_per_gas = self.w3.to_wei(max_fee_per_gas_gwei, 'gwei')

                # maxPriorityFeePerGas
                max_priority_fee_per_gas = self.w3.to_wei(priority_fee_gwei, 'gwei')

                logger.info(f"⛽ EIP-1559: baseFee={base_fee_gwei:.1f}gwei, maxFee={max_fee_per_gas_gwei:.1f}gwei, priorityFee={priority_fee_gwei:.1f}gwei")
            except Exception as gas_error:
                logger.warning(f"⚠️ Could not get EIP-1559 gas prices: {gas_error}, using legacy gasPrice")
                # Fallback to legacy gas pricing
                try:
                    current_gas_price_wei = self.w3.eth.gas_price
                    current_gas_price_gwei = float(self.w3.from_wei(current_gas_price_wei, 'gwei'))
                    max_fee_per_gas = self.w3.to_wei(max(current_gas_price_gwei * 1.5, 100), 'gwei')  # Higher minimum
                    max_priority_fee_per_gas = self.w3.to_wei(30, 'gwei')  # 30 gwei priority
                except:
                    max_fee_per_gas = self.w3.to_wei(150, 'gwei')  # Default high gas price
                    max_priority_fee_per_gas = self.w3.to_wei(30, 'gwei')

            # Estimate gas more accurately
            # Note: estimate_gas checks if we have enough funds for gas + value
            # We use a small symbolic value (1 POL) for estimation since the gas cost
            # doesn't depend on the swap amount - we just need to estimate the gas units
            # The actual swap amount will be used in the real transaction
            gas_limit = None
            try:
                # Use a small symbolic value for gas estimation (1 POL)
                # This avoids the "insufficient funds" check while still getting accurate gas estimate
                symbolic_value_wei = self.w3.to_wei(1.0, 'ether')

                estimated_gas = self.router.functions.swapExactETHForTokens(
                    min_usdc_wei,
                    path,
                    Web3.to_checksum_address(polygon_address),
                    deadline
                ).estimate_gas({
                    'from': account.address,
                    'value': symbolic_value_wei,  # Use symbolic value for estimation
                    'maxFeePerGas': max_fee_per_gas,
                    'maxPriorityFeePerGas': max_priority_fee_per_gas
                })
                gas_limit = int(estimated_gas * 1.2)  # 20% buffer
                logger.info(f"⛽ Estimated gas: {estimated_gas}, using limit: {gas_limit}")

                # Verify we have enough POL for gas after swap
                remaining_pol_wei = pol_balance_wei - pol_wei
                gas_cost_wei = gas_limit * max_fee_per_gas
                if remaining_pol_wei < gas_cost_wei:
                    logger.warning(f"⚠️ Gas cost ({self.w3.from_wei(gas_cost_wei, 'ether'):.4f} POL) exceeds remaining POL ({self.w3.from_wei(remaining_pol_wei, 'ether'):.4f} POL)")
                    # Reduce gas limit to what we can afford (with 80% safety margin)
                    max_affordable_gas = int((remaining_pol_wei * 0.8) // max_fee_per_gas)
                    if max_affordable_gas < 100000:  # Minimum reasonable gas
                        logger.error(f"❌ Not enough POL for gas! Need at least {self.w3.from_wei(100000 * max_fee_per_gas, 'ether'):.4f} POL")
                        return None
                    gas_limit = max_affordable_gas
                    logger.info(f"   Adjusted gas limit to affordable amount: {gas_limit}")

            except Exception as gas_est_error:
                # If estimation fails, use a default and verify we can afford it
                logger.warning(f"⚠️ Could not estimate gas: {gas_est_error}, using default")
                gas_limit = 500000  # Default for complex swaps

                # Verify we can afford the default gas limit
                remaining_pol_wei = pol_balance_wei - pol_wei
                gas_cost_wei = gas_limit * max_fee_per_gas
                if remaining_pol_wei < gas_cost_wei:
                    # Calculate max affordable gas
                    max_affordable_gas = int((remaining_pol_wei * 0.8) // max_fee_per_gas)
                    if max_affordable_gas < 100000:
                        logger.error(f"❌ Not enough POL for gas! Need at least {self.w3.from_wei(100000 * max_fee_per_gas, 'ether'):.4f} POL")
                        return None
                    gas_limit = max_affordable_gas
                    logger.info(f"   Using affordable gas limit: {gas_limit}")

            # Get current nonce and check for pending transactions
            current_nonce = self.w3.eth.get_transaction_count(account.address, 'pending')
            latest_nonce = self.w3.eth.get_transaction_count(account.address, 'latest')

            if current_nonce > latest_nonce:
                logger.warning(f"⚠️ Pending transaction detected! Waiting for nonce {latest_nonce} to be mined...")
                logger.info(f"   Current pending nonce: {current_nonce}, Latest mined: {latest_nonce}")
                # Wait up to 30 seconds for pending tx to be mined
                for wait_attempt in range(6):
                    time.sleep(5)
                    new_latest = self.w3.eth.get_transaction_count(account.address, 'latest')
                    if new_latest >= current_nonce:
                        logger.info(f"✅ Pending transaction mined! New nonce: {new_latest}")
                        current_nonce = self.w3.eth.get_transaction_count(account.address, 'pending')
                        break
                    logger.info(f"   Still waiting... ({(wait_attempt + 1) * 5}s / 30s)")
                else:
                    logger.warning(f"⚠️ Pending transaction not mined after 30s, will use nonce {current_nonce}")

            tx = self.router.functions.swapExactETHForTokens(
                min_usdc_wei,
                path,
                Web3.to_checksum_address(polygon_address),
                deadline
            ).build_transaction({
                'from': account.address,
                'value': pol_wei,
                'gas': gas_limit,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee_per_gas,
                'nonce': current_nonce,
                'chainId': 137  # Polygon mainnet
            })

            logger.info(f"💰 Transaction value: {pol_amount} POL ({pol_wei} wei)")
            logger.info(f"🎯 Min USDC out: {min_usdc_out:.2f} ({min_usdc_wei} micro USDC)")
            logger.info(f"🛣️  Swap path: {[p for p in path]}")

            # Sign transaction
            signed_tx = account.sign_transaction(tx)

            # Send transaction
            logger.info(f"📡 Broadcasting swap transaction...")
            logger.info(f"   POL amount: {pol_amount:.4f}")
            logger.info(f"   Min USDC out: {min_usdc_out:.2f}")

            # web3.py v6+ uses 'raw_transaction' instead of 'rawTransaction'
            raw_tx = signed_tx.raw_transaction if hasattr(signed_tx, 'raw_transaction') else signed_tx.rawTransaction
            tx_hash = self.w3.eth.send_raw_transaction(raw_tx)

            logger.info(f"✅ Swap transaction sent!")
            logger.info(f"   Hash: {tx_hash.hex()}")
            logger.info(f"   View on Polygonscan: https://polygonscan.com/tx/{tx_hash.hex()}")

            # Wait for receipt with retry logic
            logger.info(f"⏳ Waiting for confirmation...")
            max_wait_time = 180  # 3 minutes total
            poll_interval = 5   # Check every 5 seconds

            receipt = None
            for attempt in range(max_wait_time // poll_interval):
                try:
                    receipt = self.w3.eth.get_transaction_receipt(tx_hash)
                    if receipt is not None:
                        logger.info(f"✅ Transaction confirmed after {attempt * poll_interval}s!")
                        break
                except Exception:
                    pass  # Transaction not yet mined

                if attempt < (max_wait_time // poll_interval) - 1:
                    logger.info(f"⏳ Still waiting... ({(attempt + 1) * poll_interval}s / {max_wait_time}s)")
                    time.sleep(poll_interval)

            if receipt is None:
                logger.error(f"❌ Transaction not found after {max_wait_time} seconds")
                return {
                    'success': False,
                    'tx_hash': tx_hash.hex(),
                    'error': f'Transaction not found after {max_wait_time} seconds'
                }

            # Process the receipt
            logger.info(f"📄 Receipt received - Status: {receipt['status']}")

            if receipt['status'] == 1:
                logger.info(f"✅ Swap confirmed!")
                logger.info(f"   Gas used: {receipt['gasUsed']}")
                logger.info(f"   Block number: {receipt['blockNumber']}")

                # Try to get actual USDC.e balance to verify swap
                final_balance = self.get_usdc_e_balance(polygon_address)
                initial_balance = self.get_usdc_e_balance(polygon_address)  # This will be approximate

                # Estimate received amount from quote
                usdc_e_received = quote['usdc_out']

                return {
                    'success': True,
                    'tx_hash': tx_hash.hex(),
                    'usdc_e_received': usdc_e_received,
                    'pol_swapped': pol_amount,
                    'quote': quote,
                    'receipt': {
                        'gas_used': receipt['gasUsed'],
                        'block_number': receipt['blockNumber'],
                        'status': receipt['status']
                    }
                }
            else:
                logger.error(f"❌ Swap failed! Transaction status: {receipt['status']}")
                return {
                    'success': False,
                    'tx_hash': tx_hash.hex(),
                    'error': f'Transaction failed with status {receipt["status"]}',
                    'receipt': receipt
                }

        except Exception as e:
            logger.error(f"❌ Error executing swap: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e)
            }


# Global instance
_quickswap_client: Optional[QuickSwapClient] = None


def get_quickswap_client() -> QuickSwapClient:
    """Get or create QuickSwapClient instance"""
    global _quickswap_client
    if _quickswap_client is None:
        _quickswap_client = QuickSwapClient()
    return _quickswap_client
