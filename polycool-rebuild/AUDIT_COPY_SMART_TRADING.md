# Audit Copy Trading & Smart Trading - Intégration Production

**Date:** 2025-01-27
**Projet:** polycool-rebuild
**Objectif:** Auditer l'intégration complète Copy Trading et Smart Trading pour la production

---

## 📋 Architecture Micro-Services

### Services Identifiés

1. **Service Indexer** (`data_ingestion/indexer/`)
   - Récupère les transactions des leaders (copy trading) et smart traders (smart trading)
   - Via watched addresses depuis Subsquid
   - Envoie webhooks vers API service

2. **Service Bot** (`telegram_bot/`)
   - Code du bot Telegram (pas d'accès DB, `SKIP_DB=true`)
   - Handlers pour copy trading et smart trading
   - Utilise `APIClient` pour communiquer avec API service

3. **Service API** (`telegram_bot/api/`)
   - Accès DB (Supabase)
   - Endpoints REST pour copy trading et smart trading
   - Webhook receiver pour indexer

4. **Service Workers** (`workers.py`)
   - Data ingestion (poller, websocket)
   - Copy Trading Listener (Redis PubSub)
   - Watched addresses cache sync

5. **Cache Manager Redis**
   - Cache pour watched addresses
   - PubSub pour copy trading events

---

## ✅ COPY TRADING - Audit Complet

### Flow Identifié

```
Indexer → Webhook (/api/v1/webhooks/copy-trade)
  → Store DB (trades table)
  → Publish Redis (copy_trade:{address})
  → Copy Trading Listener (workers.py)
  → Execute Copy Trade (TradeService)
  → Create Position (is_copy_trade=True)
```

### Composants Analysés

#### 1. Webhook Receiver ✅
**Fichier:** `telegram_bot/api/v1/webhooks/copy_trade.py`

**Points Positifs:**
- ✅ Validation webhook secret
- ✅ Fast cache lookup (`watched_manager.is_watched_address`)
- ✅ Stockage DB asynchrone (non-blocking)
- ✅ Publication Redis asynchrone (non-blocking)
- ✅ Retry logic pour DB connection errors
- ✅ Update leader positions tracking (pour copy_leader)
- ✅ Track smart wallet positions (pour smart_wallet)

**Points d'Attention:**
- ⚠️ **PROBLÈME:** `address_type` dans le code utilise `'smart_wallet'` (ligne 326) mais le modèle utilise `'smart_trader'` (models.py ligne 206)
- ⚠️ **INCONSISTANCE:** Le webhook publie TOUS les trades (copy_leader ET smart_wallet) sur le même channel Redis `copy_trade:*`

#### 2. Copy Trading Listener ✅
**Fichier:** `data_ingestion/indexer/copy_trading_listener.py`

**Points Positifs:**
- ✅ Subscribe à Redis PubSub pattern `copy_trade:*`
- ✅ Deduplication (cache tx_id, 5min TTL)
- ✅ Market resolution via position_id (clob_token_ids lookup)
- ✅ Fallback market resolution (market_id + outcome)
- ✅ Calcul copy amount (proportional/fixed_amount)
- ✅ Calcul SELL copy amount (position-based)
- ✅ Exécution via TradeService avec `is_copy_trade=True`
- ✅ Update allocation stats après succès

**Points d'Attention:**
- ⚠️ **PROBLÈME:** Le listener traite TOUS les messages Redis, même ceux de `smart_wallet`. Il devrait filtrer uniquement `copy_leader`
- ⚠️ **PROBLÈME:** Pas de vérification que `address_type == 'copy_leader'` avant traitement
- ⚠️ **RISQUE:** Si un trade de smart_wallet arrive sur Redis, il sera traité comme copy trade

**Code Problématique:**
```python
# Ligne 127-130: Vérifie seulement si watched, pas le type
address_info = await self.watched_manager.is_watched_address(user_address)
if not address_info['is_watched']:
    return
# MANQUE: Vérification address_type == 'copy_leader'
```

#### 3. TradeService ✅
**Fichier:** `core/services/trading/trade_service.py`

**Points Positifs:**
- ✅ Support `is_copy_trade` flag
- ✅ Création position avec `is_copy_trade=True`
- ✅ Gestion SKIP_DB (utilise API client si nécessaire)
- ✅ WebSocket subscription après trade

**Intégration:** ✅ Correcte

#### 4. Handlers Telegram ✅
**Fichiers:** `telegram_bot/handlers/copy_trading/`

**Points Positifs:**
- ✅ Handlers complets pour dashboard, settings, history
- ✅ Utilisation API endpoints via APIClient (quand SKIP_DB=true)

**Intégration:** ✅ Correcte

#### 5. API Endpoints ✅
**Fichier:** `telegram_bot/api/v1/copy_trading.py`

**Points Positifs:**
- ✅ Endpoints REST complets (GET /leaders, POST /subscribe, etc.)
- ✅ Accès DB direct

**Intégration:** ✅ Correcte

### Problèmes Identifiés - Copy Trading

#### 🔴 CRITIQUE: Filtrage Redis Messages

**Problème:** Le Copy Trading Listener traite TOUS les messages Redis `copy_trade:*`, y compris ceux des smart wallets.

**Impact:**
- Risque d'exécution de copy trades pour des smart wallets (non désiré)
- Confusion entre copy trading et smart trading

**Solution Recommandée:**
```python
# Dans copy_trading_listener.py, ligne ~127
address_info = await self.watched_manager.is_watched_address(user_address)
if not address_info['is_watched']:
    return

# AJOUTER:
if address_info['address_type'] != 'copy_leader':
    logger.debug(f"⏭️ Skipped non-leader address: {user_address[:10]}... (type: {address_info['address_type']})")
    return
```

#### 🟡 MOYEN: Inconsistance address_type

**Problème:** Le code utilise parfois `'smart_wallet'` et parfois `'smart_trader'` pour le même concept.

**Fichiers Affectés:**
- `webhooks/copy_trade.py` ligne 326: `'smart_wallet'`
- `models.py` ligne 206: `'smart_trader'`
- `smart_trading/service.py` ligne 59: `'smart_wallet'`

**Solution:** Standardiser sur `'smart_trader'` partout (ou `'smart_wallet'` si préféré, mais être cohérent)

---

## ✅ SMART TRADING - Audit Complet

### Flow Identifié

```
Indexer → Webhook (/api/v1/webhooks/copy-trade)
  → Store DB (trades table, watched_address_id avec address_type='smart_trader')
  → Publish Redis (copy_trade:{address}) [mais pas utilisé pour smart trading]
  → Smart Trading Service (query DB)
  → Handlers Telegram (/smart_trading)
  → Display recommendations
  → User choisit manuellement
  → Execute trade via TradeService
```

### Composants Analysés

#### 1. Webhook Receiver ✅
**Fichier:** `telegram_bot/api/v1/webhooks/copy_trade.py`

**Points Positifs:**
- ✅ Stocke trades dans DB avec `watched_address_id`
- ✅ Track smart wallet positions (ligne 326-370)
- ✅ Utilise `SmartWalletPositionTracker`

**Points d'Attention:**
- ⚠️ **INCONSISTANCE:** Utilise `'smart_wallet'` au lieu de `'smart_trader'` (ligne 326)

#### 2. Smart Trading Service ✅
**Fichier:** `core/services/smart_trading/service.py`

**Points Positifs:**
- ✅ Query DB pour trades de smart wallets
- ✅ Filtres: `address_type='smart_wallet'`, `trade_type='buy'`, `amount_usdc >= $300`
- ✅ Pagination support
- ✅ Stats support

**Points d'Attention:**
- ⚠️ **INCONSISTANCE:** Utilise `'smart_wallet'` (ligne 59) mais modèle utilise `'smart_trader'`
- ⚠️ **PROBLÈME:** Si la table `watched_addresses` utilise `'smart_trader'`, la query ne trouvera rien

**Code Problématique:**
```python
# Ligne 59: Utilise 'smart_wallet'
WatchedAddress.address_type == 'smart_wallet',
# Mais models.py définit 'smart_trader'
```

#### 3. Smart Trading Handlers ✅
**Fichiers:**
- `telegram_bot/handlers/smart_trading/view_handler.py`
- `telegram_bot/handlers/smart_trading/callbacks.py`

**Points Positifs:**
- ✅ Handler `/smart_trading` command
- ✅ Callbacks pour view market, quick buy, pagination
- ✅ Utilise `SmartTradingService` directement (pas d'API call nécessaire car service a accès DB)

**Points d'Attention:**
- ⚠️ **ARCHITECTURE:** Les handlers utilisent directement le service (accès DB), ce qui est OK pour le service API mais pourrait être problématique si le bot service n'a pas accès DB

**Intégration:** ✅ Correcte (assumant que le service API a accès DB)

#### 4. API Endpoints ✅
**Fichier:** `telegram_bot/api/v1/smart_trading.py`

**Points Positifs:**
- ✅ Endpoints REST complets
- ✅ Utilise `SmartTradingService`

**Intégration:** ✅ Correcte

### Problèmes Identifiés - Smart Trading

#### 🔴 CRITIQUE: Inconsistance address_type

**Problème:** Le code utilise `'smart_wallet'` mais le modèle définit `'smart_trader'`.

**Impact:**
- Les queries ne trouveront pas les smart traders dans la DB
- Smart trading ne fonctionnera pas

**Solution Recommandée:**
Standardiser sur `'smart_trader'` partout:

1. **webhooks/copy_trade.py ligne 326:**
```python
# AVANT:
if watched_address.address_type == 'smart_wallet':

# APRÈS:
if watched_address.address_type == 'smart_trader':
```

2. **smart_trading/service.py ligne 59:**
```python
# AVANT:
WatchedAddress.address_type == 'smart_wallet',

# APRÈS:
WatchedAddress.address_type == 'smart_trader',
```

3. **smart_trading/service.py ligne 245:**
```python
# AVANT:
WatchedAddress.address_type == 'smart_wallet',

# APRÈS:
WatchedAddress.address_type == 'smart_trader',
```

#### 🟡 MOYEN: Redis PubSub Non Utilisé

**Observation:** Les trades de smart traders sont publiés sur Redis mais ne sont pas consommés pour smart trading (c'est normal car smart trading est manuel).

**Impact:** Aucun (c'est le comportement attendu)

---

## 🔍 Intégration API Calls

### Bot → API Service

**Fichier:** `core/services/api_client/api_client.py`

**Points Positifs:**
- ✅ APIClient avec retry logic, rate limiting, circuit breaker
- ✅ Cache Redis intégré
- ✅ Support pour user, wallet, positions

**Utilisation dans Handlers:**

#### Copy Trading Handlers
- ✅ Utilisent `APIClient` quand `SKIP_DB=true`
- ✅ Endpoints: `/copy-trading/leaders`, `/copy-trading/subscribe`, etc.

#### Smart Trading Handlers
- ⚠️ **PROBLÈME:** Utilisent directement `SmartTradingService` (accès DB direct)
- ⚠️ **RISQUE:** Si le bot service n'a pas accès DB (`SKIP_DB=true`), smart trading ne fonctionnera pas

**Solution Recommandée:**
Les handlers smart trading devraient utiliser l'API endpoint `/smart-trading/recommendations` via `APIClient` au lieu d'appeler directement le service.

**Code Actuel (Problématique):**
```python
# view_handler.py ligne 20
smart_trading_service = SmartTradingService()  # Accès DB direct

# Devrait être:
from core.services.api_client.api_client import get_api_client
api_client = get_api_client()
result = await api_client.get_smart_trading_recommendations(...)
```

---

## 📊 Tables Supabase

### Tables Attendues (d'après models.py)

1. **watched_addresses** ✅
   - Colonnes: `id`, `address`, `address_type`, `is_active`, `win_rate`, etc.
   - **Status:** À vérifier dans Supabase

2. **trades** ✅
   - Colonnes: `id`, `watched_address_id`, `market_id`, `outcome`, `amount_usdc`, `tx_hash`, `trade_type`, etc.
   - **Status:** À vérifier dans Supabase

3. **copy_trading_allocations** ✅
   - Colonnes: `id`, `user_id`, `leader_address_id`, `allocation_type`, `allocation_value`, `mode`, etc.
   - **Status:** À vérifier dans Supabase

4. **leader_positions** (si existe)
   - Pour tracking positions des leaders
   - **Status:** À vérifier dans Supabase

5. **smart_traders_positions** (si existe)
   - Pour tracking positions des smart traders
   - **Status:** À vérifier dans Supabase

### Vérification Requise

**Action:** Vérifier que toutes les tables existent dans Supabase avec les bonnes colonnes et indexes.

---

## 🎯 Recommandations Prioritaires

### 🔴 PRIORITÉ 1: Corrections Critiques

1. **Filtrer Copy Trading Listener**
   - Ajouter vérification `address_type == 'copy_leader'` dans `copy_trading_listener.py`

2. **Standardiser address_type**
   - Choisir `'smart_trader'` ou `'smart_wallet'` et l'utiliser partout
   - Recommandation: `'smart_trader'` (cohérent avec `'copy_leader'`)

3. **Vérifier Tables Supabase**
   - S'assurer que `watched_addresses`, `trades`, `copy_trading_allocations` existent
   - Vérifier les colonnes et indexes

### 🟡 PRIORITÉ 2: Améliorations Architecture

4. **Smart Trading via API**
   - Modifier handlers smart trading pour utiliser `APIClient` au lieu d'accès DB direct
   - Garantir fonctionnement avec `SKIP_DB=true`

5. **Séparation Redis Channels**
   - Considérer channels séparés: `copy_trade:*` pour copy leaders, `smart_trade:*` pour smart traders
   - (Optionnel, car smart trading n'utilise pas Redis actuellement)

### 🟢 PRIORITÉ 3: Monitoring & Tests

6. **Logging Amélioré**
   - Ajouter logs pour distinguer copy trading vs smart trading dans webhook
   - Ajouter métriques pour monitoring

7. **Tests d'Intégration**
   - Tests end-to-end pour copy trading flow
   - Tests end-to-end pour smart trading flow

---

## 📝 Checklist de Déploiement

### Avant Production

- [ ] Corriger filtrage Copy Trading Listener
- [ ] Standardiser `address_type` partout
- [ ] Vérifier tables Supabase existent avec bonnes colonnes
- [ ] Modifier smart trading handlers pour utiliser API
- [ ] Tester copy trading end-to-end
- [ ] Tester smart trading end-to-end
- [ ] Vérifier Redis PubSub fonctionne
- [ ] Vérifier webhook receiver fonctionne
- [ ] Vérifier Copy Trading Listener démarre dans workers
- [ ] Vérifier watched addresses cache sync fonctionne

### Monitoring Production

- [ ] Logs pour webhook receiver (copy vs smart)
- [ ] Métriques Copy Trading Listener (success/fail rates)
- [ ] Alertes si Copy Trading Listener s'arrête
- [ ] Alertes si Redis PubSub déconnecte
- [ ] Monitoring DB connection pool

---

## 🔗 Fichiers Clés à Modifier

1. `data_ingestion/indexer/copy_trading_listener.py` - Ajouter filtrage address_type
2. `telegram_bot/api/v1/webhooks/copy_trade.py` - Standardiser address_type
3. `core/services/smart_trading/service.py` - Standardiser address_type
4. `telegram_bot/handlers/smart_trading/view_handler.py` - Utiliser APIClient
5. `telegram_bot/handlers/smart_trading/callbacks.py` - Utiliser APIClient

---

## ✅ Points Positifs

1. ✅ Architecture micro-services bien séparée
2. ✅ Webhook receiver robuste avec retry logic
3. ✅ Copy Trading Listener bien structuré avec deduplication
4. ✅ TradeService supporte copy trading flag
5. ✅ Handlers Telegram complets
6. ✅ API endpoints REST complets
7. ✅ Redis PubSub intégré
8. ✅ Cache manager pour watched addresses

---

**Conclusion:** L'architecture est solide mais nécessite quelques corrections critiques avant production, principalement autour de la standardisation `address_type` et du filtrage des messages Redis.
