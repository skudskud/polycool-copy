"""
High-Speed Trading Bot
Ultra-aggressive pricing for instant execution
"""

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
from py_clob_client.constants import POLYGON
from py_clob_client.order_builder.constants import BUY, SELL
import time
import sys
from typing import Dict, List, Optional

# ❌ REMOVED HARDCODED IMPORTS FOR SECURITY - V2 Bot uses UserTrader instead
# from config.config import PRIVATE_KEY, API_CREDENTIALS, AGGRESSIVE_BUY_PREMIUM, AGGRESSIVE_SELL_DISCOUNT
from config.config import AGGRESSIVE_BUY_PREMIUM, AGGRESSIVE_SELL_DISCOUNT  # Keep trading config only
from database import db_manager, Market


class SpeedTrader:
    def __init__(self, private_key=None, api_credentials=None):
        # ❌ LEGACY CLASS - V2 Bot uses UserTrader with user-specific credentials
        # This class kept for reference but not used by telegram bot
        if not private_key or not api_credentials:
            raise ValueError("SpeedTrader requires private_key and api_credentials - use UserTrader in telegram_bot.py instead")
        
        # Initialize CLOB client with provided credentials
        creds = ApiCreds(**api_credentials)
        self.client = ClobClient(
            'https://clob.polymarket.com',
            key=private_key,
            chain_id=POLYGON,
            creds=creds
        )
        
        # Initialize market database
        self.db = MarketDatabase()
        
    def get_live_price(self, token_id: str, side: str) -> float:
        """Get live price for token (BUY or SELL side)"""
        try:
            price_data = self.client.get_price(token_id, side)
            return float(price_data.get('price', 0))
        except Exception as e:
            print(f"❌ Live price error: {e}")
            return 0.0
    
    def get_best_markets(self, limit: int = 10) -> List[Dict]:
        """Get best markets for trading (high volume/liquidity)"""
        return self.db.get_high_volume_markets(limit)
    
    def search_markets(self, query: str) -> List[Dict]:
        """Search for markets by keyword"""
        return self.db.search_markets(query)
    
    def display_market_info(self, market: Dict):
        """Display market information"""
        question = market['question']
        volume = market.get('volume', 0)
        liquidity = market.get('liquidity', 0)
        end_date = market.get('end_date', 'Unknown')
        
        print(f"❓ {question}")
        print(f"📊 Volume: ${volume:,.0f} | Liquidity: ${liquidity:,.0f}")
        print(f"📅 Ends: {end_date}")
        
        # Display token information
        token_ids = market.get('clob_token_ids', [])
        outcomes = market.get('outcomes', [])
        prices = market.get('outcome_prices', [])
        
        # Handle string representations of lists
        if isinstance(prices, str):
            try:
                import ast
                prices = ast.literal_eval(prices)
            except:
                prices = []
        
        if isinstance(outcomes, str):
            try:
                import ast
                outcomes = ast.literal_eval(outcomes)
            except:
                outcomes = []
        
        if len(token_ids) >= 2 and len(outcomes) >= 2 and len(prices) >= 2:
            print(f"✅ {outcomes[0]}: ${float(prices[0]):.4f}")
            print(f"❌ {outcomes[1]}: ${float(prices[1]):.4f}")
        
        print('=' * 60)
    
    def speed_buy(self, market: Dict, outcome: str = 'yes', amount_usd: float = 2.0) -> Optional[str]:
        """Execute ultra-fast buy order"""
        print(f'🚀 SPEED BUY - {outcome.upper()} TOKENS')
        print('=' * 40)
        
        try:
            # Get market data
            token_ids = market.get('clob_token_ids', [])
            outcomes = market.get('outcomes', [])
            prices = market.get('outcome_prices', [])
            
            # Handle string representations
            if isinstance(token_ids, str):
                try:
                    import ast
                    token_ids = ast.literal_eval(token_ids)
                    # Ensure token IDs remain as strings
                    token_ids = [str(token_id) for token_id in token_ids]
                except:
                    token_ids = []
            
            if isinstance(prices, str):
                try:
                    import ast
                    prices = ast.literal_eval(prices)
                except:
                    prices = []
            
            if isinstance(outcomes, str):
                try:
                    import ast
                    outcomes = ast.literal_eval(outcomes)
                except:
                    outcomes = []
            
            if not token_ids or not outcomes or not prices:
                print("❌ Incomplete market data")
                return None
            
            # FIXED: Use outcome-based token matching instead of array index
            # Import utility function for correct token resolution
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            from telegram_bot.utils.token_utils import get_token_id_for_outcome
            
            token_id = get_token_id_for_outcome(market, outcome)
            
            if not token_id:
                print(f"❌ Cannot find token_id for outcome '{outcome}'")
                return None
            
            # Get price for the matched token
            # Find index of matched token to get corresponding price
            token_index = None
            for i, tid in enumerate(token_ids):
                if str(tid) == str(token_id):
                    token_index = i
                    break
            
            if token_index is not None and token_index < len(prices):
                base_price = float(prices[token_index])
                outcome_name = outcomes[token_index] if token_index < len(outcomes) else outcome.upper()
            else:
                base_price = 0.5
                outcome_name = outcome.upper()
            
            print(f"🔍 TOKEN LOOKUP (BUY): outcome={outcome_name}, token_id={token_id[:20]}...")
            
            # Get LIVE market price for BUY side
            live_buy_price = self.get_live_price(token_id, "BUY")
            
            if live_buy_price > 0:
                market_price = live_buy_price
                print(f"📡 Using LIVE price: ${market_price:.4f}")
            else:
                market_price = base_price
                print(f"📊 Using cached price: ${market_price:.4f} (API unavailable)")
            
            # ULTRA-aggressive pricing for INSTANT fill
            ultra_aggressive_premium = 0.02  # +2¢ for guaranteed instant execution
            aggressive_price = market_price + ultra_aggressive_premium
            
            size = max(5, int(amount_usd / aggressive_price))
            
            # FIX: Round to API precision requirements
            aggressive_price = round(aggressive_price, 4)  # Price: max 4 decimals
            actual_cost = round(size * aggressive_price, 2)  # Amount: max 2 decimals
            
            print(f"💰 Market price: ${market_price:.4f}")
            print(f"⚡ ULTRA price: ${aggressive_price:.4f} (+{ultra_aggressive_premium:.3f} = +2¢)")
            print(f"📦 Size: {size} tokens")
            print(f"💵 Cost: ${actual_cost:.2f}")
            print(f"🎯 Outcome: {outcome_name}")
            print(f"🚀 Strategy: INSTANT EXECUTION")
            
            # Place order
            order_args = OrderArgs(
                price=aggressive_price,
                size=size,
                side=BUY,
                token_id=token_id,
            )
            
            signed_order = self.client.create_order(order_args)
            resp = self.client.post_order(signed_order)
            
            order_id = resp.get('orderID', 'Unknown')
            print(f"✅ SPEED BUY PLACED!")
            print(f"📋 Order ID: {order_id}")
            
            return order_id
            
        except Exception as e:
            print(f"❌ Speed buy error: {e}")
            return None
    
    def speed_sell(self, market: Dict, outcome: str = 'yes', tokens_to_sell: int = 5) -> Optional[str]:
        """Execute ultra-fast sell order"""
        print(f'⚡ SPEED SELL - {outcome.upper()} TOKENS')
        print('=' * 40)
        
        try:
            # Get market data
            token_ids = market.get('clob_token_ids', [])
            outcomes = market.get('outcomes', [])
            prices = market.get('outcome_prices', [])
            
            # Handle string representations
            if isinstance(token_ids, str):
                try:
                    import ast
                    token_ids = ast.literal_eval(token_ids)
                    # Ensure token IDs remain as strings
                    token_ids = [str(token_id) for token_id in token_ids]
                except:
                    token_ids = []
            
            if isinstance(prices, str):
                try:
                    import ast
                    prices = ast.literal_eval(prices)
                except:
                    prices = []
            
            if isinstance(outcomes, str):
                try:
                    import ast
                    outcomes = ast.literal_eval(outcomes)
                except:
                    outcomes = []
            
            if not token_ids or not outcomes or not prices:
                print("❌ Incomplete market data")
                return None
            
            # FIXED: Use outcome-based token matching instead of array index
            # Import utility function for correct token resolution
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            from telegram_bot.utils.token_utils import get_token_id_for_outcome
            
            token_id = get_token_id_for_outcome(market, outcome)
            
            if not token_id:
                print(f"❌ Cannot find token_id for outcome '{outcome}'")
                return None
            
            # Get price for the matched token
            # Find index of matched token to get corresponding price
            token_index = None
            for i, tid in enumerate(token_ids):
                if str(tid) == str(token_id):
                    token_index = i
                    break
            
            if token_index is not None and token_index < len(prices):
                base_price = float(prices[token_index])
                outcome_name = outcomes[token_index] if token_index < len(outcomes) else outcome.upper()
            else:
                base_price = 0.5
                outcome_name = outcome.upper()
            
            print(f"🔍 TOKEN LOOKUP (SELL): outcome={outcome_name}, token_id={token_id[:20]}...")
            
            # Get LIVE market price for SELL side  
            live_sell_price = self.get_live_price(token_id, "SELL")
            
            if live_sell_price > 0:
                market_price = live_sell_price
                print(f"📡 Using LIVE sell price: ${market_price:.4f}")
            else:
                market_price = base_price
                print(f"📊 Using cached price: ${market_price:.4f} (API unavailable)")
            
            # NEW: Smart aggressive pricing (percentage-based for low prices)
            if market_price < 0.10:  # Under 10¢ - use percentage
                discount_percent = 0.05  # 5% discount for instant sell
                ultra_aggressive_discount = market_price * discount_percent
                pricing_strategy = f"-{discount_percent*100:.0f}%"
            else:  # Over 10¢ - use fixed amount
                ultra_aggressive_discount = 0.03  # 3¢ discount
                pricing_strategy = "-3¢"
            
            # Ensure price doesn't go negative
            aggressive_price = max(0.001, market_price - ultra_aggressive_discount)
            will_receive = tokens_to_sell * aggressive_price
            
            print(f"💰 Market price: ${market_price:.4f}")
            print(f"⚡ SMART price: ${aggressive_price:.4f} ({pricing_strategy})")
            print(f"📦 Size: {tokens_to_sell} tokens")
            print(f"💵 Receive: ${will_receive:.2f}")
            print(f"🎯 Outcome: {outcome_name}")
            print(f"🚀 Strategy: INSTANT EXECUTION")
            
            # Place LIMIT sell order with aggressive pricing (V1 approach that works!)
            # FIX: Round to API precision requirements
            aggressive_price = round(aggressive_price, 4)  # Price: max 4 decimals
            
            # Use V1 approach - aggressive limit orders (instant due to pricing)
            order_args = OrderArgs(
                price=aggressive_price,
                size=tokens_to_sell,
                side=SELL,
                token_id=token_id,
            )
            signed_order = self.client.create_order(order_args)
            print(f"🚀 Using LIMIT order with aggressive pricing (V1 approach)")
            resp = self.client.post_order(signed_order)
            
            order_id = resp.get('orderID', 'Unknown')
            print(f"✅ SPEED SELL PLACED!")
            print(f"📋 Order ID: {order_id}")
            
            return order_id
            
        except Exception as e:
            print(f"❌ Speed sell error: {e}")
            return None
    
    def monitor_order(self, order_id: str, timeout: int = 30) -> bool:
        """Monitor order until filled or timeout"""
        print(f"👀 Monitoring order: {order_id[:20]}...")
        
        start_time = time.time()
        
        for attempt in range(timeout):
            try:
                orders = self.client.get_orders()
                
                # Check if order still exists
                order_found = False
                for order in orders:
                    if order_id in order.get('id', ''):
                        order_found = True
                        status = order.get('status', '')
                        
                        if status in ['matched', 'filled']:
                            elapsed = int(time.time() - start_time)
                            print(f"🎉 ORDER FILLED! ({elapsed}s)")
                            return True
                        elif attempt % 5 == 0:  # Print every 5th attempt
                            print(f"  ⏰ {attempt}s: {status}")
                        break
                
                if not order_found:
                    elapsed = int(time.time() - start_time)
                    print(f"✅ ORDER COMPLETED! ({elapsed}s)")
                    return True
                
                time.sleep(1)
                
            except Exception as e:
                if attempt % 10 == 0:
                    print(f"  ❌ Monitor error: {str(e)[:30]}...")
                time.sleep(2)
        
        print(f"⏰ Monitoring timeout after {timeout}s")
        return False
    
    def cancel_all_orders(self):
        """Cancel all pending orders"""
        print("🗑️ Cancelling all orders...")
        
        try:
            resp = self.client.cancel_all()
            canceled = resp.get('canceled', [])
            print(f"✅ Canceled {len(canceled)} orders")
            return len(canceled)
        except Exception as e:
            print(f"❌ Cancel error: {e}")
            return 0
    
    def check_balance(self):
        """Check USDC balance"""
        try:
            balance = self.client.get_balance_allowance()
            print(f"💰 USDC.e Balance: ${balance}")
            return balance
        except Exception as e:
            print(f"❌ Balance error: {e}")
            return None


def main():
    if len(sys.argv) < 2:
        print("🚀 SPEED TRADING BOT")
        print("=" * 50)
        print("COMMANDS:")
        print("  python speed_trader.py search <keyword>  # Find markets")  
        print("  python speed_trader.py top               # Show top volume markets")
        print("  python speed_trader.py buy <market_id> <yes/no> <amount>")
        print("  python speed_trader.py sell <market_id> <yes/no> <tokens>")
        print("  python speed_trader.py cancel            # Cancel all orders")
        print("  python speed_trader.py balance           # Check balance")
        print()
        print("EXAMPLES:")
        print("  python speed_trader.py search trump")
        print("  python speed_trader.py buy 538932 yes 2.0")
        print("  python speed_trader.py sell 538932 yes 5")
        return
    
    trader = SpeedTrader()
    command = sys.argv[1].lower()
    
    if command == 'search' and len(sys.argv) > 2:
        query = ' '.join(sys.argv[2:])
        print(f"🔍 Searching markets for: '{query}'")
        print("=" * 50)
        
        markets = trader.search_markets(query)
        
        if markets:
            print(f"Found {len(markets)} matching markets:")
            print()
            
            for i, market in enumerate(markets[:10], 1):
                print(f"{i}. ID: {market['id']}")
                trader.display_market_info(market)
        else:
            print("No matching markets found")
    
    elif command == 'top':
        print("🏆 TOP VOLUME MARKETS FOR TRADING")
        print("=" * 50)
        
        markets = trader.get_best_markets(10)
        
        for i, market in enumerate(markets, 1):
            print(f"{i}. ID: {market['id']}")
            trader.display_market_info(market)
    
    elif command == 'buy' and len(sys.argv) >= 4:
        market_id = sys.argv[2]
        outcome = sys.argv[3]
        amount = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
        
        # Find market by ID
        markets = trader.get_best_markets(1000)
        market = next((m for m in markets if str(m['id']) == market_id), None)
        
        if market:
            trader.display_market_info(market)
            order_id = trader.speed_buy(market, outcome, amount)
            if order_id:
                trader.monitor_order(order_id)
        else:
            print(f"❌ Market ID {market_id} not found")
    
    elif command == 'sell' and len(sys.argv) >= 4:
        market_id = sys.argv[2]
        outcome = sys.argv[3]
        tokens = int(sys.argv[4]) if len(sys.argv) > 4 else 5
        
        # Find market by ID
        markets = trader.get_best_markets(1000) 
        market = next((m for m in markets if str(m['id']) == market_id), None)
        
        if market:
            trader.display_market_info(market)
            order_id = trader.speed_sell(market, outcome, tokens)
            if order_id:
                trader.monitor_order(order_id)
        else:
            print(f"❌ Market ID {market_id} not found")
    
    elif command == 'cancel':
        trader.cancel_all_orders()
    
    elif command == 'balance':
        trader.check_balance()
    
    else:
        print("❌ Invalid command. Use 'python speed_trader.py' for help.")


if __name__ == '__main__':
    main()
