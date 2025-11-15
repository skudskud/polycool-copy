"""
MARKET RESOLUTION MONITOR
Detects newly resolved markets and creates resolved_positions records
"""

import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import SessionLocal, ResolvedPosition
from telegram_bot.services.transaction_service import TransactionService
from telegram_bot.services.fee_service import get_fee_service
from core.utils.aiohttp_client import get_http_client

logger = logging.getLogger(__name__)


class MarketResolutionMonitor:
    """Monitors markets for resolution"""

    def __init__(self):
        self.transaction_service = TransactionService()
        self.fee_service = get_fee_service()
        logger.info("✅ MarketResolutionMonitor initialized")

    async def scan_for_resolutions(self, lookback_minutes: int = 10) -> Dict:
        """Scan for newly resolved markets"""
        logger.info(f"🔍 [RESOLUTION] Scanning for resolved markets (lookback: {lookback_minutes}min)")

        stats = {'markets': 0, 'positions': 0, 'winners': 0, 'losers': 0}

        try:
            # Find RESOLVED markets using multiple signals
            with SessionLocal() as session:
                cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)

                # Detect resolved markets by checking if:
                # 1. resolution_date is set by Polymarket (official resolution)
                # 2. OR end_date has passed AND outcome_prices show decisive winner (≥0.90)
                #
                # KEY FIX: Use end_date/resolution_date for lookback, NOT updated_at
                # This catches markets that resolved days ago but haven't been updated recently
                query = text("""
                    SELECT market_id, condition_id, title, slug, outcome_prices, clob_token_ids
                    FROM subsquid_markets_poll
                    WHERE outcome_prices IS NOT NULL
                        AND array_length(outcome_prices, 1) >= 2
                        AND (
                            (resolution_date IS NOT NULL AND resolution_date >= :cutoff)
                            OR (
                                end_date IS NOT NULL
                                AND end_date >= :cutoff
                                AND end_date < NOW()
                                AND (outcome_prices[1] >= 0.90 OR outcome_prices[2] >= 0.90)
                            )
                        )
                    LIMIT 100
                """)

                result = session.execute(query, {'cutoff': cutoff})

                for row in result:
                    # Skip if already processed
                    exists = session.query(ResolvedPosition).filter(
                        ResolvedPosition.market_id == row.market_id
                    ).first()

                    if exists:
                        continue

                    stats['markets'] += 1

                    # Determine winner
                    winner = self._get_winner(row.outcome_prices)
                    if not winner:
                        continue

                    # Find users with positions (using LIVE blockchain data)
                    user_positions = await self._get_users_with_positions(row.condition_id, session)

                    for user_pos in user_positions:
                        created = await self._create_position(
                            user_pos['user_id'],
                            user_pos['position'],
                            row,
                            winner,
                            session
                        )
                        if created:
                            stats['positions'] += 1
                            if created.is_winner:
                                stats['winners'] += 1
                            else:
                                stats['losers'] += 1

            logger.info(f"✅ [RESOLUTION] Scan complete: {stats}")

        except Exception as e:
            logger.error(f"❌ [RESOLUTION] Error: {e}")

        return stats

    def _get_winner(self, prices: List) -> Optional[str]:
        """Determine winner from outcome_prices"""
        if not prices or len(prices) < 2:
            return None

        yes_price = float(prices[0]) if prices[0] else 0
        no_price = float(prices[1]) if prices[1] else 0

        # Lowered threshold from 0.99 to 0.90 to catch resolved markets
        # Markets often settle around 0.95 before reaching full 0.99
        if yes_price >= 0.90 and yes_price > no_price + 0.80:
            return 'YES'
        elif no_price >= 0.90 and no_price > yes_price + 0.80:
            return 'NO'
        elif abs(yes_price - 0.5) < 0.1 and abs(no_price - 0.5) < 0.1:
            return 'INVALID'

        return None

    async def _get_users_with_positions(self, condition_id: str, session: Session) -> List[Dict]:
        """Find users with positions in this market

        OPTIMIZED: Uses transaction history instead of API calls to avoid rate limiting.
        Only checks users who have actually traded in this market.

        Args:
            condition_id: The market's condition_id (0x...) for matching
        """
        # OPTIMIZATION: Find users who have transactions in this market
        # Instead of scanning ALL users with API calls (which causes 429 errors)
        query = text("""
            SELECT DISTINCT t.user_id as telegram_user_id, u.polygon_address
            FROM transactions t
            JOIN users u ON t.user_id = u.telegram_user_id
            WHERE t.market_id IN (
                SELECT market_id FROM subsquid_markets_poll
                WHERE condition_id = :condition_id
            )
            AND u.polygon_address IS NOT NULL
        """)

        result = session.execute(query, {'condition_id': condition_id})
        users_with_transactions = list(result)

        logger.debug(f"🔍 [OPTIMIZED] Found {len(users_with_transactions)} users with transactions in market {condition_id[:10]}...")

        users_with_positions = []

        # Only fetch positions for users who actually traded in this market
        # This reduces API calls from hundreds to just the active traders
        if users_with_transactions:
            http_session = await get_http_client()
            rate_limit_count = 0

            for i, row in enumerate(users_with_transactions):
                user_id = row.telegram_user_id
                wallet_address = row.polygon_address

                logger.debug(f"🔍 [DEBUG] Checking positions for user {user_id} (traded in this market)")

                # RATE LIMITING: Add delay every 5 requests to avoid 429 errors
                if i > 0 and i % 5 == 0:
                    logger.info(f"⏳ Rate limiting: Pausing for 2 seconds after {i} requests...")
                    await asyncio.sleep(2)

                try:
                    # Fetch positions with timeout and error handling
                    url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
                    async with http_session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            positions_data = await response.json()

                            # Check if user still has position in this market
                            for pos in positions_data:
                                pos_condition_id = pos.get('conditionId', '')
                                if pos_condition_id.lower() == condition_id.lower():
                                    size = float(pos.get('size', 0))
                                    if size > 0.001:
                                        users_with_positions.append({
                                            'user_id': user_id,
                                            'position': pos
                                        })
                                        logger.info(f"✅ Found active position: User {user_id} has {size} tokens")
                                        break
                        elif response.status == 429:
                            rate_limit_count += 1
                            logger.warning(f"⚠️ Rate limited for user {user_id} ({rate_limit_count}/session)")
                            if rate_limit_count >= 3:  # Stop after 3 rate limits
                                logger.error(f"❌ Too many rate limits ({rate_limit_count}), stopping market scan")
                                break
                            await asyncio.sleep(5)  # Longer pause on rate limit
                        else:
                            logger.warning(f"⚠️ API error {response.status} for user {user_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not fetch positions for user {user_id}: {e}")
                    continue

        logger.debug(f"🔍 [DEBUG] Total users with positions in this market: {len(users_with_positions)}")
        return users_with_positions

    async def _create_position(self, user_id: int, position_data: Dict, market_row, winner: str, session: Session):
        """Create resolved_position record from live position data

        Args:
            user_id: Telegram user ID
            position_data: Live position data from Polymarket API
            market_row: Market data from database
            winner: Winning outcome (YES/NO/INVALID)
            session: Database session
        """
        try:
            # Extract position details from live API data
            tokens = Decimal(str(position_data.get('size', 0)))
            if tokens < 0.001:
                return None

            # Get outcome (YES/NO)
            outcome = position_data.get('outcome', '').upper()
            if not outcome:
                logger.warning(f"⚠️ No outcome in position data for user {user_id}")
                return None

            # Calculate cost basis
            avg_price = float(position_data.get('avgPrice', 0))
            cost = tokens * Decimal(str(avg_price))

            # Get token_id (called 'asset' in API response)
            token_id = position_data.get('asset', '')

            # Determine if winner
            is_winner = (outcome == winner) or (winner == 'INVALID')

            if is_winner:
                # Winner gets tokens redeemed at $1 each, minus 1% fee
                gross = tokens * Decimal('1.00')
                fee_calc = self.fee_service.calculate_fee(user_id, float(gross))
                fee = Decimal(str(fee_calc['fee_amount']))
                net = gross - fee
            else:
                # Loser gets nothing
                gross = fee = net = Decimal('0.00')

            pnl = net - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else Decimal('0')

            resolved_pos = ResolvedPosition(
                user_id=user_id,
                market_id=market_row.market_id,
                condition_id=market_row.condition_id,
                market_title=market_row.title,
                market_slug=market_row.slug,
                outcome=outcome,
                token_id=token_id,
                tokens_held=tokens,
                total_cost=cost,
                avg_buy_price=Decimal(str(avg_price)),
                transaction_count=0,  # Unknown from live data
                winning_outcome=winner,
                is_winner=is_winner,
                resolved_at=datetime.utcnow(),
                gross_value=gross,
                fee_amount=fee,
                net_value=net,
                pnl=pnl,
                pnl_percentage=pnl_pct,
                expires_at=datetime.utcnow() + timedelta(days=3) if not is_winner else None
            )

            session.add(resolved_pos)
            session.commit()

            logger.info(f"✅ Created position: User {user_id} - {outcome} {'WIN' if is_winner else 'LOSS'} ${float(net):.2f}")

            # Send notification
            from telegram_bot.services.resolution_notification_service import send_resolution_notification
            asyncio.create_task(send_resolution_notification(user_id, resolved_pos))

            return resolved_pos

        except Exception as e:
            logger.error(f"❌ Error creating resolved position: {e}")
            return None


_monitor = None

def get_resolution_monitor():
    global _monitor
    if _monitor is None:
        _monitor = MarketResolutionMonitor()
    return _monitor
