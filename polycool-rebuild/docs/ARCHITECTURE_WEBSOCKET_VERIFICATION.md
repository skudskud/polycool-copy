# 📊 Architecture WebSocket & Vérification Production

## 🏗️ Architecture des Micro-Services

### Services de Production

1. **Service Indexer** (`data_ingestion/indexer/`)
   - Récupère les transactions des leaders (copy trading) et smart traders
   - Via `watched_addresses` table
   - Écoute les événements blockchain via `copy_trading_listener`

2. **Service Bot** (`telegram_bot/`)
   - `SKIP_DB=true` → Pas d'accès direct à la DB
   - Utilise `APIClient` pour toutes les opérations DB
   - Handlers Telegram intégrés avec calls API

3. **Service API** (`api/`)
   - Accès DB complet
   - Endpoints REST pour le bot
   - Gestion des positions, markets, users

4. **Service Workers** (`workers.py`)
   - Data ingestion: Poller (60s), WebSocket (temps réel)
   - TP/SL Monitor
   - Copy Trading Listener
   - Watched Addresses Sync

5. **Cache Manager Redis**
   - Cache des prix, markets, positions
   - Invalidation automatique lors des updates

---

## 🔌 Architecture WebSocket

### Flux Complet

```
┌─────────────────┐
│  Trade Executed │ (via CLOB Service)
│  (User buys)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ TradeService    │ → websocket_manager.on_trade_executed()
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│WebSocketManager │ → subscription_manager.on_trade_executed()
│  (Centralized)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│SubscriptionMgr  │ → websocket_client.subscribe_markets(token_ids)
│ (Smart tracking)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│WebSocketClient  │ → Connect to Polymarket WS
│ (Polymarket WS) │ → Subscribe to token_ids
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Price Update    │ (from Polymarket)
│ Message Received│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│MarketUpdater    │ → handle_price_update()
│                 │ → _update_market_prices() → Update markets table
│                 │ → _schedule_position_updates() → Debounce
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│_update_positions│ → get_positions_by_market()
│_for_market()    │ → batch_update_positions_prices()
│                 │ → Invalidate cache
│                 │ → Check TP/SL triggers
└─────────────────┘
```

### Composants Clés

#### 1. **StreamerService** (`data_ingestion/streamer/streamer.py`)
- Orchestre WebSocket client, subscription manager, market updater
- Démarre seulement si positions actives existent
- Auto-start après premier trade

#### 2. **SubscriptionManager** (`data_ingestion/streamer/subscription_manager.py`)
- Gère les subscriptions intelligentes
- Subscribe uniquement aux marchés avec positions actives
- Auto-subscribe après trade
- Auto-unsubscribe quand position fermée
- Cleanup périodique (5min)

#### 3. **MarketUpdater** (`data_ingestion/streamer/market_updater/market_updater.py`)
- Met à jour `markets.outcome_prices` (source: 'ws')
- Met à jour `positions.current_price` et P&L automatiquement
- Debouncing: 1 seconde avant update positions
- Rate limiting: max 10 positions/seconde
- Vérifie TP/SL triggers immédiatement (< 100ms latency)

#### 4. **WebSocketClient** (`data_ingestion/streamer/websocket_client/websocket_client.py`)
- Connexion WebSocket Polymarket
- Ping/Pong toutes les 10 secondes
- Auto-reconnect avec backoff exponentiel
- Gestion des erreurs et reconnection

---

## ✅ Intégration Handlers ↔ API

### Pattern SKIP_DB

Tous les handlers vérifient `SKIP_DB`:

```python
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

if SKIP_DB:
    from core.services.api_client import get_api_client
    api_client = get_api_client()
    # Appel API
    positions = await api_client.get_user_positions(user_id)
else:
    # Accès DB direct
    positions = await position_service.get_active_positions(user_id)
```

### Handlers Intégrés

1. **Positions Handler** (`telegram_bot/bot/handlers/positions_handler.py`)
   - `/positions` → `api_client.get_user_positions()`
   - Refresh → `api_client.sync_positions()`

2. **Sell Handler** (`telegram_bot/bot/handlers/positions/sell_handler.py`)
   - Sell → `api_client.close_position()` ou `position_service.close_position()`
   - Notifie `websocket_manager.unsubscribe_user_from_market()`

3. **TP/SL Handler** (`telegram_bot/bot/handlers/positions/tpsl_handler.py`)
   - Set TP/SL → `api_client.update_position_tpsl()` ou `position_service.update_position_tpsl()`

4. **Trade Handler** (`core/services/trading/trade_service.py`)
   - Après trade → `websocket_manager.on_trade_executed()`
   - Crée position → `position_service.create_position()`

---

## 🔍 Vérification WebSocket en Production

### 1. Vérifier que le WebSocket Stream

#### Via Logs Workers

```bash
# Logs du service workers
railway logs --service workers

# Chercher ces messages:
✅ WebSocket connected
📡 Subscribed to X token IDs from Y markets
✅ Updated prices for market [market_id]
✅ Updated N positions for market [market_id]
```

#### Via Database Supabase

```sql
-- Vérifier que les prix viennent du WebSocket (source = 'ws')
SELECT
    id,
    source,
    outcome_prices,
    last_mid_price,
    updated_at
FROM markets
WHERE source = 'ws'
ORDER BY updated_at DESC
LIMIT 10;

-- Vérifier que les positions sont mises à jour
SELECT
    id,
    user_id,
    market_id,
    outcome,
    current_price,
    entry_price,
    pnl_amount,
    pnl_percentage,
    updated_at
FROM positions
WHERE status = 'active'
ORDER BY updated_at DESC
LIMIT 10;

-- Vérifier la fréquence des updates
SELECT
    market_id,
    COUNT(*) as update_count,
    MIN(updated_at) as first_update,
    MAX(updated_at) as last_update
FROM positions
WHERE status = 'active'
  AND updated_at > NOW() - INTERVAL '1 hour'
GROUP BY market_id
ORDER BY update_count DESC;
```

#### Via API Health Check

```python
# Endpoint health check (si disponible)
GET /api/v1/health/websocket

# Devrait retourner:
{
    "websocket_manager": "healthy",
    "streamer_connected": true,
    "websocket_connected": true,
    "active_subscriptions": 5,
    "streamer_stats": {
        "enabled": true,
        "running": true,
        "websocket": {
            "connected": true,
            "message_count": 1234,
            "subscribed_token_ids": 10
        },
        "market_updater": {
            "update_count": 567
        }
    }
}
```

### 2. Vérifier les Subscriptions

```sql
-- Vérifier les marchés avec positions actives
SELECT DISTINCT market_id
FROM positions
WHERE status = 'active';

-- Vérifier les token_ids pour ces marchés
SELECT
    m.id as market_id,
    m.clob_token_ids,
    COUNT(p.id) as active_positions
FROM markets m
JOIN positions p ON p.market_id = m.id
WHERE p.status = 'active'
GROUP BY m.id, m.clob_token_ids;
```

### 3. Test Manuel

1. **Créer une position**
   - Via bot Telegram: `/markets` → Choisir marché → BUY
   - Vérifier logs: `📡 Auto-subscribed to market [market_id]`

2. **Attendre update prix**
   - Vérifier dans DB que `markets.source = 'ws'`
   - Vérifier que `positions.current_price` change
   - Vérifier que `positions.pnl_amount` est recalculé

3. **Vérifier TP/SL**
   - Set TP/SL sur une position
   - Attendre que le prix atteigne le TP/SL
   - Vérifier que la position est vendue automatiquement

4. **Fermer position**
   - Via bot: `/positions` → Sell
   - Vérifier logs: `🚪 Auto-unsubscribed from market [market_id]`

### 4. Monitoring Métriques

#### Métriques Clés

- **WebSocket Connection**: Doit être stable (1 connexion persistante)
- **Message Rate**: 1-10 messages/minute selon activité
- **Position Updates**: Corrélé avec nombre de positions actives
- **Error Rate**: < 1% des messages
- **Latence**: < 100ms pour price updates, < 1s pour P&L updates

#### Logs à Monitorer

```
✅ WebSocket connected              # Connexion réussie
🏓 Sent PING to maintain connection  # Ping/pong fonctionne
📡 Subscribed to X markets          # Subscription réussie
✅ Updated prices for market XXX    # Prix mis à jour
✅ Updated N positions for market   # Positions mises à jour
🚪 Unsubscribed from X markets      # Unsubscription réussie
⚠️ WebSocket connection closed      # Reconnexion en cours
```

---

## 🐛 Problèmes Potentiels & Solutions

### Problème 1: WebSocket ne démarre pas

**Symptômes:**
- Pas de logs "WebSocket connected"
- `STREAMER_ENABLED=false` ou non configuré

**Solution:**
```bash
# Vérifier variable d'environnement
railway variables --service workers
# STREAMER_ENABLED doit être "true"
```

### Problème 2: Pas de subscription après trade

**Symptômes:**
- Trade exécuté mais pas de subscription
- Logs: `⚠️ No token IDs found for market [market_id]`

**Solution:**
```sql
-- Vérifier que clob_token_ids est bien rempli
SELECT id, clob_token_ids
FROM markets
WHERE id = '[market_id]';

-- Si NULL ou vide, le poller doit le remplir
```

### Problème 3: Positions ne se mettent pas à jour

**Symptômes:**
- Prix dans `markets` changent mais `positions.current_price` ne change pas

**Solution:**
- Vérifier que `MarketUpdater._update_positions_for_market()` est appelé
- Vérifier logs: `✅ Updated N positions for market [market_id]`
- Vérifier debouncing: attendre 1 seconde après price change

### Problème 4: Cache non invalidé

**Symptômes:**
- Positions affichées avec anciens prix dans le bot

**Solution:**
- Vérifier que `cache_manager.invalidate(f"positions:{user_id}")` est appelé
- Vérifier connexion Redis

---

## 📋 Checklist Production

- [ ] **Configuration**
  - [ ] `STREAMER_ENABLED=true` dans workers
  - [ ] `CLOB_WSS_URL` configuré correctement
  - [ ] Redis accessible depuis workers

- [ ] **Database**
  - [ ] Tables `markets` et `positions` existent
  - [ ] `markets.clob_token_ids` rempli pour marchés actifs
  - [ ] RLS activé sur `positions` table

- [ ] **Services**
  - [ ] Workers service démarré
  - [ ] WebSocket connecté (vérifier logs)
  - [ ] Subscriptions actives (vérifier logs)

- [ ] **Intégration**
  - [ ] Trade → Subscription fonctionne
  - [ ] Price updates → Position updates fonctionne
  - [ ] TP/SL triggers fonctionne
  - [ ] Unsubscribe après fermeture position fonctionne

- [ ] **Monitoring**
  - [ ] Logs structurés en place
  - [ ] Métriques collectées
  - [ ] Alertes configurées

---

## 🎯 Conclusion

Le WebSocket est **bien intégré** avec:
- ✅ Architecture micro-services respectée (SKIP_DB pattern)
- ✅ Handlers ↔ API calls fonctionnels
- ✅ WebSocket streaming des prix en temps réel
- ✅ Mise à jour automatique des positions
- ✅ TP/SL triggers < 100ms
- ✅ Subscription intelligente (seulement positions actives)

**Pour vérifier en production:**
1. Vérifier logs workers pour connexion WebSocket
2. Vérifier DB pour `markets.source = 'ws'`
3. Vérifier que `positions.current_price` et `pnl_amount` changent
4. Tester avec un trade réel et observer les updates
