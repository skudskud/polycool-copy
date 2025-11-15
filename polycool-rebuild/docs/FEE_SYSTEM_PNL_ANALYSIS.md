# Fee System & PnL Analysis

## ✅ État Actuel du Système de Fees

### 1. Calcul et Enregistrement des Fees

**Fichier:** `core/services/referral/commission_service.py`

- ✅ Fees calculés après chaque trade (BUY et SELL)
- ✅ Taux: 1% du montant du trade ou $0.10 minimum
- ✅ Discount de 10% pour les utilisateurs référés
- ✅ Fees enregistrés dans la table `trade_fees`
- ✅ Commissions de referral créées automatiquement (3 niveaux)

**Hook dans trade_service.py:**
```python
# Ligne 148-176
if trade_result['success']:
    # Calculate and record trade fee + commissions
    trade_fee = await commission_service.calculate_and_record_fee(
        user_id=internal_user_id,
        trade_amount=trade_amount,
        trade_type=trade_type,
        market_id=market_id,
        trade_id=None
    )
```

### 2. ❌ Problème: Fees NON Déduits du PnL

**Fichier:** `core/services/position/position_service.py`

La méthode `_calculate_pnl()` calcule le PnL **BRUT** sans tenir compte des fees :

```python
# Ligne 325-365
def _calculate_pnl(self, entry_price, current_price, amount, outcome):
    if outcome == "YES":
        pnl_amount = (current_price - entry_price) * amount
    elif outcome == "NO":
        pnl_amount = ((1 - current_price) - (1 - entry_price)) * amount

    # ❌ AUCUNE DÉDUCTION DES FEES
    return pnl_amount, pnl_percentage
```

**Impact:**
- Le PnL affiché est un **PnL brut** (sans fees)
- Les fees sont enregistrés mais pas visibles dans le PnL
- L'utilisateur voit un PnL plus élevé que la réalité

## 📊 Comparaison avec l'Ancien Code

Dans `telegram-bot-v2`, les fees étaient déduits lors du calcul du PnL lors d'un SELL :

```python
# telegram-bot-v2/py-clob-server/telegram_bot/handlers/positions/sell.py
# Ligne 629-637

# ✅ Calcul avec fees
total_invested = (tokens_actually_sold * db_avg_price) + buy_fee_amount
total_received = actual_proceeds - sell_fee_amount
pnl_value = total_received - total_invested
```

## 🎯 Solution Recommandée

### Option 1: Déduire les Fees du PnL Affiché (Recommandé)

Modifier `position_service._calculate_pnl()` pour inclure les fees :

```python
async def _calculate_pnl_with_fees(
    self,
    entry_price: float,
    current_price: float,
    amount: float,
    outcome: str,
    user_id: int,
    market_id: str
) -> Tuple[float, float]:
    """
    Calculate P&L INCLUDING fees (net P&L)

    Returns:
        Tuple of (net_pnl_amount, net_pnl_percentage)
    """
    # Calculate gross P&L
    if outcome == "YES":
        gross_pnl = (current_price - entry_price) * amount
    else:
        gross_pnl = ((1 - current_price) - (1 - entry_price)) * amount

    # Get fees for this position
    buy_fee = await self._get_buy_fee(user_id, market_id)
    sell_fee_estimate = await commission_service.calculate_fee_estimate(
        user_id, current_price * amount
    )

    # Net P&L = Gross P&L - Buy Fee - Sell Fee (estimated)
    net_pnl = gross_pnl - buy_fee - sell_fee_estimate

    # Calculate percentage
    total_invested = (entry_price * amount) + buy_fee
    net_pnl_percentage = (net_pnl / total_invested * 100) if total_invested > 0 else 0.0

    return net_pnl, net_pnl_percentage
```

### Option 2: Afficher PnL Brut ET Net

Afficher les deux dans l'UI :
```
P&L: $50.00 (brut) / $48.00 (net après fees)
```

### Option 3: Afficher Fees Séparément

Ajouter une ligne dans l'affichage des positions :
```
P&L: $50.00
Fees: $2.00 (buy: $1.00, sell est: $1.00)
Net P&L: $48.00
```

## 📋 Impact Actuel

### Sur les Positions Actives (Unrealized PnL)

- **PnL affiché:** Brut (sans fees)
- **Réalité:** L'utilisateur paiera des fees au moment du sell
- **Impact:** PnL surestimé

### Sur les Positions Fermées (Realized PnL)

- **PnL affiché:** Brut (sans fees)
- **Réalité:** Les fees ont déjà été déduits du montant reçu
- **Impact:** PnL surestimé

## 🔧 Actions Requises

1. **Court terme:** Documenter que le PnL affiché est brut
2. **Moyen terme:** Implémenter Option 1 (déduire fees du PnL)
3. **Long terme:** Afficher PnL brut ET net (Option 2)

## 💡 Notes Techniques

- Les fees sont bien enregistrés dans `trade_fees` ✅
- Les commissions de referral sont créées ✅
- Le calcul du PnL doit être modifié pour inclure les fees ❌
- Les fees peuvent être récupérés depuis `trade_fees` table ✅

## 📝 Exemple de Calcul

**Trade:**
- Buy: $100 @ $0.50 = 200 tokens
- Buy fee: $1.00 (1% ou $0.10 min)
- Current price: $0.55
- Sell fee estimate: $1.10 (1% de $110)

**PnL Brut (actuel):**
```
PnL = (0.55 - 0.50) * 200 = $10.00
```

**PnL Net (avec fees):**
```
Gross PnL = $10.00
Buy Fee = $1.00
Sell Fee = $1.10
Net PnL = $10.00 - $1.00 - $1.10 = $7.90
```

**Différence:** $2.10 (21% de différence!)
