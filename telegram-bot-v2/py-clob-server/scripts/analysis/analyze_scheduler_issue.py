#!/usr/bin/env python3
"""
Analyze why smart_wallet_monitor scheduler stopped and why only 2 trades show
"""
import os
from dotenv import load_dotenv
import psycopg2
from datetime import datetime, timezone, timedelta

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL not found")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print('🔍 ANALYSE COMPLÈTE: Pourquoi seulement 2 trades ?')
print('='*80)

# 1. Vérifier l'état du scheduler
print('\n📊 1. ÉTAT DU SCHEDULER')
print('-'*80)
cur.execute("""
    SELECT
        MAX(timestamp) as last_trade_time,
        MAX(created_at) as last_sync_time,
        COUNT(*) as total_trades,
        COUNT(CASE WHEN timestamp >= NOW() - INTERVAL '1 hour' THEN 1 END) as trades_last_hour,
        COUNT(CASE WHEN created_at >= NOW() - INTERVAL '1 hour' THEN 1 END) as synced_last_hour
    FROM smart_wallet_trades
""")
result = cur.fetchone()
last_trade_time, last_sync_time, total_trades, trades_last_hour, synced_last_hour = result

print(f"Dernier trade (timestamp): {last_trade_time}")
print(f"Dernière sync (created_at): {last_sync_time}")
print(f"Total trades en DB: {total_trades}")
print(f"Trades dernière heure: {trades_last_hour}")
print(f"Syncés dernière heure: {synced_last_hour}")

if last_sync_time:
    time_since = datetime.now(timezone.utc) - last_sync_time.replace(tzinfo=timezone.utc)
    minutes_ago = int(time_since.total_seconds() / 60)
    print(f"\n⏱️  Temps depuis dernière sync: {minutes_ago} minutes")

    if minutes_ago > 15:
        print(f"❌ PROBLÈME: Scheduler arrêté depuis {minutes_ago} min")
        print("   Attendu: Sync toutes les 10 minutes")
    else:
        print("✅ Scheduler semble actif")

# 2. Vérifier le code Python exact utilisé par smart_trading_handler
print('\n📊 2. SIMULATION DU CODE /smart_trading')
print('-'*80)
print('Code exécuté:')
print('  trades = smart_trade_repo.get_recent_first_time_trades(limit=20, min_value=300.0)')
print('  → Puis filtre avec market_service.get_market_by_id() pour chaque trade')

# Récupérer les 20 premiers trades comme le fait le code
cur.execute("""
    SELECT
        id, market_id, market_question, outcome, value, timestamp
    FROM smart_wallet_trades
    WHERE is_first_time = true
      AND value >= 300
    ORDER BY timestamp DESC
    LIMIT 20
""")

top_20_trades = cur.fetchall()
print(f'\nÉtape 1: Récupéré {len(top_20_trades)} trades (limit=20, value>=300)')

# Simuler le filtre market_service
valid_trades = []
for trade_id, market_id, question, outcome, value, timestamp in top_20_trades:
    # Check if market exists and is valid
    cur.execute("""
        SELECT id, active, closed, tradeable, end_date
        FROM markets
        WHERE condition_id = %s
    """, (market_id,))

    market = cur.fetchone()

    if not market:
        print(f"  ❌ Trade {trade_id[:10]}... - Market {market_id[:10]}... PAS dans DB")
        continue

    db_id, active, closed, tradeable, end_date = market

    # Check active
    if not active:
        print(f"  ❌ Trade {trade_id[:10]}... - Market {db_id} INACTIF")
        continue

    # Check closed
    if closed:
        print(f"  ❌ Trade {trade_id[:10]}... - Market {db_id} FERMÉ")
        continue

    # Check tradeable
    if not tradeable:
        print(f"  ❌ Trade {trade_id[:10]}... - Market {db_id} NON TRADEABLE")
        continue

    # Check end_date
    if end_date:
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        if end_date <= datetime.now(timezone.utc):
            print(f"  ❌ Trade {trade_id[:10]}... - Market {db_id} EXPIRÉ (end_date={end_date})")
            continue

    print(f"  ✅ Trade {trade_id[:10]}... - Market {db_id} VALIDE")
    valid_trades.append((trade_id, market_id, question, outcome, value, timestamp, db_id))

    if len(valid_trades) >= 10:
        break

print(f'\nÉtape 2: Après filtrage → {len(valid_trades)} trades valides')

# 3. Afficher les trades qui DEVRAIENT être affichés
print('\n📊 3. TRADES QUI DEVRAIENT ÊTRE AFFICHÉS')
print('='*80)
for i, (trade_id, market_id, question, outcome, value, timestamp, db_id) in enumerate(valid_trades, 1):
    print(f'\n{i}. 💎 ${float(value):,.2f}')
    print(f'   Question: {question[:60] if question else "N/A"}...')
    print(f'   Outcome: {outcome}')
    print(f'   Time: {timestamp}')
    print(f'   Market ID: {market_id[:20]}... (DB: {db_id})')

# 4. Vérifier si c'est un problème de session/cache
print('\n📊 4. HYPOTHÈSES POUR SEULEMENT 2 TRADES AFFICHÉS')
print('='*80)
if len(valid_trades) == 2:
    print('✅ La DB a bien 2 trades valides → Code fonctionne correctement')
    print('   Raison: La plupart des markets sont fermés/expirés/non-tradeables')
elif len(valid_trades) > 2:
    print(f'❌ La DB a {len(valid_trades)} trades valides mais tu n\'en vois que 2')
    print('\nPossibles causes:')
    print('  1. Cache côté Telegram (essaie de cliquer sur /smart_trading à nouveau)')
    print('  2. Ancien code déployé (vérifie Railway deployment)')
    print('  3. Session utilisateur stocke anciennes données')
    print('  4. Logs Railway montrent des erreurs pendant le filtrage')
else:
    print(f'⚠️  La DB a {len(valid_trades)} trades mais tu en vois 2')
    print('   Il y a peut-être un cache ou des données en session')

# 5. Vérifier scheduler configuration
print('\n📊 5. DIAGNOSTIC SCHEDULER')
print('='*80)
print('Configuration attendue dans main.py:')
print('  • Job: smart_monitor.sync_all_wallets')
print('  • Trigger: IntervalTrigger(minutes=10)')
print('  • Action: Fetch trades des 10 dernières minutes')
print('')
print('État actuel:')
if minutes_ago > 15:
    print(f'  ❌ Dernière sync: Il y a {minutes_ago} min')
    print('  ❌ Le scheduler est ARRÊTÉ ou CRASH')
    print('\n  Solutions:')
    print('    1. Redéployer le service Railway')
    print('    2. Vérifier logs Railway pour erreurs async/httpx')
    print('    3. Vérifier que httpx.AsyncClient() fonctionne')
else:
    print(f'  ✅ Dernière sync: Il y a {minutes_ago} min')

# 6. Check most recent trades in detail
print('\n📊 6. DÉTAIL DES 5 DERNIERS TRADES EN DB')
print('='*80)
cur.execute("""
    SELECT
        swt.timestamp as trade_time,
        swt.created_at as sync_time,
        swt.market_question,
        swt.value,
        m.id as market_db_id,
        m.active,
        m.closed,
        m.tradeable
    FROM smart_wallet_trades swt
    LEFT JOIN markets m ON m.condition_id = swt.market_id
    WHERE swt.is_first_time = true AND swt.value >= 300
    ORDER BY swt.timestamp DESC
    LIMIT 5
""")

for row in cur.fetchall():
    trade_time, sync_time, question, value, market_id, active, closed, tradeable = row
    print(f'\nTrade: {question[:50] if question else "N/A"}...')
    print(f'  Time: {trade_time}')
    print(f'  Synced: {sync_time}')
    print(f'  Value: ${float(value):,.2f}')
    if market_id:
        print(f'  Market: {market_id} | Active:{active} Closed:{closed} Tradeable:{tradeable}')
    else:
        print(f'  Market: ❌ PAS DANS DB')

cur.close()
conn.close()
