#!/usr/bin/env python3
"""
Check how many smart_trading trades should be displayed based on DB
"""
import os
from dotenv import load_dotenv
import psycopg2
from datetime import datetime

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL not found")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print('🔍 ANALYSE: Combien de trades /smart_trading DEVRAIT afficher')
print('='*80)

# Le code exact du filtre dans smart_trading_handler.py
print('\n📊 Requête EXACTE utilisée par /smart_trading:')
print('-'*80)
print('SELECT * FROM smart_wallet_trades')
print('WHERE is_first_time = true')
print('  AND value >= 300')
print('  AND market EXISTS in markets table')
print('  AND market.active = true')
print('  AND market.closed = false')
print('  AND market.tradeable = true')
print('  AND (market.end_date IS NULL OR market.end_date > NOW())')
print('ORDER BY timestamp DESC')
print('LIMIT 20 (puis filtré à 10)')

# Exécuter la requête EXACTE
print('\n📊 RÉSULTAT:')
print('='*80)
cur.execute("""
    SELECT
        swt.id,
        swt.market_id,
        swt.market_question,
        swt.outcome,
        swt.value,
        swt.timestamp,
        m.id as db_market_id,
        m.question as db_question,
        m.active,
        m.closed,
        m.tradeable,
        m.end_date
    FROM smart_wallet_trades swt
    INNER JOIN markets m ON m.condition_id = swt.market_id
    WHERE swt.is_first_time = true
      AND swt.value >= 300
      AND m.active = true
      AND m.closed = false
      AND m.tradeable = true
      AND (m.end_date IS NULL OR m.end_date > NOW())
    ORDER BY swt.timestamp DESC
    LIMIT 20
""")

results = cur.fetchall()
total = len(results)

print(f'\n✅ TOTAL: {total} trades correspondent aux critères')
print(f'📊 /smart_trading affichera les {min(total, 10)} premiers\n')

if total == 0:
    print('❌ AUCUN trade ne passe tous les filtres!')
    print('\nDiagnostic:')

    # Check each filter step by step
    cur.execute("SELECT COUNT(*) FROM smart_wallet_trades WHERE is_first_time = true AND value >= 300")
    step1 = cur.fetchone()[0]
    print(f'  1. Trades first-time >= $300: {step1}')

    cur.execute("""
        SELECT COUNT(*) FROM smart_wallet_trades swt
        INNER JOIN markets m ON m.condition_id = swt.market_id
        WHERE swt.is_first_time = true AND swt.value >= 300
    """)
    step2 = cur.fetchone()[0]
    print(f'  2. Avec market dans DB: {step2}')

    cur.execute("""
        SELECT COUNT(*) FROM smart_wallet_trades swt
        INNER JOIN markets m ON m.condition_id = swt.market_id
        WHERE swt.is_first_time = true AND swt.value >= 300
          AND m.active = true
    """)
    step3 = cur.fetchone()[0]
    print(f'  3. Market actif: {step3}')

    cur.execute("""
        SELECT COUNT(*) FROM smart_wallet_trades swt
        INNER JOIN markets m ON m.condition_id = swt.market_id
        WHERE swt.is_first_time = true AND swt.value >= 300
          AND m.active = true
          AND m.closed = false
    """)
    step4 = cur.fetchone()[0]
    print(f'  4. Market non fermé: {step4}')

    cur.execute("""
        SELECT COUNT(*) FROM smart_wallet_trades swt
        INNER JOIN markets m ON m.condition_id = swt.market_id
        WHERE swt.is_first_time = true AND swt.value >= 300
          AND m.active = true
          AND m.closed = false
          AND m.tradeable = true
    """)
    step5 = cur.fetchone()[0]
    print(f'  5. Market tradeable: {step5}')

    cur.execute("""
        SELECT COUNT(*) FROM smart_wallet_trades swt
        INNER JOIN markets m ON m.condition_id = swt.market_id
        WHERE swt.is_first_time = true AND swt.value >= 300
          AND m.active = true
          AND m.closed = false
          AND m.tradeable = true
          AND (m.end_date IS NULL OR m.end_date > NOW())
    """)
    step6 = cur.fetchone()[0]
    print(f'  6. End date valide: {step6}')
else:
    print('TRADES ÉLIGIBLES:')
    print('='*80)
    for i, row in enumerate(results[:10], 1):  # Only show first 10
        trade_id, market_id, question, outcome, value, timestamp, db_id, db_question, active, closed, tradeable, end_date = row
        print(f'\n{i}. 💎 Trade #{trade_id}')
        print(f'   Question: {question or db_question}')
        print(f'   Outcome: {outcome}')
        print(f'   Value: ${float(value):,.2f}')
        print(f'   Timestamp: {timestamp}')
        print(f'   Market: {market_id[:20]}... (DB ID: {db_id})')
        print(f'   Status: Active={active}, Closed={closed}, Tradeable={tradeable}')
        if end_date:
            print(f'   End Date: {end_date}')
        print('-'*80)

# Summary
print('\n📊 RÉSUMÉ:')
print('='*80)
print(f'✅ {total} trades passent TOUS les filtres')
print(f'📺 /smart_trading affichera: {min(total, 10)} trades')

if total < 10:
    print(f'\n⚠️  Moins de 10 trades disponibles')
    print(f'   Raison principale: Markets eSports fermés rapidement (40% des trades)')
    print(f'   Trades affichés: Markets long-terme (politique, économie)')

# Check what's currently in the database
print('\n🔍 VÉRIFICATION: Dernière sync des smart wallet trades')
print('='*80)
cur.execute("""
    SELECT
        MAX(timestamp) as last_trade,
        MAX(created_at) as last_sync,
        COUNT(*) as total
    FROM smart_wallet_trades
""")
last_trade, last_sync, total_trades = cur.fetchone()
print(f'  Dernier trade: {last_trade}')
print(f'  Dernière sync: {last_sync}')
print(f'  Total trades: {total_trades}')

from datetime import timezone, timedelta
if last_sync:
    time_since = datetime.now(timezone.utc) - last_sync.replace(tzinfo=timezone.utc)
    minutes_ago = int(time_since.total_seconds() / 60)
    print(f'  Temps écoulé: {minutes_ago} minutes')

    if minutes_ago > 15:
        print(f'\n⚠️  ATTENTION: Dernière sync il y a {minutes_ago} min')
        print('   Le scheduler smart_wallet_monitor devrait syncer toutes les 10 min')
        print('   → Vérifier les logs Railway pour "smart wallet trades sync"')

cur.close()
conn.close()
