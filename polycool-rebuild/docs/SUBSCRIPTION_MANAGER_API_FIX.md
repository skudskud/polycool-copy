# 🔧 Fix: SubscriptionManager Utilise Maintenant l'API avec SKIP_DB=true

## 🐛 Problème Identifié

Le `SubscriptionManager` essayait d'accéder à la DB directement avec `get_db()`, ce qui échouait quand `SKIP_DB=true`:

**Erreurs dans les logs:**
```
⚠️ Error subscribing active positions: Database not initialized. Call init_db() first.
⚠️ Error getting token IDs for market 570361: Database not initialized. Call init_db() first.
⚠️ No token IDs found for market 570361
```

**Impact:**
- ❌ Aucune souscription WebSocket après les trades
- ❌ Aucune souscription au démarrage pour les positions actives
- ❌ Le WebSocket client démarre mais reste vide (pas de subscriptions)

## ✅ Solution Appliquée

### 1. Support de SKIP_DB dans `_get_market_token_ids()`

**Avant:**
```python
async def _get_market_token_ids(self, market_id: str) -> Set[str]:
    async with get_db() as db:
        # ... accès DB direct
```

**Après:**
```python
async def _get_market_token_ids(self, market_id: str) -> Set[str]:
    if SKIP_DB:
        # Utilise l'API pour récupérer le marché
        api_client = get_api_client()
        market_data = await api_client.get_market(market_id)
        clob_token_ids = market_data.get('clob_token_ids')
        # ... parse et retourne les token IDs
    else:
        # Utilise la DB normalement
        async with get_db() as db:
            # ... accès DB direct
```

### 2. Support de SKIP_DB dans `subscribe_active_positions()`

**Avant:**
```python
async def subscribe_active_positions(self) -> None:
    async with get_db() as db:
        # Récupère les market_ids depuis la DB
```

**Après:**
```python
async def subscribe_active_positions(self) -> None:
    if SKIP_DB:
        # Utilise l'API pour récupérer les positions actives
        api_client = get_api_client()
        positions_data = await api_client.get_user_positions(1, use_cache=False)
        # ... extrait les market_ids
    else:
        # Utilise la DB normalement
        async with get_db() as db:
            # ... récupère les market_ids depuis la DB
```

### 3. Support de SKIP_DB dans `on_position_closed()`

**Avant:**
```python
async def on_position_closed(self, user_id: int, market_id: str) -> None:
    async with get_db() as db:
        # Vérifie les positions actives depuis la DB
```

**Après:**
```python
async def on_position_closed(self, user_id: int, market_id: str) -> None:
    if SKIP_DB:
        # Utilise l'API pour vérifier les positions actives
        api_client = get_api_client()
        positions_data = await api_client.get_user_positions(1, use_cache=False)
        # ... compte les positions actives pour ce marché
    else:
        # Utilise la DB normalement
        async with get_db() as db:
            # ... vérifie les positions actives depuis la DB
```

## 🎯 Résultat Attendu

Après ce fix, les logs devraient montrer:

1. **Au démarrage:**
   ```
   📊 Found 1 distinct markets with active positions via API
   ✅ Got 2 token IDs for market 525364 via API
   📡 Subscribed to 2 token IDs from 1 markets with active positions
   ```

2. **Après un trade:**
   ```
   🔍 Getting token IDs for market 570361 after trade by user 6500527972
   ✅ Got 2 token IDs for market 570361 via API
   📡 Subscribing to 2 tokens for market 570361
   ✅ Auto-subscribed to market 570361 after trade
   ```

3. **Quand les prix sont mis à jour:**
   ```
   📝 Updating market 570361 with source='ws', prices=[...]
   ✅ Updated market 570361 with source='ws' in database
   ```

## 📊 Comparaison Avant/Après

| Élément | Avant | Après |
|---------|-------|-------|
| Souscription au démarrage | ❌ Échec (DB) | ✅ Succès (API) |
| Souscription après trade | ❌ Échec (DB) | ✅ Succès (API) |
| Token IDs récupérés | ❌ Vide | ✅ Via API |
| WebSocket subscriptions | ❌ 0 | ✅ Nombre correct |

## ⚠️ Note Importante

Le `MarketUpdater` utilise toujours `get_db()` directement pour **écrire** dans la DB. C'est normal car:
- Le `MarketUpdater` doit écrire dans la DB (c'est son rôle)
- En production, le streamer tourne dans un service séparé (workers) qui a accès à la DB
- Le bot avec `SKIP_DB=true` ne devrait normalement pas avoir le streamer, mais c'est utile pour les tests locaux

Si le `MarketUpdater` échoue aussi avec "Database not initialized", il faudra soit:
1. Désactiver le streamer dans le bot (`STREAMER_ENABLED=false`)
2. Ou modifier le `MarketUpdater` pour utiliser l'API pour mettre à jour les marchés (moins optimal)

## ✅ Fix Appliqué

- ✅ `_get_market_token_ids()` utilise l'API quand `SKIP_DB=true`
- ✅ `subscribe_active_positions()` utilise l'API quand `SKIP_DB=true`
- ✅ `on_position_closed()` utilise l'API quand `SKIP_DB=true`
- ✅ Logs de diagnostic améliorés
