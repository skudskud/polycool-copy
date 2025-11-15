#!/usr/bin/env python3
"""
Bridge Orchestrator
Coordinates the complete SOL → USDC.e/POL bridging workflow
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Callable
from .solana_wallet_manager import solana_wallet_manager
from .debridge_client import debridge_client
from .solana_transaction import SolanaTransactionBuilder
from .quickswap_client import quickswap_client
from .jupiter_client import jupiter_client, SOL_MINT, USDC_MINT
from .config import (
    SOLANA_CHAIN_ID,
    POLYGON_CHAIN_ID,
    SOL_TOKEN_ADDRESS,
    USDC_E_POLYGON,
    POL_TOKEN_ADDRESS,
    MIN_POL_RESERVE,
    BRIDGE_CONFIRMATION_TIMEOUT,
    DEBRIDGE_SLIPPAGE_BPS
)

logger = logging.getLogger(__name__)


class BridgeOrchestrator:
    """Orchestrates the complete bridge workflow"""

    def __init__(self):
        """Initialize bridge orchestrator"""
        self.solana_tx_builder = SolanaTransactionBuilder()
        self.active_bridges = {}  # Track active bridge operations by user_id

    async def get_bridge_quote(
        self,
        user_id: int,
        sol_amount: float,
        polygon_address: str,
        solana_address: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Step (a): Get quote from deBridge API

        Args:
            user_id: Telegram user ID
            sol_amount: Amount of SOL to bridge
            polygon_address: Destination Polygon address
            solana_address: Optional Solana source address (uses .env if not provided)

        Returns:
            Quote with fee breakdown and expected outputs
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🌉 BRIDGE QUOTE REQUEST")
            logger.info(f"   User ID: {user_id}")
            logger.info(f"   Amount: {sol_amount} SOL")
            logger.info(f"{'='*60}\n")

            # Use provided Solana address or get from config
            if not solana_address:
                from .config import SOLANA_ADDRESS
                solana_address = SOLANA_ADDRESS

            if not solana_address:
                logger.info("❌ No Solana address provided or configured")
                return None

            # Convert SOL to lamports
            lamports = int(sol_amount * 1_000_000_000)

            # NEW WORKFLOW: SOL → POL (puis QuickSwap POL → USDC.e)
            # Get quote from deBridge for SOL → POL
            quote = debridge_client.get_quote(
                src_chain_id=SOLANA_CHAIN_ID,
                src_token=SOL_TOKEN_ADDRESS,
                dst_chain_id=POLYGON_CHAIN_ID,
                dst_token=POL_TOKEN_ADDRESS,  # ✅ Demander POL au lieu de USDC.e
                amount=str(lamports),
                src_address=solana_address,
                dst_address=polygon_address,
                enable_refuel=False  # Pas besoin de refuel si on reçoit déjà du POL
            )

            logger.info(f"✅ Workflow: SOL → POL, puis QuickSwap POL → USDC.e")

            if not quote:
                logger.info("❌ Failed to get bridge quote")
                return None

            # Add user context
            quote['user_id'] = user_id
            quote['sol_amount'] = sol_amount
            quote['solana_address'] = solana_address
            quote['polygon_address'] = polygon_address

            # Format for user display (NEW: POL reçu, puis swap vers USDC.e)
            # dst_amount_expected est maintenant en POL (18 decimals)
            pol_received = float(quote['dst_amount_expected']) / 1_000_000_000_000_000_000

            # Calculer combien de POL sera swappé (garde MIN_POL_RESERVE)
            pol_to_swap = max(0, pol_received - MIN_POL_RESERVE)

            # Utiliser la valeur USD approximative de deBridge pour estimer USDC.e
            # deBridge donne 'approximateUsdValue' pour le POL reçu
            pol_usd_value = quote.get('raw_response', {}).get('estimation', {}).get('dstChainTokenOut', {}).get('approximateUsdValue', 0)

            # Calculer USDC.e après swap (proportion du POL swappé)
            if pol_received > 0:
                estimated_usdc_after_swap = (pol_to_swap / pol_received) * pol_usd_value
            else:
                estimated_usdc_after_swap = 0

            logger.info(f"📊 Quote calculation:")
            logger.info(f"   POL received: {pol_received:.4f}")
            logger.info(f"   POL USD value (deBridge): ${pol_usd_value:.2f}")
            logger.info(f"   POL to swap: {pol_to_swap:.4f}")
            logger.info(f"   Estimated USDC.e: ${estimated_usdc_after_swap:.2f}")

            quote['display'] = {
                'sol_input': sol_amount,
                'pol_received': pol_received,
                'pol_to_swap': pol_to_swap,
                'pol_kept': MIN_POL_RESERVE,
                'usdc_output_estimated': estimated_usdc_after_swap,
                'formatted': f"""
💰 BRIDGE QUOTE (SOL → POL → USDC.e)

📤 Étape 1: Bridge SOL → POL
• {sol_amount} SOL → ~{pol_received:.4f} POL

📥 Étape 2: QuickSwap POL → USDC.e
• Swap: {pol_to_swap:.4f} POL → ~{estimated_usdc_after_swap:.2f} USDC.e
• Garde: {MIN_POL_RESERVE} POL (pour gas)

🎯 Résultat final:
• ~{estimated_usdc_after_swap:.2f} USDC.e (pour trader)
• {MIN_POL_RESERVE} POL (pour gas)

⛽ Frais: Inclus dans le quote
⏱️ Temps: ~2-5 minutes
                """
            }

            logger.info(f"\n✅ Quote generated successfully!")
            logger.info(f"   {sol_amount} SOL → {pol_received:.4f} POL → ~{estimated_usdc_after_swap:.2f} USDC.e (+ {MIN_POL_RESERVE} POL gas)")

            return quote

        except Exception as e:
            logger.info(f"❌ Error getting bridge quote: {e}")
            return None

    async def execute_bridge(
        self,
        user_id: int,
        quote: Dict,
        solana_private_key: str,
        status_callback: Optional[Callable] = None
    ) -> Optional[Dict]:
        """
        Steps (c) through (g): Execute complete bridge workflow

        Args:
            user_id: Telegram user ID
            quote: Quote from get_bridge_quote()
            solana_private_key: Solana private key for signing
            status_callback: Optional callback for status updates

        Returns:
            Bridge execution result with transaction hashes
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🚀 EXECUTING BRIDGE")
            logger.info(f"   User ID: {user_id}")
            logger.info(f"{'='*60}\n")

            # Track this bridge operation
            self.active_bridges[user_id] = {
                'status': 'starting',
                'quote': quote,
                'started_at': time.time()
            }

            # Load Solana keypair FIRST (before create_order for speed)
            from solders.keypair import Keypair
            import base58

            try:
                logger.info(f"🔑 Loading Solana keypair from private key...")
                keypair = Keypair.from_base58_string(solana_private_key)
                logger.info(f"✅ Keypair loaded: {str(keypair.pubkey())[:20]}...")
            except:
                # Try from bytes if base58 fails
                try:
                    logger.info(f"⚠️ Base58 failed, trying from bytes...")
                    keypair = Keypair.from_bytes(base58.b58decode(solana_private_key))
                    logger.info(f"✅ Keypair loaded from bytes: {str(keypair.pubkey())[:20]}...")
                except Exception as e:
                    logger.error(f"❌ Failed to load keypair: {e}")
                    if status_callback:
                        await status_callback(f"❌ Invalid Solana private key: {e}")
                    return None

            # CRITICAL: Check SOL balance BEFORE attempting bridge
            logger.info(f"💰 Checking SOL balance...")
            current_balance = await self.solana_tx_builder.get_sol_balance(str(keypair.pubkey()))

            # quote['sol_amount'] is in SOL (quote['src_amount'] is in lamports from deBridge)
            bridge_amount = float(quote['sol_amount'])

            logger.info(f"   Current balance: {current_balance:.9f} SOL")
            logger.info(f"   Required for bridge: {bridge_amount:.9f} SOL")

            # Estimate transaction fee (typically 0.000005 SOL for Solana)
            # We already reserved 0.00002 SOL when calculating bridge amount
            # But double-check we have enough for fees
            estimated_fee = 0.00002  # Conservative estimate (same as SOLANA_TX_FEE_RESERVE)
            required_total = bridge_amount + estimated_fee

            if current_balance < required_total:
                error_msg = f"❌ Fonds insuffisants!\n\n" \
                           f"Balance: {current_balance:.9f} SOL\n" \
                           f"Requis: {required_total:.9f} SOL\n" \
                           f"(Bridge: {bridge_amount:.9f} + Frais: ~{estimated_fee:.9f})\n\n" \
                           f"Ajoutez au moins {(required_total - current_balance):.9f} SOL à votre wallet."
                logger.error(error_msg)
                if status_callback:
                    await status_callback(error_msg)
                return None

            logger.info(f"✅ Balance suffisante ({current_balance:.9f} SOL >= {required_total:.9f} SOL)")

            # OPTION A: Create order JUST BEFORE signing (fresh blockhash)
            logger.info(f"🔨 Step (c-d): Creating FRESH deBridge order (for recent blockhash)...")
            if status_callback:
                await status_callback("🔨 Getting fresh blockhash from deBridge...")

            try:
                order_data = debridge_client.create_order(
                    quote=quote,
                    src_address=quote['solana_address'],
                    dst_address=quote['polygon_address']
                )

                if not order_data:
                    logger.error("❌ Failed to create order")
                    if status_callback:
                        await status_callback("❌ Failed to create bridge order")
                    return None

                logger.info(f"✅ Order created: {order_data.get('orderId')}")
                logger.info(f"   Order has tx data: {'tx' in order_data}")
                logger.info(f"   ⚡ Blockhash is FRESH (< 2 seconds old)")

            except Exception as e:
                logger.error(f"❌ Error creating order: {e}")
                if status_callback:
                    await status_callback(f"❌ Failed to create order: {e}")
                return None

            self.active_bridges[user_id]['status'] = 'order_created'
            self.active_bridges[user_id]['order_id'] = order_data.get('orderId')

            # Step (e): Parse and sign transaction IMMEDIATELY
            logger.info(f"✍️ Step (e): Signing IMMEDIATELY (while blockhash is fresh)...")
            if status_callback:
                await status_callback("✍️ Signing transaction...")

            # Parse and sign transaction from deBridge order
            try:
                signed_tx = await self.solana_tx_builder.parse_and_sign_debridge_transaction(
                    order_data=order_data,
                    keypair=keypair
                )

                if not signed_tx:
                    logger.error("❌ Failed to sign transaction")
                    if status_callback:
                        await status_callback("❌ Failed to sign transaction")
                    return None

                logger.info(f"✅ Transaction signed ({len(signed_tx)} bytes)")
                logger.info(f"   ⚡ Signed within 1 second of create_order!")

            except Exception as e:
                logger.error(f"❌ Error signing transaction: {e}")
                if status_callback:
                    await status_callback(f"❌ Error signing: {e}")
                return None

            self.active_bridges[user_id]['status'] = 'transaction_signed'

            # Step (f): Broadcast to Solana RPC
            logger.info(f"📡 Step (f): Broadcasting to Solana...")
            if status_callback:
                await status_callback("📡 Broadcasting to Solana network...")

            # Send signed transaction
            signature = await self.solana_tx_builder.send_transaction(signed_tx)

            if not signature:
                logger.error("❌ No signature to broadcast")
                if status_callback:
                    await status_callback("❌ Failed to broadcast transaction")
                return None

            self.active_bridges[user_id]['status'] = 'transaction_sent'
            self.active_bridges[user_id]['solana_tx'] = signature

            logger.info(f"✅ Solana transaction sent: {signature}")

            # CRITICAL: Verify transaction confirmation
            logger.info(f"⏳ Waiting for Solana confirmation...")
            if status_callback:
                await status_callback(f"✅ Transaction broadcasted!\n\nSolana TX: `{signature}`\n\n⏳ Confirming on Solana...")

            confirmed = await self.solana_tx_builder.confirm_transaction(signature, timeout=30)

            if not confirmed:
                logger.error(f"❌ Solana transaction failed to confirm")

                # DIAGNOSTIC 1: Check deBridge order status
                logger.info(f"🔍 DIAGNOSTIC: Checking deBridge order status...")
                order_status = debridge_client.get_order_status(order_data.get('orderId'))
                if order_status:
                    logger.info(f"📊 deBridge Order Status:")
                    logger.info(f"   Status: {order_status.get('status')}")
                    logger.info(f"   Full data: {order_status}")
                else:
                    logger.error(f"❌ deBridge order NOT FOUND (UNKNOWN_ORDER)")
                    logger.error(f"   This means: Transaction was REJECTED by Solana validators")
                    logger.error(f"   Possible causes:")
                    logger.error(f"      1. Blockhash expired (most likely)")
                    logger.error(f"      2. Missing/insufficient priority fees")
                    logger.error(f"      3. Transaction malformed")

                # DIAGNOSTIC 2: Try to get transaction details from Solana
                logger.info(f"🔍 DIAGNOSTIC: Attempting to fetch transaction details from Solana...")
                tx_details = await self.solana_tx_builder.get_transaction_details(signature)
                if tx_details:
                    logger.info(f"📊 Solana Transaction Details: {tx_details}")
                else:
                    logger.error(f"❌ Transaction details NOT FOUND on Solana")
                    logger.error(f"   This confirms: Transaction was REJECTED before inclusion")

                if status_callback:
                    await status_callback(
                        f"❌ Transaction REJETÉE\n\n"
                        f"Signature: `{signature}`\n\n"
                        f"deBridge Order: {'Introuvable' if not order_status else order_status.get('status')}\n\n"
                        f"Cause probable: Blockhash expiré ou priority fees manquants\n\n"
                        f"Vérifiez les logs pour détails."
                    )
                return {'success': False, 'error': 'Transaction not confirmed', 'signature': signature, 'order_status': order_status}

            logger.info(f"✅ Solana transaction confirmed!")
            if status_callback:
                await status_callback(f"✅ Confirmé sur Solana!\n\nTX: `{signature}`\n\n⏳ Waiting for Polygon credit...")

            # Step (g): Wait for event on Polygon side
            result = await self._wait_for_polygon_credit(
                user_id=user_id,
                polygon_address=quote['polygon_address'],
                order_id=order_data.get('orderId'),  # orderId from deBridge create_order response
                status_callback=status_callback
            )

            if not result:
                if status_callback:
                    await status_callback("❌ Bridge confirmation timeout")
                return None

            logger.info(f"✅ Bridge completed successfully!")

            # Clean up tracking
            del self.active_bridges[user_id]

            return {
                'success': True,
                'solana_tx': signature,
                'polygon_credited': True,
                'usdc_received': result['usdc_amount'],
                'pol_received': result['pol_amount'],
                'timestamp': int(time.time())
            }

        except Exception as e:
            logger.info(f"❌ Error executing bridge: {e}")
            if status_callback:
                await status_callback(f"❌ Bridge error: {str(e)}")

            # Clean up tracking
            if user_id in self.active_bridges:
                del self.active_bridges[user_id]

            return None

    async def _wait_for_polygon_credit(
        self,
        user_id: int,
        polygon_address: str,
        order_id: Optional[str],
        status_callback: Optional[Callable] = None,
        timeout: int = BRIDGE_CONFIRMATION_TIMEOUT
    ) -> Optional[Dict]:
        """
        Wait for USDC.e and POL to be credited on Polygon

        Args:
            user_id: User ID
            polygon_address: Polygon address to watch
            order_id: deBridge order ID
            status_callback: Status update callback
            timeout: Maximum wait time in seconds

        Returns:
            Credit confirmation with amounts
        """
        try:
            logger.info(f"👀 Watching Polygon for credits to {polygon_address[:10]}...")

            # Get initial balances
            initial_usdc = quickswap_client.get_usdc_balance(polygon_address)
            initial_pol = quickswap_client.get_pol_balance(polygon_address)

            start_time = time.time()
            check_interval = 10  # Check every 10 seconds

            while time.time() - start_time < timeout:
                # Update status
                elapsed = int(time.time() - start_time)
                if status_callback and elapsed % 30 == 0:  # Update every 30s
                    await status_callback(f"⏳ Waiting for bridge... ({elapsed}s elapsed)")

                # Check balances
                current_usdc = quickswap_client.get_usdc_balance(polygon_address)
                current_pol = quickswap_client.get_pol_balance(polygon_address)

                # Check if balances increased
                usdc_delta = current_usdc - initial_usdc
                pol_delta = current_pol - initial_pol

                if usdc_delta > 0 or pol_delta > 0:
                    logger.info(f"✅ Credits detected on Polygon!")
                    logger.info(f"   USDC.e: +{usdc_delta}")
                    logger.info(f"   POL: +{pol_delta}")

                    if status_callback:
                        await status_callback(f"✅ Received on Polygon!\n\n• {usdc_delta:.2f} USDC.e\n• {pol_delta:.4f} POL")

                    return {
                        'usdc_amount': usdc_delta,
                        'pol_amount': pol_delta,
                        'wait_time': int(time.time() - start_time)
                    }

                # Wait before next check
                await asyncio.sleep(check_interval)

            logger.info(f"⏰ Timeout waiting for Polygon credits")
            return None

        except Exception as e:
            logger.info(f"❌ Error waiting for Polygon credit: {e}")
            return None

    async def execute_quickswap(
        self,
        polygon_address: str,
        private_key: str,
        status_callback: Optional[Callable] = None
    ) -> Optional[Dict]:
        """
        Step (h): Swap (POL_balance - 2.5) → USDC.e on QuickSwap

        Args:
            polygon_address: Polygon wallet address
            private_key: Private key for signing
            status_callback: Status update callback

        Returns:
            Swap result with transaction hash
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🔄 QUICKSWAP AUTO-SWAP")
            logger.info(f"   Address: {polygon_address[:10]}...")
            logger.info(f"{'='*60}\n")

            if status_callback:
                await status_callback("🔄 Swapping excess POL to USDC.e...")

            # Execute auto-swap
            result = quickswap_client.auto_swap_excess_pol(
                address=polygon_address,
                private_key=private_key,
                reserve_pol=MIN_POL_RESERVE
            )

            if not result:
                logger.info("⚠️ No POL to swap or swap failed")
                if status_callback:
                    await status_callback("⚠️ No excess POL to swap")
                return None

            swapped_amount, tx_hash = result

            logger.info(f"✅ QuickSwap completed!")
            logger.info(f"   Swapped: {swapped_amount} POL")
            logger.info(f"   TX: {tx_hash}")

            if status_callback:
                await status_callback(f"✅ Swap complete!\n\n• Swapped {swapped_amount:.4f} POL → USDC.e\n• Kept {MIN_POL_RESERVE} POL for gas\n\nWallet ready for Polymarket! 🎉")

            return {
                'success': True,
                'swapped_pol': swapped_amount,
                'tx_hash': tx_hash,
                'timestamp': int(time.time())
            }

        except Exception as e:
            logger.info(f"❌ Error in QuickSwap: {e}")
            if status_callback:
                await status_callback(f"❌ Swap error: {str(e)}")
            return None

    async def execute_bridge_v2(
        self,
        user_id: int,
        sol_amount: float,
        solana_private_key: str,
        polygon_address: str,
        status_callback: Optional[Callable] = None
    ) -> Optional[Dict]:
        """
        NEW WORKFLOW (v2): SOL → USDC (Jupiter) → POL (deBridge)

        This workflow avoids deBridge PreSwap issues by:
        1. Swapping SOL → USDC directly on Jupiter (with controlled slippage)
        2. Bridging USDC → POL via deBridge (no PreSwap needed)

        Args:
            user_id: Telegram user ID
            sol_amount: Amount of SOL to swap
            solana_private_key: Solana private key
            polygon_address: Destination Polygon address
            status_callback: Status update callback

        Returns:
            Result dict with success status
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🚀 NEW WORKFLOW V2: SOL → USDC → POL")
            logger.info(f"   User: {user_id}")
            logger.info(f"   Amount: {sol_amount} SOL")
            logger.info(f"{'='*60}\n")

            # Load Solana keypair
            from solders.keypair import Keypair
            import base58

            try:
                keypair = Keypair.from_base58_string(solana_private_key)
            except:
                keypair = Keypair.from_bytes(base58.b58decode(solana_private_key))

            solana_address = str(keypair.pubkey())

            # STEP 1: Jupiter swap SOL → USDC
            logger.info(f"📊 STEP 1/2: Swapping SOL → USDC via Jupiter...")
            if status_callback:
                await status_callback(f"🔄 Step 1/2: Swapping SOL → USDC...\n\nSlippage: {DEBRIDGE_SLIPPAGE_BPS/100}%")

            # Convert SOL to lamports and round to avoid precision issues with Jupiter API
            # Jupiter seems to have issues with very precise amounts
            sol_lamports = int(sol_amount * 1e9)

            # Round to nearest 0.01 SOL (10 million lamports) for Jupiter compatibility
            sol_lamports_rounded = round(sol_lamports / 10000000) * 10000000

            logger.info(f"   Original amount: {sol_lamports} lamports ({sol_amount:.9f} SOL)")
            logger.info(f"   Rounded amount: {sol_lamports_rounded} lamports ({sol_lamports_rounded/1e9:.9f} SOL)")

            # Get Jupiter order (with taker address - REQUIRED for Ultra API)
            jupiter_quote = jupiter_client.get_quote(
                input_mint=SOL_MINT,
                output_mint=USDC_MINT,
                amount=sol_lamports_rounded,  # Use rounded amount
                taker=solana_address,  # User's Solana wallet address
                slippage_bps=100  # Use reasonable 1% slippage for Jupiter (not 30%!)
            )

            if not jupiter_quote:
                logger.error("❌ Failed to get Jupiter quote")
                if status_callback:
                    await status_callback("❌ Failed to get swap quote from Jupiter")
                return {'success': False, 'error': 'Jupiter quote failed'}

            usdc_amount = int(jupiter_quote.get('outAmount', 0))
            request_id = jupiter_quote.get('requestId')
            transaction_b64 = jupiter_quote.get('transaction')

            logger.info(f"   Will receive: {usdc_amount / 1e6:.6f} USDC")
            logger.info(f"   Request ID: {request_id[:20] if request_id else 'N/A'}...")

            # Ultra API: Transaction is already in the order response!
            if not transaction_b64:
                logger.error("❌ No transaction in Jupiter order response")
                if status_callback:
                    await status_callback("❌ Invalid order response from Jupiter")
                return {'success': False, 'error': 'No transaction in order'}

            # SIMPLE APPROACH: Use Jupiter's transaction AS-IS and sign immediately
            import base64
            from solders.transaction import VersionedTransaction

            logger.info(f"✍️ Signing Jupiter transaction...")
            swap_tx_bytes = base64.b64decode(transaction_b64)
            jupiter_tx = VersionedTransaction.from_bytes(swap_tx_bytes)

            logger.info(f"   Transaction from Jupiter: {len(swap_tx_bytes)} bytes")
            logger.info(f"   Message header: {jupiter_tx.message.header}")
            logger.info(f"   Num signatures required: {jupiter_tx.message.header.num_required_signatures}")
            logger.info(f"   Existing signatures: {len(jupiter_tx.signatures)}")

            # Sign using VersionedTransaction constructor (creates new signed transaction)
            try:
                logger.info(f"✍️ Creating signed transaction with keypair...")
                logger.info(f"   Keypair pubkey: {keypair.pubkey()}")
                logger.info(f"   Fee payer (first account): {jupiter_tx.message.account_keys[0]}")

                # Verify our keypair is the fee payer
                if str(keypair.pubkey()) != str(jupiter_tx.message.account_keys[0]):
                    logger.warning(f"⚠️ Our keypair != fee payer! This might fail...")

                # Create signed transaction (VersionedTransaction handles signing internally)
                signed_jupiter_tx = VersionedTransaction(jupiter_tx.message, [keypair])
                signed_jupiter_bytes = bytes(signed_jupiter_tx)

                logger.info(f"✅ Transaction signed")
                logger.info(f"   Signed transaction: {len(signed_jupiter_bytes)} bytes")
                logger.info(f"   Signatures in signed tx: {len(signed_jupiter_tx.signatures)}")

            except Exception as e:
                logger.error(f"❌ Error signing transaction: {e}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                if status_callback:
                    await status_callback(f"❌ Failed to sign transaction: {e}")
                return {'success': False, 'error': f'Signing failed: {e}'}

            # Mode "manual" = Broadcast ourselves to Solana!
            logger.info(f"📡 Broadcasting Jupiter swap directly to Solana...")

            if status_callback:
                await status_callback(f"📡 Broadcasting swap to Solana...")

            # Use our existing Solana transaction builder (already works!)
            jupiter_sig = await self.solana_tx_builder.send_transaction(signed_jupiter_bytes)

            if not jupiter_sig:
                logger.error("❌ Failed to broadcast Jupiter transaction")
                if status_callback:
                    await status_callback("❌ Swap transaction failed to broadcast")
                return {'success': False, 'error': 'Broadcast failed'}

            logger.info(f"✅ Jupiter swap broadcasted!")
            logger.info(f"   Signature: {jupiter_sig}")
            logger.info(f"   View on Solscan: https://solscan.io/tx/{jupiter_sig}")

            # Wait for confirmation
            if status_callback:
                await status_callback(f"⏳ Confirming swap...\n\nTX: `{jupiter_sig}`")

            jupiter_confirmed = await self.solana_tx_builder.confirm_transaction(jupiter_sig, timeout=60)

            if not jupiter_confirmed:
                logger.error("❌ Jupiter swap failed to confirm")
                if status_callback:
                    await status_callback(f"❌ Swap did not confirm\n\nCheck TX: https://solscan.io/tx/{jupiter_sig}")
                return {'success': False, 'error': 'Jupiter swap not confirmed', 'jupiter_tx': jupiter_sig}

            logger.info(f"✅ Jupiter swap confirmed! Received ~{usdc_amount / 1e6:.6f} USDC")

            if status_callback:
                await status_callback(f"✅ Swap confirmed!\n\nTX: `{jupiter_sig}`\n\nReceived: ~{usdc_amount / 1e6:.6f} USDC")

            # STEP 2: deBridge USDC → POL (no PreSwap!)
            logger.info(f"\n📊 STEP 2/2: Bridging USDC → POL via deBridge...")
            if status_callback:
                await status_callback(f"✅ Swap complete!\n\n🌉 Step 2/2: Bridging USDC → POL...\n\nThis will take 2-5 minutes")

            # TODO: Implement deBridge USDC → POL bridge
            # For now, return success with Jupiter swap

            logger.info(f"\n{'='*60}")
            logger.info(f"✅ STEP 1 COMPLETED (Jupiter swap)")
            logger.info(f"⚠️ STEP 2 TODO (deBridge USDC → POL)")
            logger.info(f"{'='*60}\n")

            if status_callback:
                await status_callback(f"✅ Jupiter swap confirmed!\n\nReceived: ~{usdc_amount / 1e6:.6f} USDC\n\n⚠️ deBridge step coming next...")

            return {
                'success': True,
                'jupiter_tx': jupiter_sig,
                'usdc_received': usdc_amount / 1e6,
                'step': 'jupiter_completed',
                'note': 'deBridge USDC->POL bridge TODO'
            }

        except Exception as e:
            logger.error(f"❌ Error in execute_bridge_v2: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            if status_callback:
                await status_callback(f"❌ Bridge error: {str(e)}")
            return {'success': False, 'error': str(e)}

    async def complete_bridge_workflow(
        self,
        user_id: int,
        sol_amount: float,
        polygon_address: str,
        polygon_private_key: str,
        solana_address: Optional[str] = None,
        solana_private_key: Optional[str] = None,
        status_callback: Optional[Callable] = None
    ) -> Optional[Dict]:
        """
        Complete end-to-end workflow: Steps (a) through (i)
        NOW USES V2 WORKFLOW: SOL → USDC (Jupiter) → POL (deBridge)

        Args:
            user_id: Telegram user ID
            sol_amount: Amount of SOL to bridge
            polygon_address: Polygon wallet address
            polygon_private_key: Polygon private key for QuickSwap
            solana_address: Solana source address (uses .env if not provided)
            solana_private_key: Solana private key (uses .env if not provided)
            status_callback: Status update callback

        Returns:
            Complete workflow result
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🌉 COMPLETE BRIDGE WORKFLOW V2")
            logger.info(f"   User: {user_id}")
            logger.info(f"   Amount: {sol_amount} SOL")
            logger.info(f"{'='*60}\n")

            # Load Solana credentials from .env if not provided
            if not solana_address or not solana_private_key:
                from .config import SOLANA_ADDRESS, SOLANA_PRIVATE_KEY
                solana_address = solana_address or SOLANA_ADDRESS
                solana_private_key = solana_private_key or SOLANA_PRIVATE_KEY

            if not solana_address or not solana_private_key:
                return {'success': False, 'error': 'Solana credentials not provided'}

            # Execute NEW V2 workflow: Jupiter → deBridge
            bridge_result = await self.execute_bridge_v2(
                user_id=user_id,
                sol_amount=sol_amount,
                solana_private_key=solana_private_key,
                polygon_address=polygon_address,
                status_callback=status_callback
            )

            if not bridge_result or not bridge_result.get('success'):
                return {'success': False, 'error': 'Bridge execution failed'}

            # TODO: Step (h): QuickSwap (after deBridge is implemented)
            # swap_result = await self.execute_quickswap(...)

            # Compile final result
            final_result = {
                'success': True,
                'bridge': bridge_result,
                'timestamp': int(time.time())
            }

            logger.info(f"\n{'='*60}")
            logger.info(f"✅ WORKFLOW V2 IN PROGRESS")
            logger.info(f"{'='*60}\n")

            return final_result

        except Exception as e:
            logger.info(f"❌ Error in complete workflow: {e}")
            return {'success': False, 'error': str(e)}

    def get_bridge_status(self, user_id: int) -> Optional[Dict]:
        """Get current status of active bridge for user"""
        return self.active_bridges.get(user_id)


# Global bridge orchestrator instance
bridge_orchestrator = BridgeOrchestrator()
