# 🧪 Guide de Test Local du Bot Telegram

## 🚀 Lancer le bot

### Option 1: Script de démarrage (recommandé)
```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
./start_local.sh
```

### Option 2: Directement avec Python
```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
python3 telegram_bot/main.py
```

### Option 3: Avec Makefile
```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
make start
```

## 📊 Voir les logs

Les logs s'affichent directement dans le terminal où le bot tourne.

### Voir les logs en temps réel
Les logs apparaissent automatiquement dans le terminal où le bot est lancé. Pas besoin de commande séparée.

### Filtrer les logs par type
Si tu veux filtrer les logs dans un autre terminal:

```bash
# Voir seulement les logs du bot Telegram
# (dans un autre terminal, si tu rediriges les logs vers un fichier)

# Ou utiliser grep pour filtrer
# (si tu rediriges stdout vers un fichier)
tail -f bot.log | grep "telegram_bot"
```

### Logs importants à surveiller
- `🚀 Starting Polycool Telegram Bot` - Démarrage réussi
- `✅ Telegram bot started in background` - Bot initialisé
- `✅ Telegram bot polling started` - Polling actif
- `❌` - Erreurs à investiguer

## 🧪 Tester dans Telegram

1. **Ouvre Telegram** et cherche ton bot (utilise le token dans `.env.local`)

2. **Envoie `/start`** - Devrait répondre avec le menu d'onboarding

3. **Teste les commandes principales:**
   ```
   /start       - Menu principal / Onboarding
   /wallet      - Gestion du wallet
   /markets     - Découvrir les marchés
   /positions   - Voir tes positions
   /smart_trading - Smart trading
   /copy_trading - Copy trading
   /referral    - Système de referral
   ```

4. **Vérifie les logs** dans le terminal pour voir les interactions

## 🔍 Vérifier que le bot fonctionne

### Health Check (dans un autre terminal)
```bash
curl http://localhost:8000/health
```

### Vérifier que le bot répond
```bash
curl http://localhost:8000/
```

### Voir la documentation API
Ouvre dans ton navigateur: http://localhost:8000/docs

## 🐛 Debug

### Voir les erreurs seulement
Les erreurs apparaissent dans les logs avec `❌` ou `ERROR`.

### Vérifier la connexion DB
Les logs montrent les requêtes SQL si `DEBUG=true` dans `.env.local`

### Vérifier le token Telegram
Si tu vois des erreurs d'authentification, vérifie `TELEGRAM_BOT_TOKEN` dans `.env.local`

## 🛑 Arrêter le bot

Appuie sur `Ctrl+C` dans le terminal où le bot tourne.

## 📝 Exemple de logs attendus

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [XXXXX] using WatchFiles
INFO:     Started server process [XXXXX]
INFO:     Waiting for application startup.
2025-11-07 XX:XX:XX,XXX - telegram_bot.main - INFO - 🚀 Starting Polycool Telegram Bot
2025-11-07 XX:XX:XX,XXX - telegram_bot.main - INFO - ✅ Telegram bot started in background
2025-11-07 XX:XX:XX,XXX - telegram_bot.bot.application - INFO - ✅ Telegram bot initialized successfully
2025-11-07 XX:XX:XX,XXX - telegram_bot.bot.application - INFO - 🚀 Starting Telegram bot...
2025-11-07 XX:XX:XX,XXX - telegram_bot.bot.application - INFO - ✅ Telegram bot polling started
INFO:     Application startup complete.
```

## ⚙️ Configuration rapide

Assure-toi que `.env.local` contient:
```bash
TELEGRAM_BOT_TOKEN=ton_token_ici
DATABASE_URL=ton_url_supabase
STREAMER_ENABLED=false  # ✅ Désactivé pour les tests
INDEXER_ENABLED=false   # ✅ Désactivé pour les tests
```
