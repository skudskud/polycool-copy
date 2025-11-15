#!/usr/bin/env python3
"""
Check the status of the Bitcoin market in our database
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, ResolvedPosition, SubsquidMarketPoll
from datetime import datetime

def check_market_status():
    print('=== CHECKING ALL RESOLVED POSITIONS ===')

    with SessionLocal() as session:
        # Check ALL resolved positions
        all_positions = session.query(ResolvedPosition).order_by(
            ResolvedPosition.resolved_at.desc()
        ).limit(20).all()

        print(f'Found {len(all_positions)} total resolved positions:')

        for pos in all_positions:
            print(f'\n• Market: {pos.market_title[:60]}...')
            print(f'  User: {pos.user_id}, Outcome: {pos.outcome}, Winner: {pos.is_winner}')
            print(f'  Status: {pos.status}, Net Value: ${pos.net_value}')
            print(f'  Resolved: {pos.resolved_at}')
            print(f'  Condition ID: {pos.condition_id[:20]}...')
            print(f'  Token ID: {pos.token_id[:20]}...')

            if pos.is_winner and pos.status == 'PENDING':
                print('  🎯 READY TO REDEEM!')
            elif pos.is_winner and pos.status == 'PROCESSING':
                print('  🔄 PROCESSING...')
            elif pos.is_winner and pos.status == 'REDEEMED':
                print('  ✅ ALREADY REDEEMED')
            elif not pos.is_winner:
                print('  💸 LOSER POSITION')

        # Now check specifically for Bitcoin markets
        print(f'\n\n🔍 SPECIFIC SEARCH FOR BITCOIN MARKETS:')
        bitcoin_positions = session.query(ResolvedPosition).filter(
            ResolvedPosition.market_title.ilike('%bitcoin%')
        ).all()

        print(f'Found {len(bitcoin_positions)} Bitcoin-related positions:')

        for pos in bitcoin_positions:
            print(f'\n• BITCOIN: {pos.market_title}')
            print(f'  User: {pos.user_id}, Status: {pos.status}, Winner: {pos.is_winner}')
            print(f'  Condition ID: {pos.condition_id}')
            print(f'  Token ID: {pos.token_id}')

        print(f'\n\n📊 SUMMARY:')
        total_pending = session.query(ResolvedPosition).filter(
            ResolvedPosition.status == 'PENDING',
            ResolvedPosition.is_winner == True
        ).count()

        print(f'• Total resolved positions: {len(all_positions)}')
        print(f'• Bitcoin positions: {len(bitcoin_positions)}')
        print(f'• Total pending redemptions: {total_pending}')

        if total_pending > 0:
            print('\n🎯 THERE ARE PENDING REDEMPTIONS TO TEST!')
        else:
            print('\n❌ NO PENDING POSITIONS - THAT EXPLAINS THE ERROR!')

if __name__ == "__main__":
    check_market_status()
