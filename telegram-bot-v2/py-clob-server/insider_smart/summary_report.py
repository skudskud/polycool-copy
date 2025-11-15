#!/usr/bin/env python3
"""
Smart Wallets Analysis Summary Report
Creates a comprehensive summary of the analysis results
"""

import csv
import json
from datetime import datetime, timezone
from typing import Dict, List
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SmartWalletSummaryReport:
    """Generate comprehensive summary report from analysis results"""

    def __init__(self, analysis_file: str):
        self.analysis_file = analysis_file
        self.results = []

    def load_analysis_data(self):
        """Load analysis data from CSV file"""
        try:
            with open(self.analysis_file, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                self.results = list(reader)

            logger.info(f"Loaded {len(self.results)} wallet analysis results")
            return True

        except Exception as e:
            logger.error(f"Error loading analysis data: {e}")
            return False

    def generate_summary_report(self):
        """Generate comprehensive summary report"""
        if not self.results:
            logger.error("No analysis data loaded")
            return

        print("📊 SMART WALLETS ANALYSIS SUMMARY REPORT")
        print("=" * 80)
        print(f"Analysis Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Total Wallets Analyzed: {len(self.results)}")
        print()

        # 1. Activity Overview
        self._print_activity_overview()

        # 2. Top Performers
        self._print_top_performers()

        # 3. Market Analysis
        self._print_market_analysis()

        # 4. Value Distribution
        self._print_value_distribution()

        # 5. Recent Activity
        self._print_recent_activity()

        # 6. Export Top Wallets
        self._export_top_wallets()

    def _print_activity_overview(self):
        """Print activity overview statistics"""
        print("📈 ACTIVITY OVERVIEW")
        print("-" * 40)

        # Count activity types
        activity_counts = {}
        for result in self.results:
            activity_type = result.get('Latest Activity Type', 'none')
            activity_counts[activity_type] = activity_counts.get(activity_type, 0) + 1

        for activity_type, count in activity_counts.items():
            percentage = (count / len(self.results)) * 100
            print(f"  {activity_type.title()}: {count} wallets ({percentage:.1f}%)")

        # Count wallets with recent activity
        active_wallets = [r for r in self.results if r.get('Latest Value', '$0.00') != '$0.00']
        print(f"  Active Wallets: {len(active_wallets)} ({len(active_wallets)/len(self.results)*100:.1f}%)")
        print()

    def _print_top_performers(self):
        """Print top performing wallets"""
        print("🏆 TOP PERFORMERS BY LATEST VALUE")
        print("-" * 50)

        # Filter wallets with activity
        active_wallets = [r for r in self.results if r.get('Latest Value', '$0.00') != '$0.00']

        if not active_wallets:
            print("  No active wallets found")
            print()
            return

        # Sort by latest value
        sorted_wallets = sorted(active_wallets,
                              key=lambda x: float(x.get('Latest Value', '$0.00').replace('$', '').replace(',', '')),
                              reverse=True)

        print(f"  Top 15 Wallets by Latest Trade Value:")
        for i, wallet in enumerate(sorted_wallets[:15], 1):
            address = wallet['Adresse'][:12] + "..."
            value = wallet['Latest Value']
            market = wallet['Latest Market'][:40] + "..." if len(wallet['Latest Market']) > 40 else wallet['Latest Market']
            smartscore = wallet.get('Smartscore', 'N/A')
            win_rate = wallet.get('Win Rate', 'N/A')

            print(f"  {i:2d}. {address:<15} | {value:>10} | SmartScore: {smartscore} | WinRate: {win_rate}")
            print(f"      Market: {market}")
            print()

    def _print_market_analysis(self):
        """Print market analysis"""
        print("📊 MARKET ANALYSIS")
        print("-" * 30)

        # Count market activity
        market_counts = {}
        market_values = {}

        for result in self.results:
            market = result.get('Latest Market', 'No activity')
            value_str = result.get('Latest Value', '$0.00')

            if market != 'No recent activity' and market != 'No activity' and value_str != '$0.00':
                market_counts[market] = market_counts.get(market, 0) + 1

                # Parse value
                try:
                    value = float(value_str.replace('$', '').replace(',', ''))
                    market_values[market] = market_values.get(market, 0) + value
                except:
                    pass

        if market_counts:
            print(f"  Most Active Markets (by wallet count):")
            sorted_markets = sorted(market_counts.items(), key=lambda x: x[1], reverse=True)

            for market, count in sorted_markets[:10]:
                market_short = market[:50] + "..." if len(market) > 50 else market
                total_value = market_values.get(market, 0)
                print(f"    {market_short}: {count} wallets (${total_value:,.2f} total)")
        else:
            print("  No market activity found")

        print()

    def _print_value_distribution(self):
        """Print value distribution analysis"""
        print("💰 VALUE DISTRIBUTION")
        print("-" * 30)

        # Parse values and create distribution
        values = []
        for result in self.results:
            value_str = result.get('Latest Value', '$0.00')
            try:
                value = float(value_str.replace('$', '').replace(',', ''))
                if value > 0:
                    values.append(value)
            except:
                pass

        if values:
            values.sort(reverse=True)

            print(f"  Total Active Value: ${sum(values):,.2f}")
            print(f"  Average Value: ${sum(values)/len(values):,.2f}")
            print(f"  Median Value: ${values[len(values)//2]:,.2f}")
            print(f"  Highest Value: ${max(values):,.2f}")
            print(f"  Lowest Value: ${min(values):,.2f}")

            # Value ranges
            ranges = [
                (0, 100, "Under $100"),
                (100, 1000, "$100 - $1,000"),
                (1000, 10000, "$1,000 - $10,000"),
                (10000, float('inf'), "Over $10,000")
            ]

            print(f"\n  Value Distribution:")
            for min_val, max_val, label in ranges:
                count = sum(1 for v in values if min_val <= v < max_val)
                percentage = (count / len(values)) * 100 if values else 0
                print(f"    {label}: {count} wallets ({percentage:.1f}%)")
        else:
            print("  No value data found")

        print()

    def _print_recent_activity(self):
        """Print recent activity analysis"""
        print("⏰ RECENT ACTIVITY ANALYSIS")
        print("-" * 35)

        # Analyze dates
        today_activity = 0
        this_week_activity = 0

        for result in self.results:
            date_str = result.get('Latest Date', '')
            if date_str and date_str != 'N/A':
                try:
                    # Parse ISO date
                    activity_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)

                    # Check if today
                    if activity_date.date() == now.date():
                        today_activity += 1

                    # Check if this week
                    days_diff = (now - activity_date).days
                    if days_diff <= 7:
                        this_week_activity += 1

                except:
                    pass

        print(f"  Activity Today: {today_activity} wallets")
        print(f"  Activity This Week: {this_week_activity} wallets")
        print(f"  Total Active: {len([r for r in self.results if r.get('Latest Value', '$0.00') != '$0.00'])} wallets")
        print()

    def _export_top_wallets(self):
        """Export top wallets to a separate CSV file"""
        try:
            # Filter and sort top wallets
            active_wallets = [r for r in self.results if r.get('Latest Value', '$0.00') != '$0.00']
            sorted_wallets = sorted(active_wallets,
                                  key=lambda x: float(x.get('Latest Value', '$0.00').replace('$', '').replace(',', '')),
                                  reverse=True)

            # Export top 50 wallets
            top_wallets = sorted_wallets[:50]

            output_file = "top_smart_wallets.csv"
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                if top_wallets:
                    fieldnames = top_wallets[0].keys()
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(top_wallets)

            print(f"📁 EXPORTED TOP WALLETS")
            print(f"  Top 50 wallets exported to: {output_file}")
            print()

        except Exception as e:
            logger.error(f"Error exporting top wallets: {e}")

def main():
    """Main execution function"""
    analysis_file = "smart_wallets_final_analysis.csv"

    # Create summary report
    report = SmartWalletSummaryReport(analysis_file)

    if report.load_analysis_data():
        report.generate_summary_report()
        print("✅ Summary report complete!")
    else:
        print("❌ Failed to load analysis data")

if __name__ == "__main__":
    main()
