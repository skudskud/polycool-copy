# 🔍 AUDIT ARCHITECTURE - Polycool Rebuild

**Date:** 2025-01-XX
**Projet:** `/polycool/polycool-rebuild`
**Architecture:** Multi-services Railway (API + BOT + WORKERS)

---

## 📊 RÉSUMÉ EXÉCUTIF

### ✅ Points Forts
- Architecture multi-services bien séparée (API, BOT, WORKERS)
- Communication bot-API via HTTP avec cache Redis
- Base de données centralisée dans l'API
- Configuration Railway correcte avec fichiers séparés

### ⚠️ Points d'Attention
- **CRITIQUE:** Le bot initialise quand même la DB malgré `SKIP_DB=true`
- Certains handlers utilisent encore l'accès DB direct au lieu de l'API client
- Pas de vérification de santé de l'API avant les appels
- Cache Redis partagé mais pas de stratégie d'invalidation cohérente

---

## 🏗️ ARCHITECTURE ACTUELLE

### Structure des Services Railway

```
┌─────────────────────────────────────────────────────────────┐
│                    Railway Project                            │
│              (cheerful-fulfillment)                           │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ polycool-api │    │ polycool-bot │    │polycool-     │  │
│  │              │    │              │    │  workers     │  │
│  │ FastAPI      │    │ Telegram Bot │    │ Background   │  │
│  │              │    │              │    │              │  │
│  │ SKIP_DB=false│    │ SKIP_DB=true │    │ SKIP_DB=false│  │
│  │              │    │              │    │              │  │
│  │ ✅ DB Access │    │ ❌ No DB     │    │ ✅ DB Access │  │
│  │ ✅ HTTP API  │    │ ✅ HTTP API  │    │ ✅ Streamer  │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                   │           │
│         └───────────────────┼───────────────────┘           │
│                             │                               │
│                    ┌─────────▼─────────┐                    │
│                    │   Supabase Pooler │                    │
│                    │  (PostgreSQL DB)  │                    │
│                    └────────────────────┘                    │
│                                                               │
│                    ┌────────────────────┐                    │
│                    │   Redis (shared)  │                    │
│                    │  Cache + PubSub   │                    │
│                    └────────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

### Configuration Railway

#### 1. **polycool-api** (`railway.api.json` / `railway.json`)
```json
{
  "deploy": {
    "startCommand": "python api_only.py",
    "healthcheckPath": "/health/live",
    "readinessProbe": {
      "path": "/health/ready",
      "port": "$PORT"
    }
  }
}
```

**Variables d'environnement:**
- `SKIP_DB=false` → Initialise la DB
- `STREAMER_ENABLED=false` → Pas de workers
- `DATABASE_URL` → Supabase Pooler
- `REDIS_URL` → Redis partagé

**Responsabilités:**
- ✅ Gestion HTTP API (FastAPI)
- ✅ Accès base de données (PostgreSQL)
- ✅ Endpoints REST pour bot et workers
- ✅ Health checks

#### 2. **polycool-bot** (`railway.bot.json`)
```json
{
  "deploy": {
    "startCommand": "python bot_only.py",
    "restartPolicyType": "ALWAYS"
  }
}
```

**Variables d'environnement:**
- `SKIP_DB=true` → **NE DEVRAIT PAS** init la DB
- `STREAMER_ENABLED=false` → Pas de workers
- `API_URL` → URL de l'API (https://polycool-api-production.up.railway.app)
- `REDIS_URL` → Redis partagé

**Responsabilités:**
- ✅ Interface Telegram (polling)
- ✅ Handlers utilisateur (`/start`, `/wallet`, `/markets`, etc.)
- ❌ **PROBLÈME:** Initialise quand même la DB (voir `bot_only.py:29-35`)

#### 3. **polycool-workers** (`railway.workers.json`)
```json
{
  "deploy": {
    "startCommand": "python workers.py",
    "restartPolicyType": "ALWAYS"
  }
}
```

**Variables d'environnement:**
- `SKIP_DB=false` → Initialise la DB
- `STREAMER_ENABLED=true` → Active le streamer
- `TPSL_MONITORING_ENABLED=true` → Active le monitoring TP/SL

**Responsabilités:**
- ✅ WebSocket streamer (prix marchés)
- ✅ TP/SL monitor (déclenchement ordres)
- ✅ Copy-trading listener (Redis Pub/Sub)
- ✅ Pollers (discovery, events, resolutions, price)

---

## 🔗 CONNEXIONS BOT ↔ API

### Architecture de Communication

```
┌─────────────────┐                    ┌─────────────────┐
│  Telegram Bot   │                    │   FastAPI API   │
│  (bot_only.py)  │                    │  (api_only.py) │
│                 │                    │                 │
│  Handlers:      │                    │  Endpoints:     │
│  - /start       │                    │  - POST /users │
│  - /wallet      │  HTTP Requests     │  - GET /users/  │
│  - /positions   │◄───────────────────►│  - GET /wallet/ │
│  - /markets     │                    │  - GET /positions│
│                 │                    │  - POST /positions/sync│
│  APIClient      │                    │                 │
│  (api_client.py)│                    │  Database       │
│                 │                    │  (PostgreSQL)   │
└─────────────────┘                    └─────────────────┘
         │                                      │
         └──────────────┬───────────────────────┘
                        │
                ┌───────▼───────┐
                │  Redis Cache  │
                │  (shared)     │
                └───────────────┘
```

### Implémentation Actuelle

#### ✅ **APIClient** (`core/services/api_client/api_client.py`)

**Fonctionnalités:**
- ✅ HTTP client avec `httpx.AsyncClient`
- ✅ Cache Redis intégré (via `CacheManager`)
- ✅ Retry logic (3 tentatives avec backoff exponentiel)
- ✅ Rate limiting (100 req/min)
- ✅ Circuit breaker (protection contre API down)
- ✅ Gestion d'erreurs robuste

**Méthodes principales:**
```python
# User management
await api_client.get_user(telegram_user_id)
await api_client.create_user(...)

# Wallet & Positions
await api_client.get_wallet_balance(user_id)
await api_client.get_user_positions(user_id)
await api_client.sync_positions(user_id)

# Markets
await api_client.get_trending_markets(...)
await api_client.get_category_markets(...)
await api_client.search_markets(...)

# Copy Trading
await api_client.subscribe_to_leader(...)
await api_client.get_follower_allocation(user_id)
```

#### ✅ **User Helper** (`core/services/user/user_helper.py`)

**Fonction utilitaire centrale:**
```python
async def get_user_data(telegram_user_id: int) -> Optional[Dict[str, Any]]:
    """
    Get user data - uses API client if SKIP_DB=true,
    otherwise direct DB access
    """
    if SKIP_DB:
        api_client = get_api_client()
        return await api_client.get_user(telegram_user_id)
    else:
        user = await user_service.get_by_telegram_id(telegram_user_id)
        # Convert to dict...
```

**✅ Utilisé dans:**
- `start_handler.py` → Création utilisateur via API
- `positions_handler.py` → Récupération positions via API
- `wallet_handler.py` → Affichage wallet via API
- `clob_service.py` → Récupération clés privées via API

---

## 🗄️ GESTION BASE DE DONNÉES

### ✅ **API Service** (`api_only.py`)

**Initialisation DB:**
```python
if os.getenv("SKIP_DB", "false").lower() != "true":
    await init_db()
    logger.info("✅ Database initialized")
```

**✅ Correct:** L'API initialise la DB car `SKIP_DB=false`

**Endpoints DB:**
- `POST /api/v1/users` → Crée utilisateur en DB
- `GET /api/v1/users/{telegram_user_id}` → Lit depuis DB
- `GET /api/v1/positions/user/{user_id}` → Lit positions depuis DB
- `POST /api/v1/positions/sync/{user_id}` → Sync depuis blockchain → DB

### ⚠️ **BOT Service** (`bot_only.py`)

**Code actuel (PROBLÈME):**
```python
# Always initialize database connection (required for trade_service and other DB operations)
# SKIP_DB only controls whether services USE the database, not whether it's initialized
from core.database.connection import init_db
try:
    await init_db()
    logger.info("✅ Database initialized")
except Exception as e:
    logger.warning(f"⚠️ Database initialization failed: {e}")
```

**❌ PROBLÈME:** Le bot initialise la DB même avec `SKIP_DB=true`

**Commentaire dans le code:**
> "SKIP_DB only controls whether services USE the database, not whether it's initialized"

**⚠️ RISQUE:**
- Connexions DB inutiles depuis le bot
- Risque de timeout si DB inaccessible
- Violation de l'architecture prévue (bot ne devrait pas toucher la DB)

**✅ SOLUTION RECOMMANDÉE:**
```python
# Ne PAS initialiser la DB si SKIP_DB=true
if os.getenv("SKIP_DB", "true").lower() != "true":
    from core.database.connection import init_db
    try:
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.warning(f"⚠️ Database initialization failed: {e}")
else:
    logger.info("⚠️ Database initialization skipped (SKIP_DB=true)")
```

### ✅ **WORKERS Service** (`workers.py`)

**Initialisation DB:**
```python
if os.getenv("SKIP_DB", "true").lower() != "true":
    from core.database.connection import init_db
    try:
        await init_db()
        logger.info("✅ Database initialized")
except Exception as e:
    logger.error(f"❌ Database initialization failed: {e}")
```

**✅ Correct:** Les workers initialisent la DB car `SKIP_DB=false`

---

## 🔍 ANALYSE DES HANDLERS

### ✅ Handlers Utilisant Correctement l'API Client

#### 1. **Start Handler** (`telegram_bot/bot/handlers/start_handler.py`)
```python
# ✅ Utilise get_user_data() helper
user_data = await get_user_data(user_id)

# ✅ Création utilisateur via API si SKIP_DB
if SKIP_DB:
    api_client = get_api_client()
    user_data = await api_client.create_user(...)
```

#### 2. **Positions Handler** (`telegram_bot/bot/handlers/positions_handler.py`)
```python
# ✅ Sync positions via API
if SKIP_DB:
    api_client = get_api_client()
    sync_result = await api_client.sync_positions(internal_id)

# ✅ Récupération positions via API
if SKIP_DB:
    positions_data = await api_client.get_user_positions(internal_id)
```

#### 3. **Wallet Handler** (`telegram_bot/bot/handlers/wallet_handler.py`)
```python
# ✅ Utilise get_user_data() helper
user_data = await get_user_data(user_id)
```

### ⚠️ Handlers à Vérifier

#### 1. **Markets Handler** (`telegram_bot/bot/handlers/markets_handler.py`)
- ✅ Utilise `api_client.get_trending_markets()` pour SKIP_DB
- ⚠️ Vérifier si tous les chemins utilisent l'API client

#### 2. **Trading Handler** (`telegram_bot/bot/handlers/markets/trading.py`)
- ⚠️ Vérifier si les trades utilisent l'API ou accès DB direct
- ⚠️ Les trades nécessitent des clés privées (via API client)

#### 3. **Copy Trading Handlers**
- ⚠️ Vérifier si tous utilisent `api_client.subscribe_to_leader()`
- ⚠️ Certains fichiers dans `telegram_bot/handlers/copy_trading/` peuvent encore utiliser DB direct

---

## 🚨 PROBLÈMES IDENTIFIÉS

### 🔴 **CRITIQUE: Bot Initialise la DB**

**Fichier:** `bot_only.py:29-35`

**Problème:**
```python
# Always initialize database connection
from core.database.connection import init_db
try:
    await init_db()  # ❌ S'exécute même avec SKIP_DB=true
```

**Impact:**
- Connexions DB inutiles depuis le bot
- Risque de timeout au démarrage si DB inaccessible
- Violation de l'architecture prévue

**Solution:**
```python
if os.getenv("SKIP_DB", "true").lower() != "true":
    from core.database.connection import init_db
    await init_db()
else:
    logger.info("⚠️ Database initialization skipped (SKIP_DB=true)")
```

### 🟡 **MOYEN: Pas de Health Check API**

**Problème:**
- Le bot n'vérifie pas si l'API est disponible avant les appels
- Si l'API est down, tous les appels échouent sans fallback

**Solution:**
- Ajouter un health check au démarrage du bot
- Utiliser le circuit breaker existant dans `APIClient`
- Afficher un message d'erreur clair si l'API est inaccessible

### 🟡 **MOYEN: Cache Invalidation Incohérente**

**Problème:**
- Certains endpoints invalident le cache, d'autres non
- Pas de stratégie claire pour l'invalidation

**Solution:**
- Documenter la stratégie d'invalidation
- Utiliser des patterns cohérents (`invalidate_pattern()`)

### 🟢 **FAIBLE: Handlers Mixtes**

**Problème:**
- Certains handlers utilisent encore `user_service` directement au lieu de `get_user_data()`

**Solution:**
- Audit complet des handlers
- Migration progressive vers `get_user_data()` helper

---

## ✅ RECOMMANDATIONS

### 1. **Corriger l'Initialisation DB du Bot**

**Priorité:** 🔴 CRITIQUE

**Action:**
```python
# bot_only.py
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

if not SKIP_DB:
    from core.database.connection import init_db
    await init_db()
else:
    logger.info("⚠️ Database initialization skipped (SKIP_DB=true)")
```

### 2. **Ajouter Health Check API au Démarrage**

**Priorité:** 🟡 MOYEN

**Action:**
```python
# bot_only.py
async def _check_api_health():
    api_client = get_api_client()
    try:
        response = await api_client.client.get(f"{api_client.api_url}/health/live")
        if response.status_code == 200:
            logger.info("✅ API service is healthy")
            return True
    except Exception as e:
        logger.error(f"❌ API service is not available: {e}")
        return False

# Dans _run_bot()
if not await _check_api_health():
    logger.error("❌ Cannot start bot: API service unavailable")
    raise RuntimeError("API service unavailable")
```

### 3. **Audit Complet des Handlers**

**Priorité:** 🟡 MOYEN

**Action:**
- Lister tous les handlers qui utilisent `user_service` directement
- Migrer vers `get_user_data()` helper
- Tester avec `SKIP_DB=true`

### 4. **Documenter la Stratégie de Cache**

**Priorité:** 🟢 FAIBLE

**Action:**
- Documenter les TTL par type de données
- Documenter les patterns d'invalidation
- Créer un guide pour les développeurs

### 5. **Tests d'Intégration Bot-API**

**Priorité:** 🟡 MOYEN

**Action:**
- Tests avec `SKIP_DB=true` pour le bot
- Tests avec API mockée
- Tests de fallback si API down

---

## 📋 CHECKLIST DE VALIDATION

### Architecture
- [x] Services séparés (API, BOT, WORKERS)
- [x] Configuration Railway correcte
- [x] Variables d'environnement définies
- [ ] Bot ne doit PAS initialiser la DB (❌ PROBLÈME)

### Communication Bot-API
- [x] APIClient implémenté avec retry/cache
- [x] User helper fonctionne avec SKIP_DB
- [x] Handlers principaux utilisent l'API client
- [ ] Health check API au démarrage (❌ MANQUANT)
- [ ] Tous les handlers migrés (⚠️ PARTIEL)

### Base de Données
- [x] API gère la DB correctement
- [x] Workers gèrent la DB correctement
- [ ] Bot ne doit PAS toucher la DB (❌ PROBLÈME)

### Cache Redis
- [x] Cache partagé entre services
- [x] TTL configurés
- [ ] Stratégie d'invalidation documentée (⚠️ PARTIEL)

---

## 📝 CONCLUSION

### État Actuel
L'architecture multi-services est **globalement bien implémentée** avec:
- ✅ Séparation claire des responsabilités
- ✅ Communication bot-API fonctionnelle
- ✅ Cache Redis partagé
- ✅ Configuration Railway correcte

### Actions Prioritaires
1. **🔴 CRITIQUE:** Corriger l'initialisation DB du bot (`bot_only.py`)
2. **🟡 MOYEN:** Ajouter health check API au démarrage
3. **🟡 MOYEN:** Audit complet des handlers pour migration API client

### Architecture Recommandée (Finale)

```
┌─────────────────┐                    ┌─────────────────┐
│  Telegram Bot   │                    │   FastAPI API   │
│  SKIP_DB=true   │  HTTP + Cache      │  SKIP_DB=false  │
│  ❌ No DB Init  │◄───────────────────►│  ✅ DB Access   │
│  ✅ API Client  │                    │  ✅ Endpoints   │
└─────────────────┘                    └─────────────────┘
         │                                      │
         └──────────────┬───────────────────────┘
                        │
                ┌───────▼───────┐
                │  Redis Cache  │
                │  (shared)     │
                └───────────────┘
                        │
                ┌───────▼───────┐
                │  Supabase DB  │
                │  (via API)    │
                └───────────────┘
```

---

**Rapport généré le:** 2025-01-XX
**Prochaine révision:** Après corrections critiques
