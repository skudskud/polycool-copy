# 🔍 Audit de Performance - Bot Telegram & Base de Données

**Date**: 2025-01-12
**Contexte**: Architecture microservices (Bot SKIP_DB=true, API SKIP_DB=false, Workers)
**Projet**: Polycool Telegram Bot

---

## 📊 Résumé Exécutif

### Problèmes Critiques Identifiés

1. **❌ CRITIQUE**: Appels API répétitifs pour récupérer les marchés dans les positions
2. **⚠️ HAUTE PRIORITÉ**: Invalidation de cache trop agressive avec `invalidate_pattern`
3. **⚠️ HAUTE PRIORITÉ**: Requêtes DB non optimisées dans les handlers
4. **⚠️ MOYENNE PRIORITÉ**: Débounce insuffisant pour les mises à jour de positions
5. **⚠️ MOYENNE PRIORITÉ**: Pas de batch fetching pour les marchés multiples

---

## 🚨 Problèmes Détailés

### 1. Appels API Répétitifs pour les Marchés (CRITIQUE)

**Localisation**: `telegram_bot/bot/handlers/positions_handler.py:266-270`

**Problème**:
```python
# Get cached markets
for position in positions:
    if position.market_id not in markets_map:
        market = await api_client.get_market(position.market_id)  # ❌ Appel API par position
        if market:
            markets_map[position.market_id] = market
```

**Impact**:
- Si un utilisateur a 10 positions, cela génère **10 appels API séquentiels**
- Chaque appel prend ~100-300ms
- **Latence totale: 1-3 secondes** juste pour récupérer les marchés
- Surcharge inutile de l'API et de la DB Supabase

**Solution Recommandée**:
```python
# Batch fetch all markets at once
if positions:
    market_ids = list(set(p.market_id for p in positions))
    markets_data = await api_client.get_markets_batch(market_ids)  # ✅ Un seul appel
    markets_map = {m['id']: m for m in markets_data}
```

**Priorité**: 🔴 CRITIQUE - Impact direct sur la latence utilisateur

---

### 2. Invalidation de Cache Trop Agressive (HAUTE PRIORITÉ)

**Localisation**: Multiple fichiers

**Problème**:
```python
# Dans api_client.py et positions.py
await cache_manager.invalidate_pattern("api:positions:*")  # ❌ Invalide TOUTES les positions
```

**Impact**:
- Invalide le cache pour **TOUS les utilisateurs** alors qu'un seul utilisateur a changé
- Force tous les utilisateurs à refaire des requêtes DB/API
- Augmente la charge sur Supabase de manière exponentielle
- Perte de performance du cache (hit rate réduit)

**Exemples Trouvés**:
- `api_client.py:512` - `invalidate_pattern("api:positions:*")`
- `api_client.py:562` - `invalidate_pattern("api:positions:*")`
- `tpsl_handler.py` - Invalidation trop large

**Solution Recommandée**:
```python
# Invalider uniquement pour l'utilisateur concerné
await cache_manager.invalidate_pattern(f"api:positions:{user_id}")  # ✅ Ciblé
await cache_manager.delete(f"api:position:{position_id}")  # ✅ Spécifique
```

**Priorité**: 🟠 HAUTE - Impact sur la charge DB et performance globale

---

### 3. Requêtes DB Non Optimisées (HAUTE PRIORITÉ)

**Localisation**: `telegram_bot/api/v1/positions.py`

**Problème**:
```python
# Dans sync_positions
synced_count = await position_service.sync_positions_from_blockchain(...)  # 1 requête
updated_count = await position_service.update_all_positions_prices(user_id)  # N requêtes
```

**Impact**:
- `update_all_positions_prices` fait une requête DB par position
- Pour 20 positions = 20 requêtes DB séquentielles
- Pas de batch update
- Surcharge Supabase avec trop de connexions

**Solution Recommandée**:
```python
# Batch update en une seule transaction
await position_service.batch_update_positions_prices(
    user_id=user_id,
    position_updates=updates  # Liste de {position_id, current_price}
)
```

**Priorité**: 🟠 HAUTE - Impact direct sur la charge Supabase

---

### 4. Débounce Insuffisant pour Positions (MOYENNE PRIORITÉ)

**Localisation**: `data_ingestion/streamer/market_updater/market_updater.py:59-60`

**Problème**:
```python
self.position_debounce = DebounceManager(delay=10.0, max_updates_per_second=5)  # 10s delay
```

**Impact**:
- Avec 1000 marchés actifs et mises à jour WebSocket fréquentes
- 5 updates/seconde = 300 updates/minute
- Si chaque update déclenche une requête DB pour les positions → surcharge
- Le délai de 10s peut être trop court pour les marchés très actifs

**Solution Recommandée**:
```python
# Augmenter le délai et réduire le taux
self.position_debounce = DebounceManager(
    delay=15.0,  # ✅ Augmenté à 15s
    max_updates_per_second=2  # ✅ Réduit à 2/sec
)
```

**Priorité**: 🟡 MOYENNE - Impact sur la charge DB lors de pics d'activité

---

### 5. Pas de Batch Fetching pour Marchés (MOYENNE PRIORITÉ)

**Localisation**: `core/services/api_client/api_client.py`

**Problème**:
- Pas de méthode `get_markets_batch()` dans `APIClient`
- Chaque handler doit faire des appels individuels
- Multiplie les requêtes HTTP et DB

**Solution Recommandée**:
```python
async def get_markets_batch(
    self,
    market_ids: List[str],
    use_cache: bool = True
) -> Optional[List[Dict[str, Any]]]:
    """
    Get multiple markets in a single API call

    Args:
        market_ids: List of market IDs
        use_cache: Whether to use cache

    Returns:
        List of market dicts
    """
    # Endpoint: POST /markets/batch
    # Body: {"market_ids": [...]}
    # Returns: {"markets": [...]}
```

**Priorité**: 🟡 MOYENNE - Amélioration significative de la latence

---

## 📈 État des Lieux - Gestion du Cache

### Configuration Actuelle

**TTL Strategy** (`cache_manager.py:23-31`):
```python
TTL_STRATEGY = {
    'prices': 20s,           # ✅ Ultra-court (OK)
    'positions': 30s,        # ✅ Court (réduit de 3min, bon)
    'markets_list': 5min,    # ✅ Moyen (OK)
    'market_detail': 5min,    # ✅ Moyen (OK)
    'user_profile': 1h,      # ✅ Long (OK)
    'smart_trades': 5min,    # ✅ Moyen (OK)
    'leaderboard': 1h,       # ✅ Long (OK)
}
```

**✅ Points Positifs**:
- TTL bien configurés selon le type de données
- Cache Redis fonctionnel
- Invalidation présente dans l'API service

**❌ Points à Améliorer**:
- Invalidation trop large (pattern `*` au lieu de ciblé)
- Pas de métriques de cache hit rate en production
- Pas de cache warming pour les données fréquentes

---

### Cache Hit Rate (Estimation)

**Scénarios**:
- **Positions**: ~70% hit rate (TTL 30s, invalidation fréquente)
- **Markets**: ~85% hit rate (TTL 5min, données stables)
- **User Profile**: ~95% hit rate (TTL 1h, changements rares)

**Problème**: Invalidation trop agressive réduit le hit rate réel

---

## 🔧 Recommandations d'Optimisation

### Priorité 1 - Immédiat (Impact Critique)

1. **Implémenter Batch Fetching pour Marchés**
   - Créer endpoint `/markets/batch` dans l'API
   - Ajouter méthode `get_markets_batch()` dans `APIClient`
   - Modifier `positions_handler.py` pour utiliser batch

2. **Corriger Invalidation de Cache**
   - Remplacer `invalidate_pattern("api:positions:*")` par `invalidate_pattern(f"api:positions:{user_id}")`
   - Fichiers à modifier:
     - `core/services/api_client/api_client.py:512, 562`
     - Vérifier tous les usages de `invalidate_pattern`

3. **Optimiser Requêtes DB Positions**
   - Implémenter `batch_update_positions_prices()` dans `position_service`
   - Utiliser une seule transaction pour toutes les mises à jour

### Priorité 2 - Court Terme (Impact Important)

4. **Améliorer Débounce**
   - Augmenter délai position updates à 15s
   - Réduire max_updates_per_second à 2

5. **Ajouter Métriques Cache**
   - Logger cache hit rate par type de données
   - Alertes si hit rate < 50%

6. **Optimiser Requêtes API**
   - Utiliser `use_cache=True` par défaut (déjà fait ✅)
   - Éviter `use_cache=False` sauf si nécessaire

### Priorité 3 - Moyen Terme (Amélioration Continue)

7. **Cache Warming**
   - Pré-charger les marchés populaires au démarrage
   - Pré-charger les positions des utilisateurs actifs

8. **Connection Pooling**
   - Vérifier que le pool DB est bien configuré (actuellement: pool_size=3, max_overflow=5)
   - Monitorer les connexions actives

9. **Rate Limiting**
   - Vérifier que le rate limiting API client fonctionne (100 req/min ✅)
   - Ajouter rate limiting côté API pour protéger Supabase

---

## 📊 Métriques à Surveiller

### Base de Données Supabase

1. **Connexions Actives**
   - Cible: < 50 connexions simultanées
   - Alerte si > 80 connexions

2. **Requêtes par Seconde**
   - Cible: < 100 req/s
   - Alerte si > 200 req/s

3. **Latence P95**
   - Cible: < 100ms
   - Alerte si > 500ms

### API Service

1. **Latence Endpoints**
   - `/positions/user/{id}`: Cible < 200ms
   - `/markets/{id}`: Cible < 150ms
   - `/markets/batch`: Cible < 300ms (à créer)

2. **Taux d'Erreur**
   - Cible: < 1%
   - Alerte si > 5%

### Cache Redis

1. **Hit Rate Global**
   - Cible: > 70%
   - Alerte si < 50%

2. **Mémoire Utilisée**
   - Surveiller l'utilisation mémoire Redis
   - Alerte si > 80% de la capacité

---

## 🎯 Plan d'Action Immédiat

### Semaine 1

- [ ] Implémenter `get_markets_batch()` dans APIClient
- [ ] Créer endpoint `/markets/batch` dans l'API
- [ ] Modifier `positions_handler.py` pour utiliser batch
- [ ] Corriger toutes les invalidations de cache trop larges

### Semaine 2

- [ ] Implémenter `batch_update_positions_prices()`
- [ ] Optimiser `sync_positions` pour utiliser batch
- [ ] Ajuster paramètres débounce

### Semaine 3

- [ ] Ajouter métriques cache hit rate
- [ ] Implémenter monitoring connexions DB
- [ ] Tests de charge pour valider les améliorations

---

## 📝 Notes Techniques

### Architecture Actuelle

```
Bot (SKIP_DB=true)
  ↓ HTTP
API Service (SKIP_DB=false)
  ↓ SQL
Supabase PostgreSQL
  ↑
Redis Cache (shared)
```

### Points d'Attention

1. **Race Conditions**: L'invalidation de cache côté bot et API peut créer des race conditions
   - Solution: Invalider uniquement côté API après écriture DB

2. **Cache Coherence**: Le cache doit être invalidé après chaque écriture
   - ✅ Déjà fait dans l'API service
   - ⚠️ À améliorer: invalidation plus ciblée

3. **Connection Pooling**: Supabase Pooler (port 6543) utilisé
   - ✅ Configuration correcte
   - ⚠️ Pool size peut être augmenté si nécessaire

---

## ✅ Conclusion

**Problèmes Identifiés**: 5 problèmes majeurs
**Impact Estimé**:
- Réduction latence: **-60%** (batch fetching)
- Réduction charge DB: **-40%** (invalidation ciblée)
- Amélioration hit rate cache: **+15%**

**Effort Estimé**:
- Priorité 1: 2-3 jours
- Priorité 2: 1-2 jours
- Priorité 3: 3-5 jours

**ROI**: Très élevé - améliorations critiques pour la scalabilité
