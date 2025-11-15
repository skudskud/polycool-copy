"""
REDEMPTION SERVICE
Handles redemption of resolved positions via CTF Exchange
"""
from typing import Dict, List, Optional
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from web3 import Web3
from eth_utils import keccak
from eth_abi.packed import encode_packed

from core.database.models import ResolvedPosition
from core.database.connection import get_db
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Contract addresses (Polymarket/Polygon)
CONDITIONAL_TOKENS_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
COLLATERAL_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC on Polygon


class RedemptionService:
    """Service to handle position redemption on blockchain"""

    def __init__(self):
        self.polygon_rpc_url = settings.web3.polygon_rpc_url
        logger.info("✅ RedemptionService initialized")

    async def _check_existing_transaction(self, resolved_pos: ResolvedPosition) -> Optional[Dict]:
        """
        Check status of existing redemption transaction if one exists

        Returns:
            Dict with status if transaction found and checked, None otherwise
        """
        if not resolved_pos.redemption_tx_hash:
            return None

        try:
            w3 = Web3(Web3.HTTPProvider(self.polygon_rpc_url))
            tx_hash_hex = resolved_pos.redemption_tx_hash

            logger.info(f"🔍 [REDEMPTION] Checking existing transaction: {tx_hash_hex}")

            # Check if transaction receipt exists
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash_hex)

                if receipt.status == 1:
                    # Transaction succeeded!
                    logger.info(f"✅ [REDEMPTION] Existing transaction succeeded: {tx_hash_hex}")
                    return {
                        'success': True,
                        'tx_hash': tx_hash_hex,
                        'already_completed': True,
                        'receipt': receipt
                    }
                else:
                    # Transaction failed
                    logger.warning(f"⚠️ [REDEMPTION] Existing transaction failed: {tx_hash_hex}")
                    return {
                        'success': False,
                        'tx_hash': tx_hash_hex,
                        'already_failed': True,
                        'error': 'Previous transaction reverted'
                    }
            except Exception:
                # No receipt yet - transaction might be pending
                try:
                    tx = w3.eth.get_transaction(tx_hash_hex)
                    if tx:
                        logger.info(f"⏳ [REDEMPTION] Existing transaction still pending: {tx_hash_hex}")
                        return {
                            'success': False,
                            'tx_hash': tx_hash_hex,
                            'pending': True,
                            'error': f'Transaction pending on blockchain: {tx_hash_hex}'
                        }
                except Exception:
                    # Transaction not found - might have been dropped
                    logger.warning(f"⚠️ [REDEMPTION] Existing transaction not found: {tx_hash_hex}")
                    return None

        except Exception as e:
            logger.error(f"❌ [REDEMPTION] Error checking existing transaction: {e}")
            return None

    async def redeem_position(self, resolved_position_id: int, user_private_key: str) -> Dict:
        """
        Redeem a resolved position via CTF Exchange

        Args:
            resolved_position_id: ID in resolved_positions table
            user_private_key: User's wallet private key (decrypted)

        Returns:
            Dict with redemption status and details
        """
        try:
            async with get_db() as db:
                # Get resolved position
                query = select(ResolvedPosition).where(ResolvedPosition.id == resolved_position_id)
                result = await db.execute(query)
                resolved_pos = result.scalar_one_or_none()

                if not resolved_pos:
                    return {'success': False, 'error': 'Position not found'}

                if resolved_pos.status == 'REDEEMED':
                    return {'success': False, 'error': 'Already redeemed'}

                if not resolved_pos.is_winner:
                    return {'success': False, 'error': 'Cannot redeem losing position'}

                # ✅ CRITICAL: Check if there's an existing transaction in PROCESSING
                if resolved_pos.status == 'PROCESSING' and resolved_pos.redemption_tx_hash:
                    existing_check = await self._check_existing_transaction(resolved_pos)
                    if existing_check:
                        if existing_check.get('already_completed'):
                            # Transaction already succeeded - update status
                            receipt = existing_check['receipt']
                            resolved_pos.status = 'REDEEMED'
                            resolved_pos.redemption_block_number = receipt.blockNumber
                            resolved_pos.redemption_gas_used = receipt.gasUsed
                            resolved_pos.redemption_gas_price = receipt.effectiveGasPrice
                            resolved_pos.redeemed_at = datetime.now(timezone.utc)
                            resolved_pos.last_redemption_error = None
                            await db.commit()
                            await db.refresh(resolved_pos)

                            logger.info(
                                f"✅ [REDEMPTION] Position {resolved_position_id} already redeemed "
                                f"in tx {existing_check['tx_hash']}"
                            )
                            return {
                                'success': True,
                                'tx_hash': existing_check['tx_hash'],
                                'net_value': float(resolved_pos.net_value),
                                'gas_used': receipt.gasUsed,
                                'block_number': receipt.blockNumber,
                                'recovered': True
                            }
                        elif existing_check.get('pending'):
                            # Transaction still pending
                            return {
                                'success': False,
                                'error': existing_check.get('error', 'Transaction pending'),
                                'tx_hash': existing_check['tx_hash']
                            }
                        elif existing_check.get('already_failed'):
                            # Previous transaction failed - allow retry by clearing status
                            logger.info(f"🔄 [REDEMPTION] Previous transaction failed, allowing retry")
                            resolved_pos.status = 'PENDING'
                            resolved_pos.last_redemption_error = existing_check.get('error', 'Previous transaction failed')
                            await db.commit()
                            # Continue to create new transaction below

                # Update status to PROCESSING
                resolved_pos.status = 'PROCESSING'
                resolved_pos.processing_started_at = datetime.now(timezone.utc)
                resolved_pos.redemption_attempt_count = (resolved_pos.redemption_attempt_count or 0) + 1
                await db.commit()

                logger.info(f"🔄 [REDEMPTION] Starting redemption for position {resolved_position_id}")

                # Initialize Web3
                w3 = Web3(Web3.HTTPProvider(self.polygon_rpc_url))

                # ✅ Check POL balance for gas BEFORE attempting transaction
                account = w3.eth.account.from_key(user_private_key)
                pol_balance_wei = w3.eth.get_balance(account.address)
                pol_balance = float(w3.from_wei(pol_balance_wei, 'ether'))

                # Estimate gas cost: 300,000 gas * current gas price
                gas_limit = 300000
                current_gas_price = w3.eth.gas_price
                estimated_gas_cost_wei = gas_limit * current_gas_price
                estimated_gas_cost_pol = float(w3.from_wei(estimated_gas_cost_wei, 'ether'))

                logger.info(
                    f"⛽ [REDEMPTION] POL balance: {pol_balance:.6f} MATIC, "
                    f"estimated gas cost: {estimated_gas_cost_pol:.6f} MATIC"
                )

                # Add 20% buffer for gas price fluctuations
                required_pol = estimated_gas_cost_pol * 1.2

                if pol_balance < required_pol:
                    shortfall = required_pol - pol_balance
                    resolved_pos.status = 'PENDING'
                    resolved_pos.last_redemption_error = (
                        f'Insufficient POL for gas. Balance: {pol_balance:.6f} MATIC, '
                        f'Required: ~{required_pol:.6f} MATIC (need {shortfall:.6f} more). '
                        f'Add POL to your wallet via /bridge or exchange.'
                    )
                    await db.commit()
                    return {
                        'success': False,
                        'error': resolved_pos.last_redemption_error
                    }

                # 🎯 Conditional Tokens ABI for redeemPositions
                CONDITIONAL_TOKENS_ABI = [{
                    "inputs": [
                        {"internalType": "address", "name": "collateralToken", "type": "address"},
                        {"internalType": "bytes32", "name": "parentCollectionId", "type": "bytes32"},
                        {"internalType": "bytes32", "name": "conditionId", "type": "bytes32"},
                        {"internalType": "uint256[]", "name": "indexSets", "type": "uint256[]"}
                    ],
                    "name": "redeemPositions",
                    "outputs": [],
                    "stateMutability": "nonpayable",
                    "type": "function"
                }]

                conditional_tokens = w3.eth.contract(
                    address=w3.to_checksum_address(CONDITIONAL_TOKENS_ADDRESS),
                    abi=CONDITIONAL_TOKENS_ABI
                )

                # ✅ CRITICAL FIX: Check actual token balances to determine which indexSets to redeem
                ERC1155_ABI = [{
                    "inputs": [
                        {"internalType": "address", "name": "account", "type": "address"},
                        {"internalType": "uint256", "name": "id", "type": "uint256"}
                    ],
                    "name": "balanceOf",
                    "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function"
                }]

                conditional_tokens_balance_checker = w3.eth.contract(
                    address=w3.to_checksum_address(CONDITIONAL_TOKENS_ADDRESS),
                    abi=ERC1155_ABI
                )

                # Check balance of the stored position_id first (clob_token_id)
                user_token_id = int(resolved_pos.position_id) if resolved_pos.position_id else 0
                user_token_balance = 0
                if user_token_id > 0:
                    try:
                        user_token_balance = conditional_tokens_balance_checker.functions.balanceOf(
                            account.address, user_token_id
                        ).call()
                        logger.info(
                            f"🔍 [REDEMPTION] Checking stored position_id {resolved_pos.position_id[:20] if resolved_pos.position_id else 'N/A'}... "
                            f"balance: {user_token_balance}"
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ [REDEMPTION] Could not check stored token balance: {e}")

                # Also check both indexSets to see which ones have tokens
                parent_collection_id = b'\x00' * 32
                condition_id_bytes = w3.to_bytes(hexstr=resolved_pos.condition_id)

                balance_1 = 0
                balance_2 = 0
                try:
                    packed_1 = encode_packed(['bytes32', 'bytes32', 'uint256'], [parent_collection_id, condition_id_bytes, 1])
                    packed_2 = encode_packed(['bytes32', 'bytes32', 'uint256'], [parent_collection_id, condition_id_bytes, 2])

                    collection_id_1 = keccak(packed_1)
                    collection_id_2 = keccak(packed_2)

                    token_id_1 = int.from_bytes(collection_id_1, 'big')
                    token_id_2 = int.from_bytes(collection_id_2, 'big')

                    balance_1 = conditional_tokens_balance_checker.functions.balanceOf(account.address, token_id_1).call()
                    balance_2 = conditional_tokens_balance_checker.functions.balanceOf(account.address, token_id_2).call()

                    logger.info(
                        f"🔍 [REDEMPTION] Calculated token balances - indexSet 1 (YES): {balance_1}, "
                        f"indexSet 2 (NO): {balance_2}"
                    )
                except Exception as calc_error:
                    logger.warning(f"⚠️ [REDEMPTION] Could not calculate token IDs from indexSets: {calc_error}")

                # Verify user has tokens for at least one indexSet
                has_tokens = False
                if user_token_balance > 0:
                    has_tokens = True
                    if resolved_pos.outcome == 'YES':
                        logger.info(f"✅ [REDEEM] User has {user_token_balance} YES tokens (indexSet 1)")
                    else:
                        logger.info(f"✅ [REDEEM] User has {user_token_balance} NO tokens (indexSet 2)")
                else:
                    # Check calculated balances
                    if balance_1 > 0 or balance_2 > 0:
                        has_tokens = True
                        if balance_1 > 0:
                            logger.info(f"✅ [REDEEM] User has {balance_1} YES tokens (indexSet 1)")
                        if balance_2 > 0:
                            logger.info(f"✅ [REDEEM] User has {balance_2} NO tokens (indexSet 2)")

                if not has_tokens:
                    error_msg = (
                        f"No redeemable tokens found. Stored token balance: {user_token_balance}, "
                        f"Calculated YES: {balance_1}, NO: {balance_2}. "
                        f"Tokens may have already been redeemed."
                    )
                    logger.error(f"❌ [REDEMPTION] {error_msg}")
                    resolved_pos.status = 'PENDING'
                    resolved_pos.last_redemption_error = error_msg
                    await db.commit()
                    return {'success': False, 'error': error_msg}

                # ✅ FIX: Always use [1, 2] for binary markets (CTF requirement)
                index_sets = [1, 2]
                logger.info(f"✅ [REDEMPTION] Will redeem indexSets: {index_sets} (binary market - CTF requires both)")

                # ✅ CRITICAL: Check if market is actually resolved on-chain before attempting redemption
                CONDITIONAL_TOKENS_FULL_ABI = [{
                    "inputs": [
                        {"internalType": "bytes32", "name": "conditionId", "type": "bytes32"},
                        {"internalType": "uint256", "name": "indexSet", "type": "uint256"}
                    ],
                    "name": "payoutDenominator",
                    "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function"
                }]

                conditional_tokens_full = w3.eth.contract(
                    address=w3.to_checksum_address(CONDITIONAL_TOKENS_ADDRESS),
                    abi=CONDITIONAL_TOKENS_FULL_ABI
                )

                try:
                    # Check if payoutDenominator is set (non-zero means resolved)
                    payout_denom_1 = conditional_tokens_full.functions.payoutDenominator(
                        w3.to_bytes(hexstr=resolved_pos.condition_id),
                        1  # indexSet 1
                    ).call()
                    payout_denom_2 = conditional_tokens_full.functions.payoutDenominator(
                        w3.to_bytes(hexstr=resolved_pos.condition_id),
                        2  # indexSet 2
                    ).call()

                    logger.info(
                        f"🔍 [REDEMPTION] Payout denominators - indexSet 1: {payout_denom_1}, "
                        f"indexSet 2: {payout_denom_2}"
                    )

                    # If payoutDenominator is 0, the market is not resolved on-chain yet
                    if payout_denom_1 == 0 and payout_denom_2 == 0:
                        error_msg = (
                            "Market not yet resolved on-chain. The UMA Oracle needs to call reportPayouts() first. "
                            "This usually happens within 1-2 hours after market expiration. Please try again later."
                        )
                        logger.warning(f"⚠️ [REDEMPTION] {error_msg}")
                        resolved_pos.status = 'PENDING'
                        resolved_pos.last_redemption_error = error_msg
                        await db.commit()
                        return {'success': False, 'error': error_msg}
                except Exception as payout_check_error:
                    logger.warning(f"⚠️ [REDEMPTION] Could not check payoutDenominator: {payout_check_error}")
                    # Continue anyway - might be a contract compatibility issue

                # Build transaction
                txn = conditional_tokens.functions.redeemPositions(
                    w3.to_checksum_address(COLLATERAL_TOKEN_ADDRESS),
                    b'\x00' * 32,  # parentCollectionId (0 for base positions)
                    w3.to_bytes(hexstr=resolved_pos.condition_id),
                    index_sets
                ).build_transaction({
                    'from': account.address,
                    'nonce': w3.eth.get_transaction_count(account.address),
                    'gas': 300000,
                    'gasPrice': w3.eth.gas_price
                })

                # ✅ Pre-flight checks before sending transaction
                try:
                    logger.info(f"🔍 [REDEMPTION] Estimating gas...")
                    estimated_gas = conditional_tokens.functions.redeemPositions(
                        w3.to_checksum_address(COLLATERAL_TOKEN_ADDRESS),
                        b'\x00' * 32,
                        w3.to_bytes(hexstr=resolved_pos.condition_id),
                        index_sets
                    ).estimate_gas({'from': account.address})
                    logger.info(f"✅ [REDEMPTION] Gas estimate: {estimated_gas}")
                except Exception as estimate_error:
                    error_str = str(estimate_error)
                    logger.error(f"❌ [REDEMPTION] Gas estimate failed: {error_str}")

                    # Try to extract meaningful error message
                    if 'no positions' in error_str.lower() or 'already redeemed' in error_str.lower():
                        error_msg = "Tokens already redeemed or no positions found. Check your wallet balance."
                    elif 'not resolved' in error_str.lower() or 'invalid' in error_str.lower() or 'payout' in error_str.lower():
                        error_msg = (
                            "Market not fully resolved on-chain yet. The UMA Oracle needs to call reportPayouts() first. "
                            "This usually happens within 1-2 hours after market expiration. Please try again later."
                        )
                    elif 'execution reverted' in error_str.lower():
                        error_msg = (
                            "Redemption failed - market may not be resolved on-chain yet. "
                            "The UMA Oracle needs to call reportPayouts() first. "
                            "Please wait 1-2 hours after market expiration and try again."
                        )
                    else:
                        error_msg = f"Transaction would fail: {error_str[:200]}"

                    resolved_pos.status = 'PENDING'
                    resolved_pos.last_redemption_error = error_msg
                    await db.commit()
                    return {'success': False, 'error': error_msg}

                # Sign and send transaction
                signed_txn = w3.eth.account.sign_transaction(txn, user_private_key)
                raw_tx = getattr(signed_txn, 'raw_transaction', None) or getattr(signed_txn, 'rawTransaction', None)
                tx_hash = w3.eth.send_raw_transaction(raw_tx)
                tx_hash_hex = tx_hash.hex()

                logger.info(f"✅ [REDEMPTION] Transaction sent: {tx_hash_hex}")

                # ✅ CRITICAL: Save tx_hash immediately so we can track it even if process crashes
                resolved_pos.redemption_tx_hash = tx_hash_hex
                await db.commit()

                # Wait for confirmation with timeout handling
                receipt = None
                try:
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                except Exception as timeout_error:
                    # Timeout or other error - check transaction status manually
                    error_msg = f"Transaction timeout or error waiting for receipt: {str(timeout_error)}"
                    logger.warning(f"⚠️ [REDEMPTION] {error_msg}")

                    # Try to check transaction status manually
                    try:
                        tx = w3.eth.get_transaction(tx_hash_hex)
                        if tx:
                            # Transaction exists, check if it's pending or failed
                            try:
                                receipt = w3.eth.get_transaction_receipt(tx_hash_hex)
                                # If we get here, receipt exists - continue processing below
                                logger.info(f"✅ [REDEMPTION] Found receipt after timeout: {tx_hash_hex}")
                            except Exception:
                                # Transaction is still pending
                                error_msg = (
                                    f"Transaction pending on blockchain: {tx_hash_hex}. "
                                    f"Please check PolygonScan or try again later."
                                )
                                logger.warning(f"⚠️ [REDEMPTION] {error_msg}")
                                resolved_pos.status = 'PENDING'
                                resolved_pos.last_redemption_error = error_msg
                                await db.commit()
                                return {'success': False, 'error': error_msg, 'tx_hash': tx_hash_hex}
                    except Exception as check_error:
                        logger.error(f"❌ [REDEMPTION] Could not check transaction status: {check_error}")
                        error_msg = f"Transaction sent but status unknown. Hash: {tx_hash_hex}. Please check PolygonScan."
                        resolved_pos.status = 'PENDING'
                        resolved_pos.last_redemption_error = error_msg
                        await db.commit()
                        return {'success': False, 'error': error_msg, 'tx_hash': tx_hash_hex}

                if receipt and receipt.status == 1:
                    # Success!
                    resolved_pos.status = 'REDEEMED'
                    resolved_pos.redemption_block_number = receipt.blockNumber
                    resolved_pos.redemption_gas_used = receipt.gasUsed
                    resolved_pos.redemption_gas_price = receipt.effectiveGasPrice
                    resolved_pos.redeemed_at = datetime.now(timezone.utc)
                    resolved_pos.last_redemption_error = None
                    await db.commit()
                    await db.refresh(resolved_pos)

                    logger.info(f"🎉 [REDEMPTION] Success! Position {resolved_position_id} redeemed in tx {tx_hash_hex}")

                    return {
                        'success': True,
                        'tx_hash': tx_hash_hex,
                        'net_value': float(resolved_pos.net_value),
                        'gas_used': receipt.gasUsed,
                        'block_number': receipt.blockNumber
                    }
                elif receipt and receipt.status == 0:
                    # Transaction failed
                    error_msg = "Transaction reverted on-chain"
                    resolved_pos.status = 'PENDING'  # Allow retry
                    resolved_pos.last_redemption_error = error_msg
                    await db.commit()

                    logger.error(f"❌ [REDEMPTION] Transaction failed: {error_msg} (tx: {tx_hash_hex})")
                    return {'success': False, 'error': error_msg, 'tx_hash': tx_hash_hex}

        except Exception as e:
            logger.error(f"❌ [REDEMPTION] Error: {e}", exc_info=True)
            # Try to update status if we have a session
            try:
                async with get_db() as db:
                    query = select(ResolvedPosition).where(ResolvedPosition.id == resolved_position_id)
                    result = await db.execute(query)
                    resolved_pos = result.scalar_one_or_none()
                    if resolved_pos:
                        resolved_pos.status = 'PENDING'
                        resolved_pos.last_redemption_error = str(e)
                        await db.commit()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    async def cleanup_stuck_transactions(self, max_age_minutes: int = 30) -> Dict:
        """
        Clean up redemption transactions stuck in PROCESSING status

        Args:
            max_age_minutes: Maximum age in minutes before considering a transaction stuck

        Returns:
            Dict with cleanup statistics
        """
        try:
            from datetime import timedelta

            async with get_db() as db:
                cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

                # Find stuck transactions
                query = select(ResolvedPosition).where(
                    ResolvedPosition.status == 'PROCESSING',
                    ResolvedPosition.processing_started_at < cutoff_time
                )
                result = await db.execute(query)
                stuck_positions = result.scalars().all()

                stats = {
                    'checked': len(stuck_positions),
                    'recovered': 0,
                    'failed': 0,
                    'pending': 0,
                    'errors': 0
                }

                for pos in stuck_positions:
                    try:
                        if pos.redemption_tx_hash:
                            # Check transaction status
                            existing_check = await self._check_existing_transaction(pos)

                            if existing_check:
                                if existing_check.get('already_completed'):
                                    # Transaction succeeded - recover it
                                    receipt = existing_check['receipt']
                                    pos.status = 'REDEEMED'
                                    pos.redemption_block_number = receipt.blockNumber
                                    pos.redemption_gas_used = receipt.gasUsed
                                    pos.redemption_gas_price = receipt.effectiveGasPrice
                                    pos.redeemed_at = datetime.now(timezone.utc)
                                    pos.last_redemption_error = None
                                    stats['recovered'] += 1
                                    logger.info(f"✅ [CLEANUP] Recovered stuck transaction: {pos.redemption_tx_hash}")
                                elif existing_check.get('already_failed'):
                                    # Transaction failed - mark as PENDING for retry
                                    pos.status = 'PENDING'
                                    pos.last_redemption_error = existing_check.get('error', 'Previous transaction failed')
                                    stats['failed'] += 1
                                    logger.info(f"🔄 [CLEANUP] Marked failed transaction for retry: {pos.redemption_tx_hash}")
                                elif existing_check.get('pending'):
                                    # Still pending - leave it alone
                                    stats['pending'] += 1
                                    logger.info(f"⏳ [CLEANUP] Transaction still pending: {pos.redemption_tx_hash}")
                            else:
                                # Transaction not found - might have been dropped, allow retry
                                pos.status = 'PENDING'
                                pos.last_redemption_error = (
                                    f"Transaction {pos.redemption_tx_hash} not found on blockchain - "
                                    f"may have been dropped"
                                )
                                stats['failed'] += 1
                                logger.warning(
                                    f"⚠️ [CLEANUP] Transaction not found, marked for retry: {pos.redemption_tx_hash}"
                                )
                        else:
                            # No tx_hash but stuck in PROCESSING - likely crashed before sending
                            pos.status = 'PENDING'
                            pos.last_redemption_error = "Transaction never sent - process may have crashed"
                            stats['failed'] += 1
                            logger.warning(f"⚠️ [CLEANUP] No transaction hash found for stuck position {pos.id}")

                        await db.commit()
                    except Exception as e:
                        stats['errors'] += 1
                        logger.error(f"❌ [CLEANUP] Error processing stuck position {pos.id}: {e}")

                logger.info(f"🧹 [CLEANUP] Cleanup complete: {stats}")
                return {'success': True, 'stats': stats}

        except Exception as e:
            logger.error(f"❌ [CLEANUP] Error during cleanup: {e}")
            return {'success': False, 'error': str(e)}

    async def get_pending_redemptions(self, user_id: int) -> List[Dict]:
        """Get all pending redemptions for a user"""
        try:
            async with get_db() as db:
                query = select(ResolvedPosition).where(
                    ResolvedPosition.user_id == user_id,
                    ResolvedPosition.status == 'PENDING',
                    ResolvedPosition.is_winner == True
                ).order_by(ResolvedPosition.resolved_at.desc())
                result = await db.execute(query)
                pending = result.scalars().all()

                return [pos.to_dict() for pos in pending]
        except Exception as e:
            logger.error(f"❌ Error fetching pending redemptions: {e}")
            return []


# Singleton instance
_service = None


def get_redemption_service() -> RedemptionService:
    """Get singleton instance"""
    global _service
    if _service is None:
        _service = RedemptionService()
    return _service
