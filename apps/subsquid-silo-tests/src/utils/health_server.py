"""
Reusable Health Check Server for Subsquid Services
Provides /health and /metrics endpoints for monitoring and observability.
Runs as a lightweight FastAPI server in a background asyncio task.
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from time import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response, JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)


class HealthServer:
    """
    Lightweight health check and metrics server.
    
    Features:
    - /health endpoint with service status (healthy/degraded/error)
    - /metrics endpoint for Prometheus scraping
    - Non-blocking async operation
    - Graceful shutdown support
    """
    
    def __init__(
        self,
        service_name: str,
        port: int,
        host: str = "0.0.0.0",
        error_threshold: int = 3,
        degraded_threshold_seconds: int = 90
    ):
        """
        Initialize health server.
        
        Args:
            service_name: Name of the service (e.g., "poller", "streamer")
            port: Port to listen on
            host: Host to bind to (default: 0.0.0.0)
            error_threshold: Consecutive errors before marking as "error"
            degraded_threshold_seconds: Seconds without update before marking as "degraded"
        """
        self.service_name = service_name
        self.port = port
        self.host = host
        self.error_threshold = error_threshold
        self.degraded_threshold_seconds = degraded_threshold_seconds
        
        # Service state (to be updated by parent service)
        self.last_update_time: Optional[datetime] = None
        self.consecutive_errors: int = 0
        self.total_cycles: int = 0
        self.start_time: float = time()
        self.custom_metrics: Dict[str, Any] = {}
        
        # FastAPI app
        self.app = FastAPI(title=f"{service_name} Health Server")
        self.server: Optional[uvicorn.Server] = None
        self.server_task: Optional[asyncio.Task] = None
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.get("/")
        async def root():
            """Root endpoint - service info"""
            return {
                "service": self.service_name,
                "version": "1.0.0",
                "endpoints": {
                    "health": "GET /health",
                    "metrics": "GET /metrics"
                }
            }
        
        @self.app.get("/health")
        async def health():
            """
            Health check endpoint.
            
            Returns:
                - status: "healthy" | "degraded" | "error"
                - service: service name
                - last_update: ISO timestamp of last update
                - uptime_seconds: uptime since service start
                - error_count: consecutive errors
                - metrics: custom service metrics
            """
            now = datetime.now(timezone.utc)
            uptime = time() - self.start_time
            
            # Determine status
            if self.consecutive_errors >= self.error_threshold:
                status = "error"
            elif self.last_update_time:
                age = (now - self.last_update_time).total_seconds()
                if age > self.degraded_threshold_seconds:
                    status = "degraded"
                else:
                    status = "healthy"
            else:
                # No updates yet
                if uptime < self.degraded_threshold_seconds:
                    status = "healthy"  # Service just started
                else:
                    status = "degraded"  # Service running but no updates
            
            return JSONResponse({
                "status": status,
                "service": self.service_name,
                "last_update": self.last_update_time.isoformat() if self.last_update_time else None,
                "uptime_seconds": round(uptime, 2),
                "error_count": self.consecutive_errors,
                "total_cycles": self.total_cycles,
                "metrics": self.custom_metrics
            })
        
        @self.app.get("/metrics")
        async def metrics():
            """Prometheus metrics endpoint"""
            return Response(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST
            )
    
    async def start(self):
        """Start the health server in background"""
        try:
            logger.info(f"🏥 Starting health server for {self.service_name} on {self.host}:{self.port}")
            
            config = uvicorn.Config(
                app=self.app,
                host=self.host,
                port=self.port,
                log_level="warning",  # Reduce noise
                access_log=False
            )
            self.server = uvicorn.Server(config)
            
            # Run server in background task
            self.server_task = asyncio.create_task(self.server.serve())
            
            logger.info(f"✅ Health server running at http://{self.host}:{self.port}")
            
        except Exception as e:
            logger.error(f"❌ Failed to start health server: {e}")
            raise
    
    async def stop(self):
        """Stop the health server gracefully"""
        if self.server:
            logger.info(f"⏹️ Stopping health server for {self.service_name}...")
            self.server.should_exit = True
            
            if self.server_task:
                try:
                    await asyncio.wait_for(self.server_task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("⚠️ Health server shutdown timed out")
                    self.server_task.cancel()
            
            logger.info("✅ Health server stopped")
    
    def update(
        self,
        last_update: Optional[datetime] = None,
        consecutive_errors: Optional[int] = None,
        total_cycles: Optional[int] = None,
        custom_metrics: Optional[Dict[str, Any]] = None
    ):
        """
        Update health server state.
        
        Args:
            last_update: Timestamp of last successful update
            consecutive_errors: Number of consecutive errors
            total_cycles: Total number of cycles completed
            custom_metrics: Custom service-specific metrics
        """
        if last_update is not None:
            self.last_update_time = last_update
        
        if consecutive_errors is not None:
            self.consecutive_errors = consecutive_errors
        
        if total_cycles is not None:
            self.total_cycles = total_cycles
        
        if custom_metrics is not None:
            self.custom_metrics.update(custom_metrics)


async def start_health_server(
    service_name: str,
    port: int,
    host: str = "0.0.0.0",
    error_threshold: int = 3,
    degraded_threshold_seconds: int = 90
) -> HealthServer:
    """
    Convenience function to create and start a health server.
    
    Args:
        service_name: Name of the service
        port: Port to listen on
        host: Host to bind to
        error_threshold: Consecutive errors before marking as error
        degraded_threshold_seconds: Seconds without update before degraded
    
    Returns:
        Running HealthServer instance
    """
    health_server = HealthServer(
        service_name=service_name,
        port=port,
        host=host,
        error_threshold=error_threshold,
        degraded_threshold_seconds=degraded_threshold_seconds
    )
    await health_server.start()
    return health_server

