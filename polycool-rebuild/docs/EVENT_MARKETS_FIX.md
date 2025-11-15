# Fix: Event Markets Missing event_id

**Date:** $(date)
**Status:** ✅ **RÉSOLU**

---

## Problème Identifié

### Symptôme
L'endpoint `/markets/events/{event_id}` retournait 0 résultats alors que la DB contenait bien des marchés enfants pour cet event.

### Cause Racine
1. **Dans la DB Supabase** :
   - 4 marchés enfants avec `event_title = 'Fed decision in December?'` mais `event_id = NULL`
   - 1 marché parent avec `event_id = '35090'` et `is_event_market = true`

2. **L'endpoint `/markets/events/{event_id}`** filtrait avec :
   ```python
   .where(Market.event_id == event_id)  # Cherche event_id = '35090'
   .where(Market.is_event_market == False)  # Enfants seulement
   ```
   Mais les enfants avaient `event_id = NULL`, donc 0 résultats.

3. **Le poller** (`base_poller.py:220`) mettait à jour `event_id` mais pouvait l'écraser avec NULL lors d'un update.

---

## Solutions Appliquées

### 1. ✅ Correction des Données Existantes dans la DB

**Migration SQL exécutée :**
```sql
UPDATE markets m_child
SET event_id = m_parent.event_id
FROM markets m_parent
WHERE m_child.event_title = m_parent.event_title
  AND m_child.is_event_market = false
  AND m_child.event_id IS NULL
  AND m_parent.is_event_market = true
  AND m_parent.event_id IS NOT NULL
```

**Résultat :**
- ✅ 4 marchés enfants mis à jour avec `event_id = '35090'`
- ✅ Tous les marchés de l'event "Fed decision in December?" ont maintenant le bon `event_id`

### 2. ✅ Amélioration du Poller

**Fichier :** `data_ingestion/poller/base_poller.py`

**Changement :**
```sql
-- AVANT
event_id = EXCLUDED.event_id,

-- APRÈS
event_id = CASE
    WHEN EXCLUDED.event_id IS NOT NULL AND EXCLUDED.event_id != ''
    THEN EXCLUDED.event_id
    ELSE markets.event_id
END,
```

**Bénéfice :**
- ✅ Préserve `event_id` existant si le nouveau est NULL
- ✅ Évite d'écraser les données avec NULL lors des updates
- ✅ Similaire à la logique déjà en place pour `event_title`

### 3. ✅ Amélioration de l'Endpoint

**Fichier :** `telegram_bot/api/v1/markets.py`

**Changement :**
Ajout d'un fallback si aucun marché n'est trouvé avec `event_id` :
1. Cherche le marché parent avec cet `event_id`
2. Utilise son `event_title` pour trouver les marchés enfants
3. Log les actions pour le débogage

**Code ajouté :**
```python
# Fallback: If no markets found by event_id, try to find parent event and use event_title
if not event_markets_db:
    logger.debug(f"No markets found for event_id {event_id}, trying fallback with event_title")
    # Find parent event market to get event_title
    parent_result = await db.execute(
        select(Market)
        .where(Market.event_id == event_id)
        .where(Market.is_event_market == True)
        .limit(1)
    )
    parent_market = parent_result.scalar_one_or_none()

    if parent_market and parent_market.event_title:
        # Use event_title to find child markets
        logger.info(f"Using fallback: searching by event_title '{parent_market.event_title}'")
        result = await db.execute(
            select(Market)
            .where(Market.event_title == parent_market.event_title)
            .where(Market.is_event_market == False)
            .where(Market.is_active == True)
            .where(Market.is_resolved == False)
            .order_by(Market.volume.desc())
            .limit(page_size)
            .offset(page * page_size)
        )
        event_markets_db = result.scalars().all()
```

**Bénéfice :**
- ✅ Fallback robuste si les données ne sont pas parfaites
- ✅ Logs pour le débogage
- ✅ Fonctionne même si certains marchés ont `event_id = NULL`

---

## Tests Effectués

### 1. ✅ Vérification de la Migration SQL
```sql
SELECT id, title, event_id, event_title, is_event_market
FROM markets
WHERE event_title = 'Fed decision in December?'
ORDER BY is_event_market DESC, id;
```

**Résultat :**
- ✅ 1 marché parent avec `event_id = '35090'`
- ✅ 4 marchés enfants avec `event_id = '35090'`

### 2. ✅ Test de l'Endpoint
```bash
curl "https://polycool-api-production.up.railway.app/api/v1/markets/events/35090?page=0&page_size=20"
```

**Résultat :**
- ✅ Retourne 4 marchés enfants
- ✅ Tous les marchés ont des données complètes (prices, outcomes, etc.)

### 3. ✅ Test du Flow Complet
- `/markets` → Trending Markets → Event Group → Liste des marchés
- ✅ Fonctionne correctement

---

## Fichiers Modifiés

1. **`data_ingestion/poller/base_poller.py`**
   - Ligne 220-225 : Protection contre l'écrasement de `event_id` avec NULL

2. **`telegram_bot/api/v1/markets.py`**
   - Ligne 273-300 : Ajout du fallback sur `event_title`

---

## Impact

**Avant :**
- ❌ Endpoint retournait 0 résultats
- ❌ Utilisateurs voyaient "No markets found"
- ❌ Données incohérentes dans la DB

**Après :**
- ✅ Endpoint retourne les 4 marchés enfants
- ✅ Utilisateurs peuvent naviguer dans les events
- ✅ Données cohérentes dans la DB
- ✅ Protection contre les futures corruptions de données

---

## Prochaines Étapes Recommandées

1. **Monitorer** les logs pour détecter l'utilisation du fallback
2. **Vérifier** que le poller remplit bien `event_id` sur les nouveaux marchés
3. **Considérer** une migration périodique pour corriger les données orphelines

---

**Status:** ✅ **Tous les problèmes résolus**

**Dernière mise à jour:** $(date)
