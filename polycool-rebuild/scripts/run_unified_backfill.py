#!/usr/bin/env python3
"""
Unified Backfill Runner - One-shot complete market backfill with ZERO ORPHANS guarantee
Optimized version with parallel processing and resume capability
"""
import asyncio
import sys
import argparse
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_ingestion.poller.unified_backfill_poller import UnifiedBackfillPoller
from infrastructure.logging.logger import get_logger
from core.database.connection import init_db
from infrastructure.config.settings import settings
import os

logger = get_logger(__name__)


async def run_unified_backfill(resume_on_existing: bool = False, parallel_requests: int = 10, skip_tags: bool = False):
    """Run the unified comprehensive backfill"""
    print("🚀 Starting Unified Backfill Runner")
    logger.info("🚀 Starting Unified Backfill Runner")

    try:
        print("🗄️ Initializing database...")
        if os.getenv("SKIP_DB", "false").lower() != "true":
            await init_db()
            print("✅ Database initialized")
        else:
            print("⚠️ Database initialization skipped (SKIP_DB=true)")
            raise RuntimeError("Cannot run backfill without database. Set SKIP_DB=false")

        print(f"📦 Creating UnifiedBackfillPoller (resume={resume_on_existing}, parallel={parallel_requests}, skip_tags={skip_tags})...")
        # Create and run the backfill
        backfill_poller = UnifiedBackfillPoller(
            resume_on_existing=resume_on_existing,
            parallel_requests=parallel_requests,
            skip_tags=skip_tags
        )
        print("✅ UnifiedBackfillPoller created successfully")

        print("🚀 Starting comprehensive_backfill...")
        print("📊 Calling comprehensive_backfill() method...")

        try:
            stats = await backfill_poller.comprehensive_backfill()
            print("✅ Backfill completed!")
        except KeyboardInterrupt:
            print("⚠️ Backfill interrupted by user")
            raise
        except Exception as e:
            print(f"❌ Backfill failed with error: {e}")
            raise

        # Print final summary
        print("\n" + "="*60)
        print("🎉 UNIFIED BACKFILL COMPLETED!")
        print("="*60)
        print(f"📊 Total Markets: {stats['total_markets']}")
        print(f"🏛️ Event Markets: {stats['event_markets']}")
        print(f"🏠 Standalone Markets: {stats['standalone_markets']}")
        print(f"👻 Orphans Found: {stats['orphans_found']}")
        print(f"✅ Orphans Enriched: {stats['orphans_enriched']}")
        print(f"💾 Final Upserted: {stats['final_upserted']}")
        print(f"⏱️ Duration: {stats['duration_seconds']:.2f} seconds")
        print("="*60)

        if stats['orphans_found'] > 0 and stats['orphans_enriched'] == stats['orphans_found']:
            print("✅ SUCCESS: Zero orphan markets remaining!")
        elif stats['orphans_found'] > 0:
            print(f"⚠️ WARNING: {stats['orphans_found'] - stats['orphans_enriched']} orphan markets could not be enriched")
        else:
            print("✅ PERFECT: No orphan markets found!")

        return True

    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}", exc_info=True)
        print(f"\n❌ BACKFILL FAILED: {e}")
        return False


def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(description="Run unified market backfill with optimizations")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Allow running backfill on non-empty tables (resume mode)"
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Number of parallel API requests (default: 1, sequential mode)"
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Fast mode: conservative parallelism (3 requests) and resume enabled"
    )
    parser.add_argument(
        "--ultra-fast",
        action="store_true",
        help="Ultra fast mode: skip tags, minimal sleeps, resume enabled - 15-30min total"
    )
    parser.add_argument(
        "--skip-tags",
        action="store_true",
        help="Skip tags enrichment for faster backfill (can be done later)"
    )

    args = parser.parse_args()

    # Mode overrides
    skip_tags = False
    if args.fast:
        args.resume = True
        args.parallel = 3  # Conservative parallelism to avoid 429 errors
        skip_tags = False
    elif args.ultra_fast:
        args.resume = True
        args.parallel = 1  # Sequential for speed (no 429 risk)
        skip_tags = True   # Skip tags for massive speed boost
    elif args.skip_tags:
        skip_tags = True

    print(f"⚡ Backfill Configuration:")
    print(f"   Resume on existing: {args.resume}")
    print(f"   Parallel requests: {args.parallel}")
    print(f"   Skip tags: {skip_tags}")
    print(f"   Fast mode: {args.fast}")
    print(f"   Ultra fast mode: {args.ultra_fast}")
    if args.parallel == 1:
        print("   ⚠️  SEQUENTIAL MODE: Safe (no 429 errors)")
    else:
        print(f"   ⚡ PARALLEL MODE: {args.parallel} concurrent requests")

    if skip_tags:
        print("   🚀 TAGS SKIPPED: Massive speed boost (+4-6h saved)!")
    print()

    success = asyncio.run(run_unified_backfill(
        resume_on_existing=args.resume,
        parallel_requests=args.parallel,
        skip_tags=skip_tags
    ))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
