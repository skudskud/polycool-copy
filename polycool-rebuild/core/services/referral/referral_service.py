"""
Referral Service
Manages 3-tier referral system, commission tracking, and referral links
"""
import secrets
import string
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from sqlalchemy import select, func, and_
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import User, Referral, ReferralCommission
from core.services.user.user_service import UserService
from core.services.referral.bot_username_service import get_bot_username_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Commission rates by level
COMMISSION_RATES = {
    1: Decimal("25.00"),  # 25%
    2: Decimal("5.00"),   # 5%
    3: Decimal("3.00")    # 3%
}

# Referral link format
REFERRAL_LINK_FORMAT = "https://t.me/{bot_username}?start={referrer_code}"


class ReferralService:
    """
    Service for managing referral relationships and stats
    - Create 3-tier referral relationships
    - Generate referral links
    - Get referral statistics
    - Generate unique referral codes
    """

    def __init__(self):
        """Initialize referral service"""
        self.user_service = UserService()
        self.bot_username_service = get_bot_username_service()

    async def generate_referral_code(self, user_id: int) -> str:
        """
        Generate unique referral code for user
        Uses username if available, otherwise generates random code

        Args:
            user_id: Internal database user ID

        Returns:
            Unique referral code
        """
        try:
            async with get_db() as db:
                user = await self.user_service.get_by_id(user_id)
                if not user:
                    raise ValueError(f"User {user_id} not found")

                # If user already has a referral code, return it
                if user.referral_code:
                    return user.referral_code

                # Try to use username as referral code
                if user.username:
                    code = user.username.lower().replace(" ", "_")
                    # Check if code is unique
                    existing = await db.execute(
                        select(User).where(User.referral_code == code)
                    )
                    if existing.scalar_one_or_none() is None:
                        user.referral_code = code
                        await db.commit()
                        return code

                # Generate random code if username not available or not unique
                while True:
                    code = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
                    existing = await db.execute(
                        select(User).where(User.referral_code == code)
                    )
                    if existing.scalar_one_or_none() is None:
                        user.referral_code = code
                        await db.commit()
                        return code

        except Exception as e:
            logger.error(f"Error generating referral code for user {user_id}: {e}")
            # Fallback: use user_id as code
            return f"user_{user_id}"

    async def create_referral(
        self,
        referrer_code: str,
        referred_user_id: int
    ) -> Tuple[bool, str]:
        """
        Create referral relationship with automatic multi-level detection

        Args:
            referrer_code: Referral code (username or generated code) of referrer
            referred_user_id: Internal database ID of referred user

        Returns:
            Tuple of (success, message)
        """
        try:
            async with get_db() as db:
                # Find referrer by referral_code (try exact match first)
                referrer_result = await db.execute(
                    select(User).where(User.referral_code == referrer_code)
                )
                referrer = referrer_result.scalar_one_or_none()

                # If not found by referral_code, try by username (case-insensitive)
                if not referrer:
                    logger.debug(f"🔍 Referrer code '{referrer_code}' not found, trying username match")
                    referrer_result = await db.execute(
                        select(User).where(func.lower(User.username) == func.lower(referrer_code))
                    )
                    referrer = referrer_result.scalar_one_or_none()

                    # If found by username, generate referral_code if missing
                    if referrer and not referrer.referral_code:
                        logger.info(f"🔗 Generating referral_code for user {referrer.id} (username: {referrer.username})")
                        referrer.referral_code = await self.generate_referral_code(referrer.id)
                        await db.commit()
                        logger.info(f"✅ Generated referral_code '{referrer.referral_code}' for user {referrer.id}")

                if not referrer:
                    logger.warning(f"🔗 REFERRAL: Referrer code/username '{referrer_code}' not found in database")
                    # Log available referral codes for debugging
                    all_codes = await db.execute(
                        select(User.referral_code, User.username).where(User.referral_code.isnot(None))
                    )
                    codes_list = all_codes.fetchall()
                    logger.debug(f"Available referral codes: {[f'{c[1]}->{c[0]}' for c in codes_list[:10]]}")
                    return False, f"Referrer code '{referrer_code}' not found"

                referrer_id = referrer.id

                # Validate not self-referral
                if referrer_id == referred_user_id:
                    logger.warning(f"🔗 REFERRAL: User {referred_user_id} tried to self-refer")
                    return False, "Cannot refer yourself"

                # Check if user already referred
                existing_referral = await db.execute(
                    select(Referral).where(Referral.referred_user_id == referred_user_id)
                )
                if existing_referral.scalar_one_or_none():
                    logger.warning(f"🔗 REFERRAL: User {referred_user_id} already referred")
                    return False, "User already has a referrer"

                # Create Level 1 relationship
                level1_referral = Referral(
                    referrer_user_id=referrer_id,
                    referred_user_id=referred_user_id,
                    level=1
                )
                db.add(level1_referral)
                await db.flush()  # Flush to get IDs

                logger.info(f"✅ REFERRAL L1: User {referrer_id} → {referred_user_id}")

                # Find Level 2 (referrer's referrer)
                level2_query = select(Referral).where(
                    and_(
                        Referral.referred_user_id == referrer_id,
                        Referral.level == 1
                    )
                )
                level2_result = await db.execute(level2_query)
                level2_referrer = level2_result.scalar_one_or_none()

                level2_created = False
                level3_created = False

                if level2_referrer:
                    level2_referral = Referral(
                        referrer_user_id=level2_referrer.referrer_user_id,
                        referred_user_id=referred_user_id,
                        level=2
                    )
                    db.add(level2_referral)
                    level2_created = True
                    logger.info(f"✅ REFERRAL L2: Created level 2 relationship for {referred_user_id}")

                    # Find Level 3 (referrer's referrer's referrer)
                    level3_query = select(Referral).where(
                        and_(
                            Referral.referred_user_id == level2_referrer.referrer_user_id,
                            Referral.level == 1
                        )
                    )
                    level3_result = await db.execute(level3_query)
                    level3_referrer = level3_result.scalar_one_or_none()

                    if level3_referrer:
                        level3_referral = Referral(
                            referrer_user_id=level3_referrer.referrer_user_id,
                            referred_user_id=referred_user_id,
                            level=3
                        )
                        db.add(level3_referral)
                        level3_created = True
                        logger.info(f"✅ REFERRAL L3: Created level 3 relationship for {referred_user_id}")

                await db.commit()

                total_levels = 1 + (1 if level2_created else 0) + (1 if level3_created else 0)
                logger.info(f"🎉 REFERRAL: User {referred_user_id} linked to {total_levels} referrer(s)")

                return True, f"Referral created successfully ({total_levels} level(s))"

        except Exception as e:
            logger.error(f"❌ REFERRAL ERROR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False, f"Error creating referral: {str(e)}"

    async def get_user_referral_stats(self, user_id: int) -> Dict:
        """
        Get comprehensive referral statistics for a user

        Args:
            user_id: Internal database user ID

        Returns:
            Dictionary with referral stats, link, and commission breakdown
        """
        try:
            async with get_db() as db:
                user = await self.user_service.get_by_id(user_id)
                if not user:
                    return {
                        'user_username': None,
                        'referral_code': None,
                        'referral_link': None,
                        'bot_username': await self.bot_username_service.get_bot_username(),
                        'total_referrals': {'level_1': 0, 'level_2': 0, 'level_3': 0},
                        'total_commissions': {'pending': 0.0, 'paid': 0.0, 'total': 0.0},
                        'commission_breakdown': []
                    }

                # Generate referral code if not exists
                referral_code = await self.generate_referral_code(user_id)

                # Get bot username (for display purposes)
                bot_username = await self.bot_username_service.get_bot_username()

                # Generate referral link with fixed bot username: Polypolis_Bot
                referral_link = REFERRAL_LINK_FORMAT.format(
                    bot_username="Polypolis_Bot",
                    referrer_code=referral_code
                )

                # Count referrals by level
                referrals_query = select(
                    Referral.level,
                    func.count(Referral.id).label('count')
                ).where(
                    Referral.referrer_user_id == user_id
                ).group_by(Referral.level)

                referral_counts_result = await db.execute(referrals_query)
                referral_counts = referral_counts_result.fetchall()

                total_referrals = {'level_1': 0, 'level_2': 0, 'level_3': 0}
                for level, count in referral_counts:
                    total_referrals[f'level_{level}'] = count

                # Calculate commissions by status
                commissions_query = select(
                    ReferralCommission.status,
                    func.sum(ReferralCommission.commission_amount).label('total')
                ).where(
                    ReferralCommission.referrer_user_id == user_id
                ).group_by(ReferralCommission.status)

                commission_sums_result = await db.execute(commissions_query)
                commission_sums = commission_sums_result.fetchall()

                pending = Decimal("0.0")
                paid = Decimal("0.0")
                for status, total in commission_sums:
                    if status == 'pending':
                        pending = Decimal(str(total or 0))
                    elif status == 'paid':
                        paid = Decimal(str(total or 0))

                # Commission breakdown by level
                breakdown_query = select(
                    ReferralCommission.level,
                    ReferralCommission.status,
                    func.sum(ReferralCommission.commission_amount).label('total')
                ).where(
                    ReferralCommission.referrer_user_id == user_id
                ).group_by(ReferralCommission.level, ReferralCommission.status)

                breakdown_result = await db.execute(breakdown_query)
                breakdown_data = breakdown_result.fetchall()

                # Organize breakdown
                breakdown = {
                    1: {'pending': Decimal("0.0"), 'paid': Decimal("0.0")},
                    2: {'pending': Decimal("0.0"), 'paid': Decimal("0.0")},
                    3: {'pending': Decimal("0.0"), 'paid': Decimal("0.0")}
                }

                for level, status, total in breakdown_data:
                    if level in breakdown:
                        breakdown[level][status] = Decimal(str(total or 0))

                commission_breakdown = [
                    {
                        'level': 1,
                        'rate': 25.0,
                        'pending': float(breakdown[1]['pending']),
                        'paid': float(breakdown[1]['paid'])
                    },
                    {
                        'level': 2,
                        'rate': 5.0,
                        'pending': float(breakdown[2]['pending']),
                        'paid': float(breakdown[2]['paid'])
                    },
                    {
                        'level': 3,
                        'rate': 3.0,
                        'pending': float(breakdown[3]['pending']),
                        'paid': float(breakdown[3]['paid'])
                    }
                ]

                return {
                    'user_username': user.username,
                    'referral_code': referral_code,
                    'referral_link': referral_link,
                    'bot_username': bot_username,
                    'total_referrals': total_referrals,
                    'total_commissions': {
                        'pending': float(pending),
                        'paid': float(paid),
                        'total': float(pending + paid)
                    },
                    'commission_breakdown': commission_breakdown
                }

        except Exception as e:
            logger.error(f"❌ REFERRAL STATS ERROR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'user_username': None,
                'referral_code': None,
                'referral_link': None,
                'bot_username': await self.bot_username_service.get_bot_username(),
                'total_referrals': {'level_1': 0, 'level_2': 0, 'level_3': 0},
                'total_commissions': {'pending': 0.0, 'paid': 0.0, 'total': 0.0},
                'commission_breakdown': []
            }

    async def get_referral_link(self, user_id: int) -> Optional[str]:
        """
        Generate referral link for user

        Args:
            user_id: Internal database user ID

        Returns:
            Referral link or None if error
        """
        try:
            stats = await self.get_user_referral_stats(user_id)
            return stats.get('referral_link')
        except Exception as e:
            logger.error(f"Error generating referral link for user {user_id}: {e}")
            return None

    async def get_referrals_list(self, user_id: int, level: Optional[int] = None) -> List[Dict]:
        """
        Get list of referrals for a user

        Args:
            user_id: Internal database user ID
            level: Optional level filter (1, 2, or 3)

        Returns:
            List of referral dictionaries
        """
        try:
            async with get_db() as db:
                query = select(Referral, User).join(
                    User, Referral.referred_user_id == User.id
                ).where(
                    Referral.referrer_user_id == user_id
                )

                if level:
                    query = query.where(Referral.level == level)

                result = await db.execute(query)
                referrals_data = result.fetchall()

                referrals = []
                for referral, referred_user in referrals_data:
                    referrals.append({
                        'referred_user_id': referral.referred_user_id,
                        'referred_username': referred_user.username,
                        'level': referral.level,
                        'created_at': referral.created_at.isoformat() if referral.created_at else None
                    })

                return referrals

        except Exception as e:
            logger.error(f"Error getting referrals list for user {user_id}: {e}")
            return []


# Singleton instance
_referral_service: Optional[ReferralService] = None


def get_referral_service() -> ReferralService:
    """Get singleton referral service instance"""
    global _referral_service
    if _referral_service is None:
        _referral_service = ReferralService()
    return _referral_service
