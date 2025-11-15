# 🔧 Fix: Données Manquantes (condition_id, clob_token_ids, nouveaux markets)

## 📊 Problèmes Identifiés

### 1. ❌ Markets Sans condition_id et clob_token_ids

**Statistiques**:
- **1,380 markets** (11.6% du total) sans `condition_id` ni `clob_token_ids`
- Ces markets sont actifs mais incomplets
- Exemples: "Where will Zelenskyy and Putin meet next?", "Which company has best AI model end of 2025?"

**Cause**:
- L'API `/markets` (liste) ne retourne pas toujours ces champs
- Ces champs sont disponibles dans `/markets/{id}` (détail individuel)
- Le poller utilise souvent la liste qui peut être incomplète

**Impact**:
- Impossible de trader ces markets (pas de `clob_token_ids`)
- Impossible de les identifier via `condition_id` pour le WebSocket

---

### 2. ⚠️ Markets Résolus Ne Sont Plus Pollés

**Comportement actuel**:
- Une fois un market résolu (`is_resolved = true`), il est filtré dans `_upsert_markets()` (sauf `allow_resolved=True`)
- Le `price_poller` et autres pollers ne les mettent plus à jour
- Seul le `resolutions_poller` peut les mettre à jour (avec `allow_resolved=True`)

**Question**: Est-ce le comportement souhaité ?
- ✅ **OUI** si on veut arrêter de poller les markets résolus (économise ressources)
- ❌ **NON** si on veut continuer à mettre à jour les métadonnées (volume, etc.)

**Recommandation**: Garder le comportement actuel (ne plus poller les résolus) car:
- Les markets résolus ne changent plus de prix
- Le volume/liquidity peut encore changer mais c'est moins critique
- Économise des ressources API

---

### 3. ⚠️ Discovery Poller Limité

**Problème**:
- Ne cherche que dans les **top 1000 markets par volume**
- Rate: **toutes les 2h**
- Peut manquer des nouveaux markets moins populaires

**Impact**:
- Nouveaux markets avec faible volume ne sont pas découverts rapidement
- Markets qui deviennent populaires peuvent être découverts avec retard

---

## 🔧 Solutions Proposées

### Solution 1: Enrichment Poller pour condition_id et clob_token_ids

**Créer un nouveau poller** qui:
1. Trouve les markets sans `condition_id` ou `clob_token_ids`
2. Fetch `/markets/{id}` individuellement pour obtenir les champs complets
3. Met à jour uniquement ces champs manquants

**Fichier**: `data_ingestion/poller/enrichment_poller.py`

```python
class EnrichmentPoller(BaseGammaAPIPoller):
    """
    Poller pour enrichir les markets avec condition_id et clob_token_ids manquants
    - Trouve les markets actifs sans ces champs
    - Fetch /markets/{id} pour obtenir les données complètes
    - Met à jour uniquement les champs manquants
    - Frequency: 1h
    """

    async def _poll_cycle(self):
        # 1. Trouver markets sans condition_id ou clob_token_ids
        # 2. Fetch individuellement /markets/{id}
        # 3. Upsert avec seulement les champs manquants
```

---

### Solution 2: Améliorer le Discovery Poller

**Modifications**:
1. **Augmenter la limite**: 1000 → 2000 markets
2. **Ajouter des stratégies**:
   - Top volume (1000)
   - Nouveaux markets récents (500) - `order=createdAt`
   - Markets avec volume récent (500) - `order=volume24hr`
3. **Réduire l'intervalle**: 2h → 1h pour découvrir plus rapidement

---

### Solution 3: Améliorer l'Upsert pour Toujours Récupérer condition_id et clob_token_ids

**Problème actuel**: Le SQL préserve les valeurs existantes si nouvelles valeurs sont NULL

```sql
clob_token_ids = CASE WHEN EXCLUDED.clob_token_ids IS NOT NULL THEN EXCLUDED.clob_token_ids ELSE markets.clob_token_ids END,
condition_id = EXCLUDED.condition_id,
```

**Solution**: Si un market n'a pas ces champs, toujours essayer de les récupérer via `/markets/{id}` avant l'upsert.

**Modification dans `base_poller.py`**:
- Avant l'upsert, vérifier si `condition_id` ou `clob_token_ids` manquent
- Si oui, fetch `/markets/{id}` pour enrichir
- Puis upsert avec les données complètes

---

## 📋 Plan d'Implémentation

### Priorité 1: Enrichment Poller (CRITIQUE)

1. Créer `enrichment_poller.py`
2. Trouver markets sans `condition_id` ou `clob_token_ids`
3. Fetch individuellement `/markets/{id}` pour enrichir
4. Upsert avec `allow_missing_fields=True` pour ne pas écraser d'autres données

### Priorité 2: Améliorer Discovery Poller

1. Augmenter limite à 2000
2. Ajouter stratégies multiples (volume, createdAt, volume24hr)
3. Réduire intervalle à 1h

### Priorité 3: Enrichment Automatique dans Base Poller

1. Détecter markets incomplets avant upsert
2. Fetch `/markets/{id}` si nécessaire
3. Enrichir automatiquement

---

## 🎯 Résultats Attendus

### Avant
- ❌ 1,380 markets sans `condition_id` ni `clob_token_ids`
- ❌ Discovery limité aux top 1000
- ❌ Markets résolus ne sont plus pollés (comportement voulu)

### Après
- ✅ Enrichment poller comble les champs manquants
- ✅ Discovery plus large (2000 markets, stratégies multiples)
- ✅ Markets résolus toujours non pollés (comportement conservé)

---

## 📊 Métriques à Surveiller

```sql
-- Markets sans condition_id (devrait diminuer)
SELECT COUNT(*)
FROM markets
WHERE (condition_id IS NULL OR condition_id = '')
AND is_resolved = false;

-- Markets sans clob_token_ids (devrait diminuer)
SELECT COUNT(*)
FROM markets
WHERE (clob_token_ids IS NULL OR clob_token_ids = '[]'::jsonb)
AND is_resolved = false;

-- Nouveaux markets découverts par jour
SELECT DATE(created_at) as date, COUNT(*) as new_markets
FROM markets
GROUP BY DATE(created_at)
ORDER BY date DESC
LIMIT 7;
```
