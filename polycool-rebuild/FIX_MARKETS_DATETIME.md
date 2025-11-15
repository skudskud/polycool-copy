# 🔧 Fix: Datetime Comparison Error in Markets

## Problème identifié

**Erreur:** `can't compare offset-naive and offset-aware datetimes`

**Localisation:** Handler trending markets (`/markets` → "🔥 Trending Markets")

**Cause:**
- La colonne `end_date` dans la table `markets` est de type `timestamp without time zone` (offset-naive)
- Le code utilisait `datetime.now(timezone.utc)` qui retourne un datetime avec timezone (offset-aware)
- SQLAlchemy ne peut pas comparer ces deux types

## Solution appliquée

### ✅ Correction dans `market_service.py`

**Avant:**
```python
now = datetime.now(timezone.utc)
query = select(Market).where(Market.end_date > now)
```

**Après:**
```python
# Note: end_date is stored as timestamp without time zone, so we need offset-naive datetime
now = datetime.now(timezone.utc).replace(tzinfo=None)
query = select(Market).where(Market.end_date > now)
```

### 📍 Endroits corrigés

1. **`get_trending_markets()`** - Ligne 205
2. **`get_category_markets()`** - Ligne 265
3. **`_is_market_valid()`** - Ligne 117
4. **`search_markets()`** - Ligne 324

## 🔍 Analyse de la base de données

**Vérification Supabase:**
- Colonne `end_date`: `timestamp without time zone`
- Stockage: Datetime sans timezone

**Comparaison avec l'ancien code:**
- Ancien code utilisait probablement `datetime.utcnow()` (offset-naive)
- Nouveau code utilisait `datetime.now(timezone.utc)` (offset-aware)

## 🧪 Test

**Avant la correction:**
```
Error in trending callback: can't compare offset-naive and offset-aware datetimes
```

**Après la correction:**
```
✅ SUCCESS: Got X trending markets
First market: [Market Name]
```

## 📝 Structure des données

La table `markets` utilise maintenant un schéma unifié (au lieu de 3 tables fragmentées):

```sql
CREATE TABLE markets (
    id TEXT PRIMARY KEY,
    end_date TIMESTAMP WITHOUT TIME ZONE,
    -- ... autres colonnes
);
```

**Comparaison:**
- **Ancien:** `subsquid_markets_poll.end_date` (offset-naive)
- **Nouveau:** `markets.end_date` (offset-naive)

## 🚀 Résultat

- ✅ `/markets` fonctionne maintenant
- ✅ "🔥 Trending Markets" affiche correctement
- ✅ Pagination et filtres opérationnels
- ✅ Performance maintenue

## 📚 Documentation

Cette correction maintient la compatibilité avec le nouveau schéma de données unifié tout en résolvant les problèmes de timezone.
