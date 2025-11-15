"""
Commission Service
Calculates trade fees and referral commissions
"""
import os
from decimal import Decimal
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import Web3
from eth_account import Account

from core.database.connection import get_db
from core.database.models import User, TradeFee, Referral, ReferralCommission
from core.services.user.user_service import UserService
from core.services.referral.referral_service import COMMISSION_RATES
from infrastructure.logging.logger import get_logger
from infrastructure.config.settings import settings

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Fee configuration
FEE_RATE = Decimal("0.01")  # 1% = 0.01
MINIMUM_FEE = Decimal("0.1")  # $0.1 minimum
REFERRAL_DISCOUNT_PERCENTAGE = Decimal("10.0")  # 10% discount for referred users

# Commission payout configuration
MIN_COMMISSION_PAYOUT = Decimal("1.0")  # Minimum $1.00 to claim
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon

# USDC.e ERC20 ABI (minimal for transfer)
USDC_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }
]


class CommissionService:
    """
    Service for calculating trade fees and referral commissions
    - Calculate fees (1% or $0.1 minimum)
    - Apply 10% discount for referred users
    - Create commissions for 3-tier referral system
    """

    def __init__(self):
        """Initialize commission service"""
        self.user_service = UserService()

    async def calculate_and_record_fee(
        self,
        user_id: int,
        trade_amount: float,
        trade_type: str,
        market_id: str,
        trade_id: Optional[int] = None
    ) -> Optional[TradeFee]:
        """
        Calculate and record trade fee

        Args:
            user_id: Internal database user ID
            trade_amount: Trade amount in USDC
            trade_type: 'BUY' or 'SELL'
            market_id: Market identifier
            trade_id: Optional trade ID reference

        Returns:
            TradeFee object or None if fees disabled or error
        """
        # Skip fee calculation if SKIP_DB=true (bot mode without DB access)
        # Fees should be calculated via API endpoint instead
        if SKIP_DB:
            logger.debug(f"⚠️ SKIP_DB=true: Skipping fee calculation for user {user_id} (should use API endpoint)")
            return None

        try:
            async with get_db() as db:
                # Get user
                user = await self.user_service.get_by_id(user_id)
                if not user:
                    logger.error(f"User {user_id} not found for fee calculation")
                    return None

                # Check if fees are enabled for this user
                if not user.fees_enabled:
                    logger.debug(f"Fees disabled for user {user_id}, skipping fee calculation")
                    return None

                trade_amount_decimal = Decimal(str(trade_amount))

                # Calculate fee (1% of trade amount)
                fee_amount = trade_amount_decimal * FEE_RATE

                # Apply minimum fee
                final_fee_amount = max(fee_amount, MINIMUM_FEE)

                # Check if user has referral discount (has a referrer)
                has_referral_discount = False
                discount_amount = Decimal("0.0")
                final_fee_after_discount = final_fee_amount

                referral_query = select(Referral).where(
                    Referral.referred_user_id == user_id
                ).limit(1)
                referral_result = await db.execute(referral_query)
                referral = referral_result.scalar_one_or_none()

                if referral:
                    # User has a referrer - apply 10% discount
                    has_referral_discount = True
                    discount_amount = final_fee_amount * (REFERRAL_DISCOUNT_PERCENTAGE / Decimal("100.0"))
                    final_fee_after_discount = final_fee_amount - discount_amount
                    logger.debug(f"Applied 10% referral discount for user {user_id}: ${discount_amount:.2f}")

                # Create trade fee record
                trade_fee = TradeFee(
                    user_id=user_id,
                    trade_id=trade_id,
                    market_id=market_id,
                    trade_amount=trade_amount_decimal,
                    fee_rate=float(FEE_RATE),
                    fee_amount=float(fee_amount),
                    minimum_fee=float(MINIMUM_FEE),
                    final_fee_amount=float(final_fee_amount),
                    has_referral_discount=has_referral_discount,
                    discount_percentage=float(REFERRAL_DISCOUNT_PERCENTAGE) if has_referral_discount else 0.0,
                    discount_amount=float(discount_amount),
                    final_fee_after_discount=float(final_fee_after_discount),
                    trade_type=trade_type,
                    is_paid=False
                )

                db.add(trade_fee)
                await db.flush()  # Flush to get ID

                logger.info(
                    f"💰 FEE: User {user_id}, Trade ${trade_amount:.2f}, "
                    f"Fee ${final_fee_after_discount:.2f} "
                    f"({'with' if has_referral_discount else 'without'} discount)"
                )

                # Calculate and create commissions for referral chain
                await self._create_commissions(db, user_id, trade_fee)

                await db.commit()
                return trade_fee

        except RuntimeError as e:
            # Handle "Database not initialized" error gracefully
            if "Database not initialized" in str(e):
                logger.debug(f"⚠️ Database not initialized: Skipping fee calculation for user {user_id} (SKIP_DB mode)")
                return None
            raise
        except Exception as e:
            logger.error(f"Error calculating fee for user {user_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def _create_commissions(
        self,
        db: AsyncSession,
        referred_user_id: int,
        trade_fee: TradeFee
    ) -> None:
        """
        Create commissions for all referral levels

        Args:
            db: Database session
            referred_user_id: User who made the trade
            trade_fee: TradeFee object
        """
        try:
            # Fee amount to use for commission calculation (after discount)
            fee_for_commission = Decimal(str(trade_fee.final_fee_after_discount))

            # Get all referrals for this user (all levels)
            referrals_query = select(Referral).where(
                Referral.referred_user_id == referred_user_id
            )
            referrals_result = await db.execute(referrals_query)
            referrals = referrals_result.scalars().all()

            if not referrals:
                logger.debug(f"No referrals found for user {referred_user_id}, no commissions to create")
                return

            commissions_created = 0

            for referral in referrals:
                level = referral.level
                referrer_user_id = referral.referrer_user_id

                # Get commission rate for this level
                commission_rate = COMMISSION_RATES.get(level, Decimal("0.0"))
                if commission_rate == 0:
                    continue

                # Calculate commission amount
                commission_amount = fee_for_commission * (commission_rate / Decimal("100.0"))

                # Create commission record
                commission = ReferralCommission(
                    referral_id=referral.id,
                    referrer_user_id=referrer_user_id,
                    referred_user_id=referred_user_id,
                    level=level,
                    trade_fee_id=trade_fee.id,
                    fee_amount=float(fee_for_commission),
                    commission_rate=float(commission_rate),
                    commission_amount=float(commission_amount),
                    status='pending'
                )

                db.add(commission)
                commissions_created += 1

                logger.debug(
                    f"💰 COMMISSION L{level}: User {referrer_user_id} earns "
                    f"${commission_amount:.2f} ({commission_rate}% of ${fee_for_commission:.2f})"
                )

            if commissions_created > 0:
                logger.info(
                    f"✅ Created {commissions_created} commission(s) for trade fee {trade_fee.id}"
                )

        except Exception as e:
            logger.error(f"Error creating commissions: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def get_pending_commissions(self, user_id: int) -> List[Dict]:
        """
        Get pending commissions for a user

        Args:
            user_id: Internal database user ID

        Returns:
            List of commission dictionaries
        """
        try:
            async with get_db() as db:
                query = select(ReferralCommission).where(
                    and_(
                        ReferralCommission.referrer_user_id == user_id,
                        ReferralCommission.status == 'pending'
                    )
                ).order_by(ReferralCommission.created_at.desc())

                result = await db.execute(query)
                commissions = result.scalars().all()

                return [
                    {
                        'id': c.id,
                        'level': c.level,
                        'commission_rate': float(c.commission_rate),
                        'commission_amount': float(c.commission_amount),
                        'fee_amount': float(c.fee_amount),
                        'created_at': c.created_at.isoformat() if c.created_at else None
                    }
                    for c in commissions
                ]

        except Exception as e:
            logger.error(f"Error getting pending commissions for user {user_id}: {e}")
            return []

    async def get_total_pending_commission(self, user_id: int) -> float:
        """
        Get total pending commission amount for a user

        Args:
            user_id: Internal database user ID

        Returns:
            Total pending commission amount
        """
        try:
            async with get_db() as db:
                query = select(
                    func.sum(ReferralCommission.commission_amount)
                ).where(
                    and_(
                        ReferralCommission.referrer_user_id == user_id,
                        ReferralCommission.status == 'pending'
                    )
                )

                result = await db.execute(query)
                total = result.scalar_one_or_none()

                return float(total or 0.0)

        except Exception as e:
            logger.error(f"Error getting total pending commission for user {user_id}: {e}")
            return 0.0

    async def claim_commissions(self, user_id: int) -> Tuple[bool, str, float, Optional[str]]:
        """
        Claim pending commissions and transfer USDC.e from treasury to user wallet

        Args:
            user_id: Internal database user ID

        Returns:
            Tuple of (success, message, amount_paid, transaction_hash)
        """
        try:
            # Check if treasury wallet is configured
            treasury_private_key = settings.web3.treasury_private_key
            if not treasury_private_key:
                logger.warning("⚠️ TREASURY_PRIVATE_KEY not set - commission claims are disabled")
                return False, "Commission claiming is not yet available. Treasury wallet not configured.", 0.0, None

            async with get_db() as db:
                # Get total pending commissions
                total_pending = await self.get_total_pending_commission(user_id)

                if total_pending <= 0:
                    return False, "No pending commissions to claim", 0.0, None

                total_pending_decimal = Decimal(str(total_pending))

                # Check minimum payout
                if total_pending_decimal < MIN_COMMISSION_PAYOUT:
                    return False, f"Minimum payout is ${MIN_COMMISSION_PAYOUT}. You have ${total_pending_decimal:.2f}", 0.0, None

                # Get user's polygon address
                user = await self.user_service.get_by_id(user_id)
                if not user:
                    return False, "User not found", 0.0, None

                recipient_address = user.polygon_address
                if not recipient_address:
                    return False, "User wallet address not found", 0.0, None

                logger.info(f"💰 CLAIM: Processing ${total_pending_decimal:.2f} payout to user {user_id} ({recipient_address})")

                # Initialize Web3 connection
                w3 = Web3(Web3.HTTPProvider(settings.web3.polygon_rpc_url))
                if not w3.is_connected():
                    logger.error("❌ Failed to connect to Polygon RPC")
                    return False, "Failed to connect to blockchain", 0.0, None

                # Get treasury account
                treasury_account = Account.from_key(treasury_private_key)
                treasury_address = treasury_account.address

                # Create USDC.e contract instance
                usdc_contract = w3.eth.contract(
                    address=Web3.to_checksum_address(USDC_E_ADDRESS),
                    abi=USDC_ABI
                )

                # Convert amount to USDC units (6 decimals)
                amount_in_usdc_units = int(float(total_pending_decimal) * 1_000_000)

                # Get nonce for treasury address
                nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(treasury_address))

                # Build transfer transaction
                tx = usdc_contract.functions.transfer(
                    Web3.to_checksum_address(recipient_address),
                    amount_in_usdc_units
                ).build_transaction({
                    'from': Web3.to_checksum_address(treasury_address),
                    'gas': 100000,
                    'gasPrice': w3.eth.gas_price,
                    'nonce': nonce,
                    'chainId': 137  # Polygon mainnet
                })

                # Sign transaction with treasury private key
                signed_tx = treasury_account.sign_transaction(tx)

                # Send transaction
                tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                tx_hash_hex = tx_hash.hex()

                logger.info(f"💸 CLAIM: Payout transaction sent: {tx_hash_hex}")

                # Wait for confirmation (with timeout)
                try:
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

                    if receipt['status'] == 1:
                        # Mark all pending commissions as paid
                        update_query = select(ReferralCommission).where(
                            and_(
                                ReferralCommission.referrer_user_id == user_id,
                                ReferralCommission.status == 'pending'
                            )
                        )
                        result = await db.execute(update_query)
                        commissions = result.scalars().all()

                        for commission in commissions:
                            commission.status = 'paid'
                            commission.paid_at = datetime.utcnow()
                            commission.claim_tx_hash = tx_hash_hex

                        await db.commit()

                        logger.info(f"✅ CLAIM SUCCESS: Paid ${total_pending_decimal:.2f} to user {user_id}")
                        return True, f"Commissions paid successfully", float(total_pending_decimal), tx_hash_hex
                    else:
                        logger.error(f"❌ CLAIM FAILED: Transaction reverted")
                        return False, "Transaction failed on blockchain", 0.0, None

                except Exception as e:
                    logger.error(f"❌ CLAIM ERROR: Transaction confirmation failed: {e}")
                    # Transaction was sent but confirmation failed - still mark as paid if we can verify
                    # For now, return error and let admin manually verify
                    return False, f"Transaction sent but confirmation failed: {str(e)}", 0.0, tx_hash_hex

        except Exception as e:
            logger.error(f"❌ Error claiming commissions for user {user_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False, f"Error claiming commissions: {str(e)}", 0.0, None


# Singleton instance
_commission_service: Optional[CommissionService] = None


def get_commission_service() -> CommissionService:
    """Get singleton commission service instance"""
    global _commission_service
    if _commission_service is None:
        _commission_service = CommissionService()
    return _commission_service
