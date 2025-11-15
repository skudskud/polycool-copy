"""
Gamma API Poller Service
Fetches market data from Gamma API every POLL_MS and upserts to subsquid_markets_poll.
Implements exponential backoff for rate limiting.
Enhanced with health checks, metrics, and observability.
"""

import logging
import asyncio
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from time import time
import json
from dateutil import parser as date_parser

from ..config import settings, validate_experimental_subsquid, TABLES
from ..db.client import get_db_client
from ..utils.health_server import start_health_server, HealthServer
from ..utils.metrics import (
    poll_cycles_total,
    poll_markets_fetched_total,
    poll_errors_total,
    poll_last_cycle_duration_seconds,
    poll_markets_count,
    poll_consecutive_errors,
    poll_cycle_duration_seconds
)

logger = logging.getLogger(__name__)


class PollerService:
    """Gamma API polling service with health checks and metrics"""

    def __init__(self):
        self.enabled = settings.POLLER_ENABLED
        self.client: Optional[httpx.AsyncClient] = None
        self.last_etag: Optional[str] = None
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        self.backoff_seconds = 1.0
        self.max_backoff = settings.POLL_RATE_LIMIT_BACKOFF_MAX
        self.poll_count = 0
        self.market_count = 0
        self.upsert_count = 0
        self.last_poll_time = None

        # Health server for monitoring
        self.health_server: Optional[HealthServer] = None

    async def start(self):
        """Start the polling service with health monitoring"""
        if not self.enabled:
            logger.warning("⚠️ Poller service disabled (POLLER_ENABLED=false)")
            return

        validate_experimental_subsquid()
        logger.info("✅ Poller service starting...")

        # Initialize HTTP client
        self.client = httpx.AsyncClient(timeout=30.0)

        # Start health server if enabled
        if settings.HEALTH_SERVER_ENABLED:
            try:
                self.health_server = await start_health_server(
                    service_name="poller",
                    port=settings.HEALTH_SERVER_PORT_POLLER,
                    error_threshold=settings.HEALTH_CHECK_ERROR_THRESHOLD,
                    degraded_threshold_seconds=settings.HEALTH_CHECK_DEGRADED_THRESHOLD_SECONDS
                )
                logger.info(f"🏥 Health server started on port {settings.HEALTH_SERVER_PORT_POLLER}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to start health server: {e}")

        try:
            while True:
                await self.poll_cycle()
                await asyncio.sleep(settings.POLL_MS / 1000.0)
        except KeyboardInterrupt:
            logger.info("⏹️ Poller interrupted")
        except Exception as e:
            logger.error(f"❌ Poller fatal error: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the polling service and health server"""
        if self.client:
            await self.client.aclose()

        # Stop health server gracefully
        if self.health_server:
            await self.health_server.stop()

        logger.info("✅ Poller stopped")

    async def poll_cycle(self):
        """Single polling cycle"""
        try:
            start_time = time()
            self.poll_count += 1

            # Fetch markets from Gamma API with pagination
            total_markets = 0
            total_upserted = 0

            # ==========================================
            # PASS 1: Active markets (for price updates)
            # ==========================================
            offset = settings.POLL_OFFSET_START
            max_pages = 500  # Limit to 500 pages (50k markets)
            pages_fetched = 0

            logger.info(f"📊 [PASS 1] Fetching ACTIVE markets (limit={max_pages} pages)...")

            while pages_fetched < max_pages:
                markets = await self._fetch_markets(offset, active_only=True)
                if not markets:
                    break

                total_markets += len(markets)
                pages_fetched += 1

                # Upsert each page immediately (don't accumulate)
                if markets:
                    db = await get_db_client()
                    upserted = await db.upsert_markets_poll(markets)
                    total_upserted += upserted

                # Stop after fetching enough markets (pagination)
                if len(markets) < settings.POLL_LIMIT:
                    break

                offset += settings.POLL_LIMIT
                await asyncio.sleep(0.1)  # Small delay between pages

            logger.info(f"✅ [PASS 1] Fetched {total_markets} active markets, upserted {total_upserted}")

            # ==========================================
            # PASS 2: Recently closed markets (status updates)
            # This ensures expired markets get marked as CLOSED
            # ==========================================
            logger.info(f"📊 [PASS 2] Fetching CLOSED/EXPIRED markets (recent only, limit=500)...")

            offset = 0
            pages_fetched_closed = 0
            max_pages_closed = 50  # Only check first 50 pages of closed (5000 markets max)
            closed_upserted = 0

            while pages_fetched_closed < max_pages_closed:
                markets = await self._fetch_markets(offset, active_only=False)
                if not markets:
                    break

                pages_fetched_closed += 1

                # Filter to only recently updated closed markets (last 24 hours)
                now = datetime.now(timezone.utc)
                recently_updated = []
                for m in markets:
                    try:
                        updated_at_str = m.get("updatedAtMs") or m.get("updatedAt")
                        if updated_at_str:
                            updated_at = datetime.fromtimestamp(int(updated_at_str)/1000, tz=timezone.utc)
                            if (now - updated_at).days < 1:  # Last 24 hours
                                recently_updated.append(m)
                    except:
                        pass

                # Upsert recently updated closed markets
                if recently_updated:
                    db = await get_db_client()
                    upserted = await db.upsert_markets_poll(recently_updated)
                    closed_upserted += upserted

                # Stop early if we find fewer markets than expected (end of list)
                if len(markets) < settings.POLL_LIMIT:
                    break

                offset += settings.POLL_LIMIT
                await asyncio.sleep(0.1)  # Small delay between pages

            logger.info(f"✅ [PASS 2] Fetched closed markets, upserted {closed_upserted} recently updated")

            self.market_count = total_markets
            self.upsert_count = total_upserted + closed_upserted

            # Calculate metrics
            elapsed = time() - start_time

            logger.info(
                f"[POLLER] Cycle #{self.poll_count} - "
                f"PASS1: {total_markets} active markets, "
                f"PASS2: {closed_upserted} closed/expired markets, "
                f"Total upserted: {self.upsert_count}, "
                f"latency {elapsed*1000:.0f}ms"
            )

            # Reset error count on success
            self.consecutive_errors = 0
            self.backoff_seconds = 1.0
            self.last_poll_time = datetime.now(timezone.utc)

            # ✅ Update Prometheus metrics
            poll_cycles_total.inc()
            poll_markets_fetched_total.inc(total_markets)
            poll_cycle_duration_seconds.observe(elapsed)
            poll_last_cycle_duration_seconds.set(elapsed)
            poll_markets_count.set(total_markets)
            poll_consecutive_errors.set(0)

            # ✅ Update health server
            if self.health_server:
                self.health_server.update(
                    last_update=self.last_poll_time,
                    consecutive_errors=0,
                    total_cycles=self.poll_count,
                    custom_metrics={
                        "markets_fetched": total_markets,
                        "markets_upserted": self.upsert_count,
                        "cycle_duration_seconds": round(elapsed, 2)
                    }
                )

        except Exception as e:
            self.consecutive_errors += 1
            error_type = e.__class__.__name__
            logger.error(f"❌ Poll cycle #{self.poll_count} failed: {e}")

            # ⚠️ Update error metrics
            poll_errors_total.labels(error_type=error_type).inc()
            poll_consecutive_errors.set(self.consecutive_errors)

            # ⚠️ Update health server with error state
            if self.health_server:
                self.health_server.update(
                    consecutive_errors=self.consecutive_errors,
                    total_cycles=self.poll_count,
                    custom_metrics={"last_error": error_type}
                )

            if self.consecutive_errors >= self.max_consecutive_errors:
                logger.error(f"❌ Max consecutive errors ({self.max_consecutive_errors}) reached")
                raise

            # Exponential backoff
            await asyncio.sleep(min(self.backoff_seconds, self.max_backoff))
            self.backoff_seconds *= 2.0

    async def _fetch_markets(self, offset: int, active_only: bool = True) -> List[Dict[str, Any]]:
        """Fetch markets from Gamma API with pagination and ETag caching

        Args:
            offset: Pagination offset
            active_only: If True, fetch only active markets. If False, fetch all markets (including closed)
        """
        if not self.client:
            return []

        # Build URL based on active_only parameter
        # PASS 1: active=true → Get active markets for price updates
        # PASS 2: active=false → Get closed/expired markets to update their status
        if active_only:
            url = f"{settings.GAMMA_API_URL}?limit={settings.POLL_LIMIT}&offset={offset}&active=true&order=id&ascending=false"
        else:
            url = f"{settings.GAMMA_API_URL}?limit={settings.POLL_LIMIT}&offset={offset}&active=false&order=id&ascending=false"

        headers = {}
        if self.last_etag:
            headers["If-None-Match"] = self.last_etag

        try:
            response = await self.client.get(url, headers=headers)

            # 304 Not Modified
            if response.status_code == 304:
                logger.debug(f"📭 No new markets (304 Not Modified)")
                return []

            # Rate limit (429)
            if response.status_code == 429:
                logger.warning(f"⚠️ Rate limited by Gamma API (429)")
                self.backoff_seconds = min(self.backoff_seconds * 2, self.max_backoff)
                return []

            # Success
            if response.status_code == 200:
                # Update ETag for next request
                if "etag" in response.headers:
                    self.last_etag = response.headers["etag"]

                data = response.json()
                markets = self._parse_markets(data)
                logger.debug(f"✅ Fetched {len(markets)} markets from Gamma API (offset={offset})")
                return markets

            # Other errors
            logger.error(f"❌ Gamma API error {response.status_code}: {response.text[:100]}")
            return []

        except Exception as e:
            logger.error(f"❌ Fetch error: {e}")
            return []

    @staticmethod
    def _parse_markets(data: Any) -> List[Dict[str, Any]]:
        """Parse Gamma API response into enriched market dicts with all necessary fields"""
        import json
        markets = []

        # Handle both list and dict responses
        market_list = data if isinstance(data, list) else data.get("data", [])

        for market in market_list:
            try:
                # Parse outcomes and prices
                outcomes = []
                outcome_prices = []
                try:
                    outcomes_list = market.get("outcomes", "[]")
                    if isinstance(outcomes_list, str):
                        outcomes_list = json.loads(outcomes_list)
                    prices_list = market.get("outcomePrices", "[]")
                    if isinstance(prices_list, str):
                        prices_list = json.loads(prices_list)

                    for i, outcome_name in enumerate(outcomes_list):
                        price = float(prices_list[i]) if i < len(prices_list) else 0.0
                        outcomes.append(outcome_name)
                        outcome_prices.append(round(price, 4))
                except (json.JSONDecodeError, ValueError, IndexError) as e:
                    logger.debug(f"⚠️ Error parsing outcomes: {e}")

                # ✅ FIX: Valider les outcome_prices (détecter les placeholders [0,1] ou [1,0])
                is_valid_outcome_prices = PollerService._validate_outcome_prices(outcome_prices)

                # Calculate mid price from outcome prices
                last_mid = None
                if is_valid_outcome_prices and outcome_prices and len(outcome_prices) >= 2:
                    last_mid = round(sum(outcome_prices) / len(outcome_prices), 4)

                # Parse events
                events = []
                try:
                    events_list = market.get("events", [])
                    if isinstance(events_list, list):
                        for event in events_list:
                            events.append({
                                "event_id": event.get("id"),
                                "event_slug": event.get("slug"),
                                "event_title": event.get("title"),
                                "event_category": event.get("category"),
                                "event_volume": round(float(event.get("volume", 0)), 4) if event.get("volume") else 0.0,
                            })
                except Exception as e:
                    logger.debug(f"⚠️ Error parsing events: {e}")

                # Parse dates safely
                created_at = None
                end_date = None
                resolution_date = None
                try:
                    if market.get("createdAt"):
                        created_at = date_parser.parse(market.get("createdAt"))
                    if market.get("endDate"):
                        end_date = date_parser.parse(market.get("endDate"))
                    if market.get("closedTime"):
                        resolution_date = date_parser.parse(market.get("closedTime"))
                except Exception as e:
                    logger.debug(f"⚠️ Error parsing dates: {e}")

                # ✅ FIX: Logique de statut robuste basée sur dates et champs actif
                # Determine market status based on multiple factors
                is_active = market.get("active", False)
                is_closed = market.get("closed", False)
                now = datetime.now(timezone.utc)

                # Status logic - STRICT ordering:
                # 1. If end_date has PASSED (now > end_date) → CLOSED
                # 2. If closed flag is TRUE → CLOSED
                # 3. Otherwise → ACTIVE
                if end_date and end_date < now:
                    # Date passed = market definitely closed
                    status = "CLOSED"
                    accepting_orders = False
                    tradeable = False
                    logger.debug(f"✅ Market {market.get('id')} CLOSED: end_date passed ({end_date})")
                elif is_closed:
                    # API says closed
                    status = "CLOSED"
                    accepting_orders = False
                    tradeable = False
                    logger.debug(f"✅ Market {market.get('id')} CLOSED: closed flag true")
                else:
                    # Otherwise ACTIVE
                    status = "ACTIVE"
                    accepting_orders = is_active
                    tradeable = is_active and (not end_date or end_date > now)
                    logger.debug(f"✅ Market {market.get('id')} ACTIVE: end_date={end_date}, active={is_active}")

                # Extract all relevant market data
                parsed = {
                    # Identifiers
                    "market_id": market.get("id", market.get("conditionId", "")),
                    "condition_id": market.get("conditionId", ""),
                    "slug": market.get("slug", ""),

                    # Market info
                    "title": market.get("question", ""),
                    "description": market.get("description", ""),
                    "category": market.get("category", ""),

                    # Status
                    "status": status,
                    "accepting_orders": accepting_orders,
                    "archived": market.get("archived", False),

                    # Outcomes & prices
                    "outcomes": outcomes,
                    "outcome_prices": outcome_prices if is_valid_outcome_prices else [],
                    "last_mid": last_mid,

                    # Volumes
                    "volume": round(float(market.get("volume", 0)), 4) if market.get("volume") else 0.0,
                    "volume_24hr": round(float(market.get("volume24hr", 0)), 4) if market.get("volume24hr") else 0.0,
                    "volume_1wk": round(float(market.get("volume1wk", 0)), 4) if market.get("volume1wk") else 0.0,
                    "volume_1mo": round(float(market.get("volume1mo", 0)), 4) if market.get("volume1mo") else 0.0,

                    # Liquidity & trading
                    "liquidity": round(float(market.get("liquidity", 0)), 4) if market.get("liquidity") else 0.0,
                    "spread": market.get("spread", 0),
                    "tradeable": tradeable,

                    # Dates
                    "created_at": created_at,
                    "updated_at": date_parser.parse(market.get("updatedAt")) if market.get("updatedAt") else None,
                    "end_date": end_date,
                    "resolution_date": resolution_date,

                    # Price changes
                    "price_change_1h": round(float(market.get("oneHourPriceChange", 0)), 4),
                    "price_change_1d": round(float(market.get("oneDayPriceChange", 0)), 4),
                    "price_change_1w": round(float(market.get("oneWeekPriceChange", 0)), 4),

                    # CLOB tokens
                    "clob_token_ids": market.get("clobTokenIds", "[]"),

                    # Events (important pour display)
                    "events": events,

                    # Metadata
                    "market_type": market.get("marketType", "normal"),
                    "restricted": market.get("restricted", False),
                }

                # Only add if market_id exists
                if parsed["market_id"]:
                    markets.append(parsed)

            except Exception as e:
                logger.error(f"❌ Failed to parse market: {e}", exc_info=True)
                continue

        return markets

    @staticmethod
    def _validate_outcome_prices(outcome_prices: List[float]) -> bool:
        """
        ✅ Valide que les outcome_prices sont réalistes et non des placeholders.

        Les placeholders [0, 1] ou [1, 0] indiquent que l'API n'a pas encore
        calculé les vrais prix probabilistes.

        Retourne True si les prix sont valides, False sinon.
        """
        if not outcome_prices or len(outcome_prices) < 2:
            return False

        # ❌ Détecter les placeholders typiques
        placeholder_patterns = [
            [0, 1],
            [1, 0],
            [0.0, 1.0],
            [1.0, 0.0],
        ]

        normalized_prices = [round(p, 1) for p in outcome_prices]
        if normalized_prices in placeholder_patterns:
            return False

        # ✅ Valider que la somme des probabilités ≈ 1.0 (tolérance: ±0.01)
        price_sum = round(sum(outcome_prices), 4)
        if abs(price_sum - 1.0) > 0.01:
            # Somme invalide (devrait être proche de 1.0)
            return False

        # ✅ Valider que chaque prix est dans [0, 1]
        for price in outcome_prices:
            if price < 0.0 or price > 1.0:
                return False

        return True


# Global poller instance
_poller_instance: Optional[PollerService] = None


async def get_poller() -> PollerService:
    """Get or create global poller instance"""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = PollerService()
    return _poller_instance


# Entry point for running poller as standalone service
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        format=settings.LOG_FORMAT,
        level=settings.LOG_LEVEL
    )

    async def main():
        poller = await get_poller()
        await poller.start()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Poller stopped")
        sys.exit(0)
