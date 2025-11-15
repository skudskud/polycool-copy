#!/usr/bin/env python3
"""
Check recent smart wallet trades coverage in markets table
"""
import os
from dotenv import load_dotenv
import psycopg2
from datetime import datetime, timedelta, timezone

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL not found")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print('🔍 Analyse des markets récents dans smart_wallet_trades vs markets')
print('='*80)

# Markets tradés dans les dernières 24h
cur.execute("""
    SELECT COUNT(DISTINCT market_id)
    FROM smart_wallet_trades
    WHERE timestamp >= NOW() - INTERVAL '24 hours'
""")
recent_trades_24h = cur.fetchone()[0]
print(f'📊 Markets uniques tradés (24h): {recent_trades_24h}')

# Combien sont dans notre DB ?
cur.execute("""
    SELECT COUNT(DISTINCT swt.market_id)
    FROM smart_wallet_trades swt
    WHERE swt.timestamp >= NOW() - INTERVAL '24 hours'
      AND EXISTS (
          SELECT 1 FROM markets m
          WHERE m.condition_id = swt.market_id
            AND m.active = true
            AND m.closed = false
      )
""")
found_active = cur.fetchone()[0]
print(f'✅ Markets actifs dans DB: {found_active}')
print(f'❌ Markets manquants/fermés: {recent_trades_24h - found_active}')
if recent_trades_24h > 0:
    print(f'📈 Taux de couverture: {(found_active/recent_trades_24h*100):.1f}%')

print('\n🔍 Top 5 markets manquants (triés par valeur de trade):')
print('='*80)
cur.execute("""
    SELECT swt.market_id, swt.market_question,
           MAX(swt.value) as max_value,
           MAX(swt.timestamp) as last_trade
    FROM smart_wallet_trades swt
    WHERE swt.timestamp >= NOW() - INTERVAL '24 hours'
      AND NOT EXISTS (
          SELECT 1 FROM markets m
          WHERE m.condition_id = swt.market_id
      )
    GROUP BY swt.market_id, swt.market_question
    ORDER BY max_value DESC
    LIMIT 5
""")
for row in cur.fetchall():
    market_id, question, max_value, last_trade = row
    print(f'  Market: {question[:60] if question else "N/A"}...')
    print(f'  ID: {market_id[:20]}...')
    print(f'  Max trade: ${float(max_value):.2f}')
    print(f'  Last trade: {last_trade}')
    print('-'*80)

print('\n🔍 Regardons si ces markets sont dans notre DB mais FERMÉS:')
print('='*80)
cur.execute("""
    SELECT COUNT(DISTINCT swt.market_id)
    FROM smart_wallet_trades swt
    WHERE swt.timestamp >= NOW() - INTERVAL '24 hours'
      AND EXISTS (
          SELECT 1 FROM markets m
          WHERE m.condition_id = swt.market_id
            AND (m.active = false OR m.closed = true)
      )
""")
closed_in_db = cur.fetchone()[0]
print(f'🔒 Markets dans DB mais fermés: {closed_in_db}')

cur.close()
conn.close()
