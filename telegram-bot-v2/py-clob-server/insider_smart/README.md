# Smart Wallets Analysis

## 📊 Overview

This analysis examines the latest market activity of smart wallets on Polymarket using the CLOB API. The analysis covers 200 smart wallets and provides insights into their recent trading activity, market preferences, and performance metrics.

## 🔍 Analysis Results

### Key Findings

- **Total Wallets Analyzed**: 200
- **Active Wallets**: 200 (100% activity rate)
- **Total Active Value**: $172,091.21
- **Average Trade Value**: $860.46
- **Activity Today**: 105 wallets (52.5%)

### Top Performers

1. **0x509587cb...** - $29,664.55 (SmartScore: 4.50, WinRate: 61.1%)
2. **0x998154d8...** - $25,803.17 (SmartScore: 1.79, WinRate: 85.0%)
3. **0x614dc8d3...** - $19,393.57 (SmartScore: 3.66, WinRate: 66.2%)
4. **0xee00ba33...** - $10,542.70 (SmartScore: 1.72, WinRate: 64.4%)
5. **0xee035898...** - $9,989.49 (SmartScore: 2.85, WinRate: 60.8%)

### Market Analysis

**Most Active Markets:**
- Market 0x6ba1b24f...: 5 wallets ($8,632.97 total)
- Market 0xd8dfd4c7...: 4 wallets ($10,114.01 total)
- Market 0x8df234d3...: 2 wallets ($42.08 total)

### Value Distribution

- **Under $100**: 108 wallets (54.0%)
- **$100 - $1,000**: 67 wallets (33.5%)
- **$1,000 - $10,000**: 21 wallets (10.5%)
- **Over $10,000**: 4 wallets (2.0%)

## 📁 Files Generated

### Analysis Files
- `smart_wallets_final_analysis.csv` - Complete analysis with all columns
- `top_smart_wallets.csv` - Top 50 wallets by latest value
- `smart_wallets_analysis.csv` - Basic analysis results
- `smart_wallets_enhanced_analysis.csv` - Enhanced analysis results

### Scripts
- `analyze_smart_wallets.py` - Basic analysis script
- `enhanced_smart_wallet_analysis.py` - Enhanced analysis with better market resolution
- `final_smart_wallet_analysis.py` - Comprehensive analysis with caching
- `summary_report.py` - Summary report generator

## 🛠️ Technical Details

### APIs Used
- **CLOB API**: `https://clob.polymarket.com` - For active orders
- **Data API**: `https://data-api.polymarket.com` - For positions and trades
- **Gamma API**: `https://gamma-api.polymarket.com` - For market information

### Data Sources
- **Positions**: Current token holdings and values
- **Trades**: Recent trading activity (last 20 trades per wallet)
- **Orders**: Active orders on the orderbook
- **Market Info**: Market names and details

### Analysis Features
- **Market Name Resolution**: Cached market information for better readability
- **Value Calculation**: Accurate position and trade value calculations
- **Activity Prioritization**: Most recent activity (positions > orders > trades)
- **Performance Metrics**: SmartScore and WinRate correlation analysis

## 📈 Key Insights

### Smart Wallet Behavior
1. **High Activity Rate**: 100% of analyzed wallets show recent activity
2. **Value Concentration**: Top 4 wallets account for 44% of total value
3. **Market Preferences**: Clear concentration in specific markets
4. **Performance Correlation**: Higher SmartScore doesn't always correlate with higher values

### Market Trends
1. **Active Markets**: 10+ markets with multiple wallet participation
2. **Value Distribution**: Most wallets (54%) have trades under $100
3. **Recent Activity**: 52.5% of wallets active today
4. **Market Concentration**: Top markets attract multiple smart wallets

## 🚀 Usage

### Running the Analysis
```bash
# Basic analysis (50 wallets)
python3 analyze_smart_wallets.py

# Enhanced analysis (100 wallets)
python3 enhanced_smart_wallet_analysis.py

# Comprehensive analysis (200 wallets)
python3 final_smart_wallet_analysis.py

# Generate summary report
python3 summary_report.py
```

### Customizing Analysis
- Modify `max_wallets` parameter to analyze more/fewer wallets
- Adjust `rate_limit_delay` for API rate limiting
- Change output file names in the scripts

## 📊 Data Columns

### Original Data
- `User`: Hashdive profile URL
- `Adresse`: Wallet address
- `Smartscore`: Performance score
- `Win Rate`: Success rate
- `Markets`: Number of markets traded
- `Realized PnL`: Historical profit/loss

### Analysis Data
- `Latest Activity Type`: Most recent activity (trade/order/position)
- `Latest Market`: Market name of most recent activity
- `Latest Value`: Value of most recent activity
- `Latest Date`: Timestamp of most recent activity
- `Positions Count`: Number of current positions
- `Active Orders Count`: Number of active orders
- `Recent Trades Count`: Number of recent trades
- `Total Position Value`: Sum of all position values
- `Largest Position Market`: Market with highest position value
- `Most Recent Trade Market`: Market of most recent trade
- `Most Recent Order Market`: Market of most recent order

## 🔧 Configuration

### Rate Limiting
- Default: 300ms between API calls
- Adjustable in script parameters
- Respects API rate limits

### Caching
- Market information cached to avoid repeated API calls
- Improves performance and reduces API usage
- Cache cleared between runs

### Error Handling
- Graceful handling of API failures
- Detailed logging for debugging
- Continues analysis even if some wallets fail

## 📝 Notes

- Analysis uses real-time data from Polymarket APIs
- Results may vary based on market conditions
- SmartScore and WinRate from original dataset
- All values in USD
- Timestamps in UTC

## 🎯 Recommendations

### For Trading
1. **Follow Top Performers**: Monitor wallets with highest values and SmartScores
2. **Market Analysis**: Focus on markets with multiple smart wallet participation
3. **Value Distribution**: Consider both high-value and frequent traders
4. **Recent Activity**: Prioritize wallets with recent activity

### For Research
1. **Pattern Analysis**: Study correlation between SmartScore and actual performance
2. **Market Trends**: Analyze which markets attract smart wallets
3. **Value Patterns**: Understand distribution of trade values
4. **Activity Timing**: Study when smart wallets are most active

---

*Analysis completed on 2025-10-15 15:00:48 UTC*
*Total processing time: ~2 minutes for 200 wallets*
