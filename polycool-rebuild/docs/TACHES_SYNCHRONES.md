# ⏰ Tâches Synchrones - État Actuel

**Date:** Décembre 2024
**Status:** ⚠️ **Tâches Partielles - Pas de Scheduler Centralisé**

---

## 📋 Résumé Exécutif

### État Actuel

**Tâches Implémentées (Boucles `while` + `asyncio.sleep`):**
- ✅ Poller (60s intervals)
- ✅ WebSocket Streamer (continu)
- ✅ Subscription Manager Cleanup (5min intervals)

**Tâches Manquantes (Présentes dans l'Ancien Code):**
- ❌ TP/SL Monitoring (10s intervals)
- ❌ Position Price Updates automatiques
- ❌ Market Resolution Detection
- ❌ Watched Addresses Cache Refresh
- ❌ Smart Wallet Trades Filter Processor

**Architecture:**
- ⚠️ Pas de scheduler centralisé (APScheduler)
- ⚠️ Tâches gérées via boucles `while` dans chaque service

---

## ✅ Tâches Actuellement Implémentées

### 1. Poller - Gamma API (60s) ✅

**Fichier:** `data_ingestion/poller/gamma_api.py`

**Implémentation:**
```python
async def start_polling(self) -> None:
    self.running = True
    while self.running:
        try:
            await self._poll_cycle()
            await asyncio.sleep(self.poll_interval)  # 60s
        except Exception as e:
            logger.error(f"Poller error: {e}")
            await asyncio.sleep(120)  # Backoff on error
```

**Status:** ✅ Fonctionnel
**Intervalle:** 60 secondes
**Démarrage:** Via `asyncio.create_task()` dans `main.py` (si `POLLER_ENABLED=true`)

**Note:** Le poller n'est pas démarré automatiquement dans `main.py` actuellement.

---

### 2. WebSocket Streamer (Continu) ✅

**Fichier:** `data_ingestion/streamer/websocket_client/websocket_client.py`

**Implémentation:**
```python
async def start(self) -> None:
    self.running = True
    while self.running:
        try:
            await self._connect_and_stream()
        except Exception as e:
            await asyncio.sleep(min(self.backoff_seconds, self.max_backoff))
```

**Status:** ✅ Fonctionnel
**Type:** Continu (reconnect automatique)
**Démarrage:** Via `StreamerService.start()` dans `main.py` (si `STREAMER_ENABLED=true`)

---

### 3. Subscription Manager Cleanup (5min) ✅

**Fichier:** `data_ingestion/streamer/subscription_manager.py`

**Implémentation:**
```python
async def _periodic_cleanup(self) -> None:
    while self.running:
        try:
            await asyncio.sleep(self.cleanup_interval)  # 300s = 5min
            await self._cleanup_unused_subscriptions()
        except Exception as e:
            logger.error(f"⚠️ Error in periodic cleanup: {e}")
            await asyncio.sleep(60)  # Wait before retrying
```

**Status:** ✅ Fonctionnel
**Intervalle:** 5 minutes
**Fonction:** Nettoie les subscriptions WebSocket inutilisées

---

## ❌ Tâches Manquantes (Présentes dans l'Ancien Code)

### 1. TP/SL Monitoring (10s) ❌

**Ancien Code:** `telegram-bot-v2/py-clob-server/telegram_bot/services/price_monitor.py`

**Fonctionnalité:**
- Monitor toutes les positions avec TP/SL actifs
- Vérifie prix toutes les 10 secondes
- Déclenche sell automatique si TP/SL atteint

**Status:** ❌ **NON IMPLÉMENTÉ**

**À Implémenter:**
```python
# core/services/trading/tpsl_monitor.py (à créer)
class TPSLMonitor:
    async def start_monitoring(self):
        while self.running:
            await self._check_all_active_orders()
            await asyncio.sleep(10)  # 10s intervals
```

**Priorité:** 🔴 **HAUTE** (Feature critique)

---

### 2. Position Price Updates Automatiques ❌

**Fonctionnalité:**
- Met à jour `positions.current_price` automatiquement
- Recalcule P&L en temps réel
- Déclenché par WebSocket price updates

**Status:** ❌ **NON IMPLÉMENTÉ**

**À Implémenter:**
- Hook dans `MarketUpdater.handle_price_update()`
- Appeler `position_service.update_position_price()` automatiquement

**Priorité:** 🔴 **HAUTE** (Feature critique)

---

### 3. Market Resolution Detection ❌

**Ancien Code:** `apps/resolution-worker/`

**Fonctionnalité:**
- Détecte marchés résolus (toutes les heures)
- Met à jour positions → 'redeemed'
- Envoie notifications Telegram

**Status:** ❌ **NON IMPLÉMENTÉ**

**À Implémenter:**
```python
# core/services/market/resolution_detector.py (à créer)
class ResolutionDetector:
    async def check_resolutions(self):
        # Check for newly resolved markets
        # Update positions
        # Send notifications
```

**Priorité:** 🟡 **MOYENNE**

---

### 4. Watched Addresses Cache Refresh (1min) ❌

**Ancien Code:** `telegram-bot-v2/py-clob-server/main.py` (ligne 347)

**Fonctionnalité:**
- Refresh cache Redis des watched addresses
- Synchronisé avec indexer refresh interval

**Status:** ❌ **NON IMPLÉMENTÉ**

**Priorité:** 🟢 **BASSE** (Dépend de l'Indexer)

---

### 5. Smart Wallet Trades Filter Processor (30s) ❌

**Ancien Code:** `telegram-bot-v2/py-clob-server/main.py` (ligne 362)

**Fonctionnalité:**
- Filtre trades des smart wallets
- Process cycle toutes les 30 secondes
- Détermine quels trades afficher dans `/smart_trading`

**Status:** ❌ **NON IMPLÉMENTÉ**

**Priorité:** 🟡 **MOYENNE** (Dépend de l'Indexer)

---

### 6. Push Notification Processor ❌

**Ancien Code:** `telegram-bot-v2/py-clob-server/main.py` (ligne 374)

**Fonctionnalité:**
- Process notifications en queue
- Envoie notifications Telegram batch

**Status:** ❌ **NON IMPLÉMENTÉ**

**Priorité:** 🟢 **BASSE**

---

## 🔧 Architecture Actuelle vs Recommandée

### Architecture Actuelle ⚠️

```
main.py
├─ asyncio.create_task(streamer.start())  # Boucle while
├─ asyncio.create_task(bot_app.start())  # Boucle while
└─ (Poller pas démarré automatiquement)
```

**Problèmes:**
- Pas de scheduler centralisé
- Tâches dispersées dans chaque service
- Difficile de monitorer toutes les tâches
- Pas de gestion d'erreurs centralisée

### Architecture Recommandée ✅

```
main.py
├─ APScheduler (scheduler centralisé)
│   ├─ Poller (60s)
│   ├─ TP/SL Monitor (10s)
│   ├─ Resolution Detector (1h)
│   ├─ Position Price Updater (10s)
│   └─ Subscription Cleanup (5min)
├─ Streamer (continu - boucle while OK)
└─ Bot (continu - boucle while OK)
```

**Avantages:**
- Centralisation des tâches
- Monitoring facile
- Gestion d'erreurs unifiée
- Configuration centralisée

---

## 📊 Comparaison: Ancien Code vs Rebuild

| Tâche | Ancien Code | Rebuild | Status |
|-------|-------------|---------|--------|
| **Poller** | ✅ APScheduler (60s) | ✅ Boucle while (60s) | ✅ OK |
| **Streamer** | ✅ Continu | ✅ Continu | ✅ OK |
| **Subscription Cleanup** | ✅ APScheduler (5min) | ✅ Boucle while (5min) | ✅ OK |
| **TP/SL Monitor** | ✅ APScheduler (10s) | ❌ Manquant | ❌ |
| **Position Price Updates** | ✅ Via WebSocket hook | ❌ Manquant | ❌ |
| **Resolution Detector** | ✅ Cron (1h) | ❌ Manquant | ❌ |
| **Watched Addresses Refresh** | ✅ APScheduler (1min) | ❌ Manquant | ❌ |
| **Smart Wallet Filter** | ✅ APScheduler (30s) | ❌ Manquant | ❌ |
| **Push Notifications** | ✅ APScheduler | ❌ Manquant | ❌ |

**Total:** 3/9 tâches implémentées (~33%)

---

## 🎯 Tâches à Implémenter (Par Priorité)

### Priorité 1 - Critique 🔴

#### 1. TP/SL Monitoring (10s)

**Fichier à créer:** `core/services/trading/tpsl_monitor.py`

```python
class TPSLMonitor:
    async def start_monitoring(self):
        """Monitor TP/SL orders every 10s"""
        while self.running:
            await self._check_all_active_orders()
            await asyncio.sleep(10)

    async def _check_all_active_orders(self):
        # Get active TP/SL orders
        # Check current prices
        # Trigger sells if TP/SL hit
```

**Démarrage:** Dans `main.py` lifespan

---

#### 2. Position Price Updates Automatiques (Via WebSocket Hook)

**Fichier à modifier:** `data_ingestion/streamer/market_updater/market_updater.py`

```python
async def handle_price_update(self, data):
    # ... update market ...

    # ✅ NOUVEAU: Trigger position updates
    await self._update_positions_for_market(market_id, prices)

async def _update_positions_for_market(self, market_id, prices):
    """Update all active positions for this market"""
    from core.services.position import position_service

    positions = await position_service.get_positions_by_market(market_id)
    for position in positions:
        outcome_price = prices.get(position.outcome)
        if outcome_price:
            await position_service.update_position_price(
                position.id, outcome_price
            )
```

**Démarrage:** Automatique via WebSocket

---

### Priorité 2 - Haute 🟡

#### 3. Market Resolution Detection (1h)

**Fichier à créer:** `core/services/market/resolution_detector.py`

```python
class ResolutionDetector:
    async def check_resolutions(self):
        """Check for newly resolved markets (every hour)"""
        # Query markets where end_date < now() and is_resolved = false
        # Check via Gamma API if resolved
        # Update positions → 'redeemed'
        # Send notifications
```

**Démarrage:** Via scheduler ou boucle while (1h)

---

### Priorité 3 - Moyenne 🟢

#### 4. Watched Addresses Cache Refresh (1min)

**Dépend de:** Indexer implémenté

**Fichier à créer:** `core/services/watched_addresses_cache.py`

```python
class WatchedAddressesCacheManager:
    async def refresh_cache(self):
        """Refresh Redis cache of watched addresses (every 1min)"""
        # Fetch from watched_addresses table
        # Update Redis cache
```

---

#### 5. Smart Wallet Trades Filter Processor (30s)

**Dépend de:** Indexer implémenté

**Fichier à créer:** `core/services/smart_wallet_trades_filter_processor.py`

```python
class SmartWalletTradesFilterProcessor:
    async def process_cycle(self):
        """Filter smart wallet trades (every 30s)"""
        # Get recent trades from indexer
        # Filter based on criteria
        # Mark as featured
```

---

## 🚀 Recommandations d'Implémentation

### Option A: Garder Boucles `while` (Simple) ⭐

**Avantages:**
- Simple à implémenter
- Pas de dépendance supplémentaire
- Déjà utilisé pour Poller/Streamer

**Inconvénients:**
- Pas de monitoring centralisé
- Gestion d'erreurs dispersée

**Implémentation:**
```python
# main.py lifespan
if settings.trading.tpsl_monitoring_enabled:
    from core.services.trading.tpsl_monitor import TPSLMonitor
    tpsl_monitor = TPSLMonitor()
    asyncio.create_task(tpsl_monitor.start_monitoring())
```

---

### Option B: Ajouter APScheduler (Recommandé pour Production) ⭐⭐

**Avantages:**
- Monitoring centralisé
- Gestion d'erreurs unifiée
- Configuration centralisée
- Compatible avec l'ancien code

**Inconvénients:**
- Dépendance supplémentaire (`apscheduler`)
- Plus complexe à setup

**Implémentation:**
```python
# main.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler()

# TP/SL Monitor (10s)
scheduler.add_job(
    tpsl_monitor.check_all_orders,
    trigger=IntervalTrigger(seconds=10),
    id='tpsl_monitor',
    replace_existing=True
)

# Resolution Detector (1h)
scheduler.add_job(
    resolution_detector.check_resolutions,
    trigger=IntervalTrigger(hours=1),
    id='resolution_detector',
    replace_existing=True
)

scheduler.start()
```

---

## 📋 Checklist d'Implémentation

### Phase 1: Tâches Critiques (Semaine 1)

- [ ] Implémenter hook position updates dans `MarketUpdater`
- [ ] Créer `TPSLMonitor` service
- [ ] Démarrer TP/SL monitoring dans `main.py`
- [ ] Tester avec positions actives

### Phase 2: Tâches Importantes (Semaine 2)

- [ ] Créer `ResolutionDetector` service
- [ ] Démarrer resolution detection (1h)
- [ ] Tester avec marchés résolus

### Phase 3: Tâches Optionnelles (Semaine 3+)

- [ ] Ajouter APScheduler (optionnel)
- [ ] Implémenter Watched Addresses Cache Refresh
- [ ] Implémenter Smart Wallet Trades Filter Processor

---

## ✅ Résumé

### Tâches Actuelles

| Tâche | Type | Intervalle | Status |
|-------|------|------------|--------|
| Poller | Boucle while | 60s | ✅ Implémenté |
| Streamer | Boucle while | Continu | ✅ Implémenté |
| Subscription Cleanup | Boucle while | 5min | ✅ Implémenté |

### Tâches Manquantes

| Tâche | Priorité | Effort |
|-------|----------|--------|
| TP/SL Monitor | 🔴 Haute | 1-2 jours |
| Position Price Updates | 🔴 Haute | 0.5 jour |
| Resolution Detector | 🟡 Moyenne | 1 jour |
| Watched Addresses Refresh | 🟢 Basse | 0.5 jour |
| Smart Wallet Filter | 🟢 Basse | 1 jour |

**Total Effort Estimé:** 4-5 jours pour toutes les tâches critiques

---

**Dernière mise à jour:** Décembre 2024
**Prochaine étape:** Implémenter hook position updates + TP/SL Monitor
