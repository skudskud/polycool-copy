#!/usr/bin/env python3
"""
Manual resolution scan with full debug output
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

async def run_scan():
    from core.services.market_resolution_monitor import MarketResolutionMonitor
    
    print("🔍 Starting manual resolution scan...")
    print("=" * 80)
    
    monitor = MarketResolutionMonitor()
    stats = await monitor.scan_for_resolutions(lookback_minutes=10080)  # 7 days
    
    print("=" * 80)
    print(f"✅ Scan complete: {stats}")
    
    # Check resolved_positions table
    from database import SessionLocal, ResolvedPosition
    with SessionLocal() as session:
        count = session.query(ResolvedPosition).count()
        print(f"📊 Total resolved_positions in database: {count}")
        
        if count > 0:
            latest = session.query(ResolvedPosition).order_by(ResolvedPosition.resolved_at.desc()).first()
            print(f"📋 Latest: User {latest.user_id} - {latest.outcome} in {latest.market_title[:50]}")

if __name__ == "__main__":
    asyncio.run(run_scan())

