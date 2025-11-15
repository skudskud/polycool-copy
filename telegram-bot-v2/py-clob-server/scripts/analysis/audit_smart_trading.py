#!/usr/bin/env python3
"""
Audit Smart Trading Feature
Vérifie l'état du scheduler et de la table smart_wallet_trades
"""

import psycopg2
from datetime import datetime, timezone, timedelta

# Database connection
DATABASE_URL = "postgresql://postgres:gsXOUAnSYVuFOWIvophAfDVNIAsEzVuE@mainline.proxy.rlwy.net:13288/railway"

def print_table(data, headers):
    """Simple table printer"""
    if not data:
        return

    # Calculate column widths
    col_widths = [len(str(h)) for h in headers]
    for row in data:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    # Print header
    header_line = "  " + " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("  " + "-" * (sum(col_widths) + len(headers) * 3 - 3))

    # Print rows
    for row in data:
        print("  " + " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))

def audit_smart_trading():
    """Audit complet de la feature smart_trading"""

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    print("\n" + "="*80)
    print("🔍 AUDIT SMART TRADING FEATURE")
    print("="*80 + "\n")

    # 1. Statistiques globales de la table smart_wallet_trades
    print("📊 STATISTIQUES GLOBALES")
    print("-" * 80)

    cursor.execute("""
        SELECT
            COUNT(*) as total_trades,
            COUNT(*) FILTER (WHERE is_first_time = true) as first_time_trades,
            COUNT(DISTINCT wallet_address) as unique_wallets,
            COUNT(DISTINCT market_id) as unique_markets,
            MIN(timestamp) as oldest_trade,
            MAX(timestamp) as newest_trade,
            MIN(created_at) as first_inserted,
            MAX(created_at) as last_inserted
        FROM smart_wallet_trades;
    """)

    stats = cursor.fetchone()
    if stats:
        total_trades, first_time, unique_wallets, unique_markets, oldest, newest, first_insert, last_insert = stats

        print(f"  Total trades:          {total_trades:,}")
        print(f"  First-time trades:     {first_time:,} ({first_time/total_trades*100:.1f}%)" if total_trades > 0 else "  First-time trades:     0")
        print(f"  Unique wallets:        {unique_wallets:,}")
        print(f"  Unique markets:        {unique_markets:,}")
        print(f"  Oldest trade:          {oldest if oldest else 'N/A'}")
        print(f"  Newest trade:          {newest if newest else 'N/A'}")
        print(f"  First insertion:       {first_insert if first_insert else 'N/A'}")
        print(f"  Last insertion:        {last_insert if last_insert else 'N/A'}")

        # Calcul du temps écoulé depuis le dernier insert
        if last_insert:
            now = datetime.now(timezone.utc)
            # last_insert est déjà un objet datetime avec timezone
            if last_insert.tzinfo is None:
                last_insert = last_insert.replace(tzinfo=timezone.utc)

            time_since_last_insert = now - last_insert
            minutes_since = time_since_last_insert.total_seconds() / 60

            print(f"\n  ⏰ Temps depuis dernier insert: {minutes_since:.1f} minutes")

            if minutes_since > 15:
                print(f"  ⚠️  WARNING: Pas de nouveau trade depuis {minutes_since:.1f} minutes!")
                print(f"  ⚠️  Le scheduler devrait synchroniser toutes les 10 minutes")
            else:
                print(f"  ✅ OK: Scheduler semble actif (dernière sync il y a {minutes_since:.1f} min)")

    print()

    # 2. Distribution des trades dans le temps (dernières 24h)
    print("📈 DISTRIBUTION DES TRADES (DERNIÈRES 24H)")
    print("-" * 80)

    cursor.execute("""
        SELECT
            date_trunc('hour', created_at) as hour,
            COUNT(*) as trades_inserted,
            COUNT(*) FILTER (WHERE is_first_time = true) as first_time_trades
        FROM smart_wallet_trades
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY date_trunc('hour', created_at)
        ORDER BY hour DESC
        LIMIT 24;
    """)

    time_distribution = cursor.fetchall()
    if time_distribution:
        headers = ["Heure", "Trades insérés", "First-time"]
        table_data = []
        for hour, trades, first_time in time_distribution:
            table_data.append([hour.strftime("%Y-%m-%d %H:00"), trades, first_time])

        print_table(table_data, headers)
    else:
        print("  Aucun trade dans les dernières 24h")

    print()

    # 3. Top 10 wallets les plus actifs
    print("👛 TOP 10 WALLETS LES PLUS ACTIFS")
    print("-" * 80)

    cursor.execute("""
        SELECT
            sw.address,
            sw.smartscore,
            sw.win_rate,
            COUNT(swt.id) as total_trades,
            COUNT(*) FILTER (WHERE swt.is_first_time = true) as first_time_trades,
            MAX(swt.timestamp) as last_trade
        FROM smart_wallets sw
        LEFT JOIN smart_wallet_trades swt ON sw.address = swt.wallet_address
        GROUP BY sw.address, sw.smartscore, sw.win_rate
        ORDER BY total_trades DESC
        LIMIT 10;
    """)

    top_wallets = cursor.fetchall()
    if top_wallets:
        headers = ["Wallet", "SmartScore", "Win Rate", "Total", "First-time", "Dernier trade"]
        table_data = []
        for addr, score, wr, total, first_time, last in top_wallets:
            addr_short = f"{addr[:6]}...{addr[-4:]}"
            score_str = f"{score:.2f}" if score else "N/A"
            wr_str = f"{wr*100:.1f}%" if wr else "N/A"
            last_str = last.strftime("%Y-%m-%d %H:%M") if last else "N/A"
            table_data.append([addr_short, score_str, wr_str, total, first_time, last_str])

        print_table(table_data, headers)
    else:
        print("  Aucun wallet trouvé")

    print()

    # 4. Trades first-time récents >= $300 (ce que /smart_trading affiche)
    print("💎 TRADES FIRST-TIME RÉCENTS >= $300 (AFFICHÉS PAR /smart_trading)")
    print("-" * 80)

    cursor.execute("""
        SELECT
            swt.wallet_address,
            swt.market_question,
            swt.outcome,
            swt.side,
            swt.value,
            swt.timestamp,
            swt.created_at
        FROM smart_wallet_trades swt
        WHERE swt.is_first_time = true
        AND swt.value >= 300.0
        ORDER BY swt.timestamp DESC
        LIMIT 20;
    """)

    recent_first_time = cursor.fetchall()
    if recent_first_time:
        headers = ["Wallet", "Market", "Outcome", "Side", "Value $", "Trade Time", "Inserted"]
        table_data = []
        for addr, question, outcome, side, value, ts, created in recent_first_time:
            addr_short = f"{addr[:6]}...{addr[-4:]}"
            question_short = (question[:40] + "...") if question and len(question) > 40 else (question or "N/A")
            ts_str = ts.strftime("%m-%d %H:%M") if ts else "N/A"
            created_str = created.strftime("%m-%d %H:%M") if created else "N/A"
            table_data.append([addr_short, question_short, outcome, side, f"{value:.0f}", ts_str, created_str])

        print_table(table_data, headers)
        print(f"\n  ℹ️  /smart_trading affiche les 10 premiers trades de cette liste")
    else:
        print("  ❌ Aucun trade first-time >= $300 trouvé!")
        print("  ⚠️  Cela signifie que /smart_trading n'affichera rien")

    print()

    # 5. Analyse des markets dans les trades vs markets database
    print("🔍 ANALYSE DES MARKETS")
    print("-" * 80)

    cursor.execute("""
        SELECT
            COUNT(DISTINCT swt.market_id) as total_markets_traded,
            COUNT(DISTINCT m.id) as markets_in_db,
            COUNT(DISTINCT swt.market_id) FILTER (WHERE m.id IS NOT NULL) as markets_matched
        FROM smart_wallet_trades swt
        LEFT JOIN markets m ON swt.market_id = m.condition_id;
    """)

    market_stats = cursor.fetchone()
    if market_stats:
        total_traded, in_db, matched = market_stats
        print(f"  Markets tradés par smart wallets:     {total_traded:,}")
        print(f"  Markets présents dans la DB:          {in_db:,}")
        print(f"  Markets matchés:                       {matched:,}")

        if total_traded > 0:
            match_rate = (matched / total_traded) * 100
            print(f"  Taux de correspondance:                {match_rate:.1f}%")

            if match_rate < 50:
                print(f"\n  ⚠️  WARNING: Seulement {match_rate:.1f}% des markets smart wallet sont dans la DB!")
                print(f"  ⚠️  Beaucoup de trades first-time pourraient ne pas avoir d'infos de market")

    print()

    # 6. Vérification du scheduler (dernières syncs)
    print("⏰ ANALYSE DU SCHEDULER")
    print("-" * 80)

    cursor.execute("""
        SELECT
            date_trunc('minute', created_at) as minute,
            COUNT(*) as trades_inserted
        FROM smart_wallet_trades
        WHERE created_at > NOW() - INTERVAL '2 hours'
        GROUP BY date_trunc('minute', created_at)
        ORDER BY minute DESC
        LIMIT 20;
    """)

    scheduler_activity = cursor.fetchall()
    if scheduler_activity:
        print("  Activité du scheduler (dernières 2h):")
        headers = ["Minute", "Trades insérés"]
        table_data = []
        for minute, count in scheduler_activity:
            table_data.append([minute.strftime("%H:%M"), count])

        print_table(table_data, headers)

        # Vérifier si le scheduler fonctionne toutes les 10 minutes
        if len(scheduler_activity) >= 2:
            latest = scheduler_activity[0][0]
            second_latest = scheduler_activity[1][0]
            diff = (latest - second_latest).total_seconds() / 60

            print(f"\n  ℹ️  Intervalle entre les 2 dernières syncs: {diff:.1f} minutes")

            if 8 <= diff <= 12:
                print(f"  ✅ OK: Scheduler fonctionne correctement (~10 min)")
            else:
                print(f"  ⚠️  WARNING: Intervalle anormal (devrait être ~10 min)")
    else:
        print("  ❌ Aucune activité détectée dans les dernières 2h!")
        print("  ⚠️  Le scheduler ne semble pas fonctionner!")

    print()

    # 7. Recommandations
    print("💡 RECOMMANDATIONS")
    print("-" * 80)

    # Vérifier si tout est OK
    issues = []

    if stats and stats[0] == 0:
        issues.append("❌ Aucun trade dans la base de données")
        issues.append("   → Vérifier que le CSV a été chargé")
        issues.append("   → Vérifier que le backfill initial a été exécuté")

    if last_insert:
        now = datetime.now(timezone.utc)
        if last_insert.tzinfo is None:
            last_insert = last_insert.replace(tzinfo=timezone.utc)
        minutes_since = (now - last_insert).total_seconds() / 60

        if minutes_since > 15:
            issues.append(f"❌ Pas de nouveau trade depuis {minutes_since:.1f} minutes")
            issues.append("   → Le scheduler devrait synchroniser toutes les 10 minutes")
            issues.append("   → Vérifier les logs du service Railway")
            issues.append("   → Vérifier que le scheduler est bien actif")

    if not recent_first_time:
        issues.append("❌ Aucun trade first-time >= $300")
        issues.append("   → /smart_trading n'affichera rien aux utilisateurs")
        issues.append("   → Attendre que les smart wallets tradent sur de nouveaux markets")

    if market_stats and market_stats[0] > 0:
        match_rate = (market_stats[2] / market_stats[0]) * 100 if market_stats[0] > 0 else 0
        if match_rate < 50:
            issues.append(f"⚠️  Seulement {match_rate:.1f}% des markets smart wallet sont dans la DB")
            issues.append("   → Beaucoup de trades peuvent ne pas avoir d'infos de market")
            issues.append("   → Les smart wallets tradent peut-être sur des markets très récents")

    if not issues:
        print("  ✅ Tout semble fonctionner correctement!")
        print("  ✅ Le scheduler synchronise les trades toutes les 10 minutes")
        print("  ✅ Les données sont bien stockées dans smart_wallet_trades")
    else:
        for issue in issues:
            print(f"  {issue}")

    print()
    print("="*80)

    cursor.close()
    conn.close()

if __name__ == "__main__":
    try:
        audit_smart_trading()
    except Exception as e:
        print(f"\n❌ Erreur lors de l'audit: {e}")
        import traceback
        traceback.print_exc()
