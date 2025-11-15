# 🔍 Audit Cache Management - Architecture Microservices

**Date**: 2025-01-12
**Contexte**: Architecture microservices avec Bot (SKIP_DB=true) et API Service (SKIP_DB=false)

---

## 📊 Architecture Actuelle

### Services et Cache

1. **Bot Service** (`SKIP_DB=true`)
   - Utilise `APIClient` pour toutes les opérations DB
   - Cache via `CacheManager` (Redis)
   - Cache keys: `api:positions:{user_id}`, `api:user:{telegram_id}`, etc.

2. **API Service** (`SKIP_DB=false`)
   - Accès direct à la DB (Supabase)
   - **❌ PROBLÈME CRITIQUE**: Ne fait PAS d'invalidation de cache après écriture

3. **Workers Service** (data ingestion)
   - Met à jour les prix des markets
   - Met à jour les positions via `batch_update_positions_prices`
   - **❌ PROBLÈME**: Ne fait PAS d'invalidation de cache

4. **Indexer Service**
   - Récupère les transactions des leaders
   - Pas d'interaction directe avec le cache

---

## 🚨 Problèmes Critiques Identifiés

### 1. **INVALIDATION MANQUANTE DANS L'API SERVICE** ⚠️ CRITIQUE

**Problème**: Quand l'API service crée/modifie une position directement en DB, le cache du bot reste stale.

**Exemple**:
```python
# telegram_bot/api/v1/positions.py - create_position()
position = await position_service.create_position(...)  # ✅ Écrit en DB
# ❌ MANQUE: Invalidation du cache Redis
return {...}  # Retourne la position
```

**Impact**:
- Le bot peut voir des positions obsolètes pendant jusqu'à 3 minutes (TTL positions)
- Incohérence entre DB et cache
- Utilisateurs voient des données incorrectes

**Solution Requise**:
```python
# Après création/modification de position dans l'API service
from core.services.cache_manager import CacheManager
cache_manager = CacheManager()
await cache_manager.invalidate_pattern(f"api:positions:{user_id}")
```

---

### 2. **RACE CONDITION SUR L'INVALIDATION** ⚠️ HAUTE PRIORITÉ

**Problème**: Le bot invalide le cache AVANT que l'API service ait fini d'écrire en DB.

**Flow actuel**:
```
1. Bot: POST /positions/ → invalide cache immédiatement
2. API: Écrit en DB (peut prendre 100-500ms)
3. Bot: GET /positions/user/{id} → cache miss → récupère depuis API
4. API: Peut retourner données obsolètes si DB write pas encore commit
```

**Impact**:
- Cache invalidation prématurée
- Possibilité de récupérer des données incomplètes

**Solution**: Invalider le cache APRÈS confirmation de succès de l'API.

---

### 3. **PATTERNS D'INVALIDATION INCOHÉRENTS** ⚠️ MOYENNE PRIORITÉ

**Problème**: Différents patterns utilisés pour invalider le cache.

**Patterns trouvés**:
- `api:positions:{user_id}` (APIClient)
- `api:positions:*` (update_position_tpsl)
- `positions:{user_id}:*` (trade_service - pattern incorrect)
- Pas de pattern standardisé

**Impact**:
- Certaines invalidations peuvent manquer des clés
- Cache partiellement stale

**Solution**: Standardiser les patterns de cache keys.

---

### 4. **PAS DE PUB/SUB POUR INVALIDATION DISTRIBUÉE** ⚠️ MOYENNE PRIORITÉ

**Problème**: Chaque service invalide son propre cache, mais pas celui des autres services.

**Scénario**:
- Worker service met à jour les prix → cache du bot reste stale
- API service crée position → cache du bot reste stale
- Bot invalide cache → mais workers/API ne sont pas notifiés

**Solution**: Utiliser Redis Pub/Sub pour invalidation distribuée.

---

### 5. **TTL STRATEGY - VÉRIFICATION NÉCESSAIRE** ⚠️ BASSE PRIORITÉ

**TTL Actuels**:
- `prices`: 20s ✅ (OK pour données temps réel)
- `positions`: 180s (3min) ⚠️ (Peut être trop long après trade)
- `markets`: 300s (5min) ✅ (OK)
- `user_profile`: 3600s (1h) ✅ (OK)

**Problème Potentiel**:
- TTL positions de 3min peut causer des données stale après un trade
- Solution: Invalidation immédiate après trade (déjà fait côté bot)

---

## ✅ Points Positifs

1. **CacheManager centralisé**: Une seule classe pour gérer le cache
2. **TTL Strategy**: Bonne séparation des TTL par type de données
3. **Invalidation côté bot**: Le bot invalide correctement après création
4. **Metrics**: Stats de cache disponibles
5. **Circuit breaker**: Protection contre API failures

---

## 🔧 Recommandations

### Priorité 1: Fix Critique

#### 1.1 Ajouter invalidation dans API Service

**Fichier**: `telegram_bot/api/v1/positions.py`

```python
@router.post("/", response_model=dict)
async def create_position(request: CreatePositionRequest):
    # ... création position ...

    # ✅ AJOUTER: Invalider cache après création
    try:
        from core.services.cache_manager import CacheManager
        cache_manager = CacheManager()
        await cache_manager.invalidate_pattern(f"api:positions:{request.user_id}")
        logger.info(f"✅ Cache invalidated for user {request.user_id} after position creation")
    except Exception as e:
        logger.warning(f"⚠️ Cache invalidation failed (non-fatal): {e}")

    return {...}
```

**À faire aussi pour**:
- `update_position_tpsl()`
- `sync_positions()`
- Toute modification de position dans l'API service

#### 1.2 Déplacer invalidation après confirmation API

**Fichier**: `core/services/api_client/api_client.py`

```python
async def create_position(...):
    # ❌ SUPPRIMER: Invalidation avant appel API
    # await self.cache_manager.invalidate_pattern(f"api:positions:{user_id}")

    # Appel API
    result = await self._post("/positions/", json_data)

    # ✅ AJOUTER: Invalidation APRÈS succès
    if result:
        await self.cache_manager.invalidate_pattern(f"api:positions:{user_id}")

    return result
```

### Priorité 2: Améliorations Architecture

#### 2.1 Standardiser les Cache Keys

**Créer un module**: `core/services/cache_keys.py`

```python
class CacheKeys:
    """Standardized cache key patterns"""

    @staticmethod
    def user_positions(user_id: int) -> str:
        return f"api:positions:{user_id}"

    @staticmethod
    def user_position(position_id: int) -> str:
        return f"api:position:{position_id}"

    @staticmethod
    def user_profile(telegram_user_id: int) -> str:
        return f"api:user:{telegram_user_id}"

    @staticmethod
    def positions_pattern(user_id: int) -> str:
        return f"api:positions:{user_id}*"

    @staticmethod
    def all_positions_pattern() -> str:
        return "api:positions:*"
```

#### 2.2 Redis Pub/Sub pour Invalidation Distribuée

**Créer**: `core/services/cache_invalidation_pubsub.py`

```python
class CacheInvalidationPubSub:
    """Redis Pub/Sub for distributed cache invalidation"""

    CHANNEL = "cache:invalidate"

    async def publish_invalidation(self, pattern: str):
        """Publish invalidation event to all services"""
        await self.redis.publish(self.CHANNEL, json.dumps({
            "pattern": pattern,
            "timestamp": datetime.utcnow().isoformat()
        }))

    async def subscribe(self, callback):
        """Subscribe to invalidation events"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.CHANNEL)
        async for message in pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                await callback(data['pattern'])
```

**Utilisation**:
```python
# Dans API service après création position
await pubsub.publish_invalidation(f"api:positions:{user_id}")

# Dans Bot service (subscribe au démarrage)
async def handle_invalidation(pattern: str):
    await cache_manager.invalidate_pattern(pattern)
await pubsub.subscribe(handle_invalidation)
```

### Priorité 3: Monitoring et Debugging

#### 3.1 Ajouter Logging Structuré

```python
logger.info("CACHE_INVALIDATION", extra={
    "service": "api",
    "pattern": f"api:positions:{user_id}",
    "reason": "position_created",
    "user_id": user_id
})
```

#### 3.2 Métriques de Cache Coherence

```python
# Track cache misses après invalidation
cache_misses_after_invalidation = 0
cache_hits_after_invalidation = 0
```

---

## 📋 Checklist de Correction

### Phase 1: Fix Critique (Immédiat)
- [ ] Ajouter invalidation cache dans `create_position()` API service
- [ ] Ajouter invalidation cache dans `update_position_tpsl()` API service
- [ ] Ajouter invalidation cache dans `sync_positions()` API service
- [ ] Déplacer invalidation après confirmation API dans `APIClient.create_position()`
- [ ] Tester flow complet: Bot → API → Cache invalidation

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

### Phase 4: Monitoring (Long terme)
- [ ] Métriques de cache coherence
- [ ] Alertes sur cache stale détecté
- [ ] Dashboard cache hit/miss rates
- [ ] Logs structurés pour debugging

---

## 🧪 Tests Recommandés

### Test 1: Cache Coherence After Position Creation
```python
async def test_cache_invalidation_after_position_creation():
    # 1. Créer position via API service
    # 2. Vérifier que cache est invalidé
    # 3. Vérifier que bot récupère position fraîche
```

### Test 2: Race Condition Prevention
```python
async def test_no_race_condition_on_invalidation():
    # 1. Bot invalide cache
    # 2. API écrit en DB (simuler délai)
    # 3. Bot récupère position → doit être fraîche
```

### Test 3: Cross-Service Invalidation
```python
async def test_pubsub_invalidation():
    # 1. API service publie invalidation
    # 2. Bot service reçoit et invalide cache
    # 3. Vérifier cache est bien invalidé
```

---

## 📚 Références

- Cache Keys Patterns: `core/services/cache_manager.py`
- API Client: `core/services/api_client/api_client.py`
- Position Service: `core/services/position/position_service.py`
- API Routes: `telegram_bot/api/v1/positions.py`

---

## 🎯 Conclusion

Le cache management actuel fonctionne bien côté bot mais manque d'invalidation côté API service. C'est un problème critique qui peut causer des données stale pour les utilisateurs.

**Action immédiate requise**: Ajouter invalidation cache dans l'API service après toute modification de position.




