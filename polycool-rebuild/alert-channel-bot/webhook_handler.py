"""
Webhook handler for receiving trade notifications from main bot
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import settings
from database import check_trade_sent, mark_trade_sent, save_alert_history
from formatter import format_alert_message
from sender import get_alert_sender

logger = logging.getLogger(__name__)

router = APIRouter()


class TradeNotificationPayload(BaseModel):
    """Webhook payload from main bot"""
    trade_id: str
    market_id: Optional[str] = None
    market_title: Optional[str] = None
    position_id: Optional[str] = None
    wallet_address: str
    wallet_name: Optional[str] = None
    win_rate: Optional[float] = None
    risk_score: Optional[float] = None  # This is smart_score source
    outcome: Optional[str] = None
    side: Optional[str] = None
    price: Optional[float] = None
    value: Optional[float] = None
    amount_usdc: Optional[float] = None
    timestamp: Optional[str] = None


class WebhookResponse(BaseModel):
    """Webhook response"""
    status: str
    message: str
    trade_id: Optional[str] = None


@router.post("/api/v1/alert-channel/notify", response_model=WebhookResponse)
async def receive_trade_notification(
    payload: TradeNotificationPayload,
    request: Request
) -> WebhookResponse:
    """
    Receive trade notification from main bot and send to alert channel
    
    Args:
        payload: Trade notification data
        request: FastAPI request object
        
    Returns:
        WebhookResponse with status
    """
    try:
        trade_id = payload.trade_id
        
        logger.info(f"📨 Received trade notification: {trade_id[:20]}...")
        
        # Filter: Skip trades with unknown outcome or missing market title
        if payload.outcome == "UNKNOWN" or not payload.market_title:
            logger.debug(f"⏭️ Trade {trade_id[:20]}... filtered (outcome: {payload.outcome}, market: {payload.market_title})")
            return WebhookResponse(
                status="ignored",
                message="Trade filtered (unknown outcome or missing market)",
                trade_id=trade_id
            )
        
        # Filter: Skip trades below minimum trade value
        trade_value = payload.value or payload.amount_usdc or 0.0
        if trade_value < settings.min_trade_value:
            logger.debug(f"⏭️ Trade {trade_id[:20]}... filtered (value: ${trade_value:.2f} < ${settings.min_trade_value:.2f})")
            return WebhookResponse(
                status="ignored",
                message=f"Trade filtered (value ${trade_value:.2f} below minimum ${settings.min_trade_value:.2f})",
                trade_id=trade_id
            )
        
        # Check if already sent (deduplication)
        if await check_trade_sent(trade_id):
            logger.debug(f"⏭️ Trade {trade_id[:20]}... already sent, skipping")
            return WebhookResponse(
                status="ignored",
                message="Trade already sent to alert channel",
                trade_id=trade_id
            )
        
        # Format message
        trade_data = {
            "trade_id": trade_id,
            "market_id": payload.market_id,
            "market_title": payload.market_title,
            "wallet_address": payload.wallet_address,
            "wallet_name": payload.wallet_name,
            "win_rate": payload.win_rate,
            "risk_score": payload.risk_score,  # This becomes smart_score
            "outcome": payload.outcome,
            "side": payload.side,
            "price": payload.price,
            "value": payload.value or payload.amount_usdc,
            "timestamp": payload.timestamp
        }
        
        message = format_alert_message(trade_data)
        
        # Send to Telegram channel
        sender = get_alert_sender()
        success = await sender.send_alert(message)
        
        if not success:
            logger.warning(f"⚠️ Failed to send alert for trade {trade_id[:20]}...")
            return WebhookResponse(
                status="error",
                message="Failed to send alert (rate limit or error)",
                trade_id=trade_id
            )
        
        # Mark as sent
        await mark_trade_sent(trade_id)
        
        # Save to history
        await save_alert_history(
            trade_id=trade_id,
            market_id=payload.market_id,
            market_title=payload.market_title,
            wallet_address=payload.wallet_address,
            wallet_name=payload.wallet_name,
            win_rate=payload.win_rate,
            smart_score=payload.risk_score,  # risk_score is smart_score
            confidence_score=None,  # Will be calculated in formatter
            outcome=payload.outcome,
            side=payload.side,
            price=payload.price,
            value=payload.value or payload.amount_usdc,
            amount_usdc=payload.amount_usdc,
            message_text=message
        )
        
        logger.info(f"✅ Successfully processed trade notification: {trade_id[:20]}...")
        
        return WebhookResponse(
            status="success",
            message="Alert sent successfully",
            trade_id=trade_id
        )
        
    except Exception as e:
        logger.error(f"❌ Error processing trade notification: {e}")
        return WebhookResponse(
            status="error",
            message=f"Error processing notification: {str(e)}",
            trade_id=payload.trade_id if payload else None
        )

