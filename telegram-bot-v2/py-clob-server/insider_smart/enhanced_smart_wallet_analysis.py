#!/usr/bin/env python3
"""
Enhanced Smart Wallets Analysis Script
Uses CLOB API to get active orders and recent positions
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

class EnhancedSmartWalletAnalyzer:
    """Enhanced analyzer using CLOB API for active orders and positions"""

    def __init__(self):
        self.clob_api_url = "https://clob.polymarket.com"
        self.gamma_api_url = "https://gamma-api.polymarket.com"
        self.data_api_url = "https://data-api.polymarket.com"
        self.rate_limit_delay = 0.2  # 200ms between requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'EnhancedSmartWalletAnalyzer/1.0',
            'Accept': 'application/json'
        })

    def get_active_orders(self, wallet_address: str) -> List[Dict]:
        """
        Get active orders for a wallet using CLOB API

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            List of active orders with market info
        """
        try:
            url = f"{self.clob_api_url}/data/orders"
            params = {'maker_address': wallet_address}

            response = self.session.get(url, params=params, timeout=15)

            if response.status_code == 200:
                orders = response.json()
                logger.debug(f"Found {len(orders)} active orders for {wallet_address}")
                return orders
            else:
                logger.debug(f"No active orders for {wallet_address}: {response.status_code}")
                return []

        except Exception as e:
            logger.debug(f"Error getting orders for {wallet_address}: {e}")
            return []

    def get_market_info(self, market_id: str) -> Optional[Dict]:
        """
        Get market information from Gamma API

        Args:
            market_id: Market condition ID

        Returns:
            Market information dictionary or None
        """
        try:
            url = f"{self.gamma_api_url}/markets/{market_id}"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                return response.json()
            else:
                logger.debug(f"Market {market_id} not found: {response.status_code}")
                return None

        except Exception as e:
            logger.debug(f"Error getting market {market_id}: {e}")
            return None

    def get_user_positions(self, wallet_address: str) -> List[Dict]:
        """
        Get user positions from Polymarket Data API

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            List of position dictionaries
        """
        try:
            url = f"{self.data_api_url}/positions?user={wallet_address}"
            response = self.session.get(url, timeout=15)

            if response.status_code == 200:
                positions = response.json()
                logger.debug(f"Found {len(positions)} positions for {wallet_address}")
                return positions
            else:
                logger.debug(f"No positions for {wallet_address}: {response.status_code}")
                return []

        except Exception as e:
            logger.debug(f"Error getting positions for {wallet_address}: {e}")
            return []

    def get_recent_trades(self, wallet_address: str) -> List[Dict]:
        """
        Get recent trades for a wallet

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            List of recent trades
        """
        try:
            url = f"{self.data_api_url}/trades?user={wallet_address}&limit=10"
            response = self.session.get(url, timeout=15)

            if response.status_code == 200:
                trades = response.json()
                logger.debug(f"Found {len(trades)} recent trades for {wallet_address}")
                return trades
            else:
                logger.debug(f"No trades for {wallet_address}: {response.status_code}")
                return []

        except Exception as e:
            logger.debug(f"Error getting trades for {wallet_address}: {e}")
            return []

    def analyze_wallet_enhanced(self, wallet_address: str) -> Dict:
        """
        Enhanced analysis of a single wallet's activity

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            Enhanced analysis results dictionary
        """
        logger.info(f"Analyzing wallet: {wallet_address}")

        # Get all data sources
        positions = self.get_user_positions(wallet_address)
        orders = self.get_active_orders(wallet_address)
        trades = self.get_recent_trades(wallet_address)

        # Analyze positions
        position_analysis = self._analyze_positions(positions)

        # Analyze orders
        order_analysis = self._analyze_orders(orders)

        # Analyze trades
        trade_analysis = self._analyze_trades(trades)

        # Determine most recent activity
        latest_activity = self._determine_latest_activity(
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
            'largest_position': position_analysis['largest_position'],
            'most_recent_order': order_analysis['most_recent'],
            'most_recent_trade': trade_analysis['most_recent']
        }

    def _analyze_positions(self, positions: List[Dict]) -> Dict:
        """Analyze positions data"""
        if not positions:
            return {'total_value': 0, 'largest_position': None}

        total_value = 0
        largest_position = None
        max_value = 0

        for position in positions:
            tokens = position.get('tokens', 0)
            avg_price = position.get('avgPrice', 0)
            position_value = tokens * avg_price
            total_value += position_value

            if position_value > max_value:
                max_value = position_value
                largest_position = {
                    'market_id': position.get('conditionId'),
                    'tokens': tokens,
                    'avg_price': avg_price,
                    'value': position_value
                }

        return {
            'total_value': total_value,
            'largest_position': largest_position
        }

    def _analyze_orders(self, orders: List[Dict]) -> Dict:
        """Analyze orders data"""
        if not orders:
            return {'most_recent': None}

        # Find most recent order
        most_recent = None
        latest_timestamp = 0

        for order in orders:
            created_at = int(order.get('created_at', 0))
            if created_at > latest_timestamp:
                latest_timestamp = created_at
                most_recent = {
                    'market_id': order.get('market'),
                    'side': order.get('side'),
                    'price': order.get('price'),
                    'size': order.get('original_size'),
                    'created_at': created_at
                }

        return {'most_recent': most_recent}

    def _analyze_trades(self, trades: List[Dict]) -> Dict:
        """Analyze trades data"""
        if not trades:
            return {'most_recent': None}

        # Find most recent trade
        most_recent = None
        latest_timestamp = 0

        for trade in trades:
            timestamp = trade.get('timestamp', 0)
            if timestamp > latest_timestamp:
                latest_timestamp = timestamp
                most_recent = {
                    'market_id': trade.get('conditionId'),
                    'side': trade.get('side'),
                    'price': trade.get('price'),
                    'size': trade.get('size'),
                    'timestamp': timestamp
                }

        return {'most_recent': most_recent}

    def _determine_latest_activity(self, position_analysis: Dict, order_analysis: Dict, trade_analysis: Dict) -> Dict:
        """Determine the most recent activity"""
        activities = []

        # Add position activity
        if position_analysis['largest_position']:
            activities.append({
                'type': 'position',
                'market': 'Position in market',
                'value': position_analysis['total_value'],
                'date': 'Current',
                'timestamp': float('inf')
            })

        # Add order activity
        if order_analysis['most_recent']:
            order = order_analysis['most_recent']
            market_info = self.get_market_info(order['market_id'])
            market_name = market_info.get('question', 'Unknown Market') if market_info else 'Unknown Market'

            activities.append({
                'type': 'order',
                'market': market_name,
                'value': float(order['price']) * float(order['size']),
                'date': datetime.fromtimestamp(order['created_at']).isoformat(),
                'timestamp': order['created_at']
            })

        # Add trade activity
        if trade_analysis['most_recent']:
            trade = trade_analysis['most_recent']
            market_info = self.get_market_info(trade['market_id'])
            market_name = market_info.get('question', 'Unknown Market') if market_info else 'Unknown Market'

            activities.append({
                'type': 'trade',
                'market': market_name,
                'value': float(trade['price']) * float(trade['size']),
                'date': datetime.fromtimestamp(trade['timestamp']).isoformat(),
                'timestamp': trade['timestamp']
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

    def analyze_csv_enhanced(self, input_file: str, output_file: str, max_wallets: int = 100):
        """
        Enhanced analysis of smart wallets from CSV file

        Args:
            input_file: Input CSV file path
            output_file: Output CSV file path
            max_wallets: Maximum number of wallets to analyze
        """
        logger.info(f"Starting enhanced analysis of {input_file}")

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

                    # Analyze wallet with enhanced method
                    analysis = self.analyze_wallet_enhanced(wallet_address)

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
                        'Analysis Date': datetime.now(timezone.utc).isoformat()
                    }

                    results.append(result_row)
                    processed += 1

                    if processed % 10 == 0:
                        logger.info(f"Processed {processed} wallets...")

            # Write results to new CSV
            if results:
                with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = results[0].keys()
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(results)

                logger.info(f"Enhanced analysis complete! Results saved to {output_file}")
                logger.info(f"Processed {len(results)} wallets")

                # Print summary
                self._print_summary(results)
            else:
                logger.warning("No results to save")

        except Exception as e:
            logger.error(f"Error during enhanced analysis: {e}")
            raise

    def _print_summary(self, results: List[Dict]):
        """Print analysis summary"""
        print(f"\n📊 ANALYSIS SUMMARY")
        print(f"=" * 50)

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
            print(f"\nTop 5 Wallets by Latest Value:")
            sorted_wallets = sorted(wallets_with_activity,
                                  key=lambda x: float(x.get('Latest Value', '$0.00').replace('$', '').replace(',', '')),
                                  reverse=True)

            for i, wallet in enumerate(sorted_wallets[:5], 1):
                print(f"  {i}. {wallet['Adresse'][:10]}... - {wallet['Latest Value']} - {wallet['Latest Market'][:50]}...")

def main():
    """Main execution function"""
    analyzer = EnhancedSmartWalletAnalyzer()

    # File paths
    input_file = "smart_wallets.csv"
    output_file = "smart_wallets_enhanced_analysis.csv"

    # Analyze first 100 wallets with enhanced method
    analyzer.analyze_csv_enhanced(input_file, output_file, max_wallets=100)

    print(f"\n✅ Enhanced analysis complete!")
    print(f"📊 Results saved to: {output_file}")
    print(f"🔍 Check the new columns for detailed activity analysis")

if __name__ == "__main__":
    main()
