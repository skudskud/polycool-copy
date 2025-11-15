"""
Resolution Worker - Auto-liquidation for resolved markets
Runs hourly to detect resolved markets and notify users of their P&L
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import List, Dict, Optional
import aiohttp
from sqlalchemy import create_engine, text
from telegram import Bot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "2"))
MAX_API_CALLS_PER_CYCLE = int(os.getenv("MAX_API_CALLS_PER_CYCLE", "200"))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


class ResolutionWorker:
    """Worker that processes resolved markets and notifies users"""

    def __init__(self):
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is required")
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

        self.db = create_engine(DATABASE_URL, pool_pre_ping=True)
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.http_session = None
        self.stats = {
            'markets_found': 0,
            'user_market_pairs': 0,
            'positions_created': 0,
            'auto_sells': 0,
            'notifications_sent': 0,
            'api_errors': 0,
            'no_position_found': 0
        }

    async def run(self):
        """Main execution: find resolved markets and process positions"""
        logger.info("🚀 Starting resolution worker cycle")
        logger.info(f"⚙️ Config: LOOKBACK_HOURS={LOOKBACK_HOURS}, MAX_API_CALLS={MAX_API_CALLS_PER_CYCLE}, DRY_RUN={DRY_RUN}")
        start_time = datetime.now(timezone.utc)

        self.http_session = aiohttp.ClientSession()

        try:
            # Step 1: Find all users with positions in newly resolved markets
            user_market_pairs = self.get_users_with_resolved_positions()
            self.stats['user_market_pairs'] = len(user_market_pairs)

            # Count unique markets
            unique_markets = set(p['market_id'] for p in user_market_pairs)
            self.stats['markets_found'] = len(unique_markets)

            logger.info(f"📊 Found {len(unique_markets)} resolved markets with {len(user_market_pairs)} user-market pairs to process")

            if len(user_market_pairs) == 0:
                logger.info("✅ No new resolved positions to process")
                return

            # Step 2: Process each user-market pair
            api_calls_made = 0
            for i, pair in enumerate(user_market_pairs):
                if api_calls_made >= MAX_API_CALLS_PER_CYCLE:
                    remaining = len(user_market_pairs) - i
                    logger.warning(f"⚠️ Reached API call limit ({MAX_API_CALLS_PER_CYCLE}), deferring {remaining} pairs to next cycle")
                    break

                await self.process_user_position(pair)
                api_calls_made += 1

                # Rate limiting: 200ms delay between API calls
                if i < len(user_market_pairs) - 1:  # Don't sleep after last iteration
                    await asyncio.sleep(0.2)

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(f"✅ Cycle complete in {elapsed:.1f}s")
            logger.info(f"📈 Stats: {self.stats}")

        except Exception as e:
            logger.error(f"❌ Worker error: {e}", exc_info=True)
            raise
        finally:
            await self.http_session.close()

    def get_users_with_resolved_positions(self) -> List[Dict]:
        """
        Single DB query to find all users with positions in newly resolved markets
        Includes both RESOLVED markets and PROPOSED markets with extreme prices (>= 0.99 and <= 0.01)

        Returns list of:
        {
            'user_id': telegram_user_id,
            'user_address': polygon_address,
            'market_id': market_id,
            'condition_id': condition_id,
            'title': market_title,
            'winning_outcome': 0 or 1,
            'resolution_date': timestamp,
            'resolution_status': 'RESOLVED' or 'PROPOSED'
        }
        """
        # Build interval string dynamically
        interval_str = f"{LOOKBACK_HOURS} hours"

        query = text(f"""
            SELECT DISTINCT
                t.user_id,
                u.polygon_address as user_address,
                m.market_id,
                m.condition_id,
                m.title,
                -- For RESOLVED: use existing winning_outcome
                -- For PROPOSED: calculate from outcome_prices (YES=1 if prices[1]>=0.99, NO=0 if prices[2]>=0.99)
                COALESCE(
                    m.winning_outcome,
                    CASE
                        WHEN m.resolution_status = 'PROPOSED'
                         AND array_length(m.outcome_prices, 1) = 2
                         AND m.outcome_prices[1] >= 0.99
                         AND m.outcome_prices[2] <= 0.01
                        THEN 1  -- YES is winner
                        WHEN m.resolution_status = 'PROPOSED'
                         AND array_length(m.outcome_prices, 1) = 2
                         AND m.outcome_prices[2] >= 0.99
                         AND m.outcome_prices[1] <= 0.01
                        THEN 0  -- NO is winner
                        ELSE NULL
                    END
                ) as winning_outcome,
                COALESCE(m.resolution_date, m.end_date) as resolution_date,
                m.resolution_status
            FROM transactions t
            JOIN users u ON t.user_id = u.telegram_user_id
            JOIN subsquid_markets_poll m ON t.market_id = m.market_id
            WHERE (
                -- RESOLVED markets (existing logic)
                (m.resolution_status = 'RESOLVED'
                 AND m.resolution_date > NOW() - INTERVAL '{interval_str}')
                OR
                -- PROPOSED markets with extreme prices (new logic)
                (m.resolution_status = 'PROPOSED'
                 AND m.end_date < NOW() - INTERVAL '1 hour'  -- Market expired >1h ago
                 AND array_length(m.outcome_prices, 1) = 2    -- Has both YES and NO prices
                 AND (
                     (m.outcome_prices[1] >= 0.99 AND m.outcome_prices[2] <= 0.01)  -- YES winner
                     OR
                     (m.outcome_prices[2] >= 0.99 AND m.outcome_prices[1] <= 0.01)  -- NO winner
                 )
                 AND m.end_date > NOW() - INTERVAL '{interval_str}')  -- Within lookback window
            )
            AND t.user_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM resolved_positions rp
                WHERE rp.user_id = t.user_id
                  AND rp.market_id = m.market_id
            )
            ORDER BY COALESCE(m.resolution_date, m.end_date) DESC
        """)

        try:
            with self.db.connect() as conn:
                result = conn.execute(query)
                rows = [dict(row._mapping) for row in result]
                logger.debug(f"📊 Query returned {len(rows)} user-market pairs")
                return rows
        except Exception as e:
            logger.error(f"❌ Database query error: {e}", exc_info=True)
            return []

    async def process_user_position(self, pair: Dict):
        """Process a single user-market pair - Auto-sell if position still open"""
        try:
            user_id_short = str(pair['user_id'])[:8]
            market_id_short = str(pair['market_id'])[:8]
            resolution_status = pair.get('resolution_status', 'RESOLVED')

            # STEP 1: Check if user has an OPEN position (tokens > 0)
            open_position = await self.fetch_open_position(
                pair['user_address'],
                pair['condition_id']
            )

            if open_position:
                # Position is OPEN → Need to sell first!
                tokens_held = float(open_position.get('size', 0))
                outcome = open_position.get('outcome', 'Unknown')
                logger.info(f"🔔 [AUTO-SELL] User {user_id_short}... has {tokens_held:.2f} {outcome} tokens in resolved market {market_id_short}...")

                if DRY_RUN:
                    logger.info(f"[DRY RUN] Would auto-sell {tokens_held:.2f} tokens for user {pair['user_id']}")
                else:
                    # Execute auto-sell
                    sell_result = await self.auto_sell_position(pair, open_position)
                    if not sell_result['success']:
                        logger.error(f"❌ Auto-sell failed for user {user_id_short}...: {sell_result.get('error')}")
                        self.stats['api_errors'] += 1
                        return

                    self.stats['auto_sells'] += 1
                    logger.info(f"✅ [AUTO-SELL] Sold {tokens_held:.2f} tokens for ${sell_result.get('value', 0):.2f}")
                    # Wait a bit for API to update closed-positions
                    await asyncio.sleep(2)

            # STEP 2: Fetch closed position (now should exist after sell)
            closed_pos = await self.fetch_closed_position(
                pair['user_address'],
                pair['condition_id']
            )

            # STEP 2.5: For PROPOSED markets, if no closed_pos exists, create one from open_position
            if not closed_pos and resolution_status == 'PROPOSED' and open_position:
                logger.info(f"📊 [PROPOSED] No closed position found, creating from open_position for PROPOSED market")
                closed_pos = await self._create_closed_pos_from_proposed(pair, open_position)

            if not closed_pos:
                self.stats['no_position_found'] += 1
                logger.debug(f"⚠️ No closed position found for user {user_id_short}... market {market_id_short}... (may have no activity)")
                return

            if DRY_RUN:
                logger.info(f"[DRY RUN] Would process: User {pair['user_id']} / Market {pair['market_id']} / Status {resolution_status} / PnL ${closed_pos.get('realizedPnl', 0):.2f}")
                self.stats['positions_created'] += 1
                self.stats['notifications_sent'] += 1
                return

            # STEP 3: Insert resolved_position record
            position_id = self.insert_resolved_position(pair, closed_pos, resolution_status)
            self.stats['positions_created'] += 1

            # STEP 4: Send Telegram notification
            await self.send_notification(pair['user_id'], closed_pos, pair['title'], resolution_status)
            self.stats['notifications_sent'] += 1

            pnl = float(closed_pos.get('realizedPnl', 0))
            logger.info(f"✅ Processed user {user_id_short}... market {market_id_short}... ({resolution_status}): PnL ${pnl:.2f}")

        except Exception as e:
            logger.error(f"❌ Error processing user {pair.get('user_id')} / market {pair.get('market_id')}: {e}", exc_info=True)
            self.stats['api_errors'] += 1

    async def fetch_open_position(self, user_address: str, condition_id: str) -> Optional[Dict]:
        """
        Check if user has an OPEN position in this market

        API: GET /positions?user={addr}
        Returns position dict if found, None if no open position
        """
        url = f"https://data-api.polymarket.com/positions"
        params = {'user': user_address}

        try:
            async with self.http_session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    positions = await resp.json()
                    # Find position matching this condition_id
                    for pos in positions:
                        if pos.get('conditionId') == condition_id:
                            size = float(pos.get('size', 0))
                            if size > 0:
                                return pos
                    return None
                elif resp.status == 429:
                    logger.warning(f"⚠️ Rate limited (429) checking open positions for {user_address[:10]}...")
                    await asyncio.sleep(5)
                    return None
                else:
                    logger.warning(f"⚠️ API error {resp.status} checking open positions for {user_address[:10]}...")
                    return None
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Timeout checking open position for {user_address[:10]}...")
            return None
        except Exception as e:
            logger.error(f"❌ Error checking open position for {user_address[:10]}...: {e}")
            return None

    async def auto_sell_position(self, pair: Dict, open_position: Dict) -> Dict:
        """
        Auto-sell an open position in a resolved market

        Returns: {'success': bool, 'value': float, 'error': str}
        """
        try:
            # Get user credentials from database
            with self.db.connect() as conn:
                from sqlalchemy import text
                query = text("""
                    SELECT api_key, api_secret, api_passphrase, polygon_private_key
                    FROM users
                    WHERE telegram_user_id = :user_id
                """)
                result = conn.execute(query, {'user_id': pair['user_id']}).fetchone()

                if not result:
                    return {'success': False, 'error': 'User not found in database'}

                api_key = result[0]
                api_secret = result[1]
                api_passphrase = result[2]
                private_key = result[3]

                if not all([api_key, api_secret, api_passphrase, private_key]):
                    return {'success': False, 'error': 'Missing API credentials or private key'}

            # Import py-clob-client
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds, MarketOrderArgs
            from py_clob_client.order_builder.constants import SELL
            from py_clob_client.constants import POLYGON

            # Initialize client
            creds = ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase
            )
            client = ClobClient(
                host="https://clob.polymarket.com",
                key=private_key,
                chain_id=POLYGON,
                creds=creds
            )

            # Prepare sell order
            token_id = open_position.get('asset')  # token_id
            tokens_to_sell = float(open_position.get('size', 0))

            if tokens_to_sell <= 0:
                return {'success': False, 'error': 'No tokens to sell'}

            # Create and execute market sell order
            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=tokens_to_sell,  # SHARES (not USD)
                side=SELL
            )

            logger.info(f"🔄 [AUTO-SELL] Creating market sell order: {tokens_to_sell:.2f} shares, token_id={token_id[:20]}...")

            signed_order = client.create_market_order(order_args)
            from py_clob_client.clob_types import OrderType
            resp = client.post_order(signed_order, orderType=OrderType.FOK)

            logger.info(f"✅ [AUTO-SELL] Order posted: {resp}")

            # Calculate approximate value (resolved markets: winning tokens = $1 each)
            avg_price = float(open_position.get('avgPrice', 0))
            current_price = float(open_position.get('price', 1.0))  # Resolved = 1.0 or 0.0
            value = tokens_to_sell * current_price

            return {
                'success': True,
                'value': value,
                'tokens_sold': tokens_to_sell,
                'order_response': resp
            }

        except Exception as e:
            logger.error(f"❌ [AUTO-SELL] Error: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    async def _create_closed_pos_from_proposed(self, pair: Dict, open_position: Dict) -> Optional[Dict]:
        """
        Create a closed_pos dict from open_position for PROPOSED markets with extreme prices
        For PROPOSED markets, the API may not have closed positions yet, so we simulate one

        Args:
            pair: Market pair dict with winning_outcome calculated from prices
            open_position: Open position dict from API

        Returns:
            Dict in same format as fetch_closed_position() result
        """
        try:
            # Get outcome prices from database
            with self.db.connect() as conn:
                query = text("""
                    SELECT outcome_prices, outcomes
                    FROM subsquid_markets_poll
                    WHERE market_id = :market_id
                """)
                result = conn.execute(query, {'market_id': pair['market_id']}).fetchone()

                if not result:
                    logger.warning(f"⚠️ [PROPOSED] Could not find market {pair['market_id']} in DB")
                    return None

                outcome_prices = result[0]  # Array of Numeric
                outcomes = result[1]  # Array of String

            if not outcome_prices or len(outcome_prices) != 2:
                logger.warning(f"⚠️ [PROPOSED] Invalid outcome_prices for market {pair['market_id']}")
                return None

            # Extract position data
            tokens_held = float(open_position.get('size', 0))
            avg_price = float(open_position.get('avgPrice', 0))
            outcome_str = open_position.get('outcome', 'Unknown').upper()

            # Determine if user won based on outcome price
            yes_price = float(outcome_prices[0]) if outcome_prices[0] else 0
            no_price = float(outcome_prices[1]) if outcome_prices[1] else 0

            # Check if user's outcome matches winning outcome
            position_outcome_num = 1 if outcome_str == 'YES' else 0
            is_winner = (position_outcome_num == pair['winning_outcome'])

            # Calculate P&L
            total_bought = tokens_held * avg_price

            if is_winner:
                # Winner: tokens worth 1 USDC each (current price is ~1.0)
                current_price = 1.0
                realized_pnl = (tokens_held * current_price) - total_bought
            else:
                # Loser: tokens worth 0 (current price is ~0.0)
                current_price = 0.0
                realized_pnl = -total_bought  # Loss = negative of investment

            # Create closed_pos dict matching API format
            closed_pos = {
                'proxyWallet': pair['user_address'],
                'asset': open_position.get('asset', ''),
                'conditionId': pair['condition_id'],
                'avgPrice': avg_price,
                'totalBought': total_bought,
                'realizedPnl': realized_pnl,
                'curPrice': current_price,
                'outcome': outcome_str,
                'title': pair['title']
            }

            logger.info(
                f"📊 [PROPOSED] Created closed_pos: outcome={outcome_str}, "
                f"tokens={tokens_held:.2f}, price={current_price:.2f}, pnl=${realized_pnl:.2f}"
            )

            return closed_pos

        except Exception as e:
            logger.error(f"❌ [PROPOSED] Error creating closed_pos: {e}", exc_info=True)
            return None

    async def fetch_closed_position(self, user_address: str, condition_id: str) -> Optional[Dict]:
        """
        Fetch closed position from Polymarket API

        API: GET /closed-positions?user={addr}&market={condition_id}
        Returns: {
            'proxyWallet': user_address,
            'asset': token_id,
            'conditionId': condition_id,
            'avgPrice': 0.45,
            'totalBought': 100,
            'realizedPnl': 55.23,  ← KEY FIELD
            'curPrice': 1.0 or 0.0,
            'outcome': 'Yes' or 'No',
            'title': market_title
        }
        """
        url = "https://data-api.polymarket.com/closed-positions"
        params = {
            'user': user_address,
            'market': condition_id,
            'limit': 1
        }

        try:
            async with self.http_session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and len(data) > 0:
                        return data[0]
                    else:
                        return None
                elif resp.status == 429:
                    logger.warning(f"⚠️ Rate limited (429) for user {user_address[:10]}...")
                    await asyncio.sleep(5)  # Backoff
                    return None
                else:
                    logger.warning(f"⚠️ API error {resp.status} for user {user_address[:10]}...")
                    return None
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Timeout fetching closed position for {user_address[:10]}...")
            return None
        except Exception as e:
            logger.error(f"❌ API error for {user_address[:10]}...: {e}")
            return None

    def insert_resolved_position(self, pair: Dict, closed_pos: Dict, resolution_status: str = 'RESOLVED') -> int:
        """Insert resolved_position record into database"""
        pnl = float(closed_pos.get('realizedPnl', 0))
        is_winner = pnl > 0

        # Map outcome string to our format
        outcome_str = closed_pos.get('outcome', 'UNKNOWN').upper()
        if outcome_str not in ['YES', 'NO']:
            outcome_str = 'YES' if pair['winning_outcome'] == 1 else 'NO'

        # Calculate values
        total_bought = float(closed_pos.get('totalBought', 0))
        avg_price = float(closed_pos.get('avgPrice', 0))
        tokens_held = total_bought / avg_price if avg_price > 0 else 0
        pnl_pct = (pnl / total_bought * 100) if total_bought > 0 else 0

        # Map winning_outcome to string
        winning_outcome_str = 'YES' if pair['winning_outcome'] == 1 else 'NO'

        query = text("""
            INSERT INTO resolved_positions (
                user_id,
                market_id,
                condition_id,
                market_title,
                outcome,
                token_id,
                tokens_held,
                total_cost,
                avg_buy_price,
                winning_outcome,
                is_winner,
                resolved_at,
                pnl,
                pnl_percentage,
                gross_value,
                net_value,
                status,
                created_at
            ) VALUES (
                :user_id,
                :market_id,
                :condition_id,
                :title,
                :outcome,
                :token_id,
                :tokens_held,
                :total_cost,
                :avg_price,
                :winning_outcome,
                :is_winner,
                :resolved_at,
                :pnl,
                :pnl_pct,
                :gross,
                :net,
                'PENDING',
                NOW()
            )
            RETURNING id
        """)

        try:
            with self.db.connect() as conn:
                result = conn.execute(query, {
                    'user_id': pair['user_id'],
                    'market_id': pair['market_id'],
                    'condition_id': pair['condition_id'],
                    'title': pair['title'],
                    'outcome': outcome_str,
                    'token_id': closed_pos.get('asset', ''),
                    'tokens_held': tokens_held,
                    'total_cost': total_bought,
                    'avg_price': avg_price,
                    'winning_outcome': winning_outcome_str,
                    'is_winner': is_winner,
                    'resolved_at': pair['resolution_date'],
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'gross': total_bought + pnl,
                    'net': total_bought + pnl,
                })
                conn.commit()
                position_id = result.fetchone()[0]
                logger.debug(f"✅ Inserted resolved_position #{position_id}")
                return position_id
        except Exception as e:
            logger.error(f"❌ Database insert error: {e}", exc_info=True)
            raise

    async def send_notification(self, user_id: int, closed_pos: Dict, market_title: str, resolution_status: str = 'RESOLVED'):
        """Send Telegram notification about resolved position"""
        pnl = float(closed_pos.get('realizedPnl', 0))
        is_win = pnl > 0

        emoji = "🎉" if is_win else "😔"
        result = "WON" if is_win else "LOST"

        # Use market title from pair (more reliable than API)
        title = market_title
        if len(title) > 80:
            title = title[:77] + "..."

        outcome = closed_pos.get('outcome', 'Unknown')

        # Differentiate message for PROPOSED vs RESOLVED
        if resolution_status == 'PROPOSED':
            status_text = "Market Proposed (Extreme Prices)"
            note = "\n⚠️ Market status: PROPOSED (prices indicate resolution)"
        else:
            status_text = "Market Resolved!"
            note = ""

        message = f"{emoji} **{status_text}**\n\n"
        message += f"📊 {title}\n\n"
        message += f"✅ Outcome: **{outcome}**\n"
        message += f"💰 You {result}: **${abs(pnl):.2f}**\n"

        if is_win:
            message += f"\n🎁 Profit: +${pnl:.2f}\n"
            message += f"💵 Position auto-closed\n"
        else:
            message += f"\n📉 Loss: -${abs(pnl):.2f}\n"

        message += note
        message += f"\n📈 View history: /positions"

        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='Markdown'
            )
            logger.debug(f"📨 Sent notification to user {user_id}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to send notification to {user_id}: {e}")
            # Don't raise - continue processing other users


async def main():
    """Entry point"""
    try:
        worker = ResolutionWorker()
        await worker.run()
        logger.info("✅ Worker completed successfully")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Worker failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
