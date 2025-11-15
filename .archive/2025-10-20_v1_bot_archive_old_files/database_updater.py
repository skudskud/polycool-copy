"""
Real-Time Database Updater
Continuously updates market database with fresh data
Handles new market creation and resolved market removal
"""

import time
import schedule
import signal
import sys
from datetime import datetime, timezone
import threading
from market_database import MarketDatabase, initialize_database


class DatabaseUpdater:
    def __init__(self):
        self.db = MarketDatabase()
        self.running = False
        self.update_thread = None
        
    def update_markets_job(self):
        """Job function to update markets"""
        print(f"\n🔄 {datetime.now().strftime('%H:%M:%S')} - Starting market update...")
        
        try:
            updated = self.db.update_database()
            
            if updated:
                database = self.db.load_database()
                total_markets = database['metadata']['total_markets']
                tradeable_markets = len([m for m in database['markets'] if m.get('tradeable', False)])
                
                print(f"✅ Database updated: {total_markets} total, {tradeable_markets} tradeable")
            else:
                print("⏰ Database is fresh, no update needed")
                
        except Exception as e:
            print(f"❌ Update error: {e}")
    
    def cleanup_resolved_markets(self):
        """Remove resolved/inactive markets"""
        print("🧹 Cleaning up resolved markets...")
        
        try:
            database = self.db.load_database()
            markets = database.get('markets', [])
            
            # Filter out inactive markets
            active_markets = []
            removed_count = 0
            
            for market in markets:
                # Check if market is still active and not resolved
                end_date_str = market.get('end_date', '')
                
                try:
                    # Parse end date
                    if end_date_str:
                        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                        now = datetime.now(timezone.utc)
                        
                        # Keep market if it hasn't ended yet and is still active
                        if end_date > now and market.get('active', False):
                            active_markets.append(market)
                        else:
                            removed_count += 1
                    else:
                        # Keep markets without end dates if they're active
                        if market.get('active', False):
                            active_markets.append(market)
                        else:
                            removed_count += 1
                            
                except Exception:
                    # Keep market if date parsing fails
                    if market.get('active', False):
                        active_markets.append(market)
            
            if removed_count > 0:
                # Update database with cleaned markets
                database['markets'] = active_markets
                database['metadata']['total_markets'] = len(active_markets)
                database['metadata']['last_cleaned'] = datetime.now(timezone.utc).isoformat()
                
                self.db.save_database(database)
                print(f"🗑️ Removed {removed_count} resolved markets")
            else:
                print("✅ No cleanup needed")
                
        except Exception as e:
            print(f"❌ Cleanup error: {e}")
    
    def start_scheduler(self):
        """Start the scheduled update process"""
        print("🚀 Starting Real-Time Database Updater")
        print("=" * 50)
        
        # Schedule regular updates
        schedule.every(5).minutes.do(self.update_markets_job)
        schedule.every(30).minutes.do(self.cleanup_resolved_markets)
        
        print("📅 Scheduled updates:")
        print("   • Market data: Every 5 minutes")
        print("   • Cleanup resolved: Every 30 minutes")
        print("   • Press Ctrl+C to stop")
        print()
        
        # Run initial update
        self.update_markets_job()
        
        # Start scheduler loop
        self.running = True
        
        def run_scheduler():
            while self.running:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        
        self.update_thread = threading.Thread(target=run_scheduler)
        self.update_thread.daemon = True
        self.update_thread.start()
        
        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_scheduler()
    
    def stop_scheduler(self):
        """Stop the scheduler"""
        print("\n🛑 Stopping database updater...")
        self.running = False
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=5)
        print("✅ Database updater stopped")


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Received interrupt signal")
    sys.exit(0)


def main():
    # Set up signal handling
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if len(sys.argv) > 1 and sys.argv[1] == '--init':
        print("🏗️ Initializing database...")
        initialize_database()
        return
    
    # Start the updater
    updater = DatabaseUpdater()
    
    try:
        updater.start_scheduler()
    except KeyboardInterrupt:
        updater.stop_scheduler()


if __name__ == "__main__":
    main()
