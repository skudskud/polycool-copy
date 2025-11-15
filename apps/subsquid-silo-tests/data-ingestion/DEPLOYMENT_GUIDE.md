# Déploiement Poller Optimisé - Guide Complet

## 📋 Pré-requis

- [x] Migration DB exécutée (colonnes créées)
- [x] Code modifié et testé (linting OK)
- [ ] Scripts de backfill prêts
- [ ] Railway CLI configuré

## 🚀 Étapes de Déploiement

### Étape 1: Backfill Events Corruption (Local)

**Objectif:** Nettoyer les 2,089 events corrompus avant le nouveau poller

```bash
cd apps/subsquid-silo-tests/data-ingestion

# Set DATABASE_URL
export DATABASE_URL="postgresql://postgres.fkksycggxaaohlfdwfle:YOUR_PASSWORD@aws-0-us-west-1.pooler.supabase.com:6543/postgres"

# Run fix script
python scripts/fix_events_corruption.py
```

**Durée estimée:** 2-3 minutes
**Résultat attendu:**
```
✅ SUMMARY:
  - Fixed via JSON parsing: ~1500
  - Corrupted beyond repair: ~200
  - Reset to []: ~389
  - Total processed: 2089
```

---

### Étape 2: Backfill Polymarket URLs (Local)

**Objectif:** Générer URLs pour ~50k marchés existants

```bash
# Run URL backfill
python scripts/backfill_polymarket_urls.py
```

**Durée estimée:** 5-10 minutes (batching par 100)
**Résultat attendu:**
```
✅ SUMMARY:
  - Total updated: ~50,000
  - Event URLs: ~30,000
  - Market URLs: ~20,000
  - No slug available: ~500
```

---

### Étape 3: Deploy Nouveau Poller (Railway)

**Option A: Auto-deploy (si Railway watch activé)**

```bash
# Commit changes
git add .
git commit -m "feat(poller): simplify to 3 passes + add resolution tracking

- Remove PASS 1.5, 2.5, 2.75 (code cleanup)
- Add resolution_status, winning_outcome tracking
- Add polymarket_url generation
- Remove aggressive filters (date, price extremes)
- Fix events field preservation

BREAKING: None (backward compatible)
"

git push origin main
```

**Option B: Manual deploy**

```bash
cd apps/subsquid-silo-tests/data-ingestion

# Deploy to Railway
railway up -s poller

# Vérifier déploiement
railway status -s poller
```

---

### Étape 4: Monitoring Initial (15 min)

**Watch logs en temps réel:**

```bash
railway logs -s poller --follow
```

**Chercher dans les logs:**

✅ **Success indicators:**
```
✅ Poller service starting...
✅ [CYCLE #1] Total upserted: X in Ys
📊 [PASS 1] X events → Y markets
📊 [PASS 2] Updated X/Y existing markets
✅ [PASS 3] Updated X markets
🛡️ [EVENTS PRESERVATION] PASS 2: X markets preserved
```

❌ **Error indicators:**
```
❌ Poll cycle error
❌ Upsert failed
❌ Failed to connect
```

---

### Étape 5: Validation DB (après 1 cycle)

**Vérifier que les nouveaux champs sont remplis:**

```sql
-- Check resolution tracking
SELECT
    resolution_status,
    COUNT(*) as count,
    SUM(volume) as volume
FROM subsquid_markets_poll
GROUP BY resolution_status;

-- Expected:
-- PENDING: ~50,000 (majorité)
-- PROPOSED: quelques dizaines (markets juste expirés)
-- RESOLVED: quelques centaines (markets avec outcome)
```

```sql
-- Check URL generation
SELECT
    COUNT(*) FILTER (WHERE polymarket_url LIKE 'https://polymarket.com/%') as has_url,
    COUNT(*) FILTER (WHERE polymarket_url IS NULL OR polymarket_url = '') as missing_url
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';

-- Expected:
-- has_url: >90% des ACTIVE
-- missing_url: <10%
```

---

### Étape 6: Validation Fonctionnelle (après 1h)

**Test markets spécifiques:**

```sql
-- Government shutdown: doit être ACTIVE
SELECT market_id, title, status, resolution_status
FROM subsquid_markets_poll
WHERE market_id = '623600';
-- Expected: ACTIVE, PENDING

-- Lewis Hamilton: doit avoir winning_outcome après 1h
SELECT market_id, status, resolution_status, winning_outcome
FROM subsquid_markets_poll
WHERE market_id = '525361';
-- Expected: CLOSED, RESOLVED, 0

-- Bitcoin Up/Down expiré: doit passer à RESOLVED
SELECT market_id, title, status, resolution_status, winning_outcome, end_date
FROM subsquid_markets_poll
WHERE title LIKE '%Bitcoin Up or Down%'
  AND end_date < NOW() - INTERVAL '2 hours'
ORDER BY end_date DESC
LIMIT 3;
-- Expected: CLOSED, RESOLVED, 0 ou 1
```

---

### Étape 7: Performance Check

**Vérifier que le poller ne surcharge pas:**

```bash
# Check Railway metrics
railway metrics -s poller

# Vérifier:
# - CPU: <50%
# - Memory: <512MB
# - Network: Pas de spike anormal
```

**Check DB load (Supabase):**
- Aller sur Supabase Dashboard
- Section "Database" > "Query Performance"
- Vérifier pas de slow queries (>1s)

---

### Étape 8: Enable Redeem Bot (si validation OK)

Une fois que le tracking de résolution fonctionne (après 24h):

```python
# Dans le bot Telegram, ajouter commande /check_redeem
async def check_redeem_positions(user_id: int):
    """Check positions ready for redeem"""

    query = """
        SELECT
            rp.market_id,
            mp.title,
            rp.outcome,
            mp.winning_outcome,
            rp.tokens_held,
            CASE
                WHEN (rp.outcome = 'YES' AND mp.winning_outcome = 1) OR
                     (rp.outcome = 'NO' AND mp.winning_outcome = 0)
                THEN rp.tokens_held * 1.0
                ELSE 0
            END as payout,
            mp.polymarket_url
        FROM resolved_positions rp
        JOIN subsquid_markets_poll mp ON rp.market_id = mp.market_id
        WHERE rp.user_id = $1
          AND rp.status = 'PENDING'
          AND mp.resolution_status = 'RESOLVED'
    """

    positions = await db.fetch(query, user_id)

    # Send notification to user
    for pos in positions:
        if pos['payout'] > 0:
            await send_message(
                user_id,
                f"🎉 You WON ${pos['payout']:.2f} on '{pos['title']}'!\n"
                f"Click to redeem: {pos['polymarket_url']}"
            )
```

---

## 🔥 Rollback Procedure

**Si problème critique détecté:**

### 1. Rollback Code (Instant)

```bash
# Rollback poller
cd apps/subsquid-silo-tests/data-ingestion
git checkout HEAD~1 -- src/polling/poller.py src/db/client.py

# Rollback market_data_layer
cd telegram-bot-v2/py-clob-server
git checkout HEAD~1 -- core/services/market_data_layer.py

# Redeploy
railway up -s poller
```

### 2. État après Rollback

- ✅ Code revient à l'ancienne version (6 passes)
- ✅ DB colonnes restent (pas de breaking change)
- ✅ `resolution_status` reste à 'PENDING' (ignoré par ancien code)
- ✅ Bot fonctionne normalement

### 3. Investigation

Si rollback nécessaire:
- Checker logs Railway pour erreur
- Checker Supabase metrics pour DB overload
- Ouvrir issue GitHub avec logs + query stats

---

## 📊 Success Metrics (après 24h)

### Coverage:
- [ ] >95% des ACTIVE markets updated dans dernière heure
- [ ] >8,500 ACTIVE markets (vs 8,827 actuellement)
- [ ] <5% stale markets (>6h old)

### Resolution Tracking:
- [ ] >100 markets avec resolution_status=RESOLVED
- [ ] >50 markets avec winning_outcome défini
- [ ] 0 markets avec RESOLVED mais winning_outcome=NULL

### Events & URLs:
- [ ] <100 events corrompus (vs 2,089 avant)
- [ ] >90% ACTIVE markets ont polymarket_url
- [ ] 0 erreurs de parsing events dans logs

### Performance:
- [ ] Cycle time <30s (vs ~45s avant)
- [ ] CPU Railway <50%
- [ ] Memory <512MB
- [ ] 0 DB timeout errors

---

## 🆘 Troubleshooting

### Problème: "No markets upserted"

```bash
# Check si poller est enabled
railway vars -s poller | grep POLLER_ENABLED

# Check DATABASE_URL
railway vars -s poller | grep DATABASE_URL

# Check logs pour erreurs
railway logs -s poller | grep "❌"
```

### Problème: "Events still corrupted"

```bash
# Re-run fix script
python scripts/fix_events_corruption.py

# Validate
python -c "
import asyncio
from scripts.fix_events_corruption import validate_events_field
asyncio.run(validate_events_field())
"
```

### Problème: "Markets missing URLs"

```bash
# Re-run backfill
python scripts/backfill_polymarket_urls.py
```

### Problème: "Too many ACTIVE markets"

C'est normal! Les filtres ont été supprimés pour avoir 100% coverage.

Si vraiment trop de charge:
- Augmenter `POLL_MS` de 60s à 120s
- Réduire `max_pages` dans PASS 1 et 2

---

## 📞 Support

**Logs Railway:**
```bash
railway logs -s poller --lines 1000 > poller_logs.txt
```

**DB Stats:**
```sql
-- Export pour debugging
COPY (
    SELECT status, resolution_status, COUNT(*), SUM(volume)
    FROM subsquid_markets_poll
    GROUP BY status, resolution_status
) TO '/tmp/market_stats.csv' CSV HEADER;
```

**Contact:** Ulysse (owner)

---

**Date:** Nov 3, 2025
**Version:** v2.0 (Simplified Poller)
**Status:** ✅ Ready for Production
