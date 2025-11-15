#!/usr/bin/env python3
"""
One-time cleanup script to remove non-user-position markets from watched_markets.
Run this once during deployment to clean up existing data.
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.services.watched_markets_service import get_watched_markets_service

async def main():
    print("🧹 Starting one-time watched_markets cleanup...")
    service = get_watched_markets_service()
    removed = await service.cleanup_inactive_watched_markets()
    print(f"✅ Cleanup complete: removed {removed} inactive markets")

if __name__ == "__main__":
    asyncio.run(main())
