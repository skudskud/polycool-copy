# 🔧 Dépannage - Bot ne répond pas

## Problème
Le bot ne répond pas après avoir lancé `start-all.sh`.

## Étapes de diagnostic

### 1. Vérifier que le bot est démarré

```bash
# Vérifier si le processus bot est en cours d'exécution
ps aux | grep -E "python.*bot_only|bot_only.py" | grep -v grep

# Si aucun processus n'est trouvé, le bot n'est pas démarré
```

### 2. Vérifier les logs du bot

```bash
# Voir les dernières erreurs
tail -n 50 logs/bot.log | grep -E "ERROR|WARNING|Exception|Failed"

# Voir les dernières lignes du log
tail -n 20 logs/bot.log
```

### 3. Vérifier que l'API est disponible

Le bot nécessite l'API pour fonctionner (SKIP_DB=true). Vérifie que l'API répond :

```bash
curl http://localhost:8000/health/live
```

Si l'API ne répond pas, démarre-la d'abord :
```bash
./scripts/dev/start-api.sh
```

### 4. Vérifier le token Telegram

Le bot token doit être configuré dans `.env.local` :

```bash
# Vérifier que le token est présent
grep -E "BOT_TOKEN|TELEGRAM_BOT_TOKEN" .env.local

# Tester le token (remplace TOKEN par ton token)
curl "https://api.telegram.org/bot<TOKEN>/getMe"
```

### 5. Vérifier Redis

Le bot utilise Redis pour le cache :

```bash
# Vérifier que Redis est démarré
redis-cli ping

# Si Redis n'est pas démarré
docker-compose -f docker-compose.local.yml up -d redis
```

### 6. Redémarrer le bot

Si le bot ne démarre pas correctement :

```bash
# Arrêter tous les services
./scripts/dev/stop-all.sh

# Redémarrer
./scripts/dev/start-all.sh
```

### 7. Démarrer le bot manuellement pour voir les erreurs

```bash
# Démarrer le bot directement pour voir les erreurs
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
source .venv/bin/activate  # ou ton environnement virtuel
python bot_only.py
```

## Causes communes

1. **API non disponible** : Le bot ne peut pas fonctionner sans l'API (SKIP_DB=true)
2. **Token Telegram invalide** : Vérifie que le token dans `.env.local` est correct
3. **Redis non démarré** : Le bot utilise Redis pour le cache
4. **Erreur au démarrage** : Vérifie les logs pour des erreurs Python

## Solution rapide

```bash
# 1. Arrêter tous les services
./scripts/dev/stop-all.sh

# 2. Vérifier que Redis est démarré
docker-compose -f docker-compose.local.yml up -d redis

# 3. Démarrer l'API d'abord
./scripts/dev/start-api.sh

# 4. Attendre quelques secondes que l'API démarre

# 5. Démarrer le bot
./scripts/dev/start-bot.sh

# 6. Vérifier les logs
tail -f logs/bot.log
```

Si le bot démarre mais ne répond toujours pas, vérifie :
- Que tu utilises le bon bot Telegram (celui correspondant au token)
- Que le bot n'est pas bloqué ou désactivé dans Telegram
- Que tu envoies les messages au bon bot (vérifie le username du bot dans les logs)
