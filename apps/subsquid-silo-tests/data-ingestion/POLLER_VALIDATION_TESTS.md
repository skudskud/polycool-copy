# Poller Validation Tests

Tests à effectuer après déploiement pour valider que le nouveau poller fonctionne correctement.

## Test 1: Government Shutdown Market (623600)

**Objectif:** Vérifier que ce marché reste ACTIVE malgré la suppression des filtres

```sql
SELECT
    market_id,
    title,
    status,
    resolution_status,
    winning_outcome,
    end_date,
    outcome_prices,
    polymarket_url,
    updated_at
FROM subsquid_markets_poll
WHERE market_id = '623600';
```

**Attendu:**
- `status = 'ACTIVE'`
- `resolution_status = 'PENDING'`
- `winning_outcome = NULL`
- `end_date` future (2025-11-15)
- `outcome_prices` non-vides
- `polymarket_url` commence par `https://polymarket.com/`

---

## Test 2: Bitcoin Up/Down Markets (Catégorie 2)

**Objectif:** Vérifier le tracking de résolution pour markets expirés

```sql
-- Find recently expired Bitcoin Up/Down markets
SELECT
    market_id,
    title,
    status,
    resolution_status,
    winning_outcome,
    end_date,
    resolution_date,
    NOW() - end_date as time_since_expiry,
    outcome_prices,
    polymarket_url
FROM subsquid_markets_poll
WHERE title LIKE '%Bitcoin Up or Down%'
  AND end_date < NOW()
  AND end_date > NOW() - INTERVAL '6 hours'
ORDER BY end_date DESC
LIMIT 5;
```

**Attendu (progression temporelle):**

**Étape 1 (juste après expiration < 1h):**
- `status = 'CLOSED'`
- `resolution_status = 'PROPOSED'`
- `winning_outcome = NULL` (pas encore dispo)

**Étape 2 (après > 1h):**
- `status = 'CLOSED'`
- `resolution_status = 'RESOLVED'`
- `winning_outcome = 0 ou 1` (outcome confirmé)
- `resolution_date` rempli

---

## Test 3: Lewis Hamilton F1 (525361) - Catégorie 3

**Objectif:** Vérifier fermeture prématurée avec résolution immédiate

```sql
SELECT
    market_id,
    title,
    status,
    resolution_status,
    winning_outcome,
    end_date,
    resolution_date,
    tradeable,
    accepting_orders,
    events,
    polymarket_url
FROM subsquid_markets_poll
WHERE market_id = '525361';
```

**Attendu:**
- `status = 'CLOSED'`
- `resolution_status = 'RESOLVED'` (outcome immédiatement disponible)
- `winning_outcome = 0` (Hamilton éliminé = "No")
- `end_date` future (2025-12-07)
- `events` contient event F1 Championship
- `polymarket_url` commence par `https://polymarket.com/event/`

---

## Test 4: Black to the Future (654056) - Catégorie 1

**Objectif:** Vérifier ACTIVE malgré tradeable=false

```sql
SELECT
    market_id,
    title,
    status,
    resolution_status,
    tradeable,
    accepting_orders,
    end_date,
    outcome_prices,
    polymarket_url
FROM subsquid_markets_poll
WHERE market_id = '654056';
```

**Attendu:**
- `status = 'ACTIVE'` (même si tradeable=false)
- `resolution_status = 'PENDING'`
- `accepting_orders = true`
- `outcome_prices = [0.735, 0.265]` (non-vides)

---

## Test 5: Events Field Corruption

**Objectif:** Vérifier qu'il n'y a plus de backslashes échappés en cascade

```sql
-- Should return 0 rows
SELECT
    market_id,
    title,
    LEFT(events::text, 200) as events_preview
FROM subsquid_markets_poll
WHERE events::text LIKE '%\\\\\\%'
LIMIT 10;
```

**Attendu:** 0 rows (aucune corruption)

---

## Test 6: Coverage Global

**Objectif:** Vérifier qu'on a bien tous les marchés actifs

```sql
SELECT
    status,
    resolution_status,
    COUNT(*) as count,
    SUM(volume) as total_volume
FROM subsquid_markets_poll
GROUP BY status, resolution_status
ORDER BY count DESC;
```

**Attendu:**
- ACTIVE + PENDING: ~7,500+ markets (majorité)
- CLOSED + RESOLVED: Markets avec outcome disponible
- CLOSED + PROPOSED: Markets fermés en attente d'outcome
- Augmentation du nombre de ACTIVE vs avant (suppression filtres)

---

## Test 7: URL Generation Coverage

**Objectif:** Vérifier que les URLs sont générées

```sql
SELECT
    COUNT(*) FILTER (WHERE polymarket_url LIKE 'https://polymarket.com/event/%') as event_urls,
    COUNT(*) FILTER (WHERE polymarket_url LIKE 'https://polymarket.com/market/%') as market_urls,
    COUNT(*) FILTER (WHERE polymarket_url IS NULL OR polymarket_url = '') as missing_urls,
    COUNT(*) as total
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';
```

**Attendu:**
- `event_urls + market_urls > 90%` du total
- `missing_urls < 10%` (seulement markets sans slug)

---

## Test 8: Redeem Ready Positions

**Objectif:** Tester la query pour le bot redeem

```sql
SELECT
    rp.id,
    rp.market_id,
    rp.outcome,
    mp.winning_outcome,
    mp.resolution_status,
    mp.resolution_date,
    mp.title,
    CASE
        WHEN (rp.outcome = 'YES' AND mp.winning_outcome = 1) OR
             (rp.outcome = 'NO' AND mp.winning_outcome = 0)
        THEN 'WINNER'
        ELSE 'LOSER'
    END as position_status
FROM resolved_positions rp
JOIN subsquid_markets_poll mp ON rp.market_id = mp.market_id
WHERE rp.status = 'PENDING'
  AND mp.resolution_status = 'RESOLVED'
LIMIT 10;
```

**Attendu:** Liste des positions prêtes pour redeem avec indication winner/loser

---

## Test 9: Health Monitoring

**Objectif:** Vérifier que le poller tourne bien et update les marchés

```bash
# Check poller logs sur Railway
railway logs -s poller

# Chercher:
# - "✅ [CYCLE #X] Total upserted: Y"
# - "📊 [PASS 1] X events → Y markets"
# - "📊 [PASS 2] Updated X/Y existing markets"
# - "✅ [PASS 3] Updated X markets"
# - No errors "❌"
```

---

## Test 10: Price Extremes Validation

**Objectif:** Vérifier que les marchés avec prix extrêmes ne sont plus filtrés

```sql
-- Markets with extreme prices (should now be visible)
SELECT
    market_id,
    title,
    outcome_prices,
    volume,
    status,
    polymarket_url
FROM subsquid_markets_poll
WHERE status = 'ACTIVE'
  AND (
    outcome_prices[1] < 0.01 OR outcome_prices[1] > 0.99 OR
    outcome_prices[2] < 0.01 OR outcome_prices[2] > 0.99
  )
ORDER BY volume DESC
LIMIT 10;
```

**Attendu:** Liste de marchés high-confidence avec gros volumes (ex: F1, elections)

---

## Rollback si problème

Si un test échoue:

```bash
# 1. Rollback code poller
cd apps/subsquid-silo-tests/data-ingestion
git checkout HEAD -- src/polling/poller.py src/db/client.py

# 2. Rollback market_data_layer
cd telegram-bot-v2/py-clob-server
git checkout HEAD -- core/services/market_data_layer.py

# 3. Redéployer l'ancienne version
railway up -s poller
```

Les colonnes DB peuvent rester (pas de breaking change).

---

## Success Criteria

✅ Tous les tests passent
✅ Pas d'erreurs dans les logs Railway
✅ Market "Government shutdown" visible
✅ Coverage >95% des marchés actifs
✅ URLs générées pour >90% des marchés
✅ Events field propre (pas de corruption)
