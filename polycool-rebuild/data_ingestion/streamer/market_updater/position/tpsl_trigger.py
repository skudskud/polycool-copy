"""
TPSL Trigger - Check and trigger TP/SL orders when prices change
Integrates with TPSLMonitor for hybrid approach (WebSocket + polling)
"""
from typing import List, Any, Optional
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class TPSLTrigger:
    """
    Check TP/SL triggers immediately when prices change via WebSocket
    This gives < 100ms latency instead of 10s polling
    """

    def __init__(self, tpsl_monitor=None):
        """
        Initialize TPSLTrigger

        Args:
            tpsl_monitor: Optional TPSLMonitor instance
        """
        self.tpsl_monitor = tpsl_monitor

    async def check_triggers_for_market(
        self,
        market_id: str,
        positions: List[Any]
    ) -> None:
        """
        Check TP/SL triggers immediately when prices change via WebSocket
        This gives < 100ms latency instead of 10s polling

        Args:
            market_id: Market ID
            positions: List of positions that were just updated
        """
        try:
            # Filter positions with active TP/SL
            positions_with_tpsl = [
                pos for pos in positions
                if pos.take_profit_price is not None or pos.stop_loss_price is not None
            ]

            if not positions_with_tpsl:
                return  # No TP/SL to check

            logger.debug(
                f"🎯 Checking TP/SL for {len(positions_with_tpsl)} positions on market {market_id}"
            )

            # Get TPSLMonitor if not provided
            if not self.tpsl_monitor:
                try:
                    from core.services.trading.tpsl_monitor import get_tpsl_monitor
                    self.tpsl_monitor = get_tpsl_monitor()
                except ImportError:
                    logger.debug("⚠️ TPSLMonitor import failed - hybrid approach unavailable")
                    return

            if not self.tpsl_monitor:
                logger.debug("⚠️ TPSLMonitor not available for hybrid triggering")
                return

            # Collect triggered positions for batch execution
            triggered_positions = []

            # Trigger immediate TP/SL checks for these positions
            for position in positions_with_tpsl:
                try:
                    # Use current_price from the position (just updated)
                    current_price = position.current_price
                    if current_price is None:
                        continue

                    # Check TP/SL conditions immediately
                    triggered = await self.tpsl_monitor._check_tpsl_conditions(
                        position,
                        current_price
                    )
                    if triggered:
                        logger.info(
                            f"🎯 HYBRID TRIGGER: TP/SL hit for position {position.id} "
                            f"@ ${current_price:.4f}"
                        )
                        triggered_positions.append((position, triggered, current_price))

                except Exception as e:
                    logger.error(f"❌ Error checking TP/SL for position {position.id}: {e}")
                    continue

            # Execute triggered sells in batch
            if triggered_positions:
                await self.tpsl_monitor._execute_triggered_sells(triggered_positions)

        except Exception as e:
            logger.error(f"⚠️ Error in TP/SL triggering: {e}")
