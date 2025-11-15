# Copy Trading vs Smart Trading - Distinction et Flow

**Date:** 2025-01-27
**Status:** Architecture en place, clarification nécessaire

---

## 🎯 Vue d'Ensemble

Deux flows distincts utilisent la même infrastructure d'ingestion de données mais avec des objectifs différents:

1. **Copy Trading** (`/copy_trading`): Copy automatique des trades d'un leader choisi par l'utilisateur
2. **Smart Trading** (`/smart_trading`): Affichage des derniers trades des smart wallets (hard-coded) pour choix manuel

---

## 📊 Distinction dans la Table `trades`

### Structure Actuelle

```sql
-- Table watched_addresses
CREATE TABLE watched_addresses (
    id SERIAL PRIMARY KEY,
    address VARCHAR(100) UNIQUE NOT NULL,
    address_type VARCHAR(20) NOT NULL,  -- 'smart_trader', 'copy_leader', 'bot_user'
    is_active BOOLEAN DEFAULT TRUE,
    ...
);

-- Table trades
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    watched_address_id INTEGER REFERENCES watched_addresses(id),
    market_id VARCHAR(100) NOT NULL,
    outcome VARCHAR(100) NOT NULL,
    amount FLOAT NOT NULL,
    price FLOAT NOT NULL,
    amount_usdc NUMERIC(18, 6),  -- Exact USDC amount (taking_amount from indexer)
    tx_hash VARCHAR(100) UNIQUE NOT NULL,
    trade_type VARCHAR(20) NOT NULL,  -- 'buy', 'sell'
    timestamp TIMESTAMP NOT NULL,
    ...
);
```

### Comment Distinguer Leader vs Smart Wallet

**Méthode actuelle:** JOIN avec `watched_addresses` et filtrer par `address_type`

```sql
-- Trades de Smart Wallets (pour /smart_trading)
SELECT t.*, wa.address, wa.name
FROM trades t
JOIN watched_addresses wa ON t.watched_address_id = wa.id
WHERE wa.address_type = 'smart_trader'
  AND wa.is_active = TRUE
  AND t.trade_type = 'buy'
  AND t.amount_usdc >= 300.0  -- Filtre montant minimum
ORDER BY t.timestamp DESC
LIMIT 20;

-- Trades de Leaders (pour copy trading)
SELECT t.*, wa.address, wa.name
FROM trades t
JOIN watched_addresses wa ON t.watched_address_id = wa.id
WHERE wa.address_type = 'copy_leader'
  AND wa.is_active = TRUE
ORDER BY t.timestamp DESC;
```

### ⚠️ Problème Actuel

**Pas de champ direct dans `trades`** pour distinguer sans JOIN. Cela fonctionne mais:
- Requêtes plus lentes (JOIN nécessaire)
- Pas d'index direct sur le type
- Code plus verbeux

### ✅ Solution Recommandée (Optionnelle)

Ajouter un champ dérivé `source_type` dans `trades` pour faciliter les requêtes:

```python
# Migration suggérée
ALTER TABLE trades ADD COLUMN source_type VARCHAR(20);
-- 'copy_leader', 'smart_trader', 'bot_user'

# Populate from watched_addresses
UPDATE trades t
SET source_type = wa.address_type
FROM watched_addresses wa
WHERE t.watched_address_id = wa.id;

# Index pour performance
CREATE INDEX idx_trades_source_type ON trades(source_type, timestamp);

# Trigger pour auto-populate (optionnel)
CREATE OR REPLACE FUNCTION update_trade_source_type()
RETURNS TRIGGER AS $$
BEGIN
    SELECT address_type INTO NEW.source_type
    FROM watched_addresses
    WHERE id = NEW.watched_address_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trade_source_type_trigger
BEFORE INSERT OR UPDATE ON trades
FOR EACH ROW
EXECUTE FUNCTION update_trade_source_type();
```

**Avantages:**
- Requêtes plus rapides (pas de JOIN nécessaire)
- Index direct sur `source_type`
- Code plus simple

**Inconvénients:**
- Redondance de données (déjà dans `watched_addresses`)
- Nécessite trigger ou logique applicative pour maintenir

**Recommandation:** **Garder la structure actuelle** (JOIN) pour l'instant, sauf si les performances deviennent un problème.

---

## 🔄 Flow: Ajouter une Nouvelle Adresse Watchée

### Flow Copy Trading (User-Driven)

```
1. User exécute /copy_trading
   ↓
2. User entre l'adresse du leader (ou recherche)
   ↓
3. Bot vérifie si l'adresse existe dans watched_addresses
   ↓
4a. Si existe:
    - Vérifie address_type == 'copy_leader'
    - Crée/update CopyTradingAllocation
   ↓
4b. Si n'existe pas:
    - Crée WatchedAddress avec address_type='copy_leader'
    - Crée CopyTradingAllocation
   ↓
5. Refresh cache Redis (watched_addresses)
   ↓
6. Indexer fetch via /subsquid/watched_addresses (dans 1min)
   ↓
7. Indexer commence à tracker cette adresse
   ↓
8. Trades détectés → Webhook → Redis → Copy Trade automatique
```

**Code actuel:**

```python
# telegram_bot/bot/handlers/copy_trading/leaders.py
async def _handle_add_leader(query, context):
    # User entre l'adresse
    # ...
    # Crée WatchedAddress si nécessaire
    watched_addr = await watched_manager.add_watched_address(
        address=leader_address,
        address_type='copy_leader',
        name=name
    )
    # Crée allocation
    allocation = await copy_trading_service.subscribe_to_leader(...)
```

### Flow Smart Trading (Admin-Driven)

```
1. Admin ajoute smart wallet manuellement (script/DB)
   ↓
2. Crée WatchedAddress avec address_type='smart_trader'
   ↓
3. Refresh cache Redis (watched_addresses)
   ↓
4. Indexer fetch via /subsquid/watched_addresses (dans 1min)
   ↓
5. Indexer commence à tracker cette adresse
   ↓
6. Trades détectés → Webhook → Redis → Stocke dans trades
   ↓
7. Filtre: amount_usdc >= $300 (dans smart_trading_handler)
   ↓
8. Affiche dans /smart_trading pour choix manuel user
```

**Code actuel:**

```python
# Scripts/import_smart_wallets.py ou admin command
watched_addr = await watched_manager.add_watched_address(
    address=wallet_address,
    address_type='smart_trader',
    name=wallet_name
)
```

---

## 🔍 Différences Clés entre les Deux Flows

| Aspect | Copy Trading | Smart Trading |
|--------|--------------|---------------|
| **Trigger** | User choisit un leader | Admin ajoute smart wallet |
| **Address Type** | `copy_leader` | `smart_trader` |
| **Filtre Montant** | Aucun (copy tous les trades) | `amount_usdc >= $300` |
| **Exécution** | Automatique (Redis PubSub) | Manuel (user choisit) |
| **Allocation** | Budget % ou Fixed Amount | Pas d'allocation |
| **Mode** | Proportional ou Fixed Amount | N/A |
| **SELL** | Toujours proportionnel | N/A (affichage seulement) |
| **Table Utilisée** | `copy_trading_allocations` | Pas de table dédiée |
| **Handler** | `copy_trading_listener.py` | `smart_trading_handler.py` |

---

## 📋 Flow Complet par Type

### Copy Trading Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    USER ACTION                             │
│  /copy_trading → Add Leader → Enter Address               │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              WATCHED ADDRESS CREATION                       │
│  WatchedAddress(address_type='copy_leader')                │
│  CopyTradingAllocation(user_id, leader_address_id)         │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              REDIS CACHE REFRESH                           │
│  watched_addresses:cache → Updated                         │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              INDEXER FETCH (1min interval)                 │
│  GET /subsquid/watched_addresses                           │
│  → Indexer commence à tracker cette adresse                 │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              TRADE DETECTED                                │
│  Indexer → Webhook → Redis PubSub                          │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              COPY TRADING LISTENER                         │
│  Subscribe copy_trade:* → Execute copy trade               │
│  - Calculate amount (proportional/fixed)                    │
│  - Execute via trade_service                               │
│  - Update allocation stats                                 │
└─────────────────────────────────────────────────────────────┘
```

### Smart Trading Flow

```
┌─────────────────────────────────────────────────────────────┐
│              ADMIN ACTION                                    │
│  Script/DB: Add smart wallet                                │
│  WatchedAddress(address_type='smart_trader')                │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              REDIS CACHE REFRESH                           │
│  watched_addresses:cache → Updated                         │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              INDEXER FETCH (1min interval)                 │
│  GET /subsquid/watched_addresses                           │
│  → Indexer commence à tracker cette adresse                 │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              TRADE DETECTED                                │
│  Indexer → Webhook → Redis PubSub                          │
│  → Stocke dans trades (watched_address_id)                  │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              SMART TRADING HANDLER                         │
│  /smart_trading command                                    │
│  - Query trades WHERE address_type='smart_trader'          │
│  - Filter: trade_type='buy' AND amount_usdc >= $300         │
│  - Display: 10 derniers trades                             │
│  - User choisit manuellement                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 Code Actuel - Points Clés

### 1. Distinction dans les Requêtes

**Smart Trading Handler:**

```120:135:polycool/polycool-rebuild/telegram_bot/bot/handlers/smart_trading_handler.py
            result = await db.execute(
                select(Trade)
                .join(WatchedAddress, Trade.watched_address_id == WatchedAddress.id)
                .where(
                    and_(
                        WatchedAddress.address_type == 'smart_trader',
                        WatchedAddress.is_active == True,
                        Trade.trade_type == 'buy',
                        Trade.timestamp >= cutoff_time,
                        Trade.amount * Trade.price >= MIN_TRADE_VALUE
                    )
                )
                .options(joinedload(Trade.watched_address))
                .order_by(desc(Trade.timestamp))
                .limit(limit)
            )
```

**Copy Trading Listener:**

```144:155:polycool/polycool-rebuild/data_ingestion/indexer/copy_trading_listener.py
            # Get all active copy trading allocations for this leader
            async with get_db() as db:
                result = await db.execute(
                    select(CopyTradingAllocation)
                    .where(
                        and_(
                            CopyTradingAllocation.leader_address_id == watched_address.id,
                            CopyTradingAllocation.is_active == True
                        )
                    )
                )
                allocations = list(result.scalars().all())
```

### 2. Filtre Montant Minimum

**Smart Trading:** Filtre `amount_usdc >= $300` (ou `amount * price >= MIN_TRADE_VALUE`)

**Copy Trading:** Pas de filtre (copy tous les trades)

### 3. Webhook Receiver

Le webhook receiver stocke dans `trades` avec `watched_address_id`, qui permet de distinguer via JOIN:

```147:209:polycool/polycool-rebuild/telegram_bot/api/v1/webhooks/copy_trade.py
async def _store_trade_in_db(
    watched_address_id: int,
    event: CopyTradeWebhookPayload
) -> None:
    """Store trade in database (background task)"""
    try:
        async with get_db() as db:
            # Check if trade already exists (deduplication)
            result = await db.execute(
                select(Trade)
                .where(Trade.tx_hash == event.tx_hash)
            )
            existing = result.scalar_one_or_none()

            if existing:
                logger.debug(f"⏭️ Trade {event.tx_hash[:20]}... already exists in DB")
                return

            # Parse values
            try:
                # amount is in units (6 decimals), convert to real value
                amount_raw = float(event.amount) if event.amount else 0.0
                amount = amount_raw / 1_000_000 if amount_raw > 1_000_000 else amount_raw  # Convert if in units
                price = float(event.price) if event.price else None
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Invalid amount/price in webhook: {event.amount}, {event.price}")
                amount = 0.0
                price = None

            # Parse amount_usdc (taking_amount) - already in USDC real value, not units
            amount_usdc = None
            if event.taking_amount:
                try:
                    amount_usdc = float(event.taking_amount)
                    # Validate range to prevent overflow
                    if amount_usdc > 999999999.999999 or amount_usdc < -999999999.999999:
                        logger.warning(f"⚠️ amount_usdc out of range: {amount_usdc}, setting to None")
                        amount_usdc = None
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ Invalid taking_amount format: {event.taking_amount}")
                    amount_usdc = None

            # Parse timestamp
            try:
                timestamp = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
            except Exception:
                timestamp = datetime.now(timezone.utc)

            # Create trade record
            trade = Trade(
                watched_address_id=watched_address_id,
                market_id=event.market_id or "unknown",
                outcome="YES" if event.outcome == 1 else "NO" if event.outcome == 0 else "UNKNOWN",
                amount=amount,
                price=price or 0.0,
                amount_usdc=amount_usdc,  # Store exact USDC amount from indexer
                tx_hash=event.tx_hash,
                block_number=int(event.block_number) if event.block_number else None,
                timestamp=timestamp,
                trade_type=event.tx_type.lower(),  # 'buy' or 'sell'
                is_processed=False,
                created_at=datetime.now(timezone.utc)
            )

            db.add(trade)
            await db.commit()

            logger.debug(f"✅ Stored trade {event.tx_hash[:20]}... in DB")
```

---

## ✅ Checklist: Comment Ajouter une Nouvelle Adresse

### Pour Copy Trading (User-Driven)

- [ ] User exécute `/copy_trading`
- [ ] User entre l'adresse du leader
- [ ] Bot crée `WatchedAddress` avec `address_type='copy_leader'`
- [ ] Bot crée `CopyTradingAllocation` pour l'user
- [ ] Cache Redis refresh automatique
- [ ] Indexer fetch dans 1min max
- [ ] Trades commencent à être trackés

### Pour Smart Trading (Admin-Driven)

- [ ] Admin ajoute smart wallet (script/DB)
- [ ] Crée `WatchedAddress` avec `address_type='smart_trader'`
- [ ] Refresh cache Redis (ou attend refresh automatique)
- [ ] Indexer fetch dans 1min max
- [ ] Trades commencent à être trackés
- [ ] Filtre `amount_usdc >= $300` appliqué dans handler
- [ ] Trades affichés dans `/smart_trading`

---

## 🚀 Recommandations

### 1. Garder la Structure Actuelle

✅ **JOIN avec `watched_addresses`** fonctionne bien pour distinguer les types.

### 2. Améliorer le Filtre Smart Trading

Actuellement, le filtre utilise `Trade.amount * Trade.price >= MIN_TRADE_VALUE`, mais on devrait utiliser `amount_usdc` directement (plus précis):

```python
# Actuel (moins précis)
Trade.amount * Trade.price >= MIN_TRADE_VALUE

# Recommandé (plus précis)
Trade.amount_usdc >= 300.0  # Utilise le montant exact de l'indexer
```

### 3. Documenter le Flow Admin

Créer un script/admin command pour ajouter smart wallets facilement:

```python
# scripts/add_smart_wallet.py
async def add_smart_wallet(address: str, name: str):
    watched_manager = get_watched_addresses_manager()
    await watched_manager.add_watched_address(
        address=address,
        address_type='smart_trader',
        name=name
    )
    logger.info(f"✅ Added smart wallet: {address}")
```

### 4. Monitoring

Ajouter des métriques pour distinguer les deux flows:
- Nombre de trades copy trading vs smart trading
- Volume par type
- Performance par type

---

## 📚 Références

- Models: `core/database/models.py`
- Copy Trading: `data_ingestion/indexer/copy_trading_listener.py`
- Smart Trading: `telegram_bot/bot/handlers/smart_trading_handler.py`
- Webhook: `telegram_bot/api/v1/webhooks/copy_trade.py`
- Watched Addresses: `data_ingestion/indexer/watched_addresses/manager.py`
