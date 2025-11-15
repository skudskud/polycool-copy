#!/usr/bin/env python3
"""
Referral Service
Manages 3-tier referral system, commission tracking, and payouts
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from web3 import Web3
from sqlalchemy import text

from core.services import user_service
from database import SessionLocal
from config.config import BOT_USERNAME

logger = logging.getLogger(__name__)

# Configuration
MIN_COMMISSION_PAYOUT = Decimal("1.00")  # $1 minimum
CLAIM_COOLDOWN_HOURS = 24
REFERRAL_LINK_FORMAT = "https://t.me/{bot_username}?start={referrer_code}"

# USDC contract on Polygon (same as fee_service)
USDC_CONTRACT_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }
]


class ReferralService:
    """Service for managing referral relationships and commission payouts"""

    def __init__(self):
        """Initialize referral service with Web3 connection for payouts"""
        import os

        # Web3 setup for commission payouts
        rpc_url = os.getenv('POLYGON_RPC_URL') or "https://polygon-rpc.com"
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.usdc_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(USDC_CONTRACT_ADDRESS),
            abi=USDC_ABI
        )

        # Treasury wallet for payouts
        self.treasury_private_key = os.getenv('TREASURY_PRIVATE_KEY')
        if self.treasury_private_key:
            self.treasury_account = self.w3.eth.account.from_key(self.treasury_private_key)
            logger.info(f"🎁 ReferralService initialized with treasury: {self.treasury_account.address}")
        else:
            logger.warning("⚠️ TREASURY_PRIVATE_KEY not set - commission claims will fail")

    def create_referral(self, referrer_username: str, referred_user_id: int) -> Tuple[bool, str]:
        """
        Create referral relationship with automatic multi-level detection

        Args:
            referrer_username: Telegram username of referrer (without @)
            referred_user_id: Telegram user ID of referred user

        Returns:
            Tuple of (success, message)
        """
        try:
            session = SessionLocal()

            # Find referrer by username
            referrer_id = self._find_user_by_username(referrer_username)

            if not referrer_id:
                logger.warning(f"🔗 REFERRAL: Username @{referrer_username} not found")
                session.close()
                return False, f"Referrer @{referrer_username} not found"

            # Validate not self-referral
            if referrer_id == referred_user_id:
                logger.warning(f"🔗 REFERRAL: User {referred_user_id} tried to self-refer")
                session.close()
                return False, "Cannot refer yourself"

            # Check if user already referred
            check_query = text("""
                SELECT COUNT(*) FROM referrals WHERE referred_user_id = :user_id
            """)
            result = session.execute(check_query, {'user_id': referred_user_id})
            already_referred = result.fetchone()[0] > 0

            if already_referred:
                logger.warning(f"🔗 REFERRAL: User {referred_user_id} already referred")
                session.close()
                return False, "User already has a referrer"

            # Create Level 1 relationship
            level1_query = text("""
                INSERT INTO referrals (referrer_user_id, referred_user_id, level)
                VALUES (:referrer_id, :referred_id, 1)
            """)
            session.execute(level1_query, {
                'referrer_id': referrer_id,
                'referred_id': referred_user_id
            })

            logger.info(f"✅ REFERRAL L1: User {referrer_id} → {referred_user_id}")

            # Find Level 2 (referrer's referrer)
            level2_query = text("""
                WITH ref_level2 AS (
                    SELECT referrer_user_id
                    FROM referrals
                    WHERE referred_user_id = :referrer_id AND level = 1
                )
                INSERT INTO referrals (referrer_user_id, referred_user_id, level)
                SELECT referrer_user_id, :referred_id, 2
                FROM ref_level2
                WHERE referrer_user_id IS NOT NULL
            """)
            result2 = session.execute(level2_query, {
                'referrer_id': referrer_id,
                'referred_id': referred_user_id
            })

            if result2.rowcount > 0:
                logger.info(f"✅ REFERRAL L2: Created level 2 relationship for {referred_user_id}")

            # Find Level 3 (referrer's referrer's referrer)
            level3_query = text("""
                WITH ref_level3 AS (
                    SELECT r2.referrer_user_id
                    FROM referrals r1
                    JOIN referrals r2 ON r1.referrer_user_id = r2.referred_user_id
                    WHERE r1.referred_user_id = :referrer_id
                      AND r1.level = 1
                      AND r2.level = 1
                )
                INSERT INTO referrals (referrer_user_id, referred_user_id, level)
                SELECT referrer_user_id, :referred_id, 3
                FROM ref_level3
                WHERE referrer_user_id IS NOT NULL
            """)
            result3 = session.execute(level3_query, {
                'referrer_id': referrer_id,
                'referred_id': referred_user_id
            })

            if result3.rowcount > 0:
                logger.info(f"✅ REFERRAL L3: Created level 3 relationship for {referred_user_id}")

            session.commit()
            session.close()

            total_levels = 1 + result2.rowcount + result3.rowcount
            logger.info(f"🎉 REFERRAL: User {referred_user_id} linked to {total_levels} referrer(s)")

            return True, f"Referral created successfully ({total_levels} level(s))"

        except Exception as e:
            logger.error(f"❌ REFERRAL ERROR: {e}")
            if 'session' in locals():
                session.rollback()
                session.close()
            return False, f"Error creating referral: {str(e)}"

    def get_user_referral_stats(self, user_id: int) -> Dict:
        """
        Get comprehensive referral statistics for a user

        Args:
            user_id: Telegram user ID

        Returns:
            Dictionary with referral stats, link, and commission breakdown
        """
        try:
            session = SessionLocal()

            # Get user's username for link generation
            user = user_service.get_user(user_id)
            user_username = user.username if user else None

            if not user_username:
                return {
                    'user_username': None,
                    'referral_link': None,
                    'bot_username': BOT_USERNAME,
                    'total_referrals': {'level_1': 0, 'level_2': 0, 'level_3': 0},
                    'total_commissions': {'pending': 0.0, 'paid': 0.0, 'total': 0.0},
                    'commission_breakdown': []
                }

            # Generate referral link
            referral_link = REFERRAL_LINK_FORMAT.format(
                bot_username=BOT_USERNAME,
                referrer_code=user_username
            )

            # Count referrals by level
            referrals_query = text("""
                SELECT level, COUNT(*) as count
                FROM referrals
                WHERE referrer_user_id = :user_id
                GROUP BY level
            """)
            referral_counts = session.execute(referrals_query, {'user_id': user_id}).fetchall()

            total_referrals = {'level_1': 0, 'level_2': 0, 'level_3': 0}
            for level, count in referral_counts:
                total_referrals[f'level_{level}'] = count

            # Calculate commissions by status
            commissions_query = text("""
                SELECT status, SUM(commission_amount) as total
                FROM referral_commissions
                WHERE referrer_user_id = :user_id
                GROUP BY status
            """)
            commission_sums = session.execute(commissions_query, {'user_id': user_id}).fetchall()

            pending = 0.0
            paid = 0.0
            for status, total in commission_sums:
                if status == 'pending':
                    pending = float(total)
                elif status == 'paid':
                    paid = float(total)

            # Commission breakdown by level
            breakdown_query = text("""
                SELECT level, status, SUM(commission_amount) as total
                FROM referral_commissions
                WHERE referrer_user_id = :user_id
                GROUP BY level, status
            """)
            breakdown_data = session.execute(breakdown_query, {'user_id': user_id}).fetchall()

            # Organize breakdown
            breakdown = {1: {'pending': 0.0, 'paid': 0.0},
                        2: {'pending': 0.0, 'paid': 0.0},
                        3: {'pending': 0.0, 'paid': 0.0}}

            for level, status, total in breakdown_data:
                if level in breakdown:
                    breakdown[level][status] = float(total)

            commission_breakdown = [
                {'level': 1, 'rate': 25, 'pending': breakdown[1]['pending'], 'paid': breakdown[1]['paid']},
                {'level': 2, 'rate': 5, 'pending': breakdown[2]['pending'], 'paid': breakdown[2]['paid']},
                {'level': 3, 'rate': 3, 'pending': breakdown[3]['pending'], 'paid': breakdown[3]['paid']}
            ]

            session.close()

            return {
                'user_username': user_username,
                'referral_link': referral_link,
                'bot_username': BOT_USERNAME,
                'total_referrals': total_referrals,
                'total_commissions': {
                    'pending': pending,
                    'paid': paid,
                    'total': pending + paid
                },
                'commission_breakdown': commission_breakdown
            }

        except Exception as e:
            logger.error(f"❌ REFERRAL STATS ERROR: {e}")
            return {
                'user_username': None,
                'referral_link': None,
                'bot_username': BOT_USERNAME,
                'total_referrals': {'level_1': 0, 'level_2': 0, 'level_3': 0},
                'total_commissions': {'pending': 0.0, 'paid': 0.0, 'total': 0.0},
                'commission_breakdown': []
            }

    async def claim_commissions(self, user_id: int) -> Tuple[bool, str, float, Optional[str]]:
        """
        Claim pending commissions and transfer USDC from treasury to user wallet

        Args:
            user_id: Telegram user ID

        Returns:
            Tuple of (success, message, amount_paid, transaction_hash)
        """
        try:
            if not self.treasury_private_key:
                return False, "Treasury wallet not configured", 0.0, None

            session = SessionLocal()

            # Check rate limit
            rate_limited, limit_msg = self._check_claim_rate_limit(user_id)
            if rate_limited:
                session.close()
                return False, limit_msg, 0.0, None

            # Calculate total pending commissions
            pending_query = text("""
                SELECT SUM(commission_amount) as total
                FROM referral_commissions
                WHERE referrer_user_id = :user_id AND status = 'pending'
            """)
            result = session.execute(pending_query, {'user_id': user_id})
            total_pending = result.fetchone()[0]

            if not total_pending or total_pending <= 0:
                session.close()
                return False, "No pending commissions to claim", 0.0, None

            total_pending = Decimal(str(total_pending))

            # Check minimum
            if total_pending < MIN_COMMISSION_PAYOUT:
                session.close()
                return False, f"Minimum payout is ${MIN_COMMISSION_PAYOUT}. You have ${total_pending:.2f}", 0.0, None

            # Get user's wallet
            user = user_service.get_user(user_id)
            if not user:
                session.close()
                return False, "User not found", 0.0, None

            recipient_address = user.polygon_address

            logger.info(f"💰 CLAIM: Processing ${total_pending} payout to user {user_id}")

            # Convert to USDC units (6 decimals)
            amount_in_usdc_units = int(float(total_pending) * 1_000_000)

            # Build transfer transaction from treasury
            treasury_address = self.treasury_account.address
            nonce = self.w3.eth.get_transaction_count(Web3.to_checksum_address(treasury_address))

            tx = self.usdc_contract.functions.transfer(
                Web3.to_checksum_address(recipient_address),
                amount_in_usdc_units
            ).build_transaction({
                'from': Web3.to_checksum_address(treasury_address),
                'gas': 100000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': nonce,
                'chainId': 137  # Polygon mainnet
            })

            # Sign with treasury private key
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.treasury_private_key)

            # Send transaction (handle both web3.py versions)
            raw_tx = getattr(signed_tx, 'raw_transaction', None) or getattr(signed_tx, 'rawTransaction', None)
            tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
            tx_hash_hex = tx_hash.hex()

            logger.info(f"💸 CLAIM: Payout transaction sent: {tx_hash_hex}")

            # Wait for confirmation
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            if receipt['status'] == 1:
                # Mark all pending commissions as paid
                update_query = text("""
                    UPDATE referral_commissions
                    SET status = 'paid',
                        paid_at = NOW(),
                        payment_transaction_hash = :tx_hash
                    WHERE referrer_user_id = :user_id AND status = 'pending'
                """)
                session.execute(update_query, {
                    'user_id': user_id,
                    'tx_hash': tx_hash_hex
                })
                session.commit()
                session.close()

                logger.info(f"✅ CLAIM SUCCESS: Paid ${total_pending} to user {user_id}")
                return True, "Commission claimed successfully", float(total_pending), tx_hash_hex
            else:
                session.close()
                logger.error(f"❌ CLAIM FAILED: Transaction reverted")
                return False, "Payout transaction failed", 0.0, None

        except Exception as e:
            logger.error(f"❌ CLAIM ERROR: {e}")
            if 'session' in locals():
                session.close()
            return False, f"Claim error: {str(e)}", 0.0, None

    def _find_user_by_username(self, username: str) -> Optional[int]:
        """Find user ID by Telegram username"""
        try:
            # Remove @ if present
            username = username.lstrip('@').lower()

            session = SessionLocal()
            query = text("""
                SELECT telegram_user_id
                FROM users
                WHERE LOWER(username) = :username
            """)
            result = session.execute(query, {'username': username})
            row = result.fetchone()
            session.close()

            if row:
                return row[0]
            return None

        except Exception as e:
            logger.error(f"❌ REFERRAL: Error finding user by username: {e}")
            return None

    def _check_claim_rate_limit(self, user_id: int) -> Tuple[bool, str]:
        """Check if user can claim (24h cooldown)"""
        try:
            session = SessionLocal()

            # Find last claim time
            query = text("""
                SELECT MAX(paid_at) as last_claim
                FROM referral_commissions
                WHERE referrer_user_id = :user_id AND status = 'paid'
            """)
            result = session.execute(query, {'user_id': user_id})
            last_claim = result.fetchone()[0]
            session.close()

            if last_claim:
                time_since_claim = datetime.utcnow() - last_claim
                if time_since_claim < timedelta(hours=CLAIM_COOLDOWN_HOURS):
                    hours_remaining = CLAIM_COOLDOWN_HOURS - (time_since_claim.total_seconds() / 3600)
                    return True, f"Please wait {hours_remaining:.1f} hours before next claim"

            return False, ""

        except Exception as e:
            logger.error(f"❌ REFERRAL: Rate limit check error: {e}")
            return False, ""


# Singleton instance
_referral_service_instance = None

def get_referral_service() -> ReferralService:
    """Get singleton ReferralService instance"""
    global _referral_service_instance
    if _referral_service_instance is None:
        _referral_service_instance = ReferralService()
    return _referral_service_instance
