#!/usr/bin/env python3
"""
Async HTTP Client Singleton
Provides shared aiohttp ClientSession to avoid resource leaks
"""

import logging
import aiohttp
from typing import Optional

logger = logging.getLogger(__name__)


class AsyncHTTPClient:
    """
    Singleton aiohttp ClientSession manager
    Prevents creating multiple sessions and ensures proper cleanup
    """

    _instance: Optional['AsyncHTTPClient'] = None
    _session: Optional[aiohttp.ClientSession] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize (only once due to singleton)"""
        if self._session is None:
            logger.info("✅ AsyncHTTPClient singleton initialized")

    async def get_session(self) -> aiohttp.ClientSession:
        """
        Get or create shared ClientSession

        Returns:
            Shared aiohttp ClientSession
        """
        if self._session is None or self._session.closed:
            # Create new session with optimal settings
            timeout = aiohttp.ClientTimeout(
                total=30,           # Total request timeout
                connect=10,         # Connection timeout
                sock_read=20        # Socket read timeout
            )

            connector = aiohttp.TCPConnector(
                limit=100,          # Max simultaneous connections
                limit_per_host=30,  # Max per host
                ttl_dns_cache=300   # DNS cache TTL
            )

            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    'User-Agent': 'PolycoolBot/2.0',
                }
            )

            logger.info("🌐 Created new aiohttp ClientSession")

        return self._session

    async def close(self):
        """Close the session gracefully"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("🔒 Closed aiohttp ClientSession")
            self._session = None


# Global singleton instance
_http_client = AsyncHTTPClient()


async def get_http_client() -> aiohttp.ClientSession:
    """
    Convenience function to get the shared HTTP client session

    Usage:
        async with (await get_http_client()).get(url) as response:
            data = await response.json()

    Returns:
        Shared aiohttp ClientSession
    """
    return await _http_client.get_session()


async def fetch_json(url: str, timeout: int = 10) -> dict:
    """
    Convenience function to fetch JSON from URL

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON response

    Raises:
        aiohttp.ClientError: On HTTP errors
        asyncio.TimeoutError: On timeout
    """
    session = await get_http_client()

    async with session.get(
        url,
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as response:
        response.raise_for_status()
        return await response.json()


async def close_http_client():
    """Close the shared HTTP client (called on shutdown)"""
    await _http_client.close()
