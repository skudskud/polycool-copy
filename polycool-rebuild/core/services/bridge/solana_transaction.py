"""
Solana Transaction Builder
Handles building, signing, and broadcasting Solana transactions
Adapted from telegram-bot-v2 for new architecture
"""
import asyncio
import time
import base64
import requests
from typing import Dict, Optional
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solana.rpc.commitment import Confirmed, Finalized, Processed
from solana.rpc.types import TxOpts
from solders.transaction import Transaction, VersionedTransaction
from solders.message import MessageV0
from solders.hash import Hash as Blockhash
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.instruction import Instruction, CompiledInstruction

from .config import BridgeConfig
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class SolanaTransactionBuilder:
    """Build, sign, and send Solana transactions"""

    def __init__(self, rpc_url: Optional[str] = None):
        """Initialize Solana transaction builder"""
        self.rpc_url = rpc_url or BridgeConfig.SOLANA_RPC_URL
        logger.info(f"🔧 SolanaTransactionBuilder initialized with RPC: {self.rpc_url[:60]}...")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - no cleanup needed for HTTP client"""
        pass

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

            import requests
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
        Uses direct HTTP RPC call to avoid GetClusterNodes error

        Args:
            address: Solana address
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            Balance in SOL

        Raises:
            Exception: If balance fetch fails after all retries
        """
        # Validate address format
        if not address or len(address) < 32:
            logger.error(f"❌ Invalid Solana address format: {address}")
            raise ValueError(f"Invalid Solana address: {address}")

        logger.debug(f"💨 Fetching SOL balance for {address[:8]}...{address[-8:]}")

        # Use direct HTTP RPC call to avoid GetClusterNodes error
        import requests

        last_exception = None

        for attempt in range(max_retries):
            try:
                logger.debug(f"🔍 Fetching SOL balance via HTTP RPC (attempt {attempt + 1}/{max_retries})")

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBalance",
                    "params": [address]
                }

                response = requests.post(
                    self.rpc_url,
                    json=payload,
                    timeout=10
                )
                response.raise_for_status()

                result = response.json()

                if 'result' in result and 'value' in result['result']:
                    # Convert lamports to SOL (1 SOL = 1e9 lamports)
                    balance_lamports = result['result']['value']
                    balance_sol = balance_lamports / 1e9
                    logger.debug(f"✅ Fetched SOL balance: {balance_sol:.4f} SOL")
                    return balance_sol
                else:
                    logger.warning(f"⚠️ RPC returned unexpected format (attempt {attempt + 1}/{max_retries})")
                    last_exception = Exception("RPC returned unexpected format")

            except Exception as e:
                last_exception = e
                error_type = type(e).__name__
                error_msg = str(e)

                # Handle specific GetClusterNodes error (shouldn't happen with HTTP, but just in case)
                if "GetClusterNodes" in error_type or "GetClusterNodes" in error_msg:
                    logger.error(f"❌ Solana RPC configuration error (GetClusterNodes): {error_msg}")
                    logger.warning("⚠️ This usually means SOLANA_RPC_URL is misconfigured or RPC endpoint is unavailable")
                    # Don't retry on configuration errors
                    raise Exception(f"Solana RPC configuration error: {error_msg}")

                logger.error(f"❌ Error fetching SOL balance (attempt {attempt + 1}/{max_retries}): {error_type}: {error_msg}")

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

                # CRITICAL: deBridge blockhash is ALWAYS expired by the time we receive it
                # We MUST replace it with a fresh one
                if is_versioned:
                    logger.info(f"🔧 REPLACING expired deBridge blockhash with FRESH blockhash...")

                    # Extract message components from deBridge transaction
                    old_message = transaction.message
                    logger.info(f"   Original blockhash: {str(old_message.recent_blockhash)[:16]}...")

                    # Fetch FRESH blockhash
                    fresh_blockhash_str = await self.get_recent_blockhash()
                    if not fresh_blockhash_str:
                        logger.error("❌ Failed to fetch fresh blockhash!")
                        return None

                    fresh_blockhash = Blockhash.from_string(fresh_blockhash_str)
                    logger.info(f"   ✅ Fresh blockhash: {str(fresh_blockhash)[:16]}... (< 1s old)")

                    # Check for ComputeBudget program
                    COMPUTE_BUDGET_PROGRAM = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
                    has_compute_budget = COMPUTE_BUDGET_PROGRAM in old_message.account_keys

                    priority_fee_price = 0
                    compute_unit_limit = 600000  # Default

                    if has_compute_budget:
                        compute_budget_index = old_message.account_keys.index(COMPUTE_BUDGET_PROGRAM)
                        # Check for compute budget instructions
                        for ix in old_message.instructions:
                            if ix.program_id_index == compute_budget_index:
                                if len(ix.data) > 0:
                                    ix_type = ix.data[0]
                                    if ix_type == 2:
                                        # SetComputeUnitLimit
                                        if len(ix.data) >= 5:
                                            compute_unit_limit = int.from_bytes(ix.data[1:5], 'little')
                                    elif ix_type == 3:
                                        # SetComputeUnitPrice
                                        if len(ix.data) >= 9:
                                            priority_fee_price = int.from_bytes(ix.data[1:9], 'little')

                    # Force aggressive priority fees if too low
                    instructions_to_use = list(old_message.instructions)

                    if priority_fee_price < 10000:
                        logger.info(f"🔧 FORCING AGGRESSIVE PRIORITY FEES (deBridge provided only {priority_fee_price})")

                        # Remove existing ComputeBudget instructions
                        if has_compute_budget:
                            compute_budget_index = old_message.account_keys.index(COMPUTE_BUDGET_PROGRAM)
                            instructions_to_use = [
                                ix for ix in old_message.instructions
                                if ix.program_id_index != compute_budget_index
                            ]

                        # Build NEW aggressive ComputeBudget instructions
                        aggressive_price = 200000  # 200k microlamports/CU

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
                    else:
                        logger.info(f"   ✅ Priority fees OK: {priority_fee_price} microlamports/CU")

                    # Rebuild MessageV0 with FRESH blockhash
                    new_message = MessageV0(
                        header=old_message.header,
                        account_keys=old_message.account_keys,
                        recent_blockhash=fresh_blockhash,
                        instructions=instructions_to_use,
                        address_table_lookups=old_message.address_table_lookups
                    )

                    logger.info(f"   ✅ Rebuilt transaction with fresh blockhash")

                # Sign transaction
                logger.info(f"✍️ Signing with keypair: {str(keypair.pubkey())[:16]}...")

                try:
                    if is_versioned:
                        signed_transaction = VersionedTransaction(new_message, [keypair])
                        logger.info(f"✅ VersionedTransaction signed")
                    else:
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

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getLatestBlockhash",
                "params": [{"commitment": "confirmed"}]
            }

            response = requests.post(self.rpc_url, json=payload, timeout=10)
            response.raise_for_status()

            result = response.json()

            if 'result' in result and 'value' in result['result'] and 'blockhash' in result['result']['value']:
                blockhash = result['result']['value']['blockhash']
                logger.info(f"✅ Got blockhash: {blockhash[:16]}...")
                return blockhash
            else:
                logger.error("❌ Failed to get blockhash")
                return None

        except Exception as e:
            logger.error(f"❌ Error getting recent blockhash: {e}")
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

            # Encode transaction bytes to base64
            tx_base64 = base64.b64encode(signed_transaction).decode('utf-8')
            logger.info("   ⚡ Using skip_preflight=False (shows real errors)")

            for attempt in range(max_retries):
                try:
                    # Send transaction with staggered delays
                    if attempt > 0:
                        delay = min(attempt * 0.5, 3)  # Max 3s delay
                        logger.info(f"   ⏳ Retry {attempt + 1}/{max_retries} (waiting {delay}s)")
                        await asyncio.sleep(delay)

                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "sendTransaction",
                        "params": [
                            tx_base64,
                            {
                                "encoding": "base64",
                                "skipPreflight": False,
                                "preflightCommitment": "confirmed"
                            }
                        ]
                    }

                    response = requests.post(self.rpc_url, json=payload, timeout=30)
                    response.raise_for_status()

                    result = response.json()

                    if 'result' in result and result['result']:
                        signature = result['result']
                        logger.info(f"✅ Transaction sent! Signature: {signature}")
                        logger.info(f"   View on Solscan: https://solscan.io/tx/{signature}")
                        return signature
                    else:
                        # Log the full response to understand the error
                        logger.warning(f"⚠️ Attempt {attempt + 1}/{max_retries} failed (no result)")
                        logger.warning(f"   Response: {result}")
                        if 'error' in result:
                            logger.error(f"   RPC Error: {result['error']}")
                        if attempt < max_retries - 1:
                            continue

                except requests.exceptions.HTTPError as e:
                    logger.warning(f"⚠️ HTTP error on attempt {attempt + 1}/{max_retries}: {e}")
                    try:
                        # Try to get error details from response
                        error_response = e.response.json() if e.response else {}
                        logger.warning(f"   HTTP Error Response: {error_response}")
                        if 'error' in error_response:
                            logger.error(f"   RPC Error: {error_response['error']}")
                    except:
                        logger.warning(f"   Could not parse error response: {e.response.text if e.response else 'No response'}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
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

            start_time = time.time()
            last_status = None

            while time.time() - start_time < timeout:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignatureStatuses",
                    "params": [[signature]]
                }

                response = requests.post(self.rpc_url, json=payload, timeout=10)
                response.raise_for_status()

                result = response.json()

                if 'result' in result and 'value' in result['result'] and len(result['result']['value']) > 0:
                    status = result['result']['value'][0]

                    if status is not None:
                        # Log status changes
                        if status != last_status:
                            logger.info(f"   Status update: {status}")
                            last_status = status

                        # Check if transaction succeeded
                        if status.get('confirmationStatus') is not None:
                            logger.info(f"✅ Transaction confirmed! (status: {status['confirmationStatus']})")
                            logger.info(f"   View on Solscan: https://solscan.io/tx/{signature}")

                            # Check if transaction has error even if confirmed
                            if status.get('err'):
                                logger.error(f"❌ Transaction failed on-chain: {status['err']}")
                                return False

                            # No error = success!
                            return True
                        elif status.get('err'):
                            logger.error(f"❌ Transaction failed on-chain: {status['err']}")
                            return False
                    else:
                        # Transaction not found yet
                        elapsed = int(time.time() - start_time)
                        if elapsed % 10 == 0:  # Log every 10s
                            logger.info(f"   Still waiting... ({elapsed}s elapsed)")

                # Polling every 0.5s
                await asyncio.sleep(0.5)

            logger.error(f"⏰ Confirmation timeout after {timeout}s")
            logger.error(f"   Check manually: https://solscan.io/tx/{signature}")
            return False

        except Exception as e:
            logger.error(f"❌ Error confirming transaction: {e}")
            return False

    async def close(self):
        """No-op for HTTP-based client"""
        pass
