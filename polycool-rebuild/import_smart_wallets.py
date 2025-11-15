#!/usr/bin/env python3
"""
Import smart wallets from CSV into database using project infrastructure
"""

import asyncio
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.database.connection import init_db, close_db, get_db
from core.database.models import WatchedAddress
from sqlalchemy import select


async def import_smart_wallets():
    """Import smart wallets from CSV into database"""

    csv_path = project_root / "telegram_bot" / "utils" / "smart_wallets_final_analysis - smart_wallets_final_analysis.csv"

    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}")
        return

    print("📊 Reading smart wallets CSV...")

    # Parse CSV
    wallets_data = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                address = row['Adresse'].strip()
                if not address.startswith('0x'):
                    continue

                smartscore = float(row['Smartscore']) if row['Smartscore'] else 0.0
                win_rate = float(row['Win Rate']) if row['Win Rate'] else 0.0
                markets = int(float(row['Markets'])) if row['Markets'] else 0
                realized_pnl = float(row['Realized PnL']) if row['Realized PnL'] else 0.0

                bucket_smart = row.get('Bucket smart', '').strip()
                name = f"Smart Trader ({bucket_smart})" if bucket_smart else f"Smart Trader {address[:8]}..."

                wallets_data.append({
                    'address': address,
                    'name': name,
                    'risk_score': smartscore,
                    'total_trades': markets,
                    'win_rate': win_rate,
                    'total_volume': realized_pnl
                })

            except Exception as e:
                print(f"⚠️ Error parsing row: {e}")
                continue

    print(f"✅ Parsed {len(wallets_data)} smart wallets from CSV")

    # Initialize database connection
    print("🔄 Initializing database connection...")
    await init_db()

    try:
        # Import in batches
        batch_size = 50
        total_imported = 0

        async with get_db() as db:
            for i in range(0, len(wallets_data), batch_size):
                batch = wallets_data[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(wallets_data) + batch_size - 1) // batch_size

                print(f"📤 Importing batch {batch_num}/{total_batches} ({len(batch)} wallets)...")

                for wallet_data in batch:
                    # Check if wallet already exists using ORM query
                    result = await db.execute(
                        select(WatchedAddress).where(
                            WatchedAddress.address == wallet_data['address']
                        )
                    )
                    existing_wallet = result.scalar_one_or_none()

                    if existing_wallet:
                        # Update existing wallet
                        existing_wallet.name = wallet_data['name']
                        existing_wallet.risk_score = wallet_data['risk_score']
                        existing_wallet.total_trades = wallet_data['total_trades']
                        existing_wallet.win_rate = wallet_data['win_rate']
                        existing_wallet.total_volume = wallet_data['total_volume']
                        existing_wallet.updated_at = datetime.utcnow()
                        existing_wallet.is_active = True
                    else:
                        # Create new wallet
                        wallet = WatchedAddress(
                            address=wallet_data['address'],
                            blockchain='polygon',
                            address_type='smart_wallet',
                            name=wallet_data['name'],
                            risk_score=wallet_data['risk_score'],
                            is_active=True,
                            total_trades=wallet_data['total_trades'],
                            win_rate=wallet_data['win_rate'],
                            total_volume=wallet_data['total_volume'],
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                        db.add(wallet)

                # Commit batch
                await db.commit()
                total_imported += len(batch)

                if batch_num % 10 == 0 or batch_num == total_batches:
                    print(f"✅ Progress: {total_imported}/{len(wallets_data)} wallets processed")

        print(f"🎉 Successfully imported/updated {total_imported} smart wallets!")

        # Verify import
        async with get_db() as db:
            result = await db.execute(
                select(WatchedAddress).where(
                    WatchedAddress.address_type == 'smart_wallet'
                )
            )
            total_smart_wallets = len(result.scalars().all())

            print(f"📊 Total smart wallets in database: {total_smart_wallets}")

            # Show top 5 by risk score
            result = await db.execute(
                select(WatchedAddress)
                .where(WatchedAddress.address_type == 'smart_wallet')
                .order_by(WatchedAddress.risk_score.desc())
                .limit(5)
            )
            top_wallets = result.scalars().all()

            print("\n🏆 Top 5 Smart Wallets by Risk Score:")
            for i, wallet in enumerate(top_wallets, 1):
                print(f"{i}. {wallet.name} (Score: {wallet.risk_score:.2f}, Win Rate: {wallet.win_rate:.1%})")

    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(import_smart_wallets())
