#!/usr/bin/env python3
"""
Curated Smart Traders Activity Analysis
Analyzes buy/sell frequency and new market discoveries
"""

import csv
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set
import logging
from collections import defaultdict

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TradingActivityAnalyzer:
    """Analyze trading activity patterns for smart traders"""

    def __init__(self):
        self.data_api_url = "https://data-api.polymarket.com"
        self.rate_limit_delay = 0.3  # 300ms between requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'TradingActivityAnalyzer/1.0',
            'Accept': 'application/json'
        })

    def get_all_trades(self, wallet_address: str, limit: int = 1000) -> List[Dict]:
        """
        Get all trades for a wallet (up to limit)

        Args:
            wallet_address: Ethereum wallet address
            limit: Maximum number of trades to fetch

        Returns:
            List of trade dictionaries
        """
        try:
            url = f"{self.data_api_url}/trades"
            params = {
                'user': wallet_address,
                'limit': limit
            }

            response = self.session.get(url, params=params, timeout=15)

            if response.status_code == 200:
                trades = response.json()
                logger.debug(f"Found {len(trades)} trades for {wallet_address}")
                return trades
            else:
                logger.debug(f"No trades for {wallet_address}: {response.status_code}")
                return []

        except Exception as e:
            logger.debug(f"Error getting trades for {wallet_address}: {e}")
            return []

    def analyze_wallet_activity(self, wallet_address: str) -> Dict:
        """
        Comprehensive activity analysis for a wallet

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            Analysis results dictionary
        """
        logger.info(f"Analyzing wallet: {wallet_address}")

        # Get all trades (up to 1000)
        all_trades = self.get_all_trades(wallet_address, limit=1000)

        if not all_trades:
            logger.warning(f"No trades found for {wallet_address}")
            return {
                'wallet_address': wallet_address,
                'total_trades': 0,
                'avg_buys_per_day_5d': 0,
                'avg_sells_per_day_5d': 0,
                'avg_trades_per_day_5d': 0,
                'new_markets_5d': 0,
                'total_unique_markets': 0,
                'oldest_trade_date': 'N/A',
                'newest_trade_date': 'N/A'
            }

        # Calculate cutoff date (5 days ago)
        now = datetime.now(timezone.utc)
        five_days_ago = now - timedelta(days=5)

        # Analyze trades
        trades_last_5d = []
        buys_last_5d = 0
        sells_last_5d = 0

        # Track all markets ever traded (with first trade timestamp)
        market_first_trades = {}  # {market_id: timestamp}

        # Track markets first bought in last 5 days
        new_markets_5d = set()

        oldest_trade_ts = float('inf')
        newest_trade_ts = 0

        for trade in all_trades:
            timestamp = trade.get('timestamp', 0)
            market_id = trade.get('conditionId', '')
            side = trade.get('side', '')

            if not market_id or not side:
                continue

            # Track oldest and newest trades
            if timestamp < oldest_trade_ts:
                oldest_trade_ts = timestamp
            if timestamp > newest_trade_ts:
                newest_trade_ts = timestamp

            # Track first trade per market (globally)
            if market_id not in market_first_trades:
                market_first_trades[market_id] = timestamp

            # Analyze last 5 days
            trade_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)

            if trade_date >= five_days_ago:
                trades_last_5d.append(trade)

                if side.upper() == 'BUY':
                    buys_last_5d += 1
                elif side.upper() == 'SELL':
                    sells_last_5d += 1

                # Check if this is a NEW market in the last 5 days
                # (first trade on this market ever happened in last 5 days)
                if market_first_trades[market_id] >= five_days_ago.timestamp():
                    new_markets_5d.add(market_id)

        # Calculate averages
        total_trades_5d = len(trades_last_5d)
        avg_buys_per_day = buys_last_5d / 5
        avg_sells_per_day = sells_last_5d / 5
        avg_trades_per_day = total_trades_5d / 5

        # Format dates
        oldest_date = datetime.fromtimestamp(oldest_trade_ts, tz=timezone.utc).isoformat() if oldest_trade_ts != float('inf') else 'N/A'
        newest_date = datetime.fromtimestamp(newest_trade_ts, tz=timezone.utc).isoformat() if newest_trade_ts != 0 else 'N/A'

        # Rate limiting
        time.sleep(self.rate_limit_delay)

        return {
            'wallet_address': wallet_address,
            'total_trades': len(all_trades),
            'avg_buys_per_day_5d': round(avg_buys_per_day, 2),
            'avg_sells_per_day_5d': round(avg_sells_per_day, 2),
            'avg_trades_per_day_5d': round(avg_trades_per_day, 2),
            'buys_last_5d': buys_last_5d,
            'sells_last_5d': sells_last_5d,
            'total_trades_5d': total_trades_5d,
            'new_markets_5d': len(new_markets_5d),
            'total_unique_markets': len(market_first_trades),
            'oldest_trade_date': oldest_date,
            'newest_trade_date': newest_date
        }

    def analyze_csv(self, input_file: str, output_file: str, test_mode: bool = False, max_wallets: int = 2):
        """
        Analyze wallets from CSV file

        Args:
            input_file: Input CSV file path
            output_file: Output CSV file path
            test_mode: If True, only analyze first max_wallets wallets
            max_wallets: Number of wallets to analyze in test mode
        """
        logger.info(f"Starting analysis of {input_file}")

        results = []
        processed = 0

        # Track unique wallets
        seen_wallets = set()

        try:
            with open(input_file, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)

                for row in reader:
                    wallet_address = row.get('Adresse', '').strip()

                    if not wallet_address:
                        continue

                    # Deduplicate wallets
                    if wallet_address in seen_wallets:
                        logger.debug(f"Skipping duplicate wallet: {wallet_address}")
                        continue

                    seen_wallets.add(wallet_address)

                    # Test mode limit
                    if test_mode and processed >= max_wallets:
                        logger.info(f"Test mode: Reached limit of {max_wallets} wallets")
                        break

                    # Analyze wallet
                    analysis = self.analyze_wallet_activity(wallet_address)

                    # Combine with original data
                    result_row = {
                        'Adresse': wallet_address,
                        'Smartscore': row.get('Smartscore', ''),
                        'Win Rate': row.get('Win Rate', ''),
                        'Markets': row.get('Markets', ''),
                        'Realized PnL': row.get('Realized PnL', ''),
                        'Bucket smart': row.get('Bucket smart', ''),
                        'Bucket last date': row.get('Bucket last date', ''),
                        # New analysis columns
                        'Total Trades (Analyzed)': analysis['total_trades'],
                        'Avg Buys/Day (5d)': analysis['avg_buys_per_day_5d'],
                        'Avg Sells/Day (5d)': analysis['avg_sells_per_day_5d'],
                        'Avg Total Trades/Day (5d)': analysis['avg_trades_per_day_5d'],
                        'Buys Last 5 Days': analysis['buys_last_5d'],
                        'Sells Last 5 Days': analysis['sells_last_5d'],
                        'Total Trades Last 5 Days': analysis['total_trades_5d'],
                        'New Markets (5d)': analysis['new_markets_5d'],
                        'Total Unique Markets': analysis['total_unique_markets'],
                        'Oldest Trade Date': analysis['oldest_trade_date'],
                        'Newest Trade Date': analysis['newest_trade_date'],
                        'Analysis Date': datetime.now(timezone.utc).isoformat()
                    }

                    results.append(result_row)
                    processed += 1

                    logger.info(f"✅ {wallet_address[:12]}... | Avg trades/day: {analysis['avg_trades_per_day_5d']} | New markets: {analysis['new_markets_5d']}")

            # Write results to CSV
            if results:
                with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = results[0].keys()
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(results)

                logger.info(f"Analysis complete! Results saved to {output_file}")
                logger.info(f"Processed {len(results)} unique wallets")

                # Print summary
                self._print_summary(results)
            else:
                logger.warning("No results to save")

        except Exception as e:
            logger.error(f"Error during analysis: {e}")
            raise

    def _print_summary(self, results: List[Dict]):
        """Print analysis summary"""
        print(f"\n📊 TRADING ACTIVITY SUMMARY")
        print(f"=" * 60)

        # Calculate statistics
        total_wallets = len(results)

        avg_trades_per_day_all = [r['Avg Total Trades/Day (5d)'] for r in results if r['Avg Total Trades/Day (5d)'] > 0]
        avg_buys_per_day_all = [r['Avg Buys/Day (5d)'] for r in results if r['Avg Buys/Day (5d)'] > 0]
        avg_sells_per_day_all = [r['Avg Sells/Day (5d)'] for r in results if r['Avg Sells/Day (5d)'] > 0]
        new_markets_all = [r['New Markets (5d)'] for r in results]

        print(f"Total Wallets Analyzed: {total_wallets}")
        print()

        if avg_trades_per_day_all:
            print(f"📈 TRADING FREQUENCY (Last 5 Days):")
            print(f"  Avg Trades/Day (mean): {sum(avg_trades_per_day_all)/len(avg_trades_per_day_all):.2f}")
            if avg_buys_per_day_all:
                print(f"  Avg Buys/Day (mean): {sum(avg_buys_per_day_all)/len(avg_buys_per_day_all):.2f}")
            if avg_sells_per_day_all:
                print(f"  Avg Sells/Day (mean): {sum(avg_sells_per_day_all)/len(avg_sells_per_day_all):.2f}")
            print(f"  Max Trades/Day: {max(avg_trades_per_day_all):.2f}")
            print()

        print(f"🆕 NEW MARKET DISCOVERIES (Last 5 Days):")
        print(f"  Total New Markets: {sum(new_markets_all)}")
        print(f"  Avg New Markets per Wallet: {sum(new_markets_all)/len(new_markets_all):.2f}")
        print(f"  Max New Markets (one wallet): {max(new_markets_all)}")
        print()

        # Top traders by activity
        print(f"🏆 TOP 10 MOST ACTIVE TRADERS (Last 5 Days):")
        sorted_by_trades = sorted(results, key=lambda x: x['Avg Total Trades/Day (5d)'], reverse=True)
        for i, wallet in enumerate(sorted_by_trades[:10], 1):
            address = wallet['Adresse'][:12] + "..."
            avg_trades = wallet['Avg Total Trades/Day (5d)']
            new_markets = wallet['New Markets (5d)']
            print(f"  {i:2d}. {address} | {avg_trades:.2f} trades/day | {new_markets} new markets")
        print()

        # Top market discoverers
        print(f"🔍 TOP 10 MARKET DISCOVERERS (Last 5 Days):")
        sorted_by_new = sorted(results, key=lambda x: x['New Markets (5d)'], reverse=True)
        for i, wallet in enumerate(sorted_by_new[:10], 1):
            address = wallet['Adresse'][:12] + "..."
            new_markets = wallet['New Markets (5d)']
            avg_trades = wallet['Avg Total Trades/Day (5d)']
            print(f"  {i:2d}. {address} | {new_markets} new markets | {avg_trades:.2f} trades/day")

def main():
    """Main execution function"""
    analyzer = TradingActivityAnalyzer()

    # File paths
    input_file = "curated active smart traders  - Feuille 1.csv"
    output_file = "trading_activity_analysis.csv"

    # Test mode with first 2 wallets
    print("🧪 TEST MODE: Analyzing first 2 unique wallets...")
    print()

    analyzer.analyze_csv(input_file, output_file, test_mode=True, max_wallets=2)

    print(f"\n✅ Test analysis complete!")
    print(f"📊 Results saved to: {output_file}")
    print(f"\nIf results look good, run full analysis by setting test_mode=False")

if __name__ == "__main__":
    main()
