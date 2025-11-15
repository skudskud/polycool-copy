"""
Position Models - Helper classes for API responses
"""
from datetime import datetime, timezone
from typing import Dict, Any


class PositionFromAPI:
    """
    Helper class to convert API response to Position-like object
    Used when SKIP_DB=true to maintain compatibility with Position objects
    """
    def __init__(self, data: Dict[str, Any]):
        self.id = data.get('id')
        self.user_id = data.get('user_id')
        self.market_id = data.get('market_id')
        self.outcome = data.get('outcome')
        self.amount = data.get('amount')
        self.entry_price = data.get('entry_price')
        self.current_price = data.get('current_price')
        self.pnl_amount = data.get('pnl_amount', 0.0)
        self.pnl_percentage = data.get('pnl_percentage', 0.0)
        self.status = data.get('status', 'active')
        self.is_copy_trade = data.get('is_copy_trade', False)
        self.take_profit_price = data.get('take_profit_price')
        self.stop_loss_price = data.get('stop_loss_price')
        self.total_cost = data.get('total_cost')

        # Parse timestamps
        created_at_str = data.get('created_at')
        if created_at_str:
            try:
                self.created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                self.created_at = datetime.now(timezone.utc)
        else:
            self.created_at = datetime.now(timezone.utc)

        updated_at_str = data.get('updated_at')
        if updated_at_str:
            try:
                self.updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                self.updated_at = datetime.now(timezone.utc)
        else:
            self.updated_at = datetime.now(timezone.utc)
