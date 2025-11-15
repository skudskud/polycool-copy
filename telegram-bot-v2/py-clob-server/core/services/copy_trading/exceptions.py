"""
Copy Trading Custom Exceptions
Clean exception hierarchy for error handling
"""


class CopyTradingException(Exception):
    """Base exception for copy trading errors"""
    pass


class SubscriptionException(CopyTradingException):
    """Raised when subscription operations fail"""
    pass


class InvalidConfigException(CopyTradingException):
    """Raised when configuration is invalid"""
    pass


class InsufficientBudgetException(CopyTradingException):
    """Raised when copy trading budget is insufficient"""
    pass


class CopyExecutionException(CopyTradingException):
    """Raised when copy trade execution fails"""
    pass


class LeaderNotFoundError(CopyTradingException):
    """Raised when leader user is not found"""
    pass


class FollowerNotFoundError(CopyTradingException):
    """Raised when follower user is not found"""
    pass


class SubscriptionNotFoundError(CopyTradingException):
    """Raised when subscription is not found"""
    pass


class MultipleSubscriptionsError(CopyTradingException):
    """Raised when trying to create second subscription for a user"""
    pass
