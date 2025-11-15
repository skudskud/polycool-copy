"""
Bridge Service - Main orchestrator for SOL → USDC → POL bridge
Integrates with UserService and EncryptionService
Adapted from bridge_v3.py for new architecture
"""
import asyncio
import time
from typing import Dict, Optional, Callable
from solders.keypair import Keypair
import base58

from .config import BridgeConfig
from .jupiter_client import JupiterClient, get_jupiter_client
from .debridge_client import DeBridgeClient, get_debridge_client
from .solana_transaction import SolanaTransactionBuilder
from .quickswap_client import QuickSwapClient, get_quickswap_client
from core.services.user.user_service import UserService
from core.services.encryption.encryption_service import encryption_service
from core.services.approval.approval_service import ApprovalService, get_approval_service
from core.services.api.api_key_manager import ApiKeyManager, get_api_key_manager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class BridgeService:
    """Main bridge service orchestrating SOL → USDC → POL workflow"""

    def __init__(self):
        """Initialize bridge service"""
        self.jupiter_client = get_jupiter_client()
        self.debridge_client = get_debridge_client()
        self.solana_builder = SolanaTransactionBuilder()
        self.quickswap_client = get_quickswap_client()
        self.approval_service = get_approval_service()
        self.api_key_manager = get_api_key_manager()
        self.user_service = UserService()

    async def get_sol_balance(self, address: str) -> float:
        """
        Get SOL balance for an address

        Returns:
            Balance in SOL, or 0.0 if error (graceful degradation)
        """
        try:
            return await self.solana_builder.get_sol_balance(address)
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch SOL balance for {address[:10]}...: {e}")
            # Return 0.0 to allow handler to continue (will show "Check Balance" button)
            return 0.0

    async def get_usdc_balance(self, address: str) -> float:
        """Get USDC balance on Solana with ATA handling"""
        try:
            import requests
            from solders.pubkey import Pubkey
            from solders.system_program import ID as SYSTEM_PROGRAM_ID
            from spl.token.constants import TOKEN_PROGRAM_ID
            import spl.token.instructions as spl_token

            logger.info(f"💰 Fetching USDC balance for {address[:16]}...")

            # First, get or create the Associated Token Account (ATA) address
            owner_pubkey = Pubkey.from_string(address)
            mint_pubkey = Pubkey.from_string(BridgeConfig.USDC_SOLANA_ADDRESS)

            # Calculate ATA address
            ata_pubkey = spl_token.get_associated_token_address(owner_pubkey, mint_pubkey)
            ata_address = str(ata_pubkey)
            logger.info(f"   ATA address: {ata_address}")

            # Check if ATA exists by querying its balance
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountBalance",
                "params": [ata_address]
            }

            response = requests.post(
                self.solana_builder.rpc_url,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            result = response.json()

            if 'result' in result and result['result'] and 'value' in result['result']:
                token_amount = result['result']['value']
                balance_usdc = float(token_amount['uiAmount'])
                logger.info(f"✅ USDC balance: {balance_usdc:.6f} USDC (via ATA)")
                return balance_usdc

            # If ATA doesn't exist or has no balance, check all token accounts
            logger.info(f"   ATA not found or empty, checking all token accounts...")

            payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "getTokenAccountsByOwner",
                "params": [
                    address,
                    {"mint": BridgeConfig.USDC_SOLANA_ADDRESS},
                    {"encoding": "jsonParsed"}
                ]
            }

            response = requests.post(
                self.solana_builder.rpc_url,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            result = response.json()

            if 'result' in result and result['result'] and 'value' in result['result']:
                accounts = result['result']['value']

                if accounts and len(accounts) > 0:
                    logger.info(f"   Found {len(accounts)} token account(s)")
                    for i, account in enumerate(accounts):
                        token_amount = account['account']['data']['parsed']['info']['tokenAmount']
                        balance_usdc = float(token_amount['uiAmount'])
                        logger.info(f"   Account {i+1}: {balance_usdc:.6f} USDC")
                        if balance_usdc > 0:
                            return balance_usdc

            logger.info(f"💰 No USDC balance found (ATA: {ata_address})")
            return 0.0

        except Exception as e:
            logger.error(f"❌ Error fetching USDC balance: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 0.0

    def get_pol_balance(self, address: str) -> float:
        """Get POL balance on Polygon"""
        try:
            from web3 import Web3
            from infrastructure.config.settings import settings

            w3 = Web3(Web3.HTTPProvider(settings.web3.polygon_rpc_url))
            balance_wei = w3.eth.get_balance(address)
            balance_pol = balance_wei / 1e18

            logger.info(f"💰 POL balance for {address[:10]}...: {balance_pol:.4f} POL")
            return balance_pol

        except Exception as e:
            logger.error(f"❌ Error fetching POL balance: {e}")
            return 0.0

    async def wait_for_pol_arrival(
        self,
        polygon_address: str,
        starting_balance: float,
        expected_increase: float,
        timeout: int = 300,
        status_callback: Optional[Callable] = None
    ) -> Optional[float]:
        """
        Wait for POL to arrive on Polygon after deBridge

        Args:
            polygon_address: Polygon address to check
            starting_balance: POL balance BEFORE bridge started
            expected_increase: Minimum POL increase expected from bridge
            timeout: Max wait time in seconds (default 5 min)
            status_callback: Optional callback for status updates

        Returns:
            POL balance if arrived, None if timeout
        """
        try:
            logger.info(f"⏳ Waiting for POL arrival on Polygon...")
            logger.info(f"   Starting balance: {starting_balance:.4f} POL")
            logger.info(f"   Expected increase: +{expected_increase:.2f} POL")

            start_time = time.time()
            check_interval = 10  # Check every 10 seconds

            while time.time() - start_time < timeout:
                current_balance = self.get_pol_balance(polygon_address)
                balance_increase = current_balance - starting_balance

                # Check if we received enough POL
                if balance_increase >= expected_increase:
                    logger.info(f"✅ POL arrived! Balance increased by {balance_increase:.4f} POL")
                    if status_callback:
                        await status_callback(
                            f"✅ POL received on Polygon!\n\n"
                            f"Balance: {current_balance:.4f} POL\n"
                            f"Increase: +{balance_increase:.4f} POL"
                        )
                    return current_balance

                elapsed = int(time.time() - start_time)
                if elapsed % 30 == 0 and status_callback:  # Update every 30s
                    await status_callback(
                        f"⏳ Waiting for POL... ({elapsed}s / {timeout}s)\n\n"
                        f"Starting: {starting_balance:.4f} POL\n"
                        f"Current: {current_balance:.4f} POL\n"
                        f"Increase: +{balance_increase:.4f} POL\n"
                        f"Expected: +{expected_increase:.2f} POL"
                    )

                await asyncio.sleep(check_interval)

            logger.error(f"⏰ Timeout waiting for POL ({timeout}s)")
            return None

        except Exception as e:
            logger.error(f"❌ Error waiting for POL: {e}")
            return None

    async def execute_bridge(
        self,
        telegram_user_id: int,
        sol_amount: float,
        status_callback: Optional[Callable] = None
    ) -> Dict:
        """
        Execute complete bridge: SOL → USDC → POL

        Args:
            telegram_user_id: Telegram user ID
            sol_amount: Amount of SOL to bridge
            status_callback: Optional callback for status updates (async)

        Returns:
            Result dict with success status, signatures, and amounts
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🌉 BRIDGE: SOL → USDC → POL")
            logger.info(f"   User: {telegram_user_id}")
            logger.info(f"   Amount: {sol_amount:.6f} SOL")
            logger.info(f"{'='*60}\n")

            # Step 1: Get user and decrypt keys
            if status_callback:
                await status_callback("🔐 Loading wallet...")

            import os
            SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

            user_data = None
            user = None

            if SKIP_DB:
                from core.services.user.user_helper import get_user_data
                from core.services.api_client import get_api_client

                user_data = await get_user_data(telegram_user_id)
                if not user_data:
                    error_msg = "❌ User not found. Please run /start first."
                    logger.error(error_msg)
                    return {'success': False, 'error': 'user_not_found'}
            else:
                user = await self.user_service.get_by_telegram_id(telegram_user_id)
                if not user:
                    error_msg = "❌ User not found. Please run /start first."
                    logger.error(error_msg)
                    return {'success': False, 'error': 'user_not_found'}

            # Get addresses and private keys
            solana_address = None
            polygon_address = None
            solana_private_key = None

            if SKIP_DB:
                solana_address = user_data.get('solana_address')
                polygon_address = user_data.get('polygon_address')

                if not solana_address:
                    error_msg = "❌ Solana wallet not found. Please complete onboarding."
                    logger.error(error_msg)
                    return {'success': False, 'error': 'wallet_not_found'}

                if not polygon_address:
                    error_msg = "❌ Polygon wallet not found. Please complete onboarding."
                    logger.error(error_msg)
                    return {'success': False, 'error': 'polygon_wallet_not_found'}

                # Get private keys via API (already decrypted)
                api_client = get_api_client()
                solana_private_key = await api_client.get_private_key(telegram_user_id, "solana")

                if not solana_private_key:
                    error_msg = "❌ Failed to retrieve Solana private key"
                    logger.error(error_msg)
                    return {'success': False, 'error': 'decryption_failed'}
            else:
                if not user.solana_address or not user.solana_private_key:
                    error_msg = "❌ Solana wallet not found. Please complete onboarding."
                    logger.error(error_msg)
                    return {'success': False, 'error': 'wallet_not_found'}

                if not user.polygon_address:
                    error_msg = "❌ Polygon wallet not found. Please complete onboarding."
                    logger.error(error_msg)
                    return {'success': False, 'error': 'polygon_wallet_not_found'}

                # Decrypt private keys
                solana_private_key = encryption_service.decrypt_private_key(user.solana_private_key)
                if not solana_private_key:
                    error_msg = "❌ Failed to decrypt Solana private key"
                    logger.error(error_msg)
                    return {'success': False, 'error': 'decryption_failed'}

                solana_address = user.solana_address
                polygon_address = user.polygon_address

            logger.info(f"   Solana address: {solana_address}")
            logger.info(f"   Polygon address: {polygon_address}")

            # Step 2: Check SOL balance
            if status_callback:
                await status_callback("💰 Checking SOL balance...")

            balance = await self.get_sol_balance(solana_address)
            logger.info(f"   Current balance: {balance:.6f} SOL")

            if balance < BridgeConfig.MIN_SOL_FOR_BRIDGE:
                error_msg = (
                    f"❌ Insufficient SOL balance!\n\n"
                    f"Balance: {balance:.6f} SOL\n"
                    f"Minimum required: {BridgeConfig.MIN_SOL_FOR_BRIDGE} SOL"
                )
                logger.error(error_msg)
                return {'success': False, 'error': 'insufficient_sol', 'balance': balance}

            # Calculate actual swap amount (reserve for fees)
            max_swappable = balance - BridgeConfig.DEBRIDGE_FEE_RESERVE
            if sol_amount > max_swappable:
                logger.warning(f"⚠️ Adjusting swap amount to leave SOL for fees")
                actual_swap_amount = max_swappable
            else:
                actual_swap_amount = sol_amount

            if actual_swap_amount < 0.01:
                error_msg = (
                    f"❌ Insufficient SOL after fee reserve!\n\n"
                    f"Balance: {balance:.6f} SOL\n"
                    f"Reserve: {BridgeConfig.DEBRIDGE_FEE_RESERVE:.6f} SOL\n"
                    f"Available: {actual_swap_amount:.6f} SOL\n"
                    f"Minimum: 0.01 SOL"
                )
                logger.error(error_msg)
                return {'success': False, 'error': 'insufficient_sol_after_reserve', 'balance': balance}

            # Step 3: Swap SOL → USDC via Jupiter
            if status_callback:
                await status_callback(
                    f"🔄 Step 1/7: Swapping SOL → USDC\n\n"
                    f"Amount: {actual_swap_amount:.6f} SOL"
                )

            logger.info(f"📊 STEP 1/7: Swap SOL → USDC via Jupiter...")

            # Record starting USDC balance
            starting_usdc_balance = await self.get_usdc_balance(solana_address)
            logger.info(f"   Starting USDC: {starting_usdc_balance:.6f} USDC")

            swap_result = await self.jupiter_client.swap_sol_to_usdc(
                solana_address=solana_address,
                solana_private_key=solana_private_key,
                amount_sol=actual_swap_amount,
                slippage_bps=100
            )

            swap_signature = swap_result.get('signature')
            usdc_estimate = swap_result.get('usdc_estimate', 0)

            if not swap_signature:
                logger.error("❌ Swap failed - no signature returned")
                return {'success': False, 'error': 'swap_failed', 'step': 'jupiter_swap'}

            logger.info(f"✅ Swap completed! Signature: {swap_signature}")

            if status_callback:
                await status_callback(
                    f"✅ Swap confirmed!\n\n"
                    f"TX: `{swap_signature}`\n\n"
                    f"⏳ Verifying USDC balance..."
                )

            # Verify USDC balance increased with retry logic
            logger.info(f"   Verifying USDC balance increase...")
            current_usdc_balance = starting_usdc_balance
            usdc_increase = 0.0
            max_retries = 5
            retry_delay = 3  # seconds

            for attempt in range(max_retries):
                await asyncio.sleep(retry_delay)
                logger.info(f"   Attempt {attempt + 1}/{max_retries}: Checking USDC balance...")

                current_usdc_balance = await self.get_usdc_balance(solana_address)
                usdc_increase = current_usdc_balance - starting_usdc_balance

                logger.info(f"   USDC balance: {current_usdc_balance:.6f} USDC (+{usdc_increase:.6f})")

                # Success condition: received at least 50% of expected amount
                if usdc_increase >= (usdc_estimate * 0.5):
                    logger.info(f"✅ Swap verification successful! Received {usdc_increase:.6f} USDC")
                    break

                if attempt < max_retries - 1:
                    logger.warning(f"   USDC not received yet, retrying in {retry_delay}s...")
                else:
                    logger.error(f"   Final attempt: USDC increase {usdc_increase:.6f} < expected {usdc_estimate * 0.5:.2f}")

            if usdc_increase < (usdc_estimate * 0.5):
                warning_msg = (
                    f"⚠️ Swap verification uncertain after {max_retries} attempts!\n\n"
                    f"Expected: +{usdc_estimate:.2f} USDC (min: +{usdc_estimate * 0.5:.2f})\n"
                    f"Received: +{usdc_increase:.6f} USDC\n\n"
                    f"TX: `{swap_signature}`\n\n"
                    f"This may be due to RPC delays. Proceeding with bridge assuming swap succeeded..."
                )
                logger.warning(warning_msg)

                if status_callback:
                    await status_callback(
                        f"⚠️ USDC verification uncertain\n\n"
                        f"Expected: +{usdc_estimate:.2f} USDC\n"
                        f"Received: +{usdc_increase:.6f} USDC\n\n"
                        f"Continuing with bridge...\n\n"
                        f"🌉 Step 2/7: Bridging USDC → POL"
                    )

                # Continue with bridge even if verification failed
                # Use the expected amount as fallback
                current_usdc_balance = starting_usdc_balance + usdc_estimate
                logger.info(f"   Using fallback USDC balance: {current_usdc_balance:.6f} USDC")

            # Step 4: Bridge USDC → POL via deBridge
            if status_callback:
                await status_callback(
                    f"🌉 Step 4/7: Bridging USDC → POL\n\n"
                    f"Amount: {current_usdc_balance:.2f} USDC\n"
                    f"⏱️ This takes 2-5 minutes..."
                )

            logger.info(f"📊 STEP 4/7: Bridge USDC → POL via deBridge...")

            # Bridge 85% of USDC to leave margin for deBridge variable fees (~1.16 USDC needed)
            # With extra USDC from reduced SOL reserve, we can afford to leave more margin
            usdc_to_bridge = current_usdc_balance * 0.85
            usdc_lamports = int(usdc_to_bridge * 1e6)  # USDC has 6 decimals

            debridge_quote = self.debridge_client.get_quote(
                src_chain_id=BridgeConfig.SOLANA_CHAIN_ID,
                src_token=BridgeConfig.USDC_SOLANA_ADDRESS,
                dst_chain_id=BridgeConfig.POLYGON_CHAIN_ID,
                dst_token=BridgeConfig.POL_TOKEN_ADDRESS,
                amount=str(usdc_lamports),
                src_address=solana_address,
                dst_address=polygon_address,
                enable_refuel=False
            )

            if not debridge_quote:
                logger.error("❌ Failed to get deBridge quote")
                return {
                    'success': False,
                    'error': 'debridge_quote_failed',
                    'swap_signature': swap_signature
                }

            pol_expected = int(debridge_quote.get('dst_amount_expected', 0)) / 1e18
            logger.info(f"💰 Quote: {current_usdc_balance:.2f} USDC → {pol_expected:.2f} POL")

            if status_callback:
                await status_callback(
                    f"📊 Bridge quote received!\n\n"
                    f"{current_usdc_balance:.2f} USDC → {pol_expected:.2f} POL\n\n"
                    f"⏳ Creating order..."
                )

            # Create deBridge order
            order_data = self.debridge_client.create_order(
                quote=debridge_quote,
                src_address=solana_address,
                dst_address=polygon_address
            )

            if not order_data:
                logger.error("❌ Failed to create deBridge order")
                return {
                    'success': False,
                    'error': 'debridge_order_failed',
                    'swap_signature': swap_signature
                }

            order_id = order_data.get('orderId')
            logger.info(f"✅ Order created: {order_id}")

            # Parse and sign deBridge transaction
            if status_callback:
                await status_callback("✍️ Signing bridge transaction...")

            try:
                keypair = Keypair.from_base58_string(solana_private_key)
            except:
                keypair = Keypair.from_bytes(base58.b58decode(solana_private_key))

            signed_debridge_tx = await self.solana_builder.parse_and_sign_debridge_transaction(
                order_data=order_data,
                keypair=keypair
            )

            if not signed_debridge_tx:
                logger.error("❌ Failed to sign deBridge transaction")
                return {
                    'success': False,
                    'error': 'debridge_sign_failed',
                    'swap_signature': swap_signature
                }

            # Broadcast deBridge transaction
            if status_callback:
                await status_callback("📡 Broadcasting bridge transaction...")

            debridge_signature = await self.solana_builder.send_transaction(signed_debridge_tx)

            if not debridge_signature:
                logger.error("❌ Failed to broadcast deBridge transaction")
                return {
                    'success': False,
                    'error': 'debridge_broadcast_failed',
                    'swap_signature': swap_signature
                }

            logger.info(f"✅ deBridge tx sent: {debridge_signature}")

            if status_callback:
                await status_callback(
                    f"✅ Bridge tx sent!\n\n"
                    f"TX Solana: `{debridge_signature}`\n\n"
                    f"⏳ Step 3/7: Waiting for Solana confirmation..."
                )

            # Wait for Solana confirmation
            logger.info(f"📊 STEP 3/7: Waiting for Solana confirmation...")
            debridge_confirmed = await self.solana_builder.confirm_transaction(debridge_signature, timeout=120)

            if not debridge_confirmed:
                logger.warning(f"⚠️ deBridge tx timeout (may still succeed)")

            if status_callback:
                await status_callback(
                    f"✅ Confirmed on Solana!\n\n"
                    f"⏳ Step 4/7: Waiting for POL on Polygon...\n"
                    f"(2-5 minutes)\n\n"
                    f"Order: {order_id}"
                )

            logger.info(f"📊 STEP 4/7: Waiting for POL arrival on Polygon...")

            # Record starting POL balance
            starting_pol_balance = self.get_pol_balance(polygon_address)
            logger.info(f"   Starting POL: {starting_pol_balance:.4f} POL")

            # Wait for POL arrival
            pol_balance = await self.wait_for_pol_arrival(
                polygon_address=polygon_address,
                starting_balance=starting_pol_balance,
                expected_increase=pol_expected * 0.9,  # 90% of expected (account for fees)
                timeout=300,
                status_callback=status_callback
            )

            if pol_balance is None:
                logger.warning(f"⚠️ POL arrival timeout (may still arrive)")
                return {
                    'success': False,
                    'error': 'pol_arrival_timeout',
                    'swap_signature': swap_signature,
                    'debridge_signature': debridge_signature,
                    'order_id': order_id
                }

            logger.info(f"✅ POL received: {pol_balance:.4f} POL")

            # Step 5: Swap POL → USDC.e via QuickSwap
            if status_callback:
                await status_callback(
                    f"✅ POL received!\n\n"
                    f"Balance: {pol_balance:.4f} POL\n\n"
                    f"💱 Step 5/7: Swapping POL → USDC.e..."
                )

            logger.info(f"📊 STEP 5/7: Swap POL → USDC.e via QuickSwap...")

            # Get Polygon private key (via API or DB)
            polygon_private_key = None
            if SKIP_DB:
                # Get private key via API (already decrypted)
                from core.services.api_client import get_api_client
                api_client = get_api_client()
                polygon_private_key = await api_client.get_private_key(telegram_user_id, "polygon")
                if not polygon_private_key:
                    logger.error("❌ Failed to retrieve Polygon private key")
                    return {
                        'success': False,
                        'error': 'decryption_failed_polygon',
                        'swap_signature': swap_signature,
                        'debridge_signature': debridge_signature
                    }
            else:
                # Decrypt polygon private key (needed for QuickSwap and later steps)
                polygon_private_key = encryption_service.decrypt_private_key(user.polygon_private_key)
                if not polygon_private_key:
                    logger.error("❌ Failed to decrypt Polygon private key")
                    return {
                        'success': False,
                        'error': 'decryption_failed_polygon',
                        'swap_signature': swap_signature,
                        'debridge_signature': debridge_signature
                    }

            pol_to_swap = pol_balance - BridgeConfig.MIN_POL_FOR_GAS
            quickswap_result = None
            usdc_e_received = 0.0

            if pol_to_swap > 0.1:  # Minimum 0.1 POL to swap
                logger.info(f"💱 Swapping {pol_to_swap:.4f} POL → USDC.e (keeping {BridgeConfig.MIN_POL_FOR_GAS} POL for gas)")

                try:
                    quickswap_result = self.quickswap_client.swap_pol_to_usdc_e(
                        polygon_address=polygon_address,
                        polygon_private_key=polygon_private_key,
                        pol_amount=pol_to_swap
                    )

                    if quickswap_result and quickswap_result.get('success'):
                        usdc_e_received = quickswap_result.get('usdc_e_received', 0.0)
                        quickswap_tx = quickswap_result.get('tx_hash')
                        logger.info(f"✅ QuickSwap complete! TX: {quickswap_tx}")
                        logger.info(f"   USDC.e received: {usdc_e_received:.2f}")

                        if status_callback:
                            await status_callback(
                                f"✅ POL→USDC.e swap complete!\n\n"
                                f"~{usdc_e_received:.2f} USDC.e received\n"
                                f"TX: `{quickswap_tx}`\n\n"
                                f"⚡ Step 6/7: Approving contracts..."
                            )
                    else:
                        logger.warning(f"⚠️ QuickSwap failed: {quickswap_result.get('error', 'unknown') if quickswap_result else 'no result'}")
                        if status_callback:
                            await status_callback(
                                f"⚠️ QuickSwap failed (continuing...)\n\n"
                                f"You can swap POL→USDC.e manually.\n\n"
                                f"⚡ Step 6/7: Approving contracts..."
                            )
                except Exception as e:
                    logger.error(f"❌ QuickSwap error: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

                    # Check if we have a tx_hash to investigate
                    if 'tx_hash' in locals() and quickswap_result and quickswap_result.get('tx_hash'):
                        tx_hash = quickswap_result['tx_hash']
                        logger.info(f"🔍 Investigating failed transaction: {tx_hash}")
                        try:
                            # Check if transaction exists on chain
                            tx_details = self.quickswap_client.w3.eth.get_transaction(tx_hash)
                            logger.info(f"📋 Transaction found on chain: {tx_details}")
                        except Exception as tx_check_error:
                            logger.warning(f"⚠️ Transaction not found on chain: {tx_check_error}")

                    if status_callback:
                        await status_callback(
                            f"⚠️ QuickSwap error (continuing with POL in wallet)\n\n"
                            f"💰 POL available: {pol_balance:.4f} POL\n\n"
                            f"⚡ Step 6/7: Approving contracts..."
                        )
            else:
                logger.info(f"ℹ️ Not enough POL to swap ({pol_to_swap:.4f} POL)")
                if status_callback:
                    await status_callback(
                        f"ℹ️ Keeping POL for gas\n\n"
                        f"⚡ Step 6/7: Approving contracts..."
                    )

            # Step 6: Auto-Approvals
            logger.info(f"📊 STEP 6/7: Auto-approving contracts...")

            approval_success = False
            try:
                # polygon_private_key already decrypted in Step 5
                approval_success, approval_results = self.approval_service.approve_all_for_trading(polygon_private_key)

                if approval_success:
                    logger.info(f"✅ All approvals successful!")
                    # Update auto_approval_completed via API or DB
                    if SKIP_DB:
                        from core.services.api_client import get_api_client
                        api_client = get_api_client()
                        await api_client.update_user(telegram_user_id, auto_approval_completed=True)
                    else:
                        await self.user_service.set_auto_approval_completed(telegram_user_id, True)

                    if status_callback:
                        await status_callback(
                            f"✅ Contracts approved!\n\n"
                            f"USDC.e: ✅\n"
                            f"Conditional Tokens: ✅\n\n"
                            f"🔑 Step 7/7: Generating API keys..."
                        )
                else:
                    logger.warning(f"⚠️ Some approvals failed: {approval_results}")
                    if status_callback:
                        await status_callback(
                            f"⚠️ Some approvals failed (continuing...)\n\n"
                            f"You can approve manually later.\n\n"
                            f"🔑 Step 7/7: Generating API keys..."
                        )
            except Exception as e:
                logger.error(f"❌ Approval error: {e}")
                if status_callback:
                    await status_callback(
                        f"⚠️ Approval error (continuing...)\n\n"
                        f"🔑 Step 7/7: Generating API keys..."
                    )

            # Step 7: Generate API Keys
            logger.info(f"📊 STEP 7/7: Generating API keys...")

            api_keys_generated = False
            try:
                # Check if API keys already exist
                user_for_api_check = None
                if SKIP_DB:
                    # Check API keys via API
                    from core.services.api_client import get_api_client
                    api_client = get_api_client()
                    user_data = await api_client.get_user(telegram_user_id)
                    if user_data:
                        # Create a simple object to check API keys
                        class UserData:
                            def __init__(self, data):
                                self.api_key = data.get('api_key')
                                self.api_secret = data.get('api_secret')
                                self.api_passphrase = data.get('api_passphrase')
                        user_for_api_check = UserData(user_data)
                else:
                    user_for_api_check = user

                if user_for_api_check and user_for_api_check.api_key and user_for_api_check.api_secret and user_for_api_check.api_passphrase:
                    logger.info(f"ℹ️ API keys already exist for user {telegram_user_id}")
                    api_keys_generated = True
                else:
                    # polygon_private_key already decrypted in Step 5
                    api_creds = self.api_key_manager.generate_api_credentials(
                        telegram_user_id=telegram_user_id,
                        polygon_private_key=polygon_private_key,
                        polygon_address=polygon_address
                    )

                    if api_creds:
                        # Encrypt api_secret before saving
                        encrypted_secret = encryption_service.encrypt_api_secret(api_creds['api_secret'])

                        # Save to database via API or DB
                        if SKIP_DB:
                            from core.services.api_client import get_api_client
                            api_client = get_api_client()
                            await api_client.update_user(
                                telegram_user_id=telegram_user_id,
                                api_key=api_creds['api_key'],
                                api_secret=encrypted_secret,
                                api_passphrase=api_creds['api_passphrase']
                            )
                        else:
                            await self.user_service.set_api_credentials(
                                telegram_user_id=telegram_user_id,
                                api_key=api_creds['api_key'],
                                api_secret=encrypted_secret,
                                api_passphrase=api_creds['api_passphrase']
                            )

                        logger.info(f"✅ API keys generated and saved!")
                        api_keys_generated = True

                        if status_callback:
                            await status_callback(
                                f"✅ API keys generated!\n\n"
                                f"🎉 Setup complete!"
                            )
                    else:
                        logger.warning(f"⚠️ API key generation failed")
                        if status_callback:
                            await status_callback(
                                f"⚠️ API key generation failed\n\n"
                                f"You can generate manually later.\n\n"
                                f"🎉 Bridge complete!"
                            )
            except Exception as e:
                logger.error(f"❌ API key generation error: {e}")
                import traceback
                logger.error(traceback.format_exc())

            # Update user stage to ready
            if SKIP_DB:
                from core.services.api_client import get_api_client
                api_client = get_api_client()
                await api_client.update_user(telegram_user_id, stage='ready', funded=True)
            else:
                await self.user_service.update_stage(telegram_user_id, 'ready')
                await self.user_service.set_funded(telegram_user_id, True)

            # Success!
            logger.info(f"✅ Bridge workflow completed successfully!")
            logger.info(f"   POL received: {pol_balance:.4f} POL")
            if quickswap_result and quickswap_result.get('success'):
                logger.info(f"   USDC.e received: {usdc_e_received:.2f}")
            logger.info(f"   Approvals: {'✅' if approval_success else '⚠️'}")
            logger.info(f"   API keys: {'✅' if api_keys_generated else '⚠️'}")

            if status_callback:
                success_msg = f"🎉 **BRIDGE COMPLETE!**\n\n"
                success_msg += f"✅ Swap SOL→USDC: `{swap_signature}`\n"
                success_msg += f"✅ Bridge USDC→POL: `{debridge_signature}`\n"
                success_msg += f"✅ POL received: {pol_balance:.4f} POL\n"

                if quickswap_result and quickswap_result.get('success'):
                    success_msg += f"✅ QuickSwap: `{quickswap_result.get('tx_hash')}`\n"
                    success_msg += f"💰 USDC.e: {usdc_e_received:.2f}\n"

                success_msg += f"💰 POL gas: {BridgeConfig.MIN_POL_FOR_GAS} POL\n\n"
                success_msg += f"Approvals: {'✅' if approval_success else '⚠️'}\n"
                success_msg += f"API keys: {'✅' if api_keys_generated else '⚠️'}\n\n"
                success_msg += f"🎯 Wallet ready for Polymarket!"

                await status_callback(success_msg)

            return {
                'success': True,
                'swap_signature': swap_signature,
                'debridge_signature': debridge_signature,
                'order_id': order_id,
                'pol_received': pol_balance,
                'usdc_swapped': current_usdc_balance,
                'quickswap_tx': quickswap_result.get('tx_hash') if quickswap_result else None,
                'usdc_e_received': usdc_e_received,
                'approvals_success': approval_success,
                'api_keys_generated': api_keys_generated
            }

        except Exception as e:
            logger.error(f"❌ Bridge error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': 'bridge_exception',
                'error_message': str(e)
            }

    async def close(self):
        """Close connections"""
        await self.solana_builder.close()
        await self.jupiter_client.close()


# Global instance
_bridge_service: Optional[BridgeService] = None


def get_bridge_service() -> BridgeService:
    """Get or create BridgeService instance"""
    global _bridge_service
    if _bridge_service is None:
        _bridge_service = BridgeService()
    return _bridge_service
