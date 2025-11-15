# Bot Feature Audit — Nov 8, 2025

## Executive Summary
- **✅ Verified**: Bridge workflow, wallet generation + encryption, buy/sell execution pipeline, copy trading API + Telegram handlers, Redis PubSub connected at startup
- **⚠️ Pending Validation**: TP/SL automation wired but needs end-to-end tests, smart trading endpoints stubbed
- **✅ Security**: RLS enabled on all 6 Supabase tables with proper policies
- **Structural Warning**: `bridge_service.py` currently exceeds 700 lines; should be split before further expansion

## Completed & Verified Paths

### Bridge (SOL → POL)
- `BridgeService` orchestrates Jupiter swap, deBridge transfer, and Polygon settlement with detailed status callbacks
- Private keys decrypted via `EncryptionService`; approvals/api keys injected via service locators
- Needs refactor into submodules (swap, bridge, settlement) to comply with 700-line guideline

```26:139:polycool/polycool-rebuild/core/services/bridge/bridge_service.py
class BridgeService:
    """Main bridge service orchestrating SOL → USDC → POL workflow"""

    def __init__(self):
        self.jupiter_client = get_jupiter_client()
        self.debridge_client = get_debridge_client()
        self.solana_builder = SolanaTransactionBuilder()
        self.quickswap_client = get_quickswap_client()
        self.approval_service = get_approval_service()
        self.api_key_manager = get_api_key_manager()
        self.user_service = UserService()
```

```242:344:polycool/polycool-rebuild/core/services/bridge/bridge_service.py
            user = await self.user_service.get_by_telegram_id(telegram_user_id)
            if not user:
                return {'success': False, 'error': 'user_not_found'}

            if not user.solana_address or not user.solana_private_key:
                return {'success': False, 'error': 'wallet_not_found'}

            solana_private_key = encryption_service.decrypt_private_key(user.solana_private_key)
            if not solana_private_key:
                return {'success': False, 'error': 'decryption_failed'}

            solana_address = user.solana_address
            polygon_address = user.polygon_address

            balance = await self.get_sol_balance(solana_address)
            if balance < BridgeConfig.MIN_SOL_FOR_BRIDGE:
                return {'success': False, 'error': 'insufficient_sol', 'balance': balance}
```

### Wallet Creation & Encryption
- Polygon/Solana wallets generated and encrypted prior to persistence; decryption helpers provided for runtime usage

```28:89:polycool/polycool-rebuild/core/services/wallet/wallet_service.py
    def generate_user_wallets(self) -> dict:
        try:
            polygon_address, polygon_private_key = self.generate_polygon_wallet()
            encrypted_polygon_key = encryption_service.encrypt_private_key(polygon_private_key)

            solana_address, solana_private_key = self.generate_solana_wallet()
            encrypted_solana_key = encryption_service.encrypt_private_key(solana_private_key)

            return {
                "polygon_address": polygon_address,
                "polygon_private_key": encrypted_polygon_key,
                "solana_address": solana_address,
                "solana_private_key": encrypted_solana_key,
            }
```

```16:88:polycool/polycool-rebuild/core/services/encryption/encryption_service.py
class EncryptionService:
    def __init__(self):
        key = settings.security.encryption_key
        if len(key) != 32:
            raise ValueError("Encryption key must be exactly 32 bytes for AES-256")
        self.key = key.encode('utf-8') if isinstance(key, str) else key
        self.aesgcm = AESGCM(self.key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)
        plaintext_bytes = plaintext.encode('utf-8')
        ciphertext = self.aesgcm.encrypt(nonce, plaintext_bytes, None)
        encrypted_data = nonce + ciphertext
        return base64.b64encode(encrypted_data).decode('utf-8')
```

### Buy & Sell Flow
- `TradeService.execute_market_order` validates wallet readiness, checks balances, resolves token IDs, and records positions
- Dry-run mode supports automated tests; fallback JSON parsing for `clob_token_ids` remains risky but functional

```56:147:polycool/polycool-rebuild/core/services/trading/trade_service.py
    async def execute_market_order(
        self,
        user_id: int,
        market_id: str,
        outcome: str,
        amount_usd: float,
        order_type: str = 'FOK',
        dry_run: bool = False
    ) -> Dict[str, Any]:
        try:
            logger.info(f"🎯 Executing {order_type} order: user={user_id}, market={market_id}")

            is_dry_run = dry_run or self._is_test_mode()
            if is_dry_run:
                return {'status': 'executed', 'trade': {'dry_run': True}}

            user = await user_service.get_by_telegram_id(user_id)
            if not user:
                return {'status': 'failed', 'error': 'User not found'}

            wallet_ready, status_msg = await self._check_wallet_ready(user)
            if not wallet_ready:
                return {'status': 'failed', 'error': f'Wallet not ready: {status_msg}'}

            balance_check = await self._check_balance(user.polygon_address, amount_usd)
            if not balance_check['sufficient']:
                return {'status': 'failed', 'error': balance_check['message']}

            market_data = await self._get_market_data(market_id)
            if not market_data:
                return {'status': 'failed', 'error': 'Market not found or inactive'}
```

## Pending / Not Validated

### TP/SL Automation — ⚠️ Not Checked
- Monitor service implemented with batch queries, hybrid polling/WebSocket triggers, and sell execution via CLOB
- Requires integration tests + wiring to streamer notifications before enabling

```35:151:polycool/polycool-rebuild/core/services/trading/tpsl_monitor.py
class TPSLMonitor:
    def __init__(self, check_interval: int = 10):
        self.check_interval = check_interval
        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None
        self.max_positions_per_cycle = 100

    async def _check_all_active_orders(self) -> None:
        async with get_db() as db:
            result = await db.execute(
                select(Position)
                .where(
                    and_(
                        Position.status == "active",
                        or_(
                            Position.take_profit_price.isnot(None),
                            Position.stop_loss_price.isnot(None)
                        )
                    )
                )
                .limit(self.max_positions_per_cycle)
            )
            positions = list(result.scalars().all())
```

### Smart Trading — ❌ Not Implemented
- FastAPI endpoint returns placeholder; no service layer or ingestion wiring

```8:11:polycool/polycool-rebuild/telegram_bot/api/v1/smart_trading.py
@router.get("/")
async def get_smart_trades():
    """Get smart trading recommendations"""
    return {"trades": [], "message": "Smart trading endpoint - to be implemented"}
```

### Copy Trading — ✅ Functionally Complete
- **Backend**: `CopyTradingService` with leader resolution, allocation management, stats tracking
- **Telegram Handlers**: Complete conversation flow (/copy_trading → search leader → confirm → budget allocation)
- **API REST**: Full endpoints implemented (GET /leaders, POST /subscribe, PUT /allocation, DELETE /subscription, GET /stats)
- **Webhook**: `/api/v1/webhooks/copy_trade` receives indexer events → stores in DB → publishes to Redis PubSub
- **Listener**: `CopyTradingListener` consumes Redis events and executes copy trades
- **Remaining**: Seed `watched_addresses` table with real leader data + connect DipDup indexer

### Redis Pub/Sub — ✅ Connected at Startup
- **Service**: Async Redis client with auto-reconnect, exponential backoff, health checks
- **Startup Hook**: Connected in `telegram_bot/main.py` lifespan manager
- **Usage**: Copy trading webhook publishes to `copy_trade:{address}` channels
- **Listeners**: `CopyTradingListener` subscribes to `copy_trade:*` pattern
- **Graceful Shutdown**: Disconnects cleanly on app shutdown
- **Remaining**: Add to health check endpoints for monitoring

## Actions & Recommendations
- **Split `BridgeService`** into cohesive modules (`swap_runner.py`, `bridge_runner.py`, `settlement_tracker.py`) before further edits
- **Add integration tests** for TP/SL monitor triggered off streamer updates (simulate market hitting TP/SL targets)
- **Implement smart trading backend**: define data contract, reuse Supabase views, secure caching layer
- **Seed `watched_addresses`**: Populate with real leader data for copy trading production deployment
- **Connect DipDup indexer**: Wire up webhook from indexer-ts to `/api/v1/webhooks/copy_trade`
- **Add Redis health checks**: Include PubSub status in `/health` endpoints
