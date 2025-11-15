#!/usr/bin/env python3
"""
Smart Wallets Analysis Script
Analyzes smart wallets' latest market positions using Polymarket CLOB API
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

class SmartWalletAnalyzer:
    """Analyze smart wallets' latest positions on Polymarket"""

    def __init__(self):
        self.clob_api_url = "https://clob.polymarket.com"
        self.gamma_api_url = "https://gamma-api.polymarket.com"
        self.rate_limit_delay = 0.1  # 100ms between requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'SmartWalletAnalyzer/1.0',
            'Accept': 'application/json'
        })

    def get_user_positions(self, wallet_address: str) -> List[Dict]:
        """
        Get user positions from Polymarket Data API

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            List of position dictionaries
        """
        try:
            url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Failed to get positions for {wallet_address}: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error getting positions for {wallet_address}: {e}")
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

    def get_active_orders(self, wallet_address: str) -> List[Dict]:
        """
        Get active orders for a wallet using CLOB API

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            List of active orders
        """
        try:
            url = f"{self.clob_api_url}/data/orders"
            params = {'maker_address': wallet_address}

            response = self.session.get(url, params=params, timeout=10)

            if response.status_code == 200:
                return response.json()
            else:
                logger.debug(f"No active orders for {wallet_address}: {response.status_code}")
                return []

        except Exception as e:
            logger.debug(f"Error getting orders for {wallet_address}: {e}")
            return []

    def analyze_wallet(self, wallet_address: str) -> Dict:
        """
        Analyze a single wallet's latest activity

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            Analysis results dictionary
        """
        logger.info(f"Analyzing wallet: {wallet_address}")

        # Get positions
        positions = self.get_user_positions(wallet_address)

        # Get active orders
        orders = self.get_active_orders(wallet_address)

        # Find the most recent activity
        latest_activity = None
        latest_market = None
        latest_value = 0

        # Check positions for recent activity
        for position in positions:
            if position.get('tokens', 0) > 0:  # Has tokens
                market_id = position.get('conditionId')
                if market_id:
                    market_info = self.get_market_info(market_id)
                    if market_info:
                        # Calculate position value
                        tokens = position.get('tokens', 0)
                        avg_price = position.get('avgPrice', 0)
                        position_value = tokens * avg_price

                        if position_value > latest_value:
                            latest_value = position_value
                            latest_market = market_info.get('question', 'Unknown Market')
                            latest_activity = 'position'

        # Check orders for recent activity
        for order in orders:
            if order.get('status') == 'open':
                market_id = order.get('market')
                if market_id:
                    market_info = self.get_market_info(market_id)
                    if market_info:
                        order_value = float(order.get('original_size', 0)) * float(order.get('price', 0))

                        if order_value > latest_value:
                            latest_value = order_value
                            latest_market = market_info.get('question', 'Unknown Market')
                            latest_activity = 'order'

        # Rate limiting
        time.sleep(self.rate_limit_delay)

        return {
            'wallet_address': wallet_address,
            'latest_activity': latest_activity,
            'latest_market': latest_market,
            'latest_value': latest_value,
            'positions_count': len(positions),
            'orders_count': len(orders)
        }

    def analyze_csv(self, input_file: str, output_file: str, max_wallets: int = 50):
        """
        Analyze smart wallets from CSV file

        Args:
            input_file: Input CSV file path
            output_file: Output CSV file path
            max_wallets: Maximum number of wallets to analyze (for testing)
        """
        logger.info(f"Starting analysis of {input_file}")

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

                    # Analyze wallet
                    analysis = self.analyze_wallet(wallet_address)

                    # Combine with original data
                    result_row = {
                        'User': row.get('User', ''),
                        'Adresse': wallet_address,
                        'Smartscore': row.get('Smartscore', ''),
                        'Win Rate': row.get('Win Rate', ''),
                        'Markets': row.get('Markets', ''),
                        'Realized PnL': row.get('Realized PnL', ''),
                        'Latest Activity': analysis['latest_activity'],
                        'Latest Market': analysis['latest_market'],
                        'Latest Value': f"${analysis['latest_value']:.2f}",
                        'Positions Count': analysis['positions_count'],
                        'Orders Count': analysis['orders_count'],
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

                logger.info(f"Analysis complete! Results saved to {output_file}")
                logger.info(f"Processed {len(results)} wallets")
            else:
                logger.warning("No results to save")

        except Exception as e:
            logger.error(f"Error during analysis: {e}")
            raise

def main():
    """Main execution function"""
    analyzer = SmartWalletAnalyzer()

    # File paths
    input_file = "smart_wallets.csv"
    output_file = "smart_wallets_analysis.csv"

    # Analyze first 50 wallets (adjust as needed)
    analyzer.analyze_csv(input_file, output_file, max_wallets=50)

    print(f"\n✅ Analysis complete!")
    print(f"📊 Results saved to: {output_file}")
    print(f"🔍 Check the 'Latest Market' and 'Latest Value' columns for recent activity")

if __name__ == "__main__":
    main()
