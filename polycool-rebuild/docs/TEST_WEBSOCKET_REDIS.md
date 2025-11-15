# 🧪 Test WebSocket Redis Pub/Sub en Local

## 📋 Vue d'ensemble

Ce guide explique comment tester la solution Redis Pub/Sub pour les subscriptions WebSocket en local, simulant l'architecture de production (API + Workers séparés).

## 🏗️ Architecture de Test

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   API       │────────▶│    Redis     │◀────────│  Workers    │
│ (api_only)  │  Pub    │   Pub/Sub    │  Sub    │ (workers.py)│
│             │         │              │         │             │
│ STREAMER=   │         │              │         │ STREAMER=   │
│   false     │         │              │         │   true      │
└─────────────┘         └──────────────┘         └─────────────┘
                                                          │
                                                          ▼
                                                  ┌─────────────┐
                                                  │  Streamer   │
                                                  │  Service    │
                                                  │  (WebSocket) │
                                                  └─────────────┘
```

## 🚀 Démarrage

### 1. Lancer le script de test

```bash
cd polycool-rebuild
./scripts/dev/test-bot-simple.sh
```

Le script va :
1. ✅ Vérifier/ démarrer Redis
2. ✅ Démarrer l'API (`api_only.py`) - **sans streamer**
3. ✅ Démarrer Workers (`workers.py`) - **avec streamer + listener Redis**
4. ✅ Démarrer le Bot (`bot_only.py`) - **sans streamer** (utilise Redis)

### 2. Vérifier que tout est démarré

Dans des terminaux séparés, surveille les logs :

```bash
# Terminal 1: Logs API
tail -f logs/api.log | grep -i websocket

# Terminal 2: Logs Workers
tail -f logs/workers.log | grep -i "redis\|subscribe\|websocket"

# Terminal 3: Logs Bot
tail -f logs/bot.log
```

## ✅ Vérifications Initiales

### API Service
Tu devrais voir dans `logs/api.log` :
```
✅ API service startup complete
```

### Workers Service
Tu devrais voir dans `logs/workers.log` :
```
✅ Streamer service launched
✅ WebSocket subscription listener started
✅ Redis PubSub connected
```

### Bot Service
Tu devrais voir dans `logs/bot.log` :
```
⚠️ Streamer disabled (STREAMER_ENABLED=false) - WebSocket features unavailable
✅ Telegram bot started
```

## 🧪 Test d'une Subscription WebSocket

### 1. Exécuter un trade via le bot Telegram

1. Envoie `/start` au bot
2. Exécute un trade (achat d'une position)

### 2. Observer les logs

#### Dans `logs/api.log` :
```
📡 [API] Subscribe request: user=6500527972, market=570362
📡 [API] Publishing to Redis Pub/Sub (multi-service mode)
📤 [API] Published subscribe request to Redis: 1 subscribers
✅ [API] Successfully subscribed user 6500527972 to market 570362
```

#### Dans `logs/workers.log` :
```
📡 [Redis] Subscribe request: user=6500527972, market=570362
✅ [Redis] Successfully subscribed user 6500527972 to market 570362
📡 User 6500527972 subscribed to market 570362
```

### 3. Vérifier que le WebSocket est démarré

Dans `logs/workers.log`, tu devrais voir :
```
🌐 WebSocket Client starting...
✅ WebSocket connected
📡 Subscribed to markets: ['570362']
```

## 🔍 Debugging

### Problème: "Subscription failed"

**Symptôme** dans `logs/api.log` :
```
⚠️ [API] Failed to subscribe user X to market Y
```

**Vérifications** :
1. ✅ Redis est-il démarré ? `redis-cli ping`
2. ✅ Workers service est-il démarré ? `ps aux | grep workers.py`
3. ✅ Listener Redis est-il actif ? Cherche dans `logs/workers.log` : `✅ WebSocket subscription listener started`

### Problème: "No subscribers" dans Redis

**Symptôme** :
```
📤 [API] Published subscribe request to Redis: 0 subscribers
```

**Cause** : Le listener Redis dans workers n'est pas démarré ou n'a pas souscrit au pattern.

**Solution** : Vérifie dans `logs/workers.log` :
```
✅ Subscribed to pattern: websocket:subscribe:*
✅ Subscribed to pattern: websocket:unsubscribe:*
```

### Problème: Streamer non connecté

**Symptôme** dans `logs/workers.log` :
```
⚠️ WebSocketManager not connected to streamer
```

**Cause** : Le streamer n'est pas démarré dans workers.

**Solution** : Vérifie que `STREAMER_ENABLED=true` dans workers et cherche :
```
✅ Streamer service launched
✅ WebSocketManager connected to streamer
```

## 📊 Test Manuel de l'Endpoint

Tu peux aussi tester directement l'endpoint API :

```bash
curl -X POST http://localhost:8000/api/v1/websocket/subscribe \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 6500527972,
    "market_id": "570362"
  }'
```

Réponse attendue :
```json
{
  "success": true,
  "message": "Subscribed to market 570362",
  "user_id": 6500527972,
  "market_id": "570362"
}
```

## 🛑 Arrêt des Services

Appuie sur `Ctrl+C` dans le terminal où le script tourne. Le script va automatiquement arrêter :
- ✅ API
- ✅ Workers
- ✅ Bot

Ou manuellement :
```bash
pkill -f "api_only.py"
pkill -f "workers.py"
pkill -f "bot_only.py"
```

## 🎯 Résultat Attendu

Si tout fonctionne correctement :

1. ✅ L'API publie sur Redis quand un trade est exécuté
2. ✅ Le Workers service reçoit le message Redis
3. ✅ Le Workers service exécute la subscription via WebSocketManager
4. ✅ Le StreamerService démarre le WebSocket si nécessaire
5. ✅ Le marché est souscrit au WebSocket pour les mises à jour en temps réel

## 📝 Notes

- En mode local avec `STREAMER_ENABLED=true` dans le bot, l'appel direct fonctionne aussi (pas besoin de Redis)
- Le script force `STREAMER_ENABLED=false` dans le bot pour tester le mode Redis Pub/Sub
- En production, l'API n'a jamais le streamer, donc Redis Pub/Sub est toujours utilisé
