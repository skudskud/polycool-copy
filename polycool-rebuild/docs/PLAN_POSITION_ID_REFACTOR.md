# Plan : Utiliser position_id comme identifiant principal

## Objectif
Simplifier le flow copy trading en utilisant `position_id` (clob_token_id) comme identifiant unique et précis, au lieu de gérer `original_id` vs `resolved_id`.

## Avantages
1. **Plus précis** : `position_id` identifie directement le token (YES/NO) d'un market
2. **Plus simple** : Plus besoin de gérer `original_id` vs `resolved_id`
3. **Plus rapide** : Une seule colonne indexée au lieu de `market_id + outcome`
4. **Cohérent** : Même logique pour leader et follower
5. **Déjà disponible** : `position_id` est dans le webhook et dans `trades` table

## État actuel

### Tables avec position_id ✅
- `leader_positions` : a déjà `position_id` (nullable)
- `trades` : a déjà `position_id` (nullable)

### Tables SANS position_id ❌
- `positions` : PAS de `position_id` (follower positions)

## Modifications nécessaires

### 1. Migration SQL : Ajouter position_id à positions
**Fichier** : `migrations/add_position_id_to_positions.sql`

```sql
-- Ajouter colonne position_id
ALTER TABLE positions
ADD COLUMN position_id VARCHAR(100);

-- Index pour recherche rapide
CREATE INDEX idx_positions_position_id ON positions(position_id);

-- Index composite pour recherche par user + position_id
CREATE INDEX idx_positions_user_position_id ON positions(user_id, position_id)
WHERE status = 'active';
```

### 2. Modifier le modèle Position
**Fichier** : `core/database/models.py`

Ajouter :
```python
position_id = Column(String(100), nullable=True, index=True,
                     comment="Token ID from blockchain (clob_token_id) - for precise position lookup")
```

### 3. Modifier create_position() pour accepter position_id
**Fichier** : `core/services/position/crud.py`

- Ajouter paramètre `position_id: Optional[str] = None`
- Stocker `position_id` lors de la création

### 4. Modifier trade_service pour passer position_id
**Fichier** : `core/services/trading/trade_service.py`

Dans `_execute_trade()` :
- `token_id` est déjà récupéré via `_get_token_id_for_outcome()`
- Passer `token_id` à `create_position()` comme `position_id`

### 5. Modifier _calculate_sell_copy_amount() pour chercher par position_id
**Fichier** : `data_ingestion/indexer/copy_trading_listener.py`

- Récupérer `position_id` depuis `trade_data.get('position_id')`
- Chercher follower position UNIQUEMENT par `position_id` (plus besoin de `market_id` + `outcome`)
- Simplifier la logique (plus besoin de try resolved_id puis original_id)

### 6. Vérifier leader_positions (déjà OK)
**Fichier** : `core/services/copy_trading/leader_position_tracker.py`

- ✅ Déjà stocke `position_id` dans `update_leader_position()`
- ✅ Déjà cherche par `position_id` en priorité dans `get_leader_position()`

## Flow simplifié

### BUY Copy Trade
```
1. Webhook reçoit : event.position_id
2. Résolution : position_id → market.id + outcome (via clob_token_ids)
3. Exécution trade : token_id = position_id
4. Création position follower : stocke position_id ✅
5. Mise à jour leader_positions : stocke position_id ✅
```

### SELL Copy Trade
```
1. Webhook reçoit : event.position_id
2. Résolution : position_id → market.id + outcome
3. Cherche leader position : par position_id ✅
4. Cherche follower position : par position_id ✅ (NOUVEAU)
5. Calcul proportionnel : utilise tokens directement
```

## Points d'attention

1. **Backward compatibility** : Les positions existantes n'auront pas de `position_id`
   - Solution : `position_id` est nullable
   - Recherche fallback : si `position_id` est NULL, utiliser `market_id + outcome` (pour positions existantes)

2. **Résolution position_id → market** : Déjà implémentée dans `_resolve_market_by_position_id()`
   - Utilise `Market.clob_token_ids.contains([position_id])`
   - Trouve l'index dans `clob_token_ids`
   - Récupère l'outcome depuis `outcomes[index]`

3. **API mode (SKIP_DB)** : Vérifier que `api_client.create_position()` supporte `position_id`
   - Si non, ajouter le support

## Tests à effectuer

1. ✅ BUY copy trade crée position avec `position_id`
2. ✅ SELL copy trade trouve position follower par `position_id`
3. ✅ Positions existantes (sans `position_id`) fonctionnent toujours (fallback)
4. ✅ Leader positions fonctionnent (déjà OK)

## Ordre d'implémentation

1. Migration SQL
2. Modèle Position
3. create_position()
4. trade_service._execute_trade()
5. _calculate_sell_copy_amount()
6. Tests
