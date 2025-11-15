"""
Pydantic models for webhook payloads
"""
from typing import Optional
from pydantic import BaseModel, Field


class CopyTradeWebhookPayload(BaseModel):
    """Webhook payload from indexer-ts for copy trading"""

    tx_id: str = Field(..., description="Unique transaction ID")
    user_address: str = Field(..., description="Wallet address of trader")
    position_id: Optional[str] = Field(None, description="Position/token ID")
    market_id: Optional[str] = Field(None, description="Market ID")
    outcome: Optional[int] = Field(None, description="Outcome (0=NO, 1=YES)")
    tx_type: str = Field(..., description="Transaction type: BUY or SELL")
    amount: str = Field(..., description="Token amount (decimal string)")
    price: Optional[str] = Field(None, description="Price (decimal string)")
    taking_amount: Optional[str] = Field(None, description="Total USDC amount (decimal string)")
    tx_hash: str = Field(..., description="Transaction hash")
    block_number: Optional[str] = Field(None, description="Block number")
    timestamp: str = Field(..., description="ISO timestamp")


class WebhookResponse(BaseModel):
    """Standard webhook response"""

    status: str = Field(..., description="Status: ok, error, ignored")
    message: Optional[str] = Field(None, description="Optional message")

