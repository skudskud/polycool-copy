"""
Trades API Routes
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.services.trading.trade_service import trade_service
from core.services.user.user_service import user_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class TradeRequest(BaseModel):
    """Request model for trade execution"""
    user_id: int = Field(..., description="Telegram user ID")
    market_id: str = Field(..., description="Market identifier")
    outcome: str = Field(..., description="Outcome: 'Yes' or 'No'")
    amount_usd: float = Field(..., gt=0, description="USD amount to spend")
    order_type: str = Field(default="FOK", description="Order type: 'FOK' (Fill-or-Kill) or 'IOC' (Immediate-or-Cancel)")
    dry_run: bool = Field(default=False, description="Dry run mode (simulate trade without execution)")


class TradeResponse(BaseModel):
    """Response model for trade execution"""
    success: bool
    status: str
    order_id: Optional[str] = None
    tokens: Optional[float] = None
    price: Optional[float] = None
    total_cost: Optional[float] = None
    transaction_hash: Optional[str] = None
    market_title: Optional[str] = None
    error: Optional[str] = None
    dry_run: bool = False


@router.post("/", response_model=TradeResponse)
async def execute_trade(request: TradeRequest):
    """
    Execute a market order trade

    Args:
        request: Trade request with user_id, market_id, outcome, amount_usd, order_type

    Returns:
        Trade execution result
    """
    try:
        # Validate user exists
        user = await user_service.get_by_telegram_id(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail=f"User {request.user_id} not found")

        # Validate outcome
        outcome_upper = request.outcome.upper()
        if outcome_upper not in ['YES', 'NO']:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid outcome '{request.outcome}'. Must be 'Yes' or 'No'"
            )

        # Validate order type
        order_type_upper = request.order_type.upper()
        if order_type_upper not in ['FOK', 'IOC']:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid order_type '{request.order_type}'. Must be 'FOK' or 'IOC'"
            )

        # Execute trade
        logger.info(
            f"🎯 Executing trade: user={request.user_id}, market={request.market_id}, "
            f"outcome={outcome_upper}, amount=${request.amount_usd:.2f}, "
            f"order_type={order_type_upper}, dry_run={request.dry_run}"
        )

        result = await trade_service.execute_market_order(
            user_id=request.user_id,
            market_id=request.market_id,
            outcome=outcome_upper,
            amount_usd=request.amount_usd,
            order_type=order_type_upper,
            dry_run=request.dry_run
        )

        # Format response
        if result.get('status') == 'executed':
            trade_data = result.get('trade', {})
            return TradeResponse(
                success=True,
                status='executed',
                order_id=trade_data.get('order_id'),
                tokens=trade_data.get('tokens'),
                price=trade_data.get('price'),
                total_cost=trade_data.get('total_cost', request.amount_usd),
                transaction_hash=trade_data.get('tx_hash'),
                market_title=result.get('market_title'),
                dry_run=trade_data.get('dry_run', False)
            )
        else:
            return TradeResponse(
                success=False,
                status='failed',
                error=result.get('error', 'Unknown error')
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing trade: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error executing trade: {str(e)}")
