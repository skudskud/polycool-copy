#!/usr/bin/env python3
"""
Check if a specific market is really closed on Polymarket
"""
import asyncio
import httpx

# Market from smart wallet trades
MARKET_ID = "0x7ff9d367be935d0568a039820978f6b85da1d4639d0a4e7b52eca336d037ffac"
MARKET_QUESTION = "Counter-Strike: Imperial vs Venom (BO3)"

GAMMA_API_URL = "https://gamma-api.polymarket.com"

async def check_market():
    print(f'🔍 Vérification du market: {MARKET_QUESTION}')
    print(f'Market ID: {MARKET_ID}')
    print('='*80)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Try 1: Get by condition_id via markets endpoint
        print(f'\n📡 Requête 1: GET /markets/{MARKET_ID}')
        response = await client.get(f"{GAMMA_API_URL}/markets/{MARKET_ID}")
        print(f'Status: {response.status_code}')

        if response.status_code == 200:
            data = response.json()
            print('\n✅ MARKET TROUVÉ sur Polymarket!')
            print('-'*80)
            print(f"Question: {data.get('question')}")
            print(f"Active: {data.get('active')}")
            print(f"Closed: {data.get('closed')}")
            print(f"Accepting Orders: {data.get('accepting_orders')}")
            print(f"Volume: ${float(data.get('volume', 0)):,.2f}")
            print(f"Liquidity: ${float(data.get('liquidity', 0)):,.2f}")
            print(f"End Date: {data.get('end_date_iso')}")
            print(f"Status: {data.get('status')}")

            # Check database status
            print('\n📊 Comparaison avec notre DB:')
            print('-'*80)
            import os
            from dotenv import load_dotenv
            import psycopg2

            load_dotenv()
            DATABASE_URL = os.getenv('DATABASE_URL')

            if DATABASE_URL:
                conn = psycopg2.connect(DATABASE_URL)
                cur = conn.cursor()

                cur.execute("""
                    SELECT id, active, closed, tradeable, end_date, last_updated
                    FROM markets
                    WHERE condition_id = %s
                """, (MARKET_ID,))

                result = cur.fetchone()
                if result:
                    db_id, db_active, db_closed, db_tradeable, db_end_date, db_last_updated = result
                    print(f'✅ Market TROUVÉ dans notre DB (id={db_id})')
                    print(f'   Active: {db_active}')
                    print(f'   Closed: {db_closed}')
                    print(f'   Tradeable: {db_tradeable}')
                    print(f'   End Date: {db_end_date}')
                    print(f'   Last Updated: {db_last_updated}')

                    # Comparison
                    print('\n🔍 DIFFÉRENCES:')
                    polymarket_active = data.get('active')
                    polymarket_closed = data.get('closed')
                    polymarket_accepting = data.get('accepting_orders')

                    if db_active != polymarket_active:
                        print(f'  ⚠️  Active: DB={db_active}, Polymarket={polymarket_active}')
                    if db_closed != polymarket_closed:
                        print(f'  ⚠️  Closed: DB={db_closed}, Polymarket={polymarket_closed}')
                    if db_tradeable != polymarket_accepting:
                        print(f'  ⚠️  Tradeable/Accepting: DB={db_tradeable}, Polymarket={polymarket_accepting}')

                    if db_active == polymarket_active and db_closed == polymarket_closed and db_tradeable == polymarket_accepting:
                        print('  ✅ Aucune différence - DB est à jour')
                else:
                    print('❌ Market PAS TROUVÉ dans notre DB')
                    print('   → Le market existe sur Polymarket mais pas dans notre DB')
                    print('   → Notre market updater ne l\'a pas encore synchronisé')

                cur.close()
                conn.close()

            # Conclusion
            print('\n🎯 CONCLUSION:')
            print('='*80)
            if data.get('active') and not data.get('closed') and data.get('accepting_orders'):
                print('✅ Ce market est ACTIF et TRADEABLE sur Polymarket')
                print('   → Il DEVRAIT apparaître dans /smart_trading')
                if not result:
                    print('   → PROBLÈME: Market pas dans notre DB')
                    print('   → SOLUTION: Améliorer le market updater')
            else:
                print('❌ Ce market est FERMÉ sur Polymarket')
                print('   → Normal qu\'il n\'apparaisse pas dans /smart_trading')

        elif response.status_code == 422:
            print('\n⚠️  HTTP 422 - Market not found via /markets endpoint')
            print('Le market est probablement fermé/archivé par Polymarket')

        else:
            print(f'\n❌ Erreur HTTP {response.status_code}')
            print(response.text[:200])

if __name__ == "__main__":
    asyncio.run(check_market())
