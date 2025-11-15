# Migration: Cleanup Legacy TP/SL Orders

**Date:** 15 Octobre 2025
**Type:** Data Cleanup
**Status:** Ready to execute

## Objectif

Supprimer les anciens ordres TP/SL qui utilisent des `market_id` en format hash (`0x...`) qui ne correspondent plus à la nouvelle structure de la base de données.

## Contexte

Lors de la migration vers la nouvelle structure de base de données, les `market_id` ont changé :
- **Ancien format** : Hash long (66 caractères) - ex: `0x2df7bb9bb2d044408af2a3ef947fd1eb7f5a167d7322cdbb410588af4974ab4e`
- **Nouveau format** : ID numérique - ex: `553813`

Les anciens ordres TP/SL utilisent toujours les anciens market_ids qui n'existent plus dans la table `markets`, causant des warnings dans les logs.

## Ordres Concernés

D'après les logs, il y a au moins 4 ordres TP/SL avec des market_ids invalides :
- Order 17: `0x2df7bb9bb2d044408af2a3ef947fd1eb7f5a167d7322cdbb410588af4974ab4e`
- Order 16: `0xabbc12ec87ba973d33b616ef35b93aeeb8fe7d58deb2737ed595cee7c6b18a0c`
- Order 12: `0xf4f51e9e4e8439e32f64dc0e659828af7564f9cbc323d4f7442f2c590a2ea07d`
- Order 10: `0x35ae72ecea68142496d891d6b74c3ea7069e8ac7b066542298691b43d74da891`

## Impact

**Avant Migration:**
```sql
SELECT COUNT(*) FROM tpsl_orders WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50;
-- Expected: ~4 orders
```

**Après Migration:**
```sql
SELECT COUNT(*) FROM tpsl_orders WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50;
-- Expected: 0 orders
```

## Exécution

### Option 1: Avec Railway CLI
```bash
railway login
railway link
railway run psql -f migrations/2025-10-15_cleanup_legacy_tpsl/cleanup_legacy_tpsl_orders.sql
```

### Option 2: Directement avec psql
```bash
export DATABASE_URL="postgresql://..."
psql $DATABASE_URL -f migrations/2025-10-15_cleanup_legacy_tpsl/cleanup_legacy_tpsl_orders.sql
```

### Option 3: Via Python script
```bash
python migrations/2025-10-15_cleanup_legacy_tpsl/run_cleanup.py
```

## Vérification Post-Migration

```sql
-- Vérifier qu'il ne reste plus d'ordres avec market_id hash
SELECT COUNT(*) FROM tpsl_orders WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50;
-- Should return: 0

-- Vérifier les ordres actifs restants
SELECT COUNT(*) FROM tpsl_orders WHERE status = 'active';
-- Should return: nombre d'ordres valides

-- Vérifier les market_ids restants
SELECT DISTINCT market_id FROM tpsl_orders LIMIT 10;
-- Should show numeric IDs only
```

## Rollback

Si besoin de restaurer (non recommandé car les market_ids ne sont plus valides):

```sql
-- Si vous avez archivé:
INSERT INTO tpsl_orders
SELECT * FROM tpsl_orders_archive;
```

## Notes

- ✅ Aucun risque : Les market_ids hash ne correspondent à aucun marché existant
- ✅ Les ordres sont déjà inactifs (les marchés n'existent plus)
- ✅ Nettoyage des logs (plus de warnings)
- ⚠️ Optionnel : Archiver avant suppression si vous voulez conserver l'historique

## Alternatives

### Si vous voulez conserver les ordres pour l'historique:

Au lieu de supprimer, marquer comme `cancelled`:

```sql
UPDATE tpsl_orders
SET
    status = 'cancelled',
    cancelled_at = NOW(),
    cancelled_reason = 'Legacy market_id format - market no longer exists'
WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50;
```
