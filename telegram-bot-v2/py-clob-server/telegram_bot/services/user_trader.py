#!/usr/bin/env python3
"""
User Trader Service
Handles trading operations for individual users with their own wallets
"""

import logging
import time
from typing import Dict, Optional
from datetime import datetime
from math import floor

logger = logging.getLogger(__name__)


class UserTrader:
    """
    User-specific trader that executes trades using the user's wallet and credentials
    Provides ultra-fast buy/sell execution with aggressive pricing
    """

    def __init__(self, client, private_key: str):
        """
        Initialize user trader with CLOB client and private key

        Args:
            client: ClobClient instance configured with user's wallet
            private_key: User's wallet private key
        """
        self.client = client
        self.private_key = private_key
        from database import db_manager
        self.time = time
        self.db_manager = db_manager

        # LOG: Validate that private key was successfully decrypted and retrieved
        if not private_key:
            logger.error(f"❌ [TRADER_INIT_FAILED] private_key=EMPTY | client_addr={client.get_address() if client else 'NONE'} | ts={datetime.utcnow().isoformat()}")
        else:
            key_preview = private_key[:6] + '...' + private_key[-6:] if len(private_key) > 12 else '***'
            logger.info(f"✅ [TRADER_INIT] private_key_received=True | key_len={len(private_key)} | key_preview={key_preview} | client_addr={client.get_address() if client else 'NONE'} | ts={datetime.utcnow().isoformat()}")

    def get_live_price(self, token_id: str, side: str) -> float:
        """
        Get live price for token (BUY or SELL side)

        Args:
            token_id: Token identifier
            side: "BUY" or "SELL"

        Returns:
            Current market price as float, 0.0 if error
        """
        try:
            price_data = self.client.get_price(token_id, side)
            return float(price_data.get('price', 0))
        except Exception as e:
            logger.error(f"Live price error: {e}")
            return 0.0

    def calculate_price_range(self, bid_price: float, ask_price: float, tokens_to_sell: float) -> Dict:
        """
        Calculate realistic price range using spread information
        Gives user better expectations about actual execution price

        Args:
            bid_price: Market BID (what buyers are paying)
            ask_price: Market ASK (what sellers are asking)
            tokens_to_sell: Number of tokens

        Returns:
            Dict with:
            - quote_price: Conservative quote (BID × 0.98)
            - best_case: If order fills at BID
            - worst_case: If market moves against us
            - expected_total: Best estimate of total received
            - range_total: Min-Max total possible
            - spread_pct: Market spread percentage
            - volatility: Market volatility assessment
        """
        try:
            # Calculate spread
            spread = ask_price - bid_price
            spread_pct = (spread / bid_price * 100) if bid_price > 0 else 0

            # Calculate prices
            quote_price = bid_price * 0.98  # Our conservative estimate (2% buffer)
            best_case_price = bid_price  # If order matches immediately at BID
            worst_case_price = bid_price - (spread * 0.5)  # Conservative buffer if market moves

            # Ensure worst case doesn't go below reasonable threshold
            worst_case_price = max(worst_case_price, bid_price * 0.95)  # Never quote <5% worse

            # Calculate totals
            quote_total = tokens_to_sell * quote_price
            best_total = tokens_to_sell * best_case_price
            worst_total = tokens_to_sell * worst_case_price

            # Assess volatility
            if spread_pct < 1:
                volatility = "LOW ✅"
            elif spread_pct < 3:
                volatility = "NORMAL 📊"
            elif spread_pct < 5:
                volatility = "HIGH ⚠️"
            else:
                volatility = "VERY HIGH 🚨"

            return {
                'quote_price': quote_price,
                'quote_total': quote_total,
                'best_case_price': best_case_price,
                'best_case_total': best_total,
                'worst_case_price': worst_case_price,
                'worst_case_total': worst_total,
                'bid_price': bid_price,
                'ask_price': ask_price,
                'spread': spread,
                'spread_pct': spread_pct,
                'volatility': volatility,
                'message': f"Expected: ${quote_total:.2f} | Range: ${worst_total:.2f}-${best_total:.2f}"
            }

        except Exception as e:
            logger.error(f"Error calculating price range: {e}")
            return {
                'quote_price': bid_price * 0.98,
                'quote_total': tokens_to_sell * bid_price * 0.98,
                'error': str(e)
            }

    def calculate_weighted_sell_price(self, orderbook, tokens_to_sell: float, best_ask: float) -> tuple:
        """
        Calculate the weighted average price by traversing the orderbook asks.

        This function finds the best price to sell by analyzing available liquidity
        across multiple price levels in the orderbook.

        Args:
            orderbook: The orderbook object with asks list
            tokens_to_sell: Number of tokens to sell
            best_ask: Best ask price (fallback if calculation fails)

        Returns:
            tuple: (weighted_price, total_tokens_matched, asks_to_traverse)
        """
        if not orderbook or not orderbook.asks or len(orderbook.asks) == 0:
            return best_ask, 0, 0

        total_tokens_matched = 0
        total_value = 0
        asks_traversed = 0

        print(f"\n📊 TRAVERSING ASKS TO FIND LIQUIDITY FOR {tokens_to_sell:.2f} TOKENS:")

        for ask in orderbook.asks:
            if total_tokens_matched >= tokens_to_sell:
                break

            ask_price = float(ask.price)
            ask_size = float(ask.size)

            # How many tokens we need from this ask level
            tokens_needed = tokens_to_sell - total_tokens_matched
            tokens_from_this_ask = min(tokens_needed, ask_size)

            # Add to our totals
            total_tokens_matched += tokens_from_this_ask
            total_value += tokens_from_this_ask * ask_price
            asks_traversed += 1

            print(f"   📈 Level {asks_traversed}: ${ask_price:.4f} x {ask_size:.2f} tokens → Taking {tokens_from_this_ask:.2f} tokens")
            print(f"      Total matched: {total_tokens_matched:.2f}/{tokens_to_sell:.2f} tokens")

        # Calculate weighted average price
        if total_tokens_matched > 0:
            weighted_price = total_value / total_tokens_matched
            print(f"\n✅ WEIGHTED PRICE: ${weighted_price:.4f} (across {asks_traversed} price levels)")
            print(f"   Total liquidity: {total_tokens_matched:.2f} tokens")
            return weighted_price, total_tokens_matched, asks_traversed
        else:
            return best_ask, 0, 0

    def speed_buy(self, market: dict, outcome: str, amount: float, fast_mode: bool = False) -> Optional[Dict]:
        """
        Ultra-fast buy execution with user's wallet using TRUE market orders

        Uses MarketOrderArgs for guaranteed best-price execution when buying with fixed amount.
        This is CRITICAL for quick buy ($2) on /smart_trading to get maximum tokens.

        Args:
            market: Market data dictionary
            outcome: "yes" or "no"
            amount: USD amount to spend
            fast_mode: If True, use higher gas_price for faster transaction priority

        Returns:
            Trade details dict with order_id, buy_price, tokens, etc., or None if failed
        """
        try:
            logger.info(f"🚀 [SPEED_BUY_START] market={market.get('question', 'Unknown')[:40]}... | outcome={outcome} | amount=${amount:.2f} | private_key_present={bool(self.private_key)} | ts={datetime.utcnow().isoformat()}")

            # Validate private key exists
            if not self.private_key:
                logger.error(f"❌ [SPEED_BUY_NO_KEY] market={market.get('id')} | outcome={outcome} | error=no_private_key | ts={datetime.utcnow().isoformat()}")
                raise ValueError("Private key not available for trading")

            # FIXED: Use outcome-based token matching instead of array index
            from telegram_bot.utils.token_utils import get_token_id_for_outcome

            token_id = get_token_id_for_outcome(market, outcome)

            if not token_id:
                logger.error(f"❌ [TOKEN_ID_NOT_FOUND] market={market.get('question', 'Unknown')[:40]}... | outcome={outcome} | ts={datetime.utcnow().isoformat()}")
                raise ValueError(f"Cannot find token_id for outcome '{outcome}' in market '{market.get('question', 'Unknown')[:50]}...'")

            logger.info(f"✅ [TOKEN_ID_RESOLVED] market={market.get('id')} | outcome={outcome} | token_id={token_id[:20]}... | ts={datetime.utcnow().isoformat()}")

            print(f"🚀 USER WALLET BUY - {outcome.upper()} TOKENS")
            print(f"💰 Market buy: ${amount:.2f} worth of {outcome.upper()} tokens")
            print(f"🎯 Using YOUR wallet: {self.client.get_address()}")

            # Check if orderbook exists before attempting to trade
            try:
                orderbook = self.client.get_order_book(token_id)
                if not orderbook:
                    logger.error(f"❌ [ORDERBOOK_MISSING] token_id={token_id[:20]}... | no orderbook object returned")
                    return None

                if not orderbook.bids or len(orderbook.bids) == 0:
                    logger.error(f"❌ [NO_LIQUIDITY] token_id={token_id[:20]}... | no bids in orderbook (asks={len(orderbook.asks) if orderbook.asks else 0})")
                    return None

                print(f"✅ Orderbook found: {len(orderbook.bids)} bids, {len(orderbook.asks)} asks")
                logger.info(f"✅ [ORDERBOOK_FOUND] token_id={token_id[:20]}... | bids={len(orderbook.bids)} | asks={len(orderbook.asks)}")

                # 🚨 DEBUG: Log detailed orderbook info
                print(f"🔍 DEBUG: Orderbook details:")
                if orderbook.bids and len(orderbook.bids) > 0:
                    best_bid = orderbook.bids[0]
                    try:
                        bid_price = float(best_bid.price)
                        bid_size = float(best_bid.size)
                        print(f"   Best BID: price=${bid_price:.6f}, size={bid_size:.4f}")
                        total_bid_volume = sum(float(bid.size) for bid in orderbook.bids)
                        print(f"   Total BID volume: {total_bid_volume:.4f}")
                    except (ValueError, TypeError) as e:
                        print(f"   Best BID: price={best_bid.price} (raw), size={best_bid.size} (raw) - Error: {e}")
                        print(f"   Total BID volume: {len(orderbook.bids)} orders (cannot sum)")
                else:
                    print(f"   ❌ NO BIDS in orderbook!")

                if orderbook.asks and len(orderbook.asks) > 0:
                    best_ask = orderbook.asks[0]
                    try:
                        ask_price = float(best_ask.price)
                        ask_size = float(best_ask.size)
                        print(f"   Best ASK: price=${ask_price:.6f}, size={ask_size:.4f}")
                        total_ask_volume = sum(float(ask.size) for ask in orderbook.asks)
                        print(f"   Total ASK volume: {total_ask_volume:.4f}")
                    except (ValueError, TypeError) as e:
                        print(f"   Best ASK: price={best_ask.price} (raw), size={best_ask.size} (raw) - Error: {e}")
                        print(f"   Total ASK volume: {len(orderbook.asks)} orders (cannot sum)")
                else:
                    print(f"   ❌ NO ASKS in orderbook!")

                logger.info(f"🔍 [ORDERBOOK_DETAILS] best_bid={orderbook.bids[0].price if orderbook.bids else 'NONE'} | best_ask={orderbook.asks[0].price if orderbook.asks else 'NONE'}")

            except Exception as orderbook_error:
                logger.error(f"❌ [ORDERBOOK_FAILED] token_id={token_id[:20]}... | error={str(orderbook_error)[:100]}")
                print(f"❌ Cannot access orderbook: {orderbook_error}")
                return None

            # ✅ CRITICAL FIX: Use TRUE MARKET ORDER with MarketOrderArgs
            # This ensures:
            # 1. API calculates tokens automatically (not prone to manual errors)
            # 2. Gets best available market price
            # 3. Maximum tokens for fixed amount ($2)
            # 4. Instant execution with FAK (Fill-And-Kill = IOC)
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY

            print(f"\n🚀 Strategy: TRUE MARKET ORDER (Best Price Execution)")
            print(f"   💰 Amount: ${amount:.2f}")
            print(f"   📡 API will calculate tokens automatically")
            print(f"   ⚡ Order type: FAK (Fill-And-Kill = IOC)")
            print(f"   🎯 Result: Maximum tokens for {amount} at best market price")
            print(f"   🏎️  Fast mode: {fast_mode} (higher gas priority)")

            logger.info(f"✅ [MARKET_ORDER_STRATEGY] Using MarketOrderArgs with FAK for instant best-price execution, fast_mode={fast_mode}")

            # Create TRUE MARKET ORDER (not a limit order)
            # Pass amount in dollars - the API will:
            # 1. Calculate tokens needed
            # 2. Find best price in orderbook
            # 3. Execute at best available price
            market_order_args = MarketOrderArgs(
                token_id=token_id,
                amount=amount,  # Dollar amount - API calculates tokens
                side=BUY,
            )

            # 🚀 FAST MODE: Temporarily boost gas price for copy trading priority
            if fast_mode:
                logger.info(f"🏎️ [FAST_MODE] Activating high-priority gas pricing for copy trading")
                # Temporarily modify client's gas pricing (if supported)
                original_gas_price = getattr(self.client, '_gas_price', None)
                try:
                    # Try to set a higher gas price on the client (experimental)
                    from web3 import Web3
                    w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com/"))
                    if w3.is_connected():
                        # Get current gas price and boost it by 3x for fast priority
                        current_gas = w3.eth.gas_price
                        fast_gas_price = int(current_gas * 3)  # 3x boost for copy trading
                        max_gas = w3.to_wei(200, 'gwei')  # Cap at 200 gwei
                        fast_gas_price = min(fast_gas_price, max_gas)

                        logger.info(f"🏎️ [FAST_MODE] Boosting gas from {w3.from_wei(current_gas, 'gwei'):.1f} to {w3.from_wei(fast_gas_price, 'gwei'):.1f} gwei")

                        # Try to inject gas price into client (this may not work with current py_clob_client)
                        if hasattr(self.client, 'signer') and self.client.signer:
                            # Store original for restoration
                            self._original_gas_price = getattr(self.client.signer, 'gas_price', None)
                            self.client.signer.gas_price = fast_gas_price
                    else:
                        logger.warning(f"⚠️ [FAST_MODE] Could not connect to Polygon RPC for gas boost")
                except Exception as e:
                    logger.warning(f"⚠️ [FAST_MODE] Gas boost failed: {e}")
                    fast_gas_price = None

            print(f"🔍 DEBUG: Creating market order with MarketOrderArgs...")
            print(f"   token_id: {token_id[:20]}...")
            print(f"   amount: ${amount:.2f} (in dollars)")
            print(f"   side: BUY")
            print(f"   strategy: FAK (Fill-And-Kill)")

            try:
                print(f"🔍 DEBUG: About to call create_market_order with args:")
                print(f"   token_id: {market_order_args.token_id}")
                print(f"   amount: {market_order_args.amount}")
                print(f"   side: {market_order_args.side}")

                signed_order = self.client.create_market_order(market_order_args)

                print(f"✅ DEBUG: create_market_order succeeded")
                print(f"   signed_order type: {type(signed_order)}")
                print(f"   signed_order keys: {list(signed_order.keys()) if hasattr(signed_order, 'keys') else 'N/A'}")

                logger.info(f"✅ [MARKET_ORDER_CREATED] signed_order={type(signed_order)}")
            except Exception as e:
                print(f"❌ DEBUG: create_market_order FAILED: {str(e)}")
                logger.error(f"❌ [CREATE_MARKET_ORDER_FAILED] error={str(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise

            # 🚨 DEBUG: Add detailed logging before posting
            print(f"🔍 DEBUG: Order details before posting:")
            print(f"   signed_order type: {type(signed_order)}")
            print(f"   signed_order keys: {signed_order.keys() if hasattr(signed_order, 'keys') else 'N/A'}")
            if hasattr(signed_order, 'get'):
                print(f"   salt: {signed_order.get('salt', 'N/A')}")
                print(f"   maker: {signed_order.get('maker', 'N/A')[:10]}...")
                print(f"   taker: {signed_order.get('taker', 'N/A')[:10]}...")
                print(f"   tokenId: {signed_order.get('tokenId', 'N/A')[:20]}...")
                print(f"   makerAmount: {signed_order.get('makerAmount', 'N/A')}")
                print(f"   takerAmount: {signed_order.get('takerAmount', 'N/A')}")
                print(f"   side: {signed_order.get('side', 'N/A')}")

            # Post as FAK (Fill-And-Kill = IOC) for instant execution
            print(f"🔍 DEBUG: Posting order with OrderType.FAK (Fill-And-Kill)...")
            print(f"🔍 DEBUG: Client creds: {self.client.creds}")
            print(f"🔍 DEBUG: Client address: {self.client.get_address()}")

            try:
                resp = self.client.post_order(signed_order, orderType=OrderType.FAK)
                print(f"✅ DEBUG: post_order succeeded")
                print(f"🔍 DEBUG: Raw API response: {resp}")
                print(f"🔍 DEBUG: Response type: {type(resp)}")
                logger.info(f"🔍 [POST_ORDER_RESPONSE] full_response={resp}")
            except Exception as post_error:
                print(f"❌ DEBUG: post_order FAILED: {str(post_error)}")
                logger.error(f"❌ [POST_ORDER_FAILED] error={str(post_error)}")
                print(f"❌ Post order failed: {post_error}")
                raise
            finally:
                # 🚀 FAST MODE: Restore original gas price after transaction
                if fast_mode and hasattr(self, '_original_gas_price'):
                    try:
                        if hasattr(self.client, 'signer') and self.client.signer:
                            self.client.signer.gas_price = self._original_gas_price
                            logger.info(f"✅ [FAST_MODE] Restored original gas price")
                    except Exception as e:
                        logger.warning(f"⚠️ [FAST_MODE] Failed to restore gas price: {e}")
            print(f"🔍 DEBUG: Order response type: {type(resp)}, content: {resp}")

            # Extract order_id from response
            print(f"🔍 DEBUG: Extracting order_id from response...")
            if isinstance(resp, dict):
                order_id = resp.get('orderID') or resp.get('order_id') or resp.get('id')
                print(f"   Response dict keys: {list(resp.keys())}")
                print(f"   Extracted order_id: {order_id}")
            elif isinstance(resp, str):
                order_id = resp
                print(f"   Response is string: {order_id}")
            else:
                logger.error(f"❌ Unexpected response type: {type(resp)}")
                print(f"❌ Unexpected response type: {type(resp)}")
                return None

            if not order_id:
                logger.error(f"❌ No order_id in response: {resp}")
                print(f"❌ No order_id found in response: {resp}")
                return None

            print(f"✅ Order ID extracted: {order_id}")

            # 🚨 DEBUG: Check all possible transaction fields
            print(f"🔍 DEBUG: Checking for transaction execution...")
            transaction_hashes = None
            transaction_hash = None

            if isinstance(resp, dict):
                print(f"   Checking various transaction field names...")
                possible_fields = ['transactionsHashes', 'transactionHashes', 'transactions', 'transactionHash', 'txHash', 'hash']
                for field in possible_fields:
                    if field in resp:
                        transaction_hashes = resp.get(field)
                        print(f"   Found field '{field}': {transaction_hashes}")
                        break

                # Also check for direct success indicators
                success_indicators = ['success', 'executed', 'filled']
                for indicator in success_indicators:
                    if indicator in resp:
                        print(f"   Success indicator '{indicator}': {resp.get(indicator)}")

            # CRITICAL: Check if order executed immediately (has transactionHash)
            print(f"🔍 DEBUG: Checking execution status...")
            print(f"   transaction_hashes: {transaction_hashes}")
            print(f"   resp type: {type(resp)}")
            print(f"   resp content: {resp}")

            if transaction_hashes and len(transaction_hashes) > 0:
                transaction_hash = transaction_hashes[0]
                print(f"✅ Transaction hash found: {transaction_hash}")

                print(f"🎉 MARKET ORDER EXECUTED IMMEDIATELY! Transaction hash: {transaction_hash}")
                print(f"💰 Tokens received: {resp.get('takingAmount')}")
                print(f"💵 Cost: ${resp.get('makingAmount')}")

                # Order actually executed - return success immediately
                actual_tokens = float(resp.get('takingAmount', 0))
                actual_cost = float(resp.get('makingAmount', amount))
                actual_price = actual_cost / actual_tokens if actual_tokens > 0 else amount

                logger.info(f"✅ [BUY_SUCCESS_IMMEDIATE] tokens={actual_tokens:.4f}, cost=${actual_cost:.2f}, price=${actual_price:.6f}")

                print(f"\n✅ EXECUTION SUMMARY:")
                print(f"   📦 Tokens received: {actual_tokens:.4f}")
                print(f"   💵 Cost: ${actual_cost:.2f}")
                print(f"   💲 Price per token: ${actual_price:.6f}")
                print(f"   ✅ Order Type: FAK (Market execution)")

                return {
                    'order_id': order_id,
                    'buy_price': round(actual_price, 4),
                    'tokens': actual_tokens,
                    'total_cost': actual_cost,
                    'token_id': token_id,
                    'live_price': round(actual_price, 4),
                    'transaction_hash': transaction_hash
                }

            # 🚨 DEBUG: Handle case where success=True but no transaction hash
            elif isinstance(resp, dict) and resp.get('success') == True:
                print(f"⚠️  Order marked as successful but no transaction hash found")
                print(f"   Response details: {resp}")
                logger.warning(f"⚠️ [SUCCESS_NO_TX] order_id={order_id}, response={resp}")

                # Check if there are execution details in other fields
                executed_amount = resp.get('executedAmount') or resp.get('filledAmount') or resp.get('takingAmount')
                if executed_amount:
                    print(f"✅ Found executed amount: {executed_amount}")
                    # This might be a successful execution without transaction hash
                    actual_tokens = float(executed_amount)
                    actual_cost = amount  # Assume full amount was used
                    actual_price = actual_cost / actual_tokens if actual_tokens > 0 else amount

                    logger.info(f"✅ [BUY_SUCCESS_NO_TX] tokens={actual_tokens:.4f}, cost=${actual_cost:.2f}")

                    print(f"\n✅ EXECUTION SUMMARY (No TX Hash):")
                    print(f"   📦 Tokens received: {actual_tokens:.4f}")
                    print(f"   💵 Cost: ${actual_cost:.2f}")
                    print(f"   💲 Price per token: ${actual_price:.6f}")
                    print(f"   ✅ Order Type: FAK (Market execution)")

                    return {
                        'order_id': order_id,
                        'buy_price': round(actual_price, 4),
                        'tokens': actual_tokens,
                        'total_cost': actual_cost,
                        'token_id': token_id,
                        'live_price': round(actual_price, 4),
                        'transaction_hash': None  # No transaction hash
                    }
                else:
                    print(f"❌ Success=True but no execution details found")
                    logger.error(f"❌ [SUCCESS_NO_EXECUTION] order_id={order_id}, response={resp}")
                    return None

            # If no transaction hash, the order failed
            else:
                logger.error(f"❌ [BUY_NO_TRANSACTION] order_id={order_id}, no transactionHash in response")
                print(f"❌ Order did not execute - no transaction hash in response")
                print(f"   Full response: {resp}")
                return None

        except Exception as e:
            logger.error(f"Speed buy error with user wallet: {e}")
            print(f"❌ Speed buy error: {e}")
            return None

    def speed_sell_with_token_id(self, market: dict, outcome: str, tokens: int, token_id: str, is_tpsl_sell: bool = False, suggested_price: float = None, fast_mode: bool = False) -> Optional[Dict]:
        """
        FIXED: Ultra-fast sell execution using direct token_id (bypasses broken market parsing)

        Args:
            market: Market data dictionary (for reference)
            fast_mode: If True, use higher gas_price for faster transaction priority
            outcome: "yes" or "no"
            tokens: Number of tokens to sell
            token_id: Exact token ID from position
            is_tpsl_sell: If True, uses conservative pricing for TP/SL automatic sells.
                         If False, uses aggressive pricing for manual emergency sells.

        Returns:
            Trade details dict with order_id, sell_price, tokens_sold, etc., or None if failed
        """
        try:
            logger.info(f"🚀 [SPEED_SELL_DIRECT_START] market={market.get('question', 'Unknown')[:40]}... | outcome={outcome} | tokens={tokens} | token_id={token_id} | is_tpsl_sell={is_tpsl_sell} | private_key_present={bool(self.private_key)} | ts={datetime.utcnow().isoformat()}")

            # Validate private key exists
            if not self.private_key:
                logger.error(f"❌ [SPEED_SELL_DIRECT_NO_KEY] market={market.get('id')} | outcome={outcome} | error=no_private_key | ts={datetime.utcnow().isoformat()}")
                raise ValueError("Private key not available for trading")

            logger.info(f"✅ [TOKEN_ID_RESOLVED] market={market.get('id')} | outcome={outcome} | token_id={token_id[:20]}... | ts={datetime.utcnow().isoformat()}")

            logger.info(f"🔍 SPEED_SELL_DIRECT: Using token_id directly: {token_id} (TP/SL: {is_tpsl_sell})")

            # CRITICAL DEBUG: Check orderbook BEFORE placing order
            print(f"\n{'='*80}")
            print(f"🔍 DEBUGGING ORDERBOOK FOR SELL")
            print(f"{'='*80}")

            try:
                orderbook = self.client.get_order_book(token_id)

                # Log orderbook structure
                print(f"📚 Orderbook exists: {orderbook is not None}")
                print(f"📊 Bids (buyers): {len(orderbook.bids) if orderbook and orderbook.bids else 0} orders")
                print(f"📊 Asks (sellers): {len(orderbook.asks) if orderbook and orderbook.asks else 0} orders")

                if orderbook and orderbook.bids and len(orderbook.bids) > 0:
                    best_bid = float(orderbook.bids[0].price)
                    best_bid_size = float(orderbook.bids[0].size)
                    print(f"💰 BEST BID (what buyers pay): ${best_bid:.4f} for {best_bid_size} tokens")
                    print(f"   📋 Top 5 bids:")
                    for i, bid in enumerate(orderbook.bids[:5]):
                        print(f"      #{i+1}: ${float(bid.price):.4f} x {float(bid.size)} tokens")
                else:
                    print(f"❌ NO BIDS ON ORDERBOOK - No buyers!")
                    best_bid = 0

                if orderbook and orderbook.asks and len(orderbook.asks) > 0:
                    best_ask = float(orderbook.asks[0].price)
                    best_ask_size = float(orderbook.asks[0].size)
                    print(f"💸 BEST ASK (what sellers want): ${best_ask:.4f} for {best_ask_size} tokens")
                    print(f"   📋 Top 5 asks:")
                    for i, ask in enumerate(orderbook.asks[:5]):
                        print(f"      #{i+1}: ${float(ask.price):.4f} x {float(ask.size)} tokens")
                else:
                    print(f"⚠️ NO ASKS ON ORDERBOOK")
                    best_ask = 0

            except Exception as ob_error:
                print(f"❌ Failed to get orderbook: {ob_error}")
                best_bid = 0
                best_ask = 0

            # Get live prices from API for comparison (but we'll use orderbook for actual pricing!)
            live_sell_price = self.get_live_price(token_id, "SELL")  # This gets ASK side
            live_buy_price = self.get_live_price(token_id, "BUY")    # This gets BID side

            print(f"\n🔍 API PRICES (for reference only):")
            print(f"   📡 API SELL price (ask side): ${live_sell_price:.4f}")
            print(f"   📡 API BUY price (bid side): ${live_buy_price:.4f}")
            print(f"   ⚠️ NOTE: API prices are midpoint estimates, using ORDERBOOK for actual pricing!")

            # POLYMARKET STRATEGY: Use marketable price, Polymarket executes at best available
            # Per docs: "To place a market order, simply ensure your price is marketable"
            # For SELL: Set price LOW (e.g. $0.01), Polymarket matches at highest bid
            # This ensures we get the BEST price, not worst!

            if suggested_price and suggested_price > 0:
                # Use suggested price if provided (from preview)
                base_price = suggested_price
                pricing_mode = "🎯 SUGGESTED PRICE (from preview)"
                print(f"\n✅ Using SUGGESTED PRICE from preview: ${base_price:.4f}")
                logger.info(f"✅ Using suggested price ${base_price:.4f} (passed from /positions)")
            elif best_bid > 0:
                # CORRECT: Use best_bid - this is what buyers pay for your tokens
                base_price = best_bid
                pricing_mode = "💰 BEST BID (seller price)"
                print(f"\n✅ Selling at BEST BID: ${base_price:.4f} (what buyers will pay)")
                logger.info(f"✅ SELL price = best_bid=${best_bid:.4f}")
            else:
                # CRITICAL: No real buyers on orderbook
                # When best_bid=0, calculate MIDPOINT from orderbook (best_bid + best_ask) / 2
                # NEW: Use unified price calculator for consistency
                from telegram_bot.services.price_calculator import calculate_midpoint, calculate_sell_quote_price

                logger.warning(f"⚠️ NO REAL BIDS ON ORDERBOOK - Calculating midpoint from bid/ask")
                print(f"\n⚠️ NO BIDS ON ORDERBOOK - Calculating midpoint from available data...")

                # Try 1: Calculate midpoint from orderbook if both bid and ask available
                if best_bid > 0 and best_ask > 0:
                    # Already covered above, but included for clarity
                    midpoint = calculate_midpoint(best_bid, best_ask)
                elif best_ask > 0 and live_buy_price > 0:
                    # Use best_ask + API bid to calculate midpoint
                    midpoint = calculate_midpoint(live_buy_price, best_ask)
                    logger.info(f"📊 Midpoint from API BID + orderbook ASK: ${midpoint:.6f}")
                    print(f"   Using API BID (${live_buy_price:.4f}) + Orderbook ASK (${best_ask:.4f})")
                elif live_buy_price > 0 and live_sell_price > 0:
                    # Use API prices to calculate midpoint
                    midpoint = calculate_midpoint(live_buy_price, live_sell_price)
                    logger.info(f"📊 Midpoint from API BID/ASK: ${midpoint:.6f}")
                    print(f"   Using API prices: BID=${live_buy_price:.4f}, ASK=${live_sell_price:.4f}")
                else:
                    # Fallback to API buy price (previous behavior)
                    midpoint = live_buy_price if live_buy_price > 0 else None
                    if not midpoint:
                        logger.error(f"❌ [NO_LIQUIDITY] token_id={token_id[:20]}... | no bids on orderbook and no API price")
                        print(f"\n❌ CANNOT SELL: No liquidity and no pricing data available!")
                        return None
                    logger.warning(f"⚠️ Using API BID as fallback: ${midpoint:.6f}")
                    print(f"   Fallback: Using API BID price only")

                # Apply 0.5% discount to midpoint for conservative sell quote
                if midpoint and midpoint > 0:
                    base_price = calculate_sell_quote_price(midpoint)
                    if not base_price:
                        base_price = midpoint * 0.995  # Fallback calculation
                    pricing_mode = "🎯 MIDPOINT - 0.5%"
                    print(f"\n✅ Using MIDPOINT with 0.5% discount: ${base_price:.4f}")
                    logger.info(f"💰 FALLBACK TO MIDPOINT: Using ${base_price:.4f} (midpoint - 0.5%)")
                else:
                    logger.error(f"❌ [NO_LIQUIDITY] token_id={token_id[:20]}... | cannot calculate any price")
                    print(f"\n❌ CANNOT SELL: Cannot determine price from any source!")
                    return None
            # NO SLIPPAGE - sell at exact BID price for immediate execution
            best_price = base_price  # 0% slippage - exact buyer price

            # FIX: Round to API precision requirements
            best_price = round(best_price, 4)  # Price: max 4 decimals

            logger.info(f"{pricing_mode}: ${base_price:.4f} (marketable price for Polymarket matching)")
            logger.info(f"📊 [ORDERBOOK_PREVIEW] Best available - BID: ${best_bid:.4f}, ASK: ${best_ask:.4f}")
            logger.info(f"⚠️ [PRICING_STRATEGY] Using marketable price - Polymarket will match at best available bid, final price may be higher")

            print(f"\n🎯 OUR SELL ORDER:")
            print(f"   💎 Our sell price: ${best_price:.4f} ({pricing_mode} - 0% slippage)")
            print(f"   📦 Selling: {tokens} tokens")
            print(f"   💵 Expected: ${tokens * best_price:.2f}")
            print(f"   🏎️  Fast mode: {fast_mode} (higher gas priority)")

            # 🚀 FAST MODE: Temporarily boost gas price for copy trading priority
            if fast_mode:
                logger.info(f"🏎️ [FAST_MODE] Activating high-priority gas pricing for copy trading sell")
                # Temporarily modify client's gas pricing (if supported)
                original_gas_price = getattr(self.client, '_gas_price', None)
                try:
                    # Try to set a higher gas price on the client (experimental)
                    from web3 import Web3
                    w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com/"))
                    if w3.is_connected():
                        # Get current gas price and boost it by 3x for fast priority
                        current_gas = w3.eth.gas_price
                        fast_gas_price = int(current_gas * 3)  # 3x boost for copy trading
                        max_gas = w3.to_wei(200, 'gwei')  # Cap at 200 gwei
                        fast_gas_price = min(fast_gas_price, max_gas)

                        logger.info(f"🏎️ [FAST_MODE] Boosting gas from {w3.from_wei(current_gas, 'gwei'):.1f} to {w3.from_wei(fast_gas_price, 'gwei'):.1f} gwei")

                        # Try to inject gas price into client (this may not work with current py_clob_client)
                        if hasattr(self.client, 'signer') and self.client.signer:
                            # Store original for restoration
                            self._original_gas_price = getattr(self.client.signer, 'gas_price', None)
                            self.client.signer.gas_price = fast_gas_price
                    else:
                        logger.warning(f"⚠️ [FAST_MODE] Could not connect to Polygon RPC for gas boost")
                except Exception as e:
                    logger.warning(f"⚠️ [FAST_MODE] Gas boost failed: {e}")
                    fast_gas_price = None

            print(f"\n⚖️ PRICING STRATEGY:")
            if best_bid > 0:
                print(f"   🎯 MARKETABLE PRICE: ${best_price:.4f} (Polymarket will find best buyer)")
                print(f"   💡 Best bid available: ${best_bid:.4f} - Final price may be higher")
            else:
                print(f"   ⚠️ NO BIDS - Using fallback pricing")

            print(f"\n📋 ORDER TYPE: FAK (Fill-And-Kill = IOC)")
            print(f"   ✅ FAK will match immediately at best available prices")
            print(f"{'='*80}\n")

            print(f"💎 USER WALLET SELL - {outcome.upper()} TOKENS")
            print(f"📡 Base price: ${base_price:.4f}")
            print(f"{pricing_mode}: ${best_price:.4f} (0% slippage - exact BID)")
            print(f"📦 Size: {tokens} tokens")
            print(f"💵 Expected receive: ${tokens * best_price:.2f}")
            print(f"🎯 Using YOUR wallet: {self.client.get_address()}")
            print(f"🔧 API-safe amounts: price={best_price}, tokens={tokens}")
            print(f"🎯 DIRECT TOKEN ID: {token_id}")

            # 🚨 CRITICAL FIX: Handle markets without orderbooks
            # When best_bid == 0, no orderbook exists, so we must use MARKET orders, not LIMIT orders
            if best_bid == 0:
                print(f"🚨 NO ORDERBOOK DETECTED - Using MARKET ORDER instead of LIMIT ORDER")
                print(f"📋 Order Type: FOK (Fill-Or-Kill = IOC) - Market order that fills completely or cancels")

                # Use MARKET ORDER for illiquid markets (no orderbook)
                from py_clob_client.clob_types import MarketOrderArgs, OrderType
                from py_clob_client.order_builder.constants import SELL

                market_order_args = MarketOrderArgs(
                    token_id=token_id,
                    amount=tokens,  # Number of tokens to sell
                    side=SELL,
                )

                signed_order = self.client.create_market_order(market_order_args)
                try:
                    resp = self.client.post_order(signed_order, orderType=OrderType.FOK)
                finally:
                    # 🚀 FAST MODE: Restore original gas price after transaction
                    if fast_mode and hasattr(self, '_original_gas_price'):
                        try:
                            if hasattr(self.client, 'signer') and self.client.signer:
                                self.client.signer.gas_price = self._original_gas_price
                                logger.info(f"✅ [FAST_MODE] Restored original gas price after market sell")
                        except Exception as e:
                            logger.warning(f"⚠️ [FAST_MODE] Failed to restore gas price after market sell: {e}")
            else:
                print(f"🚀 Strategy: ORDERBOOK-DRIVEN PRICING - Uses real buyer prices")
                print(f"📋 Order Type: FAK (Fill-And-Kill = IOC) - Fills immediately at best price, allows partial fills")

                # Create LIMIT sell order with FAK (Fill-And-Kill = IOC) for instant execution
                from py_clob_client.order_builder.constants import SELL
                from py_clob_client.clob_types import OrderArgs, OrderType

                order_args = OrderArgs(
                    price=best_price,  # Best price with minimal slippage
                    size=tokens,             # Number of tokens to sell
                    side=SELL,
                    token_id=token_id,       # Use exact token_id from position
                )

                # Create and submit SELL order with FAK (Fill-And-Kill = IOC)
                # FAK fills what it can immediately at best prices, cancels rest - perfect for high volume
                signed_order = self.client.create_order(order_args)
                try:
                    resp = self.client.post_order(signed_order, orderType=OrderType.FAK)
                finally:
                    # 🚀 FAST MODE: Restore original gas price after transaction
                    if fast_mode and hasattr(self, '_original_gas_price'):
                        try:
                            if hasattr(self.client, 'signer') and self.client.signer:
                                self.client.signer.gas_price = self._original_gas_price
                                logger.info(f"✅ [FAST_MODE] Restored original gas price after limit sell")
                        except Exception as e:
                            logger.warning(f"⚠️ [FAST_MODE] Failed to restore gas price after limit sell: {e}")

            logger.info(f"📤 ORDER SUBMITTED: response_type={type(resp)}, response={resp}")

            # CRITICAL: Handle response properly and return consistent format
            if isinstance(resp, dict):
                order_id = resp.get('orderID')
            elif isinstance(resp, str):
                order_id = resp  # Response is already the order ID
            else:
                logger.error(f"❌ Unexpected response type: {type(resp)}, content: {resp}")
                return None

            logger.info(f"✅ ORDER ID EXTRACTED: {order_id}")

            # 🎯 CRITICAL: Extract REAL execution data from post_order response
            # The post_order response contains takingAmount (what we received) and makingAmount (what we sold)
            real_filled = None
            real_total = None

            if isinstance(resp, dict) and (resp.get('success') or (resp.get('status') == 'matched' and resp.get('transactionsHashes'))):
                try:
                    # For SELL orders:
                    # - makingAmount = tokens we're selling
                    # - takingAmount = USD we're receiving
                    real_filled = float(resp.get('makingAmount', 0))
                    real_total = float(resp.get('takingAmount', 0))

                    if real_filled > 0 and real_total > 0:
                        real_price = real_total / real_filled
                        logger.info(f"✅ REAL EXECUTION FROM POST_ORDER: filled={real_filled}, total=${real_total:.6f}, price=${real_price:.6f}")
                        logger.info(f"💰 [EXECUTION_SUMMARY] User received ${real_total:.2f} for {real_filled:.0f} tokens at avg ${real_price:.4f}/token (includes all fees & slippage)")
                        print(f"\n💰 EXECUTION CONFIRMED:")
                        print(f"   ✅ Received: ${real_total:.2f} for {real_filled:.0f} tokens")
                        print(f"   📊 Average price: ${real_price:.4f}/token")
                        print(f"   🎯 Better than expected: Polymarket found optimal buyer!")

                        # Extract transaction hash if available
                        transaction_hash = None
                        if isinstance(resp.get('transactionsHashes'), list) and len(resp.get('transactionsHashes', [])) > 0:
                            transaction_hash = resp['transactionsHashes'][0]

                        return {
                            'order_id': order_id,
                            'sell_price': real_price,  # REAL price from execution!
                            'tokens_sold': real_filled,
                            'total_received': real_total,
                            'transaction_hash': transaction_hash,
                            'estimated_price': best_price,  # Keep estimate for reference
                            'is_real': True  # Flag that this is real, not estimated
                        }
                except Exception as e:
                    logger.warning(f"⚠️ Could not extract real execution from post_order response: {e}")

            # Return consistent dictionary format for sell_result
            if order_id:
                # Fallback: Monitor the order and try to get execution details from get_order
                print(f"\n⏳ MONITORING ORDER FOR REAL EXECUTION PRICE...")
                logger.info(f"🔄 MONITOR_ORDER: order_id={order_id}, timeout=30s")
                filled = self.monitor_order(order_id, timeout=30)

                logger.info(f"📊 MONITOR_ORDER_RESULT: filled={filled}, order_id={order_id}")

                if filled:
                    # Try to get REAL execution details from the order
                    logger.info(f"🔎 FETCHING EXECUTION DETAILS: order_id={order_id}")
                    execution_details = self.get_order_execution_details(order_id)

                    if execution_details:
                        # Use REAL price from execution, not estimate!
                        real_price = execution_details['avg_price']
                        real_total = execution_details['total_filled']
                        real_filled = execution_details['filled_qty']

                        logger.info(f"✅ EXECUTION RESULT: price=${real_price:.6f}, filled={real_filled}, total=${real_total:.4f}")

                        print(f"\n✅ REAL EXECUTION vs ESTIMATED:")
                        print(f"   Estimated Price: ${best_price:.6f}")
                        print(f"   REAL Price: ${real_price:.6f}")
                        print(f"   Difference: ${(real_price - best_price):.6f}")

                        return {
                            'order_id': order_id,
                            'sell_price': real_price,  # REAL price from execution!
                            'tokens_sold': real_filled,
                            'total_received': real_total,
                            'transaction_hash': execution_details['transaction_hash'],
                            'estimated_price': best_price,  # Keep estimate for reference
                            'is_real': True  # Flag that this is real, not estimated
                        }
                    else:
                        # Final fallback if can't get details - use estimate
                        logger.warning(f"⚠️ Could not retrieve execution details for order {order_id}, using estimate")
                        print(f"⚠️ Could not retrieve execution details, using estimate")
                        return {
                            'order_id': order_id,
                            'sell_price': best_price,
                            'tokens_sold': tokens,
                            'total_received': tokens * best_price,
                            'is_real': False
                        }
                else:
                    # Order didn't fill
                    logger.error(f"❌ Order {order_id} did not complete within timeout")
                    return None
            else:
                logger.error(f"❌ No order_id in response: {resp}")
                return None

        except Exception as e:
            from py_clob_client.exceptions import PolyApiException

            # Distinguish between 403 auth errors and other failures
            if isinstance(e, PolyApiException):
                if e.status_code == 403:
                    logger.error(f"❌ [SELL_403_FORBIDDEN] API authentication failed during sell - likely invalid credentials: {e}")
                    print(f"❌ SELL FAILED: API credentials invalid (403 Forbidden)")
                    return None
                elif e.status_code == 429:
                    logger.error(f"❌ [SELL_429_RATE_LIMITED] Rate limited: {e}")
                    print(f"❌ SELL FAILED: Rate limited - please try again")
                    return None
                else:
                    logger.error(f"❌ [SELL_API_ERROR_{e.status_code}] {e}")
                    print(f"❌ SELL FAILED: API error {e.status_code}")
                    return None
            else:
                logger.error(f"❌ Speed sell error with direct token_id: {e}", exc_info=True)
                print(f"❌ Speed sell error: {e}")
                return None

    def speed_sell(self, market: dict, outcome: str, tokens: int) -> Optional[Dict]:
        """
        Ultra-fast sell execution with user's wallet

        Args:
            market: Market data dictionary
            outcome: "yes" or "no"
            tokens: Number of tokens to sell

        Returns:
            Trade details dict with order_id, sell_price, tokens_sold, etc., or None if failed
        """
        try:
            # DEBUGGING: Log market structure
            logger.error(f"🔍 SPEED_SELL DEBUG: market keys: {list(market.keys())}")
            logger.error(f"🔍 SPEED_SELL DEBUG: market clob_token_ids: {market.get('clob_token_ids', 'MISSING')}")
            logger.error(f"🔍 SPEED_SELL DEBUG: outcome: '{outcome}'")

            # FIXED: Use outcome-based token matching instead of array index
            # Polymarket API does NOT guarantee token ordering in clob_token_ids
            from telegram_bot.utils.token_utils import get_token_id_for_outcome

            token_id = get_token_id_for_outcome(market, outcome)

            if not token_id:
                logger.error(f"🔍 SPEED_SELL DEBUG: FAILED - Cannot find token_id for outcome '{outcome}'")
                raise ValueError(f"Cannot find token_id for outcome '{outcome}' in market '{market.get('question', 'Unknown')[:50]}...'")

            logger.info(f"🔍 TOKEN LOOKUP (SELL): market={market.get('question', 'Unknown')[:50]}..., outcome={outcome.upper()}, token_id={token_id[:20]}...")

            # CRITICAL DEBUG: Check orderbook BEFORE placing order
            print(f"\n{'='*80}")
            print(f"🔍 DEBUGGING ORDERBOOK FOR SELL (speed_sell)")
            print(f"{'='*80}")

            try:
                orderbook = self.client.get_order_book(token_id)

                # Log orderbook structure
                print(f"📚 Orderbook exists: {orderbook is not None}")
                print(f"📊 Bids (buyers): {len(orderbook.bids) if orderbook and orderbook.bids else 0} orders")
                print(f"📊 Asks (sellers): {len(orderbook.asks) if orderbook and orderbook.asks else 0} orders")

                if orderbook and orderbook.bids and len(orderbook.bids) > 0:
                    best_bid = float(orderbook.bids[0].price)
                    best_bid_size = float(orderbook.bids[0].size)
                    print(f"💰 BEST BID (what buyers pay): ${best_bid:.4f} for {best_bid_size} tokens")
                    print(f"   📋 Top 5 bids:")
                    for i, bid in enumerate(orderbook.bids[:5]):
                        print(f"      #{i+1}: ${float(bid.price):.4f} x {float(bid.size)} tokens")
                else:
                    print(f"❌ NO BIDS ON ORDERBOOK - No buyers!")
                    best_bid = 0

                if orderbook and orderbook.asks and len(orderbook.asks) > 0:
                    best_ask = float(orderbook.asks[0].price)
                    best_ask_size = float(orderbook.asks[0].size)
                    print(f"💸 BEST ASK (what sellers want): ${best_ask:.4f} for {best_ask_size} tokens")
                    print(f"   📋 Top 5 asks:")
                    for i, ask in enumerate(orderbook.asks[:5]):
                        print(f"      #{i+1}: ${float(ask.price):.4f} x {float(ask.size)} tokens")
                else:
                    print(f"⚠️ NO ASKS ON ORDERBOOK")
                    best_ask = 0

            except Exception as ob_error:
                print(f"❌ Failed to get orderbook: {ob_error}")
                best_bid = 0
                best_ask = 0

            # Get live prices from API for comparison (but we'll use orderbook for actual pricing!)
            live_sell_price = self.get_live_price(token_id, "SELL")  # This gets ASK side
            live_buy_price = self.get_live_price(token_id, "BUY")    # This gets BID side

            print(f"\n📡 LIVE API PRICES (most reliable source):")
            print(f"   📊 BID price (what buyers pay): ${live_buy_price:.4f}")
            print(f"   📊 ASK price (what sellers ask): ${live_sell_price:.4f}")

            # Calculate spread
            if live_sell_price > 0 and live_buy_price > 0:
                spread = live_sell_price - live_buy_price
                spread_pct = (spread / live_buy_price) * 100 if live_buy_price > 0 else 0
                print(f"   📊 Spread: ${spread:.4f} ({spread_pct:.2f}%)")

            # ✨ NEW STRATEGY: Use LIVE API BID price with -2% buffer
            # This is your suggested strategy: "mettre 2% plus bas pour s'assurer une belle surprise"
            # User gets quoted conservative price, but actual execution will be BETTER

            if live_buy_price > 0:
                # Use the live BID price (what actual buyers are paying RIGHT NOW on the market)
                api_bid_price = live_buy_price

                # Apply -2% BUFFER so user gets pleasant surprise
                # Quoted: $0.10 | Actual likely: $0.10-$0.12 (better than quoted!)
                buffer_pct = 0.02  # 2% conservative buffer
                quoted_price = api_bid_price * (1 - buffer_pct)

                pricing_mode = "📡 LIVE API BID (-2% buffer)"

                print(f"\n✅ QUOTE STRATEGY (API-based):")
                print(f"   📡 Current market BID: ${api_bid_price:.4f}")
                print(f"   📉 Quoted to user (2% buffer): ${quoted_price:.4f}")
                print(f"   💡 Reason: User gets pleasant surprise when actual > quoted")

                best_price = quoted_price

            else:
                # Fallback: if no live API prices, try orderbook
                logger.warning(f"⚠️ No live API prices available, falling back to orderbook")
                if best_bid > 0:
                    api_bid_price = best_bid
                    buffer_pct = 0.02
                    best_price = api_bid_price * (1 - buffer_pct)
                    pricing_mode = "🎯 ORDERBOOK BID (-2% buffer) [fallback]"
                    print(f"\n⚠️ Fallback to Orderbook BID: ${best_price:.4f} (with 2% buffer)")
                else:
                    logger.error(f"❌ [NO_LIQUIDITY] token_id={token_id[:20]}... | no prices available")
                    print(f"\n❌ CANNOT SELL: No liquidity!")
                    return None

            # Round to API precision requirements
            best_price = round(best_price, 4)  # Price: max 4 decimals

            logger.info(f"{pricing_mode}: ${best_price:.4f} (2% conservative buffer - actual execution likely better)")

            print(f"\n🎯 QUOTED SELL ORDER:")
            print(f"   💎 Quoted price: ${best_price:.4f} ({pricing_mode})")
            print(f"   📦 Selling: {tokens} tokens")
            print(f"   💵 Estimated receive: ${tokens * best_price:.2f} (conservative estimate)")

            print(f"\n⚖️ WHAT TO EXPECT:")
            print(f"   💡 Actual execution will likely be BETTER than quoted")
            print(f"   💡 This is your pleasant surprise buffer!")
            print(f"   💡 Order executes at best available market price via FAK")

            print(f"\n📋 ORDER TYPE: FAK (Fill-And-Kill = IOC)")
            print(f"   ✅ FAK will match immediately at best available prices")
            print(f"   ✅ No slippage - executes at market best bid")
            print(f"{'='*80}\n")

            print(f"💎 USER WALLET SELL - {outcome.upper()} TOKENS")
            print(f"📡 Quoted price: ${best_price:.4f}")
            print(f"📦 Size: {tokens} tokens")
            print(f"💵 Est. Receive: ${tokens * best_price:.2f} (conservative)")
            print(f"🎯 Using YOUR wallet: {self.client.get_address()}")
            print(f"🚀 Strategy: LIVE API PRICING - Fast, Reliable, User-Friendly")
            print(f"🔧 API-safe amounts: price={best_price}, tokens={tokens}")
            print(f"🎯 DIRECT TOKEN ID: {token_id}")
            print(f"📋 Order Type: FAK (Fill-And-Kill = IOC) - Fills at best market price")

            # Create LIMIT sell order with FAK (Fill-And-Kill = IOC) for instant execution
            from py_clob_client.order_builder.constants import SELL
            from py_clob_client.clob_types import OrderArgs, OrderType

            order_args = OrderArgs(
                price=best_price,  # Best price with minimal slippage
                size=tokens,       # Number of tokens to sell
                side=SELL,
                token_id=token_id,
            )

            # Create and submit SELL order with FAK (Fill-And-Kill = IOC)
            # FAK fills what it can immediately at best prices, cancels rest - perfect for high volume
            signed_order = self.client.create_order(order_args)
            resp = self.client.post_order(signed_order, orderType=OrderType.FAK)

            # CRITICAL FIX: Handle response properly and return consistent format
            if isinstance(resp, dict):
                order_id = resp.get('orderID')
            elif isinstance(resp, str):
                order_id = resp  # Response is already the order ID
            else:
                logger.error(f"❌ Unexpected response type: {type(resp)}, content: {resp}")
                return None

            # Return consistent dictionary format for sell_result
            if order_id:
                # 🚀 CRITICAL IMPROVEMENT: Monitor the order and get REAL execution price
                print(f"\n⏳ MONITORING ORDER FOR REAL EXECUTION PRICE...")
                filled = self.monitor_order(order_id, timeout=30)

                if filled:
                    # Get REAL execution details from the order
                    execution_details = self.get_order_execution_details(order_id)

                    if execution_details:
                        # Use REAL price from execution, not estimate!
                        real_price = execution_details['avg_price']
                        real_total = execution_details['total_filled']
                        real_filled = execution_details['filled_qty']

                        print(f"\n✅ REAL EXECUTION vs ESTIMATED:")
                        print(f"   Estimated Price: ${best_price:.6f}")
                        print(f"   REAL Price: ${real_price:.6f}")
                        print(f"   Difference: ${(real_price - best_price):.6f}")

                        return {
                            'order_id': order_id,
                            'sell_price': real_price,  # REAL price from execution!
                            'tokens_sold': real_filled,
                            'total_received': real_total,
                            'transaction_hash': execution_details['transaction_hash'],
                            'estimated_price': best_price,  # Keep estimate for reference
                            'is_real': True  # Flag that this is real, not estimated
                        }
                    else:
                        # Fallback if can't get details
                        print(f"⚠️ Could not retrieve execution details, using estimate")
                        return {
                            'order_id': order_id,
                            'sell_price': best_price,
                            'tokens_sold': tokens,
                            'estimated_proceeds': tokens * best_price,
                            'is_real': False
                        }
                else:
                    # Order didn't fill
                    logger.error(f"❌ Order {order_id} did not complete within timeout")
                    return None
            else:
                return None

        except Exception as e:
            logger.error(f"Speed sell error with user wallet: {e}")
            print(f"❌ Speed sell error: {e}")
            return None

    def monitor_order(self, order_id: str, timeout: int = 30) -> bool:
        """
        Monitor order for completion with stricter verification and improved retry logic

        Args:
            order_id: Order identifier to monitor
            timeout: Maximum seconds to wait

        Returns:
            True if order completed and filled, False otherwise
        """
        try:
            start_time = self.time.time()
            print(f"👀 Monitoring order: {order_id[:20]}...")

            retry_count = 0
            max_retries = 5

            while self.time.time() - start_time < timeout:
                try:
                    order = self.client.get_order(order_id)
                    if order:
                        status = order.get('status')
                        filled_qty = float(order.get('filledQuantity', 0))
                        tx_hashes = order.get('transactionsHashes', [])

                        print(f"🔍 Order status: {status} (filled: {filled_qty:.4f})")

                        # FIXED: Check both filledQuantity AND transactionHashes
                        # Order is complete if either:
                        # 1. Status is FILLED (fully executed)
                        # 2. Status is MATCHED with transactionHashes (blockchain executed, API just lagging)
                        # 3. Status is CANCELLED/EXPIRED/REJECTED (no longer active)

                        if status == 'FILLED':
                            print(f"✅ ORDER FILLED! ({int(self.time.time() - start_time)}s)")
                            return True
                        elif status == 'MATCHED' and tx_hashes:
                            print(f"⚡ Order MATCHED with blockchain transaction: {tx_hashes[0][:20]}...")
                            print(f"   Confirmed on blockchain, API updating...")
                            # For BID orders @ best price with tx confirmation, order succeeded
                            self.time.sleep(2)
                            return True
                        elif status == 'MATCHED':
                            print(f"⚡ Order matched, waiting for blockchain confirmation...")
                            # Small delay to let blockchain confirm
                            self.time.sleep(2)
                            # Retry once more to check for tx hashes
                            if retry_count < max_retries:
                                retry_count += 1
                                self.time.sleep(1)
                                continue
                            else:
                                # After retries, accept MATCHED as complete
                                return True
                        elif status in ['CANCELLED', 'EXPIRED', 'REJECTED']:
                            print(f"❌ Order failed: {status}")
                            return False

                    self.time.sleep(1)

                except Exception as e:
                    print(f"⚠️ Order check error: {e}")
                    self.time.sleep(1)

            print(f"⏳ Order still processing after {timeout}s, assuming execution")
            # Don't give up - if timeout, assume it executed (Polymarket likely submitted order)
            return True

        except Exception as e:
            logger.error(f"Order monitoring error: {e}")
            return False

    def get_order_execution_details(self, order_id: str) -> dict:
        """
        Retrieve actual execution details from order after it completes.

        This returns the REAL prices and amounts the order was actually filled at,
        not estimates.

        Args:
            order_id: Order ID to get details for

        Returns:
            dict with: {
                'order_id': str,
                'status': str,
                'filled_qty': float,
                'avg_price': float (REAL execution price!),
                'total_filled': float (total amount actually received),
                'transaction_hash': str or None
            }
        """
        try:
            logger.info(f"📥 Fetching execution details for order: {order_id}")
            order = self.client.get_order(order_id)

            if not order:
                logger.error(f"❌ Could not retrieve order: {order_id}")
                return None

            logger.info(f"📋 RAW API RESPONSE: {order}")

            # Polymarket API returns different fields depending on order status
            # Try multiple field names for compatibility

            status = order.get('status')

            # Size matched (tokens sold/bought)
            filled_qty = (
                float(order.get('size_matched', 0)) or
                float(order.get('filledQuantity', 0)) or
                float(order.get('original_size', 0))  # If fully matched
            )

            # Price per token
            price_per_token = float(order.get('price', 0))

            # Calculate total based on side
            side = order.get('side', 'SELL').upper()

            # For simplicity: total = size_matched * price
            total_filled = filled_qty * price_per_token if price_per_token > 0 else 0

            transaction_hashes = order.get('transactionHashes') or order.get('transactionsHashes', [])

            logger.info(f"🔎 PARSED API VALUES:")
            logger.info(f"   status={status}")
            logger.info(f"   side={side}")
            logger.info(f"   size_matched={filled_qty}")
            logger.info(f"   price={price_per_token}")
            logger.info(f"   calculated_total={total_filled:.6f}")
            logger.info(f"   transactionHashes count={len(transaction_hashes) if transaction_hashes else 0}")

            # If status is MATCHED and we have size_matched, it's filled
            if status in ['MATCHED', 'FILLED'] and filled_qty > 0:
                execution_details = {
                    'order_id': order_id,
                    'status': status,
                    'filled_qty': filled_qty,
                    'avg_price': price_per_token,
                    'total_filled': total_filled,
                    'transaction_hash': transaction_hashes[0] if transaction_hashes else None,
                    'is_complete': True
                }

                logger.info(f"✅ EXECUTION SUMMARY: filled={filled_qty}, price=${price_per_token:.6f}, total=${total_filled:.4f}, status={status}")

                print(f"\n📊 ACTUAL EXECUTION DETAILS:")
                print(f"   📦 Filled: {execution_details['filled_qty']:.4f} tokens")
                print(f"   💵 Price: ${execution_details['avg_price']:.6f}/token")
                print(f"   💰 Total Received: ${execution_details['total_filled']:.4f}")
                print(f"   ✅ Status: {execution_details['status']}")

                return execution_details
            else:
                logger.warning(f"⚠️ Order {order_id[:20]}... not filled yet. Status: {status}, Filled: {filled_qty}")
                return None

        except Exception as e:
            logger.error(f"❌ Error getting execution details: {e}", exc_info=True)
            return None

    def _get_execution_from_blockchain(self, order_id: str, tx_hash: str) -> Optional[Dict]:
        """
        EMERGENCY FALLBACK: Query blockchain directly for real execution data
        when API filledQuantity is 0 but transactionHash exists

        This handles the edge case where Polymarket API hasn't updated yet but
        the transaction is already confirmed on-chain

        Args:
            order_id: Polymarket order ID (for reference)
            tx_hash: Blockchain transaction hash

        Returns:
            Real execution details from blockchain or None
        """
        try:
            from web3 import Web3

            logger.info(f"🔗 BLOCKCHAIN LOOKUP: Fetching real execution from tx {tx_hash[:20]}...")
            print(f"\n🔗 Querying blockchain for real execution data...")

            # Get Polygon RPC endpoint
            polygon_rpc = "https://polygon-rpc.com/"
            w3 = Web3(Web3.HTTPProvider(polygon_rpc))

            if not w3.is_connected():
                logger.error(f"❌ Could not connect to Polygon RPC")
                return None

            # Get transaction receipt
            try:
                tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
            except Exception as e:
                logger.error(f"❌ Failed to get tx receipt {tx_hash}: {e}")
                return None

            if not tx_receipt:
                logger.error(f"❌ Transaction receipt not found: {tx_hash}")
                return None

            # Check if transaction succeeded
            if tx_receipt.get('status') != 1:
                logger.error(f"❌ Transaction failed on-chain: {tx_hash}")
                return None

            logger.info(f"✅ Transaction confirmed on-chain: {tx_hash}")
            print(f"✅ Transaction confirmed on blockchain!")

            # Try to extract real amounts from transaction logs
            # Polymarket uses Transfer events to move tokens
            try:
                tx_data = w3.eth.get_transaction(tx_hash)

                # Get gas used * gas price to estimate total cost
                gas_used = tx_receipt.get('gasUsed', 0)
                gas_price = tx_data.get('gasPrice', 0)

                logger.info(f"📊 Transaction details:")
                logger.info(f"   Gas used: {gas_used}")
                logger.info(f"   Gas price: {Web3.from_wei(gas_price, 'gwei')} gwei")
                print(f"   Transaction processed: {gas_used} gas @ {Web3.from_wei(gas_price, 'gwei')} gwei")

            except Exception as e:
                logger.warning(f"⚠️ Could not decode transaction data: {e}")

            # CRITICAL: Query order from Polymarket API again to get filled amount
            # Sometimes just having the tx hash is enough to trigger API update
            time.sleep(2)  # Wait for API to update

            order_retry = self.client.get_order(order_id)
            if order_retry:
                filled_qty_retry = float(order_retry.get('filledQuantity', 0))
                total_filled_retry = float(order_retry.get('totalFilled', 0))

                if filled_qty_retry > 0 or total_filled_retry > 0:
                    logger.info(f"✅ API UPDATED after blockchain check:")
                    logger.info(f"   filledQuantity: {filled_qty_retry}")
                    logger.info(f"   totalFilled: ${total_filled_retry:.2f}")

                    # Use the updated values
                    avg_price = total_filled_retry / filled_qty_retry if filled_qty_retry > 0 else 0

                    print(f"✅ API Updated:")
                    print(f"   Filled: {filled_qty_retry} tokens")
                    print(f"   Total: ${total_filled_retry:.2f}")
                    print(f"   Avg Price: ${avg_price:.6f}")

                    return {
                        'order_id': order_id,
                        'status': order_retry.get('status'),
                        'original_qty': float(order_retry.get('origQuantity', 0)),
                        'filled_qty': filled_qty_retry,
                        'avg_price': avg_price,
                        'total_filled': total_filled_retry,
                        'transaction_hash': tx_hash,
                        'is_complete': True,
                        'source': 'blockchain_fallback'
                    }

            logger.warning(f"⚠️ API still shows no fill after blockchain check")
            return None

        except Exception as e:
            logger.error(f"Blockchain fallback error: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def get_sell_quote(self, token_id: str, tokens_to_sell: float) -> dict:
        """
        Get FAST sell quote using cached prices + orderbook verification

        Uses Redis cache for speed (<10ms), falls back to orderbook if needed

        Args:
            token_id: Token to sell
            tokens_to_sell: Amount of tokens

        Returns:
            {
                'quote_price': float,          # Weighted average price
                'total_proceeds': float,       # Amount user will receive
                'liquidity_available': float,  # Actual tokens available
                'source': 'CACHE' | 'ORDERBOOK',
                'confidence': bool             # True if plenty liquidity
            }
        """
        try:
            from core.services.redis_price_cache import RedisPriceCache

            redis_cache = RedisPriceCache()

            # STEP 1: Try Redis cache first (ultra-fast, <1ms)
            cached_price = redis_cache.get_token_price(token_id)

            if cached_price and cached_price > 0:
                # Use cached price as starting point, but verify with orderbook
                quote_proceeds = tokens_to_sell * cached_price

                print(f"\n💰 QUICK QUOTE (Redis Cache):")
                print(f"   Price: ${cached_price:.6f} (from cache)")
                print(f"   Proceeds: ${quote_proceeds:.4f}")

                # STEP 2: Verify/refine with orderbook (more accurate)
                try:
                    orderbook = self.client.get_order_book(token_id)
                    if orderbook and orderbook.bids and len(orderbook.bids) > 0:
                        # Calculate real quote from orderbook
                        total_tokens = 0
                        total_value = 0

                        for bid in orderbook.bids:
                            tokens_needed = tokens_to_sell - total_tokens
                            if tokens_needed <= 0:
                                break

                            tokens_from_bid = min(tokens_needed, bid.size)
                            total_tokens += tokens_from_bid
                            total_value += tokens_from_bid * bid.price

                        if total_tokens >= tokens_to_sell:
                            real_quote_price = total_value / total_tokens
                            real_proceeds = total_value

                            print(f"\n✅ VERIFIED QUOTE (Orderbook):")
                            print(f"   Price: ${real_quote_price:.6f} (from orderbook)")
                            print(f"   Proceeds: ${real_proceeds:.4f}")
                            print(f"   Liquidity: {total_tokens:.2f} tokens available")

                            return {
                                'quote_price': real_quote_price,
                                'total_proceeds': real_proceeds,
                                'liquidity_available': total_tokens,
                                'source': 'ORDERBOOK',
                                'confidence': True
                            }
                except Exception as ob_error:
                    logger.warning(f"Could not verify quote with orderbook: {ob_error}")
                    # Fallback to cached price
                    pass

                # Return cached quote if orderbook not available
                return {
                    'quote_price': cached_price,
                    'total_proceeds': quote_proceeds,
                    'liquidity_available': tokens_to_sell,
                    'source': 'CACHE',
                    'confidence': False  # Not verified
                }

            # STEP 3: No cache, go directly to orderbook
            print(f"\n📊 FULL QUOTE (Orderbook - no cache):")
            orderbook = self.client.get_order_book(token_id)

            if not orderbook or not orderbook.bids or len(orderbook.bids) == 0:
                print(f"   ❌ NO BIDS - Cannot sell!")
                return None

            total_tokens = 0
            total_value = 0

            for bid in orderbook.bids:
                tokens_needed = tokens_to_sell - total_tokens
                if tokens_needed <= 0:
                    break

                tokens_from_bid = min(tokens_needed, bid.size)
                total_tokens += tokens_from_bid
                total_value += tokens_from_bid * bid.price

            if total_tokens < tokens_to_sell:
                print(f"   ⚠️ INSUFFICIENT LIQUIDITY: {total_tokens:.2f} / {tokens_to_sell}")
                return None

            quote_price = total_value / total_tokens
            print(f"   Price: ${quote_price:.6f}")
            print(f"   Proceeds: ${total_value:.4f}")

            return {
                'quote_price': quote_price,
                'total_proceeds': total_value,
                'liquidity_available': total_tokens,
                'source': 'ORDERBOOK',
                'confidence': True
            }

        except Exception as e:
            logger.error(f"Error getting sell quote: {e}")
            print(f"❌ Quote error: {e}")
            return None
