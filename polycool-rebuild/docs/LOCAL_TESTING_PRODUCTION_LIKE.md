# Guide de Test Local Multi-Services (Production-Like)

Ce guide explique comment tester l'architecture multi-services en local **exactement comme en production** pour valider que tous les handlers/callbacks sont bien intégrés avec les calls API.

## Architecture Multi-Services

```
┌─────────────────────────────────────────────────────────┐
│              Architecture Multi-Services                │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────┐ │
│  │  API Service │    │  Bot Service │    │ Workers  │ │
│  │              │    │              │    │          │ │
│  │ SKIP_DB=false│    │ SKIP_DB=true │    │SKIP_DB=  │ │
│  │ Port 8000    │    │ APIClient →  │    │false     │ │
│  │              │    │   API        │    │          │ │
│  └──────┬───────┘    └──────┬───────┘    └────┬─────┘ │
│         │                    │                  │        │
│         └──────────────────┴──────────────────┘        │
│                         │                              │
│                    ┌────▼────┐                         │
│                    │  Redis  │                         │
│                    │ (Local) │                         │
│                    └────┬────┘                         │
│                         │                              │
│                    ┌────▼────┐                         │
│                    │ Supabase │                        │
│                    │   DB     │                        │
│                    │ (Prod)   │                        │
│                    └──────────┘                         │
└─────────────────────────────────────────────────────────┘
```

### Services

1. **API Service** (`api_only.py`)
   - Accès DB complet (`SKIP_DB=false`)
   - Port 8000
   - Endpoints REST pour le bot
   - Gestion des positions, markets, users

2. **Bot Service** (`bot_only.py`)
   - Pas d'accès DB (`SKIP_DB=true`)
   - Utilise `APIClient` pour toutes les opérations DB
   - Handlers Telegram intégrés avec calls API

3. **Workers Service** (`workers.py`)
   - Accès DB (`SKIP_DB=false`)
   - Data ingestion: Poller (60s), WebSocket (temps réel)
   - TP/SL Monitor
   - Copy Trading Listener
   - Watched Addresses Sync

4. **Redis Cache** (Local)
   - Cache des prix, markets, positions
   - Invalidation automatique lors des updates
   - PubSub pour copy trading events

5. **Supabase Database** (Production)
   - Base de données partagée
   - Tables: users, positions, markets, trades, etc.

## Prérequis

### 1. Configuration

Assurez-vous d'avoir les fichiers de configuration suivants :

- `.env.local` (priorité) ou `.env` (fallback)
- Variables requises :
  - `DATABASE_URL` (Supabase production)
  - `REDIS_URL` (local: `redis://localhost:6379`)
  - `TELEGRAM_BOT_TOKEN` ou `BOT_TOKEN`
  - `ENCRYPTION_KEY` (32 caractères)
  - `API_URL` (doit être `http://localhost:8000` pour local)
  - `CLOB_API_KEY`, `CLOB_API_SECRET`, `CLOB_API_PASSPHRASE`

### 2. Vérification de la Configuration

Avant de commencer, vérifiez votre configuration :

```bash
./scripts/dev/verify-config.sh
```

Ce script vérifie :
- ✅ Fichiers `.env.local` et `.env`
- ✅ Variables d'environnement requises
- ✅ Connexion Redis
- ✅ Connexion Supabase DB
- ✅ Scripts requis

### 3. Démarrage de Redis

Redis doit être démarré avant les autres services :

```bash
docker compose -f docker-compose.local.yml up -d redis
```

Vérifiez que Redis est accessible :

```bash
redis-cli ping
# Devrait retourner: PONG
```

## Démarrage des Services

### Option 1: Démarrage Automatique (Recommandé)

Démarrez tous les services en une seule commande :

```bash
./scripts/dev/start-all.sh
```

Ce script :
1. ✅ Vérifie que Redis est démarré
2. ✅ Démarre l'API Service
3. ✅ Attend que l'API soit prête (health check)
4. ✅ Démarre le Bot Service
5. ✅ Démarre le Workers Service

**Mode tmux** (si disponible) :
- Crée une session tmux avec un panneau par service
- Permet de voir les logs de chaque service séparément

**Mode background** :
- Démarre les services en arrière-plan
- Logs disponibles dans `logs/api.log`, `logs/bot.log`, `logs/workers.log`

### Option 2: Démarrage Manuel

Si vous préférez démarrer les services manuellement :

#### 1. Démarrer l'API Service

```bash
./scripts/dev/start-api.sh
```

Vérifiez que l'API est prête :

```bash
curl http://localhost:8000/health/live
# Devrait retourner: {"status": "healthy"}
```

#### 2. Démarrer le Bot Service

```bash
./scripts/dev/start-bot.sh
```

Le bot vérifie automatiquement que l'API est accessible avant de démarrer.

#### 3. Démarrer le Workers Service

```bash
./scripts/dev/start-workers.sh
```

## Vérification des Services

Vérifiez que tous les services sont démarrés et fonctionnent :

```bash
./scripts/dev/verify-services.sh
```

Ce script vérifie :
- ✅ Redis est accessible
- ✅ Database est accessible
- ✅ API Service répond aux health checks
- ✅ Bot Service est démarré
- ✅ Workers Service est démarré
- ✅ Workers individuels (poller, streamer, copy trading listener, TP/SL monitor)

## Tests d'Intégration

### 1. Test Bot-API Integration

Vérifiez que les handlers utilisent bien `APIClient` :

```bash
./scripts/dev/test-bot-api-integration.sh
```

Ce script teste :
- ✅ API endpoints sont accessibles
- ✅ Handlers utilisent `APIClient`
- ✅ Logs montrent des appels API
- ✅ Pas d'accès DB direct dans les handlers

### 2. Test Cache Redis

Vérifiez le fonctionnement du cache Redis :

```bash
./scripts/dev/test-cache-integration.sh
```

Ce script teste :
- ✅ Cache SET/GET/DELETE
- ✅ Cache hit/miss
- ✅ TTL des clés
- ✅ Invalidation par pattern
- ✅ Intégration avec les appels API

### 3. Vérification SKIP_DB

Vérifiez que tous les handlers respectent `SKIP_DB` :

```bash
./scripts/dev/verify-handlers-skip-db.sh
```

Ce script vérifie :
- ✅ Handlers utilisent `APIClient` quand `SKIP_DB=true`
- ✅ Pas d'accès DB direct sans vérification `SKIP_DB`
- ✅ Handlers protégés correctement

### 4. Test des Workers

Vérifiez que tous les workers fonctionnent :

```bash
./scripts/dev/test-workers.sh
```

Ce script teste :
- ✅ Poller démarre et fonctionne
- ✅ WebSocket Streamer démarre et fonctionne
- ✅ Copy Trading Listener démarre et fonctionne
- ✅ TP/SL Monitor démarre et fonctionne
- ✅ Watched Addresses Sync fonctionne
- ✅ Redis PubSub fonctionne

### 5. Tests End-to-End

Testez les scénarios complets :

```bash
./scripts/dev/test-e2e-scenarios.sh
```

Ce script teste :
- ✅ Copy Trading Scenario (endpoints, logs)
- ✅ Smart Trading Scenario (endpoints, logs)
- ✅ Position Management Scenario
- ✅ Market Data Scenario
- ✅ Cache Integration
- ✅ Webhook Integration
- ✅ API-Bot Communication

## Monitoring

### Monitoring des Logs

Affichez tous les logs en parallèle :

```bash
./scripts/dev/monitor-all.sh
```

**Avec tmux** :
- Crée une session avec un panneau par service
- Permet de voir les logs séparément

**Sans tmux** :
- Affiche tous les logs intercalés
- Utilise `tail -f` sur tous les fichiers de logs

### Logs Individuels

Consultez les logs de chaque service :

```bash
# API logs
tail -f logs/api.log

# Bot logs
tail -f logs/bot.log

# Workers logs
tail -f logs/workers.log
```

### Health Checks

Vérifiez la santé des services :

```bash
# API health
curl http://localhost:8000/health/live

# API root
curl http://localhost:8000/

# API docs
open http://localhost:8000/docs
```

## Scénarios de Test

### Scénario 1: Copy Trading Complet

1. User envoie `/copy_trading` au bot
2. Bot utilise `APIClient` pour récupérer les leaders
3. User sélectionne un leader
4. Bot utilise `APIClient` pour créer l'allocation
5. Indexer (simulé) envoie un webhook vers API
6. API stocke le trade dans `trades` table
7. API publie dans Redis PubSub
8. Copy trading listener traite l'événement
9. Listener crée la position via API
10. Bot peut voir la nouvelle position via `APIClient`

**Vérifications** :
- ✅ Tous les appels API fonctionnent
- ✅ Cache Redis est invalidé correctement
- ✅ Position créée dans la DB
- ✅ Bot peut récupérer la position

### Scénario 2: Smart Trading Complet

1. User envoie `/smart_trading` au bot
2. Bot utilise `APIClient` pour récupérer les recommandations
3. User sélectionne un market
4. Bot utilise `APIClient` pour créer la position
5. Position créée dans la DB
6. TP/SL monitor surveille la position
7. Prix mis à jour via WebSocket
8. TP/SL déclenché si atteint

**Vérifications** :
- ✅ Tous les appels API fonctionnent
- ✅ Position créée correctement
- ✅ Prix mis à jour en temps réel
- ✅ TP/SL fonctionne

## Arrêt des Services

Pour arrêter tous les services :

```bash
./scripts/dev/stop-all.sh
```

Ou manuellement :

```bash
# Arrêter les processus
kill $(cat logs/api.pid) 2>/dev/null || true
kill $(cat logs/bot.pid) 2>/dev/null || true
kill $(cat logs/workers.pid) 2>/dev/null || true

# Arrêter Redis (si démarré via Docker)
docker compose -f docker-compose.local.yml down
```

## Checklist de Test

Avant de considérer que les tests sont réussis :

- [ ] Tous les services démarrent sans erreur
- [ ] Bot communique avec API via `APIClient` (pas d'accès DB direct)
- [ ] Cache Redis fonctionne correctement (cache hit/miss)
- [ ] Invalidation du cache fonctionne après modifications
- [ ] Tous les handlers utilisent `APIClient` quand `SKIP_DB=true`
- [ ] Workers fonctionnent correctement (poller, websocket, copy trading)
- [ ] TP/SL monitor fonctionne
- [ ] Copy trading listener fonctionne
- [ ] Tests end-to-end passent
- [ ] Logs sont propres (pas d'erreurs critiques)

## Scripts Disponibles

| Script | Description |
|--------|-------------|
| `verify-config.sh` | Vérifie la configuration |
| `verify-services.sh` | Vérifie que les services sont démarrés |
| `test-bot-api-integration.sh` | Teste l'intégration bot-API |
| `test-cache-integration.sh` | Teste le cache Redis |
| `verify-handlers-skip-db.sh` | Vérifie que les handlers respectent SKIP_DB |
| `test-workers.sh` | Teste les workers |
| `test-e2e-scenarios.sh` | Teste les scénarios end-to-end |
| `monitor-all.sh` | Affiche tous les logs en parallèle |
| `start-all.sh` | Démarre tous les services |
| `stop-all.sh` | Arrête tous les services |

## Notes Importantes

1. **Base de données** : Utilise Supabase production (project `xxzdlbwfyetaxcmodiec`) - pas de DB locale
2. **Redis** : Local via Docker (`docker-compose.local.yml`)
3. **API_URL** : Doit être `http://localhost:8000` pour les tests locaux
4. **SKIP_DB** :
   - API : `false` (accès DB)
   - Bot : `true` (utilise APIClient)
   - Workers : `false` (accès DB)
5. **Ordre de démarrage** : Redis → API → Bot → Workers
6. **Health checks** : Vérifier que chaque service est prêt avant de démarrer le suivant

## Dépannage

Pour les problèmes courants, consultez le guide de dépannage :

```bash
cat docs/TROUBLESHOOTING.md
```

## Ressources

- [Architecture WebSocket](ARCHITECTURE_WEBSOCKET_VERIFICATION.md)
- [Audit Copy Trading & Smart Trading](AUDIT_COPY_SMART_TRADING.md)
- [Guide de Démarrage Local](../GUIDE_DEMARRAGE_LOCAL.md)
- [Quick Start Local](../QUICK_START_LOCAL.md)
