# Poller Guidelines - Règles à Respecter pour le Futur

## 🎯 Principe Fondamental

**OBJECTIF:** Récupérer 100% des marchés actifs de Polymarket sans filtrage agressif.

**RÈGLE D'OR:** Si un market est `ACTIVE` dans l'API Polymarket, il DOIT être dans notre DB.

---

## 📋 Architecture Obligatoire: 3 Passes

### PASS 1: Fetch /events (Markets Groupés)

**Endpoint:** `GET https://gamma-api.polymarket.com/events`

**Paramètres OBLIGATOIRES:**
```
?closed=false           ← CRITICAL: Seulement events actifs
&order=volume           ← CRITICAL: Pas order=id (problème pagination!)
&ascending=false        ← Plus gros volumes en premier
&limit=200              ← Max par page
&offset={X}             ← Pagination
```

**Pourquoi `order=volume` est CRITIQUE:**

```
❌ BAD: order=id
  - Latest event ID: ~900,000
  - Super Bowl event ID: 23,656
  - Pages nécessaires: ~4,400 pages!
  - Avec max_pages=50 → JAMAIS atteint

✅ GOOD: order=volume
  - Super Bowl: Position #1 (volume $494M)
  - F1 Championship: Position #5
  - NYC Mayor: Position #2
  - Avec max_pages=50 → Tous les gros events couverts
```

**Pagination:**
- `max_pages`: Minimum 100 (mieux: 200)
- `limit`: 200 events par page
- Coverage: ~20,000-40,000 events

**Processing:**
```python
for event in events:
    markets = event.get("markets", [])
    for market in markets:
        # CRITICAL: Enrich avec event parent
        enriched = self._enrich_market_from_event(market, event)

        # enriched['events'] DOIT contenir:
        # [{
        #     "event_id": event.get("id"),
        #     "event_slug": event.get("slug"),
        #     "event_title": event.get("title"),
        #     "event_volume": event.get("volume"),
        #     "event_category": event.get("category")
        # }]
```

---

### PASS 2: Volume-Based Continuous Distribution

**Stratégie:** Prioriser les marchés à fort volume (97% du volume de trading)

**Target:** 900 marchés/minute (15 marchés/seconde)
- **HIGH** (>100K): 700/min (12/cycle) - 97% du volume total
- **MEDIUM** (10K-100K): 180/min (3/cycle) - 2.6% du volume
- **SMALL** (1K-10K): 20/min (1 tous les 3 cycles) - 0.4% du volume

**Endpoint:** `GET https://gamma-api.polymarket.com/markets`

**Méthode:**
```python
# 1. Query DB par tier de volume
tier_ids = db.get_markets_by_volume_tier(min_vol=100000, limit=1200)

# 2. Rotation dans chaque tier
rotation_offset = poll_count % len(tier_ids)
selected_ids = tier_ids[rotation_offset:rotation_offset + 12]

# 3. Fetch via bulk API
markets = fetch_markets_bulk(selected_ids)  # ?id=X,Y,Z&limit=500

# 4. Préservation données DB
for market in markets:
    if market_id in events_by_market:
        enriched['events'] = preserved['events']  # Si non-vide
        enriched['category'] = preserved['category']  # Si manquant
```

**Préservation CRITIQUE:**
- Events et category chargés depuis DB AVANT update
- Overwrite seulement si nouvelles données non-vides
- Utilise CASE statement dans `upsert_markets_poll()` (déjà en place)

**Performance:**
- HIGH volume: Couvert en ~1.6 minutes (vs 2.8h rotation)
- MEDIUM volume: Couvert en ~8 minutes
- Charge API: 76 marchés/cycle (stable, pas de pics)
- Rate limiting: ~2 appels/sec (bien sous limite 20/sec)

**RÈGLE CRITIQUE: Préservation des Events**

```python
# ❌ BAD: Overwrite events avec []
enriched = self._parse_standalone_market(market)
# enriched['events'] = []  ← Écrase les events de PASS 1!

# ✅ GOOD: Préserver events de PASS 1
enriched = self._parse_standalone_market(market)

# Charger events existants depuis DB
events_by_market = load_from_db()

# Ne préserver QUE si events non-vide
if events_by_market[market_id] and len(events_by_market[market_id]) > 0:
    enriched['events'] = events_by_market[market_id]
# Sinon, laisser PASS 1 remplir au prochain cycle
```

**Exclusions:**
- SKIP markets déjà traités dans PASS 1 (`if market_id in exclude_ids: continue`)
- SKIP markets non-existants en DB (`if market_id not in existing_ids: continue`)

---

### PASS 3: Lifecycle + Resolution Detection

**Opérations:**

1. **Mark expired markets as CLOSED:**
```python
UPDATE subsquid_markets_poll
SET status = 'CLOSED',
    resolution_status = 'PROPOSED'
WHERE status = 'ACTIVE'
  AND end_date < NOW() - INTERVAL '1 hour'
```

2. **Detect winning outcomes:**
```python
# Via API field
outcome = market_data.get("outcome")  # "Yes" ou "No"

# Via prix finaux
if outcome_prices == [1.0, 0.0]:
    winning_outcome = 1  # Yes gagne
elif outcome_prices == [0.0, 1.0]:
    winning_outcome = 0  # No gagne
```

3. **Update resolution_status:**
```
PENDING → Market ouvert
PROPOSED → Market fermé, outcome en attente (<1h)
RESOLVED → Outcome confirmé, redeem disponible
```

---

## 🚫 Filtres INTERDITS

### ❌ NE JAMAIS Filtrer Par:

1. **Date de création**
   - Market créé en 2024? → GARDER si ACTIVE
   - Market créé en 2020? → GARDER si ACTIVE

2. **Prix extrêmes**
   - Prix 0.001/0.999? → VALIDE! (high-confidence market)
   - Prix 0.0001/0.9999? → VALIDE! (quasi-certain outcome)
   - Seul filtre OK: prix VIDES (`[]`)

3. **tradeable=false**
   - Market avec `tradeable=false` MAIS `closed=false`? → GARDER comme ACTIVE
   - C'est juste une pause temporaire

4. **Volume minimum**
   - Market avec $0.01 volume? → GARDER si ACTIVE
   - Utilisateurs peuvent avoir des positions dessus!

### ✅ Seuls Filtres Autorisés:

1. **outcome_prices vides**
   ```python
   if not outcome_prices or len(outcome_prices) == 0:
       return False  # Market illiquid/mort
   ```

2. **Status API**
   ```python
   # Respecter le champ "closed" de l'API
   if market.get("closed") == True:
       status = "CLOSED"
   ```

---

## 🔄 Logique de Résolution (3 Catégories)

### Catégorie 1: ACTIVE en pause

**Critères:**
- `end_date` NULL ou future
- `closed = false`
- `tradeable` peut être false (ignoré!)

**Action:**
```python
status = "ACTIVE"
resolution_status = "PENDING"
winning_outcome = None
```

---

### Catégorie 2: Expiré récemment

**Critères:**
- `end_date` passée

**Action (progression temporelle):**

```python
# <1h après expiration
if end_date < now and end_date > (now - 1h):
    status = "CLOSED"
    resolution_status = "PROPOSED"
    winning_outcome = None  # Pas encore dispo

# >1h après expiration
if end_date < (now - 1h):
    status = "CLOSED"
    outcome = extract_winning_outcome(market_data)
    if outcome is not None:
        resolution_status = "RESOLVED"
        winning_outcome = outcome
    else:
        resolution_status = "PROPOSED"
```

---

### Catégorie 3: Fermé prématurément

**Critères:**
- `end_date` future ou NULL
- `closed = true`

**Exemples:**
- Lewis Hamilton F1 (éliminé mathématiquement)
- Market suspendu pour raisons légales

**Action:**
```python
status = "CLOSED"
outcome = extract_winning_outcome(market_data)
if outcome is not None:
    resolution_status = "RESOLVED"
    winning_outcome = outcome
else:
    resolution_status = "PROPOSED"
```

---

## 📊 Champs DB Obligatoires

Tous les markets dans `subsquid_markets_poll` DOIVENT avoir:

### Champs de Base:
- `market_id` (PK)
- `title`
- `status` ("ACTIVE" ou "CLOSED")
- `slug`
- `condition_id`

### Champs de Pricing:
- `outcome_prices` (ARRAY) ← CRITICAL
- `outcomes` (ARRAY)
- `last_mid` (calculated)
- `volume`, `volume_24hr`, `liquidity`

### Champs Temporels:
- `end_date`
- `created_at`
- `updated_at`

### Champs de Résolution (NOUVEAUX):
- `resolution_status` ← CRITICAL pour redeem
- `winning_outcome` ← 0 ou 1
- `resolution_date`

### Champs de Grouping:
- `events` (JSONB array) ← CRITICAL pour UI
- `polymarket_url` ← CRITICAL pour UX

### Champs Techniques:
- `clob_token_ids` (pour trading)
- `tokens` (pour outcome matching)
- `tradeable`, `accepting_orders`

---

## 🏗️ Structure du Champ `events`

### Format OBLIGATOIRE:

```json
[
  {
    "event_id": "23656",
    "event_slug": "super-bowl-champion-2026-731",
    "event_title": "Super Bowl Champion 2026",
    "event_volume": 494341363.56,
    "event_category": "Sports"
  }
]
```

### Cas d'Usage:

**Event groupé (33 markets Super Bowl):**
```json
{
  "market_id": "540236",
  "title": "Will the Tennessee Titans win Super Bowl 2026?",
  "events": [{ "event_title": "Super Bowl Champion 2026", ... }]
}
```

**Market standalone (Xi Jinping):**
```json
{
  "market_id": "551963",
  "title": "Xi Jinping out in 2025?",
  "events": []
}
```

### Affichage Bot:

```python
# market_data_layer.py ligne 826+
def _group_markets_by_events(markets):
    for market in markets:
        events = market.get('events', [])

        # Si events non-vide ET event_title != market title → GROUP
        if events and events[0].get('event_title') != market['title']:
            # Grouper sous event parent
            event_groups[event_id] = {
                'event_title': events[0]['event_title'],
                'markets': [...]  # Tous les markets de l'event
            }
        else:
            # Individual market
            individual_markets.append(market)
```

---

## ⚡ Performance & Rate Limiting

### Pagination Limits:

```python
# PASS 1: /events
max_pages = 200       # Coverage: ~40,000 events
limit = 200           # Events par page
sleep = 0.05s         # Entre pages

# PASS 2: /markets
max_pages = 200       # Coverage: ~40,000 markets
limit = 200           # Markets par page
sleep = 0.05s

# PASS 3: /markets?closed=true
max_pages = 50        # Seulement récents
limit = 200
```

### Rate Limiting:

```python
# Entre pages
await asyncio.sleep(0.05)  # 50ms

# Entre batches enrichment
if batch_num % 10 == 0:
    await asyncio.sleep(0.1)  # 100ms

# Si 429 (rate limited)
await asyncio.sleep(2.0)  # 2 secondes
```

### Timeouts:

```python
httpx.AsyncClient(timeout=30.0)  # 30 secondes
db.execute(timeout=60.0)         # 60 secondes
```

---

## 🐛 Pièges à Éviter

### 1. Pagination par ID au lieu de Volume

```python
# ❌ BAD
url = "/events?order=id&ascending=false"
# → Events récents en premier
# → Gros events (Super Bowl ID 23656) loin dans pagination

# ✅ GOOD
url = "/events?order=volume&ascending=false"
# → Super Bowl position #1
# → F1 position #5
# → Tous les gros events dans 50 premières pages
```

### 2. Préserver events = []

```python
# ❌ BAD
if events_by_market[market_id]:
    preserve_events()
# → events=[] est falsy, donc jamais préservé
# → PASS 1 ne peut jamais fill in!

# ✅ GOOD
if events_by_market[market_id] and len(events_by_market[market_id]) > 0:
    preserve_events()
# → events=[] n'est pas préservé
# → PASS 1 peut fill in au prochain cycle
```

### 3. Filtrer par Date de Création

```python
# ❌ BAD
if created_at < datetime(2025, 8, 1):
    return False  # Exclut markets anciens
# → Exclut Super Bowl, F1, NYC Mayor (créés avant août)

# ✅ GOOD
# Pas de filtre de date!
# Seul critère: market ACTIVE dans API
```

### 4. Filtrer par Prix Extrêmes

```python
# ❌ BAD
if price < 0.01 or price > 0.99:
    return False  # "Invalid price"
# → Exclut 2,318 markets ($1.7B volume!)
# → Ex: Government shutdown 0.004/0.996

# ✅ GOOD
if not outcome_prices or len(outcome_prices) == 0:
    return False  # Seulement si vide
# → Prix extrêmes sont VALIDES (high-confidence markets)
```

### 5. Overwrite events sans Check

```python
# ❌ BAD
enriched = parse_market(market)
enriched['events'] = []  # Écrase toujours!

# ✅ GOOD
enriched = parse_market(market)
# Ne pas toucher à enriched['events']
# Laisser la logique de préservation gérer
```

---

## 📊 Monitoring Obligatoire

### Logs à Surveiller (Railway):

**Chaque cycle DOIT afficher:**
```
✅ [CYCLE #X] Total upserted: Y in Zs
📊 [PASS 1] X events → Y markets
📊 [PASS 2] Updated X/Y existing markets (Z% coverage)
✅ [PASS 3] Updated X markets
```

**Alertes si:**
- ❌ Upsert < 100 markets par cycle (problème API)
- ❌ PASS 2 coverage < 50% (problème pagination)
- ❌ Erreurs "❌" répétées

### Queries de Santé (Quotidiennes):

```sql
-- Check 1: Coverage ACTIVE markets
SELECT
    COUNT(*) as active_count,
    COUNT(*) FILTER (WHERE updated_at > NOW() - INTERVAL '1 hour') as fresh_1h,
    COUNT(*) FILTER (WHERE updated_at > NOW() - INTERVAL '6 hours') as fresh_6h
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';

-- Attendu:
-- active_count: >8,000
-- fresh_1h: >80%
-- fresh_6h: >95%


-- Check 2: Events grouping
SELECT
    COUNT(*) as total_active,
    COUNT(*) FILTER (WHERE jsonb_array_length(events) > 0) as has_events,
    COUNT(*) FILTER (WHERE events = '[]'::jsonb) as standalone
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';

-- Attendu:
-- has_events: ~6,500 (markets groupés)
-- standalone: ~2,500 (markets individuels)


-- Check 3: URLs
SELECT
    COUNT(*) FILTER (WHERE polymarket_url LIKE 'https://polymarket.com/%') as has_url,
    COUNT(*) as total
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';

-- Attendu: has_url = total (100%)


-- Check 4: Resolution tracking
SELECT
    resolution_status,
    COUNT(*),
    SUM(volume)
FROM subsquid_markets_poll
GROUP BY resolution_status;

-- Attendu:
-- PENDING: majorité
-- PROPOSED: quelques dizaines
-- RESOLVED: quelques centaines
```

---

## 🔧 Modifications Futures: Checklist

Avant de modifier le poller, vérifier:

- [ ] Le changement ne filtre PAS de markets ACTIVE
- [ ] Les events ne sont PAS écrasés accidentellement
- [ ] L'ordre de pagination est toujours `order=volume` pour `/events`
- [ ] Les 3 catégories de résolution sont respectées
- [ ] La logique de préservation est intacte
- [ ] Les tests de validation passent (voir POLLER_VALIDATION_TESTS.md)

---

## 📦 Déploiement: Procédure Standard

### Avant Deploy:

```bash
# 1. Tester localement (si possible)
cd apps/subsquid-silo-tests/data-ingestion
export DATABASE_URL="postgresql://..."
python -m src.main  # Test 1 cycle

# 2. Vérifier linting
pylint src/polling/poller.py

# 3. Review changements
git diff src/polling/poller.py
```

### Deploy:

```bash
# Commit avec message descriptif
git add .
git commit -m "feat(poller): [description]

Changes:
- [change 1]
- [change 2]

BREAKING: None/Yes
"

# Push (auto-deploy si Railway watch)
git push origin main

# OU manual deploy
railway up -s poller
```

### Après Deploy (Monitor 1h):

```bash
# Watch logs
railway logs -s poller --follow

# Vérifier coverage (après 5-10 minutes)
# Run queries de santé (ci-dessus)

# Si problème → Rollback
git revert HEAD
railway up -s poller
```

---

## 🆘 Troubleshooting Guide

### Problème: "Markets Super Bowl ont events = []"

**Cause possible:**
1. PASS 1 n'atteint pas l'event (pagination insuffisante)
2. PASS 2 écrase les events

**Solution:**
```bash
# Check logs
railway logs -s poller | grep "PASS 1"
# Chercher: "[PASS 1] X events → Y markets"

# Si Y < 1000 → Problème pagination
# Fix: Augmenter max_pages ou vérifier order=volume
```

**Validation API:**
```bash
curl "https://gamma-api.polymarket.com/events?limit=10&order=volume&ascending=false" \
  | python3 -c "import sys,json; [print(e['title']) for e in json.load(sys.stdin)[:5]]"

# Super Bowl DOIT être dans top 5
```

---

### Problème: "Markets filtrés/manquants"

**Validation:**
```sql
-- Comparer avec API
-- API dit ACTIVE, DB dit absent → Filtre trop agressif

SELECT market_id, title
FROM subsquid_markets_poll
WHERE market_id = '540236';  -- Tennessee Titans

-- Si absent → Check filtres dans _is_market_valid()
```

**Fix:**
- Supprimer tout filtre sauf `outcome_prices` vide
- Vérifier aucun `continue` prématuré dans loops

---

### Problème: "Resolution tracking ne fonctionne pas"

**Validation:**
```sql
-- Markets expirés depuis >1h devraient avoir outcome
SELECT market_id, title, resolution_status, winning_outcome
FROM subsquid_markets_poll
WHERE end_date < NOW() - INTERVAL '2 hours'
  AND status = 'CLOSED'
LIMIT 10;

-- Si winning_outcome = NULL partout → Bug extraction
```

**Fix:**
- Vérifier `_extract_winning_outcome()` fonctionne
- Vérifier API retourne bien le champ "outcome"
- Vérifier prix finaux [1.0, 0.0] détectés

---

## 📚 Documentation de Référence

### Fichiers Importants:

1. **poller.py** - Code principal (3 passes)
2. **db/client.py** - Upsert logic
3. **market_data_layer.py** - Validation markets
4. **POLLER_VALIDATION_TESTS.md** - Tests après deploy
5. **DEPLOYMENT_GUIDE.md** - Procédure déploiement

### API Polymarket:

**Endpoints:**
- `/events` - Events groupés (TOUJOURS order=volume!)
- `/markets` - Markets standalone
- `/markets/{id}` - Market individuel

**Champs clés:**
- `closed` (boolean) - Market fermé?
- `active` → `tradeable` dans DB
- `acceptingOrders` → `accepting_orders` dans DB
- `outcome` - Outcome gagnant si résolu

---

## 🎯 Success Metrics

### Coverage (Quotidien):

- [ ] >8,000 ACTIVE markets
- [ ] >95% fresh (<6h old)
- [ ] 100% URL coverage

### Events (Quotidien):

- [ ] ~6,500 markets avec events groupés
- [ ] 0 events corrompus (backslashes)
- [ ] Super Bowl, F1, NYC Mayor ont events remplis

### Resolution (Quotidien):

- [ ] >100 markets RESOLVED
- [ ] <50 markets PROPOSED depuis >24h (bloqués)
- [ ] 0 markets RESOLVED sans winning_outcome

### Performance:

- [ ] Cycle time <40s
- [ ] CPU Railway <60%
- [ ] Memory <512MB
- [ ] 0 DB timeouts

---

## 🚀 Roadmap Future

### Court Terme (1-2 semaines):

- [ ] Monitor coverage et résolution
- [ ] Activer redeem bot automatique
- [ ] Optimiser pagination si nécessaire

### Moyen Terme (1-2 mois):

- [ ] Ajouter cache Redis pour events (éviter refetch)
- [ ] Incremental updates (seulement markets changed)
- [ ] WebSocket pour résolutions temps réel

### Long Terme (3+ mois):

- [ ] Migration complète vers subsquid_markets_poll
- [ ] Deprecate old markets table
- [ ] Analytics sur résolutions

---

**Version:** 2.0
**Date:** Nov 3, 2025
**Auteur:** Team Polycool
**Status:** ✅ Production Guidelines
