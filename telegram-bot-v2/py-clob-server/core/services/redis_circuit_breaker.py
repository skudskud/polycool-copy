#!/usr/bin/env python3
"""
Redis Circuit Breaker Service
Provides graceful degradation when Redis is unavailable
"""

import logging
from typing import Callable, Awaitable, Any, Optional, Dict
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)


class RedisCircuitBreaker:
    """Circuit breaker for Redis failures with graceful degradation"""

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 60, half_open_max_calls: int = 3):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        # State tracking
        self.failure_count = 0
        self.half_open_calls = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

        logger.info(f"🔌 Redis Circuit Breaker initialized: threshold={failure_threshold}, timeout={recovery_timeout}s")

    def record_success(self):
        """Record successful Redis operation"""
        if self.state == "HALF_OPEN":
            self.half_open_calls += 1
            if self.half_open_calls >= self.half_open_max_calls:
                self._transition_to_closed()
        elif self.state == "CLOSED":
            self.failure_count = 0  # Reset on sustained success

    def record_failure(self):
        """Record failed Redis operation"""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.failure_count >= self.failure_threshold:
            self._transition_to_open()
        elif self.state == "HALF_OPEN":
            self._transition_to_open()

    def _transition_to_open(self):
        """Transition to OPEN state"""
        self.state = "OPEN"
        logger.warning(f"🔴 REDIS CIRCUIT BREAKER OPEN - {self.failure_count} failures, switching to fallback mode")

    def _transition_to_closed(self):
        """Transition to CLOSED state"""
        self.state = "CLOSED"
        self.failure_count = 0
        self.half_open_calls = 0
        logger.info("🟢 REDIS CIRCUIT BREAKER CLOSED - Redis recovered, back to normal operation")

    def _transition_to_half_open(self):
        """Transition to HALF_OPEN state"""
        self.state = "HALF_OPEN"
        self.half_open_calls = 0
        logger.info("🟡 REDIS CIRCUIT BREAKER HALF-OPEN - Testing Redis recovery")

    def can_attempt_operation(self) -> bool:
        """Check if Redis operation can be attempted"""
        if self.state == "CLOSED":
            return True

        if self.state == "OPEN":
            # Check if recovery timeout has passed
            if (self.last_failure_time and
                (datetime.utcnow() - self.last_failure_time).seconds > self.recovery_timeout):
                self._transition_to_half_open()
                return True
            return False

        # HALF_OPEN - allow limited calls
        return self.half_open_calls < self.half_open_max_calls

    async def execute_with_fallback(
        self,
        redis_operation: Callable[[], Awaitable[Any]],
        fallback_operation: Callable[[], Awaitable[Any]],
        operation_name: str = "redis_operation"
    ) -> Any:
        """
        Execute Redis operation with circuit breaker protection

        Args:
            redis_operation: Async function that uses Redis
            fallback_operation: Async function for fallback behavior
            operation_name: Name for logging

        Returns:
            Result from Redis operation or fallback
        """
        if not self.can_attempt_operation():
            logger.debug(f"Redis circuit breaker {self.state} - using fallback for {operation_name}")
            return await fallback_operation()

        try:
            result = await redis_operation()
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            logger.warning(f"Redis operation '{operation_name}' failed: {e} - using fallback")
            try:
                return await fallback_operation()
            except Exception as fallback_error:
                logger.error(f"Fallback operation also failed: {fallback_error}")
                raise fallback_error

    def get_status(self) -> dict:
        """Get circuit breaker status for monitoring"""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "half_open_calls": self.half_open_calls,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "can_attempt": self.can_attempt_operation()
        }


# Global circuit breaker instance
_circuit_breaker: Optional[RedisCircuitBreaker] = None


def get_circuit_breaker() -> RedisCircuitBreaker:
    """Get or create global circuit breaker instance"""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = RedisCircuitBreaker()
    return _circuit_breaker


async def execute_redis_with_fallback(
    redis_operation: Callable[[], Awaitable[Any]],
    fallback_operation: Callable[[], Awaitable[Any]],
    operation_name: str = "redis_operation"
) -> Any:
    """
    Convenience function to execute Redis operation with circuit breaker

    Usage:
        result = await execute_redis_with_fallback(
            lambda: redis_client.get(key),
            lambda: await api_fallback(key),
            "get_user_positions"
        )
    """
    circuit_breaker = get_circuit_breaker()
    return await circuit_breaker.execute_with_fallback(
        redis_operation, fallback_operation, operation_name
    )
