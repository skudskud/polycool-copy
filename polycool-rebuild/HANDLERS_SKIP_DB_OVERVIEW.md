# Overview Handlers & SKIP_DB - Flow par Handler

**Date:** 2025-01-27
**Objectif:** Vérifier l'état de SKIP_DB dans chaque handler principal

---

## ✅ Règle Générale

**OUI, on conserve les deux méthodes:**
- Si `SKIP_DB=true` → Utilise `APIClient` (HTTP vers API service)
- Si `SKIP_DB=false` → Utilise accès DB direct (pour dev/test)

**Pattern Standard:**
```python
import os
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

if SKIP_DB:
    api_client = get_api_client()
    data = await api_client.get_something(...)
else:
    # Accès DB direct
    async with get_db() as db:
        ...
```

---

## 📊 Overview par Handler

### 1. `/wallet` - Wallet Handler

**Fichier:** `telegram_bot/handlers/wallet/view.py`

#### ✅ Status: **Bien Adapté**

**Flow:**
```
/wallet command
  → get_user_data() (helper qui gère SKIP_DB)
  → Si SKIP_DB:
     → api_client.get_wallet_balance(internal_id)
  → Sinon:
     → balance_service.get_usdc_balance(address)
  → Affiche wallet info
```

**Callbacks:**
- `show_polygon_key` → ✅ Utilise `api_client.get_private_key()` si SKIP_DB
- `show_solana_key` → ✅ Utilise `api_client.get_private_key()` si SKIP_DB

**Points Positifs:**
- ✅ Utilise `get_user_data()` helper (gère SKIP_DB automatiquement)
- ✅ Vérifie SKIP_DB avant accès DB
- ✅ Utilise APIClient pour balance et private keys

**Problèmes:** Aucun ✅

---

### 2. `/positions` - Positions Handler

**Fichier:** `telegram_bot/bot/handlers/positions_handler.py`

#### ✅ Status: **Bien Adapté**

**Flow:**
```
/positions command
  → get_user_data() (helper)
  → Si SKIP_DB:
     → api_client.sync_positions(internal_id)
     → api_client.get_user_positions(internal_id)
     → api_client.get_market(market_id) pour chaque position
  → Sinon:
     → position_service.sync_positions_from_blockchain()
     → position_service.get_active_positions()
     → market_service.get_market_by_id()
  → Affiche positions avec P&L
```

**Callbacks:**
- `positions_hub` / `refresh_positions` → ✅ Utilise APIClient si SKIP_DB
- `position_*` → ✅ Utilise `get_position_helper()` qui gère SKIP_DB
- `sell_position_*` → ✅ Utilise `get_position_helper()` + TradeService
- `tpsl_*` → ✅ Utilise `get_position_helper()` + APIClient pour update

**Points Positifs:**
- ✅ Helper `get_position_helper()` gère SKIP_DB
- ✅ Tous les accès DB sont conditionnels
- ✅ Utilise APIClient pour sync, get positions, get markets

**Problèmes:** Aucun ✅

**Note:** `PositionFromAPI` class créée pour convertir API response en objet Position-like

---

### 3. `/markets` - Markets Handler

**Fichier:** `telegram_bot/bot/handlers/markets_handler.py`

#### ✅ Status: **Bien Adapté**

**Flow:**
```
/markets command
  → Affiche hub avec catégories
  → Pas d'accès DB direct (utilise market_helper)
```

**Callbacks:**
- `markets_trending` → ✅ Utilise `market_helper.get_market_data()` qui gère SKIP_DB
- `markets_category_*` → ✅ Utilise `market_helper.get_market_data()`
- `markets_search_*` → ✅ Utilise `market_helper.get_market_data()`
- `markets_select_*` → ✅ Utilise `market_helper.get_market_data()`
- `quick_buy_*` → ✅ Utilise TradeService (qui gère SKIP_DB)

**Points Positifs:**
- ✅ Utilise `market_helper.get_market_data()` qui gère SKIP_DB automatiquement
- ✅ Pas d'accès DB direct dans le handler

**Problèmes:** Aucun ✅

**Note:** Le `market_helper` utilise soit `APIClient` soit `MarketService` selon SKIP_DB

---

### 4. `/copy_trading` - Copy Trading Handler

**Fichier:** `telegram_bot/handlers/copy_trading/main.py` + autres modules

#### ✅ Status: **Bien Adapté**

**Flow:**
```
/copy_trading command
  → CopyTradingService.get_leader_info_for_follower()
  → CopyTradingService.get_follower_stats()
  → CopyTradingService.get_budget_info()
  → Affiche dashboard
```

**Callbacks:**
- `copy_trading:search_leader` → ✅ Utilise CopyTradingService
- `copy_trading:confirm_*` → ✅ Utilise CopyTradingService
- `copy_trading:budget_*` → ✅ Utilise CopyTradingService
- `copy_trading:subscribe` → ✅ Utilise CopyTradingService.subscribe_to_leader()

**Points Positifs:**
- ✅ Utilise `CopyTradingService` qui peut être appelé:
  - Directement (si SKIP_DB=false dans API service)
  - Via APIClient (si SKIP_DB=true dans bot service)
- ✅ Le service gère déjà SKIP_DB en interne

**Problèmes Potentiels:**
- ⚠️ **VÉRIFIER:** Les handlers appellent directement `CopyTradingService` au lieu de `APIClient`
- ⚠️ **RISQUE:** Si `SKIP_DB=true`, le service va essayer d'accéder DB et échouer

**Solution:** Les handlers devraient utiliser `APIClient` si `SKIP_DB=true`:

```python
# ❌ ACTUEL (peut échouer si SKIP_DB=true)
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

**Status:** ⚠️ **À VÉRIFIER** - Les handlers utilisent directement le service

---

### 5. `/smart_trading` - Smart Trading Handler

**Fichier:** `telegram_bot/handlers/smart_trading/view_handler.py`

#### ✅ Status: **CORRIGÉ**

**Flow:**
```
/smart_trading command
  → Si SKIP_DB:
     → api_client.get_smart_trading_recommendations()
  → Sinon:
     → smart_trading_service.get_paginated_recommendations()
  → Affiche recommendations
```

**Callbacks:**
- `smart_view_*` → ✅ Utilise `get_market_data()` helper
- `smart_buy_*` → ✅ Utilise TradeService
- `smart_page_*` → ✅ Utilise APIClient si SKIP_DB

**Points Positifs:**
- ✅ **CORRIGÉ:** Utilise maintenant APIClient si SKIP_DB=true
- ✅ Vérifie SKIP_DB avant utilisation

**Problèmes:** Aucun ✅ (corrigé récemment)

---

## 🔍 Vérification Accès DB Direct

### Recherche dans Handlers

```bash
# Cherche les accès DB directs dans handlers
grep -r "get_db()" telegram_bot/handlers/
grep -r "get_db()" telegram_bot/bot/handlers/
```

**Résultats Attendus:**
- ✅ Peu ou pas de résultats (car utilisent helpers/services)
- ⚠️ Si résultats trouvés → Vérifier qu'ils sont dans `if not SKIP_DB:`

---

## 📋 Checklist par Handler

### ✅ `/wallet`
- [x] Utilise `get_user_data()` helper
- [x] Vérifie SKIP_DB pour balance
- [x] Utilise APIClient pour private keys
- [x] Pas d'accès DB direct

### ✅ `/positions`
- [x] Utilise `get_user_data()` helper
- [x] Utilise `get_position_helper()` qui gère SKIP_DB
- [x] Utilise APIClient pour sync et get positions
- [x] Pas d'accès DB direct

### ✅ `/markets`
- [x] Utilise `market_helper.get_market_data()` qui gère SKIP_DB
- [x] Pas d'accès DB direct dans handler
- [x] TradeService gère SKIP_DB

### ⚠️ `/copy_trading`
- [x] Utilise `CopyTradingService` directement
- [ ] **PROBLÈME:** Service appelé directement, pas via APIClient si SKIP_DB=true
- [ ] **ACTION:** Vérifier si CopyTradingService gère SKIP_DB ou si handlers doivent utiliser APIClient

### ✅ `/smart_trading`
- [x] Utilise APIClient si SKIP_DB=true
- [x] Utilise service direct si SKIP_DB=false
- [x] Pas d'accès DB direct

---

## 🚨 Problèmes Identifiés

### 1. Copy Trading Handlers

**Problème:** Les handlers appellent directement `CopyTradingService` qui peut essayer d'accéder DB.

**Fichiers Affectés:**
- `telegram_bot/handlers/copy_trading/main.py`
- `telegram_bot/handlers/copy_trading/callbacks/*.py`
- `telegram_bot/handlers/copy_trading/subscription_flow.py`
- `telegram_bot/handlers/copy_trading/budget_flow.py`

**Solution:**
Vérifier si `CopyTradingService` gère SKIP_DB en interne, sinon modifier les handlers pour utiliser `APIClient` si `SKIP_DB=true`.

**Vérification Requise:**
```python
# Dans CopyTradingService
# Vérifier s'il utilise get_db() directement ou via helpers
# Si oui, vérifier si c'est dans un if not SKIP_DB:
```

---

## ✅ Résumé Global

### Handlers Bien Adaptés (4/5)

1. ✅ `/wallet` - Parfait
2. ✅ `/positions` - Parfait
3. ✅ `/markets` - Parfait
4. ✅ `/smart_trading` - Corrigé récemment
5. ⚠️ `/copy_trading` - **À VÉRIFIER**

### Pattern Utilisé

**La plupart des handlers utilisent:**
- ✅ Helpers qui gèrent SKIP_DB (`get_user_data()`, `get_market_data()`)
- ✅ Services qui peuvent être appelés via API ou direct
- ✅ APIClient quand nécessaire

**Copy Trading est différent:**
- ⚠️ Appelle directement `CopyTradingService`
- ⚠️ Doit vérifier si le service gère SKIP_DB ou utiliser APIClient

---

## 🎯 Actions Recommandées

### Priorité 1: Vérifier Copy Trading

1. **Vérifier CopyTradingService:**
   - Regarder s'il utilise `get_db()` directement
   - Vérifier s'il gère SKIP_DB en interne
   - Si non → Modifier handlers pour utiliser APIClient

2. **Vérifier APIClient:**
   - S'assurer que tous les endpoints copy trading existent dans APIClient
   - Vérifier: `get_copy_trading_leader_info()`, `get_follower_stats()`, etc.

### Priorité 2: Tests

1. **Tester avec SKIP_DB=true:**
   - Tester chaque handler
   - Vérifier qu'aucun ne crash avec erreur DB

2. **Tester avec SKIP_DB=false:**
   - Vérifier que tout fonctionne toujours

---

**Conclusion:** La plupart des handlers sont bien adaptés. Copy Trading nécessite une vérification supplémentaire.
