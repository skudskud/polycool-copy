#!/usr/bin/env python3
"""
Smart Trading Notification Service
Sends push notifications to all users when expert traders make big trades
"""

import logging
import asyncio
import re
from typing import Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.exc import IntegrityError

from database import db_manager, User
from core.persistence.models import SmartWalletTrade, SmartTradeNotification, SmartWallet

logger = logging.getLogger(__name__)


class SmartTradingNotificationService:
    """
    Sends push notifications for smart wallet trades to all active users
    
    Features:
    - Deduplication (no duplicate notifications per trade)
    - Beautiful message formatting
    - Quick buy buttons
    - Analytics tracking
    """
    
    def __init__(self, bot_app=None):
        """
        Initialize notification service
        
        Args:
            bot_app: telegram.ext.Application instance
        """
        self._bot_app = bot_app
        self._eligible_users_cache = None
        self._cache_expires_at = None
        
        # Track failed notifications to log summary instead of individual errors
        self._failed_notifications = {
            'chat_not_found': 0,
            'button_invalid': 0,
            'blocked': 0,
            'deactivated': 0,
            'other': 0
        }
        self._last_summary_log = datetime.now(timezone.utc)
        
        logger.info("✅ Smart Trading Notification Service initialized")
    
    # ===== HELPER FUNCTIONS FOR NEW DETAILED FORMAT =====
    
    @staticmethod
    def _escape_markdown(text: str) -> str:
        """
        Escape special markdown characters to prevent formatting issues
        
        Args:
            text: Text to escape
            
        Returns:
            Escaped text safe for Telegram Markdown
        """
        try:
            if not text:
                return ""
            # Escape special Markdown characters: * _ [ ] ( ) ~ ` > # + - = | { } . !
            return re.sub(r'([*_`\[\]])', r'\\\1', str(text))
        except Exception as e:
            logger.error(f"❌ [FORMAT] Error escaping markdown: {e}")
            return str(text)  # Return original if escaping fails
    
    @staticmethod
    def _safe_get_wallet_address(trade: SmartWalletTrade, wallet: Optional[SmartWallet]) -> Optional[str]:
        """
        Safely extract wallet address with fallbacks
        
        Args:
            trade: SmartWalletTrade instance
            wallet: Optional SmartWallet instance
            
        Returns:
            Wallet address or None
        """
        try:
            address = trade.wallet_address or (wallet.address if wallet else None)
            return address if address else None
        except Exception as e:
            logger.warning(f"⚠️ [FORMAT] Error getting wallet address: {e}")
            return None
    
    @staticmethod
    def _safe_get_smart_score(trade: SmartWalletTrade, wallet: Optional[SmartWallet]) -> Optional[float]:
        """
        Safely extract smart score with fallbacks
        
        Args:
            trade: SmartWalletTrade instance
            wallet: Optional SmartWallet instance
            
        Returns:
            Smart score or None
        """
        try:
            # Try wallet first
            if wallet and hasattr(wallet, 'smartscore') and wallet.smartscore:
                return float(wallet.smartscore)
            
            # Try trade
            if hasattr(trade, 'wallet_smartscore') and trade.wallet_smartscore:
                return float(trade.wallet_smartscore)
            
            return None
        except Exception as e:
            logger.debug(f"[FORMAT] Could not get smart score: {e}")
            return None
    
    @staticmethod
    def _safe_format_timestamp(timestamp) -> str:
        """
        Safely format timestamp as "Nov 05, 2025 at 06:27 UTC"
        
        Args:
            timestamp: datetime object or None
            
        Returns:
            Formatted timestamp string or "Recent"
        """
        try:
            if not timestamp:
                return "Recent"
            
            # Ensure timezone-aware
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            
            return timestamp.strftime("%b %d, %Y at %H:%M UTC")
        except Exception as e:
            logger.warning(f"⚠️ [FORMAT] Error formatting timestamp: {e}")
            return "Recent"
    
    @staticmethod
    def _calculate_confidence_score(win_rate: Optional[float]) -> int:
        """
        Calculate confidence score (1-10) based on win rate
        
        Args:
            win_rate: Win rate as decimal (0-1) or None
            
        Returns:
            Confidence score from 1-10
        """
        try:
            if win_rate is None:
                return 5  # Neutral score if no data
            
            # Ensure win_rate is in valid range
            win_rate = max(0.0, min(1.0, float(win_rate)))
            win_rate_pct = win_rate * 100
            
            if win_rate_pct >= 85:
                return 10
            elif win_rate_pct >= 80:
                return 9
            elif win_rate_pct >= 75:
                return 8
            elif win_rate_pct >= 70:
                return 7
            elif win_rate_pct >= 65:
                return 6
            elif win_rate_pct >= 60:
                return 5
            elif win_rate_pct >= 55:
                return 4
            elif win_rate_pct >= 50:
                return 3
            else:
                return 2
        except Exception as e:
            logger.warning(f"⚠️ [FORMAT] Error calculating confidence score: {e}")
            return 5  # Default to neutral
    
    @staticmethod
    def _format_confidence_visual(score: int) -> str:
        """
        Format confidence score as visual emoji representation
        
        Args:
            score: Confidence score (1-10)
            
        Returns:
            Visual representation with green and gray circles
        """
        try:
            # Clamp score to valid range
            score = max(1, min(10, int(score)))
            filled = "🟢" * score
            empty = "⚫" * (10 - score)
            return filled + empty
        except Exception as e:
            logger.warning(f"⚠️ [FORMAT] Error formatting confidence visual: {e}")
            return "🟢🟢🟢🟢🟢⚫⚫⚫⚫⚫"  # Default to 5/10
    
    @staticmethod
    def _shorten_wallet_address(address: Optional[str]) -> Optional[str]:
        """
        Shorten wallet address to "0xABCD...1234" format
        
        Args:
            address: Full wallet address or None
            
        Returns:
            Shortened address or None
        """
        try:
            if not address:
                return None
            
            address = str(address)
            if len(address) < 10:
                return address  # Too short to shorten
            
            return f"{address[:6]}...{address[-4:]}"
        except Exception as e:
            logger.warning(f"⚠️ [FORMAT] Error shortening wallet address: {e}")
            return address
    
    def set_bot_app(self, bot_app):
        """Set the Telegram bot application instance"""
        self._bot_app = bot_app
        logger.info("✅ Notification service connected to Telegram bot")
    
    async def process_new_trade(self, trade: SmartWalletTrade, wallet: Optional[SmartWallet] = None) -> int:
        """
        Process a new smart wallet trade and send notifications
        
        Args:
            trade: SmartWalletTrade instance
            wallet: Optional SmartWallet instance (for wallet stats)
            
        Returns:
            Number of users notified
        """
        try:
            # Check if trade meets notification criteria
            if not await self.should_notify_trade(trade):
                logger.debug(f"[NOTIF] Trade {trade.id[:16]}... doesn't meet criteria")
                return 0
            
            # Get list of all active users
            eligible_users = await self.get_eligible_users()
            
            if not eligible_users:
                logger.warning("[NOTIF] No eligible users found for notifications")
                return 0
            
            logger.info(f"🔔 [NOTIF] Sending notifications for trade {trade.id[:16]}... to {len(eligible_users)} users")
            
            # Load wallet data if not provided
            if not wallet:
                with db_manager.get_session() as db:
                    from core.persistence.smart_wallet_repository import SmartWalletRepository
                    wallet_repo = SmartWalletRepository(db)
                    wallet = wallet_repo.get_wallet(trade.wallet_address)
            
            # Send notifications to all users
            notified_count = 0
            failed_count = 0
            
            for user_id in eligible_users:
                try:
                    success = await self.send_notification(user_id, trade, wallet)
                    if success:
                        notified_count += 1
                    else:
                        failed_count += 1
                    
                    # Rate limiting: 25 msgs/second (buffer below Telegram's 30/sec limit)
                    await asyncio.sleep(0.04)
                    
                except Exception as e:
                    logger.error(f"❌ [NOTIF] Failed to notify user {user_id}: {e}")
                    failed_count += 1
            
            logger.info(f"✅ [NOTIF] Sent {notified_count} notifications ({failed_count} failed)")
            return notified_count
            
        except Exception as e:
            logger.error(f"❌ [NOTIF] Error processing trade notification: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 0
    
    async def get_eligible_users(self) -> List[int]:
        """
        Get list of all active users (cached for 5 minutes)
        
        Returns:
            List of telegram_user_id values
        """
        try:
            # Check cache
            now = datetime.now(timezone.utc)
            if self._eligible_users_cache and self._cache_expires_at and now < self._cache_expires_at:
                return self._eligible_users_cache
            
            # Fetch from database
            with db_manager.get_session() as db:
                # Get all users who have a wallet (minimum requirement)
                users = db.query(User.telegram_user_id).filter(
                    User.polygon_address.isnot(None)
                ).all()
                
                user_ids = [u.telegram_user_id for u in users]
                
                # Cache for 5 minutes
                self._eligible_users_cache = user_ids
                self._cache_expires_at = now + timedelta(minutes=5)
                
                logger.info(f"📊 [NOTIF] Loaded {len(user_ids)} eligible users (with Polygon addresses, cached for 5 min)")
                logger.info(f"📊 [NOTIF] User IDs: {user_ids[:10]}")  # Show first 10
                return user_ids
                
        except Exception as e:
            logger.error(f"❌ [NOTIF] Error fetching eligible users: {e}")
            return []
    
    async def should_notify_trade(self, trade: SmartWalletTrade) -> bool:
        """
        Check if trade meets notification criteria
        
        Criteria:
        - BUY trade (not SELL)
        - First-time market entry
        - Value >= $400
        - Trade timestamp < 5 minutes old (UNIFIED STANDARD)
        - Not already notified
        
        Args:
            trade: SmartWalletTrade instance
            
        Returns:
            True if should notify, False otherwise
        """
        try:
            # 1. Must be BUY trade
            if not trade.side or trade.side.upper() != 'BUY':
                logger.debug(f"[NOTIF] Trade {trade.id[:16]}... is SELL, skipping")
                return False
            
            # 2. Must be first-time market entry
            if not trade.is_first_time:
                logger.debug(f"[NOTIF] Trade {trade.id[:16]}... is not first-time, skipping")
                return False
            
            # 3. Must be >= $400
            if not trade.value or float(trade.value) < 400.0:
                logger.debug(f"[NOTIF] Trade {trade.id[:16]}... value ${float(trade.value) if trade.value else 0} < $400, skipping")
                return False
            
            # 4. UNIFIED FRESHNESS: Trade must be < 5 minutes old (matches Twitter, Alert Channel)
            if trade.timestamp:
                now = datetime.now(timezone.utc)
                trade_time = trade.timestamp
                if trade_time.tzinfo is None:
                    trade_time = trade_time.replace(tzinfo=timezone.utc)
                
                age_seconds = (now - trade_time).total_seconds()
                age_minutes = age_seconds / 60.0
                
                if age_minutes > 5.0:
                    logger.debug(f"[NOTIF] Trade {trade.id[:16]}... is {age_minutes:.1f} min old (> 5 min), skipping")
                    return False
            
            # 5. Check if already notified (at least to one user)
            with db_manager.get_session() as db:
                existing = db.query(SmartTradeNotification).filter(
                    SmartTradeNotification.trade_id == trade.id
                ).first()
                
                if existing:
                    logger.debug(f"[NOTIF] Trade {trade.id[:16]}... already notified, skipping")
                    return False
            
            logger.info(f"✅ [NOTIF] Trade {trade.id[:16]}... meets all criteria")
            return True
            
        except Exception as e:
            logger.error(f"❌ [NOTIF] Error checking notification criteria: {e}")
            return False
    
    async def send_notification(self, user_id: int, trade: SmartWalletTrade, wallet: Optional[SmartWallet] = None) -> bool:
        """
        Send notification to a single user
        
        Args:
            user_id: Telegram user ID
            trade: SmartWalletTrade instance
            wallet: Optional SmartWallet instance
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            if not self._bot_app:
                logger.warning(f"[NOTIF] Bot not initialized, cannot send notification")
                return False
            
            # Format message and buttons
            message_text, buttons = self.format_notification_message(trade, wallet)
            
            # Send message
            await self._bot_app.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode='Markdown',
                reply_markup=buttons,
                disable_web_page_preview=True
            )
            
            # Track notification in database
            await self.track_notification(user_id, trade.id)
            
            logger.debug(f"✅ [NOTIF] Sent to user {user_id}")
            return True
            
        except Exception as e:
            # Track failed notifications silently, log summary periodically (reduce spam)
            error_str = str(e).lower()
            if "bot was blocked by the user" in error_str:
                self._failed_notifications['blocked'] += 1
            elif "user is deactivated" in error_str:
                self._failed_notifications['deactivated'] += 1
            elif "chat not found" in error_str:
                self._failed_notifications['chat_not_found'] += 1
            elif "button_data_invalid" in error_str:
                self._failed_notifications['button_invalid'] += 1
            else:
                self._failed_notifications['other'] += 1
                # Only log truly unexpected errors
                logger.error(f"❌ [NOTIF] Unexpected error sending to user {user_id}: {e}")
            
            # Log summary every 5 minutes instead of every error
            now = datetime.now(timezone.utc)
            if (now - self._last_summary_log).total_seconds() > 300:  # 5 minutes
                total_failed = sum(self._failed_notifications.values())
                if total_failed > 0:
                    logger.info(
                        f"📊 [NOTIF] Last 5min failures: {total_failed} total "
                        f"(chat_not_found={self._failed_notifications['chat_not_found']}, "
                        f"button_invalid={self._failed_notifications['button_invalid']}, "
                        f"blocked={self._failed_notifications['blocked']}, "
                        f"deactivated={self._failed_notifications['deactivated']}, "
                        f"other={self._failed_notifications['other']})"
                    )
                # Reset counters
                self._failed_notifications = {k: 0 for k in self._failed_notifications}
                self._last_summary_log = now
            
            return False
    
    async def track_notification(self, user_id: int, trade_id: str) -> None:
        """
        Record notification in database for deduplication
        
        Args:
            user_id: Telegram user ID
            trade_id: Trade ID (transaction hash)
        """
        try:
            with db_manager.get_session() as db:
                notification = SmartTradeNotification(
                    trade_id=trade_id,
                    user_id=user_id,
                    notified_at=datetime.now(timezone.utc),
                    clicked=False,
                    action_taken=None
                )
                db.add(notification)
                db.commit()
                
        except IntegrityError:
            # Duplicate notification (already sent to this user)
            logger.debug(f"[NOTIF] Notification already tracked for user {user_id}, trade {trade_id[:16]}...")
        except Exception as e:
            logger.error(f"❌ [NOTIF] Error tracking notification: {e}")
    
    async def send_notification_direct(self, user_id: int, trade_dict: dict, wallet_dict: dict) -> bool:
        """
        Send notification directly using dict data (for unified processor)
        Now uses new detailed format matching alert channel
        
        Args:
            user_id: Telegram user ID
            trade_dict: Trade data dictionary
            wallet_dict: Wallet stats dictionary
            
        Returns:
            True if sent successfully
        """
        try:
            if not self._bot_app:
                logger.warning(f"[NOTIF] Bot not initialized, cannot send notification")
                return False
            
            logger.debug(f"[NEW_FORMAT_DIRECT] Formatting notification for user {user_id}")
            
            # ===== SAFELY EXTRACT ALL FIELDS =====
            
            # Market title
            market_question = trade_dict.get('market_question', 'Unknown Market')
            market_question = market_question[:150]
            market_question = self._escape_markdown(market_question)
            
            # Timestamp
            timestamp = trade_dict.get('timestamp')
            timestamp_str = self._safe_format_timestamp(timestamp)
            
            # Wallet address
            wallet_address = trade_dict.get('wallet_address')
            shortened_wallet = self._shorten_wallet_address(wallet_address) if wallet_address else None
            
            # Win rate
            win_rate = float(wallet_dict.get('win_rate', 0)) if wallet_dict.get('win_rate') else None
            win_rate_pct = win_rate * 100 if win_rate else 50.0
            
            # Smart score
            smart_score = float(wallet_dict.get('smartscore', 0)) if wallet_dict.get('smartscore') else None
            
            # Value & Price
            value = float(trade_dict.get('value', 0))
            price = float(trade_dict.get('price', 0.5))
            
            # Size
            size = float(trade_dict.get('size', 0))
            
            # Side & Outcome
            side = trade_dict.get('side', 'BUY').upper()
            outcome = trade_dict.get('outcome', 'Unknown')
            
            # Confidence score
            confidence_score = self._calculate_confidence_score(win_rate)
            confidence_visual = self._format_confidence_visual(confidence_score)
            
            # ===== BUILD MESSAGE =====
            
            message_parts = [
                "🔥 *Smart Trader Alert*\n\n",
                f"📊 Market: {market_question}\n",
                f"🕐 Trade Time: {timestamp_str}\n\n",
                "Smart wallet just entered:\n"
            ]
            
            # Add wallet address if available
            if shortened_wallet:
                message_parts.append(f"👤 {shortened_wallet}\n")
            
            # Win rate and smart score
            if smart_score:
                message_parts.append(f"📊 Win Rate: {win_rate_pct:.1f}% | Smart Score: {smart_score:.1f}\n")
            else:
                message_parts.append(f"📊 Win Rate: {win_rate_pct:.1f}%\n")
            
            # Position (with optional size)
            size_str = f" \\(Size: {size:,.0f}\\)" if size > 0 else ""
            message_parts.append(f"💰 Position: ${value:,.2f} @ ${price:.2f}{size_str}\n")
            
            # Side
            message_parts.append(f"📈 Side: {side} {outcome}\n\n")
            
            # Confidence score
            message_parts.append(f"🎯 Confidence Score: {confidence_visual} {confidence_score}/10")
            
            message = "".join(message_parts)
            
            # ===== BUILD BUTTONS =====
            condition_id_for_buttons = trade_dict.get('condition_id') or trade_dict.get('market_id') or 'unknown'
            buttons = [
                [
                    InlineKeyboardButton(
                        "📊 View Market",
                        callback_data=f"notif_view_{condition_id_for_buttons[:10]}_{outcome[0].upper()}"
                    )
                ]
            ]
            keyboard = InlineKeyboardMarkup(buttons)
            
            # Send
            await self._bot_app.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            
            # Track notification
            await self.track_notification(user_id, trade_dict['id'])
            
            logger.info(f"✅ [NEW_FORMAT_DIRECT] Sent to user {user_id} (length: {len(message)})")
            return True
            
        except Exception as e:
            logger.error(f"❌ [NOTIF] Failed to send direct notification to user {user_id}: {e}")
            return False
    
    def format_notification_message(self, trade: SmartWalletTrade, wallet: Optional[SmartWallet] = None) -> Tuple[str, InlineKeyboardMarkup]:
        """
        Format trade data into detailed Telegram message (matching alert channel style)
        
        New format includes:
        - Formatted timestamp
        - Wallet address (shortened)
        - Smart score
        - Confidence score visual
        - Size field (if > 0)
        
        Falls back to compact format if any critical error occurs.
        
        Args:
            trade: SmartWalletTrade instance
            wallet: Optional SmartWallet instance for stats
            
        Returns:
            Tuple of (message_text, InlineKeyboardMarkup)
        """
        try:
            logger.debug(f"[NEW_FORMAT] Formatting notification for trade {trade.id[:16] if trade.id else 'unknown'}...")
            
            # ===== SAFELY EXTRACT ALL FIELDS =====
            
            # Market title (REQUIRED)
            market_question = trade.market_question or "Unknown Market"
            market_question = market_question[:150]  # Truncate
            market_question = self._escape_markdown(market_question)
            if not market_question or market_question == "Unknown Market":
                logger.warning(f"[NEW_FORMAT] Missing market question for trade {trade.id}")
            
            # Timestamp
            timestamp_str = self._safe_format_timestamp(trade.timestamp)
            
            # Wallet address
            wallet_address = self._safe_get_wallet_address(trade, wallet)
            shortened_wallet = self._shorten_wallet_address(wallet_address) if wallet_address else None
            
            # Win rate
            win_rate = float(wallet.win_rate) if wallet and wallet.win_rate else None
            win_rate_pct = win_rate * 100 if win_rate else 50.0
            
            # Smart score
            smart_score = self._safe_get_smart_score(trade, wallet)
            
            # Value & Price
            value = float(trade.value) if trade.value else 0
            price = float(trade.price) if trade.price else 0.5
            
            # Size
            size = float(trade.size) if trade.size else 0
            
            # Side & Outcome
            side = (trade.side or "BUY").upper()
            outcome = trade.outcome or "Unknown"
            
            # Confidence score
            confidence_score = self._calculate_confidence_score(win_rate)
            confidence_visual = self._format_confidence_visual(confidence_score)
            
            # ===== BUILD MESSAGE =====
            
            message_parts = [
                "🔥 *Smart Trader Alert*\n\n",
                f"📊 Market: {market_question}\n",
                f"🕐 Trade Time: {timestamp_str}\n\n",
                "Smart wallet just entered:\n"
            ]
            
            # Add wallet address if available
            if shortened_wallet:
                message_parts.append(f"👤 {shortened_wallet}\n")
            
            # Win rate and smart score
            if smart_score:
                message_parts.append(f"📊 Win Rate: {win_rate_pct:.1f}% | Smart Score: {smart_score:.1f}\n")
            else:
                message_parts.append(f"📊 Win Rate: {win_rate_pct:.1f}%\n")
            
            # Position (with optional size)
            size_str = f" \\(Size: {size:,.0f}\\)" if size > 0 else ""
            message_parts.append(f"💰 Position: ${value:,.2f} @ ${price:.2f}{size_str}\n")
            
            # Side
            message_parts.append(f"📈 Side: {side} {outcome}\n\n")
            
            # Confidence score
            message_parts.append(f"🎯 Confidence Score: {confidence_visual} {confidence_score}/10")
            
            message = "".join(message_parts)
            
            # ===== CHECK MESSAGE LENGTH =====
            if len(message) > 4000:
                logger.warning(f"[NEW_FORMAT] Message too long ({len(message)} chars), truncating market title")
                # Retry with shorter market title
                market_question = (trade.market_question[:80] + "...") if trade.market_question else "Unknown Market"
                market_question = self._escape_markdown(market_question)
                
                # Rebuild message with shorter title
                message_parts[1] = f"📊 Market: {market_question}\n"
                message = "".join(message_parts)
            
            # ===== BUILD BUTTONS (unchanged) =====
            condition_id_for_buttons = trade.condition_id or trade.market_id or 'unknown'
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📊 View Market",
                        callback_data=f"notif_view_{condition_id_for_buttons[:10]}_{outcome[0].upper()}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⚡ Quick Buy $2",
                        callback_data=f"notif_buy_{condition_id_for_buttons[:10]}_{outcome[0].upper()}_2"
                    ),
                    InlineKeyboardButton(
                        "💰 Custom Buy",
                        callback_data=f"notif_buy_{condition_id_for_buttons[:10]}_{outcome[0].upper()}_custom"
                    )
                ]
            ])
            
            # Log success
            logger.info(f"✅ [NEW_FORMAT] Successfully formatted notification (length: {len(message)})")
            logger.debug(f"[NEW_FORMAT] Message preview: {message[:100]}...")
            
            return (message, buttons)
            
        except Exception as e:
            logger.error(f"❌ [NEW_FORMAT] Formatting failed, using fallback: {e}", exc_info=True)
            return self._format_notification_fallback(trade, wallet)
    
    def _format_notification_fallback(self, trade: SmartWalletTrade, wallet: Optional[SmartWallet] = None) -> Tuple[str, InlineKeyboardMarkup]:
        """
        Fallback to old compact format if new format fails
        
        Args:
            trade: SmartWalletTrade instance
            wallet: Optional SmartWallet instance
            
        Returns:
            Tuple of (message_text, InlineKeyboardMarkup)
        """
        logger.warning("⚠️ [FALLBACK] Using compact notification format")
        
        try:
            # Market title (truncate if too long)
            market_title = trade.market_question or "Unknown Market"
            if len(market_title) > 100:
                market_title = market_title[:97] + "..."
            
            # Wallet stats
            if wallet:
                win_rate = float(wallet.win_rate) * 100 if wallet.win_rate else 0
                total_pnl = float(wallet.realized_pnl) if wallet.realized_pnl else 0
                wallet_stats = f"{win_rate:.1f}% WR"
                if abs(total_pnl) >= 1000:
                    wallet_stats += f" | ${total_pnl/1000:.1f}K profit"
                elif total_pnl != 0:
                    wallet_stats += f" | ${total_pnl:.0f} profit"
            else:
                wallet_stats = "Expert Trader"
            
            # Position taken
            outcome = trade.outcome or "Unknown"
            entry_price_cents = float(trade.price) * 100 if trade.price else 50
            invested = float(trade.value) if trade.value else 0
            
            # Time ago
            time_ago = "Just now"
            if trade.timestamp:
                now = datetime.now(timezone.utc)
                trade_time = trade.timestamp
                if trade_time.tzinfo is None:
                    trade_time = trade_time.replace(tzinfo=timezone.utc)
                
                seconds = int((now - trade_time).total_seconds())
                if seconds < 60:
                    time_ago = f"{seconds}s ago"
                elif seconds < 3600:
                    time_ago = f"{seconds // 60}m ago"
                else:
                    time_ago = f"{seconds // 3600}h ago"
            
            # Build message (compact format)
            message = (
                f"🚨 *NEW EXPERT TRADE*\n\n"
                f"💎 Trader: {wallet_stats}\n"
                f"🟢 BUY {outcome} @ {entry_price_cents:.0f}¢ • ${invested:,.0f} invested\n\n"
                f"📊 {market_title}\n\n"
                f"⏱️ {time_ago} • Act fast!"
            )
            
            # Create buttons
            condition_id_for_buttons = trade.condition_id or trade.market_id or 'unknown'
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📊 View Market",
                        callback_data=f"notif_view_{condition_id_for_buttons[:10]}_{outcome[0].upper()}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⚡ Quick Buy $2",
                        callback_data=f"notif_buy_{condition_id_for_buttons[:10]}_{outcome[0].upper()}_2"
                    ),
                    InlineKeyboardButton(
                        "💰 Custom Buy",
                        callback_data=f"notif_buy_{condition_id_for_buttons[:10]}_{outcome[0].upper()}_custom"
                    )
                ]
            ])
            
            return (message, buttons)
        except Exception as e:
            logger.error(f"❌ [FALLBACK] Even fallback format failed: {e}")
            # Last resort: minimal message
            minimal_message = "🚨 *NEW EXPERT TRADE*\n\nA smart trader just made a move!"
            minimal_buttons = InlineKeyboardMarkup([[]])
            return (minimal_message, minimal_buttons)


# Global singleton
_notification_service: Optional[SmartTradingNotificationService] = None


def get_smart_trading_notification_service() -> SmartTradingNotificationService:
    """Get global notification service instance"""
    global _notification_service
    if not _notification_service:
        _notification_service = SmartTradingNotificationService()
    return _notification_service


def set_smart_trading_notification_service(service: SmartTradingNotificationService):
    """Set global notification service instance"""
    global _notification_service
    _notification_service = service

