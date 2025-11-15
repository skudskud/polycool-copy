# Fix pour le reloader automatique qui cause le shutdown

## Problème identifié

Le bot démarre correctement mais shutdown immédiatement avec:
```
WARNING: WatchFiles detected changes in 'core/services/bridge/bridge_service.py'. Reloading...
```

## Cause

FastAPI/Uvicorn avec `--reload` détecte les changements de fichiers et relance automatiquement.
Le fichier `bridge_service.py` a été récemment modifié, déclenchant un restart.

## Solutions

### Option 1: Désactiver le reloader pour les tests
```bash
# Dans main.py, changer:
# reload=settings.is_development,
reload=False,
```

### Option 2: Lancer sans reloader
```bash
python3 -c "from telegram_bot.main import app; import uvicorn; uvicorn.run(app, host='0.0.0.0', port=8000, reload=False)"
```

### Option 3: Utiliser une copie du fichier pour éviter les changements
```bash
cp telegram_bot/main.py telegram_bot/main_test.py
python3 telegram_bot/main_test.py
```
