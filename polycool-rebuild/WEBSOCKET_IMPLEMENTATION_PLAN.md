# 🚀 PLAN DE FINALISATION - WebSocket Polymarket (Pré-Prod)

**Date:** Novembre 2025
**Projet:** xxzdlbwfyetaxcmodiec (polycoolv3)
**Base:** Architecture existante + Doc Polymarket WebSocket
**Durée Estimée:** 4-5 jours

---

## 🎯 OBJECTIF

Finaliser l'implémentation WebSocket pour permettre le tracking temps réel des marchés avec positions actives, selon les spécifications du MASTER PLAN Phase 7.

### ✅ RÉSULTAT ATTENDU
- ✅ WebSocket connecté à Polymarket CLOB
- ✅ Subscription sélective (seulement marchés avec positions)
- ✅ Prix temps réel dans DB (source: 'ws')
- ✅ P&L mis à jour automatiquement
- ✅ UX temps réel dans le bot Telegram

---

## 🔍 ANALYSE DE L'ÉTAT ACTUEL

### ✅ CE QUI EST DÉJÀ EN PLACE
- ✅ **Schema DB complet** (6 tables, RLS activé, 1614 marchés, 3 positions actives)
- ✅ **StreamerService** orchestrateur fonctionnel
- ✅ **SubscriptionManager** logique sélective implémentée
- ✅ **WebSocketClient** structure de base présente
- ✅ **MarketUpdater** avec invalidation cache

### ❌ CE QUI EST À CORRIGER/IMPLÉMENTER

#### 1. **Format Messages WebSocket Incorrect**
**Problème:** Code actuel utilise format générique, pas format Polymarket

```python
# ACTUEL (INCORRECT)
subscription_message = {
    "action": "subscribe",     # ❌ Pas dans la doc Polymarket
    "type": "market",
    "assets_ids": list(token_ids)
}
```

```python
# CORRECT selon doc Polymarket
subscription_message = {
    "assets_ids": list(token_ids),  # ✅ Format Polymarket
    "type": "market"
}
```

#### 2. **Authentification Manquante**
**Problème:** Pas d'authentification API dans les messages

```python
# DOC Polymarket: Auth requise pour certains endpoints
auth = {
    "apiKey": api_key,
    "secret": api_secret,
    "passphrase": api_passphrase
}
```

#### 3. **Ping/Pong Manquant**
**Problème:** Pas de heartbeat pour maintenir la connexion

```python
# DOC Polymarket: Ping toutes les 10 secondes
def ping_loop(self, ws):
    while True:
        ws.send("PING")
        time.sleep(10)
```

#### 4. **WebSocketManager Centralisé Manquant**
**Problème:** Pas de gestionnaire centralisé mentionné dans Phase 7

#### 5. **Intégration Trades Manquante**
**Problème:** `on_trade_executed` pas appelé dans le code de trading

---

## 📋 PLAN D'IMPLÉMENTATION DÉTAILLÉ

### **PHASE 1: CORRECTION WebSocketClient** (1 jour)

#### 1.1 Corriger Format Messages
```python
# Fichier: data_ingestion/streamer/websocket_client/websocket_client.py

# CORRIGER subscribe_markets()
async def subscribe_markets(self, token_ids: Set[str]) -> None:
    subscription_message = {
        "assets_ids": list(token_ids),  # ✅ Format Polymarket
        "type": "market"
    }
    await self.websocket.send(json.dumps(subscription_message))

# CORRIGER unsubscribe_markets()
async def unsubscribe_markets(self, token_ids: Set[str]) -> None:
    unsubscribe_message = {
        "assets_ids": list(token_ids),
        "type": "market",
        "action": "unsubscribe"  # ✅ Ajouter action pour unsubscribe
    }
    await self.websocket.send(json.dumps(unsubscribe_message))
```

#### 1.2 Ajouter Authentification
```python
# AJOUTER dans __init__()
self.api_credentials = {
    "apiKey": settings.polymarket.clob_api_key,
    "secret": settings.polymarket.clob_api_secret,
    "passphrase": settings.polymarket.clob_api_passphrase
}

# MODIFIER _connect_and_stream()
async with websockets.connect(
    self.ws_url,
    ping_interval=None,  # Désactiver ping auto, on gère manuellement
    ping_timeout=10,
    max_size=10 * 1024 * 1024
) as websocket:
    # ✅ Pas besoin d'ajouter credentials dans URL
    # L'auth se fait dans les messages si nécessaire
```

#### 1.3 Implémenter Ping/Pong
```python
# AJOUTER dans __init__()
self.ping_task: Optional[asyncio.Task] = None
self.ping_interval = 10  # Polymarket: 10 secondes

# AJOUTER dans _connect_and_stream()
async def _start_ping_loop(self):
    """Ping loop pour maintenir connexion (Polymarket requirement)"""
    while self.running and self.websocket:
        try:
            await self.websocket.send("PING")
            await asyncio.sleep(self.ping_interval)
        except Exception as e:
            logger.warning(f"Ping error: {e}")
            break

# DÉMARRER ping dans connexion
self.ping_task = asyncio.create_task(self._start_ping_loop())

# GÉRER PONG responses
async def _handle_message(self, data: Dict[str, Any]) -> None:
    if data == "PONG":
        return  # ✅ Ignorer les PONG

    # ... reste du handling
```

#### 1.4 Gestion Messages Polymarket
```python
# AJOUTER gestion des différents types de messages Polymarket
async def _handle_message(self, data: Dict[str, Any]) -> None:
    # ✅ Gérer les messages Polymarket
    event_type = data.get("event_type")

    if event_type == "book":
        # Orderbook update
        await self._handle_orderbook_update(data)
    elif event_type == "price_change":
        # Price update
        await self._handle_price_update(data)
    elif event_type == "trade":
        # Trade update
        await self._handle_trade_update(data)
    elif event_type == "tick_size_change":
        # Tick size change
        await self._handle_tick_size_change(data)
    else:
        # Fallback to registered handlers
        message_type = data.get("type") or data.get("action")
        handler = self.message_handlers.get(message_type)
        if handler:
            await handler(data)
```

---

### **PHASE 2: WebSocketManager Centralisé** (1 jour)

#### 2.1 Créer WebSocketManager
```python
# NOUVEAU FICHIER: core/services/websocket_manager.py

class WebSocketManager:
    """
    Gestionnaire centralisé des WebSocket connections
    Single source of truth pour toutes les subscriptions
    """

    def __init__(self, streamer_service):
        self.streamer = streamer_service
        self.subscription_manager = streamer_service.subscription_manager

    async def subscribe_market_for_user(self, user_id: int, market_id: str):
        """Subscribe to market when user gets position"""
        await self.subscription_manager.on_trade_executed(user_id, market_id)

    async def unsubscribe_market_for_user(self, user_id: int, market_id: str):
        """Unsubscribe when user closes all positions"""
        await self.subscription_manager.on_position_closed(user_id, market_id)

    async def get_user_subscriptions(self, user_id: int) -> List[str]:
        """Get all markets user is subscribed to"""
        # Query positions + active subscriptions
        pass

# SINGLETON
websocket_manager = WebSocketManager(streamer_service)
```

#### 2.2 Intégrer dans Application
```python
# MODIFIER telegram_bot/main.py

# AJOUTER dans lifespan
if settings.data_ingestion.streamer_enabled:
    from core.services.websocket_manager import WebSocketManager
    websocket_manager = WebSocketManager(app.state.streamer)
    app.state.websocket_manager = websocket_manager
    logger.info("✅ WebSocketManager initialized")
```

---

### **PHASE 3: Intégration Trading** (1 jour)

#### 3.1 Connecter Trade Callbacks
```python
# MODIFIER core/services/clob/clob_service.py

# AJOUTER import
from core.services.websocket_manager import websocket_manager

# AJOUTER dans trade execution
async def place_order(self, order_params: Dict) -> Dict:
    """Place order and notify WebSocket manager"""

    # Execute trade
    result = await self._execute_order(order_params)

    if result.get("success"):
        market_id = order_params["market_id"]
        user_id = order_params["user_id"]

        # ✅ NOTIFIER WebSocket Manager
        await websocket_manager.subscribe_market_for_user(user_id, market_id)

    return result
```

#### 3.2 Connecter Position Closing
```python
# MODIFIER core/services/position/position_service.py

# AJOUTER import
from core.services.websocket_manager import websocket_manager

# AJOUTER dans close_position
async def close_position(self, position_id: int) -> bool:
    """Close position and check WebSocket unsubscription"""

    # Close position
    success = await self._close_position_db(position_id)

    if success:
        # ✅ CHECK si unsubscribe needed
        position = await self.get_position(position_id)
        await websocket_manager.unsubscribe_market_for_user(
            position.user_id,
            position.market_id
        )

    return success
```

---

### **PHASE 4: MarketUpdater P&L Temps Réel** (1 jour)

#### 4.1 Updates Positions Automatiques
```python
# MODIFIER data_ingestion/streamer/market_updater/market_updater.py

# AJOUTER méthode pour updates positions
async def _update_positions_pnl(self, market_id: str, new_price: float):
    """Update P&L for all positions on this market"""

    async with get_db() as db:
        # Get all active positions for this market
        positions = await db.execute(
            select(Position).where(
                Position.market_id == market_id,
                Position.status == "active"
            )
        )

        for position in positions.scalars():
            # Calculate new P&L
            pnl_amount = (new_price - position.entry_price) * position.amount
            pnl_percentage = ((new_price - position.entry_price) / position.entry_price) * 100

            # Update position
            await db.execute(
                update(Position).where(Position.id == position.id).values(
                    current_price=new_price,
                    pnl_amount=pnl_amount,
                    pnl_percentage=pnl_percentage,
                    updated_at=datetime.now(timezone.utc)
                )
            )

        await db.commit()

# APPELER dans handle_price_update
async def handle_price_update(self, data: Dict[str, Any]):
    # ... existing code ...

    # ✅ UPDATE positions P&L
    await self._update_positions_pnl(market_id, new_price)
```

#### 4.2 Debouncing pour Performance
```python
# AJOUTER debouncing pour éviter spam updates
self._position_update_queue: Dict[str, float] = {}
self._debounce_delay = 1.0  # 1 seconde

async def _debounced_position_update(self, market_id: str, price: float):
    """Debounced position updates to avoid spam"""
    self._position_update_queue[market_id] = price

    # Cancel existing task
    if hasattr(self, '_debounce_task') and not self._debounce_task.done():
        self._debounce_task.cancel()

    # Schedule new update
    self._debounce_task = asyncio.create_task(self._delayed_position_update())

async def _delayed_position_update(self):
    """Execute position updates after debounce delay"""
    await asyncio.sleep(self._debounce_delay)

    # Process all queued updates
    for market_id, price in self._position_update_queue.items():
        await self._update_positions_pnl(market_id, price)

    self._position_update_queue.clear()
```

---

### **PHASE 5: TESTS & VALIDATION** (0.5 jour)

#### 5.1 Tests d'Intégration
```python
# tests/integration/test_websocket_integration.py

async def test_websocket_subscription_flow():
    """Test complete WebSocket subscription flow"""

    # 1. Create position
    position = await position_service.create_position(user_id, market_id, ...)

    # 2. Verify WebSocket subscription
    subscriptions = await websocket_manager.get_user_subscriptions(user_id)
    assert market_id in subscriptions

    # 3. Simulate price update via WebSocket
    await websocket_client._simulate_price_update(market_id, new_price)

    # 4. Verify position P&L updated
    updated_position = await position_service.get_position(position.id)
    assert updated_position.current_price == new_price
    assert updated_position.pnl_amount is not None

    # 5. Close position
    await position_service.close_position(position.id)

    # 6. Verify WebSocket unsubscription
    subscriptions = await websocket_manager.get_user_subscriptions(user_id)
    assert market_id not in subscriptions
```

#### 5.2 Tests Performance
```python
async def test_websocket_performance():
    """Test WebSocket performance under load"""

    # Simulate 100 price updates per second
    start_time = time.time()

    for i in range(100):
        await websocket_client._simulate_price_update(market_id, 0.5 + i * 0.001)

    duration = time.time() - start_time

    # Verify updates processed within time limit
    assert duration < 2.0  # < 2 secondes pour 100 updates

    # Verify no duplicate updates (debouncing works)
    position = await position_service.get_position(position_id)
    assert position.updated_at is not None
```

---

## 🔧 MISES À JOUR DE CONFIGURATION

### Variables d'Environnement
```bash
# AJOUTER dans .env.local
CLOB_API_KEY=your_api_key
CLOB_API_SECRET=your_api_secret
CLOB_API_PASSPHRASE=your_passphrase

# DÉJÀ PRÉSENT
STREAMER_ENABLED=true
CLOB_WSS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market
```

### Settings Updates
```python
# infrastructure/config/settings.py

class PolymarketSettings(BaseSettings):
    # AJOUTER
    clob_api_key: str = Field("", env="CLOB_API_KEY")
    clob_api_secret: str = Field("", env="CLOB_API_SECRET")
    clob_api_passphrase: str = Field("", env="CLOB_API_PASSPHRASE")
```

---

## 📊 VALIDATION & SUCCESS CRITERIA

### ✅ Critères de Succès
- [ ] **Connexion WebSocket:** Connecte sans erreur à Polymarket
- [ ] **Authentification:** Reçoit des messages (pas d'erreur auth)
- [ ] **Subscription:** Subscribe automatiquement après trade
- [ ] **Prix Temps Réel:** `markets.source = 'ws'` dans DB
- [ ] **P&L Live:** Positions mises à jour automatiquement
- [ ] **Performance:** < 100ms lag WebSocket
- [ ] **Debouncing:** Pas de spam updates DB

### 🧪 Tests de Validation
```bash
# 1. Démarrer application
python3 telegram_bot/main.py

# 2. Vérifier logs connexion
# Expected: "✅ WebSocket connected" + "📡 Subscribed to X markets"

# 3. Créer position via bot
/start -> Trading flow

# 4. Vérifier en DB
SELECT source, outcome_prices FROM markets WHERE id = 'market_id';
# Expected: source = 'ws', prix mis à jour

# 5. Vérifier positions
SELECT current_price, pnl_amount FROM positions WHERE status = 'active';
# Expected: Prix et P&L mis à jour automatiquement
```

---

## 🚨 GESTION DES ERREURS & FALLBACKS

### Connection Failures
```python
# Fallback to polling si WebSocket down
if not websocket_connected:
    logger.warning("WebSocket down, falling back to polling")
    # Continue avec poller seulement
```

### Rate Limiting
```python
# Respecter limites Polymarket
self.max_subscriptions = 1000  # Polymarket limit
self.update_rate_limit = 10  # Max 10 position updates/second
```

### Data Consistency
```python
# Validation données WebSocket
if not self._validate_price_update(data):
    logger.warning(f"Invalid price update: {data}")
    return
```

---

## 📈 MONITORING & OBSERVABILITÉ

### Métriques à Ajouter
```python
# prometheus_client metrics
WEBSOCKET_CONNECTIONS = Gauge('websocket_connections_active', 'Active WebSocket connections')
WEBSOCKET_MESSAGES = Counter('websocket_messages_total', 'WebSocket messages received')
SUBSCRIPTION_COUNT = Gauge('websocket_subscriptions_total', 'Total active subscriptions')
PRICE_UPDATE_LATENCY = Histogram('price_update_latency_seconds', 'Price update processing latency')
```

### Logs Structurés
```python
logger.info("WebSocket connected", extra={
    "user_id": user_id,
    "market_count": len(subscribed_markets),
    "connection_time": connection_duration
})
```

---

## 🎯 PLAN D'EXÉCUTION

### **Semaine 1: Core WebSocket** (3 jours)
1. **Jour 1:** Corriger WebSocketClient (format, auth, ping/pong)
2. **Jour 2:** Créer WebSocketManager centralisé
3. **Jour 3:** Intégrer callbacks trading + tests

### **Semaine 2: P&L Temps Réel** (2 jours)
4. **Jour 4:** MarketUpdater avec positions updates + debouncing
5. **Jour 5:** Tests intégration + performance + validation

### **Total: 5 jours** avec tests complets

---

**Résultat Final:** WebSocket Polymarket opérationnel avec subscription sélective, P&L temps réel, et UX fluide selon le MASTER PLAN Phase 7.
