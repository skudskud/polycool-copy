# WebSocket Pricing Fix - November 3, 2025

## Problème Identifié

**Écart massif entre les prix WebSocket et Poller:**

Exemple marché 517311 ("Trump deport 250,000-500,000 people?"):
- **Poller (correct):** YES = 0.665, NO = 0.335
- **WebSocket (incorrect):** YES = 0.13-0.70 (valeurs erratiques)

Autres exemples d'écarts:
- Cincinnati Bengals: Poll YES=0.0025 vs WS YES=0.068 (**27x trop élevé!**)
- Carolina Panthers: Poll YES=0.0025 vs WS YES=0.089 (**35x trop élevé!**)
- Michelle Bachelet: Poll YES=0.0005 vs WS YES=0.06 (**120x trop élevé!**)

## Cause Root

**Le streamer WebSocket utilisait le mauvais champ pour les prix:**

1. **Format obsolète:** Le code utilisait `change.get("price")` qui est un champ legacy
2. **Migration Polymarket (Sept 2025):** Polymarket a changé le format des événements `price_change` pour inclure `best_bid` et `best_ask` au lieu d'un seul champ `price`
3. **Calcul incorrect de `last_mid`:** Le code calculait `(YES + NO) / 2` qui est mathématiquement faux pour un marché de prédiction binaire

## Solution Implémentée

### 1. Utilisation du Nouveau Format WebSocket

**Avant:**
```python
price = change.get("price")  # ❌ Format obsolète
price_float = float(price)
```

**Après:**
```python
best_bid = change.get("best_bid")
best_ask = change.get("best_ask")
legacy_price = change.get("price")  # Fallback

if best_bid is not None and best_ask is not None:
    # ✅ Calcul correct depuis bid/ask
    price_float = (float(best_bid) + float(best_ask)) / 2.0
    price_source = f"bid/ask"
elif legacy_price is not None:
    # Fallback pour ancien format
    price_float = float(legacy_price)
    logger.warning("Using legacy price field - consider upgrading")
```

### 2. Suppression du Calcul Incorrect de `last_mid`

**Problème:** `last_mid = (YES_price + NO_price) / 2` est incorrect car:
- YES et NO sont des tokens différents avec leurs propres orderbooks
- Le mid price devrait venir de l'agrégation des orderbooks, pas de la moyenne des tokens
- Les utilisateurs ont besoin des prix YES/NO individuels pour calculer leur PnL

**Action:** Supprimé le calcul de `last_mid` dans tous les handlers:
- `_handle_price_change` (ligne 431-433)
- `_handle_orderbook` (ligne 610-615)
- `_handle_snapshot` (ligne 639-644)
- `_handle_delta` (ligne 678-679)

### 3. Logging Détaillé pour Diagnostic

Ajout de logs pour tracer:
- Format des événements `price_change` reçus
- Source du prix utilisé (bid/ask vs legacy)
- Mapping token_id → outcome
- Prix calculé et sa source

## Impact sur le Bot

**AUCUN IMPACT NÉGATIF** - Le bot n'utilisait déjà pas `last_mid`:

```python
# telegram-bot-v2/py-clob-server/telegram_bot/services/price_calculator.py
# Ligne 90-102
if outcome and ws_market.last_yes_price is not None:
    price = float(ws_market.last_yes_price)  # ✅ Utilise YES/NO directement
    return price
elif outcome and ws_market.last_no_price is not None:
    price = float(ws_market.last_no_price)
    return price

# ❌ REMOVED: Ne fallback plus sur last_mid (ligne 99-103)
# Let the cascade continue to API/Poller instead
```

## Changements de Fichiers

### `apps/subsquid-silo-tests/data-ingestion/src/ws/streamer.py`

1. **Ligne 347:** Ajout logging RAW EVENT
2. **Ligne 386-404:** Nouveau calcul prix depuis `best_bid/best_ask`
3. **Ligne 396-397:** Logging détaillé du mapping token → outcome
4. **Ligne 431-433:** Suppression calcul `last_mid` dans `_handle_price_change`
5. **Ligne 610-615:** Suppression `last_mid` dans `_handle_orderbook`
6. **Ligne 639-644:** Suppression `last_mid` dans `_handle_snapshot`
7. **Ligne 678-679:** Suppression `last_mid` dans `_handle_delta`

## Déploiement

### Étapes:

1. **Railway - Service Streamer:**
   ```bash
   cd apps/subsquid-silo-tests/data-ingestion
   railway up --service streamer
   ```

2. **Vérification logs:**
   - Observer les nouveaux logs `📨 RAW EVENT`
   - Vérifier que `price_source` montre "bid/ask" et pas "legacy"
   - Confirmer que les prix YES/NO sont maintenant cohérents avec le poller

3. **Validation DB:**
   ```sql
   -- Comparer WebSocket vs Poller après le déploiement
   SELECT
       ws.market_id,
       poll.title,
       poll.outcome_prices[1] as poll_yes,
       ws.last_yes_price as ws_yes,
       ABS(poll.outcome_prices[1] - ws.last_yes_price) as diff,
       ws.updated_at
   FROM subsquid_markets_ws ws
   JOIN subsquid_markets_poll poll ON ws.market_id = poll.market_id
   WHERE poll.status = 'ACTIVE'
       AND ws.updated_at > NOW() - INTERVAL '10 minutes'
   ORDER BY diff DESC
   LIMIT 20;
   ```

   **Résultat attendu:** `diff` devrait être < 0.05 (écart < 5%) pour la plupart des marchés liquides.

## Résultats Attendus

**Avant le fix:**
- WebSocket YES prices: Erratiques, parfois 100x trop élevées
- `last_mid`: Toujours 0.5 (inutile)
- Écarts > 50% avec le poller

**Après le fix:**
- WebSocket YES/NO prices: Cohérents avec le poller (écart < 5%)
- `last_mid`: NULL (supprimé, car inutile)
- Calcul PnL des utilisateurs: CORRECT

## Notes Techniques

### Pourquoi le champ `price` était incorrect?

Le champ `price` dans l'ancien format WebSocket représentait peut-être:
- Le last trade price d'un side spécifique (buy ou sell)
- Un prix instantané non représentatif
- Un prix d'un seul order, pas le best bid/ask

### Pourquoi best_bid/best_ask est correct?

- **best_bid:** Le meilleur prix auquel quelqu'un veut ACHETER ce token
- **best_ask:** Le meilleur prix auquel quelqu'un veut VENDRE ce token
- **Mid price:** `(best_bid + best_ask) / 2` = Prix d'équilibre du marché

C'est la méthode standard pour calculer le prix d'un asset sur un orderbook.

## Références

- Polymarket CLOB WebSocket Migration Guide (Sept 2025)
- Issue identifiée: Market 517311 avec prix erratiques
- Diagnostic complet dans `/f.plan.md`
