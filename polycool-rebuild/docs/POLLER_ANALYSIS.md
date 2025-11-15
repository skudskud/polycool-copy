# 🔍 Analyse Complète du Poller - Problèmes Identifiés

## 📊 État Actuel de la Base de Données

### Statistiques Globales
- **Total markets**: 11,859
- **Markets résolus**: 0 ❌ **CRITIQUE**
- **Markets expirés non résolus**: 1,379 ❌ **CRITIQUE**
- **Source WebSocket**: 1 (0.008%)
- **Source Poller**: 11,858 (99.99%)

## 🐛 Problèmes Critiques Identifiés

### 1. ❌ PROBLÈME MAJEUR: Résolutions Non Détectées

**Symptôme**: 1,379 marchés expirés mais `is_resolved = false` et `resolved_at = NULL`

**Cause Racine**: La logique de détection de résolution dans `base_poller.py` est trop restrictive:

```282:307:data_ingestion/poller/base_poller.py
def _is_market_really_resolved(self, market: Dict) -> bool:
    """
    Determine if a market is really resolved
    IGNORES 'closed' status - focuses only on resolvedBy + closedTime + winner
    """
    try:
        # Must have resolvedBy
        if not market.get('resolvedBy'):
            return False

        # Must have valid resolution timestamp in the past
        resolved_at = self._parse_resolution_time(market)
        if not resolved_at or resolved_at > datetime.now(timezone.utc):
            return False

        # Must have a determinable winner
        winner = self._calculate_winner(market)
        if not winner:
            return False

        # If resolvedBy exists, closedTime is past, and winner is determined, it's resolved
        # IGNORE 'closed' status - some markets can be resolved without being closed
        return True
    except Exception as e:
        logger.debug(f"Error checking if market {market.get('id')} is resolved: {e}")
        return False
```

**Problèmes**:
1. **Trop restrictif**: Nécessite `resolvedBy`, `closedTime` ET `winner` - beaucoup de marchés résolus n'ont pas ces 3 champs
2. **Filtrage prématuré**: Les marchés résolus sont filtrés AVANT l'upsert (ligne 168), donc jamais mis à jour
3. **Pas de fallback**: Si l'API ne retourne pas `resolvedBy`, le marché n'est jamais marqué comme résolu

**Impact**: Les marchés expirés restent indéfiniment avec `is_resolved = false`, polluant la base de données.

---

### 2. ⚠️ PROBLÈME: Overwriting Entre Passes

**Symptôme**: Seulement 1 marché avec `source = 'ws'` malgré la protection en place

**Protection Actuelle** (dans `base_poller.py`):

```203:233:data_ingestion/poller/base_poller.py
-- CRITICAL: Preserve WebSocket prices if source is 'ws' (WebSocket has priority)
outcome_prices = CASE
    WHEN markets.source = 'ws' THEN markets.outcome_prices
    ELSE EXCLUDED.outcome_prices
END,
-- CRITICAL: Preserve WebSocket last_trade_price if source is 'ws'
last_trade_price = CASE
    WHEN markets.source = 'ws' AND markets.last_trade_price IS NOT NULL
    THEN markets.last_trade_price
    ELSE EXCLUDED.last_trade_price
END,
-- CRITICAL: Preserve WebSocket source (ws > poll priority)
source = CASE
    WHEN markets.source = 'ws' THEN 'ws'
    ELSE 'poll'
END,
```

**Analyse**:
- ✅ La protection SQL est correcte
- ⚠️ Mais le problème vient du **filtrage AVANT l'upsert** (ligne 168)
- ⚠️ Si un marché résolu est filtré, il n'est jamais mis à jour, même s'il devient résolu plus tard

**Impact Modéré**: La protection fonctionne, mais il y a peu de données WebSocket (peut-être normal si peu de positions actives).

---

### 3. ⚠️ PROBLÈME: Résolutions Poller Inefficace

**Code du Resolutions Poller**:

```31:72:data_ingestion/poller/resolutions_poller.py
async def _poll_cycle(self) -> None:
    """Single poll cycle - check for market resolutions"""
    start_time = time()

    try:
        # 1. Get markets that might be resolved (from DB)
        candidate_markets = await self._get_resolution_candidates()

        if not candidate_markets:
            logger.debug("No resolution candidates found")
            return

        # 2. Fetch fresh data from API for candidates
        updated_markets = await self._fetch_markets_for_resolution(candidate_markets)

        if not updated_markets:
            logger.debug("No markets updated from API")
            return

        # 3. Check which ones are actually resolved
        resolved_markets = [m for m in updated_markets if self._is_market_really_resolved(m)]

        if not resolved_markets:
            logger.debug("No newly resolved markets found")
            return

        # 4. Upsert resolved markets
        upserted = await self._upsert_markets(resolved_markets)
```

**Problèmes**:
1. **Filtrage dans `_upsert_markets`**: Même si un marché est détecté comme résolu, il est filtré à la ligne 168 de `base_poller.py` avant l'upsert
2. **Logique circulaire**: Le poller détecte les résolutions, mais `_upsert_markets` les filtre avant de les sauvegarder
3. **Limite de 200 marchés**: Seulement 200 candidats par cycle (15min), donc 1,379 marchés expirés prendraient ~2h à traiter

**Impact Critique**: Les résolutions ne sont jamais sauvegardées car elles sont filtrées avant l'upsert.

---

### 4. ⚠️ PROBLÈME: Logique de Résolution Trop Stricte

**Méthode `_is_market_really_resolved`**:

```282:307:data_ingestion/poller/base_poller.py
def _is_market_really_resolved(self, market: Dict) -> bool:
    """
    Determine if a market is really resolved
    IGNORES 'closed' status - focuses only on resolvedBy + closedTime + winner
    """
    try:
        # Must have resolvedBy
        if not market.get('resolvedBy'):
            return False

        # Must have valid resolution timestamp in the past
        resolved_at = self._parse_resolution_time(market)
        if not resolved_at or resolved_at > datetime.now(timezone.utc):
            return False

        # Must have a determinable winner
        winner = self._calculate_winner(market)
        if not winner:
            return False

        # If resolvedBy exists, closedTime is past, and winner is determined, it's resolved
        # IGNORE 'closed' status - some markets can be resolved without being closed
        return True
    except Exception as e:
        logger.debug(f"Error checking if market {market.get('id')} is resolved: {e}")
        return False
```

**Problèmes**:
1. **Nécessite 3 conditions**: `resolvedBy` + `closedTime` passé + `winner` déterminable
2. **Pas de fallback**: Si l'API ne retourne pas ces champs, le marché n'est jamais résolu
3. **Ignorer `closed`**: Le commentaire dit d'ignorer `closed`, mais beaucoup de marchés Polymarket utilisent `closed: true` pour indiquer la résolution

**Recommandation**: Ajouter des fallbacks:
- Si `closed: true` ET `end_date < now()` → considérer comme résolu
- Si `end_date < now()` ET prix stables (0.0 ou 1.0) → considérer comme résolu
- Si `resolvedBy` existe → toujours considérer comme résolu (même sans `closedTime`)

---

## 🔧 Solutions Proposées

### Solution 1: Corriger le Filtrage des Résolutions

**Problème**: Les marchés résolus sont filtrés AVANT l'upsert, donc jamais mis à jour.

**Fix**: Modifier `_upsert_markets` pour permettre l'upsert des résolutions:

```python
async def _upsert_markets(self, markets: List[Dict], allow_resolved: bool = False) -> int:
    """
    Upsert markets to unified table
    Shared upsert logic for all poller types

    Args:
        markets: List of market dicts
        allow_resolved: If True, allow upserting resolved markets (for resolutions poller)
    """
    upserted_count = 0
    from core.database.connection import get_db

    # Filter out resolved markets - we stop polling them once resolved
    # UNLESS allow_resolved=True (for resolutions poller)
    if allow_resolved:
        active_markets = markets
    else:
        active_markets = [m for m in markets if not self._is_market_really_resolved(m)]

    if len(active_markets) < len(markets):
        logger.debug(f"Filtered out {len(markets) - len(active_markets)} resolved markets")

    # ... rest of the code
```

**Dans `resolutions_poller.py`**:
```python
# 4. Upsert resolved markets (ALLOW RESOLVED)
upserted = await self._upsert_markets(resolved_markets, allow_resolved=True)
```

---

### Solution 2: Améliorer la Détection de Résolution

**Fix**: Ajouter des fallbacks dans `_is_market_really_resolved`:

```python
def _is_market_really_resolved(self, market: Dict) -> bool:
    """
    Determine if a market is really resolved
    Multiple strategies with fallbacks
    """
    try:
        # Strategy 1: Explicit resolution (resolvedBy + closedTime + winner)
        if market.get('resolvedBy'):
            resolved_at = self._parse_resolution_time(market)
            if resolved_at and resolved_at <= datetime.now(timezone.utc):
                winner = self._calculate_winner(market)
                if winner:
                    return True

        # Strategy 2: Closed status + expired end_date
        if market.get('closed') and market.get('endDate'):
            end_date = self._parse_date(market.get('endDate'))
            if end_date and end_date < datetime.now(timezone.utc):
                # Check if prices indicate resolution (0.0 or 1.0)
                outcome_prices = safe_json_parse(market.get('outcomePrices')) or []
                if outcome_prices:
                    # If any price is 1.0 or 0.0, market is likely resolved
                    if any(float(p) == 1.0 or float(p) == 0.0 for p in outcome_prices if p is not None):
                        return True

        # Strategy 3: Expired end_date + stable prices (0.0 or 1.0)
        if market.get('endDate'):
            end_date = self._parse_date(market.get('endDate'))
            if end_date and end_date < datetime.now(timezone.utc):
                outcome_prices = safe_json_parse(market.get('outcomePrices')) or []
                if outcome_prices:
                    # Check if prices are at extremes (resolved)
                    prices = [float(p) for p in outcome_prices if p is not None]
                    if prices and (all(p == 0.0 for p in prices) or any(p == 1.0 for p in prices)):
                        return True

        return False
    except Exception as e:
        logger.debug(f"Error checking if market {market.get('id')} is resolved: {e}")
        return False
```

---

### Solution 3: Augmenter le Batch Size du Resolutions Poller

**Problème**: Seulement 200 marchés par cycle (15min) = trop lent pour 1,379 marchés expirés.

**Fix**: Augmenter la limite et traiter par priorité:

```python
async def _get_resolution_candidates(self) -> List[str]:
    """
    Get market IDs that might be resolved
    Priority order with increased limits
    """
    try:
        async with get_db() as db:
            # Priority 1: Expired markets not resolved (INCREASED LIMIT)
            result = await db.execute(text("""
                SELECT id
                FROM markets
                WHERE end_date < now()
                AND (is_resolved = false OR is_resolved IS NULL)
                AND id IS NOT NULL
                ORDER BY end_date DESC
                LIMIT 500  -- INCREASED from 100
            """))
            expired_ids = [row[0] for row in result.fetchall()]

            # Priority 2: Markets without end_date but not resolved
            result = await db.execute(text("""
                SELECT id
                FROM markets
                WHERE end_date IS NULL
                AND (is_resolved = false OR is_resolved IS NULL)
                AND id IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT 200  -- INCREASED from 50
            """))
            no_end_date_ids = [row[0] for row in result.fetchall()]

            # Combine and deduplicate
            all_ids = list(set(expired_ids + no_end_date_ids))
            market_ids = all_ids[:500]  -- INCREASED from 200

            logger.debug(f"Found {len(market_ids)} resolution candidates ({len(expired_ids)} expired, {len(no_end_date_ids)} no end_date)")
            return market_ids
    except Exception as e:
        logger.error(f"Error getting resolution candidates: {e}")
        return []
```

---

## 📋 Checklist des Corrections

- [ ] **CRITIQUE**: Ajouter `allow_resolved=True` dans `resolutions_poller.py` pour permettre l'upsert des résolutions
- [ ] **CRITIQUE**: Améliorer `_is_market_really_resolved` avec des fallbacks (closed + expired, stable prices)
- [ ] **IMPORTANT**: Augmenter le batch size du resolutions poller (200 → 500)
- [ ] **IMPORTANT**: Ajouter des logs pour tracer les résolutions détectées mais non sauvegardées
- [ ] **OPTIONNEL**: Vérifier pourquoi si peu de marchés ont `source = 'ws'` (peut être normal)

---

## 🎯 Priorités

1. **URGENT**: Corriger le filtrage des résolutions (Solution 1)
2. **URGENT**: Améliorer la détection de résolution (Solution 2)
3. **IMPORTANT**: Augmenter le batch size (Solution 3)
4. **MONITORING**: Ajouter des métriques pour suivre les résolutions

---

## 📊 Métriques à Surveiller

- Nombre de marchés expirés non résolus (actuellement: 1,379)
- Taux de résolution détectée vs sauvegardée
- Temps moyen pour résoudre un marché expiré
- Nombre de marchés avec `source = 'ws'` (pour vérifier l'overwriting)
