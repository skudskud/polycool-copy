#!/usr/bin/env python3
"""
P&L Formatter Utility
Formats profit/loss indicators with colors and bold text for Telegram
Tracks cache audit statistics
"""

import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def format_pnl_indicator(pnl_value: float, roi_pct: float) -> str:
    """
    Format P&L with color emoji and bold text

    Args:
        pnl_value: P&L in dollars
        roi_pct: ROI percentage

    Returns:
        Formatted string: "🟢 **+$X.XX (+Y.Y%)**" or "🔴 **-$X.XX (-Y.Y%)**"
    """
    if pnl_value >= 0:
        return f"🟢 **+${pnl_value:.2f} (+{roi_pct:.1f}%)**"
    else:
        return f"🔴 **-${abs(pnl_value):.2f} ({roi_pct:.1f}%)**"


def format_global_pnl_summary(positions: Dict, current_prices: Dict, cache_stats: Dict) -> str:
    """
    Format global P&L summary for all positions

    Args:
        positions: Dictionary of positions
        current_prices: Dictionary of current prices {token_id: price}
        cache_stats: Cache statistics {token_id: {hit: bool, time: float}}

    Returns:
        Formatted summary string with total P&L and cache stats
    """
    total_pnl = 0
    total_invested = 0
    cache_hits = 0
    cache_misses = 0
    position_count = 0

    for pos_key, position in positions.items():
        token_id = position.get('token_id', '')
        tokens = float(position.get('tokens', 0))
        buy_price = float(position.get('buy_price', 0))

        if tokens > 0 and token_id in current_prices:
            current_price = current_prices[token_id]
            position_pnl = (current_price - buy_price) * tokens
            total_pnl += position_pnl
            total_invested += buy_price * tokens
            position_count += 1

            # Track cache stats
            if token_id in cache_stats:
                if cache_stats[token_id].get('hit'):
                    cache_hits += 1
                else:
                    cache_misses += 1

    # Calculate cache hit rate
    total_cache_checks = cache_hits + cache_misses
    cache_hit_rate = (cache_hits / total_cache_checks * 100) if total_cache_checks > 0 else 0

    # Format ROI
    roi_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    # Create summary
    pnl_indicator = format_pnl_indicator(total_pnl, roi_pct)

    summary = f"📊 **GLOBAL P&L**\n"
    summary += f"{pnl_indicator}\n"
    summary += f"💰 Invested: ${total_invested:.2f}\n"
    summary += f"📦 Positions: {position_count}\n"
    summary += f"⚡ Cache Hit Rate: {cache_hit_rate:.0f}% ({cache_hits}/{total_cache_checks})\n\n"

    return summary


def format_position_pnl(
    position: Dict,
    current_price: float,
    cache_hit: bool,
    fetch_time: float
) -> str:
    """
    Format P&L for a single position

    Args:
        position: Position data
        current_price: Current market price
        cache_hit: Whether price came from cache
        fetch_time: Time taken to fetch price

    Returns:
        Formatted P&L section with execution vs current price
    """
    tokens = float(position.get('tokens', 0))
    buy_price = float(position.get('buy_price', 0))

    if tokens <= 0:
        return ""

    # Calculate P&L
    position_pnl = (current_price - buy_price) * tokens
    roi_pct = (position_pnl / (buy_price * tokens) * 100) if (buy_price * tokens) > 0 else 0

    # Format pricing info
    cache_indicator = "🚀 CACHE" if cache_hit else "📡 API"
    timing_info = f"{fetch_time*1000:.0f}ms" if fetch_time < 1 else f"{fetch_time:.2f}s"

    pnl_indicator = format_pnl_indicator(position_pnl, roi_pct)

    pnl_section = f"   💰 Buy Price: ${buy_price:.4f}\n"
    pnl_section += f"   📈 Current: ${current_price:.4f} ({cache_indicator}, {timing_info})\n"
    pnl_section += f"   {pnl_indicator}\n"

    return pnl_section


def log_price_fetch_stats(token_id: str, cache_hit: bool, price: float, fetch_time: float):
    """
    Log price fetch statistics for audit trail

    Args:
        token_id: ERC-1155 token ID
        cache_hit: Whether price came from cache
        price: Price value
        fetch_time: Time taken to fetch
    """
    source = "CACHE HIT" if cache_hit else "API FETCH"
    logger.info(
        f"📊 [PRICE_FETCH] token={token_id[:20]}... | "
        f"source={source} | "
        f"price=${price:.4f} | "
        f"time={fetch_time*1000:.1f}ms"
    )


def get_cache_audit_footer(cache_stats: Dict) -> str:
    """
    Generate footer with cache audit information

    Args:
        cache_stats: Dictionary of cache statistics

    Returns:
        Formatted footer string
    """
    if not cache_stats:
        return ""

    total_hits = sum(1 for s in cache_stats.values() if s.get('hit'))
    total_checks = len(cache_stats)
    hit_rate = (total_hits / total_checks * 100) if total_checks > 0 else 0

    avg_ttl = sum(s.get('ttl', 0) for s in cache_stats.values()) / total_checks if total_checks > 0 else 0

    footer = f"\n⚡ **Cache Audit:** {hit_rate:.0f}% hit rate | {total_hits}/{total_checks} from Redis | Avg TTL: {avg_ttl:.0f}s"

    return footer
