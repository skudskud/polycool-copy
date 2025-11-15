# ⚡ Quick Start - Test Local Multi-Services

**Démarrage rapide pour tester en local avec architecture multi-services**

## 🚀 En 3 Commandes

```bash
# 1. Démarrer Redis
docker compose -f docker-compose.local.yml up -d redis

# 2. Démarrer tous les services
./scripts/dev/start-all.sh

# 3. Tester
./scripts/dev/test-services.sh
```

## 📋 Prérequis

1. **`.env.local`** configuré avec:
   - `TELEGRAM_BOT_TOKEN` ou `BOT_TOKEN`
   - `ENCRYPTION_KEY` (32 caractères)

2. **Redis** disponible (via Docker ou local)

3. **Python** et dépendances installées

## 🎯 Services

- **API**: http://localhost:8000 (gère la DB Supabase)
- **Bot**: Telegram polling (communique avec API locale)
- **Workers**: Streamer + TP/SL + Copy-trading (utilise DB Supabase)

## 📊 Architecture

```
API (8000) ← Bot (Telegram) ← Workers (Background)
    ↓              ↓                  ↓
Supabase DB    Redis Local    Indexer (Production)
```

## 🛑 Arrêt

```bash
./scripts/dev/stop-all.sh
```

## 📚 Documentation Complète

Voir `docs/LOCAL_TESTING.md` pour la documentation complète.
