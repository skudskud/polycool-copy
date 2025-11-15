# Data Ingestion Audit — Nov 8, 2025

## Snapshot
- **Scope**: Gamma poller, WebSocket streamer, on-chain indexer (DipDup/Subsquid), Redis fanout
- **Data sink**: `public.markets`, `public.positions`, `public.trades`, `public.watched_addresses` on Supabase (project `xxzdlbwfyetaxcmodiec`)
- **Status**: Poller + streamer refactored and deployed in rebuild repo; Subsquid stack still lives under `apps/subsquid-silo-tests` with critical fixes staged but not redeployed

## Architecture Map
- **Poller** (`data_ingestion/poller/gamma_api.py`): 60s loop pulls `/events`, extracts market-level payloads, enriches minimal metadata, and upserts JSONB-friendly payloads into `markets`
- **Streamer** (`data_ingestion/streamer/`): Demand-driven WebSocket client that only connects when positions exist; routes messages through `SubscriptionManager` → `MarketUpdater`
- **Indexer** (`data_ingestion/indexer/` + `apps/subsquid-silo-tests/indexer`): Async Redis listener + DipDup stack to translate blockchain transfers into copy-trading signals
- **Cache & Redis**: `CacheManager` remains source of truth for market cache invalidation; Redis Pub/Sub dedicated to trading events (separate from cache)

## Component Status

### Poller (Gamma API)
- Pagination rewritten to prioritise volume and prevent starvation of legacy events
- Upserts now run per-market with ON CONFLICT handling and JSONB payloads (supports direct GIN queries on `clob_token_ids`)
- Resolution heuristics tightened: only mark resolved if `resolvedBy`, closed timestamp in past, and winner deduced
- **Bug to fix**: stray `logger.info(".2f")` formatting placeholder left in `_poll_cycle`

```271:344:polycool/polycool-rebuild/data_ingestion/poller/gamma_api.py
                async with get_db() as db_tx:
                    await db_tx.execute(text("""
                        INSERT INTO markets (
                            id, source, title, description, category,
                            outcomes, outcome_prices, events,
                            is_event_market, parent_event_id,
                            volume, liquidity, last_trade_price,
                            clob_token_ids, condition_id,
                            is_resolved, resolved_outcome, resolved_at,
                            start_date, end_date, is_active,
                            event_id, event_slug, event_title, polymarket_url,
                            updated_at
                        ) VALUES (
                            :id, 'poll', :title, :description, :category,
                            :outcomes, :outcome_prices, :events,
                            :is_event_market, :parent_event_id,
                            :volume, :liquidity, :last_trade_price,
                            :clob_token_ids, :condition_id,
                            :is_resolved, :resolved_outcome, :resolved_at,
                            :start_date, :end_date, true,
                            :event_id, :event_slug, :event_title, :polymarket_url,
                            now()
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            title = EXCLUDED.title,
                            outcome_prices = EXCLUDED.outcome_prices,
                            volume = EXCLUDED.volume,
                            liquidity = EXCLUDED.liquidity,
                            last_trade_price = EXCLUDED.last_trade_price,
                            is_resolved = EXCLUDED.is_resolved,
                            resolved_outcome = EXCLUDED.resolved_outcome,
                            resolved_at = EXCLUDED.resolved_at,
                            event_id = EXCLUDED.event_id,
                            event_slug = EXCLUDED.event_slug,
                            event_title = EXCLUDED.event_title,
                            polymarket_url = EXCLUDED.polymarket_url,
                            updated_at = now()
                    """), {
                        'id': market.get('id'),
                        'title': market.get('question'),
                        'description': market.get('description'),
                        'category': market.get('category'),
                        'outcomes': json_dumps_safe(safe_json_parse(market.get('outcomes')) or []),
                        'outcome_prices': json_dumps_safe(safe_json_parse(market.get('outcomePrices')) or []),
                        'events': json_dumps_safe(safe_json_parse(market.get('events'))),
                        'is_event_market': market.get('event_id') is not None,
                        'parent_event_id': market.get('event_id'),
                        'volume': safe_float(market.get('volume', 0)),
                        'liquidity': safe_float(market.get('liquidity', 0)),
                        'last_trade_price': safe_float(market.get('lastTradePrice')),
                        'clob_token_ids': market.get('clobTokenIds', []) if market.get('clobTokenIds') else None,
                        'condition_id': market.get('conditionId'),
                        'is_resolved': self._is_market_really_resolved(market),
                        'resolved_outcome': self._calculate_winner(market) if self._is_market_really_resolved(market) else None,
                        'resolved_at': self._parse_resolution_time(market) if self._is_market_really_resolved(market) else None,
                        'start_date': self._parse_date(market.get('startDate')),
                        'end_date': self._parse_date(market.get('endDate')),
                        'event_id': market.get('event_id'),
                        'event_slug': market.get('event_slug'),
                        'event_title': market.get('event_title'),
                        'polymarket_url': self._build_polymarket_url(market)
                    })
```

- Subsquid deployment notes already capture required redeploy procedure; redeploy still outstanding

```1:136:polycool/apps/subsquid-silo-tests/data-ingestion/FINAL_IMPLEMENTATION_STATUS.md
# Poller Optimisation - Status Final d'Implémentation

**Date:** Nov 3, 2025 10:45 UTC
**Status:** ✅ Ready for Redeploy (Critical Fixes Applied)

---

## 🚨 Problème Critique Découvert & Fixé
...
### Étape 1: Redéployer le Poller (URGENT)
```

### Streamer (WebSocket + Cache)
- Lazily boots only when active positions exist; subscribes dynamically after trades
- Subscription manager resyncs token IDs, debounces cleanup, and handles JSON double-encoding edge cases
- Market updater keeps `markets` table authoritative, debounces position refresh, and invalidates cache keys consistently

```30:90:polycool/polycool-rebuild/data_ingestion/streamer/streamer.py
    async def start(self) -> None:
        """Start the streamer service"""
        if not self.enabled:
            logger.warning("⚠️ Streamer service disabled (STREAMER_ENABLED=false)")
            return

        logger.info("🌐 Streamer Service starting...")
        self.running = True

        # Register message handlers
        self.websocket_client.register_handler("price_update", self.market_updater.handle_price_update)
        self.websocket_client.register_handler("orderbook", self.market_updater.handle_orderbook_update)
        self.websocket_client.register_handler("trade", self.market_updater.handle_trade_update)
        self.websocket_client.register_handler("market", self.market_updater.handle_price_update)

        # Start subscription manager
        await self.subscription_manager.start()

        # Check if we have active positions before starting WebSocket
        has_active_positions = await self._check_active_positions()

        if has_active_positions:
            logger.info("✅ Active positions found - starting WebSocket client")
            await self.subscription_manager.subscribe_active_positions()
            await self.websocket_client.start()
        else:
            logger.info("⚠️ No active positions - streamer will wait for trades")
```

```130:214:polycool/polycool-rebuild/data_ingestion/streamer/subscription_manager.py
    async def subscribe_active_positions(self) -> None:
        """
        Subscribe to all markets with active user positions
        Called on startup and after reconnection
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Position.market_id)
                    .where(Position.status == "active")
                    .distinct()
                )
                market_ids = [row[0] for row in result.fetchall()]

            if not market_ids:
                logger.info("⚠️ No active positions found - no subscriptions needed")
                return

            all_token_ids: Set[str] = set()
            for market_id in market_ids:
                token_ids = await self._get_market_token_ids(market_id)
                all_token_ids.update(token_ids)

            if all_token_ids:
                await self.websocket_client.subscribe_markets(all_token_ids)
                logger.info(f"📡 Subscribed to {len(all_token_ids)} token IDs from {len(market_ids)} markets with active positions")
```

### Indexer & Copy-Trading Bridge
- `CopyTradingListener` consumes Redis events (`copy_trade:*`), deduplicates, maps to watched addresses, and triggers `TradeService`
- **Webhook endpoint**: `/api/v1/webhooks/copy_trade` receives events from indexer, stores in `trades` table, publishes to Redis
- **Redis PubSub**: Connected at startup in `main.py`, publishes to `copy_trade:{address}` channels
- Watched addresses cache syncs every 5 minutes to keep Redis warm for fast lookups
- **Remaining**: Connect DipDup/Subsquid indexer to webhook endpoint

```58:177:polycool/polycool-rebuild/data_ingestion/indexer/copy_trading_listener.py
        if self._is_duplicate(tx_id):
            logger.debug(f"⏭️ Skipped duplicate trade: {tx_id[:20]}...")
            return

        self._mark_processed(tx_id)
        self._metrics['total_trades_processed'] += 1

        address_info = await self.watched_manager.is_watched_address(user_address)
        if not address_info['is_watched']:
            logger.debug(f"⏭️ Address {user_address[:10]}... not watched")
            return

        async with get_db() as db:
            result = await db.execute(
                select(CopyTradingAllocation)
                .where(
                    and_(
                        CopyTradingAllocation.leader_address_id == watched_address.id,
                        CopyTradingAllocation.is_active == True
                    )
                )
            )
            allocations = list(result.scalars().all())

        if not allocations:
            logger.debug(f"⏭️ No active followers for leader {user_address[:10]}...")
            return

        tasks = []
        for allocation in allocations:
            task = asyncio.create_task(
                self._execute_copy_trade(allocation, trade_data)
            )
            tasks.append(task)
```

```34:91:polycool/polycool-rebuild/data_ingestion/indexer/watched_addresses/manager.py
    async def refresh_cache(self) -> Dict[str, Any]:
        """
        Refresh Redis cache with watched addresses
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.is_active == True)
                )
                addresses = list(result.scalars().all())

            smart_wallets = []
            copy_leaders = []
            bot_users = []

            for addr in addresses:
                if addr.address_type == 'smart_trader':
                    smart_wallets.append(addr.address.lower())
                elif addr.address_type == 'copy_leader':
                    copy_leaders.append(addr.address.lower())
                elif addr.address_type == 'bot_user':
                    bot_users.append(addr.address.lower())

            cache_data = {
                'smart_wallets': smart_wallets,
                'copy_leaders': copy_leaders,
                'bot_users': bot_users,
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'total_count': len(addresses),
                'smart_wallets_count': len(smart_wallets),
                'copy_leaders_count': len(copy_leaders),
                'bot_users_count': len(bot_users),
            }
```

```281:299:polycool/apps/subsquid-silo-tests/COPY_TRADING_ARCHITECTURE.md
### ⏳ Pending (Bot Integration)
- [ ] Telegram `/copytrading` command with inline keyboard
- [ ] Address validation and parsing
- [ ] Copy trading execution logic
- [ ] Webhook notification from DipDup to bot
- [ ] Budget calculation and scaling
- [ ] Failure handling and retries
- [ ] Analytics dashboard
```

## Data Schema Alignment (Supabase)
- `public.markets` carries JSONB columns for `outcomes`, `outcome_prices`, `clob_token_ids`; poller and streamer both feed this single source of truth
- `public.positions` tracks TP/SL columns that streamer + monitor must update; currently 13 rows (dev fixtures)
- `public.watched_addresses` empty; copy-trading manager persists to Redis only until addresses inserted
- `public.trades` remains empty pending DipDup ingestion

## Risks & To‑Dos
- Redeploy Subsquid poller with volume-ordered pagination to populate events for marquee markets
- Fix `logger.info(".2f")` typo and add metrics export for `_poll_cycle`
- Integrate streamer price updates with TP/SL monitor to close the loop on position refresh
- **Copy trading**: Connect DipDup/Subsquid indexer webhook to `/api/v1/webhooks/copy_trade` endpoint
- **Redis**: Add PubSub health status to `/health` endpoints for monitoring
- **Watched addresses**: Seed production data for copy trading leaders

## Suggested Next Actions
1. **Redeploy poller stack** from `apps/subsquid-silo-tests/data-ingestion` and verify Super Bowl events filled
2. **Wire streamer health metrics** into monitoring stack to detect stale subscriptions
3. **Seed watched addresses** in Supabase + trigger `WatchedAddressesManager.refresh_cache()` to exercise copy listener
4. **Define DipDup webhook contract** and map to `CopyTradingListener` to close ingestion loop
