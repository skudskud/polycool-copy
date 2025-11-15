# Fix: Copy Trading Listener Non Démarré

**Date:** 2025-11-13
**Problème:** `subscribers: 0` dans les logs Redis PubSub

---

## 🔍 Diagnostic

Les logs montrent que :
1. ✅ Redis PubSub est connecté
2. ✅ Le webhook publie dans Redis
3. ❌ **Aucun subscriber** (`subscribers: 0`)

**Cela signifie que le Copy Trading Listener n'est pas démarré ou n'est pas abonné au pattern Redis.**

---

## 🔧 Solutions

### Solution 1: Vérifier les Logs Workers

Vérifier si le listener démarre correctement dans les logs workers :

```bash
tail -f logs/workers.log | grep -E "COPY_TRADE|Copy trading listener"
```

**Rechercher:**
- `✅ [COPY_TRADE] Copy Trading Listener started and listening for messages`
- `📡 [COPY_TRADE] Subscribing to pattern: copy_trade:*`
- `✅ Subscribed to pattern: copy_trade:*`

**Si erreur:**
- `❌ Failed to start copy trading listener: ...`
- `❌ [COPY_TRADE] Failed to connect to Redis PubSub`

### Solution 2: Vérifier que Workers.py Démarrer le Listener

**Fichier:** `workers.py` ligne 219

Le listener devrait être démarré ici :
```python
copy_trading_listener = await _start_copy_trading_listener()
```

**Vérifier dans les logs:**
```bash
grep "Copy trading listener" logs/workers.log
```

### Solution 3: Vérifier l'Ordre de Démarrage

Le listener doit être démarré **après** la connexion Redis PubSub.

**Dans workers.py:**
```python
# Ligne 209-213: Redis PubSub connecté
redis_pubsub = get_redis_pubsub_service()
if await redis_pubsub.connect():
    logger.info("✅ Redis PubSub connected")

# Ligne 219: Copy Trading Listener démarré
copy_trading_listener = await _start_copy_trading_listener()
```

**Problème possible:** Le listener utilise sa propre instance de Redis PubSub, pas celle connectée dans workers.py.

### Solution 4: Vérifier l'Instance Redis PubSub

Le Copy Trading Listener crée sa propre instance de Redis PubSub via `get_redis_pubsub_service()`, qui devrait être un singleton.

**Vérifier dans `copy_trading_listener.py`:**
```python
self.pubsub_service = get_redis_pubsub_service()
```

**Problème possible:** Si le listener crée une nouvelle connexion Redis au lieu d'utiliser celle déjà connectée, il pourrait y avoir un problème de timing.

---

## 🚨 Problème Probable

Le Copy Trading Listener utilise `get_redis_pubsub_service()` qui retourne une instance singleton, mais :

1. **Dans workers.py:** Une connexion Redis est créée ligne 209
2. **Dans copy_trading_listener.start():** Le listener crée sa propre connexion Redis ligne 67-68

**Si le listener démarre avant que Redis soit complètement connecté, ou si la connexion échoue silencieusement, le listener ne s'abonnera pas.**

---

## ✅ Fix Recommandé

### Option 1: Attendre que Redis soit Connecté

Modifier `workers.py` pour s'assurer que Redis est connecté avant de démarrer le listener :

```python
# Connect Redis PubSub
redis_pubsub = get_redis_pubsub_service()
if await redis_pubsub.connect():
    logger.info("✅ Redis PubSub connected")
else:
    logger.error("❌ Failed to connect Redis PubSub - cannot start copy trading listener")
    # Ne pas démarrer le listener si Redis n'est pas connecté

# Attendre un peu pour s'assurer que la connexion est stable
await asyncio.sleep(0.5)

# Maintenant démarrer le listener
copy_trading_listener = await _start_copy_trading_listener()
```

### Option 2: Vérifier la Connexion dans le Listener

Modifier `copy_trading_listener.py` pour vérifier que Redis est connecté avant de s'abonner :

```python
async def start(self) -> None:
    """Start listening to Redis PubSub"""
    try:
        if self.running:
            logger.warning("⚠️ [COPY_TRADE] Copy Trading Listener already running")
            return

        # Connect to Redis
        logger.info("🔌 [COPY_TRADE] Connecting to Redis PubSub...")

        # Vérifier la connexion plusieurs fois si nécessaire
        max_retries = 3
        for attempt in range(max_retries):
            if await self.pubsub_service.health_check():
                logger.info("✅ [COPY_TRADE] Redis PubSub already connected")
                break
            else:
                connected = await self.pubsub_service.connect()
                if connected:
                    logger.info("✅ [COPY_TRADE] Redis PubSub connected")
                    break
                else:
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️ [COPY_TRADE] Failed to connect (attempt {attempt + 1}/{max_retries}), retrying...")
                        await asyncio.sleep(1)
                    else:
                        logger.error("❌ [COPY_TRADE] Failed to connect to Redis PubSub after {max_retries} attempts")
                        return

        # Subscribe to copy_trade:* pattern
        logger.info("📡 [COPY_TRADE] Subscribing to pattern: copy_trade:*")
        await self.pubsub_service.subscribe(
            pattern="copy_trade:*",
            callback=self._handle_trade_message
        )

        self.running = True
        logger.info("✅ [COPY_TRADE] Copy Trading Listener started and listening for messages")
```

---

## 🔍 Commandes de Diagnostic

### 1. Vérifier les Logs Workers
```bash
tail -f logs/workers.log | grep -E "COPY_TRADE|Copy trading listener|Redis PubSub"
```

### 2. Vérifier les Erreurs
```bash
grep -E "❌|Error|Failed" logs/workers.log | grep -i "copy\|redis"
```

### 3. Vérifier la Subscription Redis
```bash
# Se connecter à Redis et vérifier les subscriptions actives
redis-cli PUBSUB CHANNELS "copy_trade:*"
```

### 4. Tester la Publication Manuelle
```bash
# Publier un message de test dans Redis
redis-cli PUBLISH "copy_trade:0xa7a84f34481ec124fd38c5215d28a92e27e38552" '{"test": "message"}'
```

---

## 📊 Logs Attendus (Si Fixé)

Si le listener démarre correctement, vous devriez voir :

```
✅ Redis PubSub connected
🔌 [COPY_TRADE] Connecting to Redis PubSub...
✅ [COPY_TRADE] Redis PubSub already connected
📡 [COPY_TRADE] Subscribing to pattern: copy_trade:*
✅ Subscribed to pattern: copy_trade:*
✅ [COPY_TRADE] Copy Trading Listener started and listening for messages
```

Et ensuite, quand un webhook arrive :

```
📤 [WEBHOOK_REDIS] Publishing BUY to channel copy_trade:0xa7a84f34...
✅ [WEBHOOK_REDIS] Published BUY to copy_trade:0xa7a84f34..., subscribers: 1  ← 1 au lieu de 0!
🚀 [COPY_TRADE] Received BUY trade from 0xa7a84f34...
```

---

## 🎯 Action Immédiate

1. **Vérifier les logs workers** pour voir si le listener démarre
2. **Vérifier les erreurs** lors du démarrage
3. **Appliquer le fix** si nécessaire (Option 1 ou 2)
4. **Redémarrer les workers** et vérifier que `subscribers: 1` (ou plus)

---

**Note:** Le polling fallback (60-120s) fonctionnera toujours même si Redis PubSub échoue, mais la latence sera beaucoup plus élevée.
