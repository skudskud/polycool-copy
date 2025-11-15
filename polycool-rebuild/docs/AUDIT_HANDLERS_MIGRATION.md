# Audit Complet - Migration Handlers vers API Client

**Date**: 2025-01-XX
**Objectif**: Vérifier que tous les handlers utilisent l'API client quand SKIP_DB=true

---

## 📊 Résumé Exécutif

### État Global
- ✅ **Markets handlers**: 100% migré ✅
- ✅ **Positions handlers**: 100% migré ✅
- ✅ **TP/SL handlers**: 100% migré ✅ (workaround implémenté)

---

## 🔍 DÉTAILS PAR HANDLER

### 1. Positions Handlers

#### ✅ **positions_handler.py** - PARTIELLEMENT MIGRÉ

**Problèmes identifiés:**

1. **Ligne 82**: `get_position_helper()` utilise `position_service.get_position()` dans le else - ✅ OK
2. **Ligne 232-239**: Utilise `position_service` dans `_refresh_positions_background()` mais dans le else - ✅ OK
3. **Ligne 261**: Utilise `position_service.get_active_positions()` dans le else - ✅ OK
4. **Ligne 280, 284**: Utilise `get_market_service()` dans le else - ✅ OK
5. **Ligne 467, 468**: Utilise `get_market_service()` dans le else - ✅ OK
6. **Ligne 502**: ❌ **PROBLÈME** - Utilise `tpsl_service.get_active_orders()` directement sans vérifier SKIP_DB
7. **Ligne 521**: ❌ **PROBLÈME** - Utilise `position_service.get_position()` directement sans vérifier SKIP_DB
8. **Ligne 528**: ❌ **PROBLÈME** - Utilise `market_service` qui n'est pas défini dans le scope

**Actions requises:**
- [ ] Corriger `handle_view_all_tpsl()` pour utiliser API client
- [ ] Ajouter endpoint API pour `get_active_orders` ou utiliser positions avec TP/SL

#### ⚠️ **positions/sell_handler.py** - BIEN MIGRÉ

**État:**
- ✅ Utilise `get_position_helper()` qui gère SKIP_DB
- ✅ Utilise `get_market_data()` qui gère SKIP_DB
- ⚠️ Lignes 431, 470, 475: Utilise `position_service` directement mais dans des contextes spécifiques (sync, close, update)

**Actions requises:**
- [ ] Vérifier si ces appels sont dans des blocs SKIP_DB ou else
- [ ] Migrer vers API client si nécessaire

#### ✅ **positions/tpsl_handler.py** - BIEN MIGRÉ

**État:**
- ✅ Utilise `get_position_helper()` qui gère SKIP_DB
- ✅ Utilise `get_market_data()` qui gère SKIP_DB
- ⚠️ Ligne 543: Utilise `position_service.update_position_tpsl()` directement

**Actions requises:**
- [ ] Vérifier si cet appel est dans un bloc SKIP_DB ou else
- [ ] Utiliser `api_client.update_position_tpsl()` si SKIP_DB=true

#### ✅ **positions/refresh_handler.py** - BIEN MIGRÉ

**État:**
- ✅ Utilise API client pour sync
- ✅ Utilise `get_market_data()` qui gère SKIP_DB
- ✅ Utilise `position_service` seulement dans le else

---

### 2. Markets Handlers

#### ✅ **markets_handler.py** - BIEN MIGRÉ

**État:**
- ✅ Utilise `api_client.get_trending_markets()` quand SKIP_DB=true
- ✅ Utilise `api_client.get_market()` quand SKIP_DB=true
- ✅ Utilise `get_market_service()` seulement dans le else
- ✅ Utilise `get_market_data()` qui gère SKIP_DB

**Actions requises:**
- Aucune action requise ✅

#### ✅ **markets/categories.py** - BIEN MIGRÉ

**État:**
- ✅ Utilise `api_client.get_category_markets()` quand SKIP_DB=true
- ✅ Utilise `get_market_service()` seulement dans le else

**Actions requises:**
- Aucune action requise ✅

#### ✅ **markets/search.py** - BIEN MIGRÉ

**État:**
- ✅ Utilise `api_client.search_markets()` quand SKIP_DB=true
- ✅ Utilise `get_market_service()` seulement dans le else

**Actions requises:**
- Aucune action requise ✅

#### ✅ **markets/trading.py** - BIEN MIGRÉ

**État:**
- ✅ Utilise `get_market_data()` qui gère SKIP_DB
- ✅ Utilise `get_user_data()` qui gère SKIP_DB

**Actions requises:**
- Aucune action requise ✅

---

## 🚨 PROBLÈMES CRITIQUES À CORRIGER

### 1. **handle_view_all_tpsl()** - positions_handler.py

**Problème:**
```python
# Ligne 502: Appel direct à tpsl_service sans vérifier SKIP_DB
active_tpsl = await tpsl_service.get_active_orders(internal_id)

# Ligne 521: Appel direct à position_service sans vérifier SKIP_DB
position = await position_service.get_position(order.position_id)

# Ligne 528: Variable market_service non définie
market = await market_service.get_market_by_id(position.market_id)
```

**Solution:**
```python
# Utiliser API client si SKIP_DB=true
if SKIP_DB:
    api_client = get_api_client()
    # TODO: Ajouter endpoint API pour get_active_orders
    # Pour l'instant, récupérer depuis positions avec TP/SL
    positions_data = await api_client.get_user_positions(internal_id)
    active_tpsl = [
        pos for pos in positions_data.get('positions', [])
        if pos.get('take_profit_price') or pos.get('stop_loss_price')
    ]
else:
    active_tpsl = await tpsl_service.get_active_orders(internal_id)

# Pour chaque order, utiliser get_position_helper()
position = await get_position_helper(order.position_id, telegram_user_id)

# Pour market, utiliser get_market_data()
market = await get_market_data(position.market_id, context)
```

### 2. **positions/tpsl_handler.py ligne 543**

**Problème:**
```python
result = await position_service.update_position_tpsl(...)
```

**Solution:**
```python
if SKIP_DB:
    api_client = get_api_client()
    result = await api_client.update_position_tpsl(position_id, tpsl_type, price)
else:
    result = await position_service.update_position_tpsl(...)
```

### 3. **positions/sell_handler.py lignes 431, 470, 475**

**Vérifier si ces appels sont dans des blocs SKIP_DB ou else**

---

## 📋 CHECKLIST DE CORRECTION

### Priorité Critique
- [x] Corriger `handle_view_all_tpsl()` dans positions_handler.py ✅
- [x] Ajouter endpoint API pour `get_active_orders` ou utiliser workaround ✅ (workaround implémenté)
- [x] Corriger `market_service` non défini dans `handle_view_all_tpsl()` ✅

### Priorité Haute
- [x] Vérifier et corriger `positions/tpsl_handler.py` ligne 543 ✅ (déjà correct)
- [x] Vérifier et corriger `positions/sell_handler.py` lignes 431, 470, 475 ✅ (déjà correct - dans else)

### Priorité Moyenne
- [ ] Documenter tous les endpoints API disponibles
- [ ] Créer helpers pour TP/SL operations

---

## ✅ ENDPOINTS API DISPONIBLES

### Positions
- ✅ `GET /positions/user/{user_id}` - Get user positions
- ✅ `GET /positions/{position_id}` - Get specific position
- ✅ `POST /positions/` - Create position
- ✅ `POST /positions/sync/{user_id}` - Sync positions
- ✅ `PUT /positions/{position_id}/tpsl` - Update TP/SL
- ✅ `PUT /positions/{position_id}` - Update position

### Markets
- ✅ `GET /markets/trending` - Get trending markets
- ✅ `GET /markets/category` - Get category markets
- ✅ `GET /markets/search` - Search markets
- ✅ `GET /markets/{market_id}` - Get specific market

### TP/SL
- ❌ `GET /tpsl/active/{user_id}` - **MANQUANT** - Get active TP/SL orders

---

## 🎯 RECOMMANDATIONS

1. **Créer endpoint API pour TP/SL active orders**
   - Ajouter `GET /tpsl/active/{user_id}` dans `telegram_bot/api/v1/tpsl.py`
   - Ou utiliser workaround: filtrer positions avec TP/SL depuis `/positions/user/{user_id}`

2. **Standardiser les helpers**
   - Créer `get_tpsl_helper()` similaire à `get_position_helper()`
   - Créer `get_market_helper()` (déjà fait: `get_market_data()`)

3. **Tests**
   - Ajouter tests pour vérifier que SKIP_DB=true fonctionne correctement
   - Tester tous les handlers avec SKIP_DB=true et false

---

## 📝 NOTES

- `get_market_data()` gère déjà SKIP_DB correctement ✅
- `get_position_helper()` gère déjà SKIP_DB correctement ✅
- `get_user_data()` gère déjà SKIP_DB correctement ✅
- La plupart des handlers utilisent ces helpers, donc sont déjà migrés ✅
