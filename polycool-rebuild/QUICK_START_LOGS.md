# 🚀 Commandes pour lancer le bot et voir les logs

## 📋 Méthodes pour lancer le bot

### Option 1: Script rapide (recommandé)
```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
./test_bot.sh
```

### Option 2: Directement
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

### Méthode 1: Logs en temps réel (recommandé)
Les logs s'affichent automatiquement dans le terminal où le bot tourne.
Rien d'autre à faire - regardez simplement le terminal !

### Méthode 2: Logs vers fichier + affichage séparé
Dans un terminal:
```bash
python3 telegram_bot/main.py > bot.log 2>&1
```

Dans un autre terminal:
```bash
tail -f bot.log
```

### Méthode 3: Script d'affichage des logs
```bash
./view_logs.sh bot.log
```

## 🔍 Ce qu'il faut surveiller dans les logs

### ✅ Succès attendus:
- `🚀 Starting Polycool Telegram Bot` - Démarrage OK
- `✅ Telegram bot started in background` - Bot initialisé
- `✅ Telegram bot polling started` - Polling actif
- `🤖 BOT @Polypolis_Bot IS ACTIVE AND RECEIVING MESSAGES!` - Bot prêt

### ❌ Erreurs à surveiller:
- `❌` - Toute ligne avec ce symbole
- `ERROR` - Erreurs Python
- `Exception` - Exceptions non gérées

## 🛑 Arrêter le bot

Appuyez sur `Ctrl+C` dans le terminal où le bot tourne.

## 🧪 Test rapide

1. Lancez le bot avec `./test_bot.sh`
2. Ouvrez Telegram et cherchez @Polypolis_Bot
3. Envoyez `/start` - regardez les logs pour voir la réponse
4. Envoyez `/markets` - vérifiez que ça marche
5. Cliquez sur un marché - vérifiez les détails
