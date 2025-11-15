#!/usr/bin/env python3
"""
Analyze smart wallet trades and check which markets are missing from our database
"""
import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL not found in .env file")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print('📊 STRUCTURE DE LA TABLE smart_wallet_trades:')
print('='*80)
cur.execute('''
    SELECT column_name, data_type, character_maximum_length
    FROM information_schema.columns
    WHERE table_name = 'smart_wallet_trades'
    ORDER BY ordinal_position
''')
for row in cur.fetchall():
    col_name, data_type, max_length = row
    length_str = f"({max_length})" if max_length else ""
    print(f'  {col_name:20s} {data_type:20s} {length_str}')

print('\n📊 STRUCTURE DE LA TABLE markets (premiers 15 champs):')
print('='*80)
cur.execute('''
    SELECT column_name, data_type, character_maximum_length
    FROM information_schema.columns
    WHERE table_name = 'markets'
    ORDER BY ordinal_position
    LIMIT 15
''')
for row in cur.fetchall():
    col_name, data_type, max_length = row
    length_str = f"({max_length})" if max_length else ""
    print(f'  {col_name:20s} {data_type:20s} {length_str}')

print('\n🔍 SAMPLE: 3 trades des smart wallets:')
print('='*80)
cur.execute('''
    SELECT market_id, market_question, outcome, value, timestamp
    FROM smart_wallet_trades
    WHERE is_first_time = true
    ORDER BY timestamp DESC
    LIMIT 3
''')
for row in cur.fetchall():
    market_id, question, outcome, value, timestamp = row
    print(f'Market ID: {market_id[:20]}...')
    print(f'Question:  {question[:60] if question else "N/A"}...')
    print(f'Outcome:   {outcome}, Value: ${float(value):.2f}')
    print(f'Timestamp: {timestamp}')
    print('-'*80)

print('\n🔍 Combien de markets uniques dans smart_wallet_trades ?')
cur.execute('SELECT COUNT(DISTINCT market_id) FROM smart_wallet_trades')
total_markets = cur.fetchone()[0]
print(f'Total: {total_markets} markets uniques')

print('\n🔍 Combien de ces markets sont dans notre table markets ?')
cur.execute('''
    SELECT COUNT(DISTINCT swt.market_id)
    FROM smart_wallet_trades swt
    WHERE EXISTS (
        SELECT 1 FROM markets m
        WHERE m.condition_id = swt.market_id
    )
''')
found = cur.fetchone()[0]
print(f'✅ Trouvés dans markets: {found}')
print(f'❌ Manquants: {total_markets - found} markets')

if total_markets - found > 0:
    print('\n🔍 Exemples de markets manquants (top 10 par valeur de trade):')
    print('='*80)
    cur.execute('''
        SELECT DISTINCT swt.market_id, swt.market_question,
               MAX(swt.value) as max_trade_value,
               COUNT(*) as trade_count
        FROM smart_wallet_trades swt
        WHERE NOT EXISTS (
            SELECT 1 FROM markets m
            WHERE m.condition_id = swt.market_id
        )
        GROUP BY swt.market_id, swt.market_question
        ORDER BY max_trade_value DESC
        LIMIT 10
    ''')
    for row in cur.fetchall():
        market_id, question, max_value, trade_count = row
        print(f'  ID: {market_id[:20]}...')
        print(f'  Question: {question[:60] if question else "N/A"}...')
        print(f'  Max Trade: ${float(max_value):.2f}, Total Trades: {trade_count}')
        print('-'*80)

print('\n📊 RÉSUMÉ:')
print('='*80)
print(f'Markets dans smart_wallet_trades: {total_markets}')
print(f'Markets dans notre DB:            {found}')
print(f'Markets à ajouter:                {total_markets - found}')
print(f'Couverture:                       {(found/total_markets*100):.1f}%' if total_markets > 0 else 'N/A')

cur.close()
conn.close()
