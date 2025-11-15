-- ============================================================================
-- MIGRATION: Cleanup Legacy TP/SL Orders with Invalid Market IDs
-- Date: October 15, 2025
-- Description: Supprime les anciens ordres TP/SL qui utilisent des market_id
--              en format hash (0x...) qui ne correspondent plus à la nouvelle
--              structure de la base de données
-- ============================================================================

-- Avant la migration, afficher les ordres concernés
DO $$
DECLARE
    legacy_count INTEGER;
BEGIN
    SELECT COUNT(*)
    INTO legacy_count
    FROM tpsl_orders
    WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50;

    RAISE NOTICE '🔍 Found % legacy TP/SL orders with hash market_ids', legacy_count;
END $$;

-- Afficher quelques exemples
SELECT
    id,
    user_id,
    market_id,
    outcome,
    status,
    created_at
FROM tpsl_orders
WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50
ORDER BY created_at DESC
LIMIT 10;

-- Optionnel: Archiver les ordres avant suppression
-- CREATE TABLE IF NOT EXISTS tpsl_orders_archive AS
-- SELECT * FROM tpsl_orders WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50;

-- Supprimer les ordres avec market_id en format hash (legacy)
DELETE FROM tpsl_orders
WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50;

-- Afficher le résultat
DO $$
DECLARE
    remaining_count INTEGER;
BEGIN
    SELECT COUNT(*)
    INTO remaining_count
    FROM tpsl_orders;

    RAISE NOTICE '✅ Cleanup complete. Remaining TP/SL orders: %', remaining_count;
END $$;
