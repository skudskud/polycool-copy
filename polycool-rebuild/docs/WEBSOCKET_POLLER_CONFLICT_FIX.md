# 🔧 Fix: Conflit Poller vs WebSocket (source = 'ws')

## 🐛 Problème Identifié

Les messages WebSocket arrivent maintenant (`📊 Processing price update`), mais **toujours pas de `source = 'ws'`** dans la DB. Le problème vient du **poller qui écrase les updates WebSocket**.

### Symptômes
- ✅ Messages WebSocket reçus (`📊 Processing price update: unknown - ['market', 'price_changes', 'timestamp', 'event_type']`)
- ✅ Handler appelé
- ❌ Aucun marché avec `source = 'ws'` dans la DB
- ❌ Le poller écrase les updates WebSocket toutes les 30 secondes

### Cause Racine

Le poller utilise `ON CONFLICT DO UPDATE` et **écrase toujours** `source = 'poll'` même si le WebSocket vient de mettre `source = 'ws'`.

**Code problématique:**
```sql
ON CONFLICT (id) DO UPDATE SET
    outcome_prices = EXCLUDED.outcome_prices,  -- ❌ Écrase les prix WebSocket
    source = 'poll'  -- ❌ Écrase source = 'ws'
```

## ✅ Corrections Appliquées

### 1. Protection WebSocket dans le Poller

**Fichier:** `data_ingestion/poller/base_poller.py`

Le poller préserve maintenant les données WebSocket:

```sql
ON CONFLICT (id) DO UPDATE SET
    -- CRITICAL: Preserve WebSocket prices if source is 'ws' (WebSocket has priority)
    outcome_prices = CASE
        WHEN markets.source = 'ws' THEN markets.outcome_prices
        ELSE EXCLUDED.outcome_prices
    END,
    -- CRITICAL: Preserve WebSocket last_trade_price if source is 'ws'
    last_trade_price = CASE
        WHEN markets.source = 'ws' AND markets.last_trade_price IS NOT NULL
        THEN markets.last_trade_price
        ELSE EXCLUDED.last_trade_price
    END,
    -- CRITICAL: Preserve WebSocket source (ws > poll priority)
    source = CASE
        WHEN markets.source = 'ws' THEN 'ws'
        ELSE 'poll'
    END,
```

**Priorité:** `ws` > `poll` (WebSocket a toujours la priorité)

### 2. Support du Format `price_changes`

**Fichier:** `data_ingestion/streamer/market_updater/market_updater.py`

Les messages Polymarket ont le format:
```json
{
  "event_type": "...",
  "market": "570362",
  "price_changes": [
    {"asset_id": "...", "price": 0.5},
    {"asset_id": "...", "price": 0.5}
  ]
}
```

Ajout du support pour extraire les prix depuis `price_changes`:
```python
# Try Polymarket format: price_changes array
price_changes = data.get("price_changes")
if price_changes and isinstance(price_changes, list):
    prices = []
    for change in price_changes:
        if isinstance(change, dict):
            price = change.get("price") or change.get("last_price")
            if price is not None:
                prices.append(float(price))
    if prices:
        return prices
```

### 3. Extraction du Market ID depuis `market`

**Fichier:** `data_ingestion/streamer/market_updater/market_updater.py`

Le champ `market` peut être:
- Une string avec le market_id directement: `"570362"`
- Un objet: `{"id": "570362"}`

Gestion des deux formats:
```python
market_id = data.get("market_id") or data.get("market")

# Handle Polymarket format with "market" field containing market_id
if market_id and isinstance(market_id, str) and market_id.isdigit():
    # market_id is already a string ID
    pass
elif market_id and isinstance(market_id, dict):
    # market might be an object, extract ID
    market_id = market_id.get("id") or market_id.get("market_id")
```

### 4. Handler d'Événements Amélioré

**Fichier:** `data_ingestion/streamer/websocket_client/websocket_client.py`

- Support de `event_type = "price"` en plus de `"price_change"`
- Fallback vers `price_update` handler pour événements inconnus
- Logs améliorés pour debug

## 🧪 Comment Vérifier que ça Fonctionne

### 1. Vérifier les Logs

```bash
railway logs --service workers | grep -E "📊|✅|🎯"
```

Vous devriez voir:
```
🎯 Handling Polymarket event: price_change
📊 Routing price_change event to price_update handler
📊 Processing price update: unknown - event_type: price_change - keys: ['market', 'price_changes', ...]
✅ Extracted prices [0.5, 0.5] for market 570362
✅ Updated prices for market 570362
```

### 2. Vérifier dans Supabase

**Attendre 1-2 minutes après un update WebSocket** (pour éviter que le poller écrase immédiatement), puis:

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
-- Même après que le poller ait tourné (toutes les 30s)
```

### 3. Test de Protection contre le Poller

1. **Attendre un update WebSocket** (vérifier logs)
2. **Vérifier DB** → `source = 'ws'`
3. **Attendre que le poller tourne** (30s)
4. **Vérifier DB à nouveau** → `source` devrait toujours être `'ws'` (pas écrasé)

## 📊 Flux Complet Corrigé

```
1. WebSocket reçoit message
   ↓
2. Handler extrait market_id et prices depuis price_changes
   ↓
3. MarketUpdater met à jour DB avec source = 'ws'
   ↓
4. Poller tourne (30s plus tard)
   ↓
5. Poller vérifie: markets.source = 'ws'?
   ↓
6. Si OUI → Préserve source = 'ws' et outcome_prices WebSocket ✅
   Si NON → Met source = 'poll' et outcome_prices poller
```

## 🎯 Résultat Attendu

Après ces corrections:
- ✅ Les messages WebSocket sont traités correctement
- ✅ `source = 'ws'` apparaît dans la DB
- ✅ Le poller ne peut plus écraser les updates WebSocket
- ✅ Les prix WebSocket sont préservés même quand le poller tourne

## 📝 Notes Importantes

1. **Priorité WebSocket**: Le WebSocket a toujours la priorité sur le poller
2. **Poller comme Fallback**: Le poller met à jour seulement si `source != 'ws'`
3. **Format Polymarket**: Les messages peuvent avoir différents formats, le code gère maintenant plusieurs variantes
4. **Performance**: Le CASE WHEN dans SQL est très rapide, pas d'impact sur les performances

## 🚀 Prochaines Étapes

1. **Déployer les corrections** sur Railway
2. **Monitorer les logs** pendant 5-10 minutes
3. **Vérifier la DB** pour confirmer que `source = 'ws'` apparaît et reste
4. **Vérifier que le poller ne l'écrase plus** après son cycle (30s)
