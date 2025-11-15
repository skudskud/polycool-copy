# Diagnostic et Fix : WebSocket ne stream pas les prix

## Problème identifié

Le token `6861832820...` appartient au marché `665974` mais :
1. ❌ Le marché n'est **PAS** dans `watched_markets`
2. ❌ Aucune transaction récente dans `transactions` (30 jours)
3. ❌ Le streamer ne s'abonne donc **PAS** aux tokens de ce marché
4. ❌ Résultat : Pas de prix WebSocket disponible

## Cause racine

Le système de détection des positions utilise plusieurs sources :

### 1. WatchedMarketsService.scan_and_update_watched_markets()
- Scanne les positions via **Polymarket API** (`https://data-api.polymarket.com/positions`)
- Ne regarde que les wallets utilisateurs dans la table `users`
- Si l'utilisateur n'a pas de wallet enregistré ou si le scan n'a pas encore détecté la position → marché pas ajouté

### 2. get_market_token_ids() dans le streamer
- Source 1 : `watched_markets` (via JOIN avec `subsquid_markets_poll`)
- Source 2 : `smart_wallet_trades` (24h)
- Source 3 : `transactions` (30 jours) - **JOIN sur condition_id**

**Problème** : Si aucune de ces sources ne contient le marché, le streamer ne s'abonne pas.

## Solutions

### Solution 1 : Vérifier le scan watched_markets

Le `WatchedMarketsService` scanne périodiquement mais peut avoir raté le marché. Vérifier :

```sql
-- Vérifier si le marché devrait être dans watched_markets
SELECT
    sp.market_id,
    sp.condition_id,
    sp.title,
    COUNT(DISTINCT u.telegram_user_id) as user_count
FROM subsquid_markets_poll sp
LEFT JOIN transactions t ON t.market_id = sp.condition_id
LEFT JOIN users u ON t.user_id = u.telegram_user_id
WHERE sp.market_id = '665974'
GROUP BY sp.market_id, sp.condition_id, sp.title;
```

### Solution 2 : Forcer l'ajout manuel à watched_markets

```sql
-- Ajouter manuellement le marché à watched_markets
INSERT INTO watched_markets (
    market_id,
    condition_id,
    title,
    active_positions,
    last_position_at,
    created_at,
    updated_at
)
VALUES (
    '0xb1d1305a0b81a27413068148539ef8d15d427cc835a70cb4ba78238ce4f6cca7',  -- condition_id
    '0xb1d1305a0b81a27413068148539ef8d15d427cc835a70cb4ba78238ce4f6cca7',  -- condition_id
    'Bitcoin Up or Down - November 5, 8:00AM-8:15AM ET',
    1,  -- au moins 1 position active
    NOW(),
    NOW(),
    NOW()
)
ON CONFLICT (market_id) DO UPDATE SET
    active_positions = GREATEST(watched_markets.active_positions, 1),
    last_position_at = NOW(),
    updated_at = NOW();
```

### Solution 3 : Améliorer la détection automatique

Le problème peut venir du fait que :
1. Le scan `watched_markets` ne détecte pas toutes les positions
2. Le JOIN dans `get_market_token_ids()` utilise `t.market_id = sp.condition_id` mais `transactions.market_id` pourrait être au format court

**Fix proposé** : Vérifier le format de `transactions.market_id` :

```sql
-- Vérifier le format des market_id dans transactions
SELECT DISTINCT
    t.market_id as tx_market_id,
    sp.market_id as poll_market_id,
    sp.condition_id as poll_condition_id,
    CASE
        WHEN t.market_id = sp.condition_id THEN 'condition_id'
        WHEN t.market_id = sp.market_id THEN 'short_id'
        ELSE 'no_match'
    END as match_type
FROM transactions t
LEFT JOIN subsquid_markets_poll sp ON (
    t.market_id = sp.condition_id OR t.market_id = sp.market_id
)
WHERE t.executed_at > NOW() - INTERVAL '7 days'
LIMIT 20;
```

### Solution 4 : Ajouter une source de fallback dans get_market_token_ids()

Modifier `apps/subsquid-silo-tests/data-ingestion/src/db/client.py` pour ajouter une query qui détecte les marchés actifs même sans transactions :

```python
# Dans get_market_token_ids(), ajouter une 5ème source :
# Marchés actifs récents (basés sur updated_at dans subsquid_markets_poll)
recent_active_query = """
    SELECT DISTINCT sp.market_id, sp.clob_token_ids
    FROM subsquid_markets_poll sp
    WHERE sp.updated_at > NOW() - INTERVAL '1 hour'
        AND sp.status = 'ACTIVE'
        AND sp.tradeable = true
        AND sp.accepting_orders = true
        AND sp.clob_token_ids IS NOT NULL
        AND sp.clob_token_ids != ''
    ORDER BY sp.volume_24hr DESC NULLS LAST
    LIMIT 100
"""
```

## Vérification immédiate

### 1. Vérifier si le streamer tourne et reçoit des messages

Regarder les logs du streamer :
```bash
# Logs attendus toutes les 60s :
🔄 Subscription refresh: XXX total markets | +X | -X
```

### 2. Vérifier les abonnements actuels

Le streamer devrait logger les tokens auxquels il s'abonne :
```
✅ Subscribed to CLOB Market Channel with XXX asset IDs
```

### 3. Vérifier si le marché est streamé ailleurs

```sql
-- Vérifier si le marché apparaît dans subsquid_markets_ws (même ancien)
SELECT * FROM subsquid_markets_ws
WHERE market_id = '665974';
```

## Fix immédiat recommandé

**Option A : Ajout manuel temporaire**
```sql
INSERT INTO watched_markets (market_id, condition_id, title, active_positions, last_position_at)
VALUES (
    '0xb1d1305a0b81a27413068148539ef8d15d427cc835a70cb4ba78238ce4f6cca7',
    '0xb1d1305a0b81a27413068148539ef8d15d427cc835a70cb4ba78238ce4f6cca7',
    'Bitcoin Up or Down - November 5, 8:00AM-8:15AM ET',
    1,
    NOW()
)
ON CONFLICT (market_id) DO UPDATE SET active_positions = 1, last_position_at = NOW();
```

**Option B : Trigger manuel du refresh**
```python
# Dans le bot, forcer le refresh du streamer
redis_client.setex("streamer:watched_markets_changed", 60, "1")
```

**Option C : Forcer le scan watched_markets**
```python
# Appeler manuellement le service
from core.services.watched_markets_service import get_watched_markets_service
service = get_watched_markets_service()
await service.scan_and_update_watched_markets()
```

## Vérification post-fix

Après avoir ajouté le marché à `watched_markets` :

1. Attendre le refresh du streamer (60s max)
2. Vérifier les logs :
   ```
   🔄 Subscription refresh: XXX total markets | +1 | -0
   ```
3. Vérifier que les prix arrivent dans `subsquid_markets_ws` :
   ```sql
   SELECT * FROM subsquid_markets_ws
   WHERE market_id = '665974'
   ORDER BY updated_at DESC;
   ```
4. Tester la récupération du prix :
   ```python
   PriceCalculator.get_live_price_from_subsquid_ws(
       '0xb1d1305a0b81a27413068148539ef8d15d427cc835a70cb4ba78238ce4f6cca7',
       'down'
   )
   ```

## Améliorations long terme

1. **Détection automatique améliorée** : Scanner les positions blockchain directement via API Polymarket plutôt que seulement via `transactions`
2. **Fallback actif** : Ajouter les marchés actifs récents même sans positions utilisateurs
3. **Monitoring** : Logger quand un marché devrait être streamé mais ne l'est pas
4. **Alerting** : Notifier quand `watched_markets` n'est pas à jour
