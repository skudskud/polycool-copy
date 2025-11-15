# Analyse du fonctionnement WebSocket et watched_markets

## Vue d'ensemble

Le système utilise un WebSocket CLOB pour streamer les prix en temps réel des marchés où les utilisateurs ont des positions. Le flux complet implique plusieurs composants :

1. **WatchedMarketsService** : Détecte automatiquement les marchés avec positions utilisateurs
2. **watched_markets** (table DB) : Liste des marchés à surveiller
3. **StreamerService** : Se connecte au WebSocket CLOB et s'abonne aux tokens
4. **subsquid_markets_ws** : Stocke les prix streamés en temps réel
5. **subsquid_markets_poll** : Table de référence avec métadonnées des marchés

---

## Flux complet : Ajout d'un marché à watched_markets

### 1. Détection initiale d'une position utilisateur

**Point d'entrée** : Un utilisateur achète/vend via le bot Telegram

```python
# telegram-bot-v2/py-clob-server/telegram_bot/services/trading_service.py
# Après un trade réussi, le service appelle watched_markets_service
```

**Fichiers clés** :
- `telegram-bot-v2/py-clob-server/core/services/watched_markets_service.py`
- `telegram-bot-v2/py-clob-server/telegram_bot/services/trading_service.py`

### 2. Scan périodique des positions

Le `WatchedMarketsService` scanne régulièrement (tâche planifiée) :

```python
# main.py - Tâche planifiée toutes les 5 minutes
async def scan_watched_markets():
    result = await watched_markets_service.scan_and_update_watched_markets()
```

**Processus de scan** :

#### 2.1. Récupération des positions utilisateurs
```python
# watched_markets_service.py - _get_all_market_positions()
# Scanne les positions de tous les wallets utilisateurs via Polymarket API
# URL: https://data-api.polymarket.com/positions?user={wallet}&closed=false&limit=100
```

**Important** :
- Utilise `condition_id` comme identifiant principal (format `0x...`)
- Le `market_id` dans `watched_markets` = `condition_id` (pour JOIN avec `subsquid_markets_poll`)

#### 2.2. Récupération des marchés smart wallets
```python
# watched_markets_service.py - _get_smart_wallet_markets()
# Query smart_wallet_trades pour les 30 derniers jours
# Jointure avec subsquid_markets_poll pour obtenir condition_id
```

#### 2.3. Merge et agrégation
- Fusionne les deux sources (positions utilisateurs + smart wallets)
- Compte le nombre de positions par marché
- Identifie les nouveaux marchés à ajouter

### 3. Ajout à watched_markets

**Méthode** : `_add_watched_market(market_id, condition_id, title, position_count)`

#### 3.1. Cache Redis (optimisation)
```python
# Cache les nouveaux marchés pendant 10s pour traitement batch
cache_key = f"pending_watched_markets:{market_id}"
await redis_client.setex(cache_key, 10, "1")

# Notifie le streamer d'un changement
await redis_client.setex("streamer:watched_markets_changed", 60, "1")
```

#### 3.2. Insertion DB (upsert)
```sql
INSERT INTO watched_markets (
    market_id, condition_id, title,
    active_positions, last_position_at, created_at, updated_at
)
VALUES (:market_id, :condition_id, :title, :position_count, :now, :now, :now)
ON CONFLICT (market_id) DO UPDATE SET
    active_positions = watched_markets.active_positions + :position_count,
    last_position_at = :now,
    updated_at = :now,
    condition_id = COALESCE(EXCLUDED.condition_id, watched_markets.condition_id),
    title = COALESCE(EXCLUDED.title, watched_markets.title)
```

**Note importante** :
- `market_id` dans `watched_markets` = `condition_id` (format `0x...`)
- Permet le JOIN direct avec `subsquid_markets_poll.condition_id`

### 4. Traitement batch des marchés en attente

**Tâche planifiée** : Toutes les 10 secondes
```python
# main.py
async def process_pending_watched_markets():
    processed = await watched_markets_service.process_pending_watched_markets()
```

- Lit les clés Redis `pending_watched_markets:*`
- Récupère les métadonnées depuis `subsquid_markets_poll`
- Fait l'upsert dans `watched_markets`
- Supprime les clés Redis après traitement

---

## Fonctionnement du WebSocket Streamer

### 1. Connexion et authentification

**Fichier** : `apps/subsquid-silo-tests/data-ingestion/src/ws/streamer.py`

```python
# StreamerService._connect_and_stream()
ws_url = f"{ws_url}?apikey={CLOB_API_KEY}&secret={CLOB_API_SECRET}&passphrase={CLOB_API_PASSPHRASE}"
```

### 2. Récupération des token IDs à surveiller

**Méthode** : `get_market_token_ids(limit=500)`

**Sources multiples** (dans l'ordre de priorité) :

#### 2.1. Watched markets (positions utilisateurs)
```sql
SELECT wm.market_id, sp.clob_token_ids
FROM watched_markets wm
JOIN subsquid_markets_poll sp ON wm.market_id = sp.condition_id
WHERE wm.active_positions > 0
  AND sp.status = 'ACTIVE'
  AND sp.tradeable = true
  AND sp.accepting_orders = true
  AND sp.clob_token_ids IS NOT NULL
```

**JOIN clé** : `watched_markets.market_id = subsquid_markets_poll.condition_id`

#### 2.2. Smart traders (24h)
```sql
SELECT DISTINCT sp.market_id, sp.clob_token_ids
FROM smart_wallet_trades swt
JOIN subsquid_markets_poll sp ON swt.market_id = sp.condition_id
WHERE swt.timestamp > NOW() - INTERVAL '24 hours'
  AND sp.status = 'ACTIVE'
  AND sp.tradeable = true
```

#### 2.3. Toutes les positions utilisateurs (30 jours)
```sql
SELECT DISTINCT sp.market_id, sp.clob_token_ids
FROM transactions t
JOIN subsquid_markets_poll sp ON t.market_id = sp.condition_id
WHERE t.executed_at > NOW() - INTERVAL '30 days'
  AND t.transaction_type IN ('BUY', 'SELL')
```

#### 2.4. Parsing des clob_token_ids
```python
# clob_token_ids est stocké comme JSON string (peut être double-échappé)
# Format: "[\"token1\", \"token2\"]"
cleaned = token_ids_raw
if cleaned.startswith('"') and cleaned.endswith('"'):
    cleaned = cleaned[1:-1]
cleaned = cleaned.replace('\\\\', '\\').replace('\\"', '"')
token_array = json.loads(cleaned)
```

### 3. Abonnement WebSocket

**Message de subscription** :
```json
{
  "action": "subscribe",
  "type": "market",
  "assets_ids": ["token1", "token2", ...]  // Liste plate de tous les tokens
}
```

**Limite** : 500 tokens maximum (limite CLOB)

### 4. Refresh périodique des abonnements

**Tâche** : `_periodic_subscription_refresh()` toutes les 60 secondes

**Vérifications** :
1. Flag Redis `streamer:watched_markets_changed` (refresh immédiat si présent)
2. Comparaison avec les tokens actuellement abonnés
3. Unsubscribe des marchés inactifs
4. Subscribe aux nouveaux marchés

**Exemple de log** :
```
🔄 Subscription refresh: 234 total markets | +12 | -5
```

### 5. Réception et traitement des messages WebSocket

#### 5.1. Types de messages reçus

**price_change** (le plus commun) :
```json
{
  "event_type": "price_change",
  "market": "0x...",  // condition_id
  "price_changes": [
    {
      "asset_id": "token_id",
      "best_bid": 0.65,
      "best_ask": 0.67
    }
  ],
  "timestamp": "..."
}
```

**orderbook** / **snapshot** / **delta** :
- Contient `bids` et `asks` arrays
- Extrait `best_bid` et `best_ask`

#### 5.2. Mapping token → market

**Processus** :
1. Reçoit `market` (condition_id) dans le message
2. Query `subsquid_markets_poll` pour obtenir les métadonnées :
   ```sql
   SELECT market_id, condition_id, clob_token_ids, title, outcomes
   FROM subsquid_markets_poll
   WHERE condition_id = $1
   ```
3. Parse `clob_token_ids` pour mapper `asset_id` → `outcome` (Yes/No)
4. Calcule le prix mid : `(best_bid + best_ask) / 2`

#### 5.3. Stockage dans subsquid_markets_ws

**Update** :
```python
# streamer.py - _handle_price_change()
update_data = {
    'outcome_prices': {
        'Yes': 0.66,  # Prix calculé depuis best_bid/best_ask
        'No': 0.34
    },
    'last_bb': best_bid,
    'last_ba': best_ask
}

await db.upsert_market_ws(market_id, update_data)
```

**Table** : `subsquid_markets_ws`
- `market_id` : ID court du marché
- `last_bb` / `last_ba` : Best bid/ask
- `last_mid` : Prix moyen (calculé)
- `outcome_prices` : JSONB avec prix par outcome
- `updated_at` : Timestamp de dernière mise à jour

---

## Schéma des tables

### watched_markets
```sql
CREATE TABLE watched_markets (
    market_id TEXT PRIMARY KEY,           -- condition_id (0x...)
    condition_id TEXT,                     -- condition_id (dupliqué pour compatibilité)
    title TEXT,
    active_positions INTEGER DEFAULT 0,    -- Nombre de positions actives
    last_position_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);
```

**Index** :
- `idx_watched_markets_condition_id` sur `condition_id`
- `idx_watched_markets_active_positions` sur `active_positions DESC`

### subsquid_markets_ws
```sql
CREATE TABLE subsquid_markets_ws (
    market_id TEXT PRIMARY KEY,           -- ID court du marché
    title TEXT,
    status TEXT,
    last_bb NUMERIC(8,4),                 -- Best bid
    last_ba NUMERIC(8,4),                 -- Best ask
    last_mid NUMERIC(8,4),                -- Mid price
    last_trade_price NUMERIC(8,4),
    outcome_prices JSONB,                 -- {"Yes": 0.66, "No": 0.34}
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

**Index** :
- `idx_subsquid_markets_ws_updated_at` sur `updated_at DESC`

### subsquid_markets_poll
```sql
CREATE TABLE subsquid_markets_poll (
    market_id TEXT PRIMARY KEY,           -- ID court
    condition_id TEXT,                    -- ID complet (0x...)
    clob_token_ids TEXT,                  -- JSON array: ["token1", "token2"]
    outcomes TEXT[],                      -- Array: ['Yes', 'No']
    outcome_prices NUMERIC(8,4)[],         -- Array: [0.66, 0.34]
    status TEXT,                          -- 'ACTIVE' ou 'CLOSED'
    tradeable BOOLEAN,
    accepting_orders BOOLEAN,
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

---

## Flux de données complet

```
┌─────────────────────────────────────────────────────────────┐
│ 1. USER BUYS POSITION                                        │
│    → trading_service.py                                      │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. watched_markets_service._add_watched_market()            │
│    → Cache Redis: pending_watched_markets:{market_id}      │
│    → Flag: streamer:watched_markets_changed                 │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Batch processing (10s)                                   │
│    → process_pending_watched_markets()                      │
│    → INSERT INTO watched_markets                            │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Streamer refresh (60s ou immédiat si flag)              │
│    → get_market_token_ids()                                 │
│    → JOIN watched_markets ↔ subsquid_markets_poll           │
│    → Parse clob_token_ids                                   │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. WebSocket subscription                                    │
│    → {action: "subscribe", type: "market",                  │
│       assets_ids: [token1, token2, ...]}                    │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. CLOB WebSocket messages                                   │
│    → price_change events                                     │
│    → market: "0x..." (condition_id)                         │
│    → price_changes: [{asset_id, best_bid, best_ask}]       │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. Streamer processing                                      │
│    → _handle_price_change()                                 │
│    → Query subsquid_markets_poll pour métadonnées           │
│    → Map asset_id → outcome (Yes/No)                        │
│    → Calculate mid price                                    │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ 8. Update subsquid_markets_ws                               │
│    → UPSERT avec outcome_prices, last_bb, last_ba           │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ 9. Price retrieval (price_updater_service)                  │
│    → Priority: WS > Poller > API                           │
│    → Query subsquid_markets_ws pour prix frais              │
└─────────────────────────────────────────────────────────────┘
```

---

## Points critiques et optimisations

### 1. JOIN condition_id

**Important** : `watched_markets.market_id` = `condition_id` (pas l'ID court)

```sql
-- ✅ CORRECT
JOIN subsquid_markets_poll sp ON wm.market_id = sp.condition_id

-- ❌ INCORRECT (ne fonctionnerait pas)
JOIN subsquid_markets_poll sp ON wm.market_id = sp.market_id
```

### 2. Parsing clob_token_ids

Le champ `clob_token_ids` peut être double-échappé :
```python
# Format brut: "\"[\\\"token1\\\", \\\"token2\\\"]\""
# Après cleaning: ["token1", "token2"]
```

### 3. Limite WebSocket

- Maximum 500 tokens par subscription
- Le streamer priorise les marchés avec positions utilisateurs
- Refresh toutes les 60s pour ajouter/retirer des marchés

### 4. Fraîcheur des prix

**Hiérarchie de sources** :
1. **subsquid_markets_ws** : < 100ms (WebSocket temps réel)
2. **subsquid_markets_poll** : ~60s (poller Gamma API)
3. **CLOB API direct** : Fallback lent (~2-5s)

### 5. Cache Redis

- **pending_watched_markets:{market_id}** : TTL 10s (batch processing)
- **streamer:watched_markets_changed** : TTL 60s (notification streamer)

---

## Logs typiques

### Ajout d'un marché
```
📈 [SAFE UPSERT] Market 0x... added/updated in watched_markets
🔔 Flagged watched_markets change for Streamer (will subscribe on next check)
```

### Refresh streamer
```
✅ Retrieved 234 unique token IDs from 156 total markets
   📊 Sources: 98 watched + 34 smart traders + 24 user positions
🔄 Subscription refresh: 234 total markets | +12 | -5
```

### Réception prix WebSocket
```
🔄 HANDLER: _handle_price_change called for market 0x... with 2 changes
✅ YES PRICE: market=0x... asset_id=... price=$0.660000 (from bid/ask)
✅ UPDATED: Market 516947... with outcomes: ['Yes', 'No'], prices: {'Yes': 0.66, 'No': 0.34}
```

---

## Questions fréquentes

### Q: Pourquoi watched_markets.market_id = condition_id ?
**R:** Pour permettre le JOIN direct avec `subsquid_markets_poll.condition_id` et éviter un double mapping.

### Q: Comment le streamer sait-il quels tokens surveiller ?
**R:** Via `get_market_token_ids()` qui fait un JOIN `watched_markets` ↔ `subsquid_markets_poll` pour extraire les `clob_token_ids`.

### Q: Que se passe-t-il si un marché n'est plus dans watched_markets ?
**R:** Le streamer détecte le changement au refresh suivant (60s) et unsubscribes automatiquement.

### Q: Les prix sont-ils en temps réel ?
**R:** Oui, via WebSocket (< 100ms). Le fallback vers le poller (~60s) ou l'API (~2-5s) n'est utilisé que si le WebSocket n'a pas de données.

### Q: Comment nettoyer les marchés résolus ?
**R:** `_remove_resolved_markets()` vérifie `subsquid_markets_poll.resolution_status` et supprime automatiquement les marchés résolus de `watched_markets`.
