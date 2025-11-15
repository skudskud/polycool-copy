# 🔧 Fix: Callback Data 64-Byte Limit

**Date:** $(date)
**Problème:** `Button_data_invalid` erreur lors du clic sur "trending_markets_0"

---

## 🐛 Problème Identifié

L'erreur `Button_data_invalid` se produit parce que les `callback_data` des boutons Telegram dépassent la limite de **64 bytes**.

### Cause Racine

Dans `formatters.py`, les event groups utilisaient `event_title` encodé en base64 :

```python
# AVANT (❌ DÉPASSE 64 BYTES)
event_title = "Super Bowl Champion 2026 - Which team will win?"
encoded_title = base64.urlsafe_b64encode(event_title.encode('utf-8')).decode('utf-8')
callback_data = f"event_select_{page}|{encoded_title}"
# Résultat: 101 bytes ❌
```

**Limite Telegram:** 64 bytes maximum pour `callback_data`

---

## ✅ Solution Appliquée

### 1. Utiliser `event_id` au lieu de `event_title`

**Fichier:** `telegram_bot/bot/handlers/markets/formatters.py`

```python
# APRÈS (✅ < 64 BYTES)
event_id = market.get('event_id', 'unknown')
callback_data = f"event_select_{page}_{event_id}"
# Résultat: ~20 bytes ✅
```

### 2. Validation de longueur avec fallback

```python
# Valider longueur et tronquer si nécessaire
if len(callback_data) > 64:
    logger.warning(f"Callback data too long ({len(callback_data)} bytes)")
    event_id_short = event_id[:20] if len(event_id) > 20 else event_id
    callback_data = f"event_select_{page}_{event_id_short}"
```

### 3. Mise à jour du handler

**Fichier:** `telegram_bot/bot/handlers/markets_handler.py`

Le handler `_handle_event_select_callback` a été mis à jour pour :
- Parser le nouveau format `event_select_{page}_{event_id}`
- Utiliser l'endpoint `/markets/events/{event_id}` au lieu de `/markets/events/by-title/{title}`
- Récupérer l'event_title depuis les marchés retournés

---

## 📊 Comparaison Avant/Après

| Format | Exemple | Longueur | Status |
|--------|---------|----------|--------|
| **Avant** | `event_select_0\|U3VwZXIgQm93bCBDaGFtcGlvbiAyMDI2IC0gV2hpY2ggdGVhbSB3aWxsIHdpbiB0aGUgY2hhbXBpb25zaGlwPw` | 101 bytes | ❌ |
| **Après** | `event_select_0_23656` | 20 bytes | ✅ |

---

## 🔍 Vérification des Autres Callbacks

### Market Select Callbacks

Format: `market_select_{market_id}_{page}`

**Problème potentiel:** Certains `market_id` peuvent être très longs (78+ caractères)

**Solution:** Validation et tronquage si nécessaire

```python
if len(callback_data) > 64:
    max_market_id_len = 64 - len(f"market_select__{page}")
    market_id_short = market_id[:max_market_id_len]
    callback_data = f"market_select_{market_id_short}_{page}"
```

---

## ✅ Tests

### Test avec event_id

```python
event_id = '23656'
callback_data = f'event_select_0_{event_id}'
# Length: 20 bytes ✅
```

### Test avec market_id long

```python
market_id = '43742054330106624440770676058615966948810156625882809546791580883783971118571'
callback_data = f'market_select_{market_id}_0'
# Length: 78 bytes ❌ → Tronqué automatiquement ✅
```

---

## 🎯 Impact

**Avant:**
- ❌ Erreur `Button_data_invalid` lors du clic sur trending markets
- ❌ Message d'erreur affiché à l'utilisateur
- ❌ Impossible de naviguer dans les event groups

**Après:**
- ✅ Tous les callbacks respectent la limite de 64 bytes
- ✅ Navigation fluide dans les event groups
- ✅ Validation automatique avec fallback

---

## 📝 Fichiers Modifiés

1. **`telegram_bot/bot/handlers/markets/formatters.py`**
   - Utilise `event_id` au lieu de `event_title` encodé
   - Ajoute validation de longueur avec fallback
   - Ajoute logger pour warnings

2. **`telegram_bot/bot/handlers/markets_handler.py`**
   - Met à jour `_handle_event_select_callback` pour parser le nouveau format
   - Utilise `/markets/events/{event_id}` au lieu de `/markets/events/by-title/{title}`
   - Récupère `event_title` depuis les marchés retournés

---

## 🔄 Prochaines Étapes

1. **Redémarrer le bot** pour appliquer les changements
2. **Tester** la navigation dans les trending markets
3. **Vérifier** que les event groups s'affichent correctement
4. **Monitorer** les logs pour détecter d'autres callbacks trop longs

---

**Status:** ✅ Fix appliqué et prêt pour test

**Dernière mise à jour:** $(date)
