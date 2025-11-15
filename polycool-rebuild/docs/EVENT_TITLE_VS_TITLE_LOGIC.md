# ✅ Logique event_title vs title - Vérification

**Date:** $(date)
**Status:** ✅ **CORRECTE**

---

## 📊 Structure des Données

D'après la base de données Supabase :

| Type | `title` | `event_title` | `id` | `event_id` |
|------|---------|---------------|------|------------|
| **Event Group** | ❌ N/A | ✅ "EPL – Which Clubs Get Relegated?" | ❌ N/A | ✅ "35922" |
| **Individual Market** | ✅ "Will Burnley be relegated..." | ✅ "EPL – Which Clubs Get Relegated?" | ✅ "572859" | ✅ "35922" |

---

## ✅ Logique Respectée dans le Code

### 1. **Affichage dans la Liste des Marchés** (`formatters.py`)

#### Event Groups (`type == 'event_group'`)
```python
# Ligne 206-209
if item_type == 'event_group':
    # Display event group (parent)
    market_display = _build_group_ui(market, i)
    message += market_display
```

**Dans `_build_group_ui` (ligne 32):**
```python
# Event title - use event_title from the group data
event_title = group_data.get('event_title', 'Unknown Event')
# ...
display = f"📁 **{index}. {title_display}**\n"
```

✅ **Utilise `event_title`** pour l'affichage

#### Individual Markets (`type != 'event_group'`)
```python
# Ligne 210-220
else:
    # Display individual market
    title = market.get('title', 'Unknown Market')
    # ...
    message += f"{market_emoji} **{i}. {title_display}**\n"
```

✅ **Utilise `title`** pour l'affichage

---

### 2. **Callback Data** (`formatters.py`)

#### Event Groups
```python
# Ligne 107-121
if market.get('type') == 'event_group':
    event_id = market.get('event_id', 'unknown')
    callback_data = f"event_select_{page}_{event_id}"
```

✅ **Utilise `event_id`** pour le callback (évite dépassement 64 bytes)

#### Individual Markets
```python
# Ligne 122-135
else:
    market_id = market.get('id', 'unknown')
    callback_data = f"market_select_{market_id}_{page}"
```

✅ **Utilise `market_id`** pour le callback

---

### 3. **Affichage des Marchés d'un Event** (`markets_handler.py`)

```python
# Ligne 620-632
event_title = event_title or event_markets[0].get('event_title', f'Event {event_id}')
message = f"**{event_title}**\n\n"  # ✅ Utilise event_title comme titre de l'event

# Display markets with numbers
for i, market in enumerate(event_markets[:10], start=1):
    title = market.get('title', 'Unknown')  # ✅ Utilise title pour chaque marché
    message += f"{i}. {title}\n"
```

✅ **Utilise `event_title`** comme titre de l'event
✅ **Utilise `title`** pour chaque marché individuel

---

## 📋 Résumé

| Contexte | Champ Utilisé | Code Location |
|----------|---------------|---------------|
| **Event Group - Affichage** | `event_title` | `formatters.py:32` |
| **Event Group - Callback** | `event_id` | `formatters.py:111` |
| **Individual Market - Affichage** | `title` | `formatters.py:214` |
| **Individual Market - Callback** | `id` (market_id) | `formatters.py:124` |
| **Event Detail - Titre Event** | `event_title` | `markets_handler.py:621` |
| **Event Detail - Titre Marché** | `title` | `markets_handler.py:629` |

---

## ✅ Conclusion

**La logique est correctement respectée :**

1. ✅ **Event groups** utilisent `event_title` pour l'affichage
2. ✅ **Individual markets** utilisent `title` pour l'affichage
3. ✅ **Callbacks** utilisent `event_id` / `market_id` (pas les titres)
4. ✅ **Event detail view** affiche `event_title` comme titre et `title` pour chaque marché

**Aucun changement nécessaire !** 🎉

---

**Dernière vérification:** $(date)
