# 🔍 Analyse Complète du Cache Redis - Polycool

**Date**: 2025-01-12
**Contexte**: Architecture microservices (Bot, API, Workers) avec service Redis centralisé

---

## 📊 Architecture Actuelle

### Services Utilisant Redis

1. **Bot Service** (`SKIP_DB=true`)
   - Utilise `CacheManager` pour cache API responses
   - Utilise `APIClient` avec cache intégré
   - Clés: `api:positions:{user_id}`, `api:user:{telegram_id}`, etc.

2. **API Service** (`SKIP_DB=false`)
   - Accès direct DB (Supabase)
   - Utilise `CacheManager` pour invalidation (partielle)
   - Clés: `market:{market_id}`, `market_detail:{market_id}`, etc.

3. **Workers Service** (data-ingestion)
   - Met à jour les prix des markets
   - Utilise Redis Pub/Sub pour notifications copy-trading
   - Publie sur channel `copy_trade:*`

4. **Indexer Service**
   - Écoute Redis Pub/Sub pour copy-trading
   - Cache de résolution de positions (5min TTL)

### Configuration Redis

```python
# infrastructure/config/settings.py
class RedisSettings:
    url: str = "redis://localhost:6379"  # ou Railway internal
    ttl_prices: int = 20          # 20 secondes
    ttl_positions: int = 30       # 30 secondes (réduit de 3min)
    ttl_markets: int = 300        # 5 minutes
    ttl_user_data: int = 3600     # 1 heure
    pubsub_enabled: bool = True
```

**Configuration Redis (redis.conf)**:
- `maxmemory`: 256mb
- `maxmemory-policy`: allkeys-lru
- `persistence`: désactivée (dev)
- `notify-keyspace-events`: Ex (expiration events)

---

## 🚨 Enjeux Critiques Identifiés

### 1. **BLOCAGE AVEC `redis.keys()`** ⚠️ CRITIQUE

**Problème**: Utilisation de `redis.keys(pattern)` qui bloque Redis pendant l'exécution.

**Localisation**:
```139:150:polycool-rebuild/core/services/cache_manager.py
async def invalidate_pattern(self, pattern: str) -> int:
    try:
        keys = self.redis.keys(pattern)  # ❌ BLOQUE Redis
        if keys:
            result = self.redis.delete(*keys)
            self.stats['invalidations'] += result
            logger.info(f"Cache pattern invalidate: {pattern} ({result} keys)")
            return result
        return 0
    except Exception as e:
        logger.warning(f"Cache pattern invalidate error for {pattern}: {e}")
        return 0
```

**Impact**:
- **Blocage complet** de Redis pendant le scan (peut prendre plusieurs secondes avec beaucoup de clés)
- **Latence élevée** pour toutes les autres opérations Redis
- **Risque de timeout** pour les autres services
- **Performance dégradée** en production avec beaucoup de clés

**Solution Requise**: Utiliser `SCAN` au lieu de `KEYS`

---

### 2. **PAS DE POOL DE CONNEXIONS DANS CacheManager** ⚠️ HAUTE PRIORITÉ

**Problème**: `CacheManager` crée une connexion Redis sans pool, contrairement à `RedisPriceCache`.

**Comparaison**:

```33:35:polycool-rebuild/core/services/cache_manager.py
def __init__(self):
    """Initialize Redis connection"""
    self.redis = redis.Redis.from_url(settings.redis.url, decode_responses=True)
```

vs

```58:67:telegram-bot-v2/py-clob-server/core/services/redis_price_cache.py
self.redis_client = redis.from_url(
    redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
    retry_on_timeout=True,
    max_connections=20  # ✅ Pool de connexions
)
```

**Impact**:
- **Création de nouvelle connexion** à chaque opération (si connexion perdue)
- **Pas de réutilisation** des connexions
- **Risque de dépassement** du nombre max de connexions Redis
- **Performance dégradée** sous charge

**Solution Requise**: Ajouter un pool de connexions avec `ConnectionPool`

---

### 3. **INVALIDATION MANQUANTE DANS CERTAINS SERVICES** ⚠️ HAUTE PRIORITÉ

**Problème**: Certains services modifient des données sans invalider le cache.

**Exemples identifiés**:
- Workers mettent à jour les prix → cache du bot reste stale
- API crée position → invalidation partielle seulement
- Copy-trading listener → pas d'invalidation après trade

**Impact**:
- **Données obsolètes** dans le cache jusqu'à expiration TTL
- **Incohérence** entre DB et cache
- **Expérience utilisateur dégradée** (positions/marchés obsolètes)

**Solution Requise**: Invalidation systématique après toute modification

---

### 4. **PATTERNS D'INVALIDATION INCOHÉRENTS** ⚠️ MOYENNE PRIORITÉ

**Problème**: Différents patterns utilisés pour les mêmes données.

**Patterns trouvés**:
- `api:positions:{user_id}` (APIClient)
- `api:positions:*` (update_position_tpsl)
- `positions:{user_id}:*` (trade_service - incorrect)
- `market:{market_id}` vs `market_detail:{market_id}` (doublons)

**Impact**:
- **Invalidations manquées** (certaines clés ne sont pas invalidées)
- **Cache partiellement stale**
- **Maintenance difficile** (patterns non standardisés)

**Solution Requise**: Standardiser les patterns avec une classe `CacheKeys`

---

### 5. **PAS DE PUB/SUB POUR INVALIDATION DISTRIBUÉE** ⚠️ MOYENNE PRIORITÉ

**Problème**: Chaque service invalide son propre cache, mais pas celui des autres services.

**Scénario actuel**:
```
1. Worker met à jour prix → cache du bot reste stale
2. API crée position → cache du bot reste stale (si pas d'invalidation)
3. Bot invalide cache → mais workers/API ne sont pas notifiés
```

**Impact**:
- **Cache stale** entre services
- **Incohérence** des données
- **Performance dégradée** (cache misses fréquents)

**Solution Requise**: Utiliser Redis Pub/Sub pour invalidation distribuée (déjà implémenté pour copy-trading, mais pas pour cache)

---

### 6. **UTILISATION DE `redis.keys()` DANS AUTRES ENDROITS** ⚠️ MOYENNE PRIORITÉ

**Problème**: `redis.keys()` utilisé dans plusieurs endroits du code.

**Localisations**:
- `cache_manager.py` (ligne 150)
- `redis_price_cache.py` (lignes 1092, 1096, 1100)
- Potentiellement d'autres fichiers

**Impact**: Même problème de blocage que #1

---

### 7. **PAS DE MONITORING DE LA MÉMOIRE** ⚠️ BASSE PRIORITÉ

**Problème**: Pas de monitoring proactif de l'utilisation mémoire Redis.

**Configuration actuelle**:
- `maxmemory`: 256mb (dev) / non configuré en production
- `maxmemory-policy`: allkeys-lru

**Risques**:
- **Dépassement mémoire** non détecté
- **Éviction LRU** non surveillée
- **Performance dégradée** si mémoire saturée

**Solution Requise**: Monitoring et alertes sur utilisation mémoire

---

## ✅ Points Positifs

1. **CacheManager centralisé**: Une seule classe pour gérer le cache
2. **TTL Strategy**: Bonne séparation des TTL par type de données
3. **Redis Pub/Sub**: Déjà implémenté pour copy-trading
4. **Circuit breaker**: Protection contre API failures (dans RedisPriceCache)
5. **Metrics**: Stats de cache disponibles (hits, misses, sets)
6. **Invalidation partielle**: Certains services invalident correctement

---

## 🔧 Optimisations Recommandées

### Priorité 1: Fix Critique (Immédiat)

#### 1.1 Remplacer `redis.keys()` par `SCAN`

**Fichier**: `core/services/cache_manager.py`

```python
async def invalidate_pattern(self, pattern: str) -> int:
    """
    Invalidate all keys matching a pattern using SCAN (non-blocking)
    """
    try:
        keys = []
        cursor = 0

        # Use SCAN instead of KEYS (non-blocking)
        while True:
            cursor, batch = self.redis.scan(cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break

        if keys:
            # Delete in batches to avoid blocking
            result = 0
            batch_size = 100
            for i in range(0, len(keys), batch_size):
                batch = keys[i:i + batch_size]
                result += self.redis.delete(*batch)

            self.stats['invalidations'] += result
            logger.info(f"Cache pattern invalidate: {pattern} ({result} keys)")
            return result
        return 0
    except Exception as e:
        logger.warning(f"Cache pattern invalidate error for {pattern}: {e}")
        return 0
```

**Bénéfices**:
- ✅ Non-bloquant (ne bloque pas Redis)
- ✅ Peut être interrompu
- ✅ Meilleure performance sous charge

---

#### 1.2 Ajouter Pool de Connexions

**Fichier**: `core/services/cache_manager.py`

```python
import redis
from redis.connection import ConnectionPool

class CacheManager:
    _pool: Optional[ConnectionPool] = None

    def __init__(self):
        """Initialize Redis connection with connection pool"""
        if CacheManager._pool is None:
            CacheManager._pool = ConnectionPool.from_url(
                settings.redis.url,
                decode_responses=True,
                max_connections=20,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=True,
                health_check_interval=30
            )

        self.redis = redis.Redis(connection_pool=CacheManager._pool)
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'invalidations': 0,
        }
```

**Bénéfices**:
- ✅ Réutilisation des connexions
- ✅ Meilleure performance
- ✅ Protection contre dépassement de connexions

---

### Priorité 2: Améliorations Architecture

#### 2.1 Standardiser les Cache Keys

**Créer**: `core/services/cache_keys.py`

```python
class CacheKeys:
    """Standardized cache key patterns"""

    # Positions
    @staticmethod
    def user_positions(user_id: int) -> str:
        return f"api:positions:{user_id}"

    @staticmethod
    def positions_pattern(user_id: int) -> str:
        return f"api:positions:{user_id}*"

    @staticmethod
    def all_positions_pattern() -> str:
        return "api:positions:*"

    # Markets
    @staticmethod
    def market(market_id: str) -> str:
        return f"market:{market_id}"

    @staticmethod
    def market_detail(market_id: str) -> str:
        return f"market_detail:{market_id}"

    @staticmethod
    def market_by_condition(condition_id: str) -> str:
        return f"market_by_condition:{condition_id}"

    @staticmethod
    def markets_list_pattern() -> str:
        return "api:markets:*"

    # User data
    @staticmethod
    def user_profile(telegram_user_id: int) -> str:
        return f"api:user:{telegram_user_id}"

    # Prices
    @staticmethod
    def price(market_id: str) -> str:
        return f"price:{market_id}"
```

**Utilisation**:
```python
from core.services.cache_keys import CacheKeys

# Au lieu de:
await cache_manager.delete(f"api:positions:{user_id}")

# Utiliser:
await cache_manager.delete(CacheKeys.user_positions(user_id))
```

---

#### 2.2 Redis Pub/Sub pour Invalidation Distribuée

**Créer**: `core/services/cache_invalidation_pubsub.py`

```python
class CacheInvalidationPubSub:
    """Redis Pub/Sub for distributed cache invalidation"""

    CHANNEL = "cache:invalidate"

    def __init__(self):
        self.redis = redis.Redis.from_url(settings.redis.url, decode_responses=True)
        self.pubsub = self.redis.pubsub()
        self._subscribed = False

    async def publish_invalidation(self, pattern: str, reason: str = "unknown"):
        """Publish invalidation event to all services"""
        message = {
            "pattern": pattern,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }
        subscribers = await self.redis.publish(
            self.CHANNEL,
            json.dumps(message)
        )
        logger.debug(f"Published invalidation: {pattern} ({subscribers} subscribers)")
        return subscribers

    async def subscribe(self, callback: Callable[[str], None]):
        """Subscribe to invalidation events"""
        if not self._subscribed:
            await self.pubsub.subscribe(self.CHANNEL)
            self._subscribed = True

        async for message in self.pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                await callback(data['pattern'])
```

**Utilisation dans API Service**:
```python
# Après création position
await pubsub.publish_invalidation(
    CacheKeys.positions_pattern(user_id),
    reason="position_created"
)
```

**Utilisation dans Bot Service**:
```python
# Au démarrage
async def handle_invalidation(pattern: str):
    await cache_manager.invalidate_pattern(pattern)

await pubsub.subscribe(handle_invalidation)
```

---

### Priorité 3: Optimisations Performance

#### 3.1 Compression des Données Volumineuses

**Problème**: Les données JSON volumineuses (listes de marchés, positions) prennent beaucoup de mémoire.

**Solution**: Compresser avec `zlib` avant stockage

```python
import zlib
import json

async def set(self, key: str, value: Any, data_type: str = 'default', ttl: Optional[int] = None):
    # Serialize
    serialized = json.dumps(value)

    # Compress if large (>1KB)
    if len(serialized) > 1024:
        compressed = zlib.compress(serialized.encode())
        # Store with compression marker
        self.redis.setex(f"{key}:compressed", ttl, compressed)
    else:
        self.redis.setex(key, ttl, serialized)

async def get(self, key: str, data_type: str = 'default'):
    # Try compressed first
    compressed = self.redis.get(f"{key}:compressed")
    if compressed:
        decompressed = zlib.decompress(compressed).decode()
        return json.loads(decompressed)

    # Fallback to uncompressed
    value = self.redis.get(key)
    if value:
        return json.loads(value)
    return None
```

**Bénéfices**:
- ✅ Réduction mémoire ~40-60% pour données volumineuses
- ✅ Moins d'évictions LRU
- ✅ Meilleure performance

---

#### 3.2 Monitoring de la Mémoire

**Ajouter**: Méthode de monitoring dans `CacheManager`

```python
async def get_memory_stats(self) -> Dict[str, Any]:
    """Get Redis memory usage statistics"""
    try:
        info = self.redis.info('memory')
        stats = self.redis.info('stats')

        used_memory = info.get('used_memory', 0)
        max_memory = info.get('maxmemory', 0) or (256 * 1024 * 1024)  # 256MB default
        memory_usage_pct = (used_memory / max_memory) * 100 if max_memory > 0 else 0

        # Count keys by pattern
        key_counts = {}
        patterns = ['api:positions:*', 'market:*', 'price:*', 'api:user:*']
        for pattern in patterns:
            count = 0
            cursor = 0
            while True:
                cursor, keys = self.redis.scan(cursor, match=pattern, count=100)
                count += len(keys)
                if cursor == 0:
                    break
            key_counts[pattern] = count

        return {
            'used_memory_mb': round(used_memory / (1024 * 1024), 2),
            'max_memory_mb': round(max_memory / (1024 * 1024), 2),
            'memory_usage_pct': round(memory_usage_pct, 2),
            'key_counts': key_counts,
            'evicted_keys': stats.get('evicted_keys', 0),
            'keyspace_hits': stats.get('keyspace_hits', 0),
            'keyspace_misses': stats.get('keyspace_misses', 0),
        }
    except Exception as e:
        logger.error(f"Error getting memory stats: {e}")
        return {}
```

**Utilisation**: Exposer via endpoint `/health/cache` ou métriques Prometheus

---

#### 3.3 TTL Adaptatif

**Problème**: TTL fixes ne s'adaptent pas à la volatilité des données.

**Solution**: TTL adaptatif basé sur la fréquence d'accès

```python
async def get(self, key: str, data_type: str = 'default') -> Optional[Any]:
    value = self.redis.get(key)
    if value:
        # Extend TTL if frequently accessed (cache warming)
        ttl = self.redis.ttl(key)
        if ttl and ttl < self.TTL_STRATEGY.get(data_type, 300) * 0.5:
            # Extend to full TTL if accessed in last half of TTL
            self.redis.expire(key, self.TTL_STRATEGY.get(data_type, 300))

        self.stats['hits'] += 1
        return json.loads(value)

    self.stats['misses'] += 1
    return None
```

---

## 📋 Checklist de Correction

### Phase 1: Fix Critique (Immédiat)
- [ ] Remplacer `redis.keys()` par `SCAN` dans `cache_manager.py`
- [ ] Remplacer `redis.keys()` par `SCAN` dans `redis_price_cache.py`
- [ ] Ajouter pool de connexions dans `CacheManager`
- [ ] Tester performance avec beaucoup de clés

### Phase 2: Standardisation (Court terme)
- [ ] Créer module `CacheKeys` avec patterns standardisés
- [ ] Refactoriser tous les appels pour utiliser `CacheKeys`
- [ ] Documenter les patterns de cache keys
- [ ] Ajouter tests unitaires pour cache invalidation

### Phase 3: Architecture Distribuée (Moyen terme)
- [ ] Implémenter Redis Pub/Sub pour invalidation distribuée
- [ ] Ajouter subscription dans tous les services
- [ ] Tester invalidation cross-service
- [ ] Monitoring des invalidations Pub/Sub

### Phase 4: Optimisations (Long terme)
- [ ] Compression des données volumineuses
- [ ] Monitoring de la mémoire Redis
- [ ] TTL adaptatif
- [ ] Métriques Prometheus pour cache

---

## 🧪 Tests Recommandés

### Test 1: Performance avec SCAN vs KEYS
```python
async def test_scan_vs_keys_performance():
    # Créer 10,000 clés de test
    # Mesurer temps avec KEYS vs SCAN
    # Vérifier que SCAN ne bloque pas Redis
```

### Test 2: Pool de Connexions
```python
async def test_connection_pool():
    # Créer 100 requêtes simultanées
    # Vérifier que pool réutilise connexions
    # Vérifier pas de dépassement max_connections
```

### Test 3: Invalidation Distribuée
```python
async def test_pubsub_invalidation():
    # API service publie invalidation
    # Bot service reçoit et invalide cache
    # Vérifier cache est bien invalidé
```

---

## 📊 Métriques à Surveiller

1. **Cache Hit Rate**: `hits / (hits + misses) * 100`
   - Objectif: >80%
   - Alerte si <70%

2. **Mémoire Redis**: `used_memory / max_memory * 100`
   - Objectif: <70%
   - Alerte si >80%
   - Critique si >90%

3. **Évictions LRU**: `evicted_keys` (croissance)
   - Alerte si >1000/heure

4. **Latence Redis**: Temps de réponse moyen
   - Objectif: <5ms (p95)
   - Alerte si >10ms

5. **Connexions Redis**: Nombre de connexions actives
   - Objectif: <50% de max_connections
   - Alerte si >80%

---

## 🎯 Conclusion

Le cache Redis actuel fonctionne bien mais présente plusieurs **enjeux critiques** qui peuvent impacter la performance et la stabilité en production:

1. **Blocage avec `KEYS`** - Impact critique sur performance
2. **Pas de pool de connexions** - Risque de dépassement
3. **Invalidation manquante** - Données stale
4. **Patterns incohérents** - Maintenance difficile

**Actions immédiates requises**:
1. Remplacer `KEYS` par `SCAN` (priorité absolue)
2. Ajouter pool de connexions
3. Standardiser les patterns de clés
4. Implémenter invalidation distribuée via Pub/Sub

Ces corrections amélioreront significativement la performance, la stabilité et la maintenabilité du système de cache.

---

## 📚 Références

- CacheManager: `core/services/cache_manager.py`
- RedisPubSubService: `core/services/redis_pubsub/redis_pubsub_service.py`
- Configuration: `infrastructure/config/settings.py`
- Audit précédent: `docs/CACHE_MANAGEMENT_AUDIT.md`
