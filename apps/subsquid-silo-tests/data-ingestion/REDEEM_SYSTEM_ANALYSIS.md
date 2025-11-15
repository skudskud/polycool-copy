# Système de Redeem - Analyse Complète

**Date:** Nov 3, 2025
**Status:** Infrastructure en place, prête pour intégration

---

## 📊 État Actuel du Champ `resolution_status`

### Distribution dans la DB:

```
PENDING:  45,964 markets ($4.3B volume)
  → Markets ouvert ou vient de fermer (<1h)
  → Pas d'outcome disponible

PROPOSED: 7,635 markets ($3.8B volume)
  → Markets fermés, outcome proposé
  → En attente de confirmation API
  → ⚠️ BLOQUÉS: aucun winning_outcome rempli!

RESOLVED: 0 markets (sera rempli après redeploy poller)
  → winning_outcome sera rempli au prochain cycle poller
```

### Problème Détecté:

Le poller ne remplit pas encore `winning_outcome` lors de la détection de résolution. Après redeploy avec le fix `order=volume`, ce sera corrigé.

---

## 🎯 Infrastructure Redeem En Place ✅

### Table `resolved_positions` (EXISTE, STRUCTURE COMPLÈTE)

**Champs critiques:**

```
user_id → Qui a la position
market_id → Quel marché
outcome → User parié sur "YES" ou "NO"
tokens_held → Combien de tokens
total_cost → Investissement initial

winning_outcome → "YES" ou "NO" (déjà rempli!)
is_winner → true/false (calculé)
gross_value → tokens si winner, 0 si loser
net_value → gross_value * 0.99 (après 1% fee)
pnl → profit/loss

status → "PENDING" | "PROCESSING" | "SUCCESS" | "FAILED"
redemption_tx_hash → Transaction redeem
redemption_attempt_count → Retry counter (max 8)

fee_collected → 1% fee status
redeemed_at → Quand redeemé
expires_at → Deadline pour redeem

notified → User notifié?
redemption_notified → Notification après redeem?
```

---

## 🔌 Query pour Positions Redeem-Ready

**CLEF: Joindre resolution_status avec resolved_positions**

```sql
SELECT
    rp.id,
    rp.user_id,
    rp.market_id,
    rp.outcome,
    rp.tokens_held,
    mp.winning_outcome,
    -- Winner determination
    (rp.outcome = 'YES' AND mp.winning_outcome = 1) OR
    (rp.outcome = 'NO' AND mp.winning_outcome = 0) as is_winner,
    -- Payout
    CASE WHEN is_winner THEN rp.tokens_held * 1.0 ELSE 0 END as gross_payout,
    CASE WHEN is_winner THEN rp.tokens_held * 1.0 * 0.99 ELSE 0 END as net_payout,
    mp.polymarket_url
FROM resolved_positions rp
JOIN subsquid_markets_poll mp ON rp.market_id = mp.market_id
WHERE rp.status = 'PENDING'
  AND mp.resolution_status = 'RESOLVED'  ← KEY!
  AND mp.winning_outcome IS NOT NULL  ← KEY!
  AND rp.redemption_attempt_count < 8
ORDER BY rp.created_at ASC;
```

---

## 🚀 Redeem Bot Architecture (Efficace)

### 3-Layer System:

**Layer 1: Queue Filler (toutes les 5 min)**
- Run query ci-dessus
- Push positions to Redis: "redeem:queue"
- Update status = 'PROCESSING'

**Layer 2: Executor (worker continu)**
- Pop from Redis queue
- Calculate winner + payout
- Execute redeem transaction
- Update status = 'SUCCESS' / 'FAILED'
- Send notification

**Layer 3: Retry Handler (hourly)**
- Retry failed redemptions
- Exponential backoff: 5min → 15min → 1h → 6h
- Max 8 attempts before giving up

### Data Flow:

```
subsquid_markets_poll.resolution_status = RESOLVED
          ↓
Queue Filler (5min)
          ↓
Redis queue: "redeem:queue"
          ↓
Executor (continuous)
          ↓
Polymarket API: Execute redeem
          ↓
Update resolved_positions.status = SUCCESS
          ↓
Send notification to user
          ↓
Collect 1% fee
```

---

## 💰 Payout Logic

```python
# From resolved_positions table structure

# For Winner:
gross_value = tokens_held * 1.0  # 1 USDC per token
fee_amount = gross_value * 0.01  # 1% fee
net_value = gross_value - fee_amount
pnl = net_value - total_cost  # Profit

# For Loser:
gross_value = 0
fee_amount = 0
net_value = 0
pnl = 0 - total_cost  # Loss = -investment
```

---

## ✅ Checklist Implémentation

### Déjà En Place:
- ✅ resolved_positions table
- ✅ Winner calculation
- ✅ Payout calculation (1% fee built-in)
- ✅ Status tracking
- ✅ Retry mechanism
- ✅ Notification fields
- ✅ Transaction tracking

### À Faire (Après Redeploy Poller):
- ⏳ Verify winning_outcome populated
- ⏳ Implement Queue Filler Service
- ⏳ Implement Executor Worker
- ⏳ Add retry logic
- ⏳ Add notification system
- ⏳ Add admin monitoring

---

**Status:** 🟢 Ready to integrate
**Next:** After poller redeploy, start implementing Queue Filler
