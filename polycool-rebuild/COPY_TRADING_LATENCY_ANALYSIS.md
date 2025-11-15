# Analyse de Latence - Copy Trading Flow

**Date:** 2025-11-13
**Latence Annoncée:** **< 10 secondes** (via Redis PubSub)

---

## 📊 Latence Totale Annoncée

D'après le code existant, la latence annoncée est **< 10 secondes** entre le moment où le leader fait un trade et où le follower copie ce trade.

**Références dans le code:**
- `telegram-bot-v2/py-clob-server/core/services/copy_trading_monitor.py:414`:
  > "This provides <10s latency vs 10-60s polling"
- `telegram-bot-v2/py-clob-server/main.py:887`:
  > "This provides <10s latency for copy trading"
- `telegram-bot-v2/py-clob-server/main.py:893`:
  > "Redis Pub/Sub handles instant (<10s), this is just safety net"

---

## 🔄 Décomposition du Flow et Latences

### Phase 1: Leader Trade sur Polymarket
**Latence:** ~0s (instantané côté utilisateur)

```
Leader clique "Buy" sur Polymarket
↓
Transaction soumise à la blockchain Polygon
```

**Note:** La transaction blockchain elle-même prend quelques secondes à être confirmée, mais le trade est considéré comme "fait" dès la soumission.

---

### Phase 2: Indexer Détecte le Trade (Subsquid)
**Latence:** **2-5 secondes** (variable selon la fréquence de polling Subsquid)

```
Transaction confirmée sur Polygon
↓
Subsquid indexe la transaction (polling ou event-based)
↓
Indexer détecte que l'adresse est dans watched_addresses
↓
Indexer prépare le webhook
```

**Détails:**
- Subsquid peut être **event-based** (quasi-instantané) ou **polling-based** (quelques secondes)
- La détection dépend de la vitesse d'indexation de Subsquid
- **Typique:** 2-5 secondes pour détecter un nouveau trade

---

### Phase 3: Indexer → API Webhook
**Latence:** **100-500ms** (latence réseau)

```
Indexer envoie POST /api/v1/webhooks/copy-trade
↓
Requête HTTP traverse le réseau
↓
API reçoit le webhook
```

**Détails:**
- Latence réseau dépend de la distance géographique
- Si indexer et API sont dans la même région: **<100ms**
- Si régions différentes: **200-500ms**

---

### Phase 4: API Traite le Webhook
**Latence:** **50-200ms** (traitement synchrone)

```
API reçoit webhook
↓
Vérifie webhook secret (~10ms)
↓
Cache lookup: watched address? (~20ms)
↓
Get WatchedAddress from DB (~50-100ms)
↓
Crée async tasks (non-blocking)
↓
Return 200 OK rapidement
```

**Détails:**
- Le webhook retourne **200 OK rapidement** (<200ms)
- Les tâches lourdes (DB storage, Redis publish) sont **async** (non-blocking)
- L'API ne bloque pas sur ces opérations

---

### Phase 5: API Publie dans Redis PubSub
**Latence:** **10-50ms** (async task)

```
Async task: _publish_to_redis()
↓
Connect to Redis (si pas déjà connecté)
↓
Serialize message to JSON
↓
Publish to channel: copy_trade:{address}
↓
Redis distribue aux subscribers
```

**Détails:**
- Redis PubSub est **très rapide** (<50ms typiquement)
- Si Redis est local: **<10ms**
- Si Redis est distant: **20-50ms**

---

### Phase 6: Copy Trading Listener Reçoit le Message
**Latence:** **<10ms** (instantané via Redis PubSub)

```
Redis PubSub distribue le message
↓
Copy Trading Listener reçoit via subscription
↓
_handle_trade_message() appelé
```

**Détails:**
- Redis PubSub est **instantané** pour les subscribers actifs
- Pas de polling, pas d'attente
- **<10ms** pour recevoir le message

---

### Phase 7: Listener Traite le Message
**Latence:** **100-500ms** (parsing + vérifications)

```
Parse JSON message (~5ms)
↓
Deduplication check (~5ms)
↓
Cache lookup: watched address? (~20ms)
↓
Get WatchedAddress from DB (~50-100ms)
↓
Get CopyTradingAllocations from DB (~50-100ms)
↓
Pour chaque allocation: créer task async
```

**Détails:**
- Les vérifications DB peuvent prendre **50-200ms** chacune
- Si cache hit: **<50ms**
- Si cache miss: **100-200ms**

---

### Phase 8: Exécution Copy Trade
**Latence:** **1-3 secondes** (exécution CLOB API)

```
Pour chaque follower:
↓
Resolve market/token (~100-200ms)
↓
Get follower balance (~200-500ms)
↓
Calculate copy amount (~10ms)
↓
Execute market order via CLOB API (~1-2s)
↓
Create position in DB (~100-200ms)
```

**Détails:**
- **Résolution market:** 100-200ms (cache ou DB)
- **Balance check:** 200-500ms (CLOB API call)
- **Trade execution:** 1-2 secondes (CLOB API + blockchain)
- **Position creation:** 100-200ms (DB insert)

**Total par follower:** **1.5-3 secondes**

---

## 📈 Latence Totale Estimée

### Scénario Optimiste (Tout en Cache, Réseau Rapide)
```
Phase 2: Indexer détecte         2s
Phase 3: Webhook réseau          100ms
Phase 4: API traite webhook      50ms
Phase 5: Redis publish           10ms
Phase 6: Listener reçoit         5ms
Phase 7: Listener traite          100ms (cache hits)
Phase 8: Exécution trade          1.5s
─────────────────────────────────────
TOTAL:                            ~3.8 secondes
```

### Scénario Réaliste (Conditions Normales)
```
Phase 2: Indexer détecte         3-4s
Phase 3: Webhook réseau          200ms
Phase 4: API traite webhook      100ms
Phase 5: Redis publish           30ms
Phase 6: Listener reçoit         10ms
Phase 7: Listener traite          200ms (quelques DB calls)
Phase 8: Exécution trade          2s
─────────────────────────────────────
TOTAL:                            ~5.7 secondes
```

### Scénario Pessimiste (DB lente, Réseau lent)
```
Phase 2: Indexer détecte         5s
Phase 3: Webhook réseau          500ms
Phase 4: API traite webhook      200ms
Phase 5: Redis publish           50ms
Phase 6: Listener reçoit         10ms
Phase 7: Listener traite          500ms (DB calls lents)
Phase 8: Exécution trade          3s
─────────────────────────────────────
TOTAL:                            ~9.3 secondes
```

---

## ✅ Latence Annoncée: < 10 secondes

**Conclusion:** La latence annoncée de **< 10 secondes** est **réaliste** et correspond au scénario pessimiste.

**Breakdown typique:**
- **Indexer detection:** 2-5s (variable, dépend de Subsquid)
- **Webhook + Redis:** 200-300ms (rapide)
- **Listener processing:** 200-500ms (DB calls)
- **Trade execution:** 1.5-3s (CLOB API + blockchain)

**Total:** **4-9 secondes** dans la plupart des cas ✅

---

## 🚀 Optimisations Possibles

### 1. Réduire la Latence d'Indexation
**Actuel:** 2-5 secondes
**Optimisation:** Utiliser event-based Subsquid au lieu de polling
**Gain potentiel:** -2 à -3 secondes

### 2. Optimiser les DB Calls
**Actuel:** 200-500ms pour vérifications
**Optimisation:**
- Cache plus agressif pour WatchedAddress
- Cache pour CopyTradingAllocations
**Gain potentiel:** -100 à -200ms

### 3. Paralléliser l'Exécution
**Actuel:** Trades exécutés en parallèle mais séquentiellement pour chaque follower
**Optimisation:** Déjà fait ✅ (asyncio.create_task)
**Gain:** Aucun (déjà optimal)

### 4. Pré-chauffer les Connexions
**Actuel:** Connexions créées à la demande
**Optimisation:**
- Pool de connexions Redis
- Pool de connexions DB
- Pré-connexion CLOB clients
**Gain potentiel:** -50 à -100ms

---

## 📊 Comparaison avec Polling Fallback

### Redis PubSub (Actuel)
**Latence:** < 10 secondes
**Avantages:**
- ✅ Instantané dès que le trade est détecté
- ✅ Pas de polling inutile
- ✅ Efficace en ressources

### Polling Fallback
**Latence:** 60-120 secondes (selon configuration)
- General poller: **120 secondes**
- Fast-track poller: **60 secondes**

**Avantages:**
- ✅ Fonctionne même si Redis échoue
- ✅ Safety net pour les trades manqués

**Conclusion:** Redis PubSub est **10-20x plus rapide** que le polling fallback.

---

## 🎯 Métriques à Surveiller

Pour mesurer la latence réelle, ajouter des timestamps:

1. **Timestamp du trade leader** (dans `event.timestamp`)
2. **Timestamp de réception webhook** (dans API)
3. **Timestamp de publication Redis** (dans API)
4. **Timestamp de réception Redis** (dans Listener)
5. **Timestamp d'exécution trade** (dans TradeService)

**Calcul de latence:**
```
Latence totale = timestamp_exécution - timestamp_trade_leader
Latence webhook = timestamp_redis_publish - timestamp_webhook_received
Latence redis = timestamp_listener_received - timestamp_redis_publish
Latence execution = timestamp_trade_executed - timestamp_listener_received
```

---

## 📝 Recommandations

1. **Ajouter des métriques de latence** dans les logs
2. **Surveiller les latences** par phase pour identifier les bottlenecks
3. **Optimiser les phases les plus lentes** (indexer detection, DB calls)
4. **Garder le polling fallback** comme safety net (60-120s)

---

**Note:** La latence de **< 10 secondes** est une **bonne performance** pour un système de copy trading, surtout comparé aux alternatives de polling (60-120s).
