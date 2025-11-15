#!/usr/bin/env python3
"""
Debug backfill script - step by step testing
"""
import sys
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("🔍 Starting debug script...")

try:
    print("📦 Importing logger...")
    from infrastructure.logging.logger import get_logger
    print("✅ Logger imported")

    print("📦 Creating logger...")
    logger = get_logger(__name__)
    print("✅ Logger created")

    print("📦 Importing UnifiedBackfillPoller...")
    from data_ingestion.poller.unified_backfill_poller import UnifiedBackfillPoller
    print("✅ UnifiedBackfillPoller imported")

    print("📦 Testing poller creation...")
    poller = UnifiedBackfillPoller()
    print("✅ Poller created successfully")

    print("🎉 All imports and instantiation successful!")
    print("The issue must be in the async execution or database connection")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
