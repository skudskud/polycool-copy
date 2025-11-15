# 🧪 Scripts de Test Local Multi-Services

Guide rapide pour utiliser les scripts de test local.

## 🚀 Démarrage Rapide

```bash
# 1. Démarrer Redis (si pas déjà démarré)
docker compose -f docker-compose.local.yml up -d redis

# 2. Démarrer tous les services
./scripts/dev/start-all.sh

# 3. Tester
./scripts/dev/test-services.sh
```

## 📋 Scripts Disponibles

### Démarrage

- `start-api.sh` - Démarrer l'API (port 8000)
- `start-bot.sh` - Démarrer le bot Telegram
- `start-workers.sh` - Démarrer les workers (streamer, TP/SL, copy-trading)
- `start-all.sh` - Démarrer tous les services (tmux ou background)

### Utilitaires

- `test-services.sh` - Tester tous les services
- `view-logs.sh` - Voir les logs (api|bot|workers|all)
- `stop-all.sh` - Arrêter tous les services

## 🔧 Configuration

Les scripts utilisent `.env.local` pour les variables d'environnement.

Variables requises dans `.env.local`:
- `TELEGRAM_BOT_TOKEN` ou `BOT_TOKEN`
- `ENCRYPTION_KEY` (32 caractères)

Variables optionnelles (défauts dans les scripts):
- `DATABASE_URL` (défaut: Supabase production pooler)
- `REDIS_URL` (défaut: redis://localhost:6379)
- `API_URL` (défaut: http://localhost:8000)

## 📊 Architecture

```
API (port 8000) ← Bot (Telegram) ← Workers (Background)
     ↓                ↓                    ↓
  Supabase DB    Redis Local      Indexer (Production)
```

## 🧪 Exemples d'Utilisation

### Démarrer un service spécifique

```bash
# Terminal 1: API
./scripts/dev/start-api.sh

# Terminal 2: Bot
./scripts/dev/start-bot.sh

# Terminal 3: Workers
./scripts/dev/start-workers.sh
```

### Voir les logs

```bash
# Tous les services
./scripts/dev/view-logs.sh all

# Un service spécifique
./scripts/dev/view-logs.sh api --follow
./scripts/dev/view-logs.sh bot
./scripts/dev/view-logs.sh workers
```

### Tester les services

```bash
# Test automatique
./scripts/dev/test-services.sh
```

## 🛑 Arrêt

```bash
# Arrêter tous les services
./scripts/dev/stop-all.sh
```

## 📚 Documentation Complète

Voir `docs/LOCAL_TESTING.md` pour la documentation complète.
