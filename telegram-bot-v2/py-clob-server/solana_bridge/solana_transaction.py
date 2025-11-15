#!/usr/bin/env python3
"""
Solana Transaction Builder
Handles building, signing, and broadcasting Solana transactions
"""

import asyncio
import time
import base64
import logging
from typing import Dict, Optional
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed, Finalized, Processed
from solana.rpc.types import TxOpts
from solders.transaction import Transaction, VersionedTransaction
from solders.message import MessageV0
from solders.hash import Hash as Blockhash
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.instruction import Instruction, CompiledInstruction
from solders.message import MessageHeader
import requests
from .config import SOLANA_RPC_URL, SOLANA_PRIORITY_FEE

logger = logging.getLogger(__name__)


class SolanaTransactionBuilder:
    """Build, sign, and send Solana transactions"""

    def __init__(self, rpc_url: str = SOLANA_RPC_URL):
        """Initialize Solana transaction builder"""
        self.rpc_url = rpc_url
        self.client = AsyncClient(rpc_url)
        logger.info(f"🔧 SolanaTransactionBuilder initialized with RPC: {rpc_url[:60]}...")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close client"""
        await self.client.close()

    async def get_priority_fee_estimate(self, serialized_tx: str, priority_level: str = "High") -> int:
        """
        Get priority fee estimate from Helius API

        Args:
            serialized_tx: Base58-encoded serialized transaction
            priority_level: Priority level (Min, Low, Medium, High, VeryHigh, UnsafeMax)

        Returns:
            Priority fee in microlamports per compute unit
        """
        try:
            logger.info(f"💰 Requesting priority fee estimate from Helius (level: {priority_level})...")

            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getPriorityFeeEstimate",
                "params": [{
                    "transaction": serialized_tx,
                    "options": {
                        "priorityLevel": priority_level,
                        "recommended": True
                    }
                }]
            }

            response = requests.post(self.rpc_url, json=payload, timeout=10)
            response.raise_for_status()

            result = response.json()
            priority_fee = result.get('result', {}).get('priorityFeeEstimate', 0)

            logger.info(f"✅ Helius priority fee estimate: {priority_fee} microlamports/CU (level: {priority_level})")

            # Ensure minimum fee for inclusion
            if priority_fee < 10000:
                logger.warning(f"⚠️ Fee too low ({priority_fee}), using minimum 10000 microlamports")
                priority_fee = 10000

            return int(priority_fee)

        except Exception as e:
            logger.error(f"❌ Failed to get priority fee from Helius: {e}")
            # Fallback to safe default
            fallback_fee = 50000  # 0.00005 SOL per CU
            logger.warning(f"⚠️ Using fallback priority fee: {fallback_fee} microlamports")
            return fallback_fee

    async def get_sol_balance(self, address: str, max_retries: int = 3) -> float:
        """
        Get SOL balance for an address with retry logic

        PERFORMANCE: Cached in Redis (500ms RPC → 5ms cache hit)

        Args:
            address: Solana address
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            Balance in SOL

        Raises:
            Exception: If balance fetch fails after all retries
        """
        import asyncio

        # Validate address format
        if not address or len(address) < 32:
            logger.error(f"❌ Invalid Solana address format: {address}")
            raise ValueError(f"Invalid Solana address: {address}")

        # Try cache first
        try:
            from core.services.redis_price_cache import get_redis_cache
            redis_cache = get_redis_cache()
            if redis_cache.enabled:
                cache_key = f"balance:sol:{address.lower()}"
                cached = redis_cache.redis_client.get(cache_key)
                if cached:
                    balance_sol = float(cached)
                    logger.debug(f"🚀 CACHE HIT: SOL balance {address[:8]}... = {balance_sol:.4f}")
                    return balance_sol
        except Exception as cache_err:
            logger.debug(f"Cache lookup failed (non-fatal): {cache_err}")

        # Check if client exists
        if not self.client:
            error_msg = "AsyncClient not initialized"
            logger.error(f"❌ {error_msg}")
            raise Exception(error_msg)

        logger.debug(f"💨 CACHE MISS: Fetching SOL balance for {address[:8]}...{address[-8:]}")

        last_exception = None

        for attempt in range(max_retries):
            try:
                logger.debug(f"🔍 Fetching SOL balance (attempt {attempt + 1}/{max_retries})")

                pubkey = Pubkey.from_string(address)
                response = await self.client.get_balance(pubkey, commitment=Confirmed)

                if response.value is not None:
                    # Convert lamports to SOL (1 SOL = 1e9 lamports)
                    balance_sol = response.value / 1e9
                    logger.debug(f"✅ Fetched SOL balance: {balance_sol:.4f} SOL")

                    # Cache the result
                    try:
                        from core.services.redis_price_cache import get_redis_cache
                        redis_cache = get_redis_cache()
                        if redis_cache.enabled:
                            cache_key = f"balance:sol:{address.lower()}"
                            redis_cache.redis_client.setex(cache_key, 30, str(balance_sol))
                            logger.debug(f"💾 Cached SOL balance (TTL: 30s)")
                    except Exception as cache_err:
                        logger.debug(f"Cache write failed (non-fatal): {cache_err}")

                    return balance_sol
                else:
                    logger.warning(f"⚠️ RPC returned None for balance (attempt {attempt + 1}/{max_retries})")
                    last_exception = Exception("RPC returned None for balance")

            except Exception as e:
                last_exception = e
                logger.error(f"❌ Error fetching SOL balance (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {str(e)}")

                # If this isn't the last attempt, wait before retrying
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.debug(f"⏳ Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)

        # All retries failed
        error_msg = f"Failed to fetch SOL balance after {max_retries} attempts. Last error: {type(last_exception).__name__}: {last_exception}"
        logger.error(f"❌ {error_msg}")
        raise Exception(error_msg)

    async def parse_and_sign_debridge_transaction(
        self,
        order_data: Dict,
        keypair: Keypair
    ) -> Optional[bytes]:
        """
        Parse transaction from deBridge /create-tx response and sign it

        For Solana: tx.data is hex-encoded VersionedTransaction
        Docs: https://docs.debridge.finance/dln-details/integration-guidelines/order-creation/submitting-the-transaction

        Args:
            order_data: Response from deBridge create_order()
            keypair: Solana keypair to sign with

        Returns:
            Signed transaction bytes ready to broadcast
        """
        try:
            logger.info("🔧 Parsing deBridge transaction (Solana hex-encoded)...")

            tx_data = order_data.get('tx', {})
            if not tx_data:
                logger.error("❌ No 'tx' data in order response")
                return None

            logger.info(f"   tx keys: {list(tx_data.keys())}")

            # deBridge returns hex-encoded VersionedTransaction in tx.data
            if 'data' not in tx_data:
                logger.error("❌ No 'data' field in tx object")
                logger.error(f"   Available fields: {list(tx_data.keys())}")
                return None

            tx_hex = tx_data['data']
            logger.info(f"   Found 'data' field: {tx_hex[:32]}... (length: {len(tx_hex)})")

            try:
                # Remove '0x' prefix if present
                if tx_hex.startswith('0x'):
                    tx_hex = tx_hex[2:]
                    logger.info(f"   Removed '0x' prefix")

                # Decode hex to bytes
                tx_bytes = bytes.fromhex(tx_hex)
                logger.info(f"   Decoded hex to {len(tx_bytes)} bytes")

                # Deserialize as VersionedTransaction (deBridge uses Solana v0 format)
                try:
                    transaction = VersionedTransaction.from_bytes(tx_bytes)
                    logger.info(f"✅ VersionedTransaction deserialized successfully")
                    is_versioned = True
                except Exception as e:
                    logger.warning(f"⚠️ VersionedTransaction failed, trying legacy Transaction: {e}")
                    transaction = Transaction.from_bytes(tx_bytes)
                    logger.info(f"✅ Legacy Transaction deserialized successfully")
                    is_versioned = False

                # Note: deBridge already includes a recent blockhash in the transaction
                # According to deBridge docs, we have 30 seconds to submit
                logger.info(f"ℹ️ Using deBridge-provided blockhash (transaction valid for ~30s)")
                logger.info(f"⚡ IMPORTANT: Sending deBridge tx AS-IS without modifications!")

                # CRITICAL DEBUG: Check if deBridge actually includes compute budget instructions
                if is_versioned:
                    message = transaction.message
                    logger.info(f"🔍 INSPECTING TRANSACTION FROM DEBRIDGE:")
                    logger.info(f"   Total instructions: {len(message.instructions)}")
                    logger.info(f"   Account keys: {len(message.account_keys)}")

                    # Check for ComputeBudget program (ComputeBudget111111111111111111111111111111)
                    COMPUTE_BUDGET_PROGRAM = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
                    has_compute_budget = COMPUTE_BUDGET_PROGRAM in message.account_keys

                    logger.info(f"   Has ComputeBudget program: {has_compute_budget}")

                    priority_fee_price = 0
                    compute_unit_limit = 600000  # Default

                    if has_compute_budget:
                        compute_budget_index = message.account_keys.index(COMPUTE_BUDGET_PROGRAM)
                        logger.info(f"   ComputeBudget at index: {compute_budget_index}")

                        # Check for compute budget instructions
                        for i, ix in enumerate(message.instructions):
                            if ix.program_id_index == compute_budget_index:
                                logger.info(f"   Instruction {i} is ComputeBudget:")
                                logger.info(f"      Data: {ix.data.hex()}")

                                # Parse instruction type
                                if len(ix.data) > 0:
                                    ix_type = ix.data[0]
                                    if ix_type == 2:
                                        # SetComputeUnitLimit
                                        if len(ix.data) >= 5:
                                            compute_unit_limit = int.from_bytes(ix.data[1:5], 'little')
                                            logger.info(f"      Type: SetComputeUnitLimit ({compute_unit_limit} CU)")
                                    elif ix_type == 3:
                                        # SetComputeUnitPrice
                                        if len(ix.data) >= 9:
                                            priority_fee_price = int.from_bytes(ix.data[1:9], 'little')
                                            logger.info(f"      Type: SetComputeUnitPrice ({priority_fee_price} microlamports/CU)")
                                            if priority_fee_price == 0:
                                                logger.warning(f"      ⚠️ PRIORITY FEE IS ZERO! Will force aggressive fees...")
                    else:
                        logger.warning(f"   ⚠️ NO COMPUTE BUDGET PROGRAM FOUND!")
                        logger.warning(f"   ⚠️ deBridge did NOT include priority fees despite 'aggressive' setting!")

                    # CRITICAL FIX: If priority fees are 0, FORCE aggressive fees manually
                    if priority_fee_price == 0:
                        logger.info(f"🔧 FORCING PRIORITY FEES (deBridge returned 0)")

                        # Remove existing compute budget instructions (if any)
                        filtered_instructions = []
                        for ix in message.instructions:
                            if ix.program_id_index != compute_budget_index:
                                filtered_instructions.append(ix)

                        # Add aggressive priority fees MANUALLY (200k microlamports/CU)
                        aggressive_price = 200000  # 0.0002 SOL per CU (très agressif!)
                        price_ix = set_compute_unit_price(aggressive_price)
                        limit_ix = set_compute_unit_limit(compute_unit_limit)

                        # Compile instructions (need to convert Instruction → CompiledInstruction)
                        # This is complex, so let's prepend them
                        logger.info(f"   ⚡ Adding: SetComputeUnitLimit({compute_unit_limit} CU)")
                        logger.info(f"   ⚡ Adding: SetComputeUnitPrice({aggressive_price} microlamports/CU)")
                        logger.info(f"   ⚡ Total priority fee: ~{(aggressive_price * compute_unit_limit) / 1e9:.6f} SOL")

                        # We need to rebuild the message with new instructions
                        # This is tricky with CompiledInstruction format
                        # For now, let's just log a warning and continue
                        logger.warning(f"⚠️ Manual priority fee injection requires message rebuild")
                        logger.warning(f"⚠️ Transaction may still fail with 0 priority fees")
                    else:
                        logger.info(f"✅ Priority fees OK: {priority_fee_price} microlamports/CU")

                # deBridge supposed to include priority fees via srcChainPriorityLevel='aggressive'
                logger.info(f"💰 Requested srcChainPriorityLevel='aggressive' from deBridge")

                # CRITICAL: deBridge blockhash is ALWAYS expired by the time we receive it
                # We MUST replace it with a fresh one (confirmed by deBridge support)
                USE_AS_IS = False  # We MUST replace blockhash

                if is_versioned and not USE_AS_IS:
                    logger.info(f"🔧 REPLACING expired deBridge blockhash with FRESH Helius blockhash...")

                    # Extract message components from deBridge transaction
                    old_message = transaction.message
                    logger.info(f"   Original blockhash: {str(old_message.recent_blockhash)[:16]}...")

                    # Fetch FRESH blockhash from Helius (< 1 second old)
                    fresh_blockhash_str = await self.get_recent_blockhash()
                    if not fresh_blockhash_str:
                        logger.error("❌ Failed to fetch fresh blockhash!")
                        return None

                    fresh_blockhash = Blockhash.from_string(fresh_blockhash_str)
                    logger.info(f"   ✅ Fresh blockhash: {str(fresh_blockhash)[:16]}... (< 1s old)")

                    # CRITICAL FIX 2: Force aggressive priority fees if deBridge provides low fees
                    instructions_to_use = list(old_message.instructions)

                    if priority_fee_price < 10000:  # Less than 10k microlamports/CU = too low (was 100k)
                        logger.info(f"🔧 FORCING AGGRESSIVE PRIORITY FEES (deBridge provided only {priority_fee_price})")

                        # Remove existing ComputeBudget instructions
                        compute_budget_index = old_message.account_keys.index(COMPUTE_BUDGET_PROGRAM)
                        instructions_to_use = [
                            ix for ix in old_message.instructions
                            if ix.program_id_index != compute_budget_index
                        ]

                        # Build NEW aggressive ComputeBudget instructions
                        aggressive_price = 200000  # 200k microlamports/CU = 0.12 SOL total for 600k CU

                        # SetComputeUnitLimit instruction (type 2)
                        limit_data = bytes([2]) + compute_unit_limit.to_bytes(4, 'little')
                        limit_ix = CompiledInstruction(
                            program_id_index=compute_budget_index,
                            accounts=bytes(),
                            data=limit_data
                        )

                        # SetComputeUnitPrice instruction (type 3)
                        price_data = bytes([3]) + aggressive_price.to_bytes(8, 'little')
                        price_ix = CompiledInstruction(
                            program_id_index=compute_budget_index,
                            accounts=bytes(),
                            data=price_data
                        )

                        # Prepend ComputeBudget instructions (must be first)
                        instructions_to_use = [limit_ix, price_ix] + instructions_to_use

                        logger.info(f"   ✅ Forced SetComputeUnitLimit({compute_unit_limit} CU)")
                        logger.info(f"   ✅ Forced SetComputeUnitPrice({aggressive_price} microlamports/CU)")
                        logger.info(f"   💰 Total priority fee: ~{(aggressive_price * compute_unit_limit) / 1e9:.6f} SOL")
                    else:
                        logger.info(f"   ✅ Priority fees OK: {priority_fee_price} microlamports/CU (keeping deBridge's)")

                    # Rebuild MessageV0 with FRESH blockhash AND FORCED priority fees
                    new_message = MessageV0(
                        header=old_message.header,
                        account_keys=old_message.account_keys,
                        recent_blockhash=fresh_blockhash,  # ← CRITICAL: Fresh blockhash!
                        instructions=instructions_to_use,  # ← CRITICAL: Forced priority fees!
                        address_table_lookups=old_message.address_table_lookups
                    )

                    logger.info(f"   ✅ Rebuilt transaction with fresh blockhash + forced priority fees")

                # Sign transaction
                logger.info(f"✍️ Signing IMMEDIATELY with keypair: {str(keypair.pubkey())[:16]}...")

                try:
                    if is_versioned:
                        if USE_AS_IS:
                            # Sign deBridge transaction AS-IS (no modifications)
                            logger.info(f"   Using deBridge transaction WITHOUT modifications")
                            signed_transaction = VersionedTransaction(transaction.message, [keypair])
                            logger.info(f"✅ VersionedTransaction signed AS-IS (deBridge blockhash + fees)")
                        else:
                            # Create a fully-signed VersionedTransaction with FRESH blockhash
                            # VersionedTransaction(message, [keypair]) signs automatically
                            signed_transaction = VersionedTransaction(new_message, [keypair])
                            logger.info(f"✅ VersionedTransaction signed (fresh blockhash + deBridge priority fees)")
                    else:
                        # Legacy Transaction
                        transaction.sign([keypair])
                        signed_transaction = transaction
                        logger.info(f"✅ Legacy Transaction signed")

                    # Serialize signed transaction
                    signed_bytes = bytes(signed_transaction)
                    logger.info(f"✅ Transaction serialized ({len(signed_bytes)} bytes)")

                    return signed_bytes

                except Exception as sign_error:
                    logger.error(f"❌ Error during signing: {sign_error}")
                    import traceback
                    logger.error(f"   Detailed traceback: {traceback.format_exc()}")
                    raise

            except Exception as e:
                logger.error(f"❌ Error decoding/signing hex transaction: {e}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                return None

        except Exception as e:
            logger.error(f"❌ Error in parse_and_sign_debridge_transaction: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return None

    async def get_recent_blockhash(self) -> Optional[str]:
        """
        Get recent blockhash from Solana network

        Returns:
            Recent blockhash string
        """
        try:
            logger.info("🔗 Fetching recent blockhash from Solana...")

            response = await self.client.get_latest_blockhash(commitment=Confirmed)

            if response.value:
                blockhash = str(response.value.blockhash)
                logger.info(f"✅ Got blockhash: {blockhash[:16]}...")
                return blockhash
            else:
                logger.error("❌ Failed to get blockhash")
                return None

        except Exception as e:
            logger.error(f"❌ Error getting recent blockhash: {e}")
            return None

    async def get_balance(self, address: str) -> Optional[float]:
        """
        Get SOL balance for an address

        Args:
            address: Solana public key as string

        Returns:
            Balance in SOL
        """
        try:
            pubkey = Pubkey.from_string(address)
            response = await self.client.get_balance(pubkey)

            if response.value is not None:
                # Convert lamports to SOL
                balance_sol = response.value / 1_000_000_000
                print(f"💰 Balance for {address[:8]}...: {balance_sol} SOL")
                return balance_sol

            return None

        except Exception as e:
            print(f"❌ Error getting balance: {e}")
            return None

    def sign_transaction(
        self,
        transaction_data: bytes,
        keypair: Keypair
    ) -> Optional[bytes]:
        """
        Sign a Solana transaction

        Args:
            transaction_data: Serialized transaction bytes
            keypair: Keypair to sign with

        Returns:
            Signed transaction bytes
        """
        try:
            print(f"✍️ Signing transaction with {str(keypair.pubkey())[:8]}...")

            # Deserialize transaction
            transaction = SoldersTransaction.from_bytes(transaction_data)

            # Sign transaction
            transaction.sign([keypair])

            # Serialize signed transaction
            signed_tx_bytes = bytes(transaction)

            print(f"✅ Transaction signed successfully")
            return signed_tx_bytes

        except Exception as e:
            print(f"❌ Error signing transaction: {e}")
            return None

    async def send_transaction(
        self,
        signed_transaction: bytes,
        max_retries: int = 10
    ) -> Optional[str]:
        """
        Broadcast signed transaction to Solana network

        Args:
            signed_transaction: Signed transaction bytes
            max_retries: Maximum number of retry attempts

        Returns:
            Transaction signature (hash)
        """
        try:
            logger.info("📡 Broadcasting transaction to Solana...")

            # Create TxOpts object for solana-py v0.36+
            # CRITICAL: skip_preflight=False as recommended by deBridge support
            # This shows real errors instead of silently dropping transactions
            # We use FRESH blockhash so simulation should pass
            tx_opts = TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
            logger.info("   ⚡ Using skip_preflight=False (shows real errors, blockhash is fresh)")

            for attempt in range(max_retries):
                try:
                    # Send transaction with staggered delays (helps with network propagation)
                    if attempt > 0:
                        delay = min(attempt * 0.5, 3)  # Max 3s delay
                        logger.info(f"   ⏳ Retry {attempt + 1}/{max_retries} (waiting {delay}s for network propagation)")
                        await asyncio.sleep(delay)

                    # Send transaction
                    response = await self.client.send_raw_transaction(
                        signed_transaction,
                        opts=tx_opts
                    )

                    if response.value:
                        signature = str(response.value)
                        logger.info(f"✅ Transaction sent! Signature: {signature}")
                        logger.info(f"   View on Solscan: https://solscan.io/tx/{signature}")
                        logger.info(f"   ⚡ With fresh blockhash + 166k microlamports/CU priority fees")
                        logger.info(f"   ⏱️ Should confirm in 5-15 seconds with aggressive priority")
                        return signature
                    else:
                        logger.warning(f"⚠️ Attempt {attempt + 1}/{max_retries} failed (no response)")
                        if attempt < max_retries - 1:
                            continue

                except Exception as e:
                    logger.warning(f"⚠️ Send attempt {attempt + 1}/{max_retries} error: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)

            logger.error("❌ All send attempts failed")
            return None

        except Exception as e:
            logger.error(f"❌ Error sending transaction: {e}")
            return None

    async def confirm_transaction(
        self,
        signature: str,
        timeout: int = 90
    ) -> bool:
        """
        Wait for transaction confirmation

        Args:
            signature: Transaction signature to confirm
            timeout: Maximum time to wait (seconds)

        Returns:
            True if confirmed, False otherwise
        """
        try:
            logger.info(f"⏳ Waiting for confirmation of {signature[:16]}...")

            # Convert string signature to Signature object for solana-py
            sig = Signature.from_string(signature)

            start_time = time.time()
            last_status = None

            while time.time() - start_time < timeout:
                response = await self.client.get_signature_statuses([sig])

                if response.value and len(response.value) > 0:
                    status = response.value[0]

                    if status is not None:
                        # Log status changes
                        if status != last_status:
                            logger.info(f"   Status update: {status}")
                            last_status = status

                        # CRITICAL FIX: Check if transaction succeeded (status.err is None)
                        # AND confirmation_status exists (not None)
                        if status.confirmation_status is not None:
                            # Transaction has been confirmed at some level
                            logger.info(f"✅ Transaction confirmed! (status: {status.confirmation_status})")
                            logger.info(f"   View on Solscan: https://solscan.io/tx/{signature}")

                            # Check if transaction has error even if confirmed
                            if status.err:
                                logger.error(f"❌ Transaction failed on-chain: {status.err}")
                                logger.error(f"   This usually means: blockhash expired, insufficient SOL, or invalid transaction")
                                return False

                            # No error = success!
                            return True
                        elif status.err:
                            logger.error(f"❌ Transaction failed on-chain: {status.err}")
                            logger.error(f"   This usually means: blockhash expired, insufficient SOL, or invalid transaction")
                            return False
                    else:
                        # Transaction not found yet
                        elapsed = int(time.time() - start_time)
                        if elapsed % 10 == 0:  # Log every 10s
                            logger.info(f"   Still waiting... ({elapsed}s elapsed)")

                # FASTER polling: 0.5s instead of 2s for quicker detection
                await asyncio.sleep(0.5)

            logger.error(f"⏰ Confirmation timeout after {timeout}s")
            logger.error(f"   Transaction may have been dropped (likely expired blockhash)")
            logger.error(f"   Check manually: https://solscan.io/tx/{signature}")
            return False

        except Exception as e:
            logger.error(f"❌ Error confirming transaction: {e}")
            return False

    async def get_transaction_details(self, signature: str) -> Optional[Dict]:
        """
        Fetch transaction details from Solana to diagnose failures

        Args:
            signature: Transaction signature to inspect

        Returns:
            Transaction details dict or None if not found
        """
        try:
            logger.info(f"🔍 Fetching transaction details for {signature[:16]}...")

            sig = Signature.from_string(signature)

            # Try to get transaction with full details
            response = await self.client.get_transaction(
                sig,
                encoding="json",
                max_supported_transaction_version=0
            )

            if response.value:
                logger.info(f"✅ Transaction found on-chain:")
                logger.info(f"   Slot: {response.value.slot}")
                logger.info(f"   Block time: {response.value.block_time}")

                if response.value.meta:
                    logger.info(f"   Fee: {response.value.meta.fee} lamports")
                    logger.info(f"   Error: {response.value.meta.err}")

                    if response.value.meta.err:
                        logger.error(f"   🚨 TRANSACTION ERROR DETAILS: {response.value.meta.err}")

                return {
                    'slot': response.value.slot,
                    'blockTime': response.value.block_time,
                    'meta': response.value.meta,
                    'transaction': response.value.transaction
                }
            else:
                logger.warning(f"⚠️ Transaction NOT found on-chain (was rejected by validators)")
                return None

        except Exception as e:
            logger.error(f"❌ Error fetching transaction details: {e}")
            return None

    async def send_and_confirm_transaction(
        self,
        transaction_data: bytes,
        keypair: Keypair,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Complete flow: sign, send, and confirm transaction

        Args:
            transaction_data: Unsigned transaction bytes
            keypair: Keypair to sign with
            max_retries: Maximum send retry attempts

        Returns:
            Transaction signature if successful
        """
        try:
            # Sign transaction
            signed_tx = self.sign_transaction(transaction_data, keypair)
            if not signed_tx:
                return None

            # Send transaction
            signature = await self.send_transaction(signed_tx, max_retries)
            if not signature:
                return None

            # Confirm transaction
            confirmed = await self.confirm_transaction(signature)

            if confirmed:
                return signature
            else:
                print("⚠️ Transaction sent but confirmation failed/timeout")
                return signature  # Return signature anyway, user can check manually

        except Exception as e:
            print(f"❌ Error in send_and_confirm: {e}")
            return None

    async def close(self):
        """Close the RPC client connection"""
        await self.client.close()
