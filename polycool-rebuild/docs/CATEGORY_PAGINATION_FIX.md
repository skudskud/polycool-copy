# Fix: Pagination dans les Catégories

**Date:** $(date)
**Status:** ✅ **CORRIGÉ**

---

## Problèmes Identifiés

### 1. Incohérence dans le Format des Callbacks

**Problème :**
- Les callbacks du hub sont en lowercase : `cat_geopolitics_0`
- Le handler capitalisait la catégorie : `geopolitics` → `Geopolitics`
- Les callbacks de pagination utilisaient `context_name` directement, créant des callbacks comme `cat_Geopolitics_1` au lieu de `cat_geopolitics_1`

**Impact :**
- Les boutons "Prev/Next" ne fonctionnaient pas correctement
- Les filtres ne fonctionnaient pas

### 2. Paramètres Non Passés dans l'URL

**Problème :**
- `get_category_markets()` définissait `params` mais ne les passait pas dans l'URL
- `get_trending_markets()` avait le même problème
- `search_markets()` avait le même problème

**Impact :**
- L'API ne recevait pas les paramètres de pagination
- Le cache utilisait des clés incorrectes

---

## Solutions Appliquées

### 1. ✅ Cohérence des Callbacks

**Fichier :** `telegram_bot/bot/handlers/markets/categories.py`

**Changements :**
- Séparation entre `category_key` (lowercase pour callbacks) et `category_display` (capitalized pour API)
- `context_name` toujours en lowercase pour les callbacks de pagination

**Avant :**
```python
category = parts[1].capitalize()  # geopolitics -> Geopolitics
context_name=category  # Geopolitics dans callbacks ❌
```

**Après :**
```python
category_key = parts[1].lower()  # geopolitics (pour callbacks)
category_display = parts[1].capitalize()  # Geopolitics (pour API)
context_name=category_key  # geopolitics dans callbacks ✅
```

### 2. ✅ Callbacks de Pagination Corrigés

**Fichier :** `telegram_bot/bot/handlers/markets/formatters.py`

**Changements :**
- `context_name` converti en lowercase pour les callbacks de catégorie
- Callbacks de filtres également corrigés

**Code :**
```python
# Pagination
context_for_callback = (context_name or '').lower()
prev_callback = f"cat_{context_for_callback}_{page - 1}"
next_callback = f"cat_{context_for_callback}_{page + 1}"

# Filters
context_for_callback = (context_name or '').lower() if view_type == 'category' else (context_name or '')
callback_data = f"catfilter_{context_for_callback}_{filter_key}_{page}"
```

### 3. ✅ Paramètres Passés dans l'URL

**Fichier :** `core/services/api_client/api_client.py`

**Changements :**

#### `get_category_markets()`
```python
# Avant
endpoint = f"/markets/categories/{category}"
params = {...}  # Non utilisé ❌

# Après
endpoint = f"/markets/categories/{category}?page={page}&page_size={page_size}"
if filter_type:
    endpoint += f"&filter_type={filter_type}"
```

#### `get_trending_markets()`
```python
# Avant
endpoint = f"/markets/trending"
params = {...}  # Non utilisé ❌

# Après
endpoint = f"/markets/trending?page={page}&page_size={page_size}&group_by_events={str(group_by_events).lower()}"
if filter_type:
    endpoint += f"&filter_type={filter_type}"
```

#### `search_markets()`
```python
# Avant
endpoint = f"/markets/search"
params = {...}  # Non utilisé ❌

# Après
from urllib.parse import quote
endpoint = f"/markets/search?query={quote(query)}&page={page}&page_size={page_size}"
if filter_type:
    endpoint += f"&filter_type={filter_type}"
```

---

## Tests de Cohérence

### Format des Callbacks

| Action | Callback Format | Exemple |
|--------|----------------|---------|
| **Hub → Category** | `cat_{category}_0` | `cat_geopolitics_0` |
| **Pagination Next** | `cat_{category}_{page}` | `cat_geopolitics_1` |
| **Pagination Prev** | `cat_{category}_{page}` | `cat_geopolitics_0` |
| **Filter** | `catfilter_{category}_{filter}_{page}` | `catfilter_geopolitics_volume_0` |

### Comparaison avec Trending

| View Type | Callback Format | Cohérence |
|-----------|----------------|-----------|
| **Trending** | `trending_markets_{page}` | ✅ Référence |
| **Category** | `cat_{category}_{page}` | ✅ Cohérent |
| **Search** | `search_page_{query}_{page}` | ✅ Cohérent |

---

## Fichiers Modifiés

1. **`telegram_bot/bot/handlers/markets/categories.py`**
   - Séparation `category_key` / `category_display`
   - Utilisation de `category_key` pour `context_name`

2. **`telegram_bot/bot/handlers/markets/formatters.py`**
   - Conversion en lowercase pour les callbacks de catégorie
   - Callbacks de filtres corrigés

3. **`core/services/api_client/api_client.py`**
   - `get_category_markets()` : params dans URL
   - `get_trending_markets()` : params dans URL
   - `search_markets()` : params dans URL

---

## Impact

**Avant :**
- ❌ Pagination ne fonctionnait pas dans les catégories
- ❌ Filtres ne fonctionnaient pas
- ❌ Callbacks invalides (`cat_Geopolitics_1`)
- ❌ Paramètres de pagination non passés à l'API

**Après :**
- ✅ Pagination fonctionne correctement
- ✅ Filtres fonctionnent correctement
- ✅ Callbacks cohérents (`cat_geopolitics_1`)
- ✅ Paramètres correctement passés à l'API
- ✅ Cache keys incluent page/page_size

---

## Vérification

### Test de Pagination

1. Cliquer sur une catégorie (ex: "Geopolitics")
2. Cliquer sur "Next ➡️"
3. Vérifier que la page suivante s'affiche
4. Cliquer sur "⬅️ Prev"
5. Vérifier que la page précédente s'affiche

### Test de Filtres

1. Cliquer sur un filtre (ex: "💧 Liq")
2. Vérifier que les marchés sont filtrés
3. Vérifier que la pagination fonctionne toujours

---

**Status:** ✅ **Tous les problèmes de pagination corrigés**

**Dernière mise à jour:** $(date)
