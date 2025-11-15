"""
Utilities package for Subsquid Silo Tests
Contains reusable components for health checks, metrics, and monitoring.
"""

from .health_server import HealthServer, start_health_server
from .metrics import (
    # Counters
    poll_cycles_total,
    poll_markets_fetched_total,
    poll_errors_total,
    stream_messages_total,
    stream_duplicates_total,
    stream_stale_messages_total,
    stream_reconnections_total,
    db_upserts_total,
    db_retries_total,
    db_errors_total,
    
    # Gauges
    poll_last_cycle_duration_seconds,
    poll_markets_count,
    poll_consecutive_errors,
    stream_active_subscriptions,
    stream_last_message_age_seconds,
    stream_consecutive_errors,
    
    # Histograms
    poll_cycle_duration_seconds,
    stream_message_processing_seconds,
    db_upsert_duration_seconds,
)

__all__ = [
    "HealthServer",
    "start_health_server",
    # Metrics
    "poll_cycles_total",
    "poll_markets_fetched_total",
    "poll_errors_total",
    "stream_messages_total",
    "stream_duplicates_total",
    "stream_stale_messages_total",
    "stream_reconnections_total",
    "db_upserts_total",
    "db_retries_total",
    "db_errors_total",
    "poll_last_cycle_duration_seconds",
    "poll_markets_count",
    "poll_consecutive_errors",
    "stream_active_subscriptions",
    "stream_last_message_age_seconds",
    "stream_consecutive_errors",
    "poll_cycle_duration_seconds",
    "stream_message_processing_seconds",
    "db_upsert_duration_seconds",
]

