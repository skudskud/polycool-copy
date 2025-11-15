"""
REDEMPTION SERVICE
Handles redemption of resolved positions via CTF Exchange
"""

import logging
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from database import SessionLocal, ResolvedPosition
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

logger = logging.getLogger(__name__)


class RedemptionService:
    """Service to handle position redemption on blockchain"""

    def __init__(self):
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
            from config.config import POLYGON_RPC_URL
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
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
            user_private_key: User's wallet private key

        Returns:
            Dict with redemption status and details
        """
        try:
            with SessionLocal() as session:
                # Get resolved position
                resolved_pos = session.query(ResolvedPosition).filter(
                    ResolvedPosition.id == resolved_position_id
                ).first()

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
                            resolved_pos.redeemed_at = datetime.utcnow()
                            resolved_pos.last_redemption_error = None
                            session.commit()

                            logger.info(f"✅ [REDEMPTION] Position {resolved_position_id} already redeemed in tx {existing_check['tx_hash']}")
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
                            session.commit()
                            # Continue to create new transaction below

                # Update status to PROCESSING
                resolved_pos.status = 'PROCESSING'
                resolved_pos.processing_started_at = datetime.utcnow()
                resolved_pos.redemption_attempt_count = (resolved_pos.redemption_attempt_count or 0) + 1
                session.commit()

                logger.info(f"🔄 [REDEMPTION] Starting redemption for position {resolved_position_id}")

                # Initialize CLOB client with user's key
                from config.config import (
                    POLYMARKET_HOST, CLOB_API_URL, POLYGON_RPC_URL,
                    CTF_EXCHANGE_ADDRESS, COLLATERAL_TOKEN_ADDRESS, NEG_RISK_CTF_EXCHANGE_ADDRESS
                )

                client = ClobClient(
                    host=POLYMARKET_HOST,
                    key=user_private_key,
                    chain_id=137,  # Polygon mainnet
                    creds=ApiCreds(
                        api_key="",
                        api_secret="",
                        api_passphrase=""
                    )
                )

                # 🎯 CRITICAL FIX: Call Conditional Tokens directly like successful competitor
                # Instead of CTF Exchange, call Conditional Tokens contract directly
                # This is what the competitor does and it works!
                logger.info(f"📞 [REDEMPTION] Calling Conditional Tokens directly (like competitor) for condition_id: {resolved_pos.condition_id}")
                logger.info(f"🎯 [REDEMPTION] Using same approach as successful tx: 0x360198d0964a7c6b0bc4130b95fd435f2a4aedc4b1d9ce8787beacaf6f46d272")

                try:
                    # Get Conditional Tokens contract (like competitor does)
                    from web3 import Web3

                    # Initialize Web3 (web3.py v6+ handles Polygon PoA automatically, no middleware needed)
                    w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))

                    # ✅ Check POL balance for gas BEFORE attempting transaction
                    account = w3.eth.account.from_key(user_private_key)
                    pol_balance_wei = w3.eth.get_balance(account.address)
                    pol_balance = float(w3.from_wei(pol_balance_wei, 'ether'))  # Convert to float

                    # Estimate gas cost: 300,000 gas * current gas price
                    gas_limit = 300000
                    current_gas_price = w3.eth.gas_price
                    estimated_gas_cost_wei = gas_limit * current_gas_price
                    estimated_gas_cost_pol = float(w3.from_wei(estimated_gas_cost_wei, 'ether'))  # Convert to float

                    logger.info(f"⛽ [REDEMPTION] POL balance: {pol_balance:.6f} MATIC, estimated gas cost: {estimated_gas_cost_pol:.6f} MATIC")

                    # Add 20% buffer for gas price fluctuations
                    required_pol = estimated_gas_cost_pol * 1.2  # Now both are float, so this works

                    if pol_balance < required_pol:
                        shortfall = required_pol - pol_balance
                        return {
                            'success': False,
                            'error': f'Insufficient POL for gas. Balance: {pol_balance:.6f} MATIC, Required: ~{required_pol:.6f} MATIC (need {shortfall:.6f} more). Add POL to your wallet via /bridge or exchange.'
                        }

                    # 🎯 Conditional Tokens ABI for redeemPositions (like competitor)
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

                    # 🎯 Use Conditional Tokens contract directly (like competitor)
                    CONDITIONAL_TOKENS_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
                    conditional_tokens = w3.eth.contract(
                        address=w3.to_checksum_address(CONDITIONAL_TOKENS_ADDRESS),
                        abi=CONDITIONAL_TOKENS_ABI
                    )

                    # Prepare redemption transaction
                    account = w3.eth.account.from_key(user_private_key)

                    # ✅ CRITICAL FIX: Check actual token balances to determine which indexSets to redeem
                    # We should only redeem indexSets for which the user actually has tokens
                    # Conditional Tokens contract (ERC1155)
                    # Use separate variable to avoid overwriting the redemption contract
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

                    # 🔧 FIX: Use separate variable for balance checks to not overwrite redemption contract
                    conditional_tokens_balance_checker = w3.eth.contract(
                        address=w3.to_checksum_address(CONDITIONAL_TOKENS_ADDRESS),
                        abi=ERC1155_ABI
                    )

                    # Check balance of the stored token_id first (most reliable - this is the actual token ID from the position)
                    user_token_id = int(resolved_pos.token_id)
                    user_token_balance = conditional_tokens_balance_checker.functions.balanceOf(account.address, user_token_id).call()

                    logger.info(f"🔍 [REDEMPTION] Checking stored token_id {resolved_pos.token_id[:20]}... balance: {user_token_balance}")

                    # Also check both indexSets to see which ones have tokens
                    # Calculate token IDs using getCollectionId logic: keccak256(abi.encodePacked(parentCollectionId, conditionId, indexSet))
                    from eth_utils import keccak
                    from eth_abi.packed import encode_packed

                    parent_collection_id = b'\x00' * 32
                    condition_id_bytes = w3.to_bytes(hexstr=resolved_pos.condition_id)

                    # Calculate collection IDs for each indexSet (as per CTF spec: keccak256(abi.encodePacked(...)))
                    # encodePacked: bytes32, bytes32, uint256
                    try:
                        packed_1 = encode_packed(['bytes32', 'bytes32', 'uint256'], [parent_collection_id, condition_id_bytes, 1])
                        packed_2 = encode_packed(['bytes32', 'bytes32', 'uint256'], [parent_collection_id, condition_id_bytes, 2])

                        collection_id_1 = keccak(packed_1)
                        collection_id_2 = keccak(packed_2)

                        token_id_1 = int.from_bytes(collection_id_1, 'big')
                        token_id_2 = int.from_bytes(collection_id_2, 'big')

                        balance_1 = conditional_tokens_balance_checker.functions.balanceOf(account.address, token_id_1).call()
                        balance_2 = conditional_tokens_balance_checker.functions.balanceOf(account.address, token_id_2).call()

                        logger.info(f"🔍 [REDEMPTION] Calculated token balances - indexSet 1 (YES): {balance_1}, indexSet 2 (NO): {balance_2}")
                    except Exception as calc_error:
                        logger.warning(f"⚠️ [REDEMPTION] Could not calculate token IDs from indexSets: {calc_error}")
                        balance_1 = 0
                        balance_2 = 0

                    logger.info(f"🔍 [REDEMPTION] Stored token_id balance: {user_token_balance}")

                    # ✅ CRITICAL FIX: For binary markets, CTF Exchange requires redeeming BOTH indexSets [1, 2]
                    # even if user only has tokens for one. This is a requirement of the Conditional Token Framework.
                    # The contract checks that the partition is complete (all outcomes are redeemed).
                    #
                    # Only redeem indexSets where user has tokens, but for binary markets always include both.
                    # For multi-outcome markets (>2 outcomes), we'd need to determine all indexSets dynamically.

                    # Build indexSets list - for binary markets, always use [1, 2]
                    # Verify user has tokens for at least one indexSet before proceeding
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
                        error_msg = f"No redeemable tokens found. Stored token balance: {user_token_balance}, Calculated YES: {balance_1}, NO: {balance_2}. Tokens may have already been redeemed."
                        logger.error(f"❌ [REDEMPTION] {error_msg}")
                        resolved_pos.status = 'PENDING'
                        resolved_pos.last_redemption_error = error_msg
                        session.commit()
                        return {'success': False, 'error': error_msg}

                    # ✅ FIX: Always use [1, 2] for binary markets (CTF requirement)
                    # The contract will only redeem tokens the user actually has (balance > 0)
                    # But it requires the complete partition to be specified
                    index_sets = [1, 2]
                    logger.info(f"✅ [REDEMPTION] Will redeem indexSets: {index_sets} (binary market - CTF requires both)")

                    # ✅ CRITICAL: Check if market is actually resolved on-chain before attempting redemption
                    # The CTF Exchange requires reportPayouts() to be called by UMA Oracle first
                    # We can check this by calling the Conditional Tokens contract's payoutDenominator function
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

                        logger.info(f"🔍 [REDEMPTION] Payout denominators - indexSet 1: {payout_denom_1}, indexSet 2: {payout_denom_2}")

                        # If payoutDenominator is 0, the market is not resolved on-chain yet
                        if payout_denom_1 == 0 and payout_denom_2 == 0:
                            error_msg = "Market not yet resolved on-chain. The UMA Oracle needs to call reportPayouts() first. This usually happens within 1-2 hours after market expiration. Please try again later."
                            logger.warning(f"⚠️ [REDEMPTION] {error_msg}")
                            resolved_pos.status = 'PENDING'
                            resolved_pos.last_redemption_error = error_msg
                            session.commit()
                            return {'success': False, 'error': error_msg}
                    except Exception as payout_check_error:
                        logger.warning(f"⚠️ [REDEMPTION] Could not check payoutDenominator: {payout_check_error}")
                        # Continue anyway - might be a contract compatibility issue

                    # Build transaction
                    txn = conditional_tokens.functions.redeemPositions(
                        w3.to_checksum_address(COLLATERAL_TOKEN_ADDRESS),  # USDC (web3.py v6+)
                        b'\x00' * 32,  # parentCollectionId (0 for base positions)
                        w3.to_bytes(hexstr=resolved_pos.condition_id),  # web3.py v6+
                        index_sets
                    ).build_transaction({
                        'from': account.address,
                        'nonce': w3.eth.get_transaction_count(account.address),
                        'gas': 300000,
                        'gasPrice': w3.eth.gas_price
                    })

                    # ✅ Pre-flight checks before sending transaction
                    # Check 1: Estimate gas to see if transaction would fail
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
                            error_msg = "Market not fully resolved on-chain yet. The UMA Oracle needs to call reportPayouts() first. This usually happens within 1-2 hours after market expiration. Please try again later."
                        elif 'execution reverted' in error_str.lower():
                            error_msg = "Redemption failed - market may not be resolved on-chain yet. The UMA Oracle needs to call reportPayouts() first. Please wait 1-2 hours after market expiration and try again."
                        else:
                            error_msg = f"Transaction would fail: {error_str[:200]}"

                        resolved_pos.status = 'PENDING'
                        resolved_pos.last_redemption_error = error_msg
                        session.commit()
                        return {'success': False, 'error': error_msg}

                    # Sign and send transaction
                    signed_txn = w3.eth.account.sign_transaction(txn, user_private_key)
                    # web3.py v6+ uses 'raw_transaction' instead of 'rawTransaction'
                    raw_tx = getattr(signed_txn, 'raw_transaction', None) or getattr(signed_txn, 'rawTransaction', None)
                    tx_hash = w3.eth.send_raw_transaction(raw_tx)
                    tx_hash_hex = tx_hash.hex()

                    logger.info(f"✅ [REDEMPTION] Transaction sent: {tx_hash_hex}")

                    # ✅ CRITICAL: Save tx_hash immediately so we can track it even if process crashes
                    resolved_pos.redemption_tx_hash = tx_hash_hex
                    session.commit()

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
                                    error_msg = f"Transaction pending on blockchain: {tx_hash_hex}. Please check PolygonScan or try again later."
                                    logger.warning(f"⚠️ [REDEMPTION] {error_msg}")
                                    resolved_pos.status = 'PENDING'
                                    resolved_pos.last_redemption_error = error_msg
                                    session.commit()
                                    return {'success': False, 'error': error_msg, 'tx_hash': tx_hash_hex}
                        except Exception as check_error:
                            logger.error(f"❌ [REDEMPTION] Could not check transaction status: {check_error}")
                            error_msg = f"Transaction sent but status unknown. Hash: {tx_hash_hex}. Please check PolygonScan."
                            resolved_pos.status = 'PENDING'
                            resolved_pos.last_redemption_error = error_msg
                            session.commit()
                            return {'success': False, 'error': error_msg, 'tx_hash': tx_hash_hex}

                    if receipt and receipt.status == 1:
                        # Success!
                        resolved_pos.status = 'REDEEMED'
                        resolved_pos.redemption_block_number = receipt.blockNumber
                        resolved_pos.redemption_gas_used = receipt.gasUsed
                        resolved_pos.redemption_gas_price = receipt.effectiveGasPrice
                        resolved_pos.redeemed_at = datetime.utcnow()
                        resolved_pos.last_redemption_error = None
                        session.commit()

                        logger.info(f"🎉 [REDEMPTION] Success! Position {resolved_position_id} redeemed in tx {tx_hash_hex}")

                        return {
                            'success': True,
                            'tx_hash': tx_hash_hex,
                            'net_value': float(resolved_pos.net_value),
                            'gas_used': receipt.gasUsed,
                            'block_number': receipt.blockNumber
                        }
                    elif receipt and receipt.status == 0:
                        # Transaction failed - try to decode revert reason
                        error_msg = "Transaction reverted on-chain"

                        # Try to decode revert reason from transaction
                        try:
                            # Get the failed transaction
                            tx = w3.eth.get_transaction(tx_hash_hex)
                            # Try to call the function to get revert reason
                            try:
                                conditional_tokens.functions.redeemPositions(
                                    w3.to_checksum_address(COLLATERAL_TOKEN_ADDRESS),
                                    b'\x00' * 32,
                                    w3.to_bytes(hexstr=resolved_pos.condition_id),
                                    index_sets
                                ).call({'from': account.address})
                            except Exception as call_error:
                                call_error_str = str(call_error)
                                if 'no positions' in call_error_str.lower() or 'already redeemed' in call_error_str.lower():
                                    error_msg = "Tokens already redeemed. Check your wallet balance."
                                elif 'not resolved' in call_error_str.lower() or 'payout' in call_error_str.lower():
                                    error_msg = "Market not fully resolved on-chain yet. The UMA Oracle needs to call reportPayouts() first. Wait 1-2 hours after market expiration and try again."
                                elif 'invalid' in call_error_str.lower():
                                    error_msg = "Invalid redemption parameters. Market may not be ready."
                                else:
                                    error_msg = f"Redemption failed: {call_error_str[:150]}"
                        except Exception as decode_error:
                            logger.debug(f"Could not decode revert reason: {decode_error}")
                            # Keep default error_msg

                        # ✅ CRITICAL: Save tx_hash even on failure for tracking
                        resolved_pos.status = 'PENDING'  # Allow retry
                        resolved_pos.last_redemption_error = error_msg
                        # tx_hash already saved above
                        session.commit()

                        logger.error(f"❌ [REDEMPTION] Transaction failed: {error_msg} (tx: {tx_hash_hex})")
                        return {'success': False, 'error': error_msg, 'tx_hash': tx_hash_hex}

                except Exception as blockchain_error:
                    error_msg = str(blockchain_error)
                    logger.error(f"❌ [REDEMPTION] Blockchain error: {error_msg}")

                    # Update status back to PENDING
                    resolved_pos.status = 'PENDING'
                    resolved_pos.last_redemption_error = error_msg
                    session.commit()

                    return {'success': False, 'error': error_msg}

        except Exception as e:
            logger.error(f"❌ [REDEMPTION] Error: {e}")
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

            with SessionLocal() as session:
                cutoff_time = datetime.utcnow() - timedelta(minutes=max_age_minutes)

                # Find stuck transactions
                stuck_positions = session.query(ResolvedPosition).filter(
                    ResolvedPosition.status == 'PROCESSING',
                    ResolvedPosition.processing_started_at < cutoff_time
                ).all()

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
                                    pos.redeemed_at = datetime.utcnow()
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
                                pos.last_redemption_error = f"Transaction {pos.redemption_tx_hash} not found on blockchain - may have been dropped"
                                stats['failed'] += 1
                                logger.warning(f"⚠️ [CLEANUP] Transaction not found, marked for retry: {pos.redemption_tx_hash}")
                        else:
                            # No tx_hash but stuck in PROCESSING - likely crashed before sending
                            pos.status = 'PENDING'
                            pos.last_redemption_error = "Transaction never sent - process may have crashed"
                            stats['failed'] += 1
                            logger.warning(f"⚠️ [CLEANUP] No transaction hash found for stuck position {pos.id}")

                        session.commit()
                    except Exception as e:
                        stats['errors'] += 1
                        logger.error(f"❌ [CLEANUP] Error processing stuck position {pos.id}: {e}")

                logger.info(f"🧹 [CLEANUP] Cleanup complete: {stats}")
                return {'success': True, 'stats': stats}

        except Exception as e:
            logger.error(f"❌ [CLEANUP] Error during cleanup: {e}")
            return {'success': False, 'error': str(e)}

    def get_pending_redemptions(self, user_id: int) -> List[Dict]:
        """Get all pending redemptions for a user"""
        try:
            with SessionLocal() as session:
                pending = session.query(ResolvedPosition).filter(
                    ResolvedPosition.user_id == user_id,
                    ResolvedPosition.status == 'PENDING',
                    ResolvedPosition.is_winner == True
                ).order_by(ResolvedPosition.resolved_at.desc()).all()

                return [pos.to_dict() for pos in pending]
        except Exception as e:
            logger.error(f"❌ Error fetching pending redemptions: {e}")
            return []


_service = None

def get_redemption_service():
    global _service
    if _service is None:
        _service = RedemptionService()
    return _service
