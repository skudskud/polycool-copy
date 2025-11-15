"""
Backfill Event Parents Script
Creates parent event markets for existing event_ids in the database
"""
import asyncio
import os
from infrastructure.config.settings import settings
from core.database.connection import get_db
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


async def backfill_event_parents():
    """
    Create parent event markets for all existing event_ids
    """
    logger.info("🔄 Starting event parents backfill...")

    # Initialize database
    from core.database.connection import init_db
    await init_db()
    logger.info("✅ Database initialized")

    # Get all unique event_ids from existing markets
    async with get_db() as db:
        from sqlalchemy import text
        result = await db.execute(text("""
            SELECT DISTINCT event_id, event_title, event_slug,
                   COUNT(*) as market_count,
                   SUM(volume) as total_volume,
                   SUM(liquidity) as total_liquidity
            FROM markets
            WHERE event_id IS NOT NULL
            AND event_title IS NOT NULL
            GROUP BY event_id, event_title, event_slug
            ORDER BY market_count DESC
        """))

        events_data = result.fetchall()

    logger.info(f"📊 Found {len(events_data)} unique events to create")

    # Create parent event markets
    created_count = 0
    for event_data in events_data:
        event_id = str(event_data[0])
        event_title = event_data[1]
        event_slug = event_data[2] or f"event-{event_id}"
        market_count = event_data[3]
        total_volume = float(event_data[4] or 0)
        total_liquidity = float(event_data[5] or 0)

        try:
            async with get_db() as db_tx:
                await db_tx.execute(text("""
                    INSERT INTO markets (
                        id, source, title, description, category,
                        outcomes, outcome_prices, events,
                        is_event_market, parent_event_id,
                        volume, liquidity, last_trade_price,
                        clob_token_ids, condition_id,
                        is_resolved, resolved_outcome, resolved_at,
                        start_date, end_date, is_active,
                        event_id, event_slug, event_title,
                        created_at, updated_at
                    ) VALUES (
                        :id, 'poll', :title, :description, 'Events',
                        '["Various"]', '[0.5]', '[]',
                        true, null,
                        :volume, :liquidity, null,
                        null, null,
                        false, null, null,
                        null, null, true,
                        :event_id, :event_slug, :event_title,
                        now(), now()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        volume = EXCLUDED.volume,
                        liquidity = EXCLUDED.liquidity,
                        event_slug = EXCLUDED.event_slug,
                        event_title = EXCLUDED.event_title,
                        updated_at = now()
                """), {
                    'id': event_id,
                    'title': event_title,
                    'description': f"Event with {market_count} markets",
                    'volume': total_volume,
                    'liquidity': total_liquidity,
                    'event_id': event_id,
                    'event_slug': event_slug,
                    'event_title': event_title
                })

            created_count += 1
            logger.debug(f"✅ Created parent event: {event_title} ({market_count} markets)")

        except Exception as e:
            logger.error(f"❌ Failed to create parent event {event_id}: {e}")

    # Update child markets to have correct parent_event_id
    updated_count = 0
    for event_data in events_data:
        event_id = str(event_data[0])

        try:
            async with get_db() as db_tx:
                result = await db_tx.execute(text("""
                    UPDATE markets
                    SET parent_event_id = :event_id,
                        is_event_market = false,
                        updated_at = now()
                    WHERE event_id = :event_id
                    AND id != :event_id
                    AND (parent_event_id IS NULL OR parent_event_id != :event_id)
                """), {'event_id': event_id})

                update_count = result.rowcount
                updated_count += update_count
                if update_count > 0:
                    logger.debug(f"✅ Updated {update_count} child markets for event {event_id}")

        except Exception as e:
            logger.error(f"❌ Failed to update child markets for event {event_id}: {e}")

    logger.info(f"🎉 Backfill completed: {created_count} parent events created, {updated_count} child markets updated")


if __name__ == "__main__":
    # Set SKIP_DB to false to ensure database connection
    os.environ["SKIP_DB"] = "false"

    asyncio.run(backfill_event_parents())
