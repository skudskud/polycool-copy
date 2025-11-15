"""
Price Extractor - Extract and map prices from WebSocket messages
Handles multiple Polymarket WebSocket formats with proper outcome mapping
"""
import json
from typing import Dict, Any, Optional, List
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class PriceExtractor:
    """
    Extract prices from WebSocket messages with proper outcome mapping
    Maps asset_id from price_changes to outcomes using clob_token_ids
    """

    @staticmethod
    async def extract_prices(
        data: Dict[str, Any],
        market_data: Optional[Dict[str, Any]] = None
    ) -> Optional[List[float]]:
        """
        Extract prices from WebSocket message with proper outcome mapping

        Maps asset_id from price_changes to outcomes using clob_token_ids

        Args:
            data: WebSocket message data
            market_data: Market data with clob_token_ids and outcomes (optional)

        Returns:
            List of prices in outcome order [outcome1_price, outcome2_price, ...] or None
        """
        logger.info(f"🔍 Extracting prices from message with keys: {list(data.keys())[:20]}")

        # Try Polymarket format: price_changes array with asset_id mapping
        price_changes = data.get("price_changes")
        if price_changes and isinstance(price_changes, list):
            # If we have market_data, map asset_id to outcome index
            if market_data:
                prices = PriceExtractor._map_asset_to_outcome(price_changes, market_data)
                if prices:
                    return prices

            # Fallback: extract prices in order (assumes order matches outcomes)
            # ⚠️ WARNING: This fallback may have incorrect outcome mapping if order doesn't match
            # Prefer best_bid/best_ask over legacy price field
            prices = []
            for change in price_changes:
                if isinstance(change, dict):
                    # NEW FORMAT: Try best_bid/best_ask first
                    best_bid = change.get("best_bid")
                    best_ask = change.get("best_ask")
                    legacy_price = change.get("price") or change.get("last_price")

                    price_float = None
                    if best_bid is not None and best_ask is not None:
                        try:
                            best_bid_float = float(best_bid)
                            best_ask_float = float(best_ask)
                            if 0 <= best_bid_float <= 1 and 0 <= best_ask_float <= 1 and best_bid_float <= best_ask_float:
                                price_float = (best_bid_float + best_ask_float) / 2.0
                        except (ValueError, TypeError):
                            pass

                    # Fallback to legacy price
                    if price_float is None and legacy_price is not None:
                        try:
                            price_float = float(legacy_price)
                        except (ValueError, TypeError):
                            pass

                    if price_float is not None:
                        prices.append(price_float)

            if prices:
                outcomes = market_data.get("outcomes") if market_data else None
                logger.warning(f"⚠️ Using fallback price extraction (no mapping) - prices may be in wrong order: {prices}")
                logger.warning(f"   Market outcomes: {outcomes if market_data else 'unknown'}")
                logger.warning(f"   This may cause YES/NO inversion - check market data!")
                return prices

        # Fallback to old method
        return PriceExtractor._extract_prices_fallback(data)

    @staticmethod
    def _map_asset_to_outcome(
        price_changes: List[Dict[str, Any]],
        market_data: Dict[str, Any]
    ) -> Optional[List[float]]:
        """
        Map asset_id from price_changes to outcome index using market_data

        Args:
            price_changes: List of price change dicts with asset_id and price
            market_data: Market data with clob_token_ids and outcomes

        Returns:
            List of prices in outcome order or None
        """
        clob_token_ids = market_data.get("clob_token_ids")
        outcomes = market_data.get("outcomes")

        if not clob_token_ids or not outcomes or not isinstance(clob_token_ids, list):
            return None

        # Parse clob_token_ids if it's a JSON string
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except:
                return None

        # Create mapping: asset_id -> outcome_index
        asset_to_outcome = {}
        for idx, token_id in enumerate(clob_token_ids):
            if idx < len(outcomes):
                asset_to_outcome[str(token_id)] = idx

        # Extract prices and map to outcome order
        # According to Polymarket docs: prefer best_bid/best_ask for mid price calculation
        # Fallback to price field if best_bid/best_ask not available
        outcome_prices = [None] * len(outcomes)
        for change in price_changes:
            if isinstance(change, dict):
                asset_id = str(change.get("asset_id") or change.get("asset") or "")

                # NEW FORMAT (recommended): Use best_bid/best_ask to calculate mid price
                best_bid = change.get("best_bid")
                best_ask = change.get("best_ask")
                legacy_price = change.get("price") or change.get("last_price")

                price_float = None
                price_source = None

                if best_bid is not None and best_ask is not None:
                    try:
                        # Calculate mid price from orderbook (more accurate)
                        best_bid_float = float(best_bid)
                        best_ask_float = float(best_ask)

                        # Validate bid/ask are reasonable (0-1 range, bid <= ask)
                        if 0 <= best_bid_float <= 1 and 0 <= best_ask_float <= 1 and best_bid_float <= best_ask_float:
                            price_float = (best_bid_float + best_ask_float) / 2.0
                            price_source = f"bid/ask (${best_bid_float:.4f}/${best_ask_float:.4f})"
                        else:
                            logger.warning(
                                f"⚠️ Invalid bid/ask for asset {asset_id[:20]}...: "
                                f"bid={best_bid_float}, ask={best_ask_float} - using legacy price"
                            )
                            if legacy_price is not None:
                                price_float = float(legacy_price)
                                price_source = "legacy (bid/ask invalid)"
                    except (ValueError, TypeError) as e:
                        logger.debug(f"⚠️ Error parsing bid/ask for asset {asset_id[:20]}...: {e}")
                        if legacy_price is not None:
                            price_float = float(legacy_price)
                            price_source = "legacy (parse error)"
                elif legacy_price is not None:
                    # OLD FORMAT: Fallback to legacy price field
                    try:
                        price_float = float(legacy_price)
                        price_source = "legacy"
                    except (ValueError, TypeError):
                        pass

                if asset_id and price_float is not None:
                    outcome_idx = asset_to_outcome.get(asset_id)
                    if outcome_idx is not None:
                        outcome_prices[outcome_idx] = price_float
                        logger.debug(
                            f"   Mapped asset_id {asset_id[:20]}... → "
                            f"outcome[{outcome_idx}]={outcomes[outcome_idx]} → "
                            f"price {price_float:.4f} ({price_source})"
                        )

        # Filter out None values and return in outcome order
        prices = [p for p in outcome_prices if p is not None]
        if prices and len(prices) == len(outcomes):
            logger.info(
                f"✅ Extracted {len(prices)} prices with outcome mapping: "
                f"{prices} (outcomes: {outcomes})"
            )
            return prices
        elif prices:
            logger.warning(
                f"⚠️ Partial price mapping: {len(prices)}/{len(outcomes)} prices found "
                f"(prices: {prices}, outcomes: {outcomes})"
            )
            # For binary markets, try to calculate missing price
            if len(outcomes) == 2 and len(prices) == 1:
                known_price = prices[0]
                missing_price = 1.0 - known_price
                if 0 <= missing_price <= 1:
                    logger.info(f"✅ Calculated missing price: {missing_price:.4f} (from {known_price:.4f})")
                    # Determine which outcome is missing
                    if outcome_prices[0] is None:
                        return [missing_price, known_price]
                    else:
                        return [known_price, missing_price]
            return prices

        logger.warning(f"⚠️ No prices extracted from price_changes (outcomes: {outcomes})")
        return None

    @staticmethod
    def _extract_prices_fallback(data: Dict[str, Any]) -> Optional[List[float]]:
        """
        Fallback price extraction (original logic)
        Handles multiple Polymarket formats
        """
        logger.debug(f"🔍 Extracting prices (fallback) from message with keys: {list(data.keys())[:20]}")

        # Try Polymarket format: price_changes array
        price_changes = data.get("price_changes")
        if price_changes and isinstance(price_changes, list):
            prices = []
            for change in price_changes:
                if isinstance(change, dict):
                    # Format: {"asset_id": "...", "price": 0.5}
                    price = change.get("price") or change.get("last_price")
                    if price is not None:
                        try:
                            prices.append(float(price))
                        except (ValueError, TypeError):
                            pass
            if prices:
                logger.info(f"✅ Extracted {len(prices)} prices from price_changes: {prices}")
                return prices

        # Try Polymarket format: assets array with prices
        assets = data.get("assets") or data.get("assets_ids")
        if assets and isinstance(assets, list):
            prices = []
            for asset in assets:
                if isinstance(asset, dict):
                    price = asset.get("price") or asset.get("last_price")
                    if price is not None:
                        try:
                            prices.append(float(price))
                        except (ValueError, TypeError):
                            pass
            if prices:
                return prices

        # Try different possible formats
        prices = data.get("prices")
        if prices:
            if isinstance(prices, list):
                return [float(p) for p in prices if p is not None]
            elif isinstance(prices, dict):
                # Convert dict to list if needed
                yes_price = prices.get("YES") or prices.get("yes") or prices.get("0")
                no_price = prices.get("NO") or prices.get("no") or prices.get("1")
                if yes_price is not None and no_price is not None:
                    return [float(yes_price), float(no_price)]

        # Try outcome_prices format
        outcome_prices = data.get("outcome_prices")
        if outcome_prices and isinstance(outcome_prices, list):
            return [float(p) for p in outcome_prices if p is not None]

        # Try Polymarket format: single price for asset
        price = data.get("price") or data.get("last_price")
        if price is not None:
            try:
                return [float(price)]
            except (ValueError, TypeError):
                pass

        # Try best_bid/best_ask format (orderbook-based price)
        best_bid = data.get("best_bid") or data.get("bestBid")
        best_ask = data.get("best_ask") or data.get("bestAsk")
        if best_bid is not None and best_ask is not None:
            try:
                mid_price = (float(best_bid) + float(best_ask)) / 2.0
                return [mid_price]
            except (ValueError, TypeError):
                pass

        return None
