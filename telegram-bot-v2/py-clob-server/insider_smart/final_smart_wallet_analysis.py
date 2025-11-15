#!/usr/bin/env python3
"""
Final Smart Wallets Analysis Script
Enhanced with better market name resolution and comprehensive data
"""

import csv
import json
import time
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FinalSmartWalletAnalyzer:
    """Final analyzer with comprehensive market data and better resolution"""

    def __init__(self):
        self.clob_api_url = "https://clob.polymarket.com"
        self.gamma_api_url = "https://gamma-api.polymarket.com"
        self.data_api_url = "https://data-api.polymarket.com"
        self.rate_limit_delay = 0.3  # 300ms between requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'FinalSmartWalletAnalyzer/1.0',
            'Accept': 'application/json'
        })

        # Cache for market info to avoid repeated API calls
        self.market_cache = {}

    def get_market_info_cached(self, market_id: str) -> Optional[Dict]:
        """
        Get market information with caching

        Args:
            market_id: Market condition ID

        Returns:
            Market information dictionary or None
        """
        if market_id in self.market_cache:
            return self.market_cache[market_id]

        try:
            url = f"{self.gamma_api_url}/markets/{market_id}"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                market_info = response.json()
                self.market_cache[market_id] = market_info
                return market_info
            else:
                logger.debug(f"Market {market_id} not found: {response.status_code}")
                return None

        except Exception as e:
            logger.debug(f"Error getting market {market_id}: {e}")
            return None

    def get_user_positions(self, wallet_address: str) -> List[Dict]:
        """Get user positions from Polymarket Data API"""
        try:
            url = f"{self.data_api_url}/positions?user={wallet_address}"
            response = self.session.get(url, timeout=15)

            if response.status_code == 200:
                return response.json()
            else:
                logger.debug(f"No positions for {wallet_address}: {response.status_code}")
                return []

        except Exception as e:
            logger.debug(f"Error getting positions for {wallet_address}: {e}")
            return []

    def get_recent_trades(self, wallet_address: str) -> List[Dict]:
        """Get recent trades for a wallet"""
        try:
            url = f"{self.data_api_url}/trades?user={wallet_address}&limit=20"
            response = self.session.get(url, timeout=15)

            if response.status_code == 200:
                return response.json()
            else:
                logger.debug(f"No trades for {wallet_address}: {response.status_code}")
                return []

        except Exception as e:
            logger.debug(f"Error getting trades for {wallet_address}: {e}")
            return []

    def get_active_orders(self, wallet_address: str) -> List[Dict]:
        """Get active orders for a wallet"""
        try:
            url = f"{self.clob_api_url}/data/orders"
            params = {'maker_address': wallet_address}

            response = self.session.get(url, params=params, timeout=15)

            if response.status_code == 200:
                return response.json()
            else:
                logger.debug(f"No active orders for {wallet_address}: {response.status_code}")
                return []

        except Exception as e:
            logger.debug(f"Error getting orders for {wallet_address}: {e}")
            return []

    def analyze_wallet_comprehensive(self, wallet_address: str) -> Dict:
        """
        Comprehensive analysis of a single wallet

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            Comprehensive analysis results dictionary
        """
        logger.info(f"Analyzing wallet: {wallet_address}")

        # Get all data sources
        positions = self.get_user_positions(wallet_address)
        trades = self.get_recent_trades(wallet_address)
        orders = self.get_active_orders(wallet_address)

        # Analyze positions with market names
        position_analysis = self._analyze_positions_detailed(positions)

        # Analyze trades with market names
        trade_analysis = self._analyze_trades_detailed(trades)

        # Analyze orders with market names
        order_analysis = self._analyze_orders_detailed(orders)

        # Determine most recent activity
        latest_activity = self._determine_latest_activity_comprehensive(
            position_analysis, order_analysis, trade_analysis
        )

        # Rate limiting
        time.sleep(self.rate_limit_delay)

        return {
            'wallet_address': wallet_address,
            'latest_activity_type': latest_activity['type'],
            'latest_market': latest_activity['market'],
            'latest_value': latest_activity['value'],
            'latest_date': latest_activity['date'],
            'positions_count': len(positions),
            'active_orders_count': len(orders),
            'recent_trades_count': len(trades),
            'total_position_value': position_analysis['total_value'],
            'largest_position_market': position_analysis['largest_market'],
            'largest_position_value': position_analysis['largest_value'],
            'most_recent_trade_market': trade_analysis['most_recent_market'],
            'most_recent_trade_value': trade_analysis['most_recent_value'],
            'most_recent_trade_date': trade_analysis['most_recent_date'],
            'most_recent_order_market': order_analysis['most_recent_market'],
            'most_recent_order_value': order_analysis['most_recent_value'],
            'most_recent_order_date': order_analysis['most_recent_date']
        }

    def _analyze_positions_detailed(self, positions: List[Dict]) -> Dict:
        """Analyze positions with detailed market information"""
        if not positions:
            return {
                'total_value': 0,
                'largest_market': 'No positions',
                'largest_value': 0
            }

        total_value = 0
        largest_market = 'No positions'
        largest_value = 0

        for position in positions:
            tokens = position.get('tokens', 0)
            avg_price = position.get('avgPrice', 0)
            position_value = tokens * avg_price
            total_value += position_value

            if position_value > largest_value:
                largest_value = position_value
                market_id = position.get('conditionId')
                if market_id:
                    market_info = self.get_market_info_cached(market_id)
                    if market_info:
                        largest_market = market_info.get('question', 'Unknown Market')
                    else:
                        largest_market = f"Market {market_id[:10]}..."

        return {
            'total_value': total_value,
            'largest_market': largest_market,
            'largest_value': largest_value
        }

    def _analyze_trades_detailed(self, trades: List[Dict]) -> Dict:
        """Analyze trades with detailed market information"""
        if not trades:
            return {
                'most_recent_market': 'No trades',
                'most_recent_value': 0,
                'most_recent_date': 'N/A'
            }

        # Find most recent trade
        most_recent_trade = None
        latest_timestamp = 0

        for trade in trades:
            timestamp = trade.get('timestamp', 0)
            if timestamp > latest_timestamp:
                latest_timestamp = timestamp
                most_recent_trade = trade

        if most_recent_trade:
            market_id = most_recent_trade.get('conditionId')
            market_name = 'Unknown Market'

            if market_id:
                market_info = self.get_market_info_cached(market_id)
                if market_info:
                    market_name = market_info.get('question', 'Unknown Market')
                else:
                    market_name = f"Market {market_id[:10]}..."

            trade_value = float(most_recent_trade.get('price', 0)) * float(most_recent_trade.get('size', 0))
            trade_date = datetime.fromtimestamp(latest_timestamp).isoformat()

            return {
                'most_recent_market': market_name,
                'most_recent_value': trade_value,
                'most_recent_date': trade_date
            }

        return {
            'most_recent_market': 'No trades',
            'most_recent_value': 0,
            'most_recent_date': 'N/A'
        }

    def _analyze_orders_detailed(self, orders: List[Dict]) -> Dict:
        """Analyze orders with detailed market information"""
        if not orders:
            return {
                'most_recent_market': 'No orders',
                'most_recent_value': 0,
                'most_recent_date': 'N/A'
            }

        # Find most recent order
        most_recent_order = None
        latest_timestamp = 0

        for order in orders:
            created_at = int(order.get('created_at', 0))
            if created_at > latest_timestamp:
                latest_timestamp = created_at
                most_recent_order = order

        if most_recent_order:
            market_id = most_recent_order.get('market')
            market_name = 'Unknown Market'

            if market_id:
                market_info = self.get_market_info_cached(market_id)
                if market_info:
                    market_name = market_info.get('question', 'Unknown Market')
                else:
                    market_name = f"Market {market_id[:10]}..."

            order_value = float(most_recent_order.get('price', 0)) * float(most_recent_order.get('original_size', 0))
            order_date = datetime.fromtimestamp(latest_timestamp).isoformat()

            return {
                'most_recent_market': market_name,
                'most_recent_value': order_value,
                'most_recent_date': order_date
            }

        return {
            'most_recent_market': 'No orders',
            'most_recent_value': 0,
            'most_recent_date': 'N/A'
        }

    def _determine_latest_activity_comprehensive(self, position_analysis: Dict, order_analysis: Dict, trade_analysis: Dict) -> Dict:
        """Determine the most recent activity with comprehensive data"""
        activities = []

        # Add position activity
        if position_analysis['total_value'] > 0:
            activities.append({
                'type': 'position',
                'market': position_analysis['largest_market'],
                'value': position_analysis['total_value'],
                'date': 'Current',
                'timestamp': float('inf')
            })

        # Add order activity
        if order_analysis['most_recent_value'] > 0:
            activities.append({
                'type': 'order',
                'market': order_analysis['most_recent_market'],
                'value': order_analysis['most_recent_value'],
                'date': order_analysis['most_recent_date'],
                'timestamp': datetime.fromisoformat(order_analysis['most_recent_date'].replace('Z', '+00:00')).timestamp() if order_analysis['most_recent_date'] != 'N/A' else 0
            })

        # Add trade activity
        if trade_analysis['most_recent_value'] > 0:
            activities.append({
                'type': 'trade',
                'market': trade_analysis['most_recent_market'],
                'value': trade_analysis['most_recent_value'],
                'date': trade_analysis['most_recent_date'],
                'timestamp': datetime.fromisoformat(trade_analysis['most_recent_date'].replace('Z', '+00:00')).timestamp() if trade_analysis['most_recent_date'] != 'N/A' else 0
            })

        # Return the most recent activity
        if activities:
            return max(activities, key=lambda x: x['timestamp'])
        else:
            return {
                'type': 'none',
                'market': 'No recent activity',
                'value': 0,
                'date': 'N/A'
            }

    def analyze_csv_final(self, input_file: str, output_file: str, max_wallets: int = 200):
        """
        Final comprehensive analysis of smart wallets

        Args:
            input_file: Input CSV file path
            output_file: Output CSV file path
            max_wallets: Maximum number of wallets to analyze
        """
        logger.info(f"Starting final comprehensive analysis of {input_file}")

        results = []
        processed = 0

        try:
            with open(input_file, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)

                for row in reader:
                    if processed >= max_wallets:
                        logger.info(f"Reached limit of {max_wallets} wallets")
                        break

                    wallet_address = row.get('Adresse ', '').strip()
                    if not wallet_address:
                        continue

                    # Analyze wallet with comprehensive method
                    analysis = self.analyze_wallet_comprehensive(wallet_address)

                    # Combine with original data
                    result_row = {
                        'User': row.get('User', ''),
                        'Adresse': wallet_address,
                        'Smartscore': row.get('Smartscore', ''),
                        'Win Rate': row.get('Win Rate', ''),
                        'Markets': row.get('Markets', ''),
                        'Realized PnL': row.get('Realized PnL', ''),
                        'Latest Activity Type': analysis['latest_activity_type'],
                        'Latest Market': analysis['latest_market'],
                        'Latest Value': f"${analysis['latest_value']:.2f}",
                        'Latest Date': analysis['latest_date'],
                        'Positions Count': analysis['positions_count'],
                        'Active Orders Count': analysis['active_orders_count'],
                        'Recent Trades Count': analysis['recent_trades_count'],
                        'Total Position Value': f"${analysis['total_position_value']:.2f}",
                        'Largest Position Market': analysis['largest_position_market'],
                        'Largest Position Value': f"${analysis['largest_position_value']:.2f}",
                        'Most Recent Trade Market': analysis['most_recent_trade_market'],
                        'Most Recent Trade Value': f"${analysis['most_recent_trade_value']:.2f}",
                        'Most Recent Trade Date': analysis['most_recent_trade_date'],
                        'Most Recent Order Market': analysis['most_recent_order_market'],
                        'Most Recent Order Value': f"${analysis['most_recent_order_value']:.2f}",
                        'Most Recent Order Date': analysis['most_recent_order_date'],
                        'Analysis Date': datetime.now(timezone.utc).isoformat()
                    }

                    results.append(result_row)
                    processed += 1

                    if processed % 20 == 0:
                        logger.info(f"Processed {processed} wallets...")

            # Write results to new CSV
            if results:
                with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = results[0].keys()
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(results)

                logger.info(f"Final analysis complete! Results saved to {output_file}")
                logger.info(f"Processed {len(results)} wallets")

                # Print comprehensive summary
                self._print_comprehensive_summary(results)
            else:
                logger.warning("No results to save")

        except Exception as e:
            logger.error(f"Error during final analysis: {e}")
            raise

    def _print_comprehensive_summary(self, results: List[Dict]):
        """Print comprehensive analysis summary"""
        print(f"\n📊 COMPREHENSIVE ANALYSIS SUMMARY")
        print(f"=" * 60)

        # Count activity types
        activity_counts = {}
        for result in results:
            activity_type = result.get('Latest Activity Type', 'none')
            activity_counts[activity_type] = activity_counts.get(activity_type, 0) + 1

        print(f"Activity Types:")
        for activity_type, count in activity_counts.items():
            print(f"  {activity_type}: {count} wallets")

        # Find wallets with highest values
        wallets_with_activity = [r for r in results if r.get('Latest Value', '$0.00') != '$0.00']
        if wallets_with_activity:
            print(f"\nTop 10 Wallets by Latest Value:")
            sorted_wallets = sorted(wallets_with_activity,
                                  key=lambda x: float(x.get('Latest Value', '$0.00').replace('$', '').replace(',', '')),
                                  reverse=True)

            for i, wallet in enumerate(sorted_wallets[:10], 1):
                market_name = wallet['Latest Market'][:60] + "..." if len(wallet['Latest Market']) > 60 else wallet['Latest Market']
                print(f"  {i:2d}. {wallet['Adresse'][:10]}... - {wallet['Latest Value']:>10} - {market_name}")

        # Market analysis
        print(f"\n📈 MARKET ANALYSIS:")
        market_counts = {}
        for result in results:
            market = result.get('Latest Market', 'No activity')
            if market != 'No recent activity' and market != 'No activity':
                market_counts[market] = market_counts.get(market, 0) + 1

        print(f"Most Active Markets:")
        sorted_markets = sorted(market_counts.items(), key=lambda x: x[1], reverse=True)
        for market, count in sorted_markets[:5]:
            market_short = market[:50] + "..." if len(market) > 50 else market
            print(f"  {market_short}: {count} wallets")

def main():
    """Main execution function"""
    analyzer = FinalSmartWalletAnalyzer()

    # File paths
    input_file = "smart_wallets.csv"
    output_file = "smart_wallets_final_analysis.csv"

    # Analyze ALL wallets with comprehensive method
    analyzer.analyze_csv_final(input_file, output_file, max_wallets=2005)

    print(f"\n✅ Final comprehensive analysis complete!")
    print(f"📊 Results saved to: {output_file}")
    print(f"🔍 Check all the new columns for detailed activity analysis")

if __name__ == "__main__":
    main()
