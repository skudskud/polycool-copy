# Analyse Complète du Copy Trading Flow

**Date:** 2025-01-27
**Status:** Architecture complète, intégration partielle

---

## 🎯 Vue d'Ensemble

Le système de copy trading utilise un pipeline en 3 étapes:
1. **Indexer Subsquid** (TypeScript) → Indexe les transactions on-chain
2. **Webhook + Redis PubSub** → Notifie instantanément les trades
3. **Copy Trading Listener** (Python) → Exécute les copy trades

---

## 📊 Architecture Complète

```
┌─────────────────────────────────────────────────────────────────┐
│                    POLYGON BLOCKCHAIN                           │
│  Conditional Tokens Transfers (TransferSingle/TransferBatch)  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              INDEXER SUBSQUID (TypeScript)                       │
│  Location: apps/subsquid-silo-tests/indexer-ts/                 │
│                                                                  │
│  ✅ ÉTAPE 1: Filtrage des addresses watchées                   │
│     - Fetches: GET /subsquid/watched_addresses (BOT_API_URL)     │
│     - Refresh: Toutes les 1 minute                             │
│     - Cache: Set<string> pour O(1) lookup                       │
│                                                                  │
│  ✅ ÉTAPE 2: Indexation des transactions                       │
│     - Écoute: TransferSingle + TransferBatch events            │
│     - Parse: token_id → market_id + outcome                      │
│     - USDC tracking: Capture exact trade amounts                │
│     - Calcul prix: USDC amount / token amount                   │
│                                                                  │
│  ✅ ÉTAPE 3: Enregistrement DB                                 │
│     - Table: subsquid_user_transactions                         │
│     - Fields: tx_id, user_address, market_id, outcome,          │
│               tx_type (BUY/SELL), amount, price,                │
│               amount_in_usdc, tx_hash, timestamp                │
│                                                                  │
│  ✅ ÉTAPE 4: Webhook Notification                               │
│     - Envoie: POST /wh/copy_trade (COPY_TRADING_WEBHOOK_URL)   │
│     - Payload: Toutes les transactions watchées                │
│     - Non-blocking: Erreurs loggées mais n'arrêtent pas l'index │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼ HTTP POST
┌─────────────────────────────────────────────────────────────────┐
│         WEBHOOK RECEIVER (Python - FastAPI)                     │
│  Location: telegram_bot/api/v1/webhooks/copy_trade.py           │
│                                                                  │
│  ✅ ÉTAPE 1: Validation                                         │
│     - Vérifie: X-Webhook-Secret header                          │
│     - Check: Address watchée (cache lookup)                     │
│                                                                  │
│  ✅ ÉTAPE 2: Storage DB (async, non-blocking)                  │
│     - Table: trades                                             │
│     - Deduplication: Par tx_hash                                │
│                                                                  │
│  ✅ ÉTAPE 3: Redis PubSub Broadcast (async, non-blocking)      │
│     - Channel: copy_trade:{user_address.lower()}               │
│     - Message: JSON avec tx_id, user_address, market_id,       │
│                outcome, tx_type, amount, price, taking_amount,  │
│                tx_hash, timestamp, address_type                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼ Redis PubSub
┌─────────────────────────────────────────────────────────────────┐
│         COPY TRADING LISTENER (Python)                          │
│  Location: data_ingestion/indexer/copy_trading_listener.py      │
│                                                                  │
│  ✅ ÉTAPE 1: Subscription Redis                                 │
│     - Pattern: copy_trade:*                                    │
│     - Callback: _handle_trade_message()                        │
│                                                                  │
│  ✅ ÉTAPE 2: Deduplication                                     │
│     - Cache: tx_id → timestamp (5min TTL)                       │
│     - Skip: Trades déjà traités                                 │
│                                                                  │
│  ✅ ÉTAPE 3: Validation                                        │
│     - Check: Address watchée                                    │
│     - Check: WatchedAddress.is_active == True                   │
│     - Get: CopyTradingAllocation actives                       │
│                                                                  │
│  ✅ ÉTAPE 4: Market Resolution                                 │
│     Priority 1: position_id → clob_token_ids lookup             │
│     Priority 2: market_id + outcome (fallback)                │
│     Cache: 5min TTL pour performance                            │
│                                                                  │
│  ✅ ÉTAPE 5: Copy Trade Execution                              │
│     - Calculate: Copy amount (proportional/fixed_amount)        │
│     - Execute: trade_service.execute_market_order()            │
│     - Update: allocation stats (total_copied_trades, etc.)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔍 Détails Techniques par Composant

### 1. Indexer Subsquid (`indexer-ts/`)

#### Configuration Requise

```bash
# Variables d'environnement critiques
BOT_API_URL=https://your-bot-api.com          # Pour fetch watched addresses
COPY_TRADING_WEBHOOK_URL=https://.../wh/copy_trade  # Pour notifier les trades
WEBHOOK_SECRET=your-secret                     # Sécurité webhook
DATABASE_URL=postgresql://...                  # Supabase connection
RPC_POLYGON_HTTP=https://...                  # Polygon RPC endpoint
```

#### Flow d'Indexation

```typescript
// 1. Initialisation (main.ts)
watchedAddressManager.init(db)  // Fetch addresses watchées
processor.run(db, async (ctx) => {
  // 2. Pour chaque block
  for (const block of ctx.blocks) {
    // 2a. Accumule USDC transfers (pour calcul prix exact)
    // 2b. Parse TransferSingle/Batch events
    // 2c. Filtre: watchedAddressManager.isWatched(address)
    // 2d. Calcule prix: USDC amount / token amount
    // 2e. Crée UserTransaction
  }

  // 3. Batch upsert to DB
  await ctx.store.upsert(transactions)

  // 4. Webhook notification (non-blocking)
  await notifyNewTrades(transactions)
}
```

#### Points Clés

- ✅ **Filtrage actif**: Ne traite QUE les addresses watchées (réduit charge DB)
- ✅ **Prix calculé**: USDC amount / token amount (pas besoin d'enrichment)
- ✅ **Webhook non-blocking**: Erreurs n'arrêtent pas l'indexation
- ⚠️ **Refresh watched addresses**: Toutes les 1 minute (configurable)

---

### 2. Webhook Receiver (`telegram_bot/api/v1/webhooks/copy_trade.py`)

#### Endpoint

```
POST /wh/copy_trade
Headers:
  X-Webhook-Secret: <secret>
Body:
  {
    "tx_id": "...",
    "user_address": "0x...",
    "position_id": "...",
    "market_id": "...",
    "outcome": 0|1,
    "tx_type": "BUY"|"SELL",
    "amount": "...",
    "price": "...",
    "taking_amount": "...",  // Total USDC
    "tx_hash": "...",
    "timestamp": "..."
  }
```

#### Flow

```python
async def receive_copy_trade_webhook(event, request):
    # 1. Verify secret
    verify_webhook_secret(request)

    # 2. Fast check: Is address watched?
    address_info = await watched_manager.is_watched_address(event.user_address)
    if not address_info['is_watched']:
        return {"status": "ignored"}

    # 3. Store in DB (async, non-blocking)
    asyncio.create_task(_store_trade_in_db(...))

    # 4. Publish to Redis (async, non-blocking)
    asyncio.create_task(_publish_to_redis(...))

    # 5. Return 200 OK immediately
    return {"status": "ok"}
```

#### Points Clés

- ✅ **Réponse rapide**: 200 OK immédiat, traitement en background
- ✅ **Deduplication**: Check tx_hash avant insert DB
- ✅ **Redis PubSub**: Channel `copy_trade:{user_address.lower()}`

---

### 3. Copy Trading Listener (`data_ingestion/indexer/copy_trading_listener.py`)

#### Initialisation

```python
listener = CopyTradingListener()
await listener.start()  # Subscribe to copy_trade:*
```

#### Flow de Traitement

```python
async def _handle_trade_message(channel, data):
    # 1. Parse JSON
    trade_data = json.loads(data)

    # 2. Deduplication
    if self._is_duplicate(tx_id):
        return

    # 3. Validation
    address_info = await watched_manager.is_watched_address(user_address)
    watched_address = await get_watched_address(user_address)

    # 4. Get active allocations
    allocations = await get_active_allocations(watched_address.id)

    # 5. Execute copy trades (parallel)
    for allocation in allocations:
        await self._execute_copy_trade(allocation, trade_data)
```

#### Calcul du Montant de Copy

```python
def _calculate_copy_amount(allocation, leader_amount_usdc, follower_balance, mode):
    # Priority: Use taking_amount (amount_usdc) directly
    if leader_amount_usdc:
        leader_amount = leader_amount_usdc
    else:
        # Fallback: amount * price
        leader_amount = amount_real * price

    # Max allocation based on allocation_type
    if allocation.allocation_type == "percentage":
        max_allocation = follower_balance * (allocation.allocation_value / 100.0)
    else:
        max_allocation = min(allocation.allocation_value, follower_balance)

    # Copy amount based on mode
    if mode == "proportional":
        copy_amount = min(leader_amount, max_allocation)
    else:  # fixed_amount
        copy_amount = min(allocation.allocation_value, max_allocation)

    return min(copy_amount, follower_balance)
```

#### Points Clés

- ✅ **Deduplication**: Cache tx_id (5min TTL)
- ✅ **Market Resolution**: position_id → clob_token_ids lookup (cache 5min)
- ✅ **Parallel Execution**: Tous les followers en parallèle
- ✅ **Error Handling**: Continue même si certains échouent

---

## 🔗 Intégration Webhook + Redis PubSub

### Status Actuel

| Composant | Status | Notes |
|-----------|--------|-------|
| Indexer → Webhook | ✅ **CONNECTÉ** | `COPY_TRADING_WEBHOOK_URL` configuré |
| Webhook → Redis | ✅ **CONNECTÉ** | Publie sur `copy_trade:*` |
| Redis → Listener | ✅ **CONNECTÉ** | Subscribe `copy_trade:*` |
| Listener → Trade Execution | ✅ **CONNECTÉ** | Utilise `trade_service.execute_market_order()` |

### Vérification de la Connexion

#### 1. Indexer envoie bien les webhooks?

```bash
# Check logs indexer
# Devrait voir:
[WEBHOOK] ✅ Sent for 0xabc... (BUY, 150ms)
```

#### 2. Webhook reçoit et publie Redis?

```bash
# Check logs webhook receiver
# Devrait voir:
🎣 [WEBHOOK] Received BUY trade webhook for 0xabc...
📤 [WEBHOOK_REDIS] Published BUY to copy_trade:0xabc..., subscribers: 1
```

#### 3. Listener reçoit et traite?

```bash
# Check logs listener
# Devrait voir:
🚀 INSTANT COPY: BUY trade from 0xabc... (tx: ...)
🔄 Copying trade to 2 followers
✅ Copied BUY trade: $50.00 for user 123456
```

---

## 🧪 Comment Tester

### Test 1: Vérifier l'Indexer

```bash
# 1. Vérifier que l'indexer tourne
cd apps/subsquid-silo-tests/indexer-ts
npm run build
npm start

# 2. Vérifier les logs
# Devrait voir:
[WATCHED] ✅ Refreshed: X addresses (Y leaders, Z smart wallets)
✅ Saved N watched transactions (M with price)

# 3. Vérifier DB
# Dans Supabase:
SELECT COUNT(*) FROM subsquid_user_transactions;
SELECT * FROM subsquid_user_transactions
WHERE timestamp > NOW() - INTERVAL '1 hour'
ORDER BY timestamp DESC LIMIT 10;
```

### Test 2: Vérifier le Webhook

```bash
# 1. Tester manuellement le webhook
curl -X POST https://your-bot-api.com/wh/copy_trade \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your-secret" \
  -d '{
    "tx_id": "test_123",
    "user_address": "0xYOUR_WATCHED_ADDRESS",
    "position_id": "123456",
    "market_id": "test_market",
    "outcome": 1,
    "tx_type": "BUY",
    "amount": "1000000",
    "price": "0.5",
    "taking_amount": "50.0",
    "tx_hash": "0xtest",
    "timestamp": "2025-01-27T12:00:00Z"
  }'

# 2. Vérifier logs
# Devrait voir:
✅ [WEBHOOK] Processed BUY trade for 0x...
📤 [WEBHOOK_REDIS] Published BUY to copy_trade:0x..., subscribers: 1
```

### Test 3: Vérifier Redis PubSub

```bash
# 1. Connecter à Redis
redis-cli

# 2. Subscribe au channel
PSUBSCRIBE copy_trade:*

# 3. Dans un autre terminal, publier un message de test
PUBLISH copy_trade:0xtest "{\"tx_id\":\"test\",\"user_address\":\"0xtest\",\"tx_type\":\"BUY\"}"

# 4. Devrait voir le message dans le premier terminal
```

### Test 4: Test End-to-End

```bash
# 1. Créer une allocation copy trading via bot
# /copy_trading → Add Leader → Enter address → Set allocation

# 2. Faire un trade avec l'address watchée sur Polymarket

# 3. Vérifier les logs dans l'ordre:
#    a. Indexer: ✅ Saved transaction
#    b. Webhook: ✅ Processed trade
#    c. Listener: 🚀 INSTANT COPY
#    d. Listener: ✅ Copied trade

# 4. Vérifier DB:
SELECT * FROM trades WHERE tx_hash = '...';
SELECT * FROM positions WHERE user_id = ...;
```

---

## ⚠️ Ce Qui Reste à Faire

### 1. Configuration Environnement

#### Indexer (`indexer-ts/`)

```bash
# À configurer dans Railway/Deployment:
BOT_API_URL=https://your-bot-api.com/api/v1
COPY_TRADING_WEBHOOK_URL=https://your-bot-api.com/api/v1/wh/copy_trade
WEBHOOK_SECRET=your-secret-here
DATABASE_URL=postgresql://...
RPC_POLYGON_HTTP=https://polygon-mainnet.g.alchemy.com/v2/...
```

#### Bot (`polycool-rebuild/`)

```bash
# À configurer:
REDIS_URL=redis://...
WEBHOOK_SECRET=your-secret-here  # Même que indexer
```

### 2. Démarrage du Listener

Le listener est démarré automatiquement au démarrage du bot:

```87:93:polycool/polycool-rebuild/telegram_bot/main.py
    # Start Copy Trading Listener (for instant copy trading via Redis PubSub)
    try:
        from data_ingestion.indexer.copy_trading_listener import get_copy_trading_listener
        copy_trading_listener = get_copy_trading_listener()
        app.state.copy_trading_listener = copy_trading_listener
        await copy_trading_listener.start()
        logger.info("✅ Copy Trading Listener started")
```

**Status:** ✅ **CONFIRMÉ** - Le listener démarre automatiquement dans `telegram_bot/main.py`

### 3. Endpoint Watched Addresses

Le bot expose l'endpoint pour que l'indexer fetch les addresses:

```33:99:polycool/polycool-rebuild/telegram_bot/api/v1/subsquid/__init__.py
@router.get("/watched_addresses", response_model=WatchedAddressesResponse)
async def get_watched_addresses() -> WatchedAddressesResponse:
    """
    Return all addresses to watch for copy trading (from Redis cache)
    Ultra-fast response (<100ms) even with 10K addresses

    Used by indexer-ts to filter transactions at source.
    Format compatible with indexer-ts watched-addresses.ts

    Returns:
        {
            "addresses": [
                {"address": "0x...", "type": "external_leader", "user_id": null},
                {"address": "0x...", "type": "smart_wallet", "user_id": null}
            ],
            "total": 42,
            "timestamp": "2025-11-06T17:30:00Z",
            "cached": true
        }
    """
```

**Status:** ✅ **CONFIRMÉ** - L'endpoint existe à `/api/v1/subsquid/watched_addresses`

### 4. Tests de Charge

- [ ] Tester avec 10+ addresses watchées
- [ ] Tester avec 100+ followers
- [ ] Vérifier latence (< 10s de l'indexer au copy trade)
- [ ] Vérifier déduplication (pas de doubles trades)

### 5. Monitoring & Alertes

- [ ] Métriques: Nombre de trades copiés/jour
- [ ] Alertes: Si listener down > 5min
- [ ] Logs: Structured logging pour debugging

---

## 📈 Métriques de Performance

### Latence Attendue

| Étape | Latence |
|-------|---------|
| Indexer détecte transaction | ~50 blocks (~2min) |
| Webhook notification | < 1s |
| Redis PubSub | < 100ms |
| Listener traitement | < 5s |
| **TOTAL** | **~2-3 minutes** |

### Throughput

- Indexer: ~1000 transactions/block (filtrage réduit à ~3-10 watchées)
- Webhook: ~100 req/s (suffisant)
- Redis: ~10k msg/s (suffisant)
- Listener: ~10 copy trades/s (suffisant pour start)

---

## 🐛 Troubleshooting

### Problème: Indexer n'envoie pas de webhooks

**Check:**
1. `COPY_TRADING_WEBHOOK_URL` configuré?
2. `WEBHOOK_SECRET` configuré?
3. Logs indexer montrent des erreurs webhook?

**Solution:**
```bash
# Vérifier logs
[WEBHOOK] ❌ Failed for tx_id: ... (timeout/connection error)
```

### Problème: Webhook reçoit mais ne publie pas Redis

**Check:**
1. `REDIS_URL` configuré dans bot?
2. Redis accessible?
3. Logs webhook montrent erreur Redis?

**Solution:**
```bash
# Vérifier logs
❌ [WEBHOOK_REDIS] Redis publish failed: ...
```

### Problème: Listener ne reçoit pas de messages

**Check:**
1. Listener démarré? (`listener.running == True`)
2. Subscribe actif? (`copy_trade:*` pattern)
3. Redis PubSub fonctionne?

**Solution:**
```python
# Vérifier stats
stats = listener.get_stats()
print(stats)  # Devrait montrer running=True
```

### Problème: Copy trades ne s'exécutent pas

**Check:**
1. Allocation active? (`is_active == True`)
2. User ready? (`user.stage == "ready"`)
3. Balance suffisante?
4. Market résolu? (position_id → market lookup)

**Solution:**
```python
# Vérifier logs listener
⏭️ User 123 not ready for copy trading
⏭️ Copy amount is 0 for user 123
⚠️ Could not resolve market/token for trade ...
```

---

## ✅ Checklist de Déploiement

- [ ] Indexer configuré avec `BOT_API_URL` et `COPY_TRADING_WEBHOOK_URL`
- [ ] Bot expose `/api/v1/subsquid/watched_addresses`
- [ ] Bot expose `/api/v1/wh/copy_trade` avec secret
- [ ] Redis accessible depuis bot et indexer
- [ ] Listener démarré au startup du bot
- [ ] Tests end-to-end passent
- [ ] Monitoring configuré
- [ ] Documentation à jour

---

## 📚 Références

- Indexer: `apps/subsquid-silo-tests/indexer-ts/`
- Webhook: `telegram_bot/api/v1/webhooks/copy_trade.py`
- Listener: `data_ingestion/indexer/copy_trading_listener.py`
- Service: `core/services/copy_trading/service.py`
- Handlers: `telegram_bot/bot/handlers/copy_trading/`
