#!/usr/bin/env python3
"""
Analytics Handlers
Handles P&L analysis, transaction history, and trading statistics commands
"""

import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler

from telegram_bot.services import get_transaction_service, get_pnl_service, market_service

logger = logging.getLogger(__name__)


async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show comprehensive P&L analysis"""
    user_id = update.effective_user.id

    try:
        await update.message.reply_text("📊 Calculating Portfolio P&L...\n⏳ Fetching real-time market prices...", parse_mode='Markdown')

        pnl_service = get_pnl_service()
        portfolio_pnl = await pnl_service.calculate_portfolio_pnl(user_id)

        if 'error' in portfolio_pnl:
            await update.message.reply_text(f"❌ Error calculating P&L: {portfolio_pnl['error']}")
            return

        if portfolio_pnl['total_positions'] == 0:
            await update.message.reply_text("""
📊 YOUR PORTFOLIO

📭 No Positions Yet

Ready to start trading?

Try these:
• `/markets` - Browse trending markets
• `/search` - Find specific topics
• `/category` - Explore by category

🚀 Let's make your first trade!
            """, parse_mode='Markdown')
            return

        # Format P&L message
        total_pnl = portfolio_pnl['total_pnl']
        roi = portfolio_pnl['portfolio_roi']
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        roi_emoji = "📈" if roi >= 0 else "📉"

        message_text = f"""
📊 PORTFOLIO P&L ANALYSIS

{pnl_emoji} Total P&L: ${total_pnl:.2f}
{roi_emoji} ROI: {roi:.1f}%
💰 Total Invested: ${portfolio_pnl['total_invested']:.2f}
📈 Realized P&L: ${portfolio_pnl['total_realized_pnl']:.2f}
📊 Unrealized P&L: ${portfolio_pnl['total_unrealized_pnl']:.2f}
🎯 Active Positions: {portfolio_pnl['total_positions']}

💡 Commands:
• `/positions` - View detailed positions
• `/history` - Transaction history
        """

        # Add action buttons
        keyboard = [
            [
                InlineKeyboardButton("🔄 Refresh P&L", callback_data="refresh_pnl"),
                InlineKeyboardButton("📋 View Positions", callback_data="view_positions")
            ],
            [
                InlineKeyboardButton("📜 Transaction History", callback_data="show_history")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(message_text, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ P&L command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show transaction history with pagination (10 per page)"""
    user_id = update.effective_user.id

    try:
        # Parse page from command args (default: page 0)
        page = 0
        if context.args and len(context.args) > 0:
            try:
                page = max(0, int(context.args[0]))
            except ValueError:
                pass

        # Fetch more than we display to check if there's a next page
        per_page = 10
        fetch_limit = per_page + 1  # Fetch 11 to check if there's more
        offset = page * per_page

        transaction_service = get_transaction_service()
        transactions = transaction_service.get_user_transactions(user_id, limit=fetch_limit + offset)[offset:]

        # NEW: Load triggered TP/SL orders for backward compatibility
        # This helps identify old transactions that were TP/SL triggers (before we added metadata)
        from database import SessionLocal, TPSLOrder
        from datetime import timedelta
        tpsl_lookup = {}  # Key: (market_id, outcome, ~time) -> TP/SL info

        try:
            with SessionLocal() as session:
                triggered_orders = session.query(TPSLOrder).filter(
                    TPSLOrder.user_id == user_id,
                    TPSLOrder.status == 'triggered'
                ).all()

                for order in triggered_orders:
                    if order.triggered_at:
                        # Create lookup key with time window (±2 minutes)
                        key = (order.market_id, order.outcome.lower(), order.triggered_at)
                        tpsl_lookup[key] = {
                            'type': order.triggered_type,  # 'take_profit' or 'stop_loss'
                            'order_id': order.id,
                            'entry_price': float(order.entry_price) if order.entry_price else None,
                            'execution_price': float(order.execution_price) if order.execution_price else None,
                            'triggered_at': order.triggered_at
                        }
        except Exception as e:
            logger.warning(f"⚠️ Could not load TP/SL orders for history: {e}")
            tpsl_lookup = {}

        # Handle empty history (no transactions at all)
        if not transactions and page == 0:
            await update.message.reply_text("""
📜 TRANSACTION HISTORY

📭 No Trades Yet

Ready to start trading?

Quick Start:
• `/markets` - Browse markets
• `/search` - Find specific topics

🚀 Make your first trade!
            """, parse_mode='Markdown')
            return

        # Handle reaching end of history (page beyond available transactions)
        if not transactions and page > 0:
            keyboard = [
                [InlineKeyboardButton("◀️ Back to Recent", callback_data="history_page_0")],
                [InlineKeyboardButton("🔄 Refresh", callback_data="history_page_0")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"📜 END OF HISTORY\n\n"
                f"✅ You've reached the end of your transaction history.\n\n"
                f"That's all your trades!",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return

        # Check if there are more transactions
        has_more = len(transactions) > per_page
        display_transactions = transactions[:per_page]

        # Page indicator
        page_info = f"Page {page + 1}" if page > 0 else "Recent Trades"

        message_text = f"""
📜 TRANSACTION HISTORY
{page_info}

💡 Note: Shows trades made through this bot. Positions bought elsewhere still appear in /positions and claimable winnings! ✅

"""

        for i, tx in enumerate(display_transactions):
            tx_type = tx['transaction_type']
            emoji = "🟢" if tx_type == 'BUY' else "🔴"

            # Get market data
            market_data = tx.get('market_data', {})
            market_name = market_data.get('question', 'Unknown Market') if market_data else 'Unknown Market'

            # NEW: Check for TP/SL trigger and add indicator + bonus details
            tpsl_indicator = ""
            tpsl_details = ""
            trigger_info = None

            # Method 1: Check market_data for tpsl_trigger (new transactions)
            if market_data and isinstance(market_data, dict) and 'tpsl_trigger' in market_data:
                trigger_info = market_data['tpsl_trigger']

            # Method 2: Check tpsl_lookup table (old transactions - backward compatibility)
            elif tx_type == 'SELL' and tpsl_lookup:
                # Match by market_id, outcome, and time (±2 minutes)
                tx_time = datetime.fromisoformat(tx['executed_at'].replace('Z', '+00:00'))
                for (lookup_market, lookup_outcome, lookup_time), lookup_info in tpsl_lookup.items():
                    if (tx.get('market_id') == lookup_market and
                        tx.get('outcome', '').lower() == lookup_outcome):
                        # Check if times are close (within 2 minutes)
                        time_diff = abs((tx_time - lookup_time).total_seconds())
                        if time_diff <= 120:  # 2 minutes
                            # Calculate P&L for old transactions
                            entry_price = lookup_info.get('entry_price')
                            execution_price = lookup_info.get('execution_price')
                            if entry_price and execution_price:
                                tokens = tx.get('tokens', 0)
                                pnl_amount = tokens * (execution_price - entry_price)
                                pnl_percent = ((execution_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

                                trigger_info = {
                                    'type': lookup_info['type'],
                                    'order_id': lookup_info['order_id'],
                                    'pnl': {
                                        'amount': round(pnl_amount, 2),
                                        'percent': round(pnl_percent, 1)
                                    }
                                }
                            else:
                                trigger_info = {
                                    'type': lookup_info['type'],
                                    'order_id': lookup_info['order_id']
                                }
                            break

            # Process trigger_info if found
            if trigger_info:
                trigger_type = trigger_info.get('type')

                # Add indicator emoji
                if trigger_type == 'take_profit':
                    tpsl_indicator = " 🎯 TP"
                    trigger_label = "Take Profit"
                elif trigger_type == 'stop_loss':
                    tpsl_indicator = " 🛑 SL"
                    trigger_label = "Stop Loss"

                # BONUS: Add detailed info if available
                if trigger_type:
                    order_id = trigger_info.get('order_id', 'Unknown')
                    pnl_data = trigger_info.get('pnl', {})
                    pnl_amount = pnl_data.get('amount', 0)
                    pnl_percent = pnl_data.get('percent', 0)

                    # P&L emoji and sign
                    if pnl_amount == 0:
                        pnl_emoji = "➖"
                        pnl_sign = ""
                    elif pnl_amount > 0:
                        pnl_emoji = "📈"
                        pnl_sign = "+"
                    else:
                        pnl_emoji = "📉"
                        pnl_sign = ""

                    # Build details lines
                    tpsl_details = f"\n   • 🎯 {trigger_label} Order #{order_id} triggered"
                    if pnl_amount != 0 or pnl_percent != 0:
                        tpsl_details += f"\n   • {pnl_emoji} P&L: {pnl_sign}${pnl_amount:.2f} ({pnl_sign}{pnl_percent:.1f}%)"

            # Format date
            executed_at = datetime.fromisoformat(tx['executed_at'].replace('Z', '+00:00'))
            date_str = executed_at.strftime('%m/%d %H:%M')

            message_text += f"""
{emoji} {tx_type}{tpsl_indicator} - {date_str}
   • Market: {market_name[:35]}{'...' if len(market_name) > 35 else ''}
   • Position: {tx['tokens']:.1f} {tx['outcome'].upper()} @ ${tx['price_per_token']:.3f}
   • Total: ${tx['total_amount']:.2f}{tpsl_details}
            """

        # Add pagination buttons
        keyboard = []
        nav_row = []

        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data=f"history_page_{page-1}"))

        if has_more:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"history_page_{page+1}"))

        if nav_row:
            keyboard.append(nav_row)

        # Add refresh button
        keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"history_page_{page}")])

        # Add back to positions button
        keyboard.append([InlineKeyboardButton("⬅️ Back to Positions", callback_data="positions_refresh")])

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.message.reply_text(message_text, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ History command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show trading statistics"""
    user_id = update.effective_user.id

    try:
        # Parse days from command args
        days = 30  # Default
        if context.args and len(context.args) > 0:
            try:
                days = min(int(context.args[0]), 365)  # Max 1 year
            except ValueError:
                pass

        pnl_service = get_pnl_service()
        stats = pnl_service.get_trading_statistics(user_id, days=days)

        if 'error' in stats:
            await update.message.reply_text(f"❌ Error calculating stats: {stats['error']}")
            return

        if stats.get('total_trades', 0) == 0:
            await update.message.reply_text(f"""
📈 TRADING STATISTICS ({days} days)

📭 No Trading Activity
You haven't made any trades in the last {days} days.

💡 Get Started:
• Use /markets to browse trading opportunities
• Use /search to find specific markets

Happy trading! 🚀
            """, parse_mode='Markdown')
            return

        # Calculate additional metrics
        buy_sell_ratio = stats['buy_trades'] / stats['sell_trades'] if stats['sell_trades'] > 0 else float('inf')
        avg_trades_per_day = stats['total_trades'] / stats['trading_days'] if stats['trading_days'] > 0 else 0

        message_text = f"""
📈 TRADING STATISTICS ({days} days)

🎯 Activity Overview:
• Total Trades: {stats['total_trades']}
• Buy Orders: {stats['buy_trades']} 🟢
• Sell Orders: {stats['sell_trades']} 🔴
• Trading Days: {stats['trading_days']}
• Avg Trades/Day: {avg_trades_per_day:.1f}

💰 Volume Analysis:
• Total Volume: ${stats['total_volume']:.2f}
• Buy Volume: ${stats['buy_volume']:.2f}
• Sell Volume: ${stats['sell_volume']:.2f}
• Avg Trade Size: ${stats['avg_trade_size']:.2f}

📊 Trading Patterns:
• Buy/Sell Ratio: {buy_sell_ratio:.1f}:1
        """

        if stats.get('most_active_day'):
            most_active = stats['most_active_day']
            message_text += f"• Most Active Day: {most_active['date']} ({most_active['trades']} trades)"

        message_text += f"""

💡 Commands:
• /stats 7 - Last 7 days stats
• /stats 90 - Last 90 days stats
• /pnl - Portfolio P&L analysis
• /history - Transaction history
        """

        # Add action buttons
        keyboard = [
            [
                InlineKeyboardButton("📊 7 Days", callback_data="stats_7"),
                InlineKeyboardButton("📈 30 Days", callback_data="stats_30"),
                InlineKeyboardButton("📉 90 Days", callback_data="stats_90")
            ],
            [
                InlineKeyboardButton("💰 Show P&L", callback_data="show_pnl"),
                InlineKeyboardButton("📜 View History", callback_data="show_history")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(message_text, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ Stats command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed performance analysis"""
    user_id = update.effective_user.id

    try:
        await update.message.reply_text("🔍 Analyzing Performance...\n⏳ This may take a moment...", parse_mode='Markdown')

        # Get both P&L and statistics
        pnl_service = get_pnl_service()
        portfolio_pnl = await pnl_service.calculate_portfolio_pnl(user_id)
        stats_30d = pnl_service.get_trading_statistics(user_id, days=30)
        stats_7d = pnl_service.get_trading_statistics(user_id, days=7)

        if 'error' in portfolio_pnl:
            await update.message.reply_text(f"❌ Error: {portfolio_pnl['error']}")
            return

        if portfolio_pnl['total_positions'] == 0 and stats_30d.get('total_trades', 0) == 0:
            await update.message.reply_text("""
🔍 PERFORMANCE ANALYSIS

📭 No Trading Activity
You haven't made any trades or have any positions.

💡 Get Started:
• Use /markets to browse opportunities
• Use /search to find specific markets

Happy trading! 🚀
            """, parse_mode='Markdown')
            return

        # Performance indicators
        total_pnl = portfolio_pnl.get('total_pnl', 0)
        roi = portfolio_pnl.get('portfolio_roi', 0)

        # Performance rating
        if roi >= 20:
            performance_rating = "🔥 EXCELLENT"
        elif roi >= 10:
            performance_rating = "🟢 GOOD"
        elif roi >= 0:
            performance_rating = "🟡 MODERATE"
        elif roi >= -10:
            performance_rating = "🟠 NEEDS IMPROVEMENT"
        else:
            performance_rating = "🔴 POOR"

        message_text = f"""
🔍 PERFORMANCE ANALYSIS

🎯 Overall Rating: {performance_rating}

💰 Financial Performance:
• Total P&L: ${total_pnl:.2f}
• ROI: {roi:.1f}%
• Total Invested: ${portfolio_pnl.get('total_invested', 0):.2f}
• Active Positions: {portfolio_pnl.get('total_positions', 0)}

📊 Trading Activity (30d):
• Total Trades: {stats_30d.get('total_trades', 0)}
• Trading Days: {stats_30d.get('trading_days', 0)}
• Avg Trade Size: ${stats_30d.get('avg_trade_size', 0):.2f}

📈 Recent Activity (7d):
• Recent Trades: {stats_7d.get('total_trades', 0)}
• Recent Volume: ${stats_7d.get('total_volume', 0):.2f}

💡 Performance Tips:
        """

        # Add personalized tips based on performance
        if roi < 0:
            message_text += """
• Consider diversifying across more markets
• Review your entry and exit strategies
• Use /pnl to analyze individual positions
            """
        elif roi < 10:
            message_text += """
• Good start! Consider increasing position sizes
• Look for higher volume markets
• Use /search to find trending opportunities
            """
        else:
            message_text += """
• Excellent performance! Keep it up!
• Consider sharing strategies with the community
• Look for new market opportunities
            """

        # Add action buttons
        keyboard = [
            [
                InlineKeyboardButton("📊 Detailed P&L", callback_data="detailed_pnl"),
                InlineKeyboardButton("📈 Full Stats", callback_data="trading_stats")
            ],
            [
                InlineKeyboardButton("📜 Trade History", callback_data="show_history"),
                InlineKeyboardButton("🔄 Refresh Analysis", callback_data="refresh_performance")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(message_text, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ Performance command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


def register(app: Application):
    """Register all analytics command handlers"""
    # P&L and statistics
    app.add_handler(CommandHandler("pnl", pnl_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("performance", performance_command))

    # Transaction history with TP/SL indicators
    app.add_handler(CommandHandler("history", history_command))

    logger.info("✅ Analytics handlers registered (pnl, stats, performance, history)")
