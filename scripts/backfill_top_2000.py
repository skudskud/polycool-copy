#!/usr/bin/env python3
"""
Backfill top 2000 ACTIVE markets sorted by volume + liquidity
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "telegram-bot-v2" / "py-clob-server"))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from openai import OpenAI

# Load environment
for env_path in ["/tmp/backfill.env", ".env"]:
    if Path(env_path).exists():
        load_dotenv(env_path)
        break

database_url = os.getenv("DATABASE_URL")
openai_key = os.getenv("OPENAI_API_KEY")

if not database_url or not openai_key:
    print("❌ Missing DATABASE_URL or OPENAI_API_KEY")
    sys.exit(1)

engine = create_engine(database_url, pool_pre_ping=True, pool_recycle=3600)
client = OpenAI(api_key=openai_key)

CATEGORIES = ["Geopolitics", "Sports", "Finance", "Crypto", "Other"]

SYSTEM_PROMPT = """You are a market categorization expert. Categorize prediction markets into EXACTLY one of these categories:

- Geopolitics: Elections, politics, international relations, government, wars, diplomacy
- Sports: All sports including esports, athletics, competitions  
- Finance: Stocks, economy, business, markets, commodities (excluding crypto)
- Crypto: Cryptocurrency, blockchain, DeFi, NFTs, Web3
- Other: Culture, entertainment, science, technology, social trends, weather, misc

Rules:
1. Return ONLY the category name, nothing else
2. Elections/politics → Geopolitics
3. Esports → Sports
4. Crypto/blockchain → Crypto
5. Traditional finance → Finance
6. Everything else → Other"""

def categorize_market(question: str) -> str:
    """Categorize using GPT-4o-mini with retry"""
    try:
        if not question or len(question.strip()) < 5:
            return "Other"
        
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Categorize this prediction market: {question}"}
                    ],
                    temperature=0.1,
                    max_tokens=20
                )
                
                category = response.choices[0].message.content.strip()
                
                # Normalize
                for cat in CATEGORIES:
                    if category.lower() == cat.lower():
                        return cat
                return "Other"
                
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep((attempt + 1) * 10)
                    continue
                raise
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return "Other"

def main():
    print("🚀 BACKFILLING TOP 2000 ACTIVE MARKETS (Vol + Liquidity)")
    print("=" * 70)
    
    conn = engine.connect()
    
    try:
        # Get top 2000 ACTIVE markets by volume + liquidity
        result = conn.execute(text("""
            SELECT market_id, title
            FROM subsquid_markets_poll
            WHERE (category IS NULL OR category = '')
              AND status = 'ACTIVE'
              AND archived = false
            ORDER BY (volume + liquidity) DESC NULLS LAST
            LIMIT 2000
        """))
        
        markets = result.fetchall()
        total = len(markets)
        
        print(f"✅ Found {total} markets to categorize\n")
        
        if total == 0:
            print("🎉 All top 2000 markets already have categories!")
            return
        
        categorized = 0
        errors = 0
        start_time = time.time()
        
        for i, (market_id, title) in enumerate(markets, 1):
            try:
                category = categorize_market(title or "")
                
                # Update with proper transaction handling
                trans = conn.begin()
                try:
                    conn.execute(text("""
                        UPDATE subsquid_markets_poll
                        SET category = :category
                        WHERE market_id = :market_id
                    """), {"category": category, "market_id": market_id})
                    trans.commit()
                    
                    categorized += 1
                    print(f"[{i}/{total}] ✅ {market_id[:10]}... → {category}")
                    if i % 10 == 0:
                        print(f"         '{title[:60]}...'")
                    
                except Exception as db_error:
                    trans.rollback()
                    raise db_error
                
                # Rate limiting
                time.sleep(1.5)
                
                # Progress
                if i % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = i / elapsed
                    eta = (total - i) / rate if rate > 0 else 0
                    print(f"\n📊 Progress: {i}/{total} ({i/total*100:.1f}%) | Rate: {rate:.1f}/s | ETA: {eta/60:.1f} min\n")
                    
            except Exception as e:
                errors += 1
                print(f"[{i}/{total}] ❌ Error for {market_id}: {e}")
                
                # Rollback any pending transaction
                try:
                    if conn.in_transaction():
                        conn.rollback()
                except:
                    pass
                    
                continue
        
        elapsed = time.time() - start_time
        print(f"\n" + "=" * 70)
        print(f"✅ COMPLETE: {categorized}/{total} categorized in {elapsed/60:.1f} min")
        print(f"   Errors: {errors}")
        print(f"   Cost: ~${total * 0.00003:.4f}")
        
    finally:
        conn.close()

if __name__ == "__main__":
    main()


