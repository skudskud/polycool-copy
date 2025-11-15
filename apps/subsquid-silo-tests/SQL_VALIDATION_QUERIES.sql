-- ===============================
-- VALIDATION DES CORRECTIONS
-- Requêtes pour vérifier avant/après
-- ===============================

-- 1️⃣ AVANT: Marchés ACTIVE avec end_date expirée (INCORRECT)
-- Résultat attendu AVANT correction: Beaucoup de marchés
SELECT
  COUNT(*) as markets_incorrectly_active,
  MIN(end_date) as oldest_end_date,
  MAX(end_date) as newest_end_date,
  COUNT(*) FILTER (WHERE end_date < NOW()) as expired_markets
FROM subsquid_markets_poll
WHERE status = 'ACTIVE' AND end_date IS NOT NULL AND end_date < NOW();

-- 2️⃣ Marchés anciens (>1 an) sans end_date marqués ACTIVE
-- Ces marchés devraient être CLOSED après le fix
SELECT
  COUNT(*) as ancient_markets_without_end_date,
  MIN(created_at) as oldest_created_at,
  MAX(created_at) as newest_created_at
FROM subsquid_markets_poll
WHERE status = 'ACTIVE'
  AND end_date IS NULL
  AND created_at < NOW() - INTERVAL '365 days';

-- 3️⃣ Outcome prices INVALIDES (placeholders [0,1] ou [1,0])
-- À VÉRIFIER APRÈS correction: Devrait être vide ou très faible
SELECT
  COUNT(*) as invalid_outcome_prices,
  COUNT(*) FILTER (WHERE outcome_prices::text = '[0, 1]') as placeholder_0_1,
  COUNT(*) FILTER (WHERE outcome_prices::text = '[1, 0]') as placeholder_1_0,
  COUNT(*) FILTER (WHERE outcome_prices::text = '[0.0, 1.0]') as placeholder_0_1_float,
  COUNT(*) FILTER (WHERE outcome_prices::text = '[1.0, 0.0]') as placeholder_1_0_float
FROM subsquid_markets_poll
WHERE outcome_prices IS NOT NULL;

-- 4️⃣ Marchés avec outcome_prices invalides (somme ≠ 1.0)
-- À corriger: Les prix doivent additionner ≈ 1.0
SELECT
  market_id,
  title,
  status,
  outcome_prices,
  (outcome_prices[0] + outcome_prices[1]) as price_sum
FROM subsquid_markets_poll
WHERE outcome_prices IS NOT NULL
  AND array_length(outcome_prices, 1) >= 2
  AND ABS((outcome_prices[0] + outcome_prices[1]) - 1.0) > 0.01
LIMIT 10;

-- 5️⃣ STATISTIQUES: État des marchés AVANT correction
SELECT
  'BEFORE FIX' as phase,
  COUNT(*) FILTER (WHERE status = 'ACTIVE') as active_markets,
  COUNT(*) FILTER (WHERE status = 'CLOSED') as closed_markets,
  COUNT(*) FILTER (WHERE status = 'ACTIVE' AND end_date IS NOT NULL AND end_date < NOW()) as active_but_expired,
  COUNT(*) FILTER (WHERE accepting_orders = true) as accepting_orders_count,
  COUNT(*) FILTER (WHERE tradeable = true) as tradeable_count
FROM subsquid_markets_poll;

-- 6️⃣ Vérifier les marchés 2025 (devraient être correctement ACTIVE)
SELECT
  COUNT(*) as markets_2025,
  COUNT(*) FILTER (WHERE status = 'ACTIVE') as active_2025,
  COUNT(*) FILTER (WHERE status = 'CLOSED') as closed_2025,
  COUNT(*) FILTER (WHERE accepting_orders = true) as accepting_2025,
  COUNT(*) FILTER (WHERE tradeable = true) as tradeable_2025,
  COUNT(*) FILTER (WHERE outcome_prices IS NOT NULL AND array_length(outcome_prices, 1) >= 2) as with_prices
FROM subsquid_markets_poll
WHERE EXTRACT(YEAR FROM created_at) = 2025;

-- 7️⃣ Distribution des marchés par année
SELECT
  EXTRACT(YEAR FROM created_at) as year,
  COUNT(*) as total_markets,
  COUNT(*) FILTER (WHERE status = 'ACTIVE') as active_markets,
  COUNT(*) FILTER (WHERE status = 'CLOSED') as closed_markets,
  COUNT(*) FILTER (WHERE status = 'ACTIVE' AND end_date IS NOT NULL AND end_date < NOW()) as active_but_expired_count
FROM subsquid_markets_poll
GROUP BY EXTRACT(YEAR FROM created_at)
ORDER BY year DESC;

-- 8️⃣ Exemple de 10 marchés avec données incohérentes (AVANT)
SELECT
  market_id,
  title,
  status,
  accepting_orders,
  tradeable,
  end_date,
  created_at,
  outcome_prices,
  volume,
  liquidity
FROM subsquid_markets_poll
WHERE status = 'ACTIVE'
  AND (
    (end_date IS NOT NULL AND end_date < NOW())
    OR
    (end_date IS NULL AND created_at < NOW() - INTERVAL '365 days')
  )
ORDER BY created_at DESC
LIMIT 10;

-- 9️⃣ Vérifier les volailles et liquidity des marchés expirés
-- Ces marchés ne devraient pas avoir d'activité importante
SELECT
  market_id,
  title,
  status,
  volume,
  liquidity,
  end_date,
  created_at,
  (NOW() - end_date) as time_since_expiry
FROM subsquid_markets_poll
WHERE end_date IS NOT NULL
  AND end_date < NOW()
  AND status = 'ACTIVE'
ORDER BY time_since_expiry DESC
LIMIT 15;

-- 🔟 Santé générale: Après correction, vérifier
-- Que TOUS les marchés ACTIVE ont:
-- - accepting_orders = true OU end_date > NOW()
-- - tradeable = true OU end_date > NOW()
-- - outcome_prices valides ET non-placeholders
SELECT
  COUNT(*) as total_active,
  COUNT(*) FILTER (WHERE accepting_orders = false) as suspicious_not_accepting,
  COUNT(*) FILTER (WHERE tradeable = false) as suspicious_not_tradeable,
  COUNT(*) FILTER (WHERE outcome_prices IS NULL) as missing_prices,
  COUNT(*) FILTER (WHERE outcome_prices::text IN ('[0, 1]', '[1, 0]', '[0.0, 1.0]', '[1.0, 0.0]')) as placeholder_prices
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';
