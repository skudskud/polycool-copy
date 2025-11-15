# 🔍 Analyse du Problème WebSocket

## Problème Identifié

**Symptôme:** Aucun marché avec `source = 'ws'` dans la base de données après un trade.

**Requête SQL:**
```sql
SELECT id, source, outcome_prices, updated_at
FROM markets
WHERE source = 'ws'
ORDER BY updated_at DESC
LIMIT 10;
```
**Résultat:** `[]` (vide)

## Analyse des Logs

D'après les logs fournis (lignes 888-1013):

1. **Trade exécuté avec succès** (ligne 943-944):
   ```
   ✅ Order executed: 0xa9ba00f583b937690ab98d54dc6001289314bb6b4e25baedde34cf7037490b15
   ```

2. **Tentative de souscription WebSocket** (ligne 959):
   ```
   🔌 Attempting to subscribe to WebSocket for market 570361 after trade
   ```

3. **Échec de la connexion** (ligne 960):
   ```
   ⚠️ WebSocketManager not connected to streamer
   ```

4. **Résultat de la souscription** (ligne 961):
   ```
   ✅ WebSocket subscription result for market 570361: False
   ```

## Cause Racine

### 1. Problème d'Ordre d'Initialisation

Le singleton `websocket_manager` est créé **avant** que le streamer ne soit initialisé:

```python
# core/services/websocket_manager.py (ligne 247)
websocket_manager = WebSocketManager()  # ❌ Créé sans streamer
```

Le streamer est ensuite créé et connecté dans `main.py`:

```python
# telegram_bot/main.py (lignes 57-69)
if settings.data_ingestion.streamer_enabled:
    streamer = StreamerService()
    websocket_manager.set_streamer_service(streamer)  # ✅ Connecté ici
```

**Problème:** Si `trade_service` importe `websocket_manager` avant que `main.py` ne connecte le streamer, la connexion n'est pas établie.

### 2. Streamer ne Démarre pas le WebSocket Client

Le streamer ne démarre le WebSocket client que s'il y a des positions actives au démarrage:

```python
# data_ingestion/streamer/streamer.py (lignes 48-60)
has_active_positions = await self._check_active_positions()

if has_active_positions:
    await self.websocket_client.start()  # ✅ Démarre
else:
    logger.info("⚠️ No active positions - streamer will wait for trades")
    # ❌ Ne démarre PAS le WebSocket client
```

Quand un trade est exécuté, `on_trade_executed` est appelé mais le WebSocket client peut ne pas être démarré.

### 3. WebSocketManager Retourne False

Quand `websocket_manager.on_trade_executed()` est appelé, il vérifie si le streamer est connecté:

```python
# core/services/websocket_manager.py (lignes 58-60)
if not self.streamer or not self.subscription_manager:
    logger.warning("⚠️ WebSocketManager not connected to streamer")
    return False  # ❌ Retourne False
```

## Solutions Proposées

### Solution 1: Vérifier la Connexion au Démarrage

Ajouter une vérification dans `main.py` pour s'assurer que le WebSocketManager est bien connecté:

```python
# Dans telegram_bot/main.py après ligne 69
if settings.data_ingestion.streamer_enabled:
    # Vérifier que la connexion est établie
    if websocket_manager.streamer is None:
        logger.error("❌ WebSocketManager not connected to streamer!")
    else:
        logger.info("✅ WebSocketManager connected to streamer")
```

### Solution 2: Démarrage Conditionnel du WebSocket Client

Modifier `on_trade_executed` pour démarrer le WebSocket client si nécessaire:

```python
# Dans data_ingestion/streamer/streamer.py
async def on_trade_executed(self, user_id: int, market_id: str) -> None:
    # Subscribe to the market
    await self.subscription_manager.on_trade_executed(user_id, market_id)

    # ✅ Démarrer le WebSocket client s'il n'est pas déjà démarré
    if not self.websocket_client.running:
        logger.info("🚀 Starting WebSocket client after trade")
        asyncio.create_task(self.websocket_client.start())
```

### Solution 3: Logging Amélioré

Ajouter plus de logs pour diagnostiquer le problème:

```python
# Dans core/services/websocket_manager.py
async def subscribe_user_to_market(self, user_id: int, market_id: str) -> bool:
    logger.info(f"🔍 WebSocketManager state: streamer={self.streamer is not None}, subscription_manager={self.subscription_manager is not None}")

    if not self.streamer or not self.subscription_manager:
        logger.warning("⚠️ WebSocketManager not connected to streamer")
        logger.warning(f"   streamer={self.streamer}, subscription_manager={self.subscription_manager}")
        return False
```

## Prochaines Étapes

1. ✅ Vérifier que `STREAMER_ENABLED=true` dans `.env.local`
2. ✅ Vérifier que le streamer démarre correctement dans les logs
3. ✅ Vérifier que le WebSocketManager est connecté au streamer
4. ✅ Vérifier que le WebSocket client démarre après un trade
5. ✅ Vérifier que les messages WebSocket sont reçus
6. ✅ Vérifier que les données sont écrites avec `source='ws'`

## Commandes de Diagnostic

```bash
# Vérifier les variables d'environnement
grep STREAMER_ENABLED .env.local

# Vérifier les logs du streamer
grep -i "streamer\|websocket" logs/*.log | tail -50

# Vérifier les logs de souscription
grep -i "subscribe\|trade executed" logs/*.log | tail -50
```
