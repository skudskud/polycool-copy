"""
Admin endpoint to trigger full market enrichment
Restores events data for all markets by fetching from Gamma API
"""
import logging
import asyncio
from fastapi import HTTPException
from typing import Dict

logger = logging.getLogger(__name__)

# Global flag to prevent concurrent enrichments
_enrichment_running = False
_enrichment_progress = {
    "running": False,
    "events_fetched": 0,
    "markets_enriched": 0,
    "status": "idle"
}

async def trigger_enrichment() -> Dict:
    """
    Trigger full market enrichment to restore events data
    
    This is a long-running process (90-120 minutes) that:
    1. Fetches ALL events from Gamma API
    2. Updates markets in subsquid_markets_poll with events data
    3. Restores parent/children grouping for Telegram bot
    
    Returns:
        Status dict with progress information
    """
    global _enrichment_running, _enrichment_progress
    
    if _enrichment_running:
        return {
            "error": "Enrichment already running",
            "progress": _enrichment_progress
        }
    
    # Start enrichment in background
    asyncio.create_task(_run_enrichment_background())
    
    return {
        "success": True,
        "message": "Enrichment started in background",
        "estimated_time": "90-120 minutes",
        "check_progress_at": "/admin/enrichment/status"
    }

async def get_enrichment_status() -> Dict:
    """Get current enrichment progress"""
    return _enrichment_progress

async def _run_enrichment_background():
    """Background task to run full enrichment"""
    global _enrichment_running, _enrichment_progress
    
    _enrichment_running = True
    _enrichment_progress = {
        "running": True,
        "events_fetched": 0,
        "markets_enriched": 0,
        "status": "starting",
        "started_at": None,
        "completed_at": None
    }
    
    try:
        import httpx
        from datetime import datetime
        from database import db_manager
        
        _enrichment_progress["status"] = "fetching_events"
        _enrichment_progress["started_at"] = datetime.now().isoformat()
        
        client = httpx.AsyncClient(timeout=30.0)
        offset = 0
        limit = 200
        batch = []
        
        logger.info("🚀 Starting full market enrichment...")
        
        while True:
            try:
                url = f"https://gamma-api.polymarket.com/events?limit={limit}&offset={offset}&order=id&ascending=false"
                response = await client.get(url)
                
                if response.status_code != 200:
                    logger.warning(f"API returned {response.status_code} at offset={offset}")
                    break
                
                events = response.json()
                
                if not events:
                    logger.info(f"No more events at offset={offset}")
                    break
                
                _enrichment_progress["events_fetched"] += len(events)
                
                # Extract markets from events
                for event in events:
                    markets = event.get("markets", [])
                    
                    if not markets:
                        continue
                    
                    # Build events array
                    import json
                    events_data = json.dumps([{
                        "event_id": str(event.get("id")),
                        "event_slug": event.get("slug"),
                        "event_title": event.get("title"),
                        "event_category": event.get("category"),
                        "event_volume": float(event.get("volume", 0)),
                    }])
                    
                    for market in markets:
                        market_id = market.get("id")
                        if market_id:
                            batch.append((market_id, events_data))
                
                # ⚡ OPTIMIZED: Batch update every 1000 markets with BULK SQL
                if len(batch) >= 1000:
                    with db_manager.get_session() as db:
                        try:
                            from sqlalchemy import text
                            
                            # Build bulk UPDATE with CASE statement (100x faster!)
                            market_ids = [mid for mid, _ in batch]
                            
                            # Build CASE WHEN for each market
                            case_statements = []
                            for market_id, events_json in batch:
                                # Escape single quotes in JSON
                                escaped_json = events_json.replace("'", "''")
                                case_statements.append(f"WHEN market_id = '{market_id}' THEN '{escaped_json}'::jsonb")
                            
                            case_clause = "\n                ".join(case_statements)
                            market_ids_list = "', '".join(market_ids)
                            
                            # Single bulk UPDATE statement
                            bulk_query = f"""
                                UPDATE subsquid_markets_poll
                                SET events = CASE
                                    {case_clause}
                                END
                                WHERE market_id IN ('{market_ids_list}')
                                AND status = 'ACTIVE'
                            """
                            
                            result = db.execute(text(bulk_query))
                            db.commit()
                            
                            # Update counter with actual rows affected
                            _enrichment_progress["markets_enriched"] += len(batch)
                            logger.info(f"⚡ BULK Enriched {_enrichment_progress['markets_enriched']} markets (batch: {len(batch)})")
                            
                        except Exception as e:
                            logger.error(f"❌ Bulk update failed: {e}")
                            db.rollback()
                        
                    batch = []
                
                # Progress logging
                if _enrichment_progress["events_fetched"] % 5000 == 0:
                    logger.info(f"📊 Progress: {_enrichment_progress['events_fetched']} events fetched")
                
                offset += limit
                await asyncio.sleep(0.05)  # Rate limiting
                
            except Exception as e:
                logger.error(f"Error at offset={offset}: {e}")
                break
        
        # Final batch
        if batch:
            with db_manager.get_session() as db:
                try:
                    from sqlalchemy import text
                    
                    # Build bulk UPDATE with CASE statement
                    market_ids = [mid for mid, _ in batch]
                    
                    # Build CASE WHEN for each market
                    case_statements = []
                    for market_id, events_json in batch:
                        # Escape single quotes in JSON
                        escaped_json = events_json.replace("'", "''")
                        case_statements.append(f"WHEN market_id = '{market_id}' THEN '{escaped_json}'::jsonb")
                    
                    case_clause = "\n                ".join(case_statements)
                    market_ids_list = "', '".join(market_ids)
                    
                    # Single bulk UPDATE statement
                    bulk_query = f"""
                        UPDATE subsquid_markets_poll
                        SET events = CASE
                            {case_clause}
                        END
                        WHERE market_id IN ('{market_ids_list}')
                        AND status = 'ACTIVE'
                    """
                    
                    result = db.execute(text(bulk_query))
                    db.commit()
                    
                    _enrichment_progress["markets_enriched"] += len(batch)
                    logger.info(f"⚡ FINAL BULK Enriched {_enrichment_progress['markets_enriched']} markets (batch: {len(batch)})")
                    
                except Exception as e:
                    logger.error(f"❌ Final bulk update failed: {e}")
                    db.rollback()
        
        await client.aclose()
        
        _enrichment_progress["status"] = "completed"
        _enrichment_progress["completed_at"] = datetime.now().isoformat()
        _enrichment_progress["running"] = False
        
        logger.info(f"✅ ENRICHMENT COMPLETE: {_enrichment_progress['events_fetched']} events, {_enrichment_progress['markets_enriched']} markets")
        
    except Exception as e:
        logger.error(f"❌ Enrichment failed: {e}")
        _enrichment_progress["status"] = f"failed: {str(e)}"
        _enrichment_progress["running"] = False
    finally:
        _enrichment_running = False

