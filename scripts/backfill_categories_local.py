#!/usr/bin/env python3
"""
Local script to backfill market categories using OpenAI GPT-4.1-mini.
Runs independently of the Railway bot, connects directly to Supabase.

Usage:
    python scripts/backfill_categories_local.py --top-n 500 --batch-size 50
"""

import os
import sys
import asyncio
import argparse
from pathlib import Path

# Add parent directory to path to import from telegram-bot-v2
sys.path.insert(0, str(Path(__file__).parent.parent / "telegram-bot-v2" / "py-clob-server"))

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker
from openai import OpenAI
import time

# Load environment variables (try multiple locations)
env_paths = [
    "/tmp/backfill.env",
    ".env",
    "telegram-bot-v2/py-clob-server/.env"
]
for env_path in env_paths:
    if Path(env_path).exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()  # Try default .env

# Import the database models
from core.persistence.models import Market


class LocalMarketCategorizer:
    """Local categorizer service using GPT-4.1-mini"""
    
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

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = OpenAI(api_key=api_key)
    
    def categorize_market(self, question: str, retries: int = 3) -> str:
        """Categorize a single market question with retries for rate limiting"""
        try:
            # Validate question
            if not question or len(question.strip()) < 5:
                print(f"⚠️  Short question: '{question}' → Other")
                return "Other"
            
            # Retry logic for rate limiting
            for attempt in range(retries):
                try:
                    # Call OpenAI API
                    response = self.client.chat.completions.create(
                        model="gpt-4o-mini",  # Using standard OpenAI mini model
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": f"Categorize this prediction market: {question}"}
                        ],
                        temperature=0.3,
                        max_tokens=20
                    )
                    
                    raw_category = response.choices[0].message.content.strip()
                    
                    # Normalize category
                    category = self._normalize_category(raw_category)
                    
                    return category
                    
                except Exception as api_error:
                    error_str = str(api_error)
                    if "429" in error_str or "rate" in error_str.lower():
                        if attempt < retries - 1:
                            wait_time = (attempt + 1) * 10  # 10s, 20s, 30s
                            print(f"⚠️  Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{retries})...")
                            time.sleep(wait_time)
                            continue
                        else:
                            print(f"❌ Rate limit exceeded after {retries} attempts")
                            return "Other"
                    else:
                        raise api_error
            
        except Exception as e:
            print(f"❌ Categorization error: {e}")
            return "Other"
    
    def _normalize_category(self, raw: str) -> str:
        """Normalize GPT response to valid category"""
        if not raw:
            return "Other"
        
        raw_lower = raw.lower().strip()
        
        # Direct matches
        for cat in self.CATEGORIES:
            if raw_lower == cat.lower():
                return cat
        
        # Mapping variants
        mappings = {
            "geopolitics": ["politics", "election", "government", "international", "diplomacy", "war"],
            "sports": ["sport", "esports", "esport", "athletics", "competition", "game"],
            "finance": ["business", "economy", "stock", "market", "financial", "commodities"],
            "crypto": ["cryptocurrency", "blockchain", "bitcoin", "ethereum", "defi", "nft", "web3"],
            "other": ["culture", "entertainment", "science", "technology", "tech", "social", "weather", "misc"]
        }
        
        for category, variants in mappings.items():
            for variant in variants:
                if variant in raw_lower:
                    return category.capitalize()
        
        # Default fallback
        print(f"⚠️  Unknown category '{raw}' → Other")
        return "Other"


def main():
    parser = argparse.ArgumentParser(description="Backfill market categories locally")
    parser.add_argument("--top-n", type=int, default=500, help="Number of top markets to process")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for processing")
    parser.add_argument("--dry-run", action="store_true", help="Don't save to database")
    args = parser.parse_args()
    
    # Check environment variables
    database_url = os.getenv("DATABASE_URL")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if not database_url:
        print("❌ DATABASE_URL not set. Please set it in .env file")
        sys.exit(1)
    
    if not openai_key:
        print("❌ OPENAI_API_KEY not set. Please set it in .env file")
        sys.exit(1)
    
    print(f"✅ DATABASE_URL: {database_url[:50]}...")
    print(f"✅ OPENAI_API_KEY: {openai_key[:10]}...")
    print(f"\n🚀 Starting local backfill:")
    print(f"   - Top N markets: {args.top_n}")
    print(f"   - Batch size: {args.batch_size}")
    print(f"   - Dry run: {args.dry_run}")
    print()
    
    # Create database connection
    engine = create_engine(database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    
    # Initialize categorizer
    categorizer = LocalMarketCategorizer(api_key=openai_key)
    
    # Get markets without category
    print("📊 Fetching markets without categories...")
    session = Session()
    
    try:
        # Query top N markets by volume without category
        query = session.query(Market).filter(
            (Market.category == None) | (Market.category == '')
        ).order_by(Market.volume.desc()).limit(args.top_n)
        
        markets = query.all()
        total = len(markets)
        
        print(f"✅ Found {total} markets to categorize\n")
        
        if total == 0:
            print("🎉 All markets already have categories!")
            return
        
        # Process in batches
        categorized = 0
        skipped = 0
        errors = 0
        start_time = time.time()
        
        for i, market in enumerate(markets, 1):
            try:
                question = market.question or ""
                
                if len(question.strip()) < 5:
                    print(f"[{i}/{total}] ⏭️  Skipping market {market.id[:10]}... (no question)")
                    skipped += 1
                    continue
                
                # Categorize
                category = categorizer.categorize_market(question)
                
                # Update database
                if not args.dry_run:
                    market.category = category
                    session.commit()
                
                categorized += 1
                print(f"[{i}/{total}] ✅ {market.id[:10]}... → {category}")
                print(f"         '{question[:60]}...'")
                
                # Rate limiting - be more conservative to avoid 429 errors  
                # Wait longer between requests
                time.sleep(1.5)  # 40 requests per minute max
                
                # Progress update every batch
                if i % args.batch_size == 0:
                    elapsed = time.time() - start_time
                    rate = i / elapsed
                    eta = (total - i) / rate if rate > 0 else 0
                    print(f"\n📊 Progress: {i}/{total} ({i/total*100:.1f}%) | Rate: {rate:.1f} markets/s | ETA: {eta/60:.1f} min\n")
                
            except Exception as e:
                print(f"[{i}/{total}] ❌ Error for market {market.id[:10]}...: {e}")
                errors += 1
                continue
        
        # Final summary
        elapsed = time.time() - start_time
        print(f"\n" + "="*60)
        print(f"✅ BACKFILL COMPLETE")
        print(f"="*60)
        print(f"Total processed: {total}")
        print(f"Categorized: {categorized}")
        print(f"Skipped: {skipped}")
        print(f"Errors: {errors}")
        print(f"Time: {elapsed/60:.1f} minutes")
        print(f"Rate: {total/elapsed:.1f} markets/second")
        
        if args.dry_run:
            print(f"\n⚠️  DRY RUN - No changes saved to database")
        
    finally:
        session.close()


if __name__ == "__main__":
    main()

