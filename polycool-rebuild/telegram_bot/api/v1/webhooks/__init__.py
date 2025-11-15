"""
Webhook endpoints for external services
"""
from fastapi import APIRouter

webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Import routes to register them
from . import copy_trade

__all__ = ['webhook_router']

