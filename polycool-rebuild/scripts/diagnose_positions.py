#!/usr/bin/env python3
"""
Script de diagnostic pour comparer les positions Polymarket avec Supabase
"""
import asyncio
import json
import sys
import os
from typing import List, Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from core.database.connection import get_db
from core.database.models import Position, Market, ResolvedPosition
from sqlalchemy import select
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


async def fetch_polymarket_positions(wallet_address: str) -> Dict[str, Any]:
    """Fetch positions from Polymarket API"""
    results = {
        'active': [],
        'closed': [],
        'errors': []
    }

    # Fetch active positions
    try:
        url = f"https://data-api.polymarket.com/positions?user={wallet_address}&limit=100"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    results['active'] = data if isinstance(data, list) else []
                    logger.info(f"✅ Fetched {len(results['active'])} active positions from Polymarket")
                else:
                    results['errors'].append(f"Active positions API returned {response.status}")
    except Exception as e:
        results['errors'].append(f"Error fetching active positions: {e}")

    # Fetch closed positions
    try:
        url = f"https://data-api.polymarket.com/closed-positions?user={wallet_address}&limit=100"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    results['closed'] = data if isinstance(data, list) else []
                    logger.info(f"✅ Fetched {len(results['closed'])} closed positions from Polymarket")
                else:
                    results['errors'].append(f"Closed positions API returned {response.status}")
    except Exception as e:
        results['errors'].append(f"Error fetching closed positions: {e}")

    return results


async def fetch_supabase_positions(user_id: int) -> Dict[str, Any]:
    """Fetch positions from Supabase"""
    results = {
        'active': [],
        'closed': [],
        'resolved': []
    }

    try:
        async with get_db() as db:
            # Active positions
            active_query = select(Position).where(
                Position.user_id == user_id,
                Position.status == 'active',
                Position.amount > 0
            )
            result = await db.execute(active_query)
            active_positions = result.scalars().all()

            for pos in active_positions:
                # Get market info
                market_query = select(Market).where(Market.id == pos.market_id)
                market_result = await db.execute(market_query)
                market = market_result.scalar_one_or_none()

                results['active'].append({
                    'id': pos.id,
                    'market_id': pos.market_id,
                    'condition_id': market.condition_id if market else None,
                    'outcome': pos.outcome,
                    'amount': float(pos.amount),
                    'entry_price': float(pos.entry_price),
                    'current_price': float(pos.current_price) if pos.current_price else None,
                    'market_title': market.title if market else None,
                    'created_at': str(pos.created_at)
                })

            # Closed positions
            closed_query = select(Position).where(
                Position.user_id == user_id,
                Position.status == 'closed'
            )
            result = await db.execute(closed_query)
            closed_positions = result.scalars().all()

            for pos in closed_positions:
                market_query = select(Market).where(Market.id == pos.market_id)
                market_result = await db.execute(market_query)
                market = market_result.scalar_one_or_none()

                results['closed'].append({
                    'id': pos.id,
                    'market_id': pos.market_id,
                    'condition_id': market.condition_id if market else None,
                    'outcome': pos.outcome,
                    'amount': float(pos.amount),
                    'entry_price': float(pos.entry_price),
                    'market_title': market.title if market else None,
                    'created_at': str(pos.created_at)
                })

            # Resolved positions
            resolved_query = select(ResolvedPosition).where(
                ResolvedPosition.user_id == user_id
            )
            result = await db.execute(resolved_query)
            resolved_positions = result.scalars().all()

            for rp in resolved_positions:
                results['resolved'].append({
                    'id': rp.id,
                    'market_id': rp.market_id,
                    'condition_id': rp.condition_id,
                    'outcome': rp.outcome,
                    'tokens_held': float(rp.tokens_held),
                    'is_winner': rp.is_winner,
                    'status': rp.status,
                    'net_value': float(rp.net_value),
                    'created_at': str(rp.created_at)
                })

            logger.info(f"✅ Fetched {len(results['active'])} active, {len(results['closed'])} closed, {len(results['resolved'])} resolved from Supabase")

    except Exception as e:
        logger.error(f"❌ Error fetching Supabase positions: {e}")
        results['errors'] = [str(e)]

    return results


def normalize_outcome(outcome: str) -> str:
    """Normalize outcome to YES/NO"""
    outcome_upper = outcome.upper().strip()
    if outcome_upper in ['UP', 'YES', 'Y', 'OVER', 'ABOVE']:
        return 'YES'
    elif outcome_upper in ['DOWN', 'NO', 'N', 'UNDER', 'BELOW']:
        return 'NO'
    return outcome_upper


def compare_positions(polymarket: Dict[str, Any], supabase: Dict[str, Any]) -> Dict[str, Any]:
    """Compare Polymarket and Supabase positions"""
    comparison = {
        'active_matches': [],
        'active_missing_in_supabase': [],
        'active_extra_in_supabase': [],
        'closed_matches': [],
        'closed_missing_in_supabase': [],
        'closed_extra_in_supabase': [],
        'duplicates': []
    }

    # Compare active positions
    pm_active_by_condition = {}
    for pos in polymarket['active']:
        condition_id = pos.get('conditionId') or pos.get('id', '')
        outcome = normalize_outcome(pos.get('outcome', ''))
        key = (condition_id, outcome)
        if key not in pm_active_by_condition:
            pm_active_by_condition[key] = []
        pm_active_by_condition[key].append(pos)

    sb_active_by_condition = {}
    for pos in supabase['active']:
        condition_id = pos.get('condition_id', '')
        outcome = normalize_outcome(pos.get('outcome', ''))
        key = (condition_id, outcome)
        if key not in sb_active_by_condition:
            sb_active_by_condition[key] = []
        sb_active_by_condition[key].append(pos)

    # Find matches and differences
    all_keys = set(pm_active_by_condition.keys()) | set(sb_active_by_condition.keys())

    for key in all_keys:
        pm_positions = pm_active_by_condition.get(key, [])
        sb_positions = sb_active_by_condition.get(key, [])

        if pm_positions and sb_positions:
            # Match found
            comparison['active_matches'].append({
                'key': key,
                'polymarket_count': len(pm_positions),
                'supabase_count': len(sb_positions),
                'polymarket': pm_positions[0],
                'supabase': sb_positions[0]
            })

            # Check for duplicates
            if len(sb_positions) > 1:
                comparison['duplicates'].append({
                    'type': 'active',
                    'key': key,
                    'count': len(sb_positions),
                    'positions': sb_positions
                })
        elif pm_positions and not sb_positions:
            # Missing in Supabase
            comparison['active_missing_in_supabase'].extend(pm_positions)
        elif not pm_positions and sb_positions:
            # Extra in Supabase (should be closed)
            comparison['active_extra_in_supabase'].extend(sb_positions)

    # Compare closed positions (similar logic)
    pm_closed_by_condition = {}
    for pos in polymarket['closed']:
        condition_id = pos.get('conditionId') or pos.get('id', '')
        outcome = normalize_outcome(pos.get('outcome', ''))
        key = (condition_id, outcome)
        if key not in pm_closed_by_condition:
            pm_closed_by_condition[key] = []
        pm_closed_by_condition[key].append(pos)

    sb_closed_by_condition = {}
    for pos in supabase['closed']:
        condition_id = pos.get('condition_id', '')
        outcome = normalize_outcome(pos.get('outcome', ''))
        key = (condition_id, outcome)
        if key not in sb_closed_by_condition:
            sb_closed_by_condition[key] = []
        sb_closed_by_condition[key].append(pos)

    all_closed_keys = set(pm_closed_by_condition.keys()) | set(sb_closed_by_condition.keys())

    for key in all_closed_keys:
        pm_positions = pm_closed_by_condition.get(key, [])
        sb_positions = sb_closed_by_condition.get(key, [])

        if pm_positions and sb_positions:
            comparison['closed_matches'].append({
                'key': key,
                'polymarket_count': len(pm_positions),
                'supabase_count': len(sb_positions)
            })
        elif pm_positions and not sb_positions:
            comparison['closed_missing_in_supabase'].extend(pm_positions)
        elif not pm_positions and sb_positions:
            comparison['closed_extra_in_supabase'].extend(sb_positions)

    return comparison


async def main():
    """Main diagnostic function"""
    user_id = 1

    # Get wallet address from user
    try:
        async with get_db() as db:
            from core.database.models import User
            user_query = select(User).where(User.id == user_id)
            result = await db.execute(user_query)
            user = result.scalar_one_or_none()

            if not user:
                logger.error(f"❌ User {user_id} not found")
                return

            wallet_address = user.polygon_address
            if not wallet_address:
                logger.error(f"❌ User {user_id} has no wallet address")
                return

            logger.info(f"🔍 Diagnosing positions for user {user_id} ({wallet_address[:10]}...)")
    except Exception as e:
        logger.error(f"❌ Error getting user: {e}")
        return

    # Fetch from both sources
    logger.info("📡 Fetching positions from Polymarket API...")
    polymarket_data = await fetch_polymarket_positions(wallet_address)

    logger.info("📡 Fetching positions from Supabase...")
    supabase_data = await fetch_supabase_positions(user_id)

    # Compare
    logger.info("🔍 Comparing positions...")
    comparison = compare_positions(polymarket_data, supabase_data)

    # Print results
    print("\n" + "="*80)
    print("DIAGNOSTIC DES POSITIONS")
    print("="*80)

    print(f"\n📊 POLYMARKET API:")
    print(f"  - Active: {len(polymarket_data['active'])}")
    print(f"  - Closed: {len(polymarket_data['closed'])}")
    if polymarket_data['errors']:
        print(f"  - Errors: {polymarket_data['errors']}")

    print(f"\n💾 SUPABASE:")
    print(f"  - Active: {len(supabase_data['active'])}")
    print(f"  - Closed: {len(supabase_data['closed'])}")
    print(f"  - Resolved: {len(supabase_data['resolved'])}")

    print(f"\n🔍 COMPARAISON:")
    print(f"  - Active matches: {len(comparison['active_matches'])}")
    print(f"  - Active missing in Supabase: {len(comparison['active_missing_in_supabase'])}")
    print(f"  - Active extra in Supabase (should be closed): {len(comparison['active_extra_in_supabase'])}")
    print(f"  - Duplicates found: {len(comparison['duplicates'])}")

    if comparison['duplicates']:
        print(f"\n⚠️ DUPLICATES DETECTÉS:")
        for dup in comparison['duplicates']:
            print(f"  - {dup['type']}: {dup['key']} ({dup['count']} positions)")
            for pos in dup['positions']:
                print(f"    * ID: {pos['id']}, Outcome: {pos['outcome']}, Amount: {pos['amount']}")

    if comparison['active_extra_in_supabase']:
        print(f"\n⚠️ POSITIONS ACTIVES EN TROP DANS SUPABASE (devraient être fermées):")
        for pos in comparison['active_extra_in_supabase']:
            print(f"  - ID: {pos['id']}, Market: {pos['market_id']}, Outcome: {pos['outcome']}, Amount: {pos['amount']}")
            print(f"    Title: {pos.get('market_title', 'Unknown')[:60]}...")

    if comparison['active_missing_in_supabase']:
        print(f"\n⚠️ POSITIONS ACTIVES MANQUANTES DANS SUPABASE:")
        for pos in comparison['active_missing_in_supabase']:
            print(f"  - Condition: {pos.get('conditionId', '')[:20]}..., Outcome: {pos.get('outcome')}, Size: {pos.get('size', 0)}")

    print(f"\n📋 DÉTAILS POLYMARKET ACTIVE:")
    for i, pos in enumerate(polymarket_data['active'], 1):
        print(f"  {i}. Condition: {pos.get('conditionId', '')[:20]}...")
        print(f"     Outcome: {pos.get('outcome')}, Size: {pos.get('size', 0)}, AvgPrice: {pos.get('avgPrice', 0)}")
        print(f"     Title: {pos.get('title', 'Unknown')[:60]}...")
        print(f"     Closed: {pos.get('closed', False)}, RealizedPnl: {pos.get('realizedPnl', 0)}")

    print(f"\n📋 DÉTAILS SUPABASE ACTIVE:")
    for i, pos in enumerate(supabase_data['active'], 1):
        print(f"  {i}. ID: {pos['id']}, Market: {pos['market_id']}")
        print(f"     Condition: {pos.get('condition_id', '')[:20] if pos.get('condition_id') else 'N/A'}...")
        print(f"     Outcome: {pos['outcome']}, Amount: {pos['amount']}, EntryPrice: {pos['entry_price']}")
        print(f"     Title: {pos.get('market_title', 'Unknown')[:60]}...")

    print(f"\n💰 RESOLVED POSITIONS:")
    if supabase_data['resolved']:
        for rp in supabase_data['resolved']:
            print(f"  - ID: {rp['id']}, Condition: {rp['condition_id'][:20]}...")
            print(f"    Outcome: {rp['outcome']}, Tokens: {rp['tokens_held']}, Winner: {rp['is_winner']}")
            print(f"    Status: {rp['status']}, NetValue: ${rp['net_value']:.2f}")
    else:
        print("  Aucune position resolved trouvée")

    print("\n" + "="*80)


if __name__ == "__main__":
    asyncio.run(main())
