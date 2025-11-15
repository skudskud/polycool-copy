# Status SKIP_DB par Handler - Overview Rapide

**Date:** 2025-01-27
**Objectif:** Overview rapide des flows et problèmes SKIP_DB

---

## ✅ Règle: On Conserve les Deux Méthodes

**OUI**, on garde les deux chemins:
- `SKIP_DB=true` → Utilise `APIClient` (HTTP vers API service)
- `SKIP_DB=false` → Accès DB direct (pour dev/test)

**Pattern Standard:**
```python
if SKIP_DB:
    api_client = get_api_client()
    data = await api_client.get_something(...)
else:
    async with get_db() as db:
        data = await db.execute(...)
```

---

## 📊 Overview Rapide par Handler

### 1. `/wallet` ✅ **PARFAIT**

**Flow:**
```
/wallet
  → get_user_data() (helper auto)
  → Si SKIP_DB: api_client.get_wallet_balance()
  → Sinon: balance_service.get_usdc_balance()
  → Affiche wallet + balance
```

**Callbacks:**
- `show_polygon_key` → api_client.get_private_key() si SKIP_DB ✅
- `show_solana_key` → api_client.get_private_key() si SKIP_DB ✅

**Status:** ✅ Aucun problème

---

### 2. `/positions` ✅ **PARFAIT**

**Flow:**
```
/positions
  → get_user_data() (helper auto)
  → Si SKIP_DB:
     → api_client.sync_positions()
     → api_client.get_user_positions()
     → api_client.get_market() pour chaque
  → Sinon:
     → position_service.sync_positions_from_blockchain()
     → position_service.get_active_positions()
  → Affiche positions avec P&L
```

**Callbacks:**
- `positions_hub` → Utilise get_position_helper() ✅
- `position_*` → Utilise get_position_helper() ✅
- `sell_position_*` → Utilise get_position_helper() + TradeService ✅
- `tpsl_*` → Utilise get_position_helper() + api_client.update_position_tpsl() ✅

**Status:** ✅ Aucun problème

**Note:** `get_position_helper()` gère SKIP_DB automatiquement

---

### 3. `/markets` ✅ **PARFAIT**

**Flow:**
```
/markets
  → Affiche hub (pas de DB)
  → Callbacks utilisent market_helper.get_market_data()
  → market_helper gère SKIP_DB automatiquement
```

**Callbacks:**
- `markets_trending` → market_helper (gère SKIP_DB) ✅
- `markets_category_*` → market_helper (gère SKIP_DB) ✅
- `markets_search_*` → market_helper (gère SKIP_DB) ✅
- `quick_buy_*` → TradeService (gère SKIP_DB) ✅

**Status:** ✅ Aucun problème

**Note:** Pas d'accès DB direct, tout passe par helpers/services

---

### 4. `/copy_trading` ⚠️ **PROBLÈME IDENTIFIÉ**

**Flow Actuel:**
```
/copy_trading
  → CopyTradingService.get_leader_info_for_follower()
  → CopyTradingService.get_follower_stats()
  → CopyTradingService.get_budget_info()
  → Affiche dashboard
```

**Problème:**
- ❌ `CopyTradingService` utilise `get_db()` directement (6 occurrences)
- ❌ Les handlers appellent directement le service
- ❌ Si `SKIP_DB=true`, le service va échouer

**Fichiers avec Accès DB Direct:**
- `telegram_bot/handlers/copy_trading/budget_flow.py` (4 occurrences)
- `telegram_bot/handlers/copy_trading/helpers.py` (1 occurrence)
- `core/services/copy_trading/service.py` (6 occurrences)

**Solution:**
Les handlers doivent utiliser `APIClient` si `SKIP_DB=true`:

```python
# ❌ ACTUEL (va échouer si SKIP_DB=true)
service = get_copy_trading_service()
leader_info = await service.get_leader_info_for_follower(user_id)

# ✅ DEVRAIT ÊTRE
if SKIP_DB:
    api_client = get_api_client()
    leader_info = await api_client.get_copy_trading_leader_info(user_id)
else:
    service = get_copy_trading_service()
    leader_info = await service.get_leader_info_for_follower(user_id)
```

**Endpoints API Disponibles:**
- ✅ `GET /copy-trading/watched-address/{id}` → `api_client.get_watched_address()`
- ✅ `POST /copy-trading/subscribe` → `api_client.subscribe_to_leader()`
- ✅ `GET /copy-trading/followers/{id}` → `api_client.get_follower_allocation()`
- ✅ `GET /copy-trading/followers/{id}/stats` → `api_client.get_follower_stats()`
- ❌ **MANQUE:** `get_leader_info_for_follower()` dans APIClient
- ❌ **MANQUE:** `get_budget_info()` dans APIClient

**Status:** ⚠️ **NÉCESSITE CORRECTION**

---

### 5. `/smart_trading` ✅ **CORRIGÉ**

**Flow:**
```
/smart_trading
  → Si SKIP_DB: api_client.get_smart_trading_recommendations()
  → Sinon: smart_trading_service.get_paginated_recommendations()
  → Affiche recommendations
```

**Callbacks:**
- `smart_view_*` → get_market_data() helper ✅
- `smart_buy_*` → TradeService ✅
- `smart_page_*` → api_client si SKIP_DB ✅

**Status:** ✅ Corrigé récemment, aucun problème

---

## 🚨 Problèmes Identifiés

### 🔴 CRITIQUE: Copy Trading Handlers

**Problème:** Accès DB direct dans handlers et service

**Fichiers Affectés:**
1. `telegram_bot/handlers/copy_trading/budget_flow.py`
   - Ligne 253, 306, 426, 487: `async with get_db() as db:`

2. `telegram_bot/handlers/copy_trading/helpers.py`
   - Ligne 50: `async with get_db() as db:`

3. `core/services/copy_trading/service.py`
   - Ligne 79, 182, 229, 259, 346, 425: `async with get_db() as db:`

**Impact:**
- Si `SKIP_DB=true`, ces handlers vont échouer avec erreur DB
- Le service ne peut pas être appelé directement depuis le bot

**Solution:**
1. **Option A (Recommandée):** Modifier les handlers pour utiliser `APIClient` si `SKIP_DB=true`
2. **Option B:** Modifier `CopyTradingService` pour gérer SKIP_DB (mais c'est un service, pas idéal)

**Action Requise:**
- Ajouter méthodes manquantes dans `APIClient`:
  - `get_copy_trading_leader_info(user_id)`
  - `get_copy_trading_budget_info(user_id)`
- Modifier handlers pour utiliser `APIClient` si `SKIP_DB=true`

---

### 🟡 MOYEN: TP/SL Handler

**Fichier:** `telegram_bot/bot/handlers/positions/tpsl_handler.py`
- Ligne 300: `async with get_db() as db:`

**Impact:** Moins critique car utilisé seulement pour certaines opérations

**Solution:** Vérifier si c'est dans un `if not SKIP_DB:` ou utiliser `api_client.update_position_tpsl()`

---

## 📋 Résumé par Handler

| Handler | Status | Problèmes | Action Requise |
|---------|--------|-----------|----------------|
| `/wallet` | ✅ | Aucun | Aucune |
| `/positions` | ✅ | Aucun | Aucune |
| `/markets` | ✅ | Aucun | Aucune |
| `/copy_trading` | ⚠️ | Accès DB direct | Corriger handlers |
| `/smart_trading` | ✅ | Aucun | Aucune |

---

## 🎯 Actions Prioritaires

### Priorité 1: Copy Trading

1. **Ajouter méthodes manquantes dans APIClient:**
   ```python
   async def get_copy_trading_leader_info(self, user_id: int):
       """Get leader info for follower"""
       endpoint = f"/copy-trading/followers/{user_id}/leader-info"
       return await self._get(endpoint, ...)

   async def get_copy_trading_budget_info(self, user_id: int):
       """Get budget info for follower"""
       endpoint = f"/copy-trading/followers/{user_id}/budget-info"
       return await self._get(endpoint, ...)
   ```

2. **Modifier handlers copy trading:**
   - `main.py` → Utiliser APIClient si SKIP_DB
   - `budget_flow.py` → Supprimer accès DB direct, utiliser APIClient
   - `helpers.py` → Supprimer accès DB direct, utiliser APIClient

3. **Créer endpoints API manquants:**
   - `GET /copy-trading/followers/{id}/leader-info`
   - `GET /copy-trading/followers/{id}/budget-info`

### Priorité 2: Vérifier TP/SL Handler

- Vérifier si l'accès DB est conditionnel
- Si non, utiliser `api_client.update_position_tpsl()`

---

## ✅ Conclusion

**4/5 handlers sont parfaits** ✅
- `/wallet` ✅
- `/positions` ✅
- `/markets` ✅
- `/smart_trading` ✅

**1/5 handler nécessite correction** ⚠️
- `/copy_trading` ⚠️ - Accès DB direct à corriger

**Action:** Corriger les handlers copy trading pour utiliser APIClient si SKIP_DB=true
