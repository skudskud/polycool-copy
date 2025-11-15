# 🎯 MASTER PLAN - Polycool Telegram Bot Rebuild

**Date:** Novembre 2025
**Version:** 1.0
**Status:** Planning Phase
**Project ID (Supabase):** xxzdlbwfyetaxcmodiec

---

## 📋 EXECUTIVE SUMMARY

### Objectif
Reconstruire le bot Telegram Polymarket en **réutilisant 80% du code existant** mais avec:
- ✅ Architecture modulaire et maintenable (fichiers < 700 lignes)
- ✅ Performance optimisée (< 500ms par handler)
- ✅ Cache centralisé et intelligent
- ✅ Data schema unifié et propre
- ✅ Tests automatisés (70% coverage, 90% security-critical)

### Principes Directeurs
1. **NE PAS RECODER** ce qui fonctionne déjà
2. **RÉUTILISER** et améliorer l'existant
3. **SIMPLIFIER** l'architecture (suppression complexité excessive)
4. **TESTER** tout au fur et à mesure (TDD)
5. **DOCUMENTER** avec MCP Context7

### Sources de Code Existant
```
/Users/ulyssepiediscalzi/Documents/polynuclear/polycool/telegram-bot-v2/py-clob-server/
/Users/ulyssepiediscalzi/Documents/polynuclear/polycool/apps/subsquid-silo-tests/
```

---

## 🎯 DÉCISIONS ARCHITECTURALES CLÉS

### 1. **User Stages Simplifiés**
**Décision:** Réduire de 5 stages à 2 stages seulement

```python
# ANCIEN (Complexe)
class UserStage(Enum):
    CREATED = "created"           # Polygon wallet only
    SOL_GENERATED = "sol_ready"   # Both wallets, unfunded
    FUNDED = "funded"             # Funded, approvals pending
    APPROVED = "approved"         # Approved, API keys pending
    READY = "ready"               # Fully operational

# NOUVEAU (Simplifié)
class UserStage(Enum):
    ONBOARDING = "onboarding"     # Wallets créés, attente funding
    READY = "ready"                # Funded + approved + API keys (tout en background)
```

**Rationale:**
- UX plus claire pour l'utilisateur
- Moins de logique conditionnelle
- Approvals + API keys en background (loader 30s-1min)

### 2. **Data Schema Unifié**

**Décision:** Table unique `markets` au lieu de 3 tables fragmentées

```sql
-- ANCIEN (Fragmenté)
- markets (obsolète)
- subsquid_markets_poll (polling)
- subsquid_markets_ws (websocket)
- subsquid_markets_wh (webhook)

-- NOUVEAU (Unifié)
CREATE TABLE markets (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,  -- 'poll', 'ws', 'api'
    title TEXT NOT NULL,
    outcomes TEXT[] NOT NULL,
    outcome_prices NUMERIC(8,4)[],
    events JSONB,          -- Event grouping metadata
    category TEXT,         -- Normalized category
    volume NUMERIC(18,4),
    last_trade_price NUMERIC(8,4),
    clob_token_ids JSONB,  -- For price lookups
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_outcome TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes optimisés
CREATE INDEX idx_markets_category ON markets(category);
CREATE INDEX idx_markets_volume ON markets(volume DESC);
CREATE INDEX idx_markets_updated ON markets(updated_at DESC);
CREATE INDEX idx_markets_events ON markets USING GIN (events);
CREATE INDEX idx_markets_token_ids ON markets USING GIN (clob_token_ids);
```

**Rationale:**
- Single source of truth
- Queries simplifiées
- Performance améliorée (moins de JOINs)

### 3. **Cache Centralisé**

**Décision:** Service unique `CacheManager` au lieu de cache dispersé partout

```python
# core/services/cache_manager.py (< 500 lignes)
class CacheManager:
    """
    Gestionnaire centralisé de cache Redis
    - Évite duplication logique
    - TTL stratégiques par type
    - Invalidation intelligente
    """

    def __init__(self):
        self.redis = get_redis_client()
        self.ttls = {
            'prices': 20,          # Ultra-court (WebSocket data)
            'positions': 180,      # Court (user portfolios)
            'markets_list': 300,   # Moyen (market pages)
            'market_detail': 600,  # Long (market metadata)
            'user_profile': 3600   # Très long (user data)
        }

    def get(self, key: str, data_type: str):
        """Get avec logging et metrics"""

    def set(self, key: str, value: Any, data_type: str):
        """Set avec TTL automatique selon data_type"""

    def invalidate(self, pattern: str):
        """Invalidation pattern-based"""
```

**Rationale:**
- Évite duplication logique cache
- Centralise TTL strategy
- Metrics et monitoring centralisés

### 4. **WebSocket Selectif**

**Décision:** Subscribe WebSocket UNIQUEMENT pour positions actives

```python
# core/services/websocket_manager.py (< 400 lignes)
class WebSocketManager:
    """
    Gère souscriptions WebSocket intelligentes
    - Subscribe APRÈS trade uniquement
    - Unsubscribe si position fermée
    - Batch subscribe/unsubscribe
    """

    async def subscribe_user_positions(self, user_id: int):
        """Subscribe aux marchés où user a positions"""
        positions = await position_service.get_active_positions(user_id)
        market_ids = [p.market_id for p in positions]
        await self._batch_subscribe(market_ids)

    async def on_trade_executed(self, user_id: int, market_id: str):
        """Auto-subscribe après trade"""
        await self._subscribe_single(market_id)

    async def on_position_closed(self, user_id: int, market_id: str):
        """Auto-unsubscribe après fermeture"""
        # Check si d'autres users ont positions sur ce marché
        other_users = await position_service.count_active_positions(market_id)
        if other_users == 0:
            await self._unsubscribe_single(market_id)
```

**Rationale:**
- Impossible de stream tous les marchés (trop de volume)
- Focus sur marchés pertinents pour user
- Performance optimale

### 5. **File Size Limits**

**Décision:** STRICT 700 lignes maximum par fichier

**Stratégie de découpage:**
```
telegram_bot/
├── handlers/
│   ├── markets/
│   │   ├── hub.py          (< 300 lignes - hub principal)
│   │   ├── search.py       (< 200 lignes - search logic)
│   │   ├── categories.py   (< 200 lignes - category browsing)
│   │   └── filters.py      (< 200 lignes - filtering logic)
│   ├── positions/
│   │   ├── view.py         (< 300 lignes - affichage positions)
│   │   ├── trade.py        (< 300 lignes - buy/sell)
│   │   └── tpsl.py         (< 400 lignes - TP/SL setup)
│   └── ...
```

**Rationale:**
- Maintenabilité
- Review de code facilité
- Évite complexité excessive par fichier

---

## 📊 PLAN D'IMPLÉMENTATION PAR PHASES

### Structure des Documents

```
docs/rebuild/
├── 00_MASTER_PLAN.md                    # ← Vous êtes ici
├── 01_PHASE_ARCHITECTURE.md             # Architecture & Data Schema
├── 02_PHASE_SECURITY.md                 # Sécurité & Encryption
├── 03_PHASE_CORE_FEATURES.md            # /start, /wallet, onboarding
├── 04_PHASE_TRADING.md                  # /markets, /positions
├── 05_PHASE_ADVANCED_TRADING.md         # /smart_trading, /copy_trading
├── 06_PHASE_DATA_INGESTION.md           # Poller, Streamer, Indexer
├── 07_PHASE_PERFORMANCE.md              # Cache, WebSocket, optimizations
└── 08_TECHNICAL_DECISIONS.md            # ADRs et décisions techniques
```

### Timeline Estimée

```
Phase 1: Architecture & Schema        → 3-4 jours   (local dev setup)
Phase 2: Security                      → 2-3 jours   (encryption, keys)
Phase 3: Core Features                 → 4-5 jours   (/start, /wallet)
Phase 4: Trading                       → 5-6 jours   (/markets, /positions)
Phase 5: Advanced Trading              → 4-5 jours   (smart/copy trading)
Phase 6: Data Ingestion                → 3-4 jours   (poller, streamer)
Phase 7: Performance & Cache           → 2-3 jours   (optimizations)
Phase 8: Testing & Documentation       → 2-3 jours   (final polish)

TOTAL: ~25-33 jours (5-7 semaines)
```

**Note:** Timeline aggressive car réutilisation massive du code existant.

---

## 🎯 FEATURES PAR PHASE

### **Phase 1: Architecture & Data Schema**
- ✅ Nouveau projet Supabase
- ✅ Schema SQL unifié
- ✅ Migrations scripts
- ✅ Local development setup
- ✅ Docker compose (Postgres + Redis local)

### **Phase 2: Security**
- ✅ Wallet generation (Polygon + Solana)
- ✅ AES-256-GCM encryption
- ✅ API keys management (Polymarket CLOB)
- ✅ Environment variables secure

### **Phase 3: Core Features**
- ✅ /start - Onboarding simplifié (2 stages)
- ✅ /wallet - Multi-wallet display
- ✅ Bridge SOL → USDC (réutiliser existant)
- ✅ Auto-approvals background
- ✅ /referral - Système existant

### **Phase 4: Trading**
- ✅ /markets - Hub (trending + categories + search)
- ✅ Market detail view (event grouping)
- ✅ Buy/Sell flow (fill-or-kill best price)
- ✅ /positions - Portfolio view
- ✅ TP/SL setup (optionnel, interface existante)
- ✅ Price monitoring (10s intervals)

### **Phase 5: Advanced Trading**
- ✅ /smart_trading - Recommendations (réutiliser)
- ✅ Smart wallets tracking (Watched Addresses)
- ✅ /copy_trading - Auto-copy (grand public)
- ✅ Budget allocation (% ou fixed amount)
- ✅ Webhook + Redis PubSub

### **Phase 6: Data Ingestion**
- ✅ Poller - Gamma API (60s interval)
- ✅ Streamer - WebSocket temps réel
- ✅ Indexer - On-chain fills tracking
- ✅ Watched Addresses management
- ✅ Market resolution detection

### **Phase 7: Performance & Cache**
- ✅ Cache centralisé (CacheManager)
- ✅ WebSocket selectif (positions actives)
- ✅ Price refresh strategy
- ✅ Query optimizations
- ✅ Load testing

---

## 🔧 OUTILS & STACK TECHNIQUE

### Core Stack
```
Python 3.11+
FastAPI (API + webhooks)
python-telegram-bot 20.x
PostgreSQL 15+ (Supabase)
Redis 7.x (cache + PubSub)
```

### Development Tools
```
pytest (testing)
black (code formatting)
mypy (type checking)
ruff (linting)
```

### Deployment
```
Railway (hosting)
Supabase (database)
Upstash/Railway Redis (cache)
```

### Monitoring (Phase finale)
```
Sentry (error tracking)
Prometheus + Grafana (metrics)
Railway native monitoring
```

---

## 📐 ARCHITECTURE DE DOSSIER PROPOSÉE

Voir [README_ARCHITECTURE.md](./README_ARCHITECTURE.md) pour structure détaillée.

**Principes:**
- Fichiers < 700 lignes (strict)
- Séparation handlers / services / repositories
- Tests à côté du code
- Configuration centralisée

---

## ✅ SUCCESS CRITERIA

### Performance
- [ ] Handlers < 500ms latency (p95)
- [ ] Cache hit rate > 90%
- [ ] Trade execution < 2s (p95)
- [ ] WebSocket < 100ms lag

### Quality
- [ ] 70% code coverage (global)
- [ ] 90% coverage (security-critical code)
- [ ] 0 fichiers > 700 lignes
- [ ] 0 critical linter errors

### User Experience
- [ ] Onboarding < 2min (funded → ready)
- [ ] Position visible immédiatement post-trade
- [ ] TP/SL triggers < 100ms après prix atteint (hybride WebSocket + polling)
- [ ] Markets refresh < 1s

### Reliability
- [ ] 99.9% uptime (Railway)
- [ ] 0 data loss
- [ ] Rollback procedures tested
- [ ] Error recovery automated

---

## 🚀 NEXT STEPS

1. **[Lire Phase 1](./01_PHASE_ARCHITECTURE.md)** - Architecture & Schema détaillé
2. **Setup environnement local** - Docker Compose + Supabase local
3. **Créer nouveau projet Supabase** - Migration du schema
4. **Commencer Phase 1 implémentation** - Core tables + migrations

---

## 📝 NOTES IMPORTANTES

### Code Réutilisable (NE PAS RECODER)
- ✅ Markets flow (search, categories, trending)
- ✅ Smart trading display et pagination
- ✅ Copy trading logic (budget allocation)
- ✅ TP/SL monitoring et execution
- ✅ Bridge system (SOL → USDC)
- ✅ Wallet encryption (AES-256-GCM)

### Code À Refactoriser (AMÉLIORER)
- ⚠️ Data schema (unifier 3 tables → 1 table)
- ⚠️ Cache management (centraliser)
- ⚠️ User stages (simplifier 5 → 2)
- ⚠️ File sizes (découper fichiers > 700 lignes)
- ⚠️ WebSocket (selectif au lieu de global)

### Code À Créer (NOUVEAU)
- 🆕 CacheManager service (centralisé)
- 🆕 WebSocketManager (subscribe selectif)
- 🆕 Tests automatisés (TDD)
- 🆕 Architecture modulaire (< 700 lignes par fichier)

---

**Dernière mise à jour:** 6 novembre 2025
**Auteur:** CTO Mode - Senior Software Engineer
**Status:** Ready for Phase 1 implementation
