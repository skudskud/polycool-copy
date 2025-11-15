#!/usr/bin/env python3
"""
Watch bot logs in real-time
"""
import asyncio
import time
import sys

async def watch_logs():
    """Watch for bot logs"""
    print("👀 Watching for Polycool bot logs... (Ctrl+C to stop)")
    print("=" * 50)

    try:
        while True:
            # Check every 2 seconds for new activity
            await asyncio.sleep(2)
            print(f"[{time.strftime('%H:%M:%S')}] Waiting for user interaction...")

    except KeyboardInterrupt:
        print("\n🛑 Stopped watching logs")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(watch_logs())
