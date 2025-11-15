# 🧪 Guide de Test Local Multi-Services

**Guide complet pour tester Polycool en local avec architecture multi-services (comme en production)**

---

## 📋 Vue d'Ensemble

Cet environnement reproduit l'architecture Railway en local avec 3 services séparés:
- **API** (port 8000) - Gère la base de données et les endpoints HTTP
- **Bot** (Telegram) - Interface utilisateur, communique avec l'API
- **Workers** (Background) - Streamer, TP/SL, Copy-trading

### Infrastructure

- **Database**: Supabase Production (via pooler)
- **Redis**: Local (Docker)
- **Indexer**: Production Railway (pas besoin de le démarrer localement)

---

## 🚀 Démarrage Rapide

### 1. Prérequis

```bash
# Vérifier que Redis peut être démarré
docker compose -f docker-compose.local.yml up -d redis

# Vérifier que .env.local existe avec les variables requises
# (TELEGRAM_BOT_TOKEN, ENCRYPTION_KEY, etc.)
```

### 2. Démarrer Tous les Services

```bash
# Option A: Tous les services en une commande (recommandé)
./scripts/dev/start-all.sh

# Option B: Services individuels (pour debugging)
./scripts/dev/start-api.sh      # Terminal 1
./scripts/dev/start-bot.sh      # Terminal 2
./scripts/dev/start-workers.sh  # Terminal 3
```

### 3. Vérifier que Tout Fonctionne

```bash
# Tester tous les services
./scripts/dev/test-services.sh

# Voir les logs
./scripts/dev/view-logs.sh all
./scripts/dev/view-logs.sh api --follow
```

### 4. Arrêter Tous les Services

```bash
./scripts/dev/stop-all.sh
```

---

## 📊 Architecture Locale

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  polycool-api   │    │  polycool-bot   │    │polycool-workers │
│  (port 8000)    │    │  (Telegram)     │    │  (Background)   │
│  SKIP_DB=false  │    │  SKIP_DB=true   │    │  SKIP_DB=false  │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                       │
         │                      │                       │
         └──────────────────────┼───────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Supabase (Production) │
                    │  Project: xxzdlbw...   │
                    │  Pooler: aws-1-eu...   │
                    └───────────┬────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Redis Local (Docker)  │
                    │  (port 6379)           │
                    └───────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Indexer (Production) │
                    │  Railway (en prod)    │
                    │  Webhooks → API       │
                    └───────────────────────┘
```

---

## 🔧 Configuration

### Variables d'Environnement Requises

Créer un fichier `.env.local` avec:

```bash
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Encryption (32 caractères exactement)
ENCRYPTION_KEY=your_32_character_encryption_key

# Database (Supabase Production - optionnel, défaut dans scripts)
DATABASE_URL=postgresql://postgres.xxzdlbwfyetaxcmodiec:ClDSK0N5IedorZes@aws-1-eu-north-1.pooler.supabase.com:5432/postgres

# Redis (local - optionnel, défaut localhost:6379)
REDIS_URL=redis://localhost:6379

# Polymarket CLOB API (pour les trades)
CLOB_API_KEY=your_clob_api_key
CLOB_API_SECRET=your_clob_api_secret
CLOB_API_PASSPHRASE=your_clob_passphrase

# Web3 Providers
POLYGON_RPC_URL=https://polygon-rpc.com
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
```

### Configuration par Service

Les scripts définissent automatiquement les variables selon le service:

**API** (`start-api.sh`):
- `SKIP_DB=false` → Accès DB complet
- `STREAMER_ENABLED=false` → Pas de workers
- `PORT=8000`

**Bot** (`start-bot.sh`):
- `SKIP_DB=true` → Pas d'accès DB direct
- `API_URL=http://localhost:8000` → Communique avec API locale
- `STREAMER_ENABLED=false` → Pas de workers

**Workers** (`start-workers.sh`):
- `SKIP_DB=false` → Accès DB complet
- `STREAMER_ENABLED=true` → Active le streamer
- `TPSL_MONITORING_ENABLED=true` → Active le monitoring TP/SL

---

## 🧪 Tests Possibles

### 1. Test Bot → API

```bash
# 1. Démarrer API
./scripts/dev/start-api.sh

# 2. Vérifier que l'API répond
curl http://localhost:8000/health/live

# 3. Démarrer Bot
./scripts/dev/start-bot.sh

# 4. Dans Telegram, envoyer /start
# Le bot devrait créer un utilisateur via l'API
```

**Vérification:**
- Logs API: `tail -f logs/api.log` → Devrait voir `POST /api/v1/users`
- Logs Bot: `tail -f logs/bot.log` → Devrait voir `✅ API service is healthy`

### 2. Test Trades (Mainnet)

```bash
# ⚠️ ATTENTION: Utilise le mainnet avec de vrais fonds!

# 1. S'assurer que tous les services sont démarrés
./scripts/dev/test-services.sh

# 2. Dans Telegram:
#    - /start → Créer compte
#    - /wallet → Voir wallet
#    - /markets → Parcourir marchés
#    - Acheter un marché → Vérifier que le trade passe

# 3. Vérifier dans les logs:
tail -f logs/bot.log | grep -i trade
tail -f logs/api.log | grep -i trade
```

**Vérification:**
- Trade créé en DB (via API)
- Position visible dans `/positions`
- TP/SL monitor détecte la position (workers)

### 3. Test Workers

```bash
# 1. Démarrer Workers
./scripts/dev/start-workers.sh

# 2. Vérifier les logs:
tail -f logs/workers.log

# Devrait voir:
# - ✅ Streamer service launched
# - ✅ TP/SL monitor launched
# - ✅ Copy trading listener started
```

### 4. Test Intégration Complet

```bash
# 1. Démarrer tous les services
./scripts/dev/start-all.sh

# 2. Tester le flow complet:
#    a) Créer utilisateur (/start)
#    b) Voir wallet (/wallet)
#    c) Parcourir marchés (/markets)
#    d) Acheter un marché
#    e) Voir position (/positions)
#    f) Configurer TP/SL
#    g) Vérifier que TP/SL monitor fonctionne

# 3. Vérifier les interactions:
./scripts/dev/test-services.sh
```

---

## 🔍 Debugging

### Voir les Logs

```bash
# Tous les services (dernières 50 lignes)
./scripts/dev/view-logs.sh all

# Un service spécifique (dernières 100 lignes)
./scripts/dev/view-logs.sh api
./scripts/dev/view-logs.sh bot
./scripts/dev/view-logs.sh workers

# Suivre les logs en temps réel
./scripts/dev/view-logs.sh api --follow
```

### Vérifier l'État des Services

```bash
# Test automatique de tous les services
./scripts/dev/test-services.sh

# Vérifier manuellement
curl http://localhost:8000/health/live
redis-cli ping
ps aux | grep "python.*api_only.py"
ps aux | grep "python.*bot_only.py"
ps aux | grep "python.*workers.py"
```

### Problèmes Courants

#### API ne démarre pas

```bash
# Vérifier que le port 8000 est libre
lsof -i :8000

# Vérifier les logs
tail -f logs/api.log

# Vérifier la connexion DB
# (Les scripts utilisent Supabase production par défaut)
```

#### Bot ne peut pas se connecter à l'API

```bash
# Vérifier que l'API est démarrée
curl http://localhost:8000/health/live

# Vérifier API_URL dans les logs du bot
tail -f logs/bot.log | grep API

# Le bot devrait voir: "✅ API service is healthy"
```

#### Workers ne démarrent pas

```bash
# Vérifier les logs
tail -f logs/workers.log

# Vérifier que Redis est démarré
redis-cli ping

# Vérifier la connexion DB
# (Les workers ont besoin d'accès DB)
```

---

## 📝 Commandes Utiles

### Démarrage

```bash
# Démarrer tous les services
./scripts/dev/start-all.sh

# Démarrer un service spécifique
./scripts/dev/start-api.sh
./scripts/dev/start-bot.sh
./scripts/dev/start-workers.sh
```

### Arrêt

```bash
# Arrêter tous les services
./scripts/dev/stop-all.sh
```

### Monitoring

```bash
# Tester tous les services
./scripts/dev/test-services.sh

# Voir les logs
./scripts/dev/view-logs.sh [api|bot|workers|all] [--follow]
```

### Redis

```bash
# Démarrer Redis
docker compose -f docker-compose.local.yml up -d redis

# Arrêter Redis
docker compose -f docker-compose.local.yml down redis

# Accéder à Redis CLI
redis-cli

# Voir Redis Commander (GUI)
# http://localhost:8081 (si démarré avec profile tools)
```

---

## 🎯 Workflow de Développement

### 1. Développement d'une Feature

```bash
# 1. Démarrer tous les services
./scripts/dev/start-all.sh

# 2. Modifier le code

# 3. Redémarrer seulement le service modifié
#    (Arrêter avec Ctrl+C, puis relancer le script)

# 4. Tester dans Telegram

# 5. Vérifier les logs
./scripts/dev/view-logs.sh [service] --follow
```

### 2. Test d'un Handler Spécifique

```bash
# 1. Démarrer API + Bot
./scripts/dev/start-api.sh    # Terminal 1
./scripts/dev/start-bot.sh    # Terminal 2

# 2. Tester le handler dans Telegram

# 3. Vérifier les logs en temps réel
tail -f logs/api.log
tail -f logs/bot.log
```

### 3. Test d'un Trade

```bash
# ⚠️ ATTENTION: Utilise le mainnet!

# 1. S'assurer que tous les services sont démarrés
./scripts/dev/test-services.sh

# 2. Vérifier que le wallet a des fonds
#    (via /wallet dans Telegram)

# 3. Faire un trade via /markets

# 4. Vérifier:
#    - Trade créé en DB (via API logs)
#    - Position visible (/positions)
#    - TP/SL monitor actif (workers logs)
```

---

## 🔐 Sécurité

### ⚠️ Important

- **Database**: Utilise Supabase **production** - Fait attention aux données!
- **Trades**: Utilise le **mainnet** - Utilise de vrais fonds!
- **Secrets**: Ne commite jamais `.env.local` (déjà dans .gitignore)

### Bonnes Pratiques

1. **Tester avec de petits montants** sur le mainnet
2. **Vérifier les logs** avant de faire des trades importants
3. **Utiliser un bot de test** séparé si possible
4. **Ne pas partager** `.env.local` avec les credentials

---

## 📚 Ressources

### Documentation

- `ARCHITECTURE_AUDIT_REPORT.md` - Architecture détaillée
- `PRODUCTION_DEPLOYMENT_GUIDE.md` - Configuration production
- `RAILWAY_DEPLOYMENT_STATUS.md` - État des services Railway

### Scripts

- `scripts/dev/start-api.sh` - Démarrer API
- `scripts/dev/start-bot.sh` - Démarrer Bot
- `scripts/dev/start-workers.sh` - Démarrer Workers
- `scripts/dev/start-all.sh` - Démarrer tout
- `scripts/dev/stop-all.sh` - Arrêter tout
- `scripts/dev/test-services.sh` - Tester les services
- `scripts/dev/view-logs.sh` - Voir les logs

### Endpoints API

- `http://localhost:8000/` - Root
- `http://localhost:8000/health/live` - Health check
- `http://localhost:8000/health/ready` - Readiness check
- `http://localhost:8000/docs` - Documentation Swagger

---

## ✅ Checklist

Avant de commencer les tests:

- [ ] `.env.local` configuré avec `TELEGRAM_BOT_TOKEN` et `ENCRYPTION_KEY`
- [ ] Redis démarré (`docker compose -f docker-compose.local.yml up -d redis`)
- [ ] Connexion Supabase fonctionne (testée via scripts)
- [ ] Tous les services peuvent démarrer sans erreur
- [ ] Health checks passent (`./scripts/dev/test-services.sh`)

---

**🎉 Prêt à tester!**

Si tu rencontres des problèmes, vérifie les logs avec `./scripts/dev/view-logs.sh` et consulte la section Debugging ci-dessus.
