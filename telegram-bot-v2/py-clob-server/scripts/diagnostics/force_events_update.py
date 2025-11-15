#!/usr/bin/env python3
"""
Force update markets from Events API to populate event_id, event_slug, event_title
"""
import sys
import os
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.services.market_updater_service import MarketUpdaterService
from core.persistence.market_repository import MarketRepository
from database import SessionLocal
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GAMMA_API_URL = "https://gamma-api.polymarket.com"

async def main():
    print("=" * 80)
    print("🔥 FORCE UPDATE: Fetching markets from Events API")
    print("=" * 80)
    
    session = SessionLocal()
    repository = MarketRepository(session)
    service = MarketUpdaterService(repository, GAMMA_API_URL)
    
    try:
        # Fetch events from Gamma API
        print("\n1️⃣ Fetching events from Gamma API...")
        events = await service.fetch_events_from_gamma(max_pages=10)
        print(f"✅ Fetched {len(events)} events")
        
        # Extract markets from events
        print("\n2️⃣ Extracting markets from events...")
        markets = service.extract_markets_from_events(events)
        print(f"✅ Extracted {len(markets)} markets")
        
        # Check Fed markets
        fed_markets = [m for m in markets if 'fed' in m.get('question', '').lower() and 'october' in m.get('question', '').lower()]
        print(f"\n3️⃣ Found {len(fed_markets)} Fed October markets:")
        for m in fed_markets[:5]:
            print(f"   - {m.get('question', 'N/A')[:60]}...")
            print(f"     Event ID: {m.get('event_id')}")
            print(f"     Event Slug: {m.get('event_slug')}")
            print(f"     Event Title: {m.get('event_title')}")
        
        # Transform to DB format
        print("\n4️⃣ Transforming to DB format...")
        db_markets = []
        for market_data in markets:
            try:
                db_market = service.transform_gamma_to_db(market_data)
                db_markets.append(db_market)
            except Exception as e:
                logger.error(f"Error transforming market {market_data.get('id')}: {e}")
        
        print(f"✅ Transformed {len(db_markets)} markets")
        
        # Bulk upsert
        print("\n5️⃣ Upserting to database...")
        stats = repository.bulk_upsert(db_markets)
        print(f"✅ Upsert complete: {stats}")
        
        # Verify Fed markets in DB
        print("\n6️⃣ Verifying Fed markets in DB...")
        from sqlalchemy import text
        result = session.execute(text("""
            SELECT id, question, event_id, event_slug, event_title
            FROM markets
            WHERE question ILIKE '%fed%october%'
            AND active = true
            ORDER BY volume DESC
            LIMIT 5;
        """))
        
        db_fed_markets = result.fetchall()
        print(f"✅ Found {len(db_fed_markets)} Fed markets in DB:")
        for m in db_fed_markets:
            print(f"   Market {m[0]}: {m[1][:50]}...")
            print(f"     Event ID: {m[2]}")
            print(f"     Event Slug: {m[3]}")
            print(f"     Event Title: {m[4]}")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()
    
    print("\n" + "=" * 80)
    print("✅ Force update complete!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())

