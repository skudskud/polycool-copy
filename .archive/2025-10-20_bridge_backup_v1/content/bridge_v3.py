#!/usr/bin/env python3
"""
Bridge V3: Simplifié et fonctionnel
Workflow: SOL → USDC (Jupiter) → POL (deBridge)
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Callable

from .simple_swap_v2 import swap_sol_to_usdc
from .config import (
    # Removed SOLANA_ADDRESS - using user's generated address instead
    SOLANA_CHAIN_ID,
    POLYGON_CHAIN_ID,
    USDC_E_POLYGON,
    POL_TOKEN_ADDRESS,
)
from .solana_transaction import SolanaTransactionBuilder
from .debridge_client import debridge_client
from .quickswap_client import quickswap_client

logger = logging.getLogger(__name__)

# USDC on Solana
USDC_SOLANA_ADDRESS = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Minimum POL to keep for gas on Polygon
MIN_POL_FOR_GAS = 2.5


class BridgeV3:
    """Simple bridge: SOL → USDC (Jupiter) → POL (deBridge)"""

    def __init__(self):
        self.solana_builder = SolanaTransactionBuilder()

    def get_pol_balance(self, address: str) -> float:
        """Get POL balance on Polygon"""
        try:
            from web3 import Web3

            # Use QuickSwap's web3 instance
            w3 = quickswap_client.w3

            # Get native POL balance (in wei)
            balance_wei = w3.eth.get_balance(address)
            balance_pol = balance_wei / 1e18

            logger.info(f"💰 POL balance for {address[:10]}...: {balance_pol:.4f} POL")
            return balance_pol

        except Exception as e:
            logger.error(f"❌ Error fetching POL balance: {e}")
            return 0.0

    async def get_usdc_balance(self, address: str) -> float:
        """Get USDC balance on Solana using simpler approach"""
        try:
            from solders.pubkey import Pubkey
            from solana.rpc.async_api import AsyncClient
            from solana.rpc.commitment import Confirmed
            import requests

            logger.info(f"💰 Fetching USDC balance for {address[:16]}...")

            # Use direct RPC call instead of solana-py wrapper (more reliable)
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    address,
                    {"mint": USDC_SOLANA_ADDRESS},
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
                    # Get token amount from parsed account data
                    token_amount = accounts[0]['account']['data']['parsed']['info']['tokenAmount']
                    balance_usdc = float(token_amount['uiAmount'])

                    logger.info(f"✅ USDC balance: {balance_usdc:.6f} USDC")
                    return balance_usdc

            logger.info(f"💰 No USDC account found (balance: 0)")
            return 0.0

        except Exception as e:
            logger.error(f"❌ Error fetching USDC balance: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return 0.0

    async def wait_for_pol_arrival(
        self,
        polygon_address: str,
        expected_min: float,
        timeout: int = 300,
        status_callback: Optional[Callable] = None
    ) -> Optional[float]:
        """
        Wait for POL to arrive on Polygon after deBridge

        Args:
            polygon_address: Polygon address to check
            expected_min: Minimum POL expected
            timeout: Max wait time in seconds (default 5 min)
            status_callback: Optional callback for status updates

        Returns:
            POL balance if arrived, None if timeout
        """
        try:
            logger.info(f"⏳ Waiting for POL arrival on Polygon (min {expected_min:.2f} POL)...")

            start_time = time.time()
            check_interval = 10  # Check every 10 seconds

            while time.time() - start_time < timeout:
                pol_balance = self.get_pol_balance(polygon_address)

                if pol_balance >= expected_min:
                    logger.info(f"✅ POL arrived! Balance: {pol_balance:.4f} POL")
                    if status_callback:
                        await status_callback(
                            f"✅ POL received on Polygon!\n\n"
                            f"Balance: {pol_balance:.4f} POL\n\n"
                            f"⏳ Swapping POL → USDC.e..."
                        )
                    return pol_balance

                elapsed = int(time.time() - start_time)
                if elapsed % 30 == 0 and status_callback:  # Update every 30s
                    await status_callback(
                        f"⏳ Waiting for POL... ({elapsed}s / {timeout}s)\n\n"
                        f"Current balance: {pol_balance:.4f} POL\n"
                        f"Expected: {expected_min:.2f} POL"
                    )

                await asyncio.sleep(check_interval)

            logger.error(f"⏰ Timeout waiting for POL ({timeout}s)")
            return None

        except Exception as e:
            logger.error(f"❌ Error waiting for POL: {e}")
            return None

    async def wait_for_usdc_arrival(
        self,
        address: str,
        expected_min: float,
        timeout: int = 180,
        status_callback: Optional[Callable] = None
    ) -> bool:
        """
        Wait for USDC to arrive in Solana wallet after swap

        Args:
            address: Solana address to check
            expected_min: Minimum USDC expected
            timeout: Max wait time in seconds
            status_callback: Optional callback for status updates

        Returns:
            True if USDC arrived, False if timeout
        """
        try:
            logger.info(f"⏳ Waiting for USDC arrival (min {expected_min:.2f} USDC)...")

            start_time = time.time()
            check_interval = 3  # Check every 3 seconds

            while time.time() - start_time < timeout:
                usdc_balance = await self.get_usdc_balance(address)

                if usdc_balance >= expected_min:
                    logger.info(f"✅ USDC arrived! Balance: {usdc_balance:.6f} USDC")
                    if status_callback:
                        await status_callback(
                            f"✅ USDC received on Solana!\n\n"
                            f"Balance: {usdc_balance:.6f} USDC"
                        )
                    return True

                elapsed = int(time.time() - start_time)
                if elapsed % 10 == 0 and status_callback:  # Update every 10s
                    await status_callback(
                        f"⏳ Waiting for USDC... ({elapsed}s)\n\n"
                        f"Current balance: {usdc_balance:.6f} USDC\n"
                        f"Expected: {expected_min:.2f} USDC"
                    )

                await asyncio.sleep(check_interval)

            logger.error(f"⏰ Timeout waiting for USDC ({timeout}s)")
            return False

        except Exception as e:
            logger.error(f"❌ Error waiting for USDC: {e}")
            return False

    async def execute_full_bridge(
        self,
        sol_amount: float,
        solana_address: str,
        solana_private_key: str,
        polygon_address: str,
        polygon_private_key: str,
        status_callback: Optional[Callable] = None
    ) -> Optional[Dict]:
        """
        Execute complete bridge: SOL → USDC → POL → USDC.e

        Args:
            sol_amount: Amount of SOL to bridge
            polygon_address: Destination Polygon address
            polygon_private_key: Polygon private key for QuickSwap
            status_callback: Status update callback

        Returns:
            Result dict with signatures and amounts
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🌉 BRIDGE V3: SOL → USDC → POL")
            logger.info(f"   Solana address: {solana_address}")
            logger.info(f"   Solana privkey starts with: {solana_private_key[:10]}...")
            logger.info(f"   Polygon address: {polygon_address}")
            logger.info(f"   Amount: {sol_amount:.6f} SOL")
            logger.info(f"   Destination: {polygon_address}")
            logger.info(f"{'='*60}\n")

            # STEP 0.5: Verify we have enough SOL and calculate exact amount
            logger.info(f"💰 Checking SOL balance and calculating exact fees...")
            from .solana_transaction import SolanaTransactionBuilder
            sol_builder = SolanaTransactionBuilder()
            balance = await sol_builder.get_sol_balance(solana_address)

            logger.info(f"   Current balance: {balance:.6f} SOL")
            logger.info(f"   Requested swap: {sol_amount:.6f} SOL")

            # CRITICAL: Reserve SOL for deBridge transaction fees
            # deBridge transaction needs ~0.017 SOL in fees + buffer
            DEBRIDGE_FEE_RESERVE = 0.025  # Reserve 0.025 SOL for deBridge tx fees

            # Calculate actual amount to swap (balance - reserve)
            # If user requested specific amount, we need to make sure we have enough for fees
            max_swappable = balance - DEBRIDGE_FEE_RESERVE

            if sol_amount > max_swappable:
                logger.warning(f"⚠️ Adjusting swap amount to leave SOL for deBridge fees")
                logger.warning(f"   Requested: {sol_amount:.6f} SOL")
                logger.warning(f"   Maximum swappable: {max_swappable:.6f} SOL (balance - {DEBRIDGE_FEE_RESERVE} reserve)")
                actual_swap_amount = max_swappable
            else:
                actual_swap_amount = sol_amount

            # Verify we still have enough after reserve
            if actual_swap_amount < 0.01:  # Minimum 0.01 SOL to swap
                error_msg = (
                    f"❌ Solde SOL insuffisant après réserve fees!\n\n"
                    f"Balance: {balance:.6f} SOL\n"
                    f"Réserve deBridge: {DEBRIDGE_FEE_RESERVE:.6f} SOL\n"
                    f"Disponible swap: {actual_swap_amount:.6f} SOL\n"
                    f"Minimum requis: 0.01 SOL"
                )
                logger.error(error_msg)
                if status_callback:
                    await status_callback(error_msg)
                return {'success': False, 'error': 'insufficient_sol_after_reserve', 'balance': balance}

            logger.info(f"💰 Swap calculation:")
            logger.info(f"   Total balance: {balance:.6f} SOL")
            logger.info(f"   deBridge reserve: {DEBRIDGE_FEE_RESERVE:.6f} SOL")
            logger.info(f"   Amount to swap: {actual_swap_amount:.6f} SOL")
            logger.info(f"   SOL remaining after swap: ~{DEBRIDGE_FEE_RESERVE:.6f} SOL (for deBridge fees)")

            # STEP 1: Swap SOL → USDC on Solana
            logger.info(f"📊 STEP 1/2: Swap SOL → USDC via Jupiter...")
            if status_callback:
                await status_callback(
                    f"🔄 Step 1/2: Swapping SOL → USDC\n\n"
                    f"Amount: {actual_swap_amount:.6f} SOL\n"
                    f"Balance: {balance:.6f} SOL\n"
                    f"Reserve: {DEBRIDGE_FEE_RESERVE:.6f} SOL for fees"
                )

            swap_result = await swap_sol_to_usdc(
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

            logger.info(f"✅ Swap completed!")
            logger.info(f"   Signature: {swap_signature}")
            logger.info(f"   USDC estimate: {usdc_estimate:.6f}")

            if status_callback:
                await status_callback(
                    f"✅ Swap confirmed!\n\n"
                    f"TX: `{swap_signature}`\n\n"
                    f"⏳ Verifying USDC balance..."
                )

            # STEP 2: Verify USDC balance (swap is atomic - USDC already there!)
            logger.info(f"💰 Checking USDC balance after swap...")

            # Wait 3 seconds for RPC to sync
            await asyncio.sleep(3)

            usdc_balance = await self.get_usdc_balance(solana_address)

            logger.info(f"💰 USDC balance: {usdc_balance:.6f} USDC")

            # Verify swap succeeded by checking USDC balance
            if usdc_balance < (usdc_estimate * 0.5):  # At least 50% of expected
                logger.error(f"❌ Swap failed - USDC balance too low!")
                logger.error(f"   Expected: ~{usdc_estimate:.2f} USDC")
                logger.error(f"   Got: {usdc_balance:.6f} USDC")
                logger.error(f"   Check TX: https://solscan.io/tx/{swap_signature}")

                if status_callback:
                    await status_callback(
                        f"❌ Swap failed - USDC not received\n\n"
                        f"Expected: {usdc_estimate:.2f} USDC\n"
                        f"Received: {usdc_balance:.6f} USDC\n\n"
                        f"TX: `{swap_signature}`"
                    )

                return {
                    'success': False,
                    'step': 'swap_failed_no_usdc',
                    'swap_signature': swap_signature,
                    'usdc_received': usdc_balance,
                    'usdc_expected': usdc_estimate
                }

            logger.info(f"✅ USDC confirmed: {usdc_balance:.6f} USDC (swap successful!)")

            # STEP 3: Bridge USDC → POL via deBridge (NO PreSwap!)
            logger.info(f"\n📊 STEP 2/2: Bridge USDC → POL via deBridge...")
            if status_callback:
                await status_callback(
                    f"🌉 Step 2/2: Bridging USDC → POL\n\n"
                    f"Amount: {usdc_balance:.2f} USDC\n"
                    f"Destination: Polygon\n\n"
                    f"⏱️ This takes 2-5 minutes..."
                )

            # Get deBridge quote for USDC → POL (NO PreSwap needed!)
            # CRITICAL: Bridge 90% of USDC to leave margin for operating expenses
            # deBridge adds ~8% operating expenses, so we need to bridge less than we have
            usdc_to_bridge = usdc_balance * 0.90  # Bridge 90%, keep 10% for fees
            usdc_lamports = int(usdc_to_bridge * 1e6)  # USDC has 6 decimals

            logger.info(f"💰 Bridging {usdc_to_bridge:.2f} USDC (90% of {usdc_balance:.2f} USDC)")
            logger.info(f"   Keeping {usdc_balance - usdc_to_bridge:.2f} USDC for deBridge operating expenses")

            debridge_quote = debridge_client.get_quote(
                src_chain_id=SOLANA_CHAIN_ID,
                src_token=USDC_SOLANA_ADDRESS,  # USDC on Solana
                dst_chain_id=POLYGON_CHAIN_ID,
                dst_token=POL_TOKEN_ADDRESS,  # POL on Polygon
                amount=str(usdc_lamports),
                src_address=solana_address,  # Use user's generated address
                dst_address=polygon_address,
                enable_refuel=False  # We're getting POL directly
            )

            if not debridge_quote:
                logger.error("❌ Failed to get deBridge quote for USDC → POL")
                if status_callback:
                    await status_callback("❌ Failed to get deBridge quote")
                return {
                    'success': False,
                    'step': 'debridge_quote_failed',
                    'swap_signature': swap_signature,
                    'usdc_received': usdc_balance
                }

            pol_expected = int(debridge_quote.get('dst_amount', 0)) / 1e18
            logger.info(f"💰 deBridge quote: {usdc_balance:.2f} USDC → {pol_expected:.2f} POL")

            if status_callback:
                await status_callback(
                    f"📊 Bridge quote received!\n\n"
                    f"{usdc_balance:.2f} USDC → {pol_expected:.2f} POL\n\n"
                    f"⏳ Creating order..."
                )

            # Create deBridge order
            order_data = debridge_client.create_order(
                quote=debridge_quote,
                src_address=solana_address,  # Use user's generated address
                dst_address=polygon_address
            )

            if not order_data:
                logger.error("❌ Failed to create deBridge order")
                if status_callback:
                    await status_callback("❌ Failed to create bridge order")
                return {
                    'success': False,
                    'step': 'debridge_order_failed',
                    'swap_signature': swap_signature,
                    'usdc_received': usdc_balance
                }

            order_id = order_data.get('orderId')
            logger.info(f"✅ deBridge order created: {order_id}")

            # Parse and sign deBridge transaction
            if status_callback:
                await status_callback(f"✍️ Signing bridge transaction...")

            from solders.keypair import Keypair
            import base58

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
                if status_callback:
                    await status_callback("❌ Failed to sign bridge transaction")
                return {
                    'success': False,
                    'step': 'debridge_sign_failed',
                    'swap_signature': swap_signature,
                    'usdc_received': usdc_balance
                }

            # Broadcast deBridge transaction
            if status_callback:
                await status_callback(f"📡 Broadcasting bridge transaction...")

            debridge_signature = await self.solana_builder.send_transaction(signed_debridge_tx)

            if not debridge_signature:
                logger.error("❌ Failed to broadcast deBridge transaction")
                if status_callback:
                    await status_callback("❌ Failed to broadcast bridge transaction")
                return {
                    'success': False,
                    'step': 'debridge_broadcast_failed',
                    'swap_signature': swap_signature,
                    'usdc_received': usdc_balance
                }

            logger.info(f"✅ deBridge transaction sent: {debridge_signature}")

            if status_callback:
                await status_callback(
                    f"✅ deBridge tx envoyée!\n\n"
                    f"TX Solana: `{debridge_signature}`\n\n"
                    f"⏳ Attente confirmation Solana..."
                )

            # Wait for Solana confirmation
            debridge_confirmed = await self.solana_builder.confirm_transaction(debridge_signature, timeout=120)

            if not debridge_confirmed:
                logger.warning(f"⚠️ deBridge tx timeout (may still succeed)")
                # Don't fail - continue waiting for Polygon
            else:
                logger.info(f"✅ deBridge tx confirmed on Solana!")

            if status_callback:
                await status_callback(
                    f"✅ Confirmé sur Solana!\n\n"
                    f"⏳ Attente POL sur Polygon...\n"
                    f"(2-5 minutes)\n\n"
                    f"Order: {order_id}"
                )

            # STEP 4: Wait for POL arrival on Polygon
            logger.info(f"\n📊 STEP 3/3: Waiting for POL on Polygon...")

            pol_balance = await self.wait_for_pol_arrival(
                polygon_address=polygon_address,
                expected_min=pol_expected * 0.8,  # Accept 80% of expected (fees, slippage)
                timeout=300,  # 5 minutes
                status_callback=status_callback
            )

            if not pol_balance or pol_balance < MIN_POL_FOR_GAS:
                logger.error(f"❌ POL not arrived or insufficient: {pol_balance}")
                if status_callback:
                    await status_callback(
                        f"⏰ Timeout POL ou montant insuffisant\n\n"
                        f"Reçu: {pol_balance if pol_balance else 0:.4f} POL\n"
                        f"Check order: {order_id}"
                    )
                return {
                    'success': False,
                    'step': 'pol_arrival_timeout',
                    'swap_signature': swap_signature,
                    'debridge_signature': debridge_signature,
                    'order_id': order_id,
                    'pol_received': pol_balance
                }

            logger.info(f"✅ POL received: {pol_balance:.4f} POL")

            # STEP 5: Swap excess POL → USDC.e (keep MIN_POL_FOR_GAS for gas)
            logger.info(f"\n📊 STEP 4/4: Swap POL → USDC.e via QuickSwap...")

            pol_to_swap = pol_balance - MIN_POL_FOR_GAS

            if pol_to_swap <= 0.1:  # Minimum 0.1 POL to swap
                logger.info(f"ℹ️ Not enough excess POL to swap ({pol_to_swap:.4f} POL)")
                usdc_e_received = 0
                quickswap_tx = None
            else:
                logger.info(f"💱 Swapping {pol_to_swap:.4f} POL → USDC.e (keeping {MIN_POL_FOR_GAS} POL for gas)")

                if status_callback:
                    await status_callback(
                        f"💱 Swap POL → USDC.e\n\n"
                        f"Montant: {pol_to_swap:.4f} POL\n"
                        f"Garde: {MIN_POL_FOR_GAS} POL (gas)"
                    )

                try:
                    # Use QuickSwap to swap POL → USDC.e
                    quickswap_tx = quickswap_client.swap_pol_to_usdc(
                        pol_amount=pol_to_swap,
                        recipient_address=polygon_address,
                        private_key=polygon_private_key
                    )

                    if quickswap_tx:
                        logger.info(f"✅ QuickSwap complete!")
                        logger.info(f"   Swapped: {pol_to_swap:.4f} POL → USDC.e")
                        logger.info(f"   TX: {quickswap_tx}")

                        # Estimate USDC.e received (actual amount in receipt)
                        # For now, use conservative estimate based on quote
                        usdc_e_received = pol_to_swap * 0.23  # ~$0.23 per POL

                        if status_callback:
                            await status_callback(
                                f"✅ Swap POL→USDC.e terminé!\n\n"
                                f"~{usdc_e_received:.2f} USDC.e reçu\n"
                                f"TX: `{quickswap_tx}`"
                            )
                    else:
                        logger.warning(f"⚠️ QuickSwap failed or no POL to swap")
                        usdc_e_received = 0
                        quickswap_tx = None

                except Exception as e:
                    logger.error(f"❌ QuickSwap error: {e}")
                    usdc_e_received = 0
                    quickswap_tx = None

            logger.info(f"\n{'='*60}")
            logger.info(f"✅ BRIDGE V3 COMPLETE!")
            logger.info(f"   Swap SOL→USDC: {swap_signature}")
            logger.info(f"   Bridge USDC→POL: {debridge_signature}")
            logger.info(f"   Order ID: {order_id}")
            logger.info(f"   POL received: {pol_balance:.4f} POL")
            logger.info(f"   POL kept for gas: {MIN_POL_FOR_GAS} POL")
            if quickswap_tx:
                logger.info(f"   QuickSwap: {quickswap_tx}")
                logger.info(f"   USDC.e received: {usdc_e_received:.2f}")
            logger.info(f"{'='*60}\n")

            if status_callback:
                success_msg = f"🎉 BRIDGE COMPLETE!\n\n"
                success_msg += f"✅ Swap SOL→USDC: `{swap_signature}`\n"
                success_msg += f"✅ Bridge USDC→POL: `{debridge_signature}`\n"
                success_msg += f"✅ POL received: {pol_balance:.4f} POL\n"

                if quickswap_tx:
                    success_msg += f"✅ QuickSwap: `{quickswap_tx}`\n"
                    success_msg += f"💰 USDC.e: {usdc_e_received:.2f}\n"

                success_msg += f"💰 POL gas: {MIN_POL_FOR_GAS} POL\n\n"
                success_msg += f"Order: {order_id}\n\n"
                success_msg += f"🎯 Wallet ready for Polymarket!"

                await status_callback(success_msg)

            return {
                'success': True,
                'swap_signature': swap_signature,
                'debridge_signature': debridge_signature,
                'order_id': order_id,
                'usdc_swapped': usdc_to_bridge,
                'pol_received': pol_balance,
                'pol_kept_for_gas': MIN_POL_FOR_GAS,
                'quickswap_tx': quickswap_tx,
                'usdc_e_received': usdc_e_received
            }

        except Exception as e:
            logger.error(f"❌ Bridge V3 error: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            if status_callback:
                await status_callback(f"❌ Bridge error: {str(e)}")
            return {'success': False, 'error': str(e)}


# Global instance
bridge_v3 = BridgeV3()
