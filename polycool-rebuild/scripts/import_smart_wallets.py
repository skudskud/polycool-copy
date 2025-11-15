"""
Import Smart Wallets from CSV
Reads smart_wallets_final_analysis.csv and creates entries in watched_addresses
with address_type='smart_trader'
"""
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone

import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database.connection import get_db
from core.database.models import WatchedAddress
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def parse_smartscore(smartscore_str: str) -> Optional[float]:
    """
    Parse Smartscore from CSV (can be float or empty)

    Args:
        smartscore_str: Smartscore string from CSV

    Returns:
        Float value or None if invalid
    """
    try:
        if not smartscore_str or smartscore_str.strip() == '':
            return None
        return float(smartscore_str)
    except (ValueError, TypeError):
        return None


def parse_win_rate(win_rate_str: str) -> Optional[float]:
    """
    Parse Win Rate from CSV (can be percentage or decimal)

    Args:
        win_rate_str: Win rate string from CSV

    Returns:
        Float value (0-1) or None if invalid
    """
    try:
        if not win_rate_str or win_rate_str.strip() == '':
            return None
        value = float(win_rate_str)
        # If > 1, assume it's percentage and convert
        if value > 1:
            value = value / 100.0
        return value
    except (ValueError, TypeError):
        return None


def parse_volume(volume_str: str) -> Optional[float]:
    """
    Parse volume from CSV

    Args:
        volume_str: Volume string from CSV

    Returns:
        Float value or None if invalid
    """
    try:
        if not volume_str or volume_str.strip() == '':
            return None
        return float(volume_str)
    except (ValueError, TypeError):
        return None


async def import_smart_wallets_from_csv(csv_path: str, dry_run: bool = False) -> Dict[str, int]:
    """
    Import smart wallets from CSV file

    Args:
        csv_path: Path to CSV file
        dry_run: If True, don't actually write to DB (just validate)

    Returns:
        Dict with stats: {'imported': count, 'updated': count, 'skipped': count, 'errors': count}
    """
    stats = {
        'imported': 0,
        'updated': 0,
        'skipped': 0,
        'errors': 0
    }

    csv_file = Path(csv_path)
    if not csv_file.exists():
        logger.error(f"❌ CSV file not found: {csv_path}")
        return stats

    logger.info(f"📊 Reading smart wallets from {csv_path}")

    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        logger.info(f"✅ Found {len(rows)} rows in CSV")

        async with get_db() as db:
            for idx, row in enumerate(rows, 1):
                try:
                    # Extract address (from "Adresse" column)
                    address = row.get('Adresse', '').strip()
                    if not address or not address.startswith('0x'):
                        logger.warning(f"⚠️ Row {idx}: Invalid address: {address}")
                        stats['skipped'] += 1
                        continue

                    normalized_addr = address.lower()

                    # Extract metadata
                    smartscore = parse_smartscore(row.get('Smartscore', ''))
                    win_rate = parse_win_rate(row.get('Win Rate', ''))
                    total_volume = parse_volume(row.get('Realized PnL', ''))  # Using Realized PnL as volume proxy
                    total_trades = None
                    try:
                        trades_str = row.get('Markets', '')
                        if trades_str:
                            total_trades = int(float(trades_str))
                    except (ValueError, TypeError):
                        pass

                    # Extract name (from User column - hashdive URL)
                    name = None
                    user_url = row.get('User', '')
                    if user_url and 'user_address=' in user_url:
                        # Extract address from URL for name
                        try:
                            addr_from_url = user_url.split('user_address=')[1].split('&')[0]
                            name = f"Smart Trader {addr_from_url[:10]}..."
                        except:
                            name = f"Smart Trader {normalized_addr[:10]}..."
                    else:
                        name = f"Smart Trader {normalized_addr[:10]}..."

                    # Check if already exists
                    result = await db.execute(
                        select(WatchedAddress).where(WatchedAddress.address == normalized_addr)
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        # Update existing
                        if not dry_run:
                            existing.address_type = 'smart_trader'
                            existing.is_active = True
                            if name:
                                existing.name = name
                            if smartscore is not None:
                                existing.risk_score = smartscore
                            if win_rate is not None:
                                existing.win_rate = win_rate
                            if total_volume is not None:
                                existing.total_volume = total_volume
                            if total_trades is not None:
                                existing.total_trades = total_trades
                            existing.updated_at = datetime.now(timezone.utc)
                            await db.commit()
                        stats['updated'] += 1
                        if idx % 100 == 0:
                            logger.info(f"📊 Processed {idx}/{len(rows)} rows...")
                    else:
                        # Create new
                        if not dry_run:
                            watched_addr = WatchedAddress(
                                address=normalized_addr,
                                blockchain='polygon',
                                address_type='smart_trader',
                                user_id=None,
                                name=name,
                                description=f"Smart wallet imported from CSV (Smartscore: {smartscore})",
                                risk_score=smartscore,
                                win_rate=win_rate,
                                total_volume=total_volume or 0.0,
                                total_trades=total_trades or 0,
                                is_active=True,
                                created_at=datetime.now(timezone.utc),
                                updated_at=datetime.now(timezone.utc)
                            )
                            db.add(watched_addr)
                            await db.commit()
                        stats['imported'] += 1
                        if idx % 100 == 0:
                            logger.info(f"📊 Processed {idx}/{len(rows)} rows...")

                except Exception as e:
                    logger.error(f"❌ Error processing row {idx}: {e}")
                    stats['errors'] += 1
                    continue

        logger.info(
            f"✅ Import complete: {stats['imported']} imported, "
            f"{stats['updated']} updated, {stats['skipped']} skipped, "
            f"{stats['errors']} errors"
        )

        return stats

    except Exception as e:
        logger.error(f"❌ Error reading CSV: {e}")
        stats['errors'] += 1
        return stats


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Import smart wallets from CSV')
    parser.add_argument(
        'csv_path',
        type=str,
        help='Path to smart_wallets_final_analysis.csv'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode (validate but don\'t write to DB)'
    )

    args = parser.parse_args()

    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be written to DB")

    stats = await import_smart_wallets_from_csv(args.csv_path, dry_run=args.dry_run)

    print("\n" + "="*50)
    print("Import Summary:")
    print(f"  Imported: {stats['imported']}")
    print(f"  Updated:  {stats['updated']}")
    print(f"  Skipped:  {stats['skipped']}")
    print(f"  Errors:   {stats['errors']}")
    print("="*50)


if __name__ == '__main__':
    asyncio.run(main())

