# 📝 TECHNICAL DECISIONS (ADRs)

**Architecture Decision Records**
**Project:** Polycool Telegram Bot Rebuild

---

## 📋 FORMAT ADR

Chaque décision suit ce format:

```
## ADR-XXX: [Titre Court]

**Date:** YYYY-MM-DD
**Status:** Accepted | Rejected | Superseded
**Contexte:** Problème à résoudre
**Décision:** Solution choisie
**Conséquences:** Impacts positifs et négatifs
**Alternatives:** Options considérées mais rejetées
```

---

## ADR-001: User Stages Simplifiés (2 au lieu de 5)

**Date:** 2025-11-06
**Status:** ✅ Accepted

### Contexte
Le système actuel utilise 5 stages utilisateur (CREATED, SOL_GENERATED, FUNDED, APPROVED, READY) ce qui:
- Complexifie la logique conditionnelle
- Confond l'utilisateur
- Rend le debugging difficile
- Multiplie les edge cases

### Décision
**Réduire à 2 stages seulement:**
```python
class UserStage(Enum):
    ONBOARDING = "onboarding"  # Wallets créés, attente funding
    READY = "ready"             # Funded + approved + API keys
```

**Approvals et API keys en background:**
- User voit loader "Setting up your account..." (30s-1min)
- Pas de stages intermédiaires visibles

### Conséquences

**Positives:**
- UX plus claire
- Moins de logique conditionnelle (-60% code)
- Fewer edge cases
- Debug plus simple

**Négatives:**
- Moins de granularité pour monitoring
- Nécessite background jobs solides

### Alternatives Rejetées
1. **Garder 5 stages** → Trop complexe
2. **3 stages (ONBOARDING, FUNDING, READY)** → Encore trop granulaire
3. **1 stage (READY only)** → Pas assez de distinction

---

## ADR-002: Table Unique pour Markets

**Date:** 2025-11-06
**Status:** ✅ Accepted

### Contexte
Actuellement 3+ tables pour marchés:
- `markets` (obsolète)
- `subsquid_markets_poll`
- `subsquid_markets_ws`
- `subsquid_markets_wh`

**Problèmes:**
- Duplication données
- Queries complexes (JOINs)
- Synchro difficile
- Source of truth unclear

### Décision
**Table unique `markets` avec field `source`:**
```sql
CREATE TABLE markets (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,  -- 'poll', 'ws', 'api'
    ...
)
```

**Priority lors des conflits:**
1. WebSocket (most recent)
2. Polling (enriched data)
3. API (fallback)

### Conséquences

**Positives:**
- Single source of truth
- Queries simplifiées
- Performance améliorée (pas de JOINs)
- Maintenance facile

**Négatives:**
- Migration nécessaire depuis 3 tables
- Logic de priorité à implémenter

### Alternatives Rejetées
1. **Garder 3 tables séparées** → Complexité excessive
2. **Views materialisées** → Overhead et lag
3. **Table par source + union views** → Encore trop complexe

---

## ADR-003: Cache Centralisé (CacheManager)

**Date:** 2025-11-06
**Status:** ✅ Accepted

### Contexte
Cache actuellement dispersé partout:
- redis_price_cache.py
- position_cache_service.py
- market_cache_preloader.py
- Logique cache dans handlers

**Problèmes:**
- Duplication logique TTL
- Pas de centralisation strategy
- Monitoring fragmenté
- Invalidation manuelle partout

### Décision
**Service unique `CacheManager`:**
```python
class CacheManager:
    def __init__(self):
        self.ttls = {
            'prices': 20,
            'positions': 180,
            'markets_list': 300,
            'market_detail': 600,
            'user_profile': 3600
        }

    def get(self, key, data_type):
        """Auto TTL selon data_type"""

    def set(self, key, value, data_type):
        """Auto TTL selon data_type"""

    def invalidate(self, pattern):
        """Pattern-based invalidation"""
```

### Conséquences

**Positives:**
- Logique centralisée
- TTL strategy cohérente
- Monitoring unifié
- Invalidation intelligente

**Négatives:**
- Single point of failure (mitigé par fallback API)
- Nécessite refactoring code existant

### Alternatives Rejetées
1. **Garder cache dispersé** → Tech debt continue
2. **Cache per-service** → Duplication logique
3. **No caching** → Performance catastrophique

---

## ADR-004: WebSocket Selectif (Positions Actives Uniquement)

**Date:** 2025-11-06
**Status:** ✅ Accepted

### Contexte
**Impossible de streamer tous les marchés:**
- Volume trop élevé
- Coût bandwidth
- Overhead processing

**Besoin:**
- Prix temps réel pour positions actives
- Détection trigger TP/SL rapide

### Décision
**Subscribe WebSocket APRÈS trade uniquement:**

```python
# Post-trade
await websocket_manager.subscribe_user_positions(user_id)

# Position fermée
await websocket_manager.unsubscribe_if_no_other_users(market_id)
```

**Marchés non-actifs:**
- Polling data (60s refresh)
- On-demand fetch si user clique

### Conséquences

**Positives:**
- Bandwidth optimal
- Processing réduit
- Focus sur marchés pertinents
- Scalable

**Négatives:**
- Prix pas temps réel pour browse markets
- Logic subscribe/unsubscribe à gérer

### Alternatives Rejetées
1. **Stream tous les marchés** → Impossible à scale
2. **Stream top 100 volume** → Pas forcément pertinent pour user
3. **No WebSocket** → TP/SL triggers lents

---

## ADR-005: File Size Limit 700 Lignes (STRICT)

**Date:** 2025-11-06
**Status:** ✅ Accepted

### Contexte
**Fichiers actuels >1500 lignes:**
- Difficult à review
- Maintenance complexe
- Merge conflicts fréquents
- Violation single responsibility

### Décision
**STRICT 700 lignes maximum par fichier:**

**Stratégie découpage:**
- Handlers par fonctionnalité (markets/hub.py, markets/search.py)
- Services par domaine (user/wallet_service.py, user/onboarding_service.py)
- Tests à côté du code

**Enforcement:**
- Pre-commit hook
- CI check
- Code review

### Conséquences

**Positives:**
- Code review facile
- Maintenance simple
- Encourage single responsibility
- Moins de merge conflicts

**Négatives:**
- Plus de fichiers
- Navigation entre fichiers
- Risk de over-splitting

### Alternatives Rejetées
1. **1000 lignes** → Encore trop
2. **500 lignes** → Trop strict, trop de fichiers
3. **Pas de limite** → Tech debt continue

---

## ADR-006: Tests TDD (Write Tests First)

**Date:** 2025-11-06
**Status:** ✅ Accepted

### Contexte
**Code actuel sans tests:**
- Regression bugs fréquents
- Refactoring risqué
- Confidence faible pour changes

### Décision
**TDD strict:**
```
1. Write failing test
2. Write minimal code to pass
3. Refactor
4. Repeat
```

**Coverage targets:**
- 70% global
- 90% security-critical code
- 100% business logic core

**Structure tests:**
```
tests/
├── unit/        # 60% coverage
├── integration/ # 30% coverage
└── e2e/         # 10% coverage
```

### Conséquences

**Positives:**
- Bug detection early
- Regression prevention
- Refactoring confidence
- Documentation via tests

**Négatives:**
- Slower development initially
- Learning curve TDD
- Maintenance test code

### Alternatives Rejetées
1. **Tests après code** → Bias vers tests qui passent
2. **Pas de tests** → Inacceptable
3. **Tests manuels seulement** → Non scalable

---

## ADR-007: Réutiliser Code Existant (80%)

**Date:** 2025-11-06
**Status:** ✅ Accepted

### Contexte
**Code existant qui fonctionne bien:**
- Markets flow (search, categories, trending)
- Smart trading display
- Copy trading logic
- TP/SL monitoring
- Bridge system
- Encryption

### Décision
**NE PAS RECODER ce qui fonctionne:**

**À réutiliser (80%):**
- ✅ Handlers (markets, smart_trading, copy_trading)
- ✅ Services (bridge, encryption, tpsl)
- ✅ Utilities (formatters, validators)

**À refactoriser (20%):**
- ⚠️ Data schema (3 tables → 1)
- ⚠️ Cache (dispersé → centralisé)
- ⚠️ File sizes (>1500 lignes → < 700)
- ⚠️ User stages (5 → 2)

### Conséquences

**Positives:**
- Development rapide (5-7 semaines vs 3-4 mois from scratch)
- Code testé en production
- Features connues

**Négatives:**
- Dépendance code legacy
- Risk de reporter bugs existants
- Refactoring partiel délicat

### Alternatives Rejetées
1. **Recode from scratch** → 3-4 mois
2. **Garder tout tel quel** → Tech debt continue
3. **Refactoring total** → Risk élevé

---

## ADR-008: MCP Context7 pour Documentation

**Date:** 2025-11-06
**Status:** ✅ Accepted

### Contexte
**Documentation externe nombreuse:**
- Telegram Bot API
- Polymarket CLOB API
- Solana/Polygon RPCs
- DeBridge, Jupiter APIs

**Problème:**
- Docs éparpillées
- Versions différentes
- Recherche manuelle lente

### Décision
**Utiliser MCP Context7 systématiquement:**

```python
# Avant de coder une integration
mcp_context7_get_library_docs(
    context7CompatibleLibraryID='/python-telegram-bot/python-telegram-bot',
    topic='webhooks'
)

# Documentation toujours à jour
```

### Conséquences

**Positives:**
- Docs always up-to-date
- Recherche rapide
- Examples pertinents
- Moins d'erreurs d'intégration

**Négatives:**
- Dépendance service externe
- Learning curve MCP
- Possible rate limits

### Alternatives Rejetées
1. **Docs manuelles** → Obsolètes rapidement
2. **Copy-paste docs** → Maintenance overhead
3. **Trial & error** → Time wasted

---

## 📊 SUMMARY DECISIONS

| ADR | Décision | Impact | Status |
|-----|----------|--------|--------|
| 001 | User stages: 5 → 2 | 🟢 Haute | ✅ Accepted |
| 002 | Markets: 3 tables → 1 | 🟢 Haute | ✅ Accepted |
| 003 | Cache centralisé | 🟡 Moyenne | ✅ Accepted |
| 004 | WebSocket selectif | 🟡 Moyenne | ✅ Accepted |
| 005 | File size < 700 lignes | 🟢 Haute | ✅ Accepted |
| 006 | TDD strict | 🟢 Haute | ✅ Accepted |
| 007 | Réutiliser 80% code | 🟢 Haute | ✅ Accepted |
| 008 | MCP Context7 | 🟡 Moyenne | ✅ Accepted |

---

## 🔄 PROCESS UPDATE ADRs

**Pour ajouter une nouvelle décision:**

1. Créer `ADR-XXX: [Titre]`
2. Remplir template complet
3. Discuter avec équipe
4. Update status (Proposed → Accepted/Rejected)
5. Implémenter si Accepted
6. Review après 1 mois

---

**Dernière mise à jour:** 6 novembre 2025
**Total ADRs:** 8
**Status:** Active documentation
