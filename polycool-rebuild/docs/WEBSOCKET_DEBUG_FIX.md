# 🔧 WebSocket Debug & Fix

## 🐛 Problème Identifié

Le WebSocket se connecte bien et envoie les subscriptions, mais **aucun marché n'a `source = 'ws'`** dans la base de données. Tous les marchés ont `source = 'poll'`, ce qui signifie que les messages WebSocket ne sont pas traités.

### Symptômes
- ✅ WebSocket connecté (`✅ WebSocket connected`)
- ✅ Subscriptions envoyées (`📡 Subscribed to 8 token IDs`)
- ❌ Aucun marché avec `source = 'ws'` dans la DB
- ❌ Les prix ne sont pas mis à jour via WebSocket

## 🔍 Causes Identifiées

1. **Messages WebSocket non loggés** - Impossible de voir ce qui est reçu
2. **Format des messages non reconnu** - Le handler ne reconnaît pas le format Polymarket
3. **Token ID → Market ID** - Conversion manquante quand seul `token_id` est présent
4. **Extraction des prix incomplète** - Ne gère pas tous les formats Polymarket

## ✅ Corrections Appliquées

### 1. Ajout de Logs de Debug

**Fichier:** `data_ingestion/streamer/websocket_client/websocket_client.py`

```python
# Log tous les messages reçus (premiers 200 caractères)
logger.debug(f"📨 Received WebSocket message: {json.dumps(data)[:200]}")
```

### 2. Amélioration du Handler de Messages

**Fichier:** `data_ingestion/streamer/websocket_client/websocket_client.py`

- Ajout de la gestion explicite du type `"market"` (format Polymarket standard)
- Routing automatique vers le handler `price_update`

### 3. Conversion Token ID → Market ID

**Fichier:** `data_ingestion/streamer/market_updater/market_updater.py`

- Ajout de la méthode `_get_market_id_from_token_id()` qui cherche dans la DB
- Utilisation automatique si seul `token_id` est présent dans le message

### 4. Extraction des Prix Améliorée

**Fichier:** `data_ingestion/streamer/market_updater/market_updater.py`

- Support du format `assets` array avec prix
- Support du format `price` ou `last_price` simple
- Support du format `best_bid`/`best_ask` pour calculer mid price
- Logs détaillés pour debug

### 5. Logs de Debug dans MarketUpdater

**Fichier:** `data_ingestion/streamer/market_updater/market_updater.py`

- Log de chaque message reçu avec ses clés
- Log de l'extraction des prix
- Log de la conversion token_id → market_id

## 🧪 Comment Vérifier que ça Fonctionne

### 1. Vérifier les Logs Workers

```bash
railway logs --service workers | grep -E "📨|📊|✅|⚠️"
```

Vous devriez voir:
```
📨 Received WebSocket message: {"type":"market","asset_id":"...","price":0.5}
📊 Processing price update: market - ['type', 'asset_id', 'price']
🔍 Found market_id 570362 for token_id ...
✅ Extracted prices [0.5] for market 570362
✅ Updated prices for market 570362
```

### 2. Vérifier dans Supabase

```sql
-- Vérifier que les marchés ont maintenant source = 'ws'
SELECT
    id,
    source,
    outcome_prices,
    updated_at
FROM markets
WHERE id IN (
    SELECT DISTINCT market_id
    FROM positions
    WHERE status = 'active'
)
ORDER BY updated_at DESC;

-- Devrait montrer source = 'ws' pour les marchés avec positions actives
```

### 3. Vérifier les Positions Mises à Jour

```sql
-- Vérifier que les positions sont mises à jour
SELECT
    id,
    market_id,
    current_price,
    pnl_amount,
    updated_at
FROM positions
WHERE status = 'active'
ORDER BY updated_at DESC;

-- Les updated_at devraient être récents (< 1 minute)
```

### 4. Test Manuel

1. **Attendre quelques minutes** après le déploiement
2. **Vérifier les logs** pour voir les messages WebSocket reçus
3. **Vérifier la DB** pour voir si `source = 'ws'` apparaît
4. **Si toujours 'poll'**, vérifier les logs pour voir le format exact des messages

## 🔍 Diagnostic si ça ne Fonctionne Toujours Pas

### Étape 1: Vérifier que des Messages sont Reçus

```bash
railway logs --service workers | grep "📨 Received WebSocket message"
```

**Si aucun message:**
- Le WebSocket ne reçoit pas de données
- Vérifier la connexion WebSocket
- Vérifier que les subscriptions sont bien actives

### Étape 2: Vérifier le Format des Messages

Si des messages sont reçus, regarder leur format dans les logs:
```
📨 Received WebSocket message: {"type":"market","asset_id":"...","price":0.5}
```

**Si le format est différent:**
- Adapter `_extract_prices()` pour gérer ce format
- Adapter `handle_price_update()` pour extraire les bonnes clés

### Étape 3: Vérifier la Conversion Token ID → Market ID

```bash
railway logs --service workers | grep "🔍 Found market_id\|⚠️ Could not find market_id"
```

**Si "Could not find market_id":**
- Vérifier que `clob_token_ids` est bien rempli dans la table `markets`
- Vérifier que le `token_id` dans le message correspond bien

### Étape 4: Vérifier l'Extraction des Prix

```bash
railway logs --service workers | grep "✅ Extracted prices\|⚠️ No prices found"
```

**Si "No prices found":**
- Le format des prix dans le message n'est pas reconnu
- Adapter `_extract_prices()` pour gérer ce format spécifique

## 📋 Checklist de Vérification

- [ ] Logs montrent des messages WebSocket reçus (`📨 Received WebSocket message`)
- [ ] Logs montrent le traitement des price updates (`📊 Processing price update`)
- [ ] Logs montrent l'extraction des prix (`✅ Extracted prices`)
- [ ] DB montre `source = 'ws'` pour les marchés avec positions actives
- [ ] DB montre `positions.updated_at` récent (< 1 minute)
- [ ] DB montre `positions.current_price` et `pnl_amount` mis à jour

## 🚀 Prochaines Étapes

1. **Déployer les corrections** sur Railway
2. **Monitorer les logs** pendant 5-10 minutes
3. **Vérifier la DB** pour confirmer que `source = 'ws'` apparaît
4. **Si nécessaire**, adapter le code selon le format exact des messages Polymarket

## 📝 Notes

- Les logs de debug sont en `logger.debug()` - activer le niveau DEBUG si nécessaire
- Les logs importants sont en `logger.info()` - visibles par défaut
- Les erreurs sont en `logger.error()` - toujours visibles

Si après ces corrections le problème persiste, les logs devraient maintenant montrer exactement ce qui se passe et permettre d'identifier le problème précis.
