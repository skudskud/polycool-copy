#!/usr/bin/env python3
"""
Sync Smart Wallet Markets
Fetches missing markets from Polymarket API and adds them to our database
"""
import os
import sys
import asyncio
import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SubsquidMarketPoll, db_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
GAMMA_API_URL = "https://gamma-api.polymarket.com"


async def fetch_market_from_polymarket(condition_id: str) -> dict:
    """
    Fetch market data from Polymarket Gamma API by condition_id

    Args:
        condition_id: Market condition ID (0x...)

    Returns:
        Market data dict or None if not found
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to get market by condition_id
            url = f"{GAMMA_API_URL}/markets/{condition_id}"
            response = await client.get(url)

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Market {condition_id[:10]}... not found on Polymarket (HTTP {response.status_code})")
                return None

    except Exception as e:
        logger.error(f"Error fetching market {condition_id[:10]}...: {e}")
        return None


def market_api_to_db(api_data: dict) -> dict:
    """
    Transform Polymarket API response to our database format

    Args:
        api_data: Raw API response

    Returns:
        Dict ready for database insertion
    """
    try:
        # Parse end date
        end_date = None
        if api_data.get('end_date_iso'):
            try:
                end_date = datetime.fromisoformat(api_data['end_date_iso'].replace('Z', '+00:00'))
            except:
                pass

        # Parse outcomes
        outcomes = []
        outcome_prices = []
        tokens = api_data.get('tokens', [])

        for token in tokens:
            outcomes.append(token.get('outcome', ''))
            # We don't have real-time prices from the API, use 0.5 as default
            outcome_prices.append(0.5)

        market_data = {
            'id': api_data.get('id'),
            'condition_id': api_data.get('condition_id'),
            'question': api_data.get('question'),
            'slug': api_data.get('slug'),
            'status': api_data.get('status', 'unknown'),
            'active': api_data.get('active', False),
            'closed': api_data.get('closed', False),
            'archived': api_data.get('archived', False),
            'accepting_orders': api_data.get('accepting_orders', True),
            'resolved_at': None,
            'winner': api_data.get('winner'),
            'resolution_source': api_data.get('resolution_source'),
            'volume': float(api_data.get('volume', 0)),
            'liquidity': float(api_data.get('liquidity', 0)),
            'outcomes': outcomes,
            'outcome_prices': str(outcome_prices),
            'description': api_data.get('description'),
            'icon': api_data.get('image'),
            'category': api_data.get('category'),
            'end_date': end_date,
            'tradeable': api_data.get('accepting_orders', True),
            'tokens': tokens,
            'grouped': api_data.get('grouped_markets', []) != [],
            'last_updated': datetime.now(timezone.utc)
        }

        return market_data

    except Exception as e:
        logger.error(f"Error transforming market data: {e}")
        return None


async def sync_missing_markets():
    """
    Find markets in smart_wallet_trades that are missing from markets table
    and fetch them from Polymarket API
    """
    logger.info("🔍 Finding missing markets...")

    # Get missing market IDs
    with db_manager.get_session() as db:
        result = db.execute(text("""
            SELECT DISTINCT swt.market_id, swt.market_question
            FROM smart_wallet_trades swt
            WHERE NOT EXISTS (
                SELECT 1 FROM subsquid_markets_poll m
                WHERE m.condition_id = swt.market_id
            )
        """))
        missing_markets = result.fetchall()

    logger.info(f"📊 Found {len(missing_markets)} missing markets")

    if not missing_markets:
        logger.info("✅ All smart wallet markets are already in database!")
        return

    # Fetch and add missing markets
    added = 0
    failed = 0
    skipped = 0

    for market_id, question in missing_markets:
        try:
            logger.info(f"🔄 Fetching market {market_id[:10]}... ({question[:50] if question else 'N/A'}...)")

            # Fetch from Polymarket
            api_data = await fetch_market_from_polymarket(market_id)

            if not api_data:
                logger.warning(f"⚠️ Market {market_id[:10]}... not found on Polymarket API")
                skipped += 1
                continue

            # Transform to DB format
            market_data = market_api_to_db(api_data)

            if not market_data:
                logger.warning(f"⚠️ Could not transform market {market_id[:10]}...")
                failed += 1
                continue

            # Insert into database
            with db_manager.get_session() as db:
                # Check if already exists (race condition)
                existing = db.query(SubsquidMarketPoll).filter(SubsquidMarketPoll.condition_id == market_id).first()
                if existing:
                    logger.info(f"⏭️ Market {market_id[:10]}... already exists, skipping")
                    skipped += 1
                    continue

                market = SubsquidMarketPoll(**market_data)
                db.add(market)
                db.commit()

                logger.info(f"✅ Added market {market_id[:10]}... | {market_data['question'][:50]}...")
                added += 1

            # Rate limiting
            await asyncio.sleep(0.2)

        except Exception as e:
            logger.error(f"❌ Error processing market {market_id[:10]}...: {e}")
            failed += 1
            continue

    logger.info("\n" + "="*80)
    logger.info(f"📊 SYNC COMPLETE:")
    logger.info(f"   ✅ Added:   {added}")
    logger.info(f"   ⚠️ Skipped: {skipped}")
    logger.info(f"   ❌ Failed:  {failed}")
    logger.info(f"   📈 Total:   {len(missing_markets)}")
    logger.info("="*80)


if __name__ == "__main__":
    asyncio.run(sync_missing_markets())
