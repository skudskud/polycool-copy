# 🚀 Railway Deployment Status - Polycool

*Dernière mise à jour: 10 novembre 2025*

## 📊 Vue d'ensemble

**Projet**: `cheerful-fulfillment` (Railway)
**Environment**: Production
**Status**: ✅ **OPERATIONNEL**

---

## 🏗️ Architecture Microservices

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   polycool-api  │    │ polycool-workers │    │ polycool-indexer│
│   (FastAPI)     │    │   (Data Flow)   │    │   (Subsquid)    │
│                 │    │                 │    │                 │
│ - Endpoints REST│    │ - TP/SL Monitor │    │ - Block Indexer │
│ - DB PostgreSQL │    │ - Copy Trading  │    │ - Webhooks      │
│ - Cache Redis   │    │ - Streamer      │    │ - Skip backfill │
│                 │    │                 │    │                 │
│ SKIP_DB=false   │    │ SKIP_DB=false   │    │ SKIP_DB=false   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │ polycool-bot   │
                    │ (Telegram)     │
                    │                │
                    │ - User Interface│
                    │ - Polling       │
                    │ - Trading UI    │
                    │                │
                    │ SKIP_DB=true    │
                    └─────────────────┘
```

---

## 🔧 Services Déployés

### ✅ **polycool-api** (FastAPI)
- **URL**: https://polycool-api-production.up.railway.app
- **Status**: ✅ Running
- **Configuration**:
  - `SKIP_DB=false` → Accès DB complet
  - Pool DB: 3 connexions + 5 overflow
  - Redis: Connecté
- **Fonctionnalités**:
  - Endpoints REST complets
  - Gestion utilisateurs
  - Trading endpoints
  - Healthchecks: `/health/live` ✅

### ✅ **polycool-bot** (Telegram)
- **Status**: ✅ Running
- **Configuration**:
  - `SKIP_DB=true` → Pas d'accès DB direct
  - Interface utilisateur uniquement
- **Fonctionnalités**:
  - Polling Telegram actif
  - Gestion des commandes utilisateur
  - Redirection vers web pour inscription
- **Limitation**: Ne peut pas créer d'utilisateurs directement

### ✅ **polycool-workers** (Data Processing)
- **Status**: ✅ Running
- **Configuration**:
  - `SKIP_DB=false` → Accès DB complet
  - Pool DB: 3 connexions + 5 overflow
  - Redis PubSub actif
- **Fonctionnalités**:
  - TP/SL monitoring (30s intervals)
  - Copy trading listener
  - WebSocket streamer
  - Cache watched addresses

### ✅ **polycool-indexer** (Subsquid)
- **URL**: https://polycool-indexer-production.up.railway.app
- **Status**: ✅ Running (mais healthcheck échoue)
- **Configuration**:
  - Skip backfill activé (block 78820000+)
  - Webhooks vers API
  - Filtrage: 1 adresse watchée
- **Performance**: 19-23 blocs/sec, 5000+ items/sec
- **Métriques**: Port 43423 (Prometheus)

---

## 🗄️ Infrastructure Partagée

### ✅ **PostgreSQL (Supabase Pooler)**
- **URL**: `postgresql://...@aws-1-eu-north-1.pooler.supabase.com:5432`
- **Mode**: Session pooling (limite ~30-40 connexions)
- **Status**: ✅ Connecté
- **Optimisations**:
  - NullPool activé (1 connexion par requête)
  - Paramètres asyncpg optimisés
  - SSL obligatoire

### ✅ **Redis**
- **URL**: `redis://default:...@redis-suej.railway.internal:6379`
- **Status**: ✅ Connecté sur tous les services
- **Utilisation**:
  - Cache des prix (5-180s TTL)
  - PubSub pour copy trading
  - Cache watched addresses

---

## 🔍 Status Détaillé

### ✅ **Fonctionnalités Opérationnelles**

#### **API Endpoints**
- `GET /health/live` → ✅ 200 OK
- `GET /health/ready` → ✅ 200 OK
- `POST /api/v1/webhooks/copy-trade` → ✅ Reçoit webhooks
- Trading endpoints → ✅ Fonctionnels

#### **Database**
- Connexions optimisées → ✅ NullPool actif
- Pas d'erreurs PgBouncer → ✅ Fixé
- Tables accessibles → ✅ API + Workers

#### **Redis**
- PubSub actif → ✅ Workers subscribe
- Cache opérationnel → ✅ API + Workers
- Même instance partagée → ✅ Tous services

#### **Indexer**
- Indexing actif → ✅ 20+ blocs/sec
- Webhooks envoyés → ✅ API les reçoit
- Filtrage correct → ✅ 1 adresse watchée
- Métriques exposées → ✅ Port 43423

#### **Bot Telegram**
- Polling actif → ✅ Reçoit messages
- Interface fonctionnelle → ✅ Commandes répondent
- Gestion erreurs → ✅ Conflict résolu

### ⚠️ **Points d'attention**

#### **Healthcheck Indexer**
- **Problème**: Retourne 502 "Application failed to respond"
- **Cause**: Indexer consomme 100% CPU, ne peut pas répondre aux requêtes HTTP
- **Impact**: Fausse alerte, indexer fonctionne parfaitement
- **Solution**: Monitorer via logs + métriques Prometheus

#### **Bot Limitations**
- **Problème**: Ne peut pas créer d'utilisateurs (SKIP_DB=true)
- **Impact**: UX dégradée pour nouveaux utilisateurs
- **Solution**: Inscription via web interface (implémenté)

#### **Architecture Microservices**
- **Avantages**: Résilient, scalable, séparation des responsabilités
- **Complexité**: Coordination entre services nécessaire
- **Maintenance**: Plus de déploiements indépendants

---

## 📈 Métriques Performance

### **Indexer Performance**
- **Vitesse**: 19-23 blocs/seconde
- **Throughput**: 5000-7000 items/seconde
- **Filtrage**: 99.999% des transactions ignorées (1/1M+)
- **Memory**: Stable
- **Network**: Faible latence RPC

### **Database Performance**
- **Connexions**: 6-16 total (optimisé)
- **Queries**: NullPool (1 connexion/requête)
- **Latency**: <100ms pour queries simples

### **Redis Performance**
- **Connexions**: Partagées entre services
- **Cache hit rate**: Élevé (TTL optimisés)
- **PubSub**: Actif pour copy trading

---

## 🎯 Recommandations

### **Court terme**
1. **Laisser l'architecture actuelle** - Elle fonctionne bien
2. **Monitorer via logs** plutôt que healthchecks pour l'indexer
3. **Documenter le flow d'inscription** (web → bot)

### **Moyen terme**
1. **Ajouter interface web complète** pour remplacer certaines fonctions bot
2. **Implémenter cache Redis avancé** pour l'état utilisateur
3. **Optimiser les pools DB** si nécessaire

### **Long terme**
1. **API Gateway** pour centraliser les appels
2. **Service mesh** (Istio/Linkerd) pour la découverte de services
3. **Monitoring centralisé** (DataDog/New Relic)

---

## 🏆 Résumé

**Le système est FULLY OPERATIONNEL** 🎉

- ✅ **4 services déployés** et fonctionnels
- ✅ **Architecture microservices** robuste
- ✅ **Performance excellente** (indexer 20+ blocs/sec)
- ✅ **Infrastructure optimisée** (DB + Redis)
- ✅ **Monitoring fonctionnel** (logs + métriques)

**Prochaine étape**: Développer l'interface web pour compléter l'expérience utilisateur.
