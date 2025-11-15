#!/usr/bin/env python3
"""
Analyze closed positions from Polymarket API
"""

import asyncio
import aiohttp

async def analyze_closed_positions():
    print('=== ANALYZING CLOSED POSITIONS ===')

    competitor_wallet = '0x0D2047BC43BBDe1EC1C8009f57679Ae6F454322f'

    url = f'https://data-api.polymarket.com/closed-positions?user={competitor_wallet}&limit=20'

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f'✅ Found {len(data)} closed positions')

                    redeemable_candidates = []

                    for i, pos in enumerate(data, 1):
                        print(f'\n--- Position {i} ---')
                        title = pos.get('title', 'Unknown')
                        condition_id = pos.get('conditionId', 'N/A')
                        outcome = pos.get('outcome', 'N/A')
                        pnl = pos.get('realizedPnl', 0)
                        total_bought = pos.get('totalBought', 0)

                        print(f'Title: {title[:60]}...')
                        print(f'Condition ID: {condition_id}')
                        print(f'Outcome: {outcome}')
                        print(f'Realized PnL: ${pnl}')
                        print(f'Total Bought: {total_bought}')

                        # Logic: If PnL > 0 and we haven't redeemed it yet, it's redeemable
                        # But we need to check if it's already been redeemed on-chain
                        if pnl > 0:
                            print('🎯 POTENTIAL WINNER - needs redemption check')
                            redeemable_candidates.append({
                                'title': title,
                                'condition_id': condition_id,
                                'outcome': outcome,
                                'pnl': pnl,
                                'total_bought': total_bought
                            })
                        else:
                            print('💸 Already processed (PnL ≤ 0)')

                    print(f'\n📊 SUMMARY:')
                    print(f'Total closed positions: {len(data)}')
                    print(f'Potential redeemable: {len(redeemable_candidates)}')

                    if redeemable_candidates:
                        print('\n🎯 Candidates for redemption:')
                        for cand in redeemable_candidates:
                            print(f'  • {cand["title"][:40]}... | ${cand["pnl"]} PnL')

                else:
                    print(f'❌ API Error: {response.status}')

        except Exception as e:
            print(f'❌ Exception: {e}')

if __name__ == "__main__":
    asyncio.run(analyze_closed_positions())
