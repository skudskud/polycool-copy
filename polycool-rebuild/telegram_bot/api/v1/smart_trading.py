"""
Smart Trading API Routes
Provides smart trading recommendations and analytics
"""
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse

from core.services.smart_trading import SmartTradingService

router = APIRouter()
smart_trading_service = SmartTradingService()


@router.get("/recommendations")
async def get_recommendations(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(5, ge=1, le=50, description="Trades per page"),
    max_age_minutes: int = Query(60, ge=1, le=1440, description="Maximum age in minutes"),
    min_trade_value: float = Query(300.0, ge=0, description="Minimum trade value in USD"),
    min_win_rate: float = Query(0.55, ge=0, le=1, description="Minimum win rate")
):
    """
    Get paginated smart trading recommendations

    Returns recent trades from high-performing smart wallets that can serve as investment signals.
    """
    try:
        result = await smart_trading_service.get_paginated_recommendations(
            page=page,
            per_page=limit,
            max_age_minutes=max_age_minutes,
            min_trade_value=min_trade_value,
            min_win_rate=min_win_rate
        )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": result,
                "message": f"Retrieved {len(result['trades'])} smart trading recommendations"
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get smart trading recommendations: {str(e)}"
        )


@router.get("/stats")
async def get_smart_trading_stats():
    """
    Get overall statistics about smart trading

    Returns aggregated statistics about smart wallets and their performance.
    """
    try:
        stats = await smart_trading_service.get_smart_wallet_stats()

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": stats,
                "message": "Smart trading statistics retrieved successfully"
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get smart trading stats: {str(e)}"
        )


@router.get("/wallet/{address}")
async def validate_smart_wallet(address: str):
    """
    Validate if an address is a smart wallet and get its details

    Args:
        address: Wallet address to validate

    Returns:
        Wallet validation and statistics
    """
    try:
        result = await smart_trading_service.validate_smart_wallet(address)

        if not result['is_valid']:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "not_found",
                    "data": result,
                    "message": result['reason']
                }
            )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": result,
                "message": "Smart wallet validated successfully"
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to validate smart wallet: {str(e)}"
        )


# Backward compatibility endpoint
@router.get("/")
async def get_smart_trades():
    """Legacy endpoint - redirects to recommendations"""
    return await get_recommendations()
