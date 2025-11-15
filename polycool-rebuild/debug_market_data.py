#!/usr/bin/env python3
"""
Debug script to check market data in database
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

async def debug_market_data():
    """Debug market data for the problematic market"""
    from core.database.connection import get_db
    from sqlalchemy import select
    from core.database.models import Market

    try:
        async with get_db() as db:
            # Get data for market 551963
            result = await db.execute(
                select(Market.id, Market.title, Market.outcome_prices, Market.last_mid_price, Market.last_trade_price, Market.source)
                .where(Market.id == "551963")
            )

            market = result.scalar_one_or_none()
            if market:
                print("=== MARKET DATA DEBUG ===")
                print(f"ID: {market.id}")
                print(f"Title: {market.title}")
                print(f"Source: {market.source}")
                print(f"Outcome Prices: {market.outcome_prices}")
                print(f"Last Mid Price: {market.last_mid_price}")
                print(f"Last Trade Price: {market.last_trade_price}")
                print(f"Type of outcome_prices: {type(market.outcome_prices)}")

                if market.outcome_prices:
                    print(f"Length of outcome_prices: {len(market.outcome_prices)}")
                    if isinstance(market.outcome_prices, list):
                        for i, price in enumerate(market.outcome_prices):
                            print(f"  outcome_prices[{i}]: {price} (type: {type(price)})")

                # Test price extraction
                from core.services.position.position_service import position_service
                yes_price = position_service._extract_position_price({
                    'outcome_prices': market.outcome_prices,
                    'last_mid_price': market.last_mid_price
                }, "YES")

                no_price = position_service._extract_position_price({
                    'outcome_prices': market.outcome_prices,
                    'last_mid_price': market.last_mid_price
                }, "NO")

                print("\n=== PRICE EXTRACTION TEST ===")
                print(f"YES price: {yes_price}")
                print(f"NO price: {no_price}")

            else:
                print("❌ Market 551963 not found")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_market_data())
