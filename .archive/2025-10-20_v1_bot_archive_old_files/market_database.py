"""
Real-Time Market Database Manager
Handles fetching, updating, and maintaining active market data
"""

import json
import requests
import time
from datetime import datetime, timezone
import os
import shutil
from typing import Dict, List, Optional
from config import DATABASE_CONFIG, GAMMA_API_URL, CLOB_API_URL


class MarketDatabase:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_CONFIG['file']
        self.backup_count = DATABASE_CONFIG['backup_count']
        self.update_interval = DATABASE_CONFIG['update_interval']
        
    def fetch_fresh_markets(self) -> Dict:
        """Fetch fresh market data from APIs"""
        print("🔄 Fetching fresh market data from APIs...")
        
        try:
            # Fetch from Gamma API
            gamma_response = requests.get(GAMMA_API_URL, timeout=30)
            gamma_data = gamma_response.json()
            
            markets = []
            active_count = 0
            
            print(f"📊 Processing {len(gamma_data)} markets from Gamma API...")
            
            for market in gamma_data:
                # Filter for active, unresolved markets
                if (market.get('active', False) and 
                    not market.get('closed', False) and 
                    not market.get('archived', False)):
                    
                    # Enrich with essential trading data
                    enriched_market = {
                        'id': market.get('id'),
                        'question': market.get('question'),
                        'slug': market.get('slug'),
                        'condition_id': market.get('conditionId'),
                        'end_date': market.get('endDate'),
                        'volume': float(market.get('volume', 0)),
                        'liquidity': float(market.get('liquidity', 0)),
                        'active': market.get('active', False),
                        'enable_order_book': market.get('enableOrderBook', False),
                        'accepting_orders': market.get('acceptingOrders', False),
                        'outcomes': market.get('outcomes', []),
                        'outcome_prices': market.get('outcomePrices', []),
                        'clob_token_ids': market.get('clobTokenIds', []),
                        'last_updated': datetime.now(timezone.utc).isoformat(),
                        'tradeable': self._is_tradeable(market)
                    }
                    
                    markets.append(enriched_market)
                    active_count += 1
            
            database = {
                'metadata': {
                    'last_updated': datetime.now(timezone.utc).isoformat(),
                    'total_markets': len(markets),
                    'active_markets': active_count,
                    'data_sources': ['Gamma API', 'CLOB API'],
                    'update_interval': self.update_interval
                },
                'markets': markets
            }
            
            print(f"✅ Processed {active_count} active markets")
            return database
            
        except Exception as e:
            print(f"❌ Error fetching markets: {e}")
            return self._load_backup_database()
    
    def _is_tradeable(self, market: Dict) -> bool:
        """Determine if market is good for trading"""
        volume = float(market.get('volume', 0))
        liquidity = float(market.get('liquidity', 0))
        
        return (
            market.get('active', False) and
            market.get('enableOrderBook', False) and 
            market.get('acceptingOrders', False) and
            volume >= 1000 and  # $1K minimum volume
            liquidity >= 100    # $100 minimum liquidity
        )
    
    def save_database(self, database: Dict):
        """Save database with backup rotation"""
        # Create backup of existing database
        if os.path.exists(self.db_path):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{self.db_path}.backup_{timestamp}"
            shutil.copy2(self.db_path, backup_path)
            
            # Rotate backups (keep only recent ones)
            self._rotate_backups()
        
        # Save new database
        with open(self.db_path, 'w') as f:
            json.dump(database, f, indent=2)
        
        print(f"💾 Database saved: {database['metadata']['total_markets']} markets")
    
    def load_database(self) -> Dict:
        """Load database from file"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"❌ Error loading database: {e}")
                return self._create_empty_database()
        else:
            print("📁 No database found, creating fresh one...")
            return self._create_empty_database()
    
    def _rotate_backups(self):
        """Keep only recent backups"""
        backup_files = []
        for file in os.listdir('.'):
            if file.startswith(f"{self.db_path}.backup_"):
                backup_files.append(file)
        
        # Sort by modification time, keep only recent ones
        backup_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        
        for old_backup in backup_files[self.backup_count:]:
            try:
                os.remove(old_backup)
                print(f"🗑️ Removed old backup: {old_backup}")
            except:
                pass
    
    def _load_backup_database(self) -> Dict:
        """Load most recent backup if main database fails"""
        backup_files = []
        for file in os.listdir('.'):
            if file.startswith(f"{self.db_path}.backup_"):
                backup_files.append(file)
        
        if backup_files:
            latest_backup = max(backup_files, key=lambda x: os.path.getmtime(x))
            print(f"🔄 Loading backup database: {latest_backup}")
            
            try:
                with open(latest_backup, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        return self._create_empty_database()
    
    def _create_empty_database(self) -> Dict:
        """Create empty database structure"""
        return {
            'metadata': {
                'last_updated': datetime.now(timezone.utc).isoformat(),
                'total_markets': 0,
                'active_markets': 0,
                'data_sources': [],
                'update_interval': self.update_interval
            },
            'markets': []
        }
    
    def update_database(self, force: bool = False) -> bool:
        """Update database if needed"""
        database = self.load_database()
        
        # Check if update needed
        if not force and database.get('metadata'):
            last_updated = database['metadata'].get('last_updated')
            if last_updated:
                last_update_time = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                time_since_update = datetime.now(timezone.utc) - last_update_time
                
                if time_since_update.total_seconds() < self.update_interval:
                    print(f"⏰ Database is fresh ({time_since_update.total_seconds():.0f}s old)")
                    return False
        
        # Fetch and save fresh data
        fresh_database = self.fetch_fresh_markets()
        if fresh_database['metadata']['total_markets'] > 0:
            self.save_database(fresh_database)
            return True
        else:
            print("❌ No fresh data available, keeping existing database")
            return False
    
    def get_high_volume_markets(self, limit: int = 50) -> List[Dict]:
        """Get markets sorted by volume (best for trading)"""
        database = self.load_database()
        markets = database.get('markets', [])
        
        # Filter tradeable markets and sort by volume
        tradeable_markets = [m for m in markets if m.get('tradeable', False)]
        sorted_markets = sorted(tradeable_markets, 
                              key=lambda x: x.get('volume', 0), 
                              reverse=True)
        
        return sorted_markets[:limit]
    
    def search_markets(self, query: str) -> List[Dict]:
        """Search markets by question text"""
        database = self.load_database()
        markets = database.get('markets', [])
        
        query_lower = query.lower()
        matching_markets = []
        
        for market in markets:
            question = market.get('question', '').lower()
            if query_lower in question and market.get('tradeable', False):
                matching_markets.append(market)
        
        # Sort by volume
        return sorted(matching_markets, 
                     key=lambda x: x.get('volume', 0), 
                     reverse=True)


def initialize_database():
    """Initialize fresh market database"""
    print("🚀 Initializing Market Database...")
    
    db = MarketDatabase()
    
    # Copy from existing gamma_complete_markets.json if available
    if os.path.exists('../gamma_complete_markets.json'):
        print("📋 Found existing market data, processing...")
        try:
            with open('../gamma_complete_markets.json', 'r') as f:
                existing_data = json.load(f)
            
            # Extract markets from existing data
            markets = existing_data.get('markets', [])
            
            processed_markets = []
            for market in markets[:3000]:  # Limit to 3000 for performance
                if market.get('active', False):
                    processed_market = {
                        'id': market.get('id'),
                        'question': market.get('question'),
                        'slug': market.get('slug') or market.get('marketSlug'),
                        'condition_id': market.get('conditionId'),
                        'end_date': market.get('endDate'),
                        'volume': float(market.get('volume', 0)),
                        'liquidity': float(market.get('liquidity', 0)),
                        'active': market.get('active', False),
                        'enable_order_book': market.get('enableOrderBook', False),
                        'accepting_orders': market.get('acceptingOrders', False),
                        'outcomes': market.get('outcomes', []),
                        'outcome_prices': market.get('outcomePrices', []),
                        'clob_token_ids': market.get('clobTokenIds', []),
                        'last_updated': datetime.now(timezone.utc).isoformat(),
                        'tradeable': db._is_tradeable(market)
                    }
                    processed_markets.append(processed_market)
            
            database = {
                'metadata': {
                    'last_updated': datetime.now(timezone.utc).isoformat(),
                    'total_markets': len(processed_markets),
                    'active_markets': len(processed_markets),
                    'data_sources': ['Existing Data Import'],
                    'update_interval': db.update_interval
                },
                'markets': processed_markets
            }
            
            db.save_database(database)
            print(f"✅ Imported {len(processed_markets)} markets from existing data")
            
        except Exception as e:
            print(f"❌ Error importing existing data: {e}")
            # Fallback to API fetch
            db.update_database(force=True)
    else:
        # Fresh fetch from API
        db.update_database(force=True)
    
    return db


if __name__ == "__main__":
    # Initialize database for first time
    initialize_database()
