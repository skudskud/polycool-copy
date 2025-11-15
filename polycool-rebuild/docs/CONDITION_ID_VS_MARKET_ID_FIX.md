# 🔧 Fix: Conversion condition_id → market_id et URL API

## 🐛 Problèmes Identifiés

### 1. URL API Malformée

**Erreur dans les logs:**
```
PUT http://localhost:8000/api/v1/api/v1/markets/0xcb111226...
```

**Cause:** Le `base_url` contient déjà `/api/v1`, donc on ne doit pas l'ajouter à nouveau.

### 2. condition_id vs market_id

**Problème:** Le WebSocket envoie un `condition_id` (hash hexadécimal comme `0xcb111226...`) dans le champ `market`, mais notre API attend un `market_id` (ID numérique comme `570361`).

**Erreur dans les logs:**
```
⚠️ Market 0xcb111226a8271fed0c71bb5ec1bd67b2a4fd72f1eb08466e2180b9efa99d3f32 not found via API
```

**Explication:**
- **`condition_id`**: Identifiant unique Polymarket pour une condition de marché (hash hexadécimal, ex: `0xcb111226...`)
- **`market_id`**: Identifiant numérique utilisé dans notre DB comme clé primaire (ex: `570361`)
- **Relation**: Un `market_id` peut avoir un `condition_id` associé dans la table `markets`

### 3. CacheManager.invalidate

**Erreur:** `'CacheManager' object has no attribute 'invalidate'`

**Cause:** La méthode correcte est `delete()` pour une clé spécifique ou `invalidate_pattern()` pour un pattern.

## ✅ Solutions Appliquées

### 1. Correction de l'URL API

**Fichier:** `data_ingestion/streamer/market_updater/market_updater.py`

**Avant:**
```python
response = await api_client.client.put(
    f"{api_client.base_url}/api/v1/markets/{market_id}",
    ...
)
```

**Après:**
```python
response = await api_client.client.put(
    f"{api_client.base_url}/markets/{market_id}",  # base_url contient déjà /api/v1
    ...
)
```

### 2. Conversion condition_id → market_id

**Fichier:** `data_ingestion/streamer/market_updater/market_updater.py`

**Ajout de la détection et conversion:**

```python
# Détecter si c'est un condition_id (hash hex) ou market_id (numeric)
if market_identifier.startswith("0x") or len(market_identifier) > 20:
    # C'est un condition_id, convertir en market_id
    condition_id = market_identifier
    market_id = await self._get_market_id_from_condition_id(condition_id)
elif market_identifier.isdigit():
    # C'est déjà un market_id
    market_id = market_identifier
```

**Nouvelle méthode `_get_market_id_from_condition_id()`:**

```python
async def _get_market_id_from_condition_id(self, condition_id: str) -> Optional[str]:
    """Convert condition_id to market_id by searching in markets table"""
    if SKIP_DB:
        # Note: No API endpoint to search by condition_id yet
        return None

    async with get_db() as db:
        result = await db.execute(
            select(Market.id).where(Market.condition_id == condition_id)
        )
        return result.scalar_one_or_none()
```

### 3. Correction CacheManager

**Remplacement de `invalidate()` par `delete()`:**

```python
# Avant
await cache_manager.invalidate(f"price:{market_id}")

# Après
await cache_manager.delete(f"price:{market_id}")
await cache_manager.delete(f"market:{market_id}")
await cache_manager.delete(f"market_detail:{market_id}")
```

Pour les patterns:
```python
# Avant
await cache_manager.invalidate(f"api:positions:{user_id}")

# Après
await cache_manager.invalidate_pattern(f"api:positions:{user_id}*")
```

## 🎯 Résultat Attendu

Après ces corrections:

1. **URL correcte:**
   ```
   PUT http://localhost:8000/api/v1/markets/570361
   ```

2. **Conversion condition_id → market_id:**
   ```
   🔍 WebSocket sent condition_id: 0xcb111226...
   ✅ Converted condition_id 0xcb111226... to market_id 570361
   📝 Updating market 570361 via API with source='ws', prices=[...]
   ✅ Updated market 570361 with source='ws' via API
   ```

3. **Pas d'erreur CacheManager:**
   ```
   ✅ Cache invalidated successfully
   ```

## 📊 Comparaison condition_id vs market_id

| Propriété | condition_id | market_id |
|-----------|--------------|-----------|
| Format | Hash hexadécimal (`0xcb111226...`) | ID numérique (`570361`) |
| Source | Polymarket WebSocket | Notre DB (clé primaire) |
| Longueur | ~66 caractères | 5-6 chiffres |
| Usage | Identifiant Polymarket unique | Clé primaire dans notre DB |
| Conversion | Chercher dans `markets.condition_id` | Direct (clé primaire) |

## ✅ Fix Appliqué

- ✅ URL API corrigée (plus de double `/api/v1`)
- ✅ Détection et conversion `condition_id → market_id` ajoutée
- ✅ Méthode `_get_market_id_from_condition_id()` créée
- ✅ `CacheManager.invalidate()` remplacé par `delete()` et `invalidate_pattern()`
- ✅ Endpoint API `GET /api/v1/markets/by-condition-id/{condition_id}` créé avec support SKIP_DB
- ✅ Méthode `MarketService.get_market_by_condition_id()` ajoutée pour recherche par condition_id

## 🎯 Support SKIP_DB=true

L'endpoint `/by-condition-id/{condition_id}` utilise maintenant `MarketService` au lieu d'un accès DB direct, ce qui permet:
- ✅ Support complet de `SKIP_DB=true` (le service API peut utiliser le service de marché)
- ✅ Cache optimisé (cache par `condition_id` et `market_id`)
- ✅ Cohérence avec les autres endpoints API
- ✅ Le `market_updater` peut maintenant convertir `condition_id → market_id` via l'API même avec `SKIP_DB=true`
