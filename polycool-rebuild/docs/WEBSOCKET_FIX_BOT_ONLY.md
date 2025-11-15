# 🔧 Fix: WebSocketManager Non Connecté dans bot_only.py

## 🐛 Problème Identifié

Le script `test-bot-simple.sh` utilise `bot_only.py` qui **ne démarre PAS le streamer**. C'est pour ça que le WebSocketManager n'est jamais connecté!

### Symptômes dans les Logs

**Lignes 968-972:**
```
⚠️ WebSocketManager not connected to streamer
   streamer=False, subscription_manager=False
   This usually means STREAMER_ENABLED=false or streamer not started in main.py
```

### Cause Racine

`bot_only.py` est conçu pour démarrer **uniquement le bot** sans les workers ni le streamer. C'est un script minimal pour les déploiements où le bot et les workers sont séparés.

**Code problématique:**
```python
# bot_only.py (avant le fix)
cache_manager = CacheManager()
bot_app = TelegramBotApplication()
await bot_app.start()
# ❌ Pas d'initialisation du streamer!
```

## ✅ Solution Appliquée

### Modification de `bot_only.py`

Ajout de l'initialisation du streamer si `STREAMER_ENABLED=true`:

```python
# Start streamer if enabled (for WebSocket support)
streamer = None
if settings.data_ingestion.streamer_enabled:
    logger.info(f"🔍 STREAMER_ENABLED=true - Initializing streamer in bot_only.py...")
    from data_ingestion.streamer.streamer import StreamerService
    from core.services.websocket_manager import websocket_manager

    streamer = StreamerService()

    # Connect WebSocketManager to streamer
    websocket_manager.set_streamer_service(streamer)

    # Verify connection
    if websocket_manager.streamer is None:
        logger.error("❌ WebSocketManager not connected to streamer after set_streamer_service!")
    else:
        logger.info("✅ WebSocketManager connected to streamer")

    # Start streamer in background
    asyncio.create_task(streamer.start())
    logger.info("✅ Streamer service started in background")
else:
    logger.info("⚠️ Streamer disabled (STREAMER_ENABLED=false) - WebSocket features unavailable")
```

### Arrêt Propre du Streamer

Ajout de l'arrêt propre du streamer lors du shutdown:

```python
finally:
    logger.info("🛑 Stopping Telegram bot service")
    await bot_app.stop()

    # Stop streamer if it was started
    if streamer:
        try:
            await streamer.stop()
            logger.info("✅ Streamer service stopped")
        except Exception as e:
            logger.warning(f"⚠️ Error stopping streamer: {e}")
```

## 🎯 Résultat Attendu

Après ce fix, les logs devraient montrer:

1. **Au démarrage:**
   ```
   🔍 STREAMER_ENABLED=true - Initializing streamer in bot_only.py...
   ✅ WebSocketManager connected to streamer
   ✅ Streamer service started in background
   🌐 Streamer Service starting...
   ```

2. **Après un trade:**
   ```
   🔌 Attempting to subscribe to WebSocket for market 525364 after trade
   📡 User 6500527972 subscribed to market 525364
   ✅ WebSocket subscription result for market 525364: True
   ```

3. **Quand les prix sont mis à jour:**
   ```
   📝 Updating market 525364 with source='ws', prices=[...]
   ✅ Updated market 525364 with source='ws' in database
   ```

## 📊 Comparaison Avant/Après

| Élément | Avant | Après |
|---------|-------|-------|
| Streamer démarré | ❌ Non | ✅ Oui |
| WebSocketManager connecté | ❌ Non | ✅ Oui |
| Souscription après trade | ❌ Échec | ✅ Succès |
| Mise à jour DB avec source='ws' | ❌ Non | ✅ Oui |

## 🔍 Vérification

Après avoir relancé le bot, vérifier:

1. **Logs de démarrage:**
   ```bash
   grep -i "streamer\|websocket" logs/bot.log | head -10
   ```

2. **Après un trade:**
   ```bash
   grep -i "subscribe\|websocket" logs/bot.log | tail -10
   ```

3. **Dans Supabase:**
   ```sql
   SELECT id, source, outcome_prices, updated_at
   FROM markets
   WHERE source = 'ws'
   ORDER BY updated_at DESC
   LIMIT 10;
   ```

## ✅ Fix Appliqué

- ✅ `bot_only.py` initialise maintenant le streamer si `STREAMER_ENABLED=true`
- ✅ WebSocketManager est connecté au streamer au démarrage
- ✅ Arrêt propre du streamer lors du shutdown
- ✅ Logs de diagnostic ajoutés
