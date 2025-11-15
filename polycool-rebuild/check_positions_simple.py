#!/usr/bin/env python3
"""
Script simple pour vérifier les 3 types de positions depuis l'API Polymarket
"""
import asyncio
import aiohttp
from datetime import datetime

WALLET_ADDRESS = "0x7d47DBe915A48eE5fE1E13B35BAe76c9daed718a"

async def fetch_positions():
    """Récupérer toutes les positions depuis l'API Polymarket"""

    async with aiohttp.ClientSession() as session:
        # 1. Open positions (non resolved)
        print("=" * 80)
        print("📊 1. OPEN POSITIONS (NON RESOLVED)")
        print("=" * 80)

        try:
            url = "https://data-api.polymarket.com/positions"
            params = {
                "user": WALLET_ADDRESS,
                "sortBy": "TOKENS",
                "sortDirection": "DESC",
                "limit": 100
            }

            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    open_positions = await response.json()
                    if not isinstance(open_positions, list):
                        open_positions = open_positions.get('positions', []) if isinstance(open_positions, dict) else []

                    # Filtrer les non-resolved (redeemable = false)
                    non_resolved = [p for p in open_positions if not p.get('redeemable', False)]

                    print(f"\n✅ Total open positions (non resolved): {len(non_resolved)}\n")

                    for i, pos in enumerate(non_resolved, 1):
                        title = pos.get('title', 'Unknown')
                        outcome = pos.get('outcome', 'N/A')
                        size = pos.get('size', 0)
                        avg_price = pos.get('avgPrice', 0)
                        cur_price = pos.get('curPrice', 0)
                        pnl = pos.get('cashPnl', 0)

                        print(f"{i}. {title[:70]}...")
                        print(f"   Outcome: {outcome}")
                        print(f"   Size: {size:.2f} tokens")
                        print(f"   Avg Price: ${avg_price:.4f} | Current: ${cur_price:.4f}")
                        print(f"   P&L: ${pnl:.2f}")
                        print()
                else:
                    print(f"❌ Erreur {response.status} pour open positions")
        except Exception as e:
            print(f"❌ Erreur: {e}")

        # 2. Redeemable positions (open positions avec redeemable=true)
        print("=" * 80)
        print("🎊 2. REDEEMABLE POSITIONS (OPEN + REDEEMABLE)")
        print("=" * 80)

        try:
            url = "https://data-api.polymarket.com/positions"
            params = {
                "user": WALLET_ADDRESS,
                "sortBy": "TOKENS",
                "sortDirection": "DESC",
                "limit": 100
            }

            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    all_positions = await response.json()
                    if not isinstance(all_positions, list):
                        all_positions = all_positions.get('positions', []) if isinstance(all_positions, dict) else []

                    # Filtrer les redeemable (redeemable = true)
                    redeemable = [p for p in all_positions if p.get('redeemable', False)]

                    print(f"\n✅ Total redeemable positions: {len(redeemable)}\n")

                    for i, pos in enumerate(redeemable, 1):
                        title = pos.get('title', 'Unknown')
                        outcome = pos.get('outcome', 'N/A')
                        size = pos.get('size', 0)
                        avg_price = pos.get('avgPrice', 0)
                        cur_price = pos.get('curPrice', 0)
                        pnl = pos.get('cashPnl', 0)
                        condition_id = pos.get('conditionId', 'N/A')

                        print(f"{i}. {title[:70]}...")
                        print(f"   Condition ID: {condition_id[:50]}...")
                        print(f"   Outcome: {outcome}")
                        print(f"   Size: {size:.2f} tokens")
                        print(f"   Avg Price: ${avg_price:.4f} | Current: ${cur_price:.4f}")
                        print(f"   P&L: ${pnl:.2f}")
                        print()
                else:
                    print(f"❌ Erreur {response.status} pour redeemable positions")
        except Exception as e:
            print(f"❌ Erreur: {e}")

        # 3. Closed positions
        print("=" * 80)
        print("📋 3. CLOSED POSITIONS")
        print("=" * 80)

        try:
            url = "https://data-api.polymarket.com/closed-positions"
            params = {
                "user": WALLET_ADDRESS,
                "limit": 100,
                "sortBy": "REALIZEDPNL",
                "sortDirection": "DESC"
            }

            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    closed_positions = await response.json()
                    if not isinstance(closed_positions, list):
                        closed_positions = closed_positions.get('positions', []) if isinstance(closed_positions, dict) else []

                    print(f"\n✅ Total closed positions: {len(closed_positions)}\n")

                    # Séparer winners et losers
                    winners = [p for p in closed_positions if float(p.get('realizedPnl', 0)) > 0]
                    losers = [p for p in closed_positions if float(p.get('realizedPnl', 0)) <= 0]

                    print(f"🎯 Winners (PnL > 0): {len(winners)}")
                    print(f"📉 Losers (PnL <= 0): {len(losers)}\n")

                    if winners:
                        print("🏆 WINNERS:\n")
                        for i, pos in enumerate(winners, 1):
                            title = pos.get('title', 'Unknown')
                            outcome = pos.get('outcome', 'N/A')
                            realized_pnl = pos.get('realizedPnl', 0)
                            tokens = pos.get('totalBought', 0)

                            print(f"{i}. {title[:70]}...")
                            print(f"   Outcome: {outcome}")
                            print(f"   Tokens: {tokens:.2f}")
                            print(f"   Realized P&L: ${realized_pnl:.2f}")
                            print()

                    if losers and len(losers) <= 10:
                        print("📉 LOSERS (top 10):\n")
                        for i, pos in enumerate(losers[:10], 1):
                            title = pos.get('title', 'Unknown')
                            realized_pnl = pos.get('realizedPnl', 0)
                            print(f"{i}. {title[:70]}... (PnL: ${realized_pnl:.2f})")
                else:
                    print(f"❌ Erreur {response.status} pour closed positions")
        except Exception as e:
            print(f"❌ Erreur: {e}")

        print("=" * 80)
        print("✅ Vérification terminée")
        print("=" * 80)

if __name__ == "__main__":
    asyncio.run(fetch_positions())
