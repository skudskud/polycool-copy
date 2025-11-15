# Copy Trading Diagnostics - Amélioration des Logs

**Date:** 2025-11-13
**Problème:** Logs de transaction manquants après réception du webhook

---

## 🔍 Problème Identifié

Le webhook a bien été traité (`✅ [WEBHOOK] Processed BUY trade for 0xa7a84f34... (copy_leader)`), mais aucun log de transaction n'apparaît. Cela suggère que :

1. Le message Redis PubSub n'a pas été reçu par le listener
2. Le listener a reçu le message mais n'a pas trouvé d'allocations actives
3. Le listener a trouvé les allocations mais le trade a échoué silencieusement
4. Le listener n'est pas démarré dans workers.py

---

## ✅ Améliorations Apportées

### 1. Logs Détaillés dans Copy Trading Listener

**Fichier:** `data_ingestion/indexer/copy_trading_listener.py`

**Ajouts:**
- ✅ Logs de démarrage avec confirmation de connexion Redis
- ✅ Logs pour chaque message Redis reçu avec tx_id et channel
- ✅ Logs pour vérification d'adresse watched avec type
- ✅ Logs pour recherche d'allocations actives
- ✅ Logs avant création de chaque task de copy trade
- ✅ Logs avant et après appel à `execute_market_order`
- ✅ Logs de résultat avec statut et erreur éventuelle
- ✅ Logs de completion avec compteur de succès/échecs

**Tags utilisés:** `[COPY_TRADE]` pour faciliter le filtrage

### 2. Logs Détaillés dans Trade Service

**Fichier:** `core/services/trading/trade_service.py`

**Ajouts:**
- ✅ Logs au début de `execute_market_order` avec tous les paramètres
- ✅ Logs avant appel à `_execute_trade`
- ✅ Logs après `_execute_trade` avec résultat
- ✅ Logs de succès/échec avec détails complets

**Tags utilisés:** `[TRADE]` pour faciliter le filtrage

### 3. Logs dans Webhook Receiver

**Fichier:** `telegram_bot/api/v1/webhooks/copy_trade.py`

**Ajouts:**
- ✅ Logs avant publication Redis PubSub
- ✅ Logs après publication avec nombre de subscribers
- ✅ Warning si aucun subscriber (listener non démarré)

**Tags utilisés:** `[WEBHOOK_REDIS]` pour faciliter le filtrage

---

## 📊 Flow de Logs Attendus

### Scénario Normal (Succès)

```
1. [WEBHOOK] ✅ Processed BUY trade for 0xa7a84f34... (copy_leader)
2. [WEBHOOK] 📤 Publishing to Redis PubSub for 0xa7a84f34...
3. [WEBHOOK_REDIS] 📤 Publishing BUY to channel copy_trade:0xa7a84f34...
4. [WEBHOOK_REDIS] ✅ Published BUY to copy_trade:0xa7a84f34..., subscribers: 1
5. [COPY_TRADE] 🚀 Received BUY trade from 0xa7a84f34... (tx_id: ..., channel: copy_trade:...)
6. [COPY_TRADE] 🔍 Address info for 0xa7a84f34...: is_watched=True, address_type=copy_leader
7. [COPY_TRADE] ✅ Found watched address: id=1, address_type=copy_leader, is_active=True
8. [COPY_TRADE] 🔄 Found 1 active followers for leader 0xa7a84f34... (watched_address_id=1, tx_id=...)
9. [COPY_TRADE] 📋 Creating task for follower user_id=1 (allocation_id=15, mode=fixed_amount)
10. [COPY_TRADE] 💰 Executing BUY trade for user 6500527972: $2.00 on market ... (YES) (allocation_id=15, tx_id=...)
11. [TRADE] 🎯 Executing IOC order: user=6500527972, market=..., outcome=YES, amount=$2.00, dry_run=False, is_copy_trade=True
12. [TRADE] ⚡ Calling _execute_trade for user 6500527972: market=..., outcome=YES, amount=$2.00, is_copy_trade=True
13. [TRADE] 📈 _execute_trade result for user 6500527972: success=True, error=None, order_id=...
14. [TRADE] ✅ Trade executed successfully for user 6500527972: order_id=..., tokens=..., usd_spent=..., is_copy_trade=True
15. [COPY_TRADE] 📊 Trade execution result for user 6500527972: status=executed, error=None
16. [COPY_TRADE] ✅ Copied BUY trade: $2.00 for user 6500527972
17. [COPY_TRADE] ✅ Completed: 1/1 successful, 0 failed (tx_id=...)
```

### Scénario Problème: Listener Non Démarré

```
1. [WEBHOOK] ✅ Processed BUY trade for 0xa7a84f34... (copy_leader)
2. [WEBHOOK] 📤 Publishing to Redis PubSub for 0xa7a84f34...
3. [WEBHOOK_REDIS] 📤 Publishing BUY to channel copy_trade:0xa7a84f34...
4. [WEBHOOK_REDIS] ✅ Published BUY to copy_trade:0xa7a84f34..., subscribers: 0
5. ⚠️ [WEBHOOK_REDIS] No subscribers for channel copy_trade:0xa7a84f34... - Copy Trading Listener may not be running!
```

### Scénario Problème: Aucune Allocation Active

```
1. [WEBHOOK] ✅ Processed BUY trade for 0xa7a84f34... (copy_leader)
2. [WEBHOOK_REDIS] ✅ Published BUY to copy_trade:0xa7a84f34..., subscribers: 1
3. [COPY_TRADE] 🚀 Received BUY trade from 0xa7a84f34...
4. [COPY_TRADE] ✅ Found watched address: id=1, address_type=copy_leader, is_active=True
5. [COPY_TRADE] ⏭️ No active followers for leader 0xa7a84f34... (watched_address_id=1)
```

---

## 🔧 Comment Diagnostiquer

### 1. Vérifier que le Listener est Démarré

**Dans les logs workers:**
```bash
tail -f logs/workers.log | grep COPY_TRADE
```

**Rechercher:**
- `✅ [COPY_TRADE] Copy Trading Listener started and listening for messages`
- `📡 [COPY_TRADE] Subscribing to pattern: copy_trade:*`

### 2. Vérifier la Réception des Messages Redis

**Dans les logs workers:**
```bash
tail -f logs/workers.log | grep "COPY_TRADE.*Received"
```

**Rechercher:**
- `🚀 [COPY_TRADE] Received BUY trade from ...`

### 3. Vérifier la Publication Redis

**Dans les logs API:**
```bash
tail -f logs/api.log | grep WEBHOOK_REDIS
```

**Rechercher:**
- `✅ [WEBHOOK_REDIS] Published ... subscribers: X`
- Si `subscribers: 0` → Le listener n'est pas démarré!

### 4. Vérifier l'Exécution des Trades

**Dans les logs workers:**
```bash
tail -f logs/workers.log | grep "\[COPY_TRADE\].*Executing\|\[TRADE\]"
```

**Rechercher:**
- `💰 [COPY_TRADE] Executing ... trade for user ...`
- `🎯 [TRADE] Executing ... order: user=...`

### 5. Vérifier les Erreurs

**Dans tous les logs:**
```bash
tail -f logs/*.log | grep -E "\[COPY_TRADE\]|\[TRADE\]|\[WEBHOOK_REDIS\]" | grep -E "❌|⚠️|Error"
```

---

## 🚨 Points de Vérification Critiques

### 1. Workers Service Doit Démarrer le Listener

**Fichier:** `workers.py` ligne 219

```python
copy_trading_listener = await _start_copy_trading_listener()
```

**Vérifier dans les logs:**
- `✅ Copy trading listener started`

### 2. Redis PubSub Doit Être Connecté

**Vérifier dans les logs workers:**
- `✅ Redis PubSub connected`
- `✅ [COPY_TRADE] Redis PubSub already connected`

### 3. Subscription Doit Être Active

**Vérifier dans les logs workers:**
- `✅ Subscribed to pattern: copy_trade:*`

### 4. Webhook Doit Publier avec Subscribers > 0

**Vérifier dans les logs API:**
- `✅ [WEBHOOK_REDIS] Published ... subscribers: 1` (ou plus)

---

## 📝 Commandes Utiles pour Debugging

### Voir tous les logs de copy trading en temps réel:
```bash
tail -f logs/workers.log logs/api.log | grep -E "\[COPY_TRADE\]|\[TRADE\]|\[WEBHOOK_REDIS\]"
```

### Voir uniquement les erreurs:
```bash
tail -f logs/workers.log logs/api.log | grep -E "\[COPY_TRADE\]|\[TRADE\]|\[WEBHOOK_REDIS\]" | grep -E "❌|⚠️|Error|Failed"
```

### Voir le flow complet pour un tx_id spécifique:
```bash
tail -f logs/workers.log logs/api.log | grep "0x00da3bffc295131867d9e36077a6db486ee4d757567e073f834e3bea42a4536e"
```

### Vérifier les allocations actives dans Supabase:
```sql
SELECT
  cta.id,
  cta.user_id,
  cta.leader_address_id,
  cta.is_active,
  wa.address as leader_address,
  u.telegram_user_id,
  u.stage
FROM copy_trading_allocations cta
JOIN watched_addresses wa ON cta.leader_address_id = wa.id
JOIN users u ON cta.user_id = u.id
WHERE wa.address = '0xa7a84f34481ec124fd38c5215d28a92e27e38552'
  AND cta.is_active = true;
```

---

## 🎯 Prochaines Étapes

1. **Redémarrer les services** avec les nouveaux logs
2. **Surveiller les logs** lors du prochain trade
3. **Identifier où le flow s'arrête** grâce aux logs détaillés
4. **Corriger le problème** identifié

---

## 📊 Métriques à Surveiller

- **Nombre de messages Redis reçus** vs **nombre de trades exécutés**
- **Taux de succès** des copy trades (success_count / total_count)
- **Temps entre webhook et exécution** du copy trade
- **Nombre de subscribers Redis** (doit être > 0)

---

**Note:** Les logs sont maintenant beaucoup plus détaillés et permettront d'identifier rapidement où le problème se situe dans le flow de copy trading.
