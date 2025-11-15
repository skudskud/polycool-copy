"""
Notification Templates
Standardized templates for all notification types
"""
from typing import Dict, Any, Optional
from core.models.notification_models import NotificationType


class NotificationTemplates:
    """
    Centralized notification template engine
    Provides consistent formatting for all notification types
    """

    @staticmethod
    def get_template(notification_type: NotificationType, data: Dict[str, Any]) -> Optional[str]:
        """Get formatted message for notification type"""
        template_methods = {
            NotificationType.TPSL_TRIGGER: NotificationTemplates._tpsl_trigger_template,
            NotificationType.TPSL_FAILED: NotificationTemplates._tpsl_failed_template,
            NotificationType.COPY_TRADE_SIGNAL: NotificationTemplates._copy_trade_signal_template,
            NotificationType.COPY_TRADE_EXECUTED: NotificationTemplates._copy_trade_executed_template,
            NotificationType.SMART_TRADE_ALERT: NotificationTemplates._smart_trade_alert_template,
            NotificationType.POSITION_UPDATE: NotificationTemplates._position_update_template,
            NotificationType.SYSTEM_ALERT: NotificationTemplates._system_alert_template,
        }

        method = template_methods.get(notification_type)
        if method:
            try:
                return method(data)
            except Exception as e:
                # Fallback template for errors
                return NotificationTemplates._error_template(notification_type, str(e))

        return None

    @staticmethod
    def _tpsl_trigger_template(data: Dict[str, Any]) -> str:
        """Template for TP/SL trigger notifications

        Uses REAL execution data from blockchain transaction:
        - execution_price: Actual price per share from transaction
        - sell_amount: Actual USD received from transaction
        - pnl_amount/pnl_percentage: Calculated from real execution data
        """
        trigger_type = data.get('trigger_type', 'unknown')

        # ✅ Priority: Use execution_price (real transaction data) over current_price (trigger price)
        execution_price = data.get('execution_price') or data.get('current_price', 0)
        trigger_price = data.get('trigger_price')  # TP/SL target price (for reference)

        # ✅ Priority: Use usd_received (real transaction data) over sell_amount (estimated)
        usd_received = data.get('usd_received') or data.get('sell_amount', 0)
        tokens_sold = data.get('tokens_sold', 0)

        # ✅ Use REAL P&L calculated from execution data
        pnl_amount = data.get('pnl_amount', 0)
        pnl_percentage = data.get('pnl_percentage', 0)
        entry_price = data.get('entry_price')  # Entry price for reference

        market_title = data.get('market_title', 'Unknown Market')
        position_outcome = data.get('position_outcome', 'Unknown')
        tx_hash = data.get('tx_hash')  # Transaction hash for verification

        emoji = "🎉" if trigger_type == 'take_profit' else "🛑"
        title = "TAKE PROFIT HIT!" if trigger_type == 'take_profit' else "STOP LOSS TRIGGERED"

        message = f"""{emoji} **{title}**

🏷️ Market: {market_title}
📍 Position: {position_outcome}"""

        # Show trigger price vs execution price if different (slippage info)
        if trigger_price and abs(execution_price - trigger_price) > 0.001:
            message += f"\n🎯 Target Price: ${trigger_price:.4f}"

        message += f"\n💰 Execution Price: ${execution_price:.4f}"

        if entry_price:
            message += f"\n📊 Entry Price: ${entry_price:.4f}"

        if tokens_sold > 0:
            message += f"\n📦 Tokens Sold: {tokens_sold:.4f}"

        message += f"\n💸 Amount Received: ${usd_received:.2f}"
        message += f"\n\n📊 P&L: ${pnl_amount:+.2f} ({pnl_percentage:+.1f}%)"

        if tx_hash:
            message += f"\n\n🔗 Transaction: `{tx_hash[:16]}...`"

        message += "\n\n📈 Use /positions to view updated portfolio."

        return message

    @staticmethod
    def _tpsl_failed_template(data: Dict[str, Any]) -> str:
        """Template for TP/SL failure notifications"""
        trigger_type = data.get('trigger_type', 'unknown')
        reason = data.get('reason', 'unknown_error')
        market_title = data.get('market_title', 'Unknown Market')
        position_outcome = data.get('position_outcome', 'Unknown')
        trigger_price = data.get('trigger_price', 0)
        current_price = data.get('current_price', 0)
        tokens_to_sell = data.get('tokens_to_sell', 0)
        expected_value = data.get('expected_value', 0)
        failure_message = data.get('failure_message', 'TP/SL execution failed')

        emoji = "❌" if trigger_type == 'take_profit' else "⚠️"
        title = "TP/SL EXECUTION FAILED" if trigger_type == 'take_profit' else "TP/SL EXECUTION SKIPPED"

        message = f"""{emoji} **{title}**

🏷️ Market: {market_title}
📍 Position: {position_outcome}
🎯 Trigger: {trigger_type.replace('_', ' ').title()} at ${trigger_price:.4f}
💰 Current Price: ${current_price:.4f}
📦 Tokens to Sell: {tokens_to_sell:.4f}
💸 Expected Value: ${expected_value:.2f}

⚠️ **Reason:** {failure_message}"""

        # Add specific guidance based on failure reason
        if reason == 'insufficient_allowance':
            required_allowance = data.get('required_allowance', 0)
            current_allowance = data.get('current_allowance', 0)
            message += f"""

🔑 **Allowance Issue:**
Required: ${required_allowance:.2f}
Current: ${current_allowance:.2f}

💡 **Solution:** Go to /settings and approve USDC allowance for trading."""

        message += "\n\n📈 Use /positions to manage your position manually."

        return message

    @staticmethod
    def _copy_trade_signal_template(data: Dict[str, Any]) -> str:
        """Template for copy trading signals"""
        leader_address = data.get('leader_address', 'Unknown')[:10] + "..."
        market_title = data.get('market_title', 'Unknown Market')
        action = data.get('action', 'Unknown')
        amount = data.get('amount', 0)
        confidence = data.get('confidence', 0)

        return f"""👥 **Copy Trade Signal**

👤 Leader: {leader_address}
📊 Market: {market_title}
🎯 Action: {action.upper()}
💰 Amount: ${amount:.2f}

📈 Confidence: {confidence}%
⏰ Executed automatically."""

    @staticmethod
    def _copy_trade_executed_template(data: Dict[str, Any]) -> str:
        """Template for copy trade execution notifications"""
        market_title = data.get('market_title', 'Unknown Market')
        side = data.get('side', 'Unknown')  # BUY or SELL
        amount_usd = data.get('amount_usd', 0)
        leader_address = data.get('leader_address', 'Unknown')[:10] + "..."
        potential_profit = data.get('potential_profit')

        # Determine emoji based on side
        emoji = "🟢" if side.upper() == "BUY" else "🔴"
        action_verb = "Bought" if side.upper() == "BUY" else "Sold"

        message = f"""{emoji} **Copy Trade Executed**

👤 Leader: {leader_address}
📊 Market: {market_title}
🎯 Action: {action_verb} ({side.upper()})
💰 Amount: ${amount_usd:.2f}"""

        if potential_profit is not None:
            message += f"\n📈 Potential Profit: {potential_profit:.1f}x"

        message += "\n\n📋 Following your leader's strategy."
        return message

    @staticmethod
    def _smart_trade_alert_template(data: Dict[str, Any]) -> str:
        """Template for smart trading alerts"""
        strategy_name = data.get('strategy_name', 'Unknown Strategy')
        market_title = data.get('market_title', 'Unknown Market')
        action = data.get('action', 'Unknown')
        confidence = data.get('confidence', 0)
        expected_return = data.get('expected_return')

        message = f"""🎯 **Smart Trade Alert**

🧠 Strategy: {strategy_name}
📊 Market: {market_title}
🎯 Action: {action.upper()}
📈 Confidence: {confidence}%"""

        if expected_return is not None:
            message += f"\n💰 Expected Return: {expected_return:+.1f}%"

        message += "\n\n⚡ Executed automatically."
        return message

    @staticmethod
    def _position_update_template(data: Dict[str, Any]) -> str:
        """Template for position updates"""
        market_title = data.get('market_title', 'Unknown Market')
        update_type = data.get('update_type', 'updated')
        new_amount = data.get('new_amount')
        reason = data.get('reason', '')

        message = f"""📊 **Position {update_type.title()}**

🏷️ Market: {market_title}"""

        if new_amount is not None:
            message += f"\n💰 New Amount: ${new_amount:.2f}"

        if reason:
            message += f"\nℹ️ Reason: {reason}"

        message += "\n\n📈 Use /positions to view details."
        return message

    @staticmethod
    def _system_alert_template(data: Dict[str, Any]) -> str:
        """Template for system alerts"""
        alert_type = data.get('alert_type', 'info')
        title = data.get('title', 'System Alert')
        message = data.get('message', '')

        emoji_map = {
            'info': 'ℹ️',
            'warning': '⚠️',
            'error': '❌',
            'success': '✅'
        }

        emoji = emoji_map.get(alert_type, 'ℹ️')

        return f"""{emoji} **{title}**

{message}"""

    @staticmethod
    def _error_template(notification_type: NotificationType, error: str) -> str:
        """Fallback template for formatting errors"""
        return f"""❌ **Notification Error**

Type: {notification_type.value}
Error: {error}

Please contact support if this persists."""

    @staticmethod
    def format_price_with_precision(price: float, market_data: Optional[Dict] = None) -> str:
        """Format price with appropriate precision for the market"""
        if market_data and market_data.get('price_precision'):
            precision = market_data['price_precision']
        else:
            # Default precision for Polymarket (4 decimals)
            precision = 4

        return f"${price:.{precision}f}"
