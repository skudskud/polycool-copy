# Flow WebSocket Polymarket - Documentation Complète

## Format de Souscription (selon documentation officielle)

```json
{
  "assets_ids": ["token_id_1", "token_id_2"],
  "type": "market"
}
```

**Endpoint**: `wss://ws-subscriptions-clob.polymarket.com/ws/market`

## Format des Messages Reçus

### 1. Message `price_change` (format recommandé)

```json
{
  "market": "0x5f65177b394277fd294cd75650044e32ba009a95022d88a0c1d565897d72f8f1",
  "price_changes": [
    {
      "asset_id": "71321045679252212594626385532706912750332728571942532289631379312455583992563",
      "price": "0.5",
      "size": "200",
      "side": "BUY",
      "hash": "56621a121a47ed9333273e21c83b660cff37ae50",
      "best_bid": "0.5",
      "best_ask": "1"
    }
  ],
  "timestamp": "1757908892351",
  "event_type": "price_change"
}
```

**Champs importants**:
- `market`: condition_id (hex, commence par `0x`) - **DOIT être converti en market_id (numeric)**
- `price_changes`: array d'objets avec `asset_id`, `best_bid`, `best_ask`
- `event_type`: `"price_change"`

### 2. Message `book` (orderbook initial)

```json
{
  "event_type": "book",
  "asset_id": "65818619657568813474341868652308942079804919287380422192892211131408793125422",
  "market": "0xbd31dc8a20211944f6b70f31557f1001557b59905b7738480ca09bd4532f84af",
  "bids": [{"price": ".48", "size": "30"}],
  "asks": [{"price": ".52", "size": "25"}],
  "timestamp": "123456789000",
  "hash": "0x0...."
}
```

### 3. Message `last_trade_price` (trade exécuté)

```json
{
  "asset_id": "114122071509644379678018727908709560226618148003371446110114509806601493071694",
  "event_type": "last_trade_price",
  "fee_rate_bps": "0",
  "market": "0x6a67b9d828d53862160e470329ffea5246f338ecfffdf2cab45211ec578b0347",
  "price": "0.456",
  "side": "BUY",
  "size": "219.217767",
  "timestamp": "1750428146322"
}
```

## Flow Complet de Traitement

### 1. Souscription (`websocket_client.py`)

1. **Récupération des positions actives** (`subscription_manager.py`)
   - Appel API: `get_user_positions(user_id=1)`
   - Filtre: `status == "active"` ET `amount > 0`
   - Extraction des `market_id` distincts

2. **Récupération des token_ids** (`subscription_manager.py`)
   - Pour chaque `market_id`, récupération des `clob_token_ids`
   - Conversion en liste de token_ids

3. **Envoi de la souscription** (`websocket_client.py`)
   ```python
   subscription_message = {
       "assets_ids": valid_token_ids,
       "type": "market"
   }
   await websocket.send(json.dumps(subscription_message))
   ```

### 2. Réception des Messages (`websocket_client.py`)

1. **Réception brute**
   - Log: `📥 RAW WebSocket message`
   - Gestion spéciale pour `PONG` (heartbeat) - **AVANT** parsing JSON

2. **Parsing JSON**
   - Si `PONG`: ignoré (log DEBUG)
   - Sinon: `json.loads(message)`

3. **Routing des messages**
   - Si `event_type == "price_change"` → handler `price_update`
   - Si `event_type == "book"` → handler `orderbook`
   - Si `event_type == "last_trade_price"` → handler `price_update`
   - Si `type == "market"` → handler `price_update`

### 3. Résolution des Identifiants (`identifier_resolver.py`)

1. **Extraction du `market` (condition_id)**
   ```python
   market_identifier = data.get("market_id") or data.get("market")
   ```

2. **Détection du type**
   - Si commence par `0x` ou longueur > 20 → `condition_id` (hex)
   - Si numérique → `market_id` (déjà correct)

3. **Conversion condition_id → market_id**
   ```python
   if condition_id:
       market_id = await get_market_id_from_condition_id(condition_id)
   ```
   - Utilise `api_client.get_market(condition_id)` si `SKIP_DB=true`
   - Utilise `market_service.get_market_by_condition_id()` si `SKIP_DB=false`

4. **Fallback: token_id → market_id**
   ```python
   if not market_id and token_id:
       market_id = await get_market_id_from_token_id(token_id)
   ```

### 4. Extraction des Prix (`price_extractor.py`)

1. **Récupération des données du marché**
   - Si `market_id` disponible: fetch market data (outcomes, clob_token_ids)
   - Création du mapping `asset_id → outcome_index`

2. **Extraction depuis `price_changes`**
   ```python
   for change in price_changes:
       asset_id = change.get("asset_id")
       best_bid = change.get("best_bid")
       best_ask = change.get("best_ask")

       # Calcul du prix mid
       if best_bid and best_ask:
           price = (float(best_bid) + float(best_ask)) / 2.0
       else:
           price = float(change.get("price"))

       # Mapping à l'outcome
       outcome_idx = asset_to_outcome.get(asset_id)
       outcome_prices[outcome_idx] = price
   ```

3. **Gestion des prix partiels (marchés binaires)**
   - Si 1 seul prix pour 2 outcomes → calcul du prix manquant: `1.0 - known_price`
   - Utilisation du `PriceBuffer` pour accumuler les prix partiels

### 5. Validation des Prix (`market_updater.py`)

1. **Validation basique**
   - Tous les prix entre 0 et 1
   - Nombre de prix = nombre d'outcomes
   - Somme des prix ≈ 1.0 (tolérance: 0.05)

2. **Log des erreurs**
   - Si invalide: log WARNING et skip

### 6. Mise à Jour avec Debounce (`market_updater.py`)

1. **Scheduling avec debounce**
   ```python
   await market_debounce.schedule_update(
       key=market_id,
       data={'market_id': market_id, 'prices': prices},
       callback=_process_market_update
   )
   ```
   - Délai par défaut: 5 secondes
   - Accumule les mises à jour pour éviter le spam

2. **Traitement final**
   ```python
   await _process_market_update(market_id, prices)
   ```
   - Mise à jour DB: `outcome_prices`, `last_mid_price`, `source='ws'`
   - Log: `✅ Updated market {market_id} with source='ws'`

## Points Critiques pour les Marchés Courts (15min)

1. **Souscription rapide**: La souscription se fait automatiquement après un trade
2. **Messages fréquents**: Les marchés actifs peuvent avoir beaucoup de `price_change`
3. **Debounce**: 5 secondes peut être trop long pour des marchés très volatiles
4. **Pas de filtrage par durée**: Le code ne filtre pas les marchés courts

## Logs de Diagnostic Ajoutés

### Niveau INFO (visible en production)

- `📥 RAW WebSocket message`: Tous les messages reçus
- `📨 Received WebSocket message`: Messages JSON parsés
- `📊 Routing price_change event`: Routing vers handler
- `🔍 Resolving market identifier`: Résolution condition_id → market_id
- `🔍 Converting condition_id to market_id`: Conversion en cours
- `✅ Found market_id`: Conversion réussie
- `🔍 Extracting prices`: Extraction des prix
- `✅ Extracted prices`: Prix extraits avec succès
- `🔍 Validating prices`: Validation en cours
- `✅ Prices validated`: Validation réussie
- `⏱️ Scheduling market update`: Mise à jour planifiée
- `✅ Processing debounced market update`: Traitement final

### Niveau WARNING

- `⚠️ Could not find market_id`: Échec de résolution
- `⚠️ Partial price mapping`: Prix partiels détectés
- `⚠️ Invalid prices`: Validation échouée

## Vérifications pour le Prochain Trade

1. ✅ Format de souscription conforme à la doc
2. ✅ Gestion des messages `PONG` avant parsing JSON
3. ✅ Routing correct des `event_type="price_change"`
4. ✅ Conversion condition_id → market_id
5. ✅ Extraction des prix depuis `best_bid`/`best_ask`
6. ✅ Calcul du prix manquant pour marchés binaires
7. ✅ Validation des prix avant mise à jour
8. ✅ Debounce pour éviter le spam
9. ✅ Logs détaillés à chaque étape

## Prochaines Étapes de Debug

Si les prix ne se mettent toujours pas à jour:

1. Vérifier les logs `📥 RAW WebSocket message` pour voir si des messages arrivent
2. Vérifier les logs `🔍 Resolving market identifier` pour voir si le condition_id est résolu
3. Vérifier les logs `🔍 Extracting prices` pour voir si les prix sont extraits
4. Vérifier les logs `⏱️ Scheduling market update` pour voir si la mise à jour est planifiée
5. Vérifier les logs `✅ Processing debounced market update` pour voir si la mise à jour est appliquée
