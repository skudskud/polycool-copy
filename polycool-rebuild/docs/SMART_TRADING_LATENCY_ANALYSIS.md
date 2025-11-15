# Analyse de Latence - Commande /smart_trading

## 🔍 Problèmes Identifiés

### 1. **Résolution Séquentielle des Marchés (CRITIQUE)**

**Localisation** : `telegram_bot/handlers/smart_trading/view_handler.py:144-159`

**Problème** :
```python
for trade in trades_data:
    position_id = trade.get('position_id')
    if not position_id:
        continue

    # Check cache first
    if position_id in position_id_to_market:
        market = position_id_to_market[position_id]
    else:
        try:
            market = await _resolve_market_by_position_id(position_id, context)  # ⚠️ SÉQUENTIEL
            if market:
                position_id_to_market[position_id] = market
```

**Impact** :
- Si on a 50 trades, cela fait **50 appels API séquentiels**
- Chaque appel peut prendre jusqu'à **10 secondes** (timeout)
- **Temps total potentiel** : 50 × 10s = **500 secondes (8+ minutes)** dans le pire cas
- **Temps réel typique** : 50 × 0.5s = **25 secondes** (si chaque appel prend 500ms)

**Solution** : Paralléliser avec `asyncio.gather()` ou `asyncio.create_task()`

---

### 2. **Pas de Parallélisation des Appels API**

**Localisation** : `telegram_bot/handlers/smart_trading/callbacks.py:28-71`

**Problème** :
- Chaque résolution de marché fait un appel HTTP séparé
- Les appels sont faits un par un au lieu d'être parallélisés
- Pas de limite de concurrence (peut surcharger l'API)

**Impact** :
- Latence cumulative : si 50 trades, 50 appels séquentiels
- Pas d'utilisation optimale des connexions HTTP

**Solution** : Utiliser `asyncio.gather()` avec un semaphore pour limiter la concurrence

---

### 3. **Timeout de 10 Secondes par Requête**

**Localisation** : `core/services/api_client/api_client.py:37`

**Problème** :
```python
self.client = httpx.AsyncClient(
    timeout=10.0,  # ⚠️ 10 secondes par requête
    follow_redirects=True
)
```

**Impact** :
- Si une requête est lente, elle bloque jusqu'à 10 secondes
- Pas de timeout plus court pour les résolutions de marché
- Peut causer des timeouts Telegram (30 secondes max)

**Solution** : Réduire le timeout pour les résolutions de marché (ex: 3 secondes)

---

### 4. **Pas de Cache au Niveau du Handler**

**Localisation** : `telegram_bot/handlers/smart_trading/view_handler.py:135-171`

**Problème** :
- Le cache `position_id_to_market` est uniquement en mémoire dans `context.user_data`
- Perdu entre les sessions utilisateur
- Pas de cache Redis partagé pour les résolutions de marché

**Impact** :
- Chaque utilisateur doit résoudre les mêmes marchés
- Pas de réutilisation entre utilisateurs
- Latence répétée pour les mêmes `position_id`

**Solution** : Utiliser Redis cache pour les résolutions de marché (TTL: 5-10 minutes)

---

### 5. **Batch Resolution Inefficace**

**Localisation** : `core/services/smart_trading/service.py:392-432`

**Problème** :
```python
async with get_db() as db:
    for position_id in position_ids:  # ⚠️ Boucle séquentielle
        try:
            result = await db.execute(
                select(Market.title).where(
                    Market.is_active == True,
                    Market.clob_token_ids.op('@>')([position_id])
                ).limit(1)
            )
```

**Impact** :
- Même en mode DB, les requêtes sont faites une par une
- Pas de vraie requête batch SQL
- N requêtes au lieu d'une seule

**Solution** : Utiliser une requête SQL avec `ANY()` ou `IN` pour résoudre tous les position_ids en une seule fois

---

### 6. **Double Résolution des Marchés**

**Localisation** : `telegram_bot/handlers/smart_trading/view_handler.py:135-171`

**Problème** :
- Le service `get_recent_recommendations_cached` résout déjà les titres de marché
- Le handler les résout à nouveau pour obtenir les URLs Polymarket
- Double travail pour les mêmes données

**Impact** :
- Latence supplémentaire inutile
- Requêtes redondantes

**Solution** : Inclure les URLs Polymarket dans la réponse du service/API

---

### 7. **Pas de Limite de Concurrence**

**Problème** :
- Si on parallélise les appels, rien n'empêche de faire 50 requêtes simultanées
- Peut surcharger l'API ou la base de données
- Peut causer des erreurs de rate limiting

**Solution** : Utiliser un `asyncio.Semaphore` pour limiter à 5-10 requêtes simultanées

---

## 📊 Estimation de Latence Actuelle

### Scénario Typique (50 trades)
- **Récupération des trades** : 0.5-1s (cache Redis)
- **Résolution des 50 marchés (séquentiel)** : 50 × 0.5s = **25 secondes**
- **Filtrage et formatage** : 0.1s
- **Total** : **~26 secondes** ⚠️

### Scénario Pire Cas
- **Récupération des trades** : 2s (cache miss)
- **Résolution des 50 marchés (séquentiel)** : 50 × 10s = **500 secondes** (timeout)
- **Total** : **~502 secondes (8+ minutes)** ❌

### Scénario Optimisé (avec parallélisation)
- **Récupération des trades** : 0.5-1s (cache Redis)
- **Résolution des 50 marchés (parallèle, 10 à la fois)** : 5 × 0.5s = **2.5 secondes**
- **Filtrage et formatage** : 0.1s
- **Total** : **~3-4 secondes** ✅

---

## 🚀 Solutions Recommandées

### Solution 1 : Paralléliser les Résolutions de Marché (PRIORITÉ HAUTE)

```python
# Dans _display_trades_page
import asyncio

# Collecter tous les position_ids uniques
position_ids_to_resolve = [
    trade.get('position_id')
    for trade in trades_data
    if trade.get('position_id') and trade.get('position_id') not in position_id_to_market
]

# Paralléliser les résolutions (limite de 10 simultanées)
semaphore = asyncio.Semaphore(10)

async def resolve_with_semaphore(position_id):
    async with semaphore:
        return await _resolve_market_by_position_id(position_id, context)

if position_ids_to_resolve:
    resolved_markets = await asyncio.gather(
        *[resolve_with_semaphore(pid) for pid in position_ids_to_resolve],
        return_exceptions=True
    )

    # Mapper les résultats
    for position_id, market in zip(position_ids_to_resolve, resolved_markets):
        if market and not isinstance(market, Exception):
            position_id_to_market[position_id] = market
```

**Gain estimé** : 25s → 2.5s (10x plus rapide)

---

### Solution 2 : Cache Redis pour les Résolutions de Marché

```python
# Dans _resolve_market_by_position_id
cache_key = f"market_resolution:{position_id}"
cached_market = await cache_manager.get(cache_key)
if cached_market:
    return cached_market

# Résoudre le marché
market = await _resolve_market_by_position_id_internal(position_id, context)

# Mettre en cache (TTL: 10 minutes)
if market:
    await cache_manager.set(cache_key, market, ttl=600)

return market
```

**Gain estimé** : Réduction de 80-90% des appels API pour les marchés déjà résolus

---

### Solution 3 : Réduire le Timeout pour les Résolutions

```python
# Créer un client avec timeout plus court pour les résolutions
resolution_client = httpx.AsyncClient(timeout=3.0)  # 3 secondes au lieu de 10
```

**Gain estimé** : Réduction du temps d'attente en cas de problème réseau

---

### Solution 4 : Inclure les URLs dans la Réponse du Service

Modifier `get_recent_recommendations` pour inclure `polymarket_url` dans la réponse, évitant ainsi une deuxième résolution.

**Gain estimé** : Élimination complète de la deuxième passe de résolution

---

### Solution 5 : Vraie Requête Batch SQL

```python
# Au lieu de boucler, faire une seule requête
async with get_db() as db:
    result = await db.execute(
        select(Market.id, Market.title, Market.polymarket_url, Market.clob_token_ids)
        .where(
            Market.is_active == True,
            # Utiliser ANY() pour chercher tous les position_ids en une fois
            func.jsonb_array_elements_text(Market.clob_token_ids).in_(position_ids)
        )
    )

    # Mapper les résultats
    for market in result:
        for token_id in market.clob_token_ids:
            if token_id in position_ids:
                title_map[token_id] = market.title
                url_map[token_id] = market.polymarket_url
```

**Gain estimé** : N requêtes → 1 requête (50x moins de requêtes DB)

---

## 📈 Priorisation des Optimisations

1. **🔴 CRITIQUE** : Paralléliser les résolutions de marché (Solution 1)
   - Impact : 10x plus rapide
   - Complexité : Moyenne
   - Effort : 2-3 heures

2. **🟡 IMPORTANT** : Cache Redis pour les résolutions (Solution 2)
   - Impact : 80-90% de réduction des appels
   - Complexité : Faible
   - Effort : 1-2 heures

3. **🟡 IMPORTANT** : Inclure URLs dans la réponse du service (Solution 4)
   - Impact : Élimination de la double résolution
   - Complexité : Moyenne
   - Effort : 2-3 heures

4. **🟢 OPTIONNEL** : Réduire timeout (Solution 3)
   - Impact : Réduction des timeouts
   - Complexité : Très faible
   - Effort : 30 minutes

5. **🟢 OPTIONNEL** : Vraie requête batch SQL (Solution 5)
   - Impact : Optimisation DB
   - Complexité : Élevée
   - Effort : 4-6 heures

---

## 🎯 Objectif de Performance

**Actuel** : ~26 secondes (typique)
**Cible** : **< 5 secondes** (avec optimisations)

**Gain total estimé** : **5-10x plus rapide**
