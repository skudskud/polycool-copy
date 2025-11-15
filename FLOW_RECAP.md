# 🔄 Flow Complet - Redeem System avec Notifications

## 📊 État Actuel de la Base de Données (Supabase)

**D'après les requêtes Supabase:**
- **RESOLVED**: 10,639 marchés (tous avec `winning_outcome` rempli ✅)
- **PROPOSED**: 9,745 marchés (aucun avec `winning_outcome` rempli ❌)
- **resolved_positions**: 6 enregistrements (aucun notifié encore)

---

## 🔄 Flow Complet Côté Utilisateur

### 1️⃣ **Trigger: User appelle `/positions`**

**Fichier:** `telegram-bot-v2/py-clob-server/telegram_bot/handlers/positions/core.py`

```python
async def positions_command()
    ↓
Fetch positions depuis blockchain API (Polymarket)
    ↓
Appelle detect_redeemable_positions()
```

### 2️⃣ **Détection des Positions Redeemables**

**Fichier:** `telegram-bot-v2/py-clob-server/core/services/redeemable_position_detector.py`

#### Étape 2.1: `detect_redeemable_positions()`
- Extrait tous les `condition_id` des positions de l'utilisateur
- Appelle `_batch_query_resolved_markets()` pour trouver les marchés résolus

#### Étape 2.2: `_batch_query_resolved_markets()` ⚠️ **PROBLÈME DÉTECTÉ**

**Requête actuelle:**
```python
markets = db.query(SubsquidMarketPoll).filter(
    SubsquidMarketPoll.condition_id.in_(uncached_ids),
    SubsquidMarketPoll.resolution_status == 'RESOLVED',  # ❌ SEULEMENT RESOLVED!
    SubsquidMarketPoll.winning_outcome.isnot(None)
).all()
```

**⚠️ PROBLÈME:** Ne cherche QUE les marchés `RESOLVED` avec `winning_outcome`.
**❌ N'inclut PAS les PROPOSED avec prix extrêmes!**

**Impact:** Si un marché est PROPOSED avec prix extrêmes (>= 0.99), il ne sera PAS détecté ici!

#### Étape 2.3: `_check_position_redeemable()`
- Pour chaque position dans un marché résolu:
  - Vérifie si `tokens_held >= 0.1` (filtre dust)
  - Compare `position_outcome` avec `winning_outcome`
  - Détermine si gagnant/perdant
  - Appelle `_get_or_create_resolved_position()`

#### Étape 2.4: `_get_or_create_resolved_position()`
- **Si existe déjà:** Retourne l'enregistrement existant
- **Si nouveau:**
  - Crée `resolved_positions` record (winners ET losers)
  - Calcule P&L, fees, net_value
  - **Envoie notification** via `_send_notification()` (background thread)
  - Met à jour `notified = True` après envoi réussi

### 3️⃣ **Filtrage des Positions**

**Fichier:** `telegram-bot-v2/py-clob-server/telegram_bot/handlers/positions/core.py`

```python
# Filtre les positions redeemables des positions actives
positions_data = [
    pos for pos in positions_data
    if pos.get('conditionId') not in redeemable_condition_ids
]
```

**Résultat:** Les positions dans des marchés résolus disparaissent de la liste active.

### 4️⃣ **Affichage des Claimable Winnings**

**Fichier:** `telegram-bot-v2/py-clob-server/telegram_bot/services/position_view_builder.py`

```python
# Lit depuis resolved_positions table
claimable = db.query(ResolvedPosition).filter(
    ResolvedPosition.user_id == user_id,
    ResolvedPosition.status.in_(['PENDING', 'PROCESSING']),
    ResolvedPosition.is_winner == True  # ✅ Seulement les gagnants
).all()
```

**Affiche:**
- Section "💰 Claimable Winnings"
- Liste des positions gagnantes avec bouton "Redeem"
- **Les perdants sont filtrés mais pas affichés** (notification seulement)

### 5️⃣ **Redemption**

**Fichier:** `telegram-bot-v2/py-clob-server/telegram_bot/handlers/redemption_handler.py`

- User clique "Redeem" → `handle_redeem_position()`
- Exécute transaction blockchain via `RedemptionService`
- Met à jour `status = 'REDEEMED'`
- Envoie notification de succès

---

## 🚨 **Problème Critique Identifié**

### ❌ Le Detector ne cherche PAS les PROPOSED avec prix extrêmes!

**Code actuel (ligne 160):**
```python
SubsquidMarketPoll.resolution_status == 'RESOLVED'  # ❌ Seulement RESOLVED
```

**Conséquence:**
- Les marchés PROPOSED avec prix extrêmes (>= 0.99) ne sont PAS détectés
- Le `resolution-worker` les détecte (modifié aujourd'hui), mais le système manual (`/positions`) ne les détecte PAS

**Solution:** Modifier `_batch_query_resolved_markets()` pour inclure PROPOSED avec prix extrêmes, comme dans `resolution-worker`.

---

## ❓ **Réponse à ta Question: Passage Manuel PROPOSED → RESOLVED**

### Question: "Si je passe manuellement un marché de PROPOSED à RESOLVED dans Supabase, est-ce que ça va déclencher le flow de redeem + notif?"

### Réponse: **OUI, MAIS avec conditions ⚠️**

**Scénario 1: Passage PROPOSED → RESOLVED avec `winning_outcome` rempli**
```
1. Tu passes resolution_status = 'RESOLVED' ✅
2. Tu remplis winning_outcome = 0 ou 1 ✅
3. User appelle /positions
4. ✅ Détecté par _batch_query_resolved_markets()
5. ✅ Crée resolved_positions record
6. ✅ Envoie notification
7. ✅ Apparaît dans Claimable Winnings
```

**Scénario 2: Passage PROPOSED → RESOLVED SANS `winning_outcome`**
```
1. Tu passes resolution_status = 'RESOLVED' ✅
2. ❌ winning_outcome reste NULL
3. User appelle /positions
4. ❌ NON détecté (filtre: winning_outcome.isnot(None))
5. ❌ Pas de notification
6. ❌ Pas de redeem
```

**Scénario 3: Marché PROPOSED avec prix extrêmes (PAS changé en RESOLVED)**
```
1. Marché reste PROPOSED
2. outcome_prices = [0.99, 0.01] (prix extrêmes)
3. User appelle /positions
4. ❌ NON détecté (le detector cherche seulement RESOLVED)
5. ❌ Pas de notification
```

---

## 🔧 **Actions Requises**

### 1. **Modifier `_batch_query_resolved_markets()` pour inclure PROPOSED**

**Fichier:** `telegram-bot-v2/py-clob-server/core/services/redeemable_position_detector.py`

**Ajouter la logique similaire à `resolution-worker`:**
```python
# Inclure RESOLVED (comme avant)
# ET PROPOSED avec prix extrêmes:
# - outcome_prices[1] >= 0.99 AND outcome_prices[2] <= 0.01 (YES winner)
# - outcome_prices[2] >= 0.99 AND outcome_prices[1] <= 0.01 (NO winner)
# - end_date < NOW() - INTERVAL '1 hour' (expiré >1h)
```

### 2. **Adapter `_check_position_redeemable()` pour PROPOSED**

- Calculer `winning_outcome` depuis `outcome_prices` si PROPOSED
- Utiliser la même logique que `resolution-worker`

---

## 📝 **Résumé du Flow Complet**

```
User /positions
    ↓
Fetch positions (blockchain API)
    ↓
detect_redeemable_positions()
    ↓
_batch_query_resolved_markets()
    ├─ RESOLVED avec winning_outcome ✅ (actuel)
    └─ PROPOSED avec prix extrêmes ❌ (manquant!)
    ↓
_check_position_redeemable()
    ├─ Gagnant → Crée resolved_positions + Notification
    └─ Perdant → Crée resolved_positions + Notification (pas affiché)
    ↓
Filtre positions actives
    ↓
Affiche Claimable Winnings (winners seulement)
    ↓
User clique Redeem → Exécute transaction
```

---

## ✅ **Pour DÉCLENCHER le Flow Manuellement:**

1. **Passer PROPOSED → RESOLVED** dans Supabase
2. **Remplir `winning_outcome`** (0 ou 1)
3. User appelle `/positions`
4. ✅ Flow déclenché automatiquement!

**Note:** Le `resolution-worker` gère déjà les PROPOSED avec prix extrêmes (modifié aujourd'hui), mais le système manual (`/positions`) ne les gère PAS encore.
