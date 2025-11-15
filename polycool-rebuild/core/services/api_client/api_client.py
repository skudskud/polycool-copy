"""
API Client Service
HTTP client for bot-to-API communication when SKIP_DB=true
Integrates with CacheManager for Redis caching
Includes retry logic, rate limiting, and circuit breaker
"""
import json
import asyncio
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from collections import deque
import httpx
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger
from core.services.cache_manager import CacheManager

logger = get_logger(__name__)


class APIClient:
    """
    API Client for bot-to-API communication
    - Handles HTTP requests to API service
    - Integrates with Redis cache
    - Provides user, wallet, and positions data
    - Includes retry logic, rate limiting, and circuit breaker
    """

    def __init__(self):
        """Initialize API client"""
        self.api_url = settings.api_url.rstrip('/')
        self.api_prefix = settings.api_prefix
        self.base_url = f"{self.api_url}{self.api_prefix}"
        self.cache_manager = CacheManager()
        self.client = httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True
        )

        # Rate limiting: track request timestamps (max 100 requests per minute)
        self.rate_limit_window = timedelta(minutes=1)
        self.rate_limit_max = 100
        self.request_timestamps: deque = deque()

        # Search-specific rate limiting (max 30 search requests per minute)
        self.search_rate_limit_max = 30
        self.search_timestamps: deque = deque()

        # Circuit breaker: track API health
        self.circuit_state = "closed"  # closed, open, half_open
        self.circuit_failures = 0
        self.circuit_success_threshold = 5
        self.circuit_failure_threshold = 10
        self.circuit_open_until: Optional[datetime] = None
        self.circuit_timeout = timedelta(seconds=30)

        # Retry configuration
        self.max_retries = 3
        self.retry_backoff_base = 1.0  # seconds

    def _check_rate_limit(self) -> bool:
        """Check if rate limit is exceeded"""
        now = datetime.utcnow()
        # Remove old requests outside window
        while self.request_timestamps and now - self.request_timestamps[0] > self.rate_limit_window:
            self.request_timestamps.popleft()

        # Check if limit exceeded
        if len(self.request_timestamps) >= self.rate_limit_max:
            logger.warning(f"⚠️ Rate limit exceeded: {len(self.request_timestamps)} requests in window")
            return False

        # Add current request
        self.request_timestamps.append(now)
        return True

    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows request"""
        now = datetime.utcnow()

        if self.circuit_state == "open":
            if self.circuit_open_until and now < self.circuit_open_until:
                logger.debug(f"🔴 Circuit breaker OPEN - blocking request")
                return False
            else:
                # Timeout expired, try half-open
                logger.info("🟡 Circuit breaker transitioning to HALF_OPEN")
                self.circuit_state = "half_open"
                self.circuit_failures = 0
                return True

        return True

    def _record_success(self):
        """Record successful API call"""
        if self.circuit_state == "half_open":
            self.circuit_success_count = getattr(self, 'circuit_success_count', 0) + 1
            if self.circuit_success_count >= self.circuit_success_threshold:
                logger.info("🟢 Circuit breaker CLOSED - API healthy")
                self.circuit_state = "closed"
                self.circuit_failures = 0
                self.circuit_success_count = 0
        else:
            self.circuit_failures = max(0, self.circuit_failures - 1)

    def _record_failure(self):
        """Record failed API call"""
        self.circuit_failures += 1

        if self.circuit_state == "half_open":
            # Failed in half-open, reopen circuit
            logger.warning("🔴 Circuit breaker reopening after half-open failure")
            self.circuit_state = "open"
            self.circuit_open_until = datetime.utcnow() + self.circuit_timeout
        elif self.circuit_failures >= self.circuit_failure_threshold:
            # Too many failures, open circuit
            logger.error(f"🔴 Circuit breaker OPENED after {self.circuit_failures} failures")
            self.circuit_state = "open"
            self.circuit_open_until = datetime.utcnow() + self.circuit_timeout

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        retry_on: List[int] = None
    ) -> Optional[httpx.Response]:
        """
        Make HTTP request with retry logic

        Args:
            method: HTTP method ('GET', 'POST', or 'PUT')
            endpoint: API endpoint path
            json_data: JSON payload for POST/PUT requests
            retry_on: List of status codes to retry on (default: 5xx, timeout)

        Returns:
            Response object or None on error
        """
        if retry_on is None:
            retry_on = [500, 502, 503, 504]  # Retry on server errors

        url = f"{self.base_url}{endpoint}"

        for attempt in range(self.max_retries + 1):
            try:
                # Check rate limit
                if not self._check_rate_limit():
                    logger.warning(f"⚠️ Rate limit exceeded, skipping request to {endpoint}")
                    return None

                # Check circuit breaker
                if not self._check_circuit_breaker():
                    logger.warning(f"🔴 Circuit breaker OPEN, skipping request to {endpoint}")
                    return None

                # Make request
                if method == "GET":
                    response = await self.client.get(url)
                elif method == "POST":
                    response = await self.client.post(url, json=json_data)
                elif method == "PUT":
                    response = await self.client.put(url, json=json_data)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                # Check if we should retry
                if response.status_code in retry_on and attempt < self.max_retries:
                    backoff_time = self.retry_backoff_base * (2 ** attempt)
                    logger.warning(f"⚠️ API error {response.status_code}, retrying in {backoff_time}s (attempt {attempt + 1}/{self.max_retries + 1})")
                    await asyncio.sleep(backoff_time)
                    continue

                # Success or non-retryable error
                if response.status_code < 500:
                    self._record_success()
                else:
                    self._record_failure()

                return response

            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
                if attempt < self.max_retries:
                    backoff_time = self.retry_backoff_base * (2 ** attempt)
                    logger.warning(f"⚠️ Network error: {e}, retrying in {backoff_time}s (attempt {attempt + 1}/{self.max_retries + 1})")
                    await asyncio.sleep(backoff_time)
                    continue
                else:
                    logger.error(f"❌ Network error after {self.max_retries + 1} attempts: {e}")
                    self._record_failure()
                    return None
            except Exception as e:
                logger.error(f"❌ Unexpected error in request: {e}")
                self._record_failure()
                return None

        return None

    async def _get(
        self,
        endpoint: str,
        cache_key: Optional[str] = None,
        data_type: str = 'user_profile',
        use_cache: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Internal GET method with caching, retry logic, and circuit breaker

        Args:
            endpoint: API endpoint path (e.g., "/users/123")
            cache_key: Redis cache key (optional, auto-generated if None)
            data_type: Cache data type for TTL strategy
            use_cache: Whether to use cache (default: True)

        Returns:
            Response JSON dict or None on error
        """
        if cache_key is None:
            cache_key = f"api:{endpoint.replace('/', ':')}"

        # Try cache first (if enabled)
        if use_cache:
            cached_data = await self.cache_manager.get(cache_key, data_type)
            if cached_data is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_data
        else:
            logger.debug(f"Cache bypassed for {cache_key} (use_cache=False)")

        # Cache miss or bypassed - call API with retry logic
        response = await self._request_with_retry("GET", endpoint)

        if response is None:
            logger.error(f"API request failed for {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()
            # Cache successful response (if caching enabled)
            if use_cache:
                await self.cache_manager.set(cache_key, data, data_type)
            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Generic 404 message (not just for users)
                logger.warning(f"⚠️ API 404 for {endpoint} - Resource not found")
                # Invalidate cache to prevent stale data
                await self.cache_manager.delete(cache_key)
                return None
            logger.error(f"API error {e.response.status_code} for {endpoint}: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for {endpoint}: {e}")
            return None

    async def _post(self, endpoint: str, json_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Internal POST method with retry logic and circuit breaker

        Args:
            endpoint: API endpoint path
            json_data: JSON payload

        Returns:
            Response JSON dict or None on error
        """
        response = await self._request_with_retry("POST", endpoint, json_data)

        if response is None:
            logger.error(f"API POST failed for {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()

            # Invalidate related cache entries
            if 'user' in endpoint or 'users' in endpoint:
                await self.cache_manager.invalidate_pattern("api:users:*")
                await self.cache_manager.invalidate_pattern("api:user:*")

            return data

        except httpx.HTTPStatusError as e:
            # Log detailed error information for debugging
            status_code = e.response.status_code
            error_detail = str(e)

            # Try to extract error message from response body
            try:
                error_body = e.response.json()
                error_message = error_body.get('detail', error_body.get('message', str(e)))
                logger.error(f"API error {status_code} for POST {endpoint}: {error_message}")
            except:
                logger.error(f"API error {status_code} for POST {endpoint}: {error_detail}")

            if status_code == 405:
                logger.error(f"API error 405 (Method Not Allowed) for POST {endpoint}. This usually indicates:")
                logger.error(f"  1. Wrong HTTP method (POST vs GET)")
                logger.error(f"  2. Trailing slash mismatch (/{endpoint} vs /{endpoint}/)")
                logger.error(f"  3. Route not properly configured in FastAPI")
                logger.error(f"  4. Redirect changed POST to GET (check redirects)")
            elif status_code in [301, 302, 307, 308]:
                logger.error(f"API redirect {status_code} for POST {endpoint}. Check if trailing slash is correct.")
            elif status_code == 400:
                # For 400 errors, return the error detail so caller can see the message
                try:
                    error_body = e.response.json()
                    return {"success": False, "message": error_body.get('detail', 'Bad request'), "detail": error_body.get('detail', '')}
                except:
                    pass
            elif status_code == 404:
                # For 404 errors, return error info
                try:
                    error_body = e.response.json()
                    return {"success": False, "message": error_body.get('detail', 'Not found'), "detail": error_body.get('detail', '')}
                except:
                    pass

            return None
        except Exception as e:
            logger.error(f"API request error for {endpoint}: {e}")
            return None

    async def _put(
        self,
        endpoint: str,
        json_data: Dict[str, Any],
        cache_key: Optional[str] = None,
        data_type: str = 'markets',
        use_cache: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Internal PUT method with retry logic and circuit breaker

        Args:
            endpoint: API endpoint path
            json_data: JSON payload
            cache_key: Optional cache key for invalidation
            data_type: Cache data type
            use_cache: Whether to use cache (default: False for updates)

        Returns:
            Response JSON dict or None on error
        """
        response = await self._request_with_retry("PUT", endpoint, json_data)

        if response is None:
            logger.error(f"API PUT failed for {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()

            # Invalidate related cache entries
            if cache_key:
                await self.cache_manager.delete(cache_key)
            if 'market' in endpoint or 'markets' in endpoint:
                await self.cache_manager.invalidate_pattern("api:markets:*")
                await self.cache_manager.invalidate_pattern("api:market:*")

            return data

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            try:
                error_body = e.response.json()
                error_message = error_body.get('detail', error_body.get('message', str(e)))
                logger.error(f"API error {status_code} for PUT {endpoint}: {error_message}")
            except:
                logger.error(f"API error {status_code} for PUT {endpoint}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"API request error for PUT {endpoint}: {e}")
            return None

    async def get_user(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get user by Telegram ID

        Args:
            telegram_user_id: Telegram user ID

        Returns:
            User dict or None if not found
        """
        cache_key = f"api:user:{telegram_user_id}"
        logger.info(f"🔍 Fetching user {telegram_user_id} from API: {self.base_url}/users/{telegram_user_id}")
        result = await self._get(f"/users/{telegram_user_id}", cache_key, 'user_profile')
        if result is None:
            logger.warning(f"⚠️ User {telegram_user_id} not found via API. This may indicate:")
            logger.warning(f"   1. User doesn't exist in API database")
            logger.warning(f"   2. API database connection issue")
            logger.warning(f"   3. User was created in different database")
        return result

    async def create_user(
        self,
        telegram_user_id: int,
        username: Optional[str] = None,
        polygon_address: str = None,
        polygon_private_key: str = None,
        solana_address: str = None,
        solana_private_key: str = None,
        stage: str = "onboarding"
    ) -> Optional[Dict[str, Any]]:
        """
        Create user via API

        Args:
            telegram_user_id: Telegram user ID
            username: Telegram username
            polygon_address: Polygon wallet address
            polygon_private_key: Encrypted Polygon private key
            solana_address: Solana wallet address
            solana_private_key: Encrypted Solana private key
            stage: User stage (default: "onboarding")

        Returns:
            Created user dict or None on error
        """
        payload = {
            "telegram_user_id": telegram_user_id,
            "username": username,
            "polygon_address": polygon_address,
            "polygon_private_key": polygon_private_key,
            "solana_address": solana_address,
            "solana_private_key": solana_private_key,
            "stage": stage
        }
        return await self._post("/users/", payload)

    async def get_wallet_balance(self, user_id: int, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get wallet balance for user

        Args:
            user_id: Internal user ID (not Telegram ID)
            use_cache: Whether to use cache (default: True, set False to force fresh fetch)

        Returns:
            Balance dict with usdc_balance, pol_balance, etc. or None
        """
        cache_key = f"api:wallet:{user_id}"
        if not use_cache:
            # Invalidate cache first to force fresh fetch
            await self.cache_manager.delete(cache_key)
            logger.info(f"🗑️ Cache invalidated for wallet balance: {cache_key}")
        # Use shorter TTL for balance when forcing fresh fetch (20s instead of 1h)
        data_type = 'prices' if not use_cache else 'user_profile'
        return await self._get(f"/wallet/balance/{user_id}", cache_key, data_type, use_cache=use_cache)

    async def get_user_positions(self, user_id: int, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get user positions

        Args:
            user_id: Internal user ID (not Telegram ID)
            use_cache: Whether to use cache (default: True, set False to force fresh fetch)

        Returns:
            Positions dict with positions list or None
        """
        cache_key = f"api:positions:{user_id}"
        if not use_cache:
            # Invalidate cache first to force fresh fetch
            await self.cache_manager.delete(cache_key)
            logger.info(f"🗑️ Cache invalidated for positions: {cache_key}")
        return await self._get(f"/positions/user/{user_id}", cache_key, 'positions', use_cache=use_cache)

    async def get_position(self, position_id: int, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get specific position by ID

        Args:
            position_id: Position ID
            use_cache: Whether to use cache (default: True)

        Returns:
            Position dict or None if not found
        """
        cache_key = f"api:position:{position_id}"
        return await self._get(f"/positions/{position_id}", cache_key, 'positions', use_cache)

    async def get_market_positions(self, market_id: str, use_cache: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get all active positions for a specific market

        Args:
            market_id: Market ID
            use_cache: Whether to use cache (default: False for real-time checks)

        Returns:
            Positions dict with positions list or None
        """
        cache_key = f"api:positions:market:{market_id}"
        if not use_cache:
            # Invalidate cache first to force fresh fetch
            await self.cache_manager.delete(cache_key)
        return await self._get(f"/positions/market/{market_id}", cache_key, 'positions', use_cache=use_cache)

    async def get_resolved_positions(self, user_id: int, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get resolved (redeemable) positions for a user

        Args:
            user_id: Internal user ID (not Telegram ID)
            use_cache: Whether to use cache (default: True)

        Returns:
            Dict with resolved_positions list or None
        """
        cache_key = f"api:resolved_positions:{user_id}"
        if not use_cache:
            await self.cache_manager.delete(cache_key)
        return await self._get(f"/positions/resolved/{user_id}", cache_key, 'positions', use_cache=use_cache)

    async def get_resolved_position(self, user_id: int, resolved_position_id: int, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get a specific resolved position

        Args:
            user_id: Internal user ID (not Telegram ID)
            resolved_position_id: Resolved position ID
            use_cache: Whether to use cache (default: True)

        Returns:
            Resolved position dict or None
        """
        cache_key = f"api:resolved_position:{resolved_position_id}"
        return await self._get(f"/positions/resolved/{user_id}/{resolved_position_id}", cache_key, 'positions', use_cache)

    async def detect_redeemable_positions(
        self,
        user_id: int,
        positions_data: List[Dict[str, Any]],
        wallet_address: str
    ) -> Optional[Dict[str, Any]]:
        """
        Detect and create redeemable positions via API

        Args:
            user_id: Internal user ID (not Telegram ID)
            positions_data: List of position dicts from blockchain
            wallet_address: User's wallet address

        Returns:
            Dict with redeemable_positions and resolved_condition_ids or None
        """
        payload = {
            "positions_data": positions_data,
            "wallet_address": wallet_address
        }
        return await self._post(f"/positions/resolved/{user_id}/detect", payload)

    async def redeem_resolved_position(
        self,
        user_id: int,
        resolved_position_id: int,
        private_key: str
    ) -> Optional[Dict[str, Any]]:
        """
        Execute redemption for a resolved position via API

        Args:
            user_id: Internal user ID (not Telegram ID)
            resolved_position_id: Resolved position ID
            private_key: User's decrypted private key

        Returns:
            Redemption result dict or None
        """
        payload = {
            "private_key": private_key
        }
        return await self._post(f"/positions/resolved/{user_id}/{resolved_position_id}/redeem", payload)

    async def get_closed_positions_from_polymarket(self, wallet_address: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get closed positions from Polymarket API endpoint /closed-positions

        Args:
            wallet_address: User's Polygon wallet address

        Returns:
            List of closed position dicts or None on error
        """
        try:
            import httpx
            from infrastructure.config.settings import settings

            # Use Polymarket data API endpoint
            base_url = "https://data-api.polymarket.com"
            url = f"{base_url}/closed-positions"
            params = {
                "user": wallet_address,
                "limit": 100,  # Max 100 positions per request
                "sortBy": "REALIZEDPNL",
                "sortDirection": "DESC"
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                # Handle both array and object with 'positions' key
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'positions' in data:
                    return data['positions']
                else:
                    logger.warning(f"⚠️ Unexpected response format from /closed-positions: {type(data)}")
                    return []

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP error fetching closed positions for {wallet_address[:10]}...: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching closed positions for {wallet_address[:10]}...: {e}")
            return None

    async def create_position(
        self,
        user_id: int,
        market_id: str,
        outcome: str,
        amount: float,
        entry_price: float,
        is_copy_trade: bool = False,
        total_cost: Optional[float] = None,
        position_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new position via API

        Args:
            user_id: Internal user ID (not Telegram ID)
            market_id: Market ID
            outcome: Outcome ("YES" or "NO")
            amount: Position size (number of tokens/shares)
            entry_price: Entry price
            is_copy_trade: True if position created via copy trading
            total_cost: Number of shares (for BUY) or sold (for SELL). If None, uses amount. Note: Despite the name 'total_cost', this stores SHARES, not USD cost.

        Returns:
            Created position dict or None on error
        """
        json_data = {
            "user_id": user_id,
            "market_id": market_id,
            "outcome": outcome,
            "amount": amount,
            "entry_price": entry_price,
            "is_copy_trade": is_copy_trade
        }
        if total_cost is not None:
            json_data["total_cost"] = total_cost
        if position_id is not None:
            json_data["position_id"] = position_id

        # Call API first (don't invalidate before - prevents race condition)
        result = await self._post("/positions/", json_data)

        # ✅ CRITICAL: Invalidate cache AFTER successful API call (prevents race condition)
        # The API service also invalidates, but we do it here too for redundancy
        if result:
            await self.cache_manager.invalidate_pattern(f"api:positions:{user_id}")
            logger.debug(f"✅ Cache invalidated for user {user_id} after position creation (client-side)")

        return result

    async def update_position_tpsl(
        self,
        position_id: int,
        tpsl_type: str,
        price: float
    ) -> Optional[Dict[str, Any]]:
        """
        Update TP/SL for a position via API

        Args:
            position_id: Position ID
            tpsl_type: "tp" or "sl"
            price: Target price (0-1)

        Returns:
            Updated position dict or None on error
        """
        json_data = {
            "tpsl_type": tpsl_type,
            "price": price
        }

        # Invalidate positions cache
        endpoint = f"/positions/{position_id}/tpsl"
        response = await self._request_with_retry("PUT", endpoint, json_data)

        if response is None:
            logger.error(f"API PUT failed for update TP/SL: {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()

            # Invalidate positions cache for this user only (targeted invalidation)
            # Extract user_id from the response to avoid invalidating all users' cache
            user_id = data.get('user_id')
            if user_id:
                await self.cache_manager.invalidate_pattern(f"api:positions:{user_id}")
                logger.debug(f"✅ Cache invalidated for user {user_id} after TP/SL update")
            else:
                # Fallback: if user_id not in response, invalidate all (shouldn't happen)
                logger.warning("⚠️ user_id not found in TP/SL update response, invalidating all positions cache")
                await self.cache_manager.invalidate_pattern("api:positions:*")

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"API error {e.response.status_code} for update TP/SL: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for update TP/SL: {e}")
            return None

    async def update_position(
        self,
        position_id: int,
        amount: Optional[float] = None,
        current_price: Optional[float] = None,
        status: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update position amount, price, or status via API

        Args:
            position_id: Position ID
            amount: New amount (optional)
            current_price: New current price (optional)
            status: New status (optional)

        Returns:
            Updated position dict or None on error
        """
        json_data = {}
        if amount is not None:
            json_data['amount'] = amount
        if current_price is not None:
            json_data['current_price'] = current_price
        if status is not None:
            json_data['status'] = status

        endpoint = f"/positions/{position_id}"
        response = await self._request_with_retry("PUT", endpoint, json_data)

        if response is None:
            logger.error(f"API PUT failed for update position: {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()

            # Invalidate positions cache for this user only (targeted invalidation)
            # Extract user_id from the response to avoid invalidating all users' cache
            user_id = data.get('user_id')
            if user_id:
                await self.cache_manager.invalidate_pattern(f"api:positions:{user_id}")
                logger.debug(f"✅ Cache invalidated for user {user_id} after position update")
            else:
                # Fallback: if user_id not in response, invalidate all (shouldn't happen)
                logger.warning("⚠️ user_id not found in position update response, invalidating all positions cache")
                await self.cache_manager.invalidate_pattern("api:positions:*")

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"API error {e.response.status_code} for update position: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for update position: {e}")
            return None

    async def sync_positions(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Sync user positions from blockchain via API (with retry logic)

        Args:
            user_id: Internal user ID (not Telegram ID)

        Returns:
            Sync result dict or None on error
        """
        endpoint = f"/positions/sync/{user_id}"
        response = await self._request_with_retry("POST", endpoint)

        if response is None:
            logger.error(f"API POST failed for sync positions: {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()

            # Invalidate positions cache for this user
            await self.cache_manager.invalidate_pattern(f"api:positions:{user_id}")

            logger.debug(f"Positions synced successfully for user {user_id}")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"API error {e.response.status_code} for sync positions: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for sync positions: {e}")
            return None

    async def get_trending_markets(
        self,
        page: int = 0,
        page_size: int = 10,
        group_by_events: bool = True,
        filter_type: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get trending markets via API

        Args:
            page: Page number (0-based)
            page_size: Number of markets per page
            group_by_events: Whether to group markets by events
            filter_type: Filter by outcome type

        Returns:
            List of trending markets or None on error
        """
        # Include params in URL for proper API call
        endpoint = f"/markets/trending?page={page}&page_size={page_size}&group_by_events={str(group_by_events).lower()}"
        if filter_type:
            endpoint += f"&filter_type={filter_type}"

        cache_key = f"api:markets:trending:{page}:{page_size}:{group_by_events}:{filter_type or 'none'}"
        response_data = await self._get(endpoint, cache_key, 'markets')

        # Handle new response format with wrapper
        if response_data and isinstance(response_data, dict) and 'markets' in response_data:
            # New format: {markets: [...], total_count: ...}
            markets = response_data.get('markets', [])
            # Store total_count in cache metadata for pagination (same for all pages)
            total_count = response_data.get('total_count')
            if total_count is not None and self.cache_manager:
                # Store total_count with a key that's the same for all pages
                total_count_key = f"api:markets:trending:total_count:{group_by_events}:{filter_type or 'none'}"
                await self.cache_manager.set(
                    total_count_key,
                    total_count,
                    'metadata',
                    ttl=300
                )
            return markets
        elif isinstance(response_data, list):
            # Old format: just a list (backward compatibility)
            return response_data
        else:
            return None

    async def get_category_markets(
        self,
        category: str,
        page: int = 0,
        page_size: int = 10,
        filter_type: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get markets by category via API

        Args:
            category: Market category (capitalized, e.g., "Geopolitics")
            page: Page number (0-based)
            page_size: Number of markets per page
            filter_type: Filter by outcome type

        Returns:
            List of markets in category or None on error
        """
        # Include params in URL for proper API call
        endpoint = f"/markets/categories/{category}?page={page}&page_size={page_size}"
        if filter_type:
            endpoint += f"&filter_type={filter_type}"

        cache_key = f"api:markets:category:{category.lower()}:{page}:{page_size}:{filter_type or 'none'}"
        return await self._get(endpoint, cache_key, 'markets')

    async def search_markets(
        self,
        query: str,
        page: int = 0,
        page_size: int = 10,
        group_by_events: bool = True,
        filter_type: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Search markets via API

        Args:
            query: Search query (all terms must be in title)
            page: Page number (0-based)
            page_size: Number of markets per page
            group_by_events: Whether to group markets by events
            filter_type: Filter by outcome type (not supported in search yet)

        Returns:
            List of matching markets or None on error
        """
        # Check search-specific rate limit
        now = datetime.utcnow()
        # Remove old search requests outside window
        while self.search_timestamps and now - self.search_timestamps[0] > self.rate_limit_window:
            self.search_timestamps.popleft()

        # Check if search rate limit exceeded
        if len(self.search_timestamps) >= self.search_rate_limit_max:
            logger.warning(f"⚠️ Search rate limit exceeded: {len(self.search_timestamps)} search requests in window")
            return None  # Return None instead of empty list to indicate rate limit

        # Add current search request
        self.search_timestamps.append(now)

        # Include params in URL for proper API call
        from urllib.parse import quote
        endpoint = f"/markets/search?query_text={quote(query)}&page={page}&page_size={page_size}&group_by_events={str(group_by_events).lower()}"
        if filter_type:
            endpoint += f"&filter_type={filter_type}"

        # URL encode query for cache key
        query_safe = query.replace('/', '_').replace(':', '_')
        cache_key = f"api:markets:search:{query_safe}:{page}:{page_size}:{group_by_events}:{filter_type or 'none'}"
        response_data = await self._get(endpoint, cache_key, 'markets')

        # Handle new response format with wrapper
        if response_data and isinstance(response_data, dict) and 'markets' in response_data:
            # New format: {markets: [...], total_count: ...}
            markets = response_data.get('markets', [])
            # Store total_count in cache metadata for pagination (same for all pages)
            total_count = response_data.get('total_count')
            if total_count is not None and self.cache_manager:
                # Store total_count with a key that's the same for all pages
                total_count_key = f"api:markets:search:total_count:{query_safe}:{group_by_events}"
                await self.cache_manager.set(
                    total_count_key,
                    total_count,
                    'metadata',
                    ttl=300
                )
            return markets
        elif isinstance(response_data, list):
            # Old format: just a list (backward compatibility)
            return response_data
        else:
            return None

    async def get_event_markets(self, event_id: str, page: int = 0, page_size: int = 12) -> Optional[Dict[str, Any]]:
        """
        Get markets for a specific event via API

        Args:
            event_id: Event identifier
            page: Page number (0-based)
            page_size: Number of markets per page

        Returns:
            Dict with markets list and pagination info, or None on error
        """
        # Include params in URL for proper API call
        endpoint = f"/markets/events/{event_id}?page={page}&page_size={page_size}"
        cache_key = f"api:markets:event:{event_id}:{page}:{page_size}"
        return await self._get(endpoint, cache_key, 'markets')

    async def update_market(
        self,
        market_id: str,
        is_resolved: Optional[bool] = None,
        resolved_outcome: Optional[str] = None,
        outcome_prices: Optional[List[float]] = None,
        source: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update market via API endpoint

        Args:
            market_id: Market identifier
            is_resolved: Whether market is resolved
            resolved_outcome: Resolved outcome (YES/NO)
            outcome_prices: Optional outcome prices
            source: Optional source (ws/poll)

        Returns:
            Updated market dict or None on error
        """
        payload = {}
        if is_resolved is not None:
            payload["is_resolved"] = is_resolved
        if resolved_outcome is not None:
            payload["resolved_outcome"] = resolved_outcome
        if outcome_prices is not None:
            payload["outcome_prices"] = outcome_prices
        if source is not None:
            payload["source"] = source

        if not payload:
            logger.warning(f"⚠️ No update data provided for market {market_id}")
            return None

        cache_key = f"api:market:{market_id}"
        result = await self._put(f"/markets/{market_id}", payload, cache_key, 'markets', use_cache=False)

        # Invalidate cache after update
        if result:
            await self.cache_manager.delete(cache_key)
            await self.cache_manager.invalidate_pattern(f"api:markets:*")

        return result

    async def get_market(self, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Get market by ID via API
        Automatically detects if market_id is a long condition_id and uses appropriate endpoint

        Args:
            market_id: Market identifier (can be short market_id or long condition_id)

        Returns:
            Market details or None if not found
        """
        # Detect if this is a condition_id (long ID) vs market_id (short ID)
        # condition_id: starts with 0x or longer than 20 characters
        # market_id: short numeric ID (typically 5-6 digits)
        is_condition_id = (
            market_id.startswith("0x") or
            len(market_id) > 20
        )

        if is_condition_id:
            # Use condition_id endpoint
            cache_key = f"api:market:condition:{market_id}"
            return await self._get(f"/markets/by-condition-id/{market_id}", cache_key, 'markets')
        else:
            # Use regular market_id endpoint
            cache_key = f"api:market:{market_id}"
            return await self._get(f"/markets/{market_id}", cache_key, 'markets')

    async def get_markets_batch(
        self,
        market_ids: List[str],
        use_cache: bool = True
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get multiple markets by IDs in a single API call (optimized for performance)
        Automatically handles both short market_ids and long condition_ids

        Args:
            market_ids: List of market identifiers (can be mix of short market_ids and long condition_ids)
            use_cache: Whether to use cache (default: True)

        Returns:
            List of market dicts or None on error
        """
        if not market_ids:
            return []

        # Remove duplicates while preserving order
        seen = set()
        unique_market_ids = []
        for market_id in market_ids:
            if market_id not in seen:
                seen.add(market_id)
                unique_market_ids.append(market_id)

        # Separate condition_ids from market_ids
        condition_ids = []
        short_market_ids = []
        for market_id in unique_market_ids:
            is_condition_id = (
                market_id.startswith("0x") or
                len(market_id) > 20
            )
            if is_condition_id:
                condition_ids.append(market_id)
            else:
                short_market_ids.append(market_id)

        # If we have condition_ids, we need to fetch them individually
        # (batch endpoint may not support condition_ids)
        markets = []

        # Fetch condition_ids individually
        for condition_id in condition_ids:
            try:
                market = await self.get_market(condition_id)  # This will use by-condition-id endpoint
                if market:
                    markets.append(market)
            except Exception as e:
                logger.warning(f"Failed to get market by condition_id {condition_id[:30]}...: {e}")

        # Fetch short market_ids via batch endpoint if available
        if short_market_ids:
            # Create cache key from sorted market_ids for consistency
            import hashlib
            sorted_ids = sorted(short_market_ids)
            cache_key_str = ":".join(sorted_ids)
            cache_key_hash = hashlib.md5(cache_key_str.encode()).hexdigest()[:16]
            cache_key = f"api:markets:batch:{cache_key_hash}"

            # Try cache first (if enabled)
            response = None
            if use_cache:
                cached_data = await self.cache_manager.get(cache_key, 'markets_list')
                if cached_data is not None:
                    logger.debug(f"Cache hit for batch markets: {len(short_market_ids)} markets")
                    # Return markets in the same order as requested
                    cached_dict = {m.get('id'): m for m in cached_data if isinstance(m, dict)}
                    batch_markets = [cached_dict.get(mid) for mid in short_market_ids if mid in cached_dict]
                    markets.extend(batch_markets)
                    # Return early if we got all from cache
                    if len(batch_markets) == len(short_market_ids):
                        # Return markets in the same order as requested
                        markets_dict = {m.get('id'): m for m in markets if isinstance(m, dict)}
                        ordered_markets = [markets_dict.get(mid) for mid in unique_market_ids if mid in markets_dict]
                        return ordered_markets
                else:
                    # Call batch endpoint
                    json_data = {"market_ids": short_market_ids}
                    response = await self._request_with_retry("POST", "/markets/batch", json_data)
            else:
                # Call batch endpoint directly if cache disabled
                json_data = {"market_ids": short_market_ids}
                response = await self._request_with_retry("POST", "/markets/batch", json_data)

        # If we only had condition_ids, return early
        if not short_market_ids:
            # Return markets in the same order as requested
            markets_dict = {m.get('id'): m for m in markets if isinstance(m, dict)}
            ordered_markets = [markets_dict.get(mid) for mid in unique_market_ids if mid in markets_dict]
            return ordered_markets

        if response is None:
            logger.warning(f"⚠️ Batch endpoint failed, falling back to individual calls for {len(unique_market_ids)} markets")
            # Fallback to individual calls for backward compatibility
            markets = []
            for market_id in unique_market_ids:
                market = await self.get_market(market_id)
                if market:
                    markets.append(market)
            return markets

        try:
            response.raise_for_status()
            data = response.json()

            # Extract markets from response
            batch_markets = data.get('markets', [])
            if not batch_markets:
                # If batch returned empty, return what we have (condition_ids)
                markets_dict = {m.get('id'): m for m in markets if isinstance(m, dict)}
                ordered_markets = [markets_dict.get(mid) for mid in unique_market_ids if mid in markets_dict]
                return ordered_markets

            # Cache successful response (if caching enabled)
            if use_cache:
                await self.cache_manager.set(cache_key, batch_markets, 'markets_list')
                logger.debug(f"Cached batch markets: {len(batch_markets)} markets")

            # Add batch markets to our markets list
            markets.extend(batch_markets)

            # Return markets in the same order as requested
            markets_dict = {m.get('id'): m for m in markets if isinstance(m, dict)}
            ordered_markets = [markets_dict.get(mid) for mid in unique_market_ids if mid in markets_dict]

            return ordered_markets

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"⚠️ Batch endpoint returned 404, falling back to individual calls")
                # Fallback to individual calls
                markets = []
                for market_id in unique_market_ids:
                    market = await self.get_market(market_id)
                    if market:
                        markets.append(market)
                return markets
            logger.error(f"API error {e.response.status_code} for batch markets: {e}")
            # Fallback to individual calls on error
            markets = []
            for market_id in unique_market_ids:
                market = await self.get_market(market_id)
                if market:
                    markets.append(market)
            return markets
        except Exception as e:
            logger.error(f"API request error for batch markets: {e}")
            # Fallback to individual calls on error
            markets = []
            for market_id in unique_market_ids:
                market = await self.get_market(market_id)
                if market:
                    markets.append(market)
            return markets

    async def fetch_market_on_demand(self, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch market data on-demand from Polymarket API and update DB
        Useful for refreshing prices when they're not available

        Args:
            market_id: Market identifier

        Returns:
            Fresh market details or None on error
        """
        endpoint = f"/markets/fetch/{market_id}"

        response = await self._request_with_retry("POST", endpoint)

        if response is None:
            logger.error(f"API POST failed for fetch market on-demand: {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()

            # Invalidate cache for this market since we have fresh data
            cache_key = f"api:market:{market_id}"
            await self.cache_manager.invalidate(cache_key)

            logger.debug(f"Market {market_id} fetched on-demand successfully")
            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"Market {market_id} not found for on-demand fetch")
                return None
            logger.error(f"API error {e.response.status_code} for fetch market on-demand: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for fetch market on-demand: {e}")
            return None

    async def get_watched_address(self, watched_address_id: int) -> Optional[Dict[str, Any]]:
        """
        Get watched address (leader) statistics by ID via API

        Args:
            watched_address_id: WatchedAddress ID

        Returns:
            Leader statistics dict or None if not found
        """
        cache_key = f"api:copy_trading:watched_address:{watched_address_id}"
        return await self._get(f"/copy-trading/watched-address/{watched_address_id}", cache_key, 'user_profile')

    async def resolve_leader_by_address(self, polygon_address: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a Polygon address to leader information via API

        Uses 3-tier resolution:
        1. Bot User (from users table) → creates watched_address with user_id
        2. Smart Trader (from watched_addresses with type='smart_trader')
        3. Copy Leader (from watched_addresses with type='copy_leader' or create new)

        Args:
            polygon_address: Polygon wallet address (case-insensitive)

        Returns:
            Dict with leader info (leader_type, leader_id, watched_address_id, address) or None on error
        """
        cache_key = f"api:copy_trading:resolve_leader:{polygon_address.lower().strip()}"
        return await self._get(f"/copy-trading/resolve-leader/{polygon_address}", cache_key, 'user_profile')

    async def subscribe_to_leader(
        self,
        follower_user_id: int,
        leader_address: str,
        allocation_type: str = 'percentage',
        allocation_value: float = 50.0,
        mode: str = 'proportional',
        fixed_amount: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Subscribe follower to a leader via API

        Args:
            follower_user_id: Telegram user ID of follower
            leader_address: Polygon address of leader
            allocation_type: 'percentage' or 'fixed_amount'
            allocation_value: Percentage (0-100) or fixed amount in USD
            mode: 'proportional' or 'fixed_amount'
            fixed_amount: Fixed USD amount for copy trading (optional)

        Returns:
            Subscription result dict or None on error
        """
        json_data = {
            "follower_user_id": follower_user_id,
            "leader_address": leader_address,
            "allocation_type": allocation_type,
            "allocation_value": allocation_value,
            "mode": mode
        }
        if fixed_amount is not None:
            json_data["fixed_amount"] = fixed_amount

        # Invalidate follower-related cache
        await self.cache_manager.invalidate_pattern(f"api:copy_trading:followers:{follower_user_id}*")

        return await self._post("/copy-trading/subscribe", json_data)

    async def update_allocation(
        self,
        user_id: int,
        allocation_value: Optional[float] = None,
        allocation_type: Optional[str] = None,
        fixed_amount: Optional[float] = None,
        mode: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update allocation settings for a follower via API

        Args:
            user_id: Telegram user ID
            allocation_value: New allocation value (for budget percentage)
            allocation_type: Optional new type ('percentage' or 'fixed_amount')
            fixed_amount: Fixed USD amount for copy trading
            mode: Copy mode ('proportional' or 'fixed_amount')

        Returns:
            Update result dict or None on error
        """
        json_data = {}
        if allocation_value is not None:
            json_data["allocation_value"] = allocation_value
        if allocation_type:
            json_data["allocation_type"] = allocation_type
        if fixed_amount is not None:
            json_data["fixed_amount"] = fixed_amount
        if mode:
            json_data["mode"] = mode

        # Invalidate follower-related cache
        await self.cache_manager.invalidate_pattern(f"api:copy_trading:followers:{user_id}*")

        endpoint = f"/copy-trading/followers/{user_id}/allocation"
        response = await self._request_with_retry("PUT", endpoint, json_data)

        if response is None:
            logger.error(f"API PUT failed for {endpoint}")
            return None

        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"API error {e.response.status_code} for {endpoint}: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for {endpoint}: {e}")
            return None

    async def get_follower_allocation(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get current allocation for a follower via API

        Args:
            user_id: Telegram user ID

        Returns:
            Allocation info dict or None if not found
        """
        cache_key = f"api:copy_trading:followers:{user_id}:allocation"
        return await self._get(f"/copy-trading/followers/{user_id}", cache_key, 'user_profile')

    async def get_follower_stats(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get copy trading stats for a follower via API

        Args:
            user_id: Telegram user ID

        Returns:
            Stats dict or None on error
        """
        cache_key = f"api:copy_trading:followers:{user_id}:stats"
        return await self._get(f"/copy-trading/followers/{user_id}/stats", cache_key, 'user_profile')

    async def unsubscribe_from_leader(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Unsubscribe follower from current leader via API

        Args:
            user_id: Telegram user ID

        Returns:
            Unsubscribe result dict or None on error
        """
        # Invalidate follower-related cache
        await self.cache_manager.invalidate_pattern(f"api:copy_trading:followers:{user_id}*")

        response = await self._request_with_retry("DELETE", f"/copy-trading/followers/{user_id}/subscription")

        if response is None:
            logger.error(f"API DELETE failed for unsubscribe: /copy-trading/followers/{user_id}/subscription")
            return None

        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"API error {e.response.status_code} for unsubscribe: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for unsubscribe: {e}")
            return None

    async def subscribe_websocket(self, user_id: int, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Subscribe user to market WebSocket updates via API

        Args:
            user_id: User ID
            market_id: Market ID

        Returns:
            Subscription result dict or None on error
        """
        json_data = {
            "user_id": user_id,
            "market_id": market_id
        }
        return await self._post("/websocket/subscribe", json_data)

    async def unsubscribe_websocket(self, user_id: int, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Unsubscribe user from market WebSocket updates via API

        Args:
            user_id: User ID
            market_id: Market ID

        Returns:
            Unsubscription result dict or None on error
        """
        logger.info(f"🚪 [APIClient] Calling unsubscribe_websocket API: user={user_id}, market={market_id}")
        json_data = {
            "user_id": user_id,
            "market_id": market_id
        }
        result = await self._post("/websocket/unsubscribe", json_data)
        if result:
            logger.info(f"✅ [APIClient] Unsubscribe API call successful: {result}")
        else:
            logger.warning(f"⚠️ [APIClient] Unsubscribe API call returned None")
        return result

    async def get_websocket_subscriptions(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get user WebSocket subscriptions via API

        Args:
            user_id: User ID

        Returns:
            Subscriptions dict or None on error
        """
        cache_key = f"api:websocket:subscriptions:{user_id}"
        return await self._get(f"/websocket/subscriptions/{user_id}", cache_key, 'user_profile')

    async def get_smart_trading_recommendations(
        self,
        page: int = 1,
        limit: int = 5,
        max_age_minutes: int = 60,
        min_trade_value: float = 300.0,
        min_win_rate: float = 0.55
    ) -> Optional[Dict[str, Any]]:
        """
        Get smart trading recommendations via API

        Args:
            page: Page number (1-indexed)
            limit: Number of trades per page
            max_age_minutes: Maximum age of trades in minutes
            min_trade_value: Minimum trade value in USD
            min_win_rate: Minimum win rate (0-1)

        Returns:
            Dictionary with trades and pagination info, or None on error
        """
        endpoint = (
            f"/smart-trading/recommendations?"
            f"page={page}&limit={limit}&max_age_minutes={max_age_minutes}&"
            f"min_trade_value={min_trade_value}&min_win_rate={min_win_rate}"
        )
        cache_key = f"api:smart_trading:recommendations:{page}:{limit}:{max_age_minutes}:{min_trade_value}:{min_win_rate}"
        return await self._get(endpoint, cache_key, 'smart_trades')  # Cache using smart_trades TTL strategy

    async def get_smart_trading_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get smart trading statistics via API

        Returns:
            Dictionary with stats or None on error
        """
        cache_key = "api:smart_trading:stats"
        return await self._get("/smart-trading/stats", cache_key, 'user_profile', ttl=300)  # Cache 5 minutes

    async def get_private_key(self, telegram_user_id: int, key_type: str) -> Optional[str]:
        """
        Get decrypted private key for user (Polygon or Solana)

        SECURITY: This method does NOT cache private keys for security reasons.
        Always makes a fresh API call with retry logic.

        Args:
            telegram_user_id: Telegram user ID
            key_type: "polygon" or "solana"

        Returns:
            Decrypted private key string or None on error
        """
        if key_type not in ["polygon", "solana"]:
            logger.error(f"Invalid key_type: {key_type}. Must be 'polygon' or 'solana'")
            return None

        endpoint = f"/users/{telegram_user_id}/private-key/{key_type}"
        logger.debug(f"API GET (no cache): {endpoint}")

        # Don't retry on 404 or 429 (client errors)
        response = await self._request_with_retry("GET", endpoint, retry_on=[500, 502, 503, 504])

        if response is None:
            logger.error(f"API request failed for private key endpoint: {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()
            private_key = data.get('private_key')

            if not private_key:
                logger.warning(f"No private key in API response for user {telegram_user_id}, type {key_type}")
                return None

            logger.debug(f"Private key retrieved successfully for user {telegram_user_id}, type {key_type}")
            return private_key

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"Private key not found for user {telegram_user_id}, type {key_type}")
                return None
            elif e.response.status_code == 429:
                logger.warning(f"Rate limit exceeded for private key request: user {telegram_user_id}, type {key_type}")
                return None
            logger.error(f"API error {e.response.status_code} for private key endpoint: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for private key endpoint: {e}")
            return None

    async def get_api_credentials(self, telegram_user_id: int) -> Optional[Dict[str, str]]:
        """
        Get Polymarket API credentials for user

        SECURITY: This method does NOT cache credentials for security reasons.
        Always makes a fresh API call with retry logic.

        Args:
            telegram_user_id: Telegram user ID

        Returns:
            Dict with api_key, api_secret, api_passphrase or None on error
        """
        endpoint = f"/users/{telegram_user_id}/api-credentials"
        logger.debug(f"API GET (no cache): {endpoint}")

        # Don't retry on 404 (user doesn't have credentials)
        response = await self._request_with_retry("GET", endpoint, retry_on=[500, 502, 503, 504])

        if response is None:
            logger.error(f"API request failed for API credentials endpoint: {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()

            api_key = data.get('api_key')
            api_secret = data.get('api_secret')
            api_passphrase = data.get('api_passphrase')

            if not api_key or not api_secret or not api_passphrase:
                logger.warning(f"Incomplete API credentials in response for user {telegram_user_id}")
                return None

            logger.debug(f"API credentials retrieved successfully for user {telegram_user_id}")
            return {
                'api_key': api_key,
                'api_secret': api_secret,
                'api_passphrase': api_passphrase
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"API credentials not found for user {telegram_user_id}")
                return None
            logger.error(f"API error {e.response.status_code} for API credentials endpoint: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for API credentials endpoint: {e}")
            return None

    async def update_user(
        self,
        telegram_user_id: int,
        stage: Optional[str] = None,
        funded: Optional[bool] = None,
        auto_approval_completed: Optional[bool] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update user fields via API

        Args:
            telegram_user_id: Telegram user ID
            stage: New stage (optional)
            funded: Funded status (optional)
            auto_approval_completed: Auto-approval completed status (optional)
            api_key: API key (optional)
            api_secret: API secret (optional, should be encrypted)
            api_passphrase: API passphrase (optional)

        Returns:
            Updated user dict or None on error
        """
        # Build update payload (only include non-None fields)
        json_data = {}
        if stage is not None:
            json_data['stage'] = stage
        if funded is not None:
            json_data['funded'] = funded
        if auto_approval_completed is not None:
            json_data['auto_approval_completed'] = auto_approval_completed
        if api_key is not None:
            json_data['api_key'] = api_key
        if api_secret is not None:
            json_data['api_secret'] = api_secret
        if api_passphrase is not None:
            json_data['api_passphrase'] = api_passphrase

        if not json_data:
            logger.warning(f"No fields to update for user {telegram_user_id}")
            return None

        endpoint = f"/users/{telegram_user_id}"
        logger.debug(f"API PUT: {endpoint} with data: {json_data}")

        # Invalidate user cache after update
        await self.cache_manager.invalidate_pattern(f"api:user:{telegram_user_id}")
        await self.cache_manager.invalidate_pattern(f"api:users:{telegram_user_id}")

        response = await self._request_with_retry("PUT", endpoint, json_data)

        if response is None:
            logger.error(f"API PUT failed for update user: {endpoint}")
            return None

        try:
            response.raise_for_status()
            data = response.json()
            logger.debug(f"User {telegram_user_id} updated successfully")
            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"User {telegram_user_id} not found for update")
                return None
            logger.error(f"API error {e.response.status_code} for update user: {e}")
            return None
        except Exception as e:
            logger.error(f"API request error for update user: {e}")
            return None

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()


# Global singleton instance
_api_client: Optional[APIClient] = None


def get_api_client() -> APIClient:
    """Get global API client instance"""
    global _api_client
    if _api_client is None:
        _api_client = APIClient()
    return _api_client
