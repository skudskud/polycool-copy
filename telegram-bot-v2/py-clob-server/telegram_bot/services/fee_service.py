#!/usr/bin/env python3
"""
Fee Service
Handles fee calculation, collection, and referral commission distribution
"""

import logging
from decimal import Decimal
from typing import Dict, Optional, Tuple, List
from web3 import Web3
from datetime import datetime

from core.services import user_service
from database import SessionLocal

logger = logging.getLogger(__name__)

# Configuration
TREASURY_WALLET = "0xaEF1Da195Dd057c9252A6C03081B70f38453038c"
BASE_FEE_PERCENTAGE = Decimal("1.00")  # 1%
MINIMUM_FEE_USD = Decimal("0.10")  # $0.10 minimum

# Referral commission rates
LEVEL_1_COMMISSION = Decimal("25.00")  # 25% of fee
LEVEL_2_COMMISSION = Decimal("5.00")   # 5% of fee
LEVEL_3_COMMISSION = Decimal("3.00")   # 3% of fee

# USDC contract on Polygon
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


class FeeService:
    """Service for managing trading fees and referral commissions"""

    def __init__(self):
        """Initialize fee service with Web3 connection"""
        import os

        # Priority: POLYGON_RPC_URL from env > public RPC > Alchemy demo
        rpc_url = os.getenv('POLYGON_RPC_URL') or "https://polygon-rpc.com"

        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.usdc_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(USDC_CONTRACT_ADDRESS),
            abi=USDC_ABI
        )

        logger.info(f"💰 FeeService initialized with treasury: {TREASURY_WALLET}")

    def calculate_fee(self, user_id: int, trade_amount: float) -> Dict:
        """
        Calculate fee with referral discounts applied

        Args:
            user_id: Telegram user ID
            trade_amount: Trade amount in USD

        Returns:
            Dictionary with fee details:
            {
                'fee_amount': Decimal,
                'fee_percentage': Decimal,
                'minimum_applied': bool,
                'trade_amount_after_fee': Decimal,
                'referral_chain': List[Dict],
                'total_user_cost': Decimal
            }
        """
        try:
            trade_amount_decimal = Decimal(str(trade_amount))

            # PHASE 1: Fixed 1% for all users (testing phase)
            fee_percentage = BASE_FEE_PERCENTAGE

            # Calculate raw fee
            raw_fee = trade_amount_decimal * (fee_percentage / Decimal("100"))

            # Apply minimum
            minimum_applied = False
            if raw_fee < MINIMUM_FEE_USD:
                fee_amount = MINIMUM_FEE_USD
                minimum_applied = True
                logger.info(f"💰 FEE CALC: Minimum fee applied for user {user_id}: ${fee_amount} (raw: ${raw_fee})")
            else:
                fee_amount = raw_fee

            # Get referral chain for commission calculation
            referral_chain = self._get_referral_chain(user_id)

            # Calculate amount that goes to actual trade
            # NOTE: For now, user pays FULL amount and fee is collected separately
            trade_amount_after_fee = trade_amount_decimal

            logger.info(
                f"💰 FEE CALC: User {user_id} - "
                f"Trade=${trade_amount_decimal}, Fee=${fee_amount} ({fee_percentage}%), "
                f"Minimum={minimum_applied}, Referrers={len(referral_chain)}"
            )

            return {
                'fee_amount': fee_amount,
                'fee_percentage': fee_percentage,
                'minimum_applied': minimum_applied,
                'trade_amount_after_fee': trade_amount_after_fee,
                'referral_chain': referral_chain,
                'total_user_cost': trade_amount_decimal
            }

        except Exception as e:
            logger.error(f"❌ FEE FAILED: Error calculating fee: {e}")
            # Fallback: no fee if calculation fails
            return {
                'fee_amount': Decimal("0"),
                'fee_percentage': Decimal("0"),
                'minimum_applied': False,
                'trade_amount_after_fee': Decimal(str(trade_amount)),
                'referral_chain': [],
                'total_user_cost': Decimal(str(trade_amount))
            }

    def _get_referral_chain(self, user_id: int) -> List[Dict]:
        """
        Get the referral chain for commission distribution
        Returns list of referrers with their level and commission rate
        """
        try:
            session = SessionLocal()

            # Query to find all referrers in the chain (up to 3 levels)
            from sqlalchemy import text
            query = text("""
                WITH RECURSIVE referral_tree AS (
                    -- Base case: direct referrer (Level 1)
                    SELECT
                        referrer_user_id,
                        referred_user_id,
                        1 as level
                    FROM referrals
                    WHERE referred_user_id = :user_id

                    UNION ALL

                    -- Recursive case: referrers of referrers (Level 2, 3)
                    SELECT
                        r.referrer_user_id,
                        r.referred_user_id,
                        rt.level + 1
                    FROM referrals r
                    INNER JOIN referral_tree rt ON r.referred_user_id = rt.referrer_user_id
                    WHERE rt.level < 3  -- Max 3 levels
                )
                SELECT
                    referrer_user_id,
                    level
                FROM referral_tree
                ORDER BY level ASC;
            """)

            result = session.execute(query, {'user_id': user_id})
            rows = result.fetchall()
            session.close()

            # Build referral chain with commission rates
            chain = []
            for row in rows:
                referrer_id = row[0]
                level = row[1]

                if level == 1:
                    commission_rate = LEVEL_1_COMMISSION
                elif level == 2:
                    commission_rate = LEVEL_2_COMMISSION
                elif level == 3:
                    commission_rate = LEVEL_3_COMMISSION
                else:
                    continue

                chain.append({
                    'referrer_user_id': referrer_id,
                    'level': level,
                    'commission_percentage': commission_rate
                })

            return chain

        except Exception as e:
            logger.error(f"❌ FEE FAILED: Error getting referral chain: {e}")
            return []

    async def collect_fee(
        self,
        user_id: int,
        trade_amount: float,
        transaction_id: Optional[int] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Collect fee from user and transfer to treasury wallet

        Args:
            user_id: Telegram user ID
            trade_amount: Trade amount in USD
            transaction_id: Optional transaction ID to link fee

        Returns:
            Tuple of (success, message, fee_transaction_hash)
        """
        try:
            # Calculate fee
            fee_calc = self.calculate_fee(user_id, trade_amount)
            fee_amount = float(fee_calc['fee_amount'])

            logger.info(f"💸 FEE COLLECT: Starting collection of ${fee_amount} from user {user_id}")

            # Get user's wallet
            user = user_service.get_user(user_id)
            if not user:
                logger.error(f"❌ FEE FAILED: User {user_id} not found")
                return False, "User not found", None

            private_key = user.polygon_private_key
            from_address = user.polygon_address

            # Convert fee to USDC smallest unit (6 decimals)
            fee_in_usdc_units = int(fee_amount * 1_000_000)

            logger.info(f"💸 FEE COLLECT: Building transaction for {fee_in_usdc_units} USDC units")

            # Build transaction
            nonce = self.w3.eth.get_transaction_count(Web3.to_checksum_address(from_address))

            # Build transfer transaction
            tx = self.usdc_contract.functions.transfer(
                Web3.to_checksum_address(TREASURY_WALLET),
                fee_in_usdc_units
            ).build_transaction({
                'from': Web3.to_checksum_address(from_address),
                'gas': 100000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': nonce,
                'chainId': 137  # Polygon mainnet
            })

            # Sign transaction
            signed_tx = self.w3.eth.account.sign_transaction(tx, private_key)

            # Send transaction (handle both old and new web3.py versions)
            raw_tx = getattr(signed_tx, 'raw_transaction', None) or getattr(signed_tx, 'rawTransaction', None)
            tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
            tx_hash_hex = tx_hash.hex()

            logger.info(f"💸 FEE COLLECT: Transaction sent: {tx_hash_hex}")

            # Wait for confirmation (max 30 seconds)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            if receipt['status'] == 1:
                # Log fee to database
                fee_id = self._log_fee_to_db(
                    user_id=user_id,
                    transaction_id=transaction_id,
                    fee_calc=fee_calc,
                    fee_transaction_hash=tx_hash_hex
                )

                # Distribute referral commissions
                await self._distribute_commissions(fee_id, fee_calc, user_id)

                logger.info(f"✅ FEE SUCCESS: Collected ${fee_amount} from user {user_id}")
                return True, f"Fee collected: ${fee_amount}", tx_hash_hex
            else:
                logger.error(f"❌ FEE FAILED: Transaction reverted for user {user_id}")
                return False, "Fee transaction reverted", None

        except Exception as e:
            logger.error(f"❌ FEE FAILED: Error collecting fee from user {user_id}: {e}")
            return False, f"Fee collection error: {str(e)}", None

    def _log_fee_to_db(
        self,
        user_id: int,
        transaction_id: Optional[int],
        fee_calc: Dict,
        fee_transaction_hash: str
    ) -> Optional[int]:
        """Log fee collection to database"""
        try:
            session = SessionLocal()
            from sqlalchemy import text

            query = text("""
                INSERT INTO fees (
                    user_id,
                    transaction_id,
                    trade_amount,
                    fee_percentage,
                    fee_amount,
                    minimum_fee_applied,
                    fee_transaction_hash,
                    status,
                    collected_at
                ) VALUES (
                    :user_id,
                    :transaction_id,
                    :trade_amount,
                    :fee_percentage,
                    :fee_amount,
                    :minimum_applied,
                    :tx_hash,
                    'collected',
                    NOW()
                )
                RETURNING id;
            """)

            result = session.execute(query, {
                'user_id': user_id,
                'transaction_id': transaction_id,
                'trade_amount': str(fee_calc['total_user_cost']),
                'fee_percentage': str(fee_calc['fee_percentage']),
                'fee_amount': str(fee_calc['fee_amount']),
                'minimum_applied': fee_calc['minimum_applied'],
                'tx_hash': fee_transaction_hash
            })

            fee_id = result.fetchone()[0]
            session.commit()
            session.close()

            logger.info(f"✅ FEE SUCCESS: Logged to database with fee_id={fee_id}")
            return fee_id

        except Exception as e:
            logger.error(f"❌ FEE FAILED: Error logging fee to DB: {e}")
            return None

    async def _distribute_commissions(self, fee_id: Optional[int], fee_calc: Dict, user_id: int):
        """
        Calculate and log referral commissions (payment happens separately)
        """
        try:
            if not fee_id:
                logger.warning("⚠️ FEE: No fee_id provided, skipping commission distribution")
                return

            if not fee_calc['referral_chain']:
                logger.info(f"💰 FEE CALC: No referrers for user {user_id}")
                return

            session = SessionLocal()
            from sqlalchemy import text

            fee_amount = fee_calc['fee_amount']

            for referrer_info in fee_calc['referral_chain']:
                commission_pct = referrer_info['commission_percentage']
                commission_amount = fee_amount * (commission_pct / Decimal("100"))

                # Log commission
                query = text("""
                    INSERT INTO referral_commissions (
                        fee_id,
                        referrer_user_id,
                        referred_user_id,
                        level,
                        commission_percentage,
                        commission_amount,
                        status
                    ) VALUES (
                        :fee_id,
                        :referrer_id,
                        :referred_id,
                        :level,
                        :commission_pct,
                        :commission_amount,
                        'pending'
                    );
                """)

                session.execute(query, {
                    'fee_id': fee_id,
                    'referrer_id': referrer_info['referrer_user_id'],
                    'referred_id': user_id,
                    'level': referrer_info['level'],
                    'commission_pct': str(commission_pct),
                    'commission_amount': str(commission_amount)
                })

                logger.info(
                    f"💰 FEE CALC: Commission logged - Level {referrer_info['level']}: "
                    f"${commission_amount} for user {referrer_info['referrer_user_id']}"
                )

            session.commit()
            session.close()

        except Exception as e:
            logger.error(f"❌ FEE FAILED: Error distributing commissions: {e}")


# Singleton instance
_fee_service_instance = None

def get_fee_service() -> FeeService:
    """Get singleton FeeService instance"""
    global _fee_service_instance
    if _fee_service_instance is None:
        _fee_service_instance = FeeService()
    return _fee_service_instance
