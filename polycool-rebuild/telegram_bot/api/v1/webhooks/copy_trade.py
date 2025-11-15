"""
Copy Trading Webhook Receiver
Receives trade notifications from indexer-ts and broadcasts via Redis PubSub
"""
import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import Trade, WatchedAddress
from core.models.webhook_models import CopyTradeWebhookPayload, WebhookResponse
from core.services.redis_pubsub import get_redis_pubsub_service
from core.services.copy_trading.leader_position_tracker import get_leader_position_tracker
from core.services.smart_trading import SmartWalletPositionTracker
from core.services.market_service import get_market_service
from data_ingestion.indexer.watched_addresses.manager import get_watched_addresses_manager
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def verify_webhook_secret(request: Request) -> bool:
    """
    Verify webhook secret from header

    Args:
        request: FastAPI request object

    Returns:
        True if secret is valid

    Raises:
        HTTPException if secret is invalid
    """
    webhook_secret = settings.telegram.webhook_secret
    if not webhook_secret:
        # No secret configured, allow all (dev mode)
        return True

    provided_secret = request.headers.get("X-Webhook-Secret")
    if not provided_secret or provided_secret != webhook_secret:
        logger.warning(f"❌ Invalid webhook secret from {request.client.host if request.client else 'unknown'}")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    return True


@router.post("/copy-trade", response_model=WebhookResponse)
async def receive_copy_trade_webhook(
    event: CopyTradeWebhookPayload,
    request: Request,
    _: bool = Depends(verify_webhook_secret)
) -> WebhookResponse:
    """
    Receive copy trade webhook from indexer-ts

    Flow:
    1. Validate webhook secret
    2. Check if address is watched (fast cache lookup)
    3. Store in DB (async, non-blocking)
    4. Publish to Redis PubSub (async, non-blocking)
    5. Return 200 OK quickly

    Args:
        event: Webhook payload from indexer
        request: FastAPI request object

    Returns:
        WebhookResponse with status
    """
    try:
        # Fast check: Is this address watched?
        # Refresh cache periodically to catch new addresses
        watched_manager = get_watched_addresses_manager()
        await watched_manager.refresh_cache()  # Ensure cache is up-to-date
        address_info = await watched_manager.is_watched_address(event.user_address)

        # Only log for leaders (not smart_traders)
        if address_info.get('address_type') == 'copy_leader':
            logger.info(
                f"🎣 [WEBHOOK] Received {event.tx_type} trade webhook for "
                f"{event.user_address[:10]}... (tx: {event.tx_id[:20]}...) "
                f"(market: {event.market_id[:20] if event.market_id else 'N/A'}...)"
            )
            logger.info(
                f"🔍 [WEBHOOK_CHECK] Address check result for {event.user_address[:10]}...: "
                f"is_watched={address_info.get('is_watched')}, "
                f"address_type={address_info.get('address_type')}, "
                f"details={address_info}"
            )

        if not address_info['is_watched']:
            # Not a watched address, ignore
            logger.info(f"⏭️ [WEBHOOK_SKIP] Skipped unwatched address: {event.user_address[:10]}... (address_type: {address_info.get('address_type', 'unknown')})")
            return WebhookResponse(
                status="ignored",
                message="Not a watched address"
            )

        # Get watched address record (with timeout handling)
        watched_address = None
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.address == event.user_address.lower())
                    .where(WatchedAddress.is_active == True)
                )
                watched_address = result.scalar_one_or_none()

                # Only log for leaders (not smart_traders)
                if watched_address and watched_address.address_type == 'copy_leader':
                    logger.info(
                        f"🔍 [WEBHOOK_DB] DB lookup result for {event.user_address[:10]}...: "
                        f"found={watched_address is not None}"
                    )
                    logger.info(
                        f"📋 [WEBHOOK_DB] WatchedAddress details: id={watched_address.id}, "
                        f"address_type={watched_address.address_type}, "
                        f"name={watched_address.name}, is_active={watched_address.is_active}"
                    )
        except Exception as db_error:
            error_msg = str(db_error).lower()
            # Check if this is a connection timeout/error
            if any(keyword in error_msg for keyword in [
                'connection timeout',
                'connection timed out',
                'could not connect to server',
                'server closed the connection'
            ]):
                logger.error(f"❌ DB connection error in webhook handler: {db_error}")
                # Return 200 OK to prevent retry from indexer, but log error
                return WebhookResponse(
                    status="error",
                    message="Database temporarily unavailable"
                )
            else:
                # Re-raise other errors
                raise

        if not watched_address:
            logger.warning(f"⚠️ [WEBHOOK_DB] Watched address not found in DB: {event.user_address[:10]}... (full: {event.user_address})")
            return WebhookResponse(
                status="ignored",
                message="Watched address not found"
            )

        # Store in DB and update leader positions (async, non-blocking - don't wait)
        # ✅ Filter: Only store smart trader trades >= $50
        should_store_trade = True
        if watched_address.address_type == 'smart_wallet':
            try:
                # Convert string values to float for comparison
                taking_amount = float(event.taking_amount) if event.taking_amount else 0.0
                amount = float(event.amount) if event.amount else 0.0
                price = float(event.price) if event.price else 0.0

                amount_usdc = taking_amount or (amount * price)
                if amount_usdc < 50.0:
                    # Use debug level for smart trader filtering (not leaders)
                    logger.debug(f"⏭️ [WEBHOOK_FILTER] Skipped smart trader trade < $50: {event.user_address[:10]}... (${amount_usdc:.2f})")
                    should_store_trade = False
            except (ValueError, TypeError) as e:
                # Use debug level for smart trader errors (not leaders)
                logger.debug(f"⚠️ [WEBHOOK_FILTER] Could not parse amount_usdc for smart trader: {event.user_address[:10]}... ({e})")
                # If we can't parse, default to storing (better to store than lose data)
                pass

        if should_store_trade:
            asyncio.create_task(
                _store_trade_in_db_with_retry(
                    watched_address_id=watched_address.id,
                    event=event,
                    watched_address=watched_address
                )
            )

        # Publish to Redis PubSub (async, non-blocking - don't wait)
        # ✅ Filter: Only publish smart trader trades >= $50
        should_publish = True
        if watched_address.address_type == 'smart_wallet':
            try:
                # Convert string values to float for comparison
                taking_amount = float(event.taking_amount) if event.taking_amount else 0.0
                amount = float(event.amount) if event.amount else 0.0
                price = float(event.price) if event.price else 0.0

                amount_usdc = taking_amount or (amount * price)
                if amount_usdc < 50.0:
                    should_publish = False
                    logger.debug(f"⏭️ [REDIS_FILTER] Skipped publishing smart trader trade < $50: {event.user_address[:10]}... (${amount_usdc:.2f})")
            except (ValueError, TypeError) as e:
                logger.debug(f"⚠️ [REDIS_FILTER] Could not parse amount_usdc for smart trader: {event.user_address[:10]}... ({e})")
                # If we can't parse, default to publishing (better to publish than lose data)
                pass

        if should_publish:
            # Only log for leaders (not smart_traders)
            if address_info['address_type'] == 'copy_leader':
                logger.info(
                    f"📤 [WEBHOOK] Publishing to Redis PubSub for {event.user_address[:10]}... "
                    f"(address_type={address_info['address_type']}, tx_id={event.tx_id[:20]}...)"
                )
            asyncio.create_task(
                _publish_to_redis(
                    user_address=event.user_address,
                    event=event,
                    address_type=address_info['address_type']
                )
            )

        # Only log for leaders (not smart_traders)
        if address_info['address_type'] == 'copy_leader':
            logger.info(
                f"✅ [WEBHOOK] Processed {event.tx_type} trade for "
                f"{event.user_address[:10]}... ({address_info['address_type']})"
            )

        return WebhookResponse(
            status="ok",
            message=f"Trade processed and broadcast for {address_info['address_type']}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}", exc_info=True)
        # Return 200 OK even on error (don't retry from indexer)
        return WebhookResponse(
            status="error",
            message=f"Internal error: {str(e)[:100]}"
        )


async def _store_trade_in_db_with_retry(
    watched_address_id: int,
    event: CopyTradeWebhookPayload,
    watched_address: WatchedAddress = None,
    max_retries: int = 3,
    retry_delay: float = 2.0
) -> None:
    """Store trade in database with retry logic for Supabase connection issues"""
    logger.info(
        f"🔄 [WEBHOOK_DB] Starting DB storage for trade {event.tx_hash[:20]}... "
        f"(address_id: {watched_address_id})"
    )
    last_error = None

    for attempt in range(max_retries):
        try:
            await _store_trade_in_db(watched_address_id, event, watched_address)
            logger.info(f"✅ [WEBHOOK_DB] Successfully stored trade {event.tx_hash[:20]}... (attempt {attempt + 1})")
            return  # Success, exit retry loop

        except Exception as e:
            last_error = e
            error_msg = str(e).lower()

            # Check if this is a Supabase connection error that we should retry
            if any(keyword in error_msg for keyword in [
                'tenant or user not found',
                'connection pool exhausted',
                'connection timeout',
                'connection timed out',
                'server closed the connection unexpectedly',
                'could not connect to server',
                'connection timeout expired'  # Added for psycopg errors
            ]):
                if attempt < max_retries - 1:  # Not the last attempt
                    logger.warning(f"⚠️ [WEBHOOK_DB] DB connection error (attempt {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                    continue
                else:
                    logger.error(f"❌ [WEBHOOK_DB] DB connection failed after {max_retries} attempts: {e}")
            else:
                # Non-retryable error (like datetime issues, constraint violations, etc.)
                logger.error(f"❌ [WEBHOOK_DB] Non-retryable DB error (attempt {attempt + 1}): {e}", exc_info=True)
                break

    # If we get here, all retries failed
    logger.error(f"❌ [WEBHOOK_DB] Final DB storage failure for {event.tx_hash[:20]}...: {last_error}", exc_info=True)


async def _resolve_outcome_from_market(market_id: str, outcome_index: int) -> str:
    """
    Resolve outcome string from market_id and outcome index

    Args:
        market_id: Market ID
        outcome_index: Outcome index (0, 1, etc.)

    Returns:
        Outcome string from market's outcomes array, or "UNKNOWN" if not found
    """
    if not market_id or market_id == "unknown":
        return "UNKNOWN"

    try:
        market_service = get_market_service()
        market = await market_service.get_market_by_id(market_id)

        if not market:
            logger.warning(f"⚠️ Market {market_id} not found for outcome resolution")
            return "UNKNOWN"

        outcomes = market.get('outcomes', [])
        if not outcomes or not isinstance(outcomes, list):
            logger.warning(f"⚠️ No outcomes array in market {market_id}")
            return "UNKNOWN"

        try:
            outcome_idx = int(outcome_index) if isinstance(outcome_index, (int, str)) else 0
            if 0 <= outcome_idx < len(outcomes):
                return outcomes[outcome_idx]
            else:
                logger.warning(f"⚠️ Outcome index {outcome_idx} out of range for market {market_id} (outcomes: {outcomes})")
                return "UNKNOWN"
        except (ValueError, TypeError) as e:
            logger.warning(f"⚠️ Invalid outcome index {outcome_index}: {e}")
            return "UNKNOWN"
    except Exception as e:
        logger.warning(f"⚠️ Error resolving outcome from market {market_id}: {e}")
        return "UNKNOWN"


async def _resolve_outcome_from_position_id(position_id: str) -> Optional[str]:
    """
    Resolve outcome from position_id (clob_token_id) by finding the market
    and matching position_id to the outcomes array index

    Args:
        position_id: clob_token_id (position_id from trade)

    Returns:
        Outcome string or None if not found
    """
    if not position_id:
        return None

    try:
        from core.database.connection import get_db
        from core.database.models import Market
        from sqlalchemy import select, or_

        async with get_db() as db:
            # Find market containing this position_id in clob_token_ids
            result = await db.execute(
                select(Market)
                .where(
                    or_(
                        Market.clob_token_ids.contains([position_id]),
                        Market.clob_token_ids.contains([str(position_id)]),
                    ),
                    Market.is_active == True
                )
            )
            matching_market = result.scalar_one_or_none()

            if not matching_market:
                logger.debug(f"⚠️ [RESOLVE_OUTCOME] No market found for position_id ...{position_id[-20:]}")
                return None

            # Find index of position_id in clob_token_ids
            clob_token_ids = matching_market.clob_token_ids or []
            outcomes = matching_market.outcomes or []

            token_index = -1
            for i, token_id in enumerate(clob_token_ids):
                if str(token_id) == str(position_id):
                    token_index = i
                    break

            if token_index >= 0 and token_index < len(outcomes):
                outcome_str = outcomes[token_index]
                logger.info(
                    f"✅ [RESOLVE_OUTCOME] Resolved outcome via position_id: ...{position_id[-20]} → {outcome_str} "
                    f"(market: {matching_market.title[:50] if matching_market.title else 'N/A'}...)"
                )
                return outcome_str
            else:
                logger.warning(
                    f"⚠️ [RESOLVE_OUTCOME] position_id index {token_index} out of range "
                    f"(clob_token_ids: {len(clob_token_ids)}, outcomes: {len(outcomes)})"
                )
                return None

    except Exception as e:
        logger.error(f"❌ [RESOLVE_OUTCOME] Error resolving outcome from position_id: {e}", exc_info=True)
        return None


async def _store_trade_in_db(
    watched_address_id: int,
    event: CopyTradeWebhookPayload,
    watched_address: WatchedAddress = None
) -> None:
    """Store trade in database (background task)"""
    try:
        async with get_db() as db:
            # Get watched_address if not provided
            if not watched_address:
                result_addr = await db.execute(
                    select(WatchedAddress).where(WatchedAddress.id == watched_address_id)
                )
                watched_address = result_addr.scalar_one_or_none()
            # Check if trade already exists (deduplication)
            result = await db.execute(
                select(Trade)
                .where(Trade.tx_hash == event.tx_hash)
            )
            existing = result.scalar_one_or_none()

            if existing:
                logger.info(f"⏭️ Trade {event.tx_hash[:20]}... already exists in DB (skipping)")
                return

            # Parse values
            try:
                # amount is in units (6 decimals), convert to real value
                amount_raw = float(event.amount) if event.amount else 0.0
                amount = amount_raw / 1_000_000 if amount_raw > 1_000_000 else amount_raw  # Convert if in units
                price = float(event.price) if event.price else None
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Invalid amount/price in webhook: {event.amount}, {event.price}")
                amount = 0.0
                price = None

            # Parse amount_usdc (taking_amount) - already in USDC real value, not units
            amount_usdc = None
            if event.taking_amount:
                try:
                    amount_usdc = float(event.taking_amount)
                    # Validate range to prevent overflow
                    if amount_usdc > 999999999.999999 or amount_usdc < -999999999.999999:
                        logger.warning(f"⚠️ amount_usdc out of range: {amount_usdc}, setting to None")
                        amount_usdc = None
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ Invalid taking_amount format: {event.taking_amount}")
                    amount_usdc = None

            # Parse timestamp (convert to naive datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE)
            try:
                timestamp_aware = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
                # Convert aware datetime to naive (PostgreSQL expects TIMESTAMP WITHOUT TIME ZONE)
                timestamp = timestamp_aware.replace(tzinfo=None)
            except Exception:
                timestamp = datetime.utcnow()

            # Resolve outcome from market's outcomes array (not hardcoded YES/NO)
            outcome_str = await _resolve_outcome_from_market(event.market_id, event.outcome)
            
            # Fallback: Try to resolve via position_id if outcome is UNKNOWN
            if outcome_str == "UNKNOWN" and event.position_id:
                logger.debug(
                    f"⚠️ [WEBHOOK] Outcome resolution failed for market {event.market_id[:20] if event.market_id else 'N/A'}..., "
                    f"trying fallback via position_id"
                )
                outcome_str_fallback = await _resolve_outcome_from_position_id(event.position_id)
                if outcome_str_fallback:
                    outcome_str = outcome_str_fallback
                    logger.debug(f"✅ [WEBHOOK] Outcome resolved via position_id fallback: {outcome_str}")

            # Create trade record
            trade = Trade(
                watched_address_id=watched_address_id,
                market_id=event.market_id or "unknown",
                outcome=outcome_str,
                amount=amount,
                price=price or 0.0,
                amount_usdc=amount_usdc,  # Store exact USDC amount from indexer
                tx_hash=event.tx_hash,
                block_number=int(event.block_number) if event.block_number else None,
                timestamp=timestamp,
                trade_type=event.tx_type.lower(),  # 'buy' or 'sell'
                position_id=event.position_id,  # ✅ Store position_id from indexer
                is_processed=False,
                created_at=datetime.utcnow()  # Use naive datetime for PostgreSQL
            )

            db.add(trade)
            await db.commit()

            # Only log for leaders (not smart_traders)
            if watched_address.address_type == 'copy_leader':
                logger.info(
                    f"✅ [WEBHOOK_DB] Stored trade {event.tx_hash[:20]}... in DB "
                    f"(address: {watched_address.address[:10]}..., "
                    f"type: {event.tx_type}, amount_usdc: {amount_usdc}, "
                    f"market: {event.market_id[:20] if event.market_id else 'N/A'}...)"
                )

            # Update leader position tracking (only for copy_leader addresses)
            if watched_address.address_type == 'copy_leader' and event.market_id:
                try:
                    position_tracker = get_leader_position_tracker()

                    # Parse token amount (amount is in SHARES/tokens, not USD)
                    # amount = number of SHARES (from trades table)
                    token_amount = amount  # Already parsed above

                    # Resolve outcome from market's outcomes array (not hardcoded YES/NO)
                    outcome_str = await _resolve_outcome_from_market(event.market_id, event.outcome)

                    # Fallback: Try to resolve via position_id if outcome is UNKNOWN
                    if outcome_str == "UNKNOWN" and event.position_id:
                        logger.warning(
                            f"⚠️ [WEBHOOK] Outcome resolution failed for market {event.market_id[:20]}..., "
                            f"trying fallback via position_id ...{event.position_id[-20:]}"
                        )
                        outcome_str_fallback = await _resolve_outcome_from_position_id(event.position_id)
                        if outcome_str_fallback:
                            outcome_str = outcome_str_fallback
                            logger.info(
                                f"✅ [WEBHOOK] Outcome resolved via position_id fallback: {outcome_str}"
                            )

                    if outcome_str != "UNKNOWN":
                        # Update leader position (BUY adds, SELL subtracts)
                        # Use position_id from event for precise tracking (same as BUY logic)
                        success = await position_tracker.update_leader_position(
                            watched_address_id=watched_address_id,
                            market_id=event.market_id,
                            outcome=outcome_str,
                            trade_type=event.tx_type.upper(),  # 'BUY' or 'SELL'
                            token_amount=token_amount,  # Amount in SHARES (not USD)
                            tx_hash=event.tx_hash,
                            timestamp=timestamp_aware,  # Use aware datetime for position tracking
                            position_id=event.position_id  # Store position_id for precise lookup
                        )

                        if success:
                            logger.info(
                                f"✅ [WEBHOOK] Leader position updated: {watched_address.address[:10]}... "
                                f"{event.tx_type.upper()} {token_amount:.6f} SHARES "
                                f"(market: {event.market_id[:20]}..., outcome: {outcome_str}, "
                                f"amount_usdc: {amount_usdc})"
                            )
                        else:
                            logger.warning(
                                f"⚠️ [WEBHOOK] Failed to update leader position for trade {event.tx_hash[:20]}..."
                            )
                    else:
                        logger.warning(
                            f"⚠️ [WEBHOOK] Cannot update leader position: outcome is UNKNOWN "
                            f"(market: {event.market_id[:20]}..., position_id: {event.position_id[:20] if event.position_id else None}...)"
                            )
                except Exception as e:
                    # Non-blocking: Log error but don't fail trade storage
                    logger.error(f"❌ [WEBHOOK] Failed to update leader position: {e}", exc_info=True)

            # Track smart trader positions (only for smart_wallet addresses with >= $50 trades)
            if (watched_address.address_type == 'smart_wallet' and
                event.market_id and
                (amount_usdc or 0.0) >= 50.0):  # ✅ Only track smart trades >= $50
                try:
                    position_tracker = SmartWalletPositionTracker()

                    # Resolve outcome from market's outcomes array (not hardcoded YES/NO)
                    outcome_str = await _resolve_outcome_from_market(event.market_id, event.outcome)

                    if outcome_str != "UNKNOWN" and event.tx_type.upper() in ['BUY', 'SELL']:
                        if event.tx_type.upper() == 'BUY':
                            # Track position for BUY orders
                            trade_data = {
                                'market_id': event.market_id,
                                'smart_wallet_address': watched_address.address,
                                'outcome': outcome_str,
                                'entry_price': price or 0.0,
                                'size': amount,
                                'amount_usdc': amount_usdc or (amount * (price or 0.0)),
                                'position_id': event.position_id  # ✅ Store position_id for market resolution
                            }

                            success = await position_tracker.track_position(trade_data)

                            if success:
                                logger.debug(
                                    f"✅ Tracked smart position: {watched_address.address[:10]}... "
                                    f"BUY {amount:.6f} tokens @ ${price:.4f} "
                                    f"({event.market_id}/{outcome_str})"
                                )
                        else:  # SELL
                            # Close position for SELL orders
                            success = await position_tracker.close_position(
                                wallet_address=watched_address.address,
                                market_id=event.market_id,
                                outcome=outcome_str
                            )

                            if success:
                                logger.debug(
                                    f"✅ Closed smart position: {watched_address.address[:10]}... "
                                    f"SELL {amount:.6f} tokens "
                                    f"({event.market_id}/{outcome_str})"
                                )

                except Exception as e:
                    # Non-blocking: Log error but don't fail trade storage
                    logger.warning(f"⚠️ Failed to track smart position: {e}")

            # ✅ NEW: Notify alert channel bot for qualified smart wallet trades
            if (watched_address.address_type == 'smart_wallet' and
                event.tx_type.upper() == 'BUY' and
                (amount_usdc or 0.0) >= 300.0 and
                watched_address.win_rate and
                watched_address.win_rate >= 0.55):
                # Check trade age (< 5 minutes)
                trade_age_seconds = (datetime.now(timezone.utc) - timestamp_aware).total_seconds()
                if trade_age_seconds < 300:  # 5 minutes
                    # Trigger alert channel webhook (non-blocking)
                    asyncio.create_task(
                        _notify_alert_channel_bot(
                            trade_id=event.tx_hash,
                            market_id=event.market_id,
                            position_id=event.position_id,
                            wallet_address=watched_address.address,
                            wallet_name=watched_address.name,
                            win_rate=watched_address.win_rate,
                            risk_score=watched_address.risk_score,
                            outcome=outcome_str,  # outcome_str is defined above
                            side=event.tx_type.upper(),
                            price=price,
                            value=amount_usdc,
                            amount_usdc=amount_usdc,
                            timestamp=timestamp_aware.isoformat()
                        )
                    )

    except Exception as e:
        logger.error(f"❌ Error storing trade in DB: {e}")


async def _notify_alert_channel_bot(
    trade_id: str,
    market_id: Optional[str],
    position_id: Optional[str],
    wallet_address: str,
    wallet_name: Optional[str],
    win_rate: Optional[float],
    risk_score: Optional[float],
    outcome: Optional[str],
    side: str,
    price: Optional[float],
    value: Optional[float],
    amount_usdc: Optional[float],
    timestamp: str
) -> None:
    """
    Notify alert channel bot about a qualified smart wallet trade
    
    This is a non-blocking call - failures won't affect trade storage
    """
    try:
        import httpx
        from infrastructure.config.settings import settings as app_settings
        
        # Get alert channel bot URL from environment
        alert_bot_url = os.getenv("ALERT_CHANNEL_BOT_URL")
        if not alert_bot_url:
            logger.debug("⚠️ ALERT_CHANNEL_BOT_URL not set, skipping alert notification")
            return
        
        # Get market title if available
        market_title = None
        if market_id:
            try:
                market_service = get_market_service()
                market = await market_service.get_market_by_id(market_id)
                if market:
                    market_title = market.get('title')
            except Exception as e:
                logger.debug(f"Could not fetch market title: {e}")
        
        # Prepare webhook payload
        payload = {
            "trade_id": trade_id,
            "market_id": market_id,
            "market_title": market_title,
            "position_id": position_id,
            "wallet_address": wallet_address,
            "wallet_name": wallet_name,
            "win_rate": float(win_rate) if win_rate else None,
            "risk_score": float(risk_score) if risk_score else None,
            "outcome": outcome,
            "side": side,
            "price": float(price) if price else None,
            "value": float(value) if value else None,
            "amount_usdc": float(amount_usdc) if amount_usdc else None,
            "timestamp": timestamp
        }
        
        # Send webhook (with timeout)
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{alert_bot_url}/api/v1/alert-channel/notify",
                json=payload
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Notified alert channel bot for trade {trade_id[:20]}...")
            else:
                logger.warning(
                    f"⚠️ Alert channel bot returned {response.status_code} "
                    f"for trade {trade_id[:20]}...: {response.text[:100]}"
                )
                
    except Exception as e:
        # Non-blocking: Log error but don't fail trade storage
        logger.debug(f"⚠️ Failed to notify alert channel bot: {e}")


async def _publish_to_redis(
    user_address: str,
    event: CopyTradeWebhookPayload,
    address_type: str
) -> None:
    """Publish trade to Redis PubSub (background task)"""
    try:
        pubsub_service = get_redis_pubsub_service()

        # Ensure connected
        if not await pubsub_service.health_check():
            await pubsub_service.connect()

        # Build message
        message = {
            'tx_id': event.tx_id,
            'user_address': user_address.lower(),
            'position_id': event.position_id or '',
            'market_id': event.market_id,
            'outcome': event.outcome,
            'tx_type': event.tx_type,
            'amount': event.amount,
            'price': event.price,
            'taking_amount': event.taking_amount,
            'tx_hash': event.tx_hash,
            'timestamp': event.timestamp,
            'address_type': address_type
        }

        # Publish to channel: copy_trade:{user_address}
        channel = f"copy_trade:{user_address.lower()}"
        # Only log for leaders (not smart_traders)
        if address_type == 'copy_leader':
            logger.info(
                f"📤 [WEBHOOK_REDIS] Publishing {event.tx_type} to channel {channel} "
                f"(tx_id={event.tx_id[:20]}..., address_type={address_type})"
            )

        subscribers = await pubsub_service.publish(channel, message)

        # Only log for leaders (not smart_traders)
        if address_type == 'copy_leader':
            logger.info(
                f"✅ [WEBHOOK_REDIS] Published {event.tx_type} to {channel}, "
                f"subscribers: {subscribers} (tx_id={event.tx_id[:20]}...)"
            )

        if subscribers == 0:
            logger.warning(
                f"⚠️ [WEBHOOK_REDIS] No subscribers for channel {channel} - "
                f"Copy Trading Listener may not be running! (tx_id={event.tx_id[:20]}...)"
            )

    except Exception as e:
        # Non-blocking: If Redis fails, polling fallback will catch it
        logger.error(f"❌ [WEBHOOK_REDIS] Redis publish failed: {e}")


# Register route
from telegram_bot.api.v1.webhooks import webhook_router
webhook_router.include_router(router)
