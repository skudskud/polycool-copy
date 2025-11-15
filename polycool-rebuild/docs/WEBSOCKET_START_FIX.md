# 🔧 Fix: WebSocket Client Ne Démarre Pas Après Trade

## 🐛 Problème Identifié

Le WebSocket client ne démarre pas après un trade, même si les subscriptions sont ajoutées.

**Symptômes dans les logs:**
```
📝 WebSocket not connected - subscriptions stored for later
```

**Cause Racine:**

Dans `websocket_manager.py`, la méthode `subscribe_user_to_market()` appelait directement `subscription_manager.on_trade_executed()` au lieu de passer par `streamer.on_trade_executed()`.

**Flux incorrect:**
```
trade_service
  → websocket_manager.on_trade_executed()
  → websocket_manager.subscribe_user_to_market()
  → subscription_manager.on_trade_executed()  ❌ DIRECTEMENT
  → websocket_client.subscribe_markets()
  → ❌ WebSocket jamais démarré!
```

**Flux correct:**
```
trade_service
  → websocket_manager.on_trade_executed()
  → websocket_manager.subscribe_user_to_market()
  → streamer.on_trade_executed()  ✅ VIA STREAMER
  → subscription_manager.on_trade_executed()
  → websocket_client.subscribe_markets()
  → streamer.on_trade_executed() vérifie si WebSocket running
  → ✅ Démarre WebSocket si nécessaire
```

## ✅ Solution Appliquée

**Fichier:** `core/services/websocket_manager.py`

**Avant:**
```python
# Subscribe via subscription manager
await self.subscription_manager.on_trade_executed(user_id, market_id)
```

**Après:**
```python
# Subscribe via streamer (which will also start WebSocket if needed)
await self.streamer.on_trade_executed(user_id, market_id)
```

## 🎯 Résultat Attendu

Après ce fix, les logs devraient montrer:

1. **Après un trade:**
   ```
   📡 Trade executed for market 570361 - checking if WebSocket needs to start
   🚀 Starting WebSocket client after first trade
   ✅ WebSocket client start task created
   🔍 Getting token IDs for market 570361 after trade...
   📡 Subscribing to 2 tokens for market 570361
   ✅ Added 2 subscriptions: [...]
   🌐 WebSocket Client starting...
   🔌 Connecting to Polymarket CLOB WebSocket...
   ✅ WebSocket connected
   📡 Sending subscription message: {...}
   ```

2. **Quand les messages WebSocket arrivent:**
   ```
   📊 Processing price update: ...
   ✅ Extracted prices [...] for market 570361
   📝 Updating market 570361 via API with source='ws', prices=[...]
   ✅ Updated market 570361 with source='ws' via API
   ```

## 📊 Comparaison Avant/Après

| Élément | Avant | Après |
|---------|-------|-------|
| WebSocket démarre après trade | ❌ Non | ✅ Oui |
| Messages WebSocket reçus | ❌ Non | ✅ Oui |
| Mise à jour DB avec source='ws' | ❌ Non | ✅ Oui |

## ✅ Fix Appliqué

- ✅ `websocket_manager.subscribe_user_to_market()` appelle maintenant `streamer.on_trade_executed()` au lieu de `subscription_manager.on_trade_executed()` directement
- ✅ Le WebSocket client sera démarré automatiquement après le premier trade
- ✅ Les subscriptions seront envoyées dès que le WebSocket est connecté
