-- ============================================================================
-- Script de Rétention pour subsquid_user_transactions_v2
-- Limite automatique des transactions en base
-- ============================================================================

-- 1. Fonction de nettoyage automatique
-- Garde seulement les transactions des derniers X jours
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_old_user_transactions(retention_days INTEGER DEFAULT 7)
RETURNS TABLE(
    deleted_count BIGINT,
    oldest_kept TIMESTAMP WITH TIME ZONE,
    execution_time_ms NUMERIC
)
LANGUAGE plpgsql
AS $$
DECLARE
    start_time TIMESTAMP;
    end_time TIMESTAMP;
    rows_deleted BIGINT;
    cutoff_date TIMESTAMP WITH TIME ZONE;
BEGIN
    start_time := clock_timestamp();
    cutoff_date := NOW() - (retention_days || ' days')::INTERVAL;

    -- Log début
    RAISE NOTICE 'Starting cleanup: deleting transactions older than %', cutoff_date;

    -- Supprimer les vieilles transactions
    DELETE FROM subsquid_user_transactions_v2
    WHERE timestamp < cutoff_date;

    GET DIAGNOSTICS rows_deleted = ROW_COUNT;

    end_time := clock_timestamp();

    -- Log résultat
    RAISE NOTICE 'Cleanup complete: % rows deleted in % ms',
        rows_deleted,
        EXTRACT(MILLISECONDS FROM (end_time - start_time));

    -- Retourner les stats
    RETURN QUERY
    SELECT
        rows_deleted,
        (SELECT MIN(timestamp) FROM subsquid_user_transactions_v2) as oldest_kept,
        EXTRACT(MILLISECONDS FROM (end_time - start_time))::NUMERIC as execution_time_ms;
END;
$$;

-- ============================================================================
-- 2. Fonction de stats pour monitoring
-- ============================================================================

CREATE OR REPLACE FUNCTION get_user_transactions_stats()
RETURNS TABLE(
    total_rows BIGINT,
    oldest_transaction TIMESTAMP WITH TIME ZONE,
    newest_transaction TIMESTAMP WITH TIME ZONE,
    size_mb NUMERIC,
    avg_transactions_per_day NUMERIC
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        COUNT(*)::BIGINT as total_rows,
        MIN(timestamp) as oldest_transaction,
        MAX(timestamp) as newest_transaction,
        pg_total_relation_size('subsquid_user_transactions_v2')::NUMERIC / (1024 * 1024) as size_mb,
        CASE
            WHEN MIN(timestamp) IS NOT NULL AND MAX(timestamp) IS NOT NULL
            THEN COUNT(*)::NUMERIC / GREATEST(EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) / 86400, 1)
            ELSE 0
        END as avg_transactions_per_day
    FROM subsquid_user_transactions_v2;
$$;

-- ============================================================================
-- 3. Vue pour monitoring quotidien
-- ============================================================================

CREATE OR REPLACE VIEW v_transactions_daily_stats AS
SELECT
    DATE(timestamp) as date,
    COUNT(*) as transaction_count,
    COUNT(DISTINCT user_address) as unique_addresses,
    COUNT(DISTINCT market_id) as unique_markets,
    COUNT(*) FILTER (WHERE tx_type = 'BUY') as buy_count,
    COUNT(*) FILTER (WHERE tx_type = 'SELL') as sell_count,
    MIN(timestamp) as first_tx,
    MAX(timestamp) as last_tx
FROM subsquid_user_transactions_v2
GROUP BY DATE(timestamp)
ORDER BY date DESC;

-- ============================================================================
-- 4. Index pour optimiser le nettoyage
-- ============================================================================

-- Index sur timestamp pour accélérer les DELETE par date
CREATE INDEX IF NOT EXISTS idx_subsquid_user_tx_v2_timestamp_cleanup
ON subsquid_user_transactions_v2(timestamp)
WHERE timestamp < NOW() - INTERVAL '1 day';

-- ============================================================================
-- 5. Configuration pg_cron (si disponible sur Supabase)
-- ============================================================================

-- Activer pg_cron (nécessite droits admin Supabase)
-- CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Nettoyer tous les jours à 3h du matin (garder 7 jours)
-- SELECT cron.schedule(
--     'cleanup-old-user-transactions',
--     '0 3 * * *',  -- Tous les jours à 3h AM
--     $$SELECT cleanup_old_user_transactions(7)$$
-- );

-- ============================================================================
-- 6. Alternative : Fonction trigger pour limite en temps réel
-- ============================================================================

CREATE OR REPLACE FUNCTION enforce_transaction_retention()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    max_rows INTEGER := 1000000;  -- Limite à 1M de transactions
    current_count BIGINT;
BEGIN
    -- Vérifier le compte toutes les 10000 insertions
    IF (random() < 0.0001) THEN  -- 0.01% de chance = ~1 fois par 10k inserts
        SELECT COUNT(*) INTO current_count FROM subsquid_user_transactions_v2;

        IF current_count > max_rows THEN
            RAISE NOTICE 'Transaction limit reached (%), triggering cleanup', current_count;

            -- Supprimer les plus vieilles transactions pour revenir à 90% de la limite
            DELETE FROM subsquid_user_transactions_v2
            WHERE id IN (
                SELECT id
                FROM subsquid_user_transactions_v2
                ORDER BY timestamp ASC
                LIMIT (current_count - (max_rows * 0.9))::INTEGER
            );
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

-- Créer le trigger (DÉSACTIVÉ par défaut car peut ralentir les inserts)
-- CREATE TRIGGER trigger_enforce_retention
-- AFTER INSERT ON subsquid_user_transactions_v2
-- FOR EACH ROW
-- EXECUTE FUNCTION enforce_transaction_retention();

-- ============================================================================
-- UTILISATION
-- ============================================================================

-- Voir les stats actuelles
-- SELECT * FROM get_user_transactions_stats();

-- Nettoyer manuellement (garder 7 jours)
-- SELECT * FROM cleanup_old_user_transactions(7);

-- Nettoyer manuellement (garder 3 jours)
-- SELECT * FROM cleanup_old_user_transactions(3);

-- Voir stats par jour
-- SELECT * FROM v_transactions_daily_stats LIMIT 30;

-- Compter les transactions à supprimer AVANT de nettoyer
-- SELECT COUNT(*)
-- FROM subsquid_user_transactions_v2
-- WHERE timestamp < NOW() - INTERVAL '7 days';

-- ============================================================================
-- CLEANUP INITIAL (à exécuter une fois)
-- ============================================================================

-- Si vous voulez nettoyer immédiatement, décommentez :
-- SELECT * FROM cleanup_old_user_transactions(7);

-- ============================================================================
-- NOTES
-- ============================================================================
--
-- 1. Par défaut, garde 7 jours de transactions
-- 2. Pour copy trading, 7 jours suffit (filter service copie vers tracked_leader_trades)
-- 3. pg_cron nécessite extension Supabase (contactez support si pas dispo)
-- 4. Alternative : Cloudflare Workers cron qui appelle cette fonction via API
-- 5. Monitorer avec : SELECT * FROM v_transactions_daily_stats;
