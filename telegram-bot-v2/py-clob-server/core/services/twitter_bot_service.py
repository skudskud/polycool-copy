#!/usr/bin/env python3
"""
Twitter Bot Service
Automatically posts smart wallet trades to Twitter
"""

import logging
import os
import random
import re
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
from requests_oauthlib import OAuth1Session
import time

logger = logging.getLogger(__name__)


class TwitterBotService:
    """
    Service to automatically tweet smart wallet trades
    
    Features:
    - OAuth 1.0a authentication
    - Tweet formatting with hype style
    - Rate limit handling
    - Dry-run mode for testing
    - Duplicate detection
    """
    
    def __init__(self, trade_repo, wallet_repo, db_session, market_service=None):
        """
        Initialize Twitter Bot Service
        
        Args:
            trade_repo: SmartWalletTradeRepository instance
            wallet_repo: SmartWalletRepository instance
            db_session: Database session for logging tweets
            market_service: MarketService instance (optional, for Polymarket links)
        """
        self.trade_repo = trade_repo
        self.wallet_repo = wallet_repo
        self.db_session = db_session
        self.market_service = market_service
        
        # Load configuration from environment
        self.api_key = os.getenv("TWITTER_API_KEY")
        self.api_secret = os.getenv("TWITTER_API_SECRET")
        self.access_token = os.getenv("TWITTER_ACCESS_TOKEN")
        self.access_secret = os.getenv("TWITTER_ACCESS_SECRET")
        
        self.enabled = os.getenv("TWITTER_ENABLED", "false").lower() == "true"
        self.dry_run = os.getenv("TWITTER_DRY_RUN", "true").lower() == "true"
        self.max_tweets_per_cycle = int(os.getenv("TWITTER_MAX_TWEETS_PER_CYCLE", "5"))
        self.min_trade_value = float(os.getenv("TWITTER_MIN_TRADE_VALUE", "400.0"))  # ✅ UNIFIED: Changed from 300 to 400
        self.min_addon_value = float(os.getenv("TWITTER_MIN_ADDON_VALUE", "1000.0"))
        self.tweet_addons = os.getenv("TWITTER_TWEET_ADDONS", "true").lower() == "true"
        
        # FREE TIER LIMITS - Conservative values to avoid rate limits
        self.max_tweets_per_day = int(os.getenv("TWITTER_MAX_TWEETS_PER_DAY", "35"))  # Safe: 35/day (Free tier ~50)
        self.max_tweets_per_hour = int(os.getenv("TWITTER_MAX_TWEETS_PER_HOUR", "2"))  # Safe: 2/hour
        self.max_retry_attempts = int(os.getenv("TWITTER_MAX_RETRY_ATTEMPTS", "3"))  # Max retries before skipping
        self.rate_limit_backoff_minutes = int(os.getenv("TWITTER_RATE_LIMIT_BACKOFF_MINUTES", "60"))  # Wait 1 hour on 429
        
        # Validate credentials
        if not all([self.api_key, self.api_secret, self.access_token, self.access_secret]):
            logger.warning("⚠️ Twitter credentials not fully configured. Set TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET")
            self.enabled = False
        
        # Initialize OAuth session
        if self.enabled and not self.dry_run:
            try:
                self.oauth = OAuth1Session(
                    self.api_key,
                    client_secret=self.api_secret,
                    resource_owner_key=self.access_token,
                    resource_owner_secret=self.access_secret
                )
                logger.info("✅ Twitter OAuth session initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Twitter OAuth: {e}")
                self.enabled = False
        else:
            self.oauth = None
        
        # Rate limit tracking
        self.tweets_posted_today = 0
        self.tweets_posted_this_hour = 0
        self.hourly_window_start = None  # Track when current hour window started
        self.last_reset_date = datetime.now(timezone.utc).date()
        self.rate_limit_remaining = None  # Will be read from Twitter headers
        self.rate_limit_limit = None
        self.rate_limit_reset_time = None
        
        # Retry tracking (in-memory for this session)
        self.trade_retry_counts = {}  # {trade_id: retry_count}
        
        logger.info(f"🐦 Twitter Bot initialized - Enabled: {self.enabled}, Dry Run: {self.dry_run}")
        logger.info(f"📊 Limits: {self.max_tweets_per_day}/day, {self.max_tweets_per_hour}/hour, {self.max_retry_attempts} max retries")
        logger.info(f"💰 Min values: ${self.min_trade_value} first-time, ${self.min_addon_value} add-ons")
    
    def process_pending_trades(self):
        """
        Main loop - fetch untweeted trades and post them with smart pacing
        Called by scheduler every 2 minutes
        
        Features:
        - Daily limit: 35 tweets/day (Free tier safe)
        - Hourly limit: 2 tweets/hour (prevent bursts)
        - Rate limit backoff: 1 hour wait on 429
        - Prioritized trade selection
        """
        try:
            if not self.enabled:
                logger.debug("Twitter bot is disabled (set TWITTER_ENABLED=true to enable)")
                return
            
            # Reset daily counter if new day
            current_time = datetime.now(timezone.utc)
            current_date = current_time.date()
            if current_date > self.last_reset_date:
                logger.info(f"📅 New day! Resetting daily counter (was {self.tweets_posted_today})")
                self.tweets_posted_today = 0
                self.tweets_posted_this_hour = 0
                self.hourly_window_start = None
                self.last_reset_date = current_date
                self.trade_retry_counts = {}  # Reset retry counts
            
            # Reset hourly counter after 1 FULL HOUR from first tweet (not wall clock hour)
            if self.hourly_window_start:
                time_since_window_start = (current_time - self.hourly_window_start).total_seconds()
                if time_since_window_start >= 3600:  # 1 hour = 3600 seconds
                    logger.info(f"⏰ Hourly window expired! Resetting counter (was {self.tweets_posted_this_hour}, window started at {self.hourly_window_start.strftime('%H:%M:%S')})")
                    self.tweets_posted_this_hour = 0
                    self.hourly_window_start = None
            
            # Check if we're rate limited (backoff period)
            if self.rate_limit_reset_time and datetime.now(timezone.utc) < self.rate_limit_reset_time:
                time_remaining = (self.rate_limit_reset_time - datetime.now(timezone.utc)).total_seconds() / 60
                logger.warning(f"⏸️ Rate limit backoff active - {time_remaining:.0f} minutes remaining until {self.rate_limit_reset_time.strftime('%H:%M')}")
                return
            
            # Check daily limit
            if self.tweets_posted_today >= self.max_tweets_per_day:
                logger.info(f"⏸️ Daily tweet limit reached ({self.tweets_posted_today}/{self.max_tweets_per_day}). Resume tomorrow.")
                return
            
            # Check hourly limit
            if self.tweets_posted_this_hour >= self.max_tweets_per_hour:
                if self.hourly_window_start:
                    time_remaining = 3600 - (current_time - self.hourly_window_start).total_seconds()
                    minutes_remaining = int(time_remaining / 60)
                    logger.info(f"⏸️ Hourly limit reached ({self.tweets_posted_this_hour}/{self.max_tweets_per_hour}). Resets in ~{minutes_remaining} min at {(self.hourly_window_start + timedelta(hours=1)).strftime('%H:%M')}")
                else:
                    logger.info(f"⏸️ Hourly limit reached ({self.tweets_posted_this_hour}/{self.max_tweets_per_hour})")
                return
            
            # Calculate how many tweets we can post this cycle
            remaining_today = self.max_tweets_per_day - self.tweets_posted_today
            remaining_this_hour = self.max_tweets_per_hour - self.tweets_posted_this_hour
            tweets_available = min(remaining_today, remaining_this_hour, self.max_tweets_per_cycle)
            
            if tweets_available <= 0:
                logger.debug("No tweet quota available this cycle")
                return
            
            logger.debug(f"📊 Quota: {remaining_today} left today, {remaining_this_hour} left this hour, {tweets_available} available this cycle")
            
            # Get untweeted trades - combine first-time AND add-on trades
            all_trades = []
            
            # 1. Get first-time trades (new positions) - prioritize these
            first_time_trades = self.trade_repo.get_untweeted_qualifying_trades(
                limit=tweets_available,
                min_value=self.min_trade_value
            )
            for trade in first_time_trades:
                trade._tweet_type = 'first_time'
                trade._priority_score = self._calculate_priority_score(trade)
            all_trades.extend(first_time_trades)
            
            # 2. Get add-on trades (doubling down) if enabled and we have quota
            if self.tweet_addons and len(all_trades) < tweets_available:
                remaining_slots = tweets_available - len(all_trades)
                addon_trades = self.trade_repo.get_untweeted_addon_trades(
                    limit=remaining_slots,
                    min_value=self.min_addon_value
                )
                for trade in addon_trades:
                    trade._tweet_type = 'addon'
                    trade._priority_score = self._calculate_priority_score(trade)
                all_trades.extend(addon_trades)
            
            if not all_trades:
                logger.debug("No untweeted trades to process")
                return
            
            # Sort trades by priority score (highest first)
            all_trades.sort(key=lambda t: t._priority_score, reverse=True)
            
            # Filter out trades that have exceeded retry limit
            processable_trades = []
            skipped_trades = []
            for trade in all_trades:
                trade_key = getattr(trade, 'trade_id', trade.id) if hasattr(trade, 'trade_id') else trade.id
                retry_count = self.trade_retry_counts.get(trade_key, 0)
                if retry_count >= self.max_retry_attempts:
                    skipped_trades.append(trade)
                    # Mark as tweeted to stop retrying
                    self.trade_repo.mark_as_tweeted(trade_key)
                    logger.warning(f"⚠️ Trade {trade_key[:16]}... exceeded {self.max_retry_attempts} retries, marking as posted to skip")
                else:
                    processable_trades.append(trade)
            
            if not processable_trades:
                logger.info(f"⚠️ All trades ({len(all_trades)}) have exceeded retry limits, marked as posted")
                return
            
            logger.info(f"🐦 Processing {len(processable_trades)} trades (skipped {len(skipped_trades)} over retry limit)")
            
            tweets_posted = 0
            tweets_failed = 0
            
            for trade in processable_trades[:tweets_available]:
                try:
                    # Get the correct trade ID key (trade_id for SmartWalletTradesToShare, id for others)
                    trade_key = getattr(trade, 'trade_id', trade.id) if hasattr(trade, 'trade_id') else trade.id
                    
                    # Get wallet info
                    wallet = self.wallet_repo.get_wallet(trade.wallet_address)
                    
                    # Format tweet
                    tweet_text = self.format_tweet(trade, wallet)
                    
                    # Post tweet
                    success = self.post_tweet(tweet_text, trade)
                    
                    if success:
                        # Mark as tweeted using the correct ID
                        self.trade_repo.mark_as_tweeted(trade_key)
                        tweets_posted += 1
                        self.tweets_posted_today += 1
                        self.tweets_posted_this_hour += 1
                        
                        # Start hourly window on first tweet
                        if self.hourly_window_start is None:
                            self.hourly_window_start = datetime.now(timezone.utc)
                            logger.debug(f"⏱️  Started new hourly window at {self.hourly_window_start.strftime('%H:%M:%S')}")
                        
                        # Reset retry count on success
                        if trade_key in self.trade_retry_counts:
                            del self.trade_retry_counts[trade_key]
                        
                        # Rate limiting: don't spam Twitter too fast
                        time.sleep(2)  # 2 second delay between tweets
                        
                    else:
                        tweets_failed += 1
                        # Increment retry count
                        self.trade_retry_counts[trade_key] = self.trade_retry_counts.get(trade_key, 0) + 1
                        
                except Exception as e:
                    logger.error(f"❌ Error processing trade {trade_key}: {e}")
                    tweets_failed += 1
                    self.trade_retry_counts[trade_key] = self.trade_retry_counts.get(trade_key, 0) + 1
                    continue
            
            # Summary
            if tweets_posted > 0 or tweets_failed > 0:
                logger.info(f"📊 Twitter Bot Summary: {tweets_posted} posted, {tweets_failed} failed")
                logger.info(f"📈 Today: {self.tweets_posted_today}/{self.max_tweets_per_day}, This hour: {self.tweets_posted_this_hour}/{self.max_tweets_per_hour}")
                if self.rate_limit_remaining is not None:
                    logger.info(f"🔢 Twitter API: {self.rate_limit_remaining} requests remaining")
            
            # Check for pending trades
            pending_first_time = self.trade_repo.count_untweeted_trades(self.min_trade_value)
            pending_addons = self.trade_repo.count_untweeted_addon_trades(self.min_addon_value) if self.tweet_addons else 0
            if pending_first_time > 0 or pending_addons > 0:
                logger.info(f"📝 Pending: {pending_first_time} first-time, {pending_addons} add-ons")
            
        except Exception as e:
            logger.error(f"❌ Error in Twitter bot main loop: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _calculate_priority_score(self, trade) -> int:
        """
        Calculate priority score for a trade to determine tweet order
        Higher score = tweet first
        
        Scoring factors:
        - Trade value (larger = higher priority)
        - Wallet quality (win rate, PnL)
        - Trade freshness (newer = higher priority)
        - Trade type (first-time vs add-on)
        """
        score = 0
        
        try:
            # Value scoring (0-100 points)
            value = float(trade.value) if trade.value else 0
            if value >= 10000:
                score += 100  # Mega whale
            elif value >= 5000:
                score += 80
            elif value >= 2000:
                score += 50
            elif value >= 1000:
                score += 30
            elif value >= 500:
                score += 15
            else:
                score += 5
            
            # Wallet quality (0-30 points)
            wallet = self.wallet_repo.get_wallet(trade.wallet_address)
            if wallet:
                win_rate = float(wallet.win_rate) if wallet.win_rate else 0
                if win_rate >= 0.65:
                    score += 30  # Elite trader
                elif win_rate >= 0.60:
                    score += 20
                elif win_rate >= 0.55:
                    score += 10
            
            # Freshness (0-20 points)
            trade_time = trade.timestamp if hasattr(trade.timestamp, 'tzinfo') and trade.timestamp.tzinfo else trade.timestamp.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - trade_time).total_seconds() / 3600
            if age_hours < 2:
                score += 20  # Very fresh
            elif age_hours < 6:
                score += 15
            elif age_hours < 12:
                score += 10
            elif age_hours < 24:
                score += 5
            
            # Trade type bonus (0-10 points)
            tweet_type = getattr(trade, '_tweet_type', 'first_time')
            if tweet_type == 'first_time':
                score += 10  # Prioritize new positions over add-ons
            
        except Exception as e:
            logger.warning(f"Error calculating priority for trade {trade.id}: {e}")
            score = 0
        
        return score
    
    def format_tweet(self, trade, wallet) -> str:
        """
        Format a trade into a tweet with varied, engaging styles
        
        Handles two types of trades:
        - first_time: New position entries
        - addon: Adding to existing position (doubling down)
        
        Args:
            trade: SmartWalletTrade object (with _tweet_type attribute)
            wallet: SmartWallet object (can be None)
            
        Returns:
            Formatted tweet text (max 280 characters)
        """
        try:
            # Extract data
            value = float(trade.value) if trade.value else 0
            outcome = trade.outcome or "Unknown"
            price = float(trade.price) if trade.price else 0
            market_question = trade.market_question or "Unknown Market"
            wallet_address = trade.wallet_address or ""
            
            # Check if this is an add-on trade
            is_addon = hasattr(trade, '_tweet_type') and trade._tweet_type == 'addon'
            
            # Wallet stats
            if wallet:
                win_rate = float(wallet.win_rate) * 100 if wallet.win_rate else 0
                pnl = float(wallet.realized_pnl) if wallet.realized_pnl else 0
            else:
                win_rate = 0
                pnl = 0
            
            # Format PnL nicely
            if pnl >= 1000:
                pnl_str = f"${pnl/1000:.0f}K"
            elif pnl >= 0:
                pnl_str = f"${pnl:.0f}"
            else:
                pnl_str = f"-${abs(pnl)/1000:.0f}K" if abs(pnl) >= 1000 else f"-${abs(pnl):.0f}"
            
            # Generate wallet profile link
            wallet_link = f"https://polymarket.com/profile/{wallet_address.lower()}" if wallet_address else "https://polymarket.com"
            
            # Truncate question based on needs
            max_q_length = 60 if is_addon else 65
            if len(market_question) > max_q_length:
                market_question = market_question[:max_q_length-3] + "..."
            
            # IF ADD-ON TRADE: Use "doubling down" templates
            if is_addon:
                # Random choice between 3 add-on templates
                addon_choice = random.randint(1, 3)
                
                if addon_choice == 1:
                    tweet = (
                        f"🔥 DOUBLING DOWN\n"
                        f"${value:,.0f} MORE into {outcome}\n"
                        f"📊 {market_question}\n"
                        f"💰 Adding @ {price*100:.1f}¢\n"
                        f"👤 {win_rate:.0f}% WR | {pnl_str}\n"
                        f"{wallet_link}\n\n"
                        f"🔔 Get FREE alerts → t.me/polycool_alerts"
                    )
                elif addon_choice == 2:
                    tweet = (
                        f"💪 Smart wallet ADDING MORE\n"
                        f"+${value:,.0f} → {outcome}\n"
                        f"📊 {market_question}\n"
                        f"👤 {win_rate:.0f}% | {pnl_str} PnL\n"
                        f"They're going ALL IN 🎯\n"
                        f"{wallet_link}\n\n"
                        f"🔔 Get FREE alerts → t.me/polycool_alerts"
                    )
                else:
                    tweet = (
                        f"📈 CONVICTION PLAY\n"
                        f"Adding ${value:,.0f} to {outcome} position\n"
                        f"📊 {market_question}\n"
                        f"👤 {win_rate:.0f}% accuracy | {pnl_str}\n"
                        f"{wallet_link}\n\n"
                        f"🔔 Get FREE alerts → t.me/polycool_alerts"
                    )
            
            # ELSE: Use original first-time templates
            else:
                # Choose a random tweet template for variety
                template_choice = random.randint(1, 5)
                
                # Template 1: Alert Style 🚨
                if template_choice == 1:
                    tweet = (
                        f"🚨 WHALE ALERT\n"
                        f"${value:,.0f} into {outcome}\n"
                        f"📊 {market_question}\n"
                        f"💰 {outcome} @ {price*100:.1f}¢\n"
                        f"👤 {win_rate:.0f}% WR | {pnl_str} PnL\n"
                        f"{wallet_link}\n\n"
                        f"🔔 Get FREE alerts → t.me/polycool_alerts"
                    )
                
                # Template 2: Question Style 🤔
                elif template_choice == 2:
                    direction = "bullish on" if "yes" in outcome.lower() or "up" in outcome.lower() else "betting on"
                    tweet = (
                        f"🤔 Smart money {direction} {outcome}\n"
                        f"${value:,.0f} just dropped\n"
                        f"📊 {market_question}\n"
                        f"👤 Track record: {win_rate:.0f}% | {pnl_str}\n"
                        f"{wallet_link}\n\n"
                        f"🔔 Get FREE alerts → t.me/polycool_alerts"
                    )
                
                # Template 3: Stats First 💎
                elif template_choice == 3:
                    tweet = (
                        f"💎 Proven trader alert\n"
                        f"{win_rate:.0f}% Win Rate | {pnl_str} PnL\n"
                        f"Just bet: ${value:,.0f} → {outcome} @ {price*100:.1f}¢\n"
                        f"📊 {market_question}\n"
                        f"{wallet_link}\n\n"
                        f"🔔 Get FREE alerts → t.me/polycool_alerts"
                    )
                
                # Template 4: Hype Style 🔥
                elif template_choice == 4:
                    tweet = (
                        f"🔥 ${value:,.0f} bet just dropped!\n"
                        f"📊 {market_question}\n"
                        f"💰 {outcome} @ {price*100:.1f}¢\n"
                        f"👤 {win_rate:.0f}% accuracy, {pnl_str} up\n"
                        f"Are they onto something? 👀\n"
                        f"{wallet_link}\n\n"
                        f"🔔 Get FREE alerts → t.me/polycool_alerts"
                    )
                
                # Template 5: Clean Simple 📈
                else:
                    tweet = (
                        f"📈 Smart Wallet Trade\n"
                        f"${value:,.0f} BUY → {outcome} @ {price*100:.1f}¢\n"
                        f"📊 {market_question}\n"
                        f"👤 {win_rate:.0f}% | {pnl_str} PnL\n"
                        f"{wallet_link}\n\n"
                        f"🔔 Get FREE alerts → t.me/polycool_alerts"
                    )
            
            # Ensure we're under 280 characters
            if len(tweet) > 280:
                # Truncate market question further
                overage = len(tweet) - 280
                new_q_length = max_q_length - overage - 10
                if new_q_length > 20:
                    market_question = market_question[:new_q_length] + "..."
                    # Rebuild with shorter question (use template 5 as fallback - shortest)
                    tweet = (
                        f"📈 Smart Trade\n"
                        f"${value:,.0f} → {outcome} @ {price*100:.1f}¢\n"
                        f"📊 {market_question}\n"
                        f"👤 {win_rate:.0f}% | {pnl_str}\n"
                        f"{wallet_link}\n\n"
                        f"🔔 Get FREE alerts → t.me/polycool_alerts"
                    )
                
                # Hard limit if still over
                if len(tweet) > 280:
                    tweet = tweet[:277] + "..."
            
            return tweet
            
        except Exception as e:
            logger.error(f"Error formatting tweet: {e}")
            # Fallback to minimal tweet
            wallet_address = trade.wallet_address or ""
            wallet_link = f"https://polymarket.com/profile/{wallet_address.lower()}" if wallet_address else "https://polymarket.com"
            return f"🔥 ${trade.value} smart trade detected\n{wallet_link}"
    
    def post_tweet(self, tweet_text: str, trade) -> bool:
        """
        Post a tweet to Twitter with comprehensive rate limit handling
        
        Features:
        - Rate limit header parsing
        - 429 backoff (1 hour default)
        - 403 Free tier detection
        - Duplicate detection (187)
        - Detailed logging
        
        Args:
            tweet_text: Text to tweet
            trade: Trade object (for logging)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Dry run mode
            if self.dry_run:
                logger.info(f"🧪 [DRY RUN] Would tweet:\n{tweet_text}\n---")
                # Log to database even in dry-run mode
                self.log_tweet_to_db(trade, tweet_text, status='pending', error_message='DRY_RUN_MODE')
                return True
            
            # Post tweet via Twitter API v2 (Free tier compatible)
            url = "https://api.twitter.com/2/tweets"
            payload = {"text": tweet_text}
            
            response = self.oauth.post(url, json=payload)
            
            # Parse rate limit headers FIRST (available on all responses)
            self._parse_rate_limit_headers(response)
            
            # Handle response
            if response.status_code == 201:
                # SUCCESS - v2 API returns 201 for successful creation
                tweet_data = response.json()
                tweet_id = tweet_data.get('data', {}).get('id')
                logger.info(f"✅ Tweet posted! ID: {tweet_id} | ${trade.value} | Remaining: {self.rate_limit_remaining}")
                # Log to database
                self.log_tweet_to_db(trade, tweet_text, status='posted', tweet_id=tweet_id)
                return True
                
            elif response.status_code == 429:
                # RATE LIMITED
                logger.error(f"🚫 Rate limit exceeded (429)! Retry count: {self.trade_retry_counts.get(trade.id, 0) + 1}/{self.max_retry_attempts}")
                self._handle_rate_limit_429(response)
                self.log_tweet_to_db(trade, tweet_text, status='failed', error_message=f'Rate limit 429 - backoff until {self.rate_limit_reset_time}')
                return False
                
            elif response.status_code == 403:
                # FORBIDDEN - Could be free tier limitation, duplicate, or permission issue
                try:
                    error_data = response.json()
                    errors = error_data.get('errors', [])
                    
                    if not errors:
                        logger.error(f"❌ Twitter 403 - No error details: {response.text[:300]}")
                        self.log_tweet_to_db(trade, tweet_text, status='failed', error_message=f'403 unknown: {response.text[:200]}')
                        return False
                    
                    error = errors[0]
                    error_code = error.get('code')
                    error_message = error.get('message', '')
                    
                    if error_code == 187:
                        # DUPLICATE TWEET - Mark as posted
                        logger.warning(f"⚠️ Duplicate tweet (187), marking as posted")
                        self.log_tweet_to_db(trade, tweet_text, status='posted', error_message='Duplicate tweet (187)')
                        return True
                    
                    elif 'POST /2/tweets' in error_message or 'endpoint' in error_message.lower():
                        # FREE TIER LIMITATION - Mark as posted to avoid infinite retry
                        logger.error(f"❌ Twitter Free Tier limitation - POST not allowed. Marking as posted to skip.")
                        logger.error(f"🔧 SOLUTION: Upgrade to Basic tier ($100/mo) or use v1.1 API")
                        self.log_tweet_to_db(trade, tweet_text, status='failed', error_message=f'Free tier POST blocked - {error_message[:150]}')
                        # Return TRUE to mark as "tweeted" and stop retrying
                        return True
                    
                    else:
                        logger.error(f"❌ Twitter 403 error {error_code}: {error_message}")
                        self.log_tweet_to_db(trade, tweet_text, status='failed', error_message=f'403 {error_code}: {error_message[:150]}')
                        return False
                        
                except Exception as e:
                    logger.error(f"❌ Error parsing 403 response: {e}")
                    self.log_tweet_to_db(trade, tweet_text, status='failed', error_message=f'403 parse error: {str(e)[:150]}')
                    return False
                    
            else:
                # OTHER ERROR
                logger.error(f"❌ Twitter API error {response.status_code}: {response.text[:300]}")
                self.log_tweet_to_db(trade, tweet_text, status='failed', error_message=f'{response.status_code}: {response.text[:200]}')
                return False
                
        except Exception as e:
            logger.error(f"❌ Exception posting tweet: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.log_tweet_to_db(trade, tweet_text, status='failed', error_message=f'Exception: {str(e)[:200]}')
            return False
    
    def _parse_rate_limit_headers(self, response):
        """
        Parse rate limit information from Twitter API response headers
        
        Headers to track:
        - x-rate-limit-limit: Total requests allowed in window
        - x-rate-limit-remaining: Requests remaining in current window
        - x-rate-limit-reset: Unix timestamp when window resets
        
        Args:
            response: Response object from Twitter API
        """
        try:
            limit = response.headers.get('x-rate-limit-limit')
            remaining = response.headers.get('x-rate-limit-remaining')
            reset = response.headers.get('x-rate-limit-reset')
            
            if limit:
                self.rate_limit_limit = int(limit)
            if remaining:
                self.rate_limit_remaining = int(remaining)
            if reset:
                reset_time = datetime.fromtimestamp(int(reset), tz=timezone.utc)
                # Only log if it's a future time (not already passed)
                if reset_time > datetime.now(timezone.utc):
                    logger.debug(f"📊 Rate limit: {remaining}/{limit} remaining, resets at {reset_time.strftime('%H:%M:%S')}")
                    
        except Exception as e:
            logger.warning(f"Error parsing rate limit headers: {e}")
    
    def _handle_rate_limit_429(self, response):
        """
        Handle 429 Rate Limit response with backoff
        
        Free tier limits:
        - ~50 tweets per 24 hours
        - Unknown hourly limit
        
        Strategy:
        - Set backoff period (default 60 minutes)
        - Parse reset time from headers if available
        - Log detailed error
        
        Args:
            response: Response object from Twitter API
        """
        try:
            # Get rate limit reset time from headers
            reset_timestamp = response.headers.get('x-rate-limit-reset')
            if reset_timestamp:
                reset_time = datetime.fromtimestamp(int(reset_timestamp), tz=timezone.utc)
                self.rate_limit_reset_time = reset_time
                minutes_until_reset = (reset_time - datetime.now(timezone.utc)).total_seconds() / 60
                logger.error(f"⏸️ Rate limited by Twitter! Backoff until {reset_time.strftime('%H:%M:%S')} ({minutes_until_reset:.0f} minutes)")
            else:
                # No reset time provided, use default backoff
                from datetime import timedelta
                self.rate_limit_reset_time = datetime.now(timezone.utc) + timedelta(minutes=self.rate_limit_backoff_minutes)
                logger.error(f"⏸️ Rate limited! Backoff {self.rate_limit_backoff_minutes} minutes until {self.rate_limit_reset_time.strftime('%H:%M:%S')}")
            
            # Log current stats
            logger.error(f"📊 Stats when rate limited: {self.tweets_posted_today} posted today, {self.tweets_posted_this_hour} this hour")
            
            # Parse response body for details
            try:
                error_data = response.json()
                if 'errors' in error_data:
                    for error in error_data['errors']:
                        logger.error(f"   Twitter error: {error.get('message', error)}")
            except:
                pass
                
        except Exception as e:
            logger.error(f"Error handling rate limit: {e}")
            # Fallback backoff
            from datetime import timedelta
            self.rate_limit_reset_time = datetime.now(timezone.utc) + timedelta(minutes=self.rate_limit_backoff_minutes)
    
    def get_status(self) -> Dict:
        """Get current bot status with detailed metrics"""
        pending_first_time = self.trade_repo.count_untweeted_trades(self.min_trade_value)
        pending_addons = self.trade_repo.count_untweeted_addon_trades(self.min_addon_value) if self.tweet_addons else 0
        
        return {
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "tweets_today": self.tweets_posted_today,
            "tweets_this_hour": self.tweets_posted_this_hour,
            "max_tweets_per_day": self.max_tweets_per_day,
            "max_tweets_per_hour": self.max_tweets_per_hour,
            "pending_first_time": pending_first_time,
            "pending_addons": pending_addons,
            "min_trade_value": self.min_trade_value,
            "min_addon_value": self.min_addon_value,
            "rate_limited": self.rate_limit_reset_time is not None and datetime.now(timezone.utc) < self.rate_limit_reset_time,
            "rate_limit_reset": self.rate_limit_reset_time.isoformat() if self.rate_limit_reset_time else None,
            "rate_limit_remaining": self.rate_limit_remaining,
            "rate_limit_limit": self.rate_limit_limit,
            "trades_in_retry": len(self.trade_retry_counts)
        }
    
    def log_tweet_to_db(self, trade, tweet_text: str, status: str, tweet_id: str = None, error_message: str = None):
        """
        Log tweet to tweets_bot table for visibility
        
        Args:
            trade: SmartWalletTrade or SmartWalletTradesToShare object
            tweet_text: The tweet text
            status: 'pending', 'posted', or 'failed'
            tweet_id: Twitter's tweet ID (if posted)
            error_message: Error message (if failed)
        """
        try:
            from core.persistence.models import TweetBot
            
            # Get the correct trade ID (trade_id for SmartWalletTradesToShare, id for others)
            trade_key = getattr(trade, 'trade_id', trade.id) if hasattr(trade, 'trade_id') else trade.id
            
            tweet_log = TweetBot(
                trade_id=trade_key,
                tweet_text=tweet_text,
                tweet_id=tweet_id,
                status=status,
                character_count=len(tweet_text),
                market_question=trade.market_question,
                trade_value=trade.value,
                wallet_address=trade.wallet_address,
                posted_at=datetime.utcnow() if status == 'posted' else None,
                error_message=error_message
            )
            
            self.db_session.add(tweet_log)
            self.db_session.commit()
            
            logger.debug(f"📝 Logged tweet to tweets_bot: {status} - {trade_key[:10]}...")
            
        except Exception as e:
            logger.error(f"❌ Failed to log tweet to tweets_bot: {e}")
            self.db_session.rollback()


