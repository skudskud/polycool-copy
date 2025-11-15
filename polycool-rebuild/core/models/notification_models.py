"""
Notification Models
Data models for the centralized notification system
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel


class NotificationPriority(str, Enum):
    """Notification priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationType(str, Enum):
    """Types of notifications supported"""
    TPSL_TRIGGER = "tpsl_trigger"
    TPSL_FAILED = "tpsl_failed"
    COPY_TRADE_SIGNAL = "copy_trade_signal"
    COPY_TRADE_EXECUTED = "copy_trade_executed"
    SMART_TRADE_ALERT = "smart_trade_alert"
    POSITION_UPDATE = "position_update"
    SYSTEM_ALERT = "system_alert"


class Notification(BaseModel):
    """
    Notification data model
    Used for queuing and processing notifications
    """
    id: Optional[str] = None
    user_id: int  # Telegram user ID
    type: NotificationType
    priority: NotificationPriority = NotificationPriority.NORMAL
    data: Dict[str, Any]  # Type-specific data
    created_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3

    def __init__(self, **data):
        super().__init__(**data)
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for Redis storage"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'type': self.type.value,
            'priority': self.priority.value,
            'data': self.data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Notification':
        """Create from dict (Redis retrieval)"""
        # Convert string timestamps back to datetime
        if data.get('created_at'):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('sent_at'):
            data['sent_at'] = datetime.fromisoformat(data['sent_at'])

        # Convert string enums back to enum values
        if 'type' in data:
            data['type'] = NotificationType(data['type'])
        if 'priority' in data:
            data['priority'] = NotificationPriority(data['priority'])

        return cls(**data)

    def mark_sent(self):
        """Mark notification as sent"""
        self.sent_at = datetime.now(timezone.utc)

    def increment_retry(self) -> bool:
        """Increment retry count, return True if can retry"""
        self.retry_count += 1
        return self.retry_count <= self.max_retries


class NotificationResult(BaseModel):
    """Result of notification processing"""
    success: bool
    notification_id: Optional[str] = None
    error_message: Optional[str] = None
    telegram_message_id: Optional[int] = None
    retry_after: Optional[int] = None  # seconds
