"""
DipDup Indexer Entry Point
Indexes Conditional Tokens on Polygon and stores fills/transactions in subsquid_* tables.
"""

import sys
import logging
from pathlib import Path

# Ensure handlers directory is in Python path
handlers_dir = Path(__file__).parent / "handlers"
sys.path.insert(0, str(handlers_dir.parent))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


def main():
    """Main entry point - delegates to DipDup"""
    try:
        logger.info("🚀 Starting DipDup on-chain indexer...")
        
        # Validate environment
        import os
        if not os.getenv("EXPERIMENTAL_SUBSQUID"):
            raise RuntimeError(
                "❌ EXPERIMENTAL_SUBSQUID feature flag not enabled. "
                "Set EXPERIMENTAL_SUBSQUID=true to proceed."
            )
        
        logger.info("✅ Feature flag validated")
        
        # DipDup CLI will be invoked by: dipdup run
        # This script validates prerequisites only
        
        logger.info("✅ All prerequisites validated. Ready for: dipdup run")
        
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
