#!/usr/bin/env python3
"""
CLI Script: Read Webhook Events
Displays webhook events from Redis bridge, including event types and payloads.
"""

import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings, validate_experimental_subsquid
from src.db.client import get_db_client, close_db_client


async def main():
    """Main entry point"""
    try:
        print("\n" + "=" * 100)
        print("🔔 SUBSQUID WEBHOOK EVENTS READER")
        print("=" * 100)

        # Validate feature flag
        validate_experimental_subsquid()
        print("✅ Feature flag validated\n")

        # Get database client
        db = await get_db_client()

        # Get webhook events
        print("📋 Recent Webhook Events (Last 20):")
        print("-" * 100)
        events = await db.get_webhook_events(limit=20)

        if events:
            print(f"{'#':<3} {'Market ID':<20} {'Event':<30} {'Updated':<25} {'ID':<6}")
            print("-" * 100)

            for i, event in enumerate(events, 1):
                market_id = event.get('market_id', 'N/A')[:18]
                event_type = event.get('event', 'N/A')[:28]
                updated = str(event.get('updated_at', 'N/A'))[:22]
                event_id = str(event.get('id', 'N/A'))[:4]

                print(f"{i:<3} {market_id:<20} {event_type:<30} {updated:<25} {event_id:<6}")

            # Detailed view of first 5 events
            print("\n📌 Detailed Events (First 5):")
            print("-" * 100)

            for i, event in enumerate(events[:5], 1):
                print(f"\n  [{i}] Event ID: {event.get('id', 'N/A')}")
                print(f"      Market:  {event.get('market_id', 'N/A')}")
                print(f"      Type:    {event.get('event', 'N/A')}")
                print(f"      Time:    {event.get('updated_at', 'N/A')}")

                # Pretty-print payload
                payload = event.get('payload', {})
                if payload:
                    print(f"      Payload: {json.dumps(payload, indent=16)}")
        else:
            print("  ⚠️  No webhook events found")

        # Event type summary
        print("\n📊 Event Type Summary:")
        print("-" * 100)
        if events:
            event_types = {}
            for event in events:
                event_type = event.get('event', 'unknown')
                event_types[event_type] = event_types.get(event_type, 0) + 1

            for event_type, count in sorted(event_types.items(), key=lambda x: x[1], reverse=True):
                print(f"  {event_type:<40} {count:>5} events")

        # Summary
        print("\n" + "=" * 100)
        print("✅ Read complete")
        print("=" * 100 + "\n")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        await close_db_client()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Interrupted")
        sys.exit(0)
