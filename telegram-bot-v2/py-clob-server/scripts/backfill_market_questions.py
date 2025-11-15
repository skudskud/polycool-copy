#!/usr/bin/env python3
"""
Backfill market questions for existing smart_wallet_trades
Updates trades that have NULL or empty market_question
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def backfill_market_questions():
    """Update existing trades with market titles"""
    try:
        from database import db_manager
        from core.services.market_data_layer import MarketDataLayer
        import logging

        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)

        # Initialize market data layer
        use_subsquid = os.getenv('USE_SUBSQUID_MARKETS', 'false').lower() == 'true'
        market_data_layer = MarketDataLayer(use_subsquid=use_subsquid)

        logger.info("🚀 Starting market question backfill...")

        with db_manager.get_session() as db:
            # Find trades with missing market questions
            from core.persistence.models import SmartWalletTrade
            from sqlalchemy import or_

            trades_to_update = db.query(SmartWalletTrade).filter(
                or_(
                    SmartWalletTrade.market_question.is_(None),
                    SmartWalletTrade.market_question == ""
                )
            ).all()

            logger.info(f"📊 Found {len(trades_to_update)} trades to update")

            updated_count = 0
            for trade in trades_to_update:
                try:
                    # Get market title
                    market = market_data_layer.get_market_by_id(trade.market_id)
                    if market and 'title' in market:
                        trade.market_question = market['title']
                        updated_count += 1
                        logger.debug(f"✅ Updated trade {trade.id[:16]}... with title: {market['title']}")
                    else:
                        logger.warning(f"⚠️ No title found for market {trade.market_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to update trade {trade.id}: {e}")

            # Commit changes
            if updated_count > 0:
                db.commit()
                logger.info(f"✅ Backfill complete: {updated_count} trades updated")
            else:
                logger.info("ℹ️ No trades needed updating")

        return True

    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}")
        return False

if __name__ == "__main__":
    success = backfill_market_questions()
    sys.exit(0 if success else 1)
