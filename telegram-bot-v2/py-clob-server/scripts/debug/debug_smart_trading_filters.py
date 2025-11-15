#!/usr/bin/env python3
"""
Debug Smart Trading Filters
Analyse pourquoi certains trades n'apparaissent pas dans /smart_trading
"""
import os
from dotenv import load_dotenv
import psycopg2
from datetime import datetime, timezone

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL not found")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print('🔍 DEBUG /smart_trading - Analyse des filtres')
print('='*80)

# Étape 1: Combien de trades first-time >= $300 dans les dernières 24h ?
print('\n📊 ÉTAPE 1: Trades first-time >= $300 (dernières 24h)')
print('-'*80)
cur.execute("""
    SELECT COUNT(*)
    FROM smart_wallet_trades
    WHERE is_first_time = true
      AND value >= 300
      AND timestamp >= NOW() - INTERVAL '24 hours'
""")
total_trades = cur.fetchone()[0]
print(f'Total trades éligibles: {total_trades}')

# Étape 2: Parmi ces trades, combien ont un market dans notre DB ?
print('\n📊 ÉTAPE 2: Trades avec market existant dans DB')
print('-'*80)
cur.execute("""
    SELECT COUNT(*)
    FROM smart_wallet_trades swt
    WHERE swt.is_first_time = true
      AND swt.value >= 300
      AND swt.timestamp >= NOW() - INTERVAL '24 hours'
      AND EXISTS (
          SELECT 1 FROM markets m
          WHERE m.condition_id = swt.market_id
      )
""")
with_market = cur.fetchone()[0]
print(f'Avec market dans DB: {with_market}')
print(f'Sans market dans DB: {total_trades - with_market}')

# Étape 3: Parmi ceux avec market, combien sont ACTIFS ?
print('\n📊 ÉTAPE 3: Trades avec market ACTIF')
print('-'*80)
cur.execute("""
    SELECT COUNT(*)
    FROM smart_wallet_trades swt
    WHERE swt.is_first_time = true
      AND swt.value >= 300
      AND swt.timestamp >= NOW() - INTERVAL '24 hours'
      AND EXISTS (
          SELECT 1 FROM markets m
          WHERE m.condition_id = swt.market_id
            AND m.active = true
      )
""")
with_active = cur.fetchone()[0]
print(f'Market actif: {with_active}')

# Étape 4: Parmi ceux actifs, combien sont NON FERMÉS ?
print('\n📊 ÉTAPE 4: Trades avec market NON FERMÉ')
print('-'*80)
cur.execute("""
    SELECT COUNT(*)
    FROM smart_wallet_trades swt
    WHERE swt.is_first_time = true
      AND swt.value >= 300
      AND swt.timestamp >= NOW() - INTERVAL '24 hours'
      AND EXISTS (
          SELECT 1 FROM markets m
          WHERE m.condition_id = swt.market_id
            AND m.active = true
            AND m.closed = false
      )
""")
not_closed = cur.fetchone()[0]
print(f'Market non fermé: {not_closed}')

# Étape 5: Parmi ceux non fermés, combien ont end_date > now ?
print('\n📊 ÉTAPE 5: Trades avec market end_date dans le futur')
print('-'*80)
cur.execute("""
    SELECT COUNT(*)
    FROM smart_wallet_trades swt
    WHERE swt.is_first_time = true
      AND swt.value >= 300
      AND swt.timestamp >= NOW() - INTERVAL '24 hours'
      AND EXISTS (
          SELECT 1 FROM markets m
          WHERE m.condition_id = swt.market_id
            AND m.active = true
            AND m.closed = false
            AND (m.end_date IS NULL OR m.end_date > NOW())
      )
""")
valid_end_date = cur.fetchone()[0]
print(f'End date valide: {valid_end_date}')

# Étape 6: Parmi ceux valides, combien sont TRADEABLE ?
print('\n📊 ÉTAPE 6: Trades avec market TRADEABLE')
print('-'*80)
cur.execute("""
    SELECT COUNT(*)
    FROM smart_wallet_trades swt
    WHERE swt.is_first_time = true
      AND swt.value >= 300
      AND swt.timestamp >= NOW() - INTERVAL '24 hours'
      AND EXISTS (
          SELECT 1 FROM markets m
          WHERE m.condition_id = swt.market_id
            AND m.active = true
            AND m.closed = false
            AND m.tradeable = true
            AND (m.end_date IS NULL OR m.end_date > NOW())
      )
""")
tradeable = cur.fetchone()[0]
print(f'Market tradeable: {tradeable}')

# Afficher les 10 derniers trades éligibles avec leur statut
print('\n📊 TOP 10 TRADES ÉLIGIBLES (détail des filtres)')
print('='*80)
cur.execute("""
    SELECT
        swt.market_id,
        swt.market_question,
        swt.value,
        swt.timestamp,
        m.id as db_market_id,
        m.active,
        m.closed,
        m.tradeable,
        m.end_date,
        CASE
            WHEN m.id IS NULL THEN '❌ Market pas dans DB'
            WHEN m.active = false THEN '❌ Market inactive'
            WHEN m.closed = true THEN '❌ Market fermé'
            WHEN m.tradeable = false THEN '❌ Market non tradeable'
            WHEN m.end_date IS NOT NULL AND m.end_date < NOW() THEN '❌ Market expiré'
            ELSE '✅ Market valide'
        END as status
    FROM smart_wallet_trades swt
    LEFT JOIN markets m ON m.condition_id = swt.market_id
    WHERE swt.is_first_time = true
      AND swt.value >= 300
      AND swt.timestamp >= NOW() - INTERVAL '24 hours'
    ORDER BY swt.timestamp DESC
    LIMIT 10
""")

for i, row in enumerate(cur.fetchall(), 1):
    market_id, question, value, timestamp, db_id, active, closed, tradeable, end_date, status = row
    print(f'\n{i}. {status}')
    print(f'   Question: {question[:60] if question else "N/A"}...')
    print(f'   Value: ${float(value):.2f}')
    print(f'   Time: {timestamp}')
    print(f'   Market ID: {market_id[:20]}...')
    if db_id:
        print(f'   DB ID: {db_id} | Active: {active} | Closed: {closed} | Tradeable: {tradeable}')
        if end_date:
            print(f'   End Date: {end_date}')
    print('-'*80)

# Résumé final
print('\n📊 RÉSUMÉ DU PIPELINE DE FILTRAGE')
print('='*80)
print(f'1. Trades first-time >= $300 (24h):  {total_trades}')
print(f'2. └─ Avec market dans DB:           {with_market} ({(with_market/total_trades*100):.1f}%)' if total_trades > 0 else '2. └─ Avec market dans DB:           0')
print(f'3.    └─ Market actif:                {with_active}')
print(f'4.       └─ Market non fermé:         {not_closed}')
print(f'5.          └─ End date valide:       {valid_end_date}')
print(f'6.             └─ Market tradeable:   {tradeable} ← AFFICHÉ dans /smart_trading')
print('='*80)

if tradeable < 10:
    print(f'\n⚠️  SEULEMENT {tradeable} TRADES PASSENT TOUS LES FILTRES')
    print('\nRaisons principales:')
    print(f'  • {total_trades - with_market} markets pas encore dans notre DB (40% environ)')
    print(f'  • {with_market - with_active} markets inactifs')
    print(f'  • {with_active - not_closed} markets fermés')
    print(f'  • {not_closed - valid_end_date} markets expirés')
    print(f'  • {valid_end_date - tradeable} markets non tradeables')

cur.close()
conn.close()
