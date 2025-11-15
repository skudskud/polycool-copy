"""
Performance Monitoring Utilities
Provides decorators and helpers for tracking execution time and performance metrics
"""
import logging
import time
import functools
from typing import Callable, Any

logger = logging.getLogger(__name__)


def log_execution_time(threshold_seconds: float = 2.0):
    """
    Decorator to log execution time of functions
    
    Args:
        threshold_seconds: Log as warning if execution exceeds this threshold
    
    Usage:
        @log_execution_time(threshold_seconds=1.0)
        async def my_slow_function():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                # Log based on threshold
                func_name = f"{func.__module__}.{func.__name__}"
                if execution_time > threshold_seconds:
                    logger.warning(f"⏱️ [SLOW] {func_name} took {execution_time:.2f}s (threshold: {threshold_seconds}s)")
                else:
                    logger.info(f"⏱️ {func_name} took {execution_time:.2f}s")
                
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"❌ {func.__module__}.{func.__name__} failed after {execution_time:.2f}s: {e}")
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                # Log based on threshold
                func_name = f"{func.__module__}.{func.__name__}"
                if execution_time > threshold_seconds:
                    logger.warning(f"⏱️ [SLOW] {func_name} took {execution_time:.2f}s (threshold: {threshold_seconds}s)")
                else:
                    logger.info(f"⏱️ {func_name} took {execution_time:.2f}s")
                
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"❌ {func.__module__}.{func.__name__} failed after {execution_time:.2f}s: {e}")
                raise
        
        # Return appropriate wrapper based on function type
        if functools.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class PerformanceTimer:
    """Context manager for timing code blocks"""
    
    def __init__(self, operation_name: str, log_level: str = "info"):
        self.operation_name = operation_name
        self.log_level = log_level
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        execution_time = self.end_time - self.start_time
        
        if exc_type:
            logger.error(f"❌ {self.operation_name} failed after {execution_time:.2f}s")
        elif execution_time > 2.0:
            logger.warning(f"⏱️ [SLOW] {self.operation_name} took {execution_time:.2f}s")
        else:
            log_method = getattr(logger, self.log_level)
            log_method(f"⏱️ {self.operation_name} took {execution_time:.2f}s")
    
    @property
    def elapsed(self) -> float:
        """Get elapsed time so far"""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time

