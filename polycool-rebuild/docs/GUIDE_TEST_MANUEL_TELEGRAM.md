# 🧪 Guide de Test Manuel - Telegram Bot

**Utilisateur de test:** `telegram_user_id = 6500527972`

Ce guide te permet de tester **TOUS** les flows et callbacks manuellement via le bot Telegram.

---

## 📋 Prérequis

1. ✅ Tous les services démarrés:
   ```bash
   ./scripts/dev/start-all.sh
   ```

2. ✅ Services vérifiés:
   ```bash
   ./scripts/dev/test-e2e-user-flow.sh 6500527972
   ```

3. ✅ Monitoring des logs:
   ```bash
   ./scripts/dev/monitor-all.sh
   ```

---

## 🎯 Flow 1: Positions Complet (Buy → Visible → Sell → Disparaît)

### Étape 1: Vérifier état initial
1. Envoie `/positions` au bot
2. Note le nombre de positions actives
3. Note ton solde avec `/wallet` ou depuis le dashboard

### Étape 2: Acheter une position
1. Envoie `/markets` ou clique "📊 Browse Markets"
2. Sélectionne un marché (ex: trending markets)
3. Clique "Quick Buy" ou "Custom Buy"
4. Confirme l'achat

**✅ Vérifications:**
- [ ] Position apparaît dans `/positions`
- [ ] Solde diminue du montant de l'achat
- [ ] Logs API montrent: `POST /api/v1/trades/`
- [ ] Logs Bot montrent: `Position created`

### Étape 3: Vérifier WebSocket → PnL
1. Garde `/positions` ouvert
2. Attends 10-30 secondes
3. Observe le PnL se mettre à jour automatiquement

**✅ Vérifications:**
- [ ] Logs Workers montrent: `price.*update` ou `PnL.*updated`
- [ ] PnL change dans `/positions` sans refresh manuel
- [ ] Logs montrent: `Subscribed to market.*token_id`

### Étape 4: Mettre un Stop Loss
1. Dans `/positions`, clique sur une position
2. Clique "Set Stop Loss" ou "TP/SL"
3. Entre un prix de stop loss (ex: 0.3)
4. Confirme

**✅ Vérifications:**
- [ ] Position affiche le stop loss
- [ ] Logs API montrent: `PUT /api/v1/positions/{id}/stop-loss`
- [ ] DB vérification: `SELECT stop_loss FROM positions WHERE id = {position_id}`

### Étape 5: Vendre la position
1. Dans `/positions`, clique sur la position
2. Clique "Sell" ou "Close Position"
3. Confirme la vente

**✅ Vérifications:**
- [ ] Position disparaît de `/positions`
- [ ] Solde augmente du montant de vente
- [ ] Logs API montrent: `POST /api/v1/positions/{id}/sell`
- [ ] Logs Workers montrent: `Unsubscribed from market.*token_id` (si dernière position sur ce marché)

---

## 🎯 Flow 2: Stop Loss Automatique

### Étape 1: Créer position avec Stop Loss
1. Achete une position (voir Flow 1, Étape 2)
2. Mettez un Stop Loss à 0.3 (voir Flow 1, Étape 4)

### Étape 2: Simuler déclenchement Stop Loss
**Option A: Via WebSocket (automatique)**
- Attendez que le prix du marché descende sous 0.3
- Le TP/SL Monitor devrait fermer automatiquement

**Option B: Via DB (test manuel)**
```sql
-- Dans Supabase, mettre à jour le prix du marché pour déclencher SL
UPDATE markets
SET outcome_prices = '{"Yes": 0.25}'::jsonb
WHERE id = '{market_id}';
```

**✅ Vérifications:**
- [ ] Position fermée automatiquement
- [ ] Logs Workers montrent: `Stop Loss triggered` ou `TP/SL monitor.*closed`
- [ ] Position disparaît de `/positions`
- [ ] Solde mis à jour

---

## 🎯 Flow 3: Tous les Callbacks/Boutons

### Dashboard Principal (`/start`)
- [ ] "📊 Browse Markets" → Affiche markets hub
- [ ] "📈 View Positions" → Affiche positions
- [ ] "💼 Wallet" → Affiche solde
- [ ] "🎯 Smart Trading" → Affiche recommandations
- [ ] "👥 Copy Trading" → Affiche copy trading dashboard

### Markets Hub
- [ ] "Trending Markets" → Liste des marchés trending
- [ ] "Categories" → Liste des catégories
- [ ] "Search" → Recherche de marchés
- [ ] Sélectionner un marché → Détails du marché
- [ ] "Quick Buy" → Achat rapide
- [ ] "Custom Buy" → Achat avec montant personnalisé
- [ ] "← Back" → Retour au hub

### Positions
- [ ] Liste des positions affichée
- [ ] Cliquer sur une position → Détails
- [ ] "Refresh" → Met à jour les positions
- [ ] "Sell" → Vendre position
- [ ] "Set TP/SL" → Configurer Take Profit/Stop Loss
- [ ] "← Back" → Retour au dashboard

### Smart Trading
- [ ] Liste des recommandations affichée
- [ ] "Next" / "Prev" → Pagination
- [ ] "View Market" → Détails du marché
- [ ] "Quick Buy" → Achat depuis recommandation
- [ ] "← Back" → Retour au dashboard

### Copy Trading
- [ ] Dashboard affiché
- [ ] "➕ Add Leader" → Ajouter un leader
- [ ] "Search Leader" → Rechercher un leader
- [ ] "Settings" → Paramètres d'allocation
- [ ] "Pause" / "Resume" → Pause/Reprendre
- [ ] "Stop Following" → Arrêter de suivre
- [ ] "← Back" → Retour au dashboard

---

## 🔍 Vérifications Techniques

### 1. Vérifier WebSocket Connection
```bash
# Dans un terminal séparé
tail -f logs/workers.log | grep -i "websocket\|streamer\|subscribe"
```

**Ce que tu devrais voir:**
- `Streamer service launched`
- `WebSocket connected`
- `Subscribed to market {token_id}` (quand tu achètes)
- `Unsubscribed from market {token_id}` (quand tu vends)

### 2. Vérifier PnL Updates
```bash
tail -f logs/workers.log | grep -i "pnl\|price.*update\|position.*updated"
```

**Ce que tu devrais voir:**
- `Price update received for market {market_id}`
- `Updating positions for market {market_id}`
- `Position {id} PnL updated: {amount}`

### 3. Vérifier API Calls depuis Bot
```bash
tail -f logs/bot.log | grep -i "api_client\|api request\|GET\|POST"
```

**Ce que tu devrais voir:**
- `APIClient: GET /api/v1/positions/user/{id}`
- `APIClient: POST /api/v1/trades/`
- `APIClient: PUT /api/v1/positions/{id}/stop-loss`

### 4. Vérifier DB Updates
```sql
-- Dans Supabase SQL Editor
-- Vérifier positions créées
SELECT id, market_id, user_id, amount_usd, current_price, pnl_usd, stop_loss
FROM positions
WHERE user_id = (SELECT id FROM users WHERE telegram_user_id = 6500527972)
ORDER BY created_at DESC
LIMIT 10;

-- Vérifier trades exécutés
SELECT id, market_id, user_id, amount_usd, outcome, status
FROM trades
WHERE user_id = (SELECT id FROM users WHERE telegram_user_id = 6500527972)
ORDER BY created_at DESC
LIMIT 10;
```

---

## 📊 Checklist Complète

### ✅ Flow Positions
- [ ] Buy position → Visible dans `/positions`
- [ ] WebSocket met à jour PnL automatiquement
- [ ] Stop Loss configuré et sauvegardé
- [ ] Sell position → Disparaît de `/positions`
- [ ] Solde mis à jour après buy/sell

### ✅ Flow Stop Loss
- [ ] Stop Loss déclenché automatiquement quand prix atteint
- [ ] Position fermée automatiquement
- [ ] Notification envoyée (si implémenté)

### ✅ Flow WebSocket
- [ ] WebSocket connecté quand positions actives
- [ ] Subscribe automatique après buy
- [ ] Unsubscribe automatique après sell (si dernière position)
- [ ] Prix mis à jour en temps réel (< 100ms)
- [ ] PnL recalculé automatiquement

### ✅ Flow Callbacks
- [ ] Tous les boutons mènent quelque part (pas d'erreur)
- [ ] Navigation fonctionne (back, next, prev)
- [ ] Données affichées correctement
- [ ] Pas d'erreurs dans logs/bot.log

---

## 🐛 Dépannage

### Position n'apparaît pas après buy
1. Vérifier logs/bot.log pour erreurs
2. Vérifier logs/api.log pour erreurs API
3. Vérifier DB: `SELECT * FROM positions WHERE user_id = {id} ORDER BY created_at DESC LIMIT 1`

### WebSocket ne met pas à jour PnL
1. Vérifier que Streamer est démarré: `grep "Streamer" logs/workers.log`
2. Vérifier subscription: `grep "Subscribed" logs/workers.log`
3. Vérifier que position a un `token_id`: `SELECT token_id FROM positions WHERE id = {id}`

### Stop Loss ne se déclenche pas
1. Vérifier que TP/SL Monitor est démarré: `grep "TP/SL monitor" logs/workers.log`
2. Vérifier stop_loss dans DB: `SELECT stop_loss FROM positions WHERE id = {id}`
3. Vérifier que prix du marché est sous le stop_loss

### Callback ne fonctionne pas
1. Vérifier logs/bot.log pour erreurs
2. Vérifier que handler existe dans `telegram_bot/bot/handlers/`
3. Vérifier que callback est enregistré dans `application.py`

---

## 📝 Notes de Test

**Date:** _________________

**Résultats:**

| Flow | Status | Notes |
|------|--------|-------|
| Buy → Visible | ⬜ | |
| WebSocket → PnL | ⬜ | |
| Stop Loss | ⬜ | |
| Sell → Disparaît | ⬜ | |
| Callbacks | ⬜ | |

**Erreurs rencontrées:**
-

**Bugs trouvés:**
-
