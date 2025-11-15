# 🧪 Suite de Tests - Bot Telegram Local

## 📋 Vue d'Ensemble

Cette suite de tests couvre tous les aspects fonctionnels du bot Telegram en environnement local.

**Prérequis:**
- Python 3.9+
- `.env` configuré
- Database accessible
- Redis accessible (optionnel)

---

## 🚀 Phase 1: Préparation

### 1.1 Vérification Environnement

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild

# Vérification automatique
bash scripts/dev/test_bot_local.sh
```

**Résultat attendu:**
- ✅ Python version OK
- ✅ .env existe avec variables requises
- ✅ Dépendances installées
- ✅ Imports OK

### 1.2 Configuration .env

**Variables REQUISES:**
```bash
BOT_TOKEN=ton_token_telegram_bot
DATABASE_URL=postgresql://user:pass@host:port/db
ENCRYPTION_KEY=une_clé_exactement_32_caractères
REDIS_URL=redis://localhost:6379
```

**Variables IMPORTANTES:**
```bash
# Désactiver services non implémentés
STREAMER_ENABLED=false  # ⚠️ Sinon crash (corrigé maintenant)
INDEXER_ENABLED=false   # ⚠️ Pas encore implémenté
```

### 1.3 Test Rapide (Sans DB)

```bash
python3 scripts/dev/quick_test.py
```

**Résultat attendu:**
```
✅ 3/3 tests passed
🎉 All tests passed!
```

---

## 🤖 Phase 2: Démarrage du Bot

### 2.1 Démarrer le Bot

```bash
# Option 1: Via main.py
python3 main.py

# Option 2: Via uvicorn (recommandé pour dev)
uvicorn telegram_bot.main:app --reload --port 8000
```

### 2.2 Vérifier les Logs de Démarrage

**Logs attendus:**
```
🚀 Starting Polycool Telegram Bot
✅ Database initialized
✅ Cache manager initialized
✅ Telegram bot initialized successfully
🚀 Starting Telegram bot...
✅ All services started successfully
```

**Si erreur:**
- Vérifier `.env` (BOT_TOKEN, DATABASE_URL, ENCRYPTION_KEY)
- Vérifier que database est accessible
- Vérifier imports dans `telegram_bot/main.py` (déjà corrigé)

---

## 📱 Phase 3: Tests Telegram Bot

### Test 1: `/start` - Nouvel Utilisateur

**Action:**
1. Ouvrir Telegram
2. Chercher ton bot
3. Envoyer `/start`

**Résultat attendu:**
```
🚀 WELCOME TO POLYMARKET BOT

👋 Hi [ton_username]!

Your wallets have been created:

🔶 SOLANA ADDRESS (for funding):
[adresse_solana_ici]

💡 Next Steps:
1️⃣ Send 0.1+ SOL (~$20) to address above
2️⃣ Click "I've Funded" button below
3️⃣ We'll auto-bridge to USDC + setup trading (30s)

✅ Tap address above to copy
```

**Boutons attendus:**
- [💰 I've Funded - Start Bridge]
- [💼 View Wallet Details]
- [❓ Help & FAQ]

**Vérifications:**
- ✅ User créé en DB avec `telegram_user_id` = ton ID
- ✅ `stage` = "onboarding"
- ✅ `polygon_address` et `solana_address` générés
- ✅ `polygon_private_key` et `solana_private_key` encryptés
- ✅ Adresse Solana cliquable/copiable

**Vérifier en DB:**
```sql
SELECT telegram_user_id, username, stage, polygon_address, solana_address
FROM users
WHERE telegram_user_id = [ton_id];
```

### Test 2: `/start` - Utilisateur Existant (Onboarding)

**Action:**
1. Envoyer `/start` à nouveau (même utilisateur)

**Résultat attendu:**
```
🚀 ONBOARDING IN PROGRESS

👋 Hi [ton_username]!

Your wallets are ready:

🔶 SOLANA ADDRESS:
[même_adresse_qu_avant]

📊 Status: ONBOARDING

💡 Next Steps:
1️⃣ Fund your Solana wallet with SOL
2️⃣ Click "I've Funded" to start bridge
3️⃣ Wait ~30s for setup to complete
```

**Boutons attendus:**
- [💰 I've Funded - Start Bridge]
- [💼 View Wallet]

**Vérifications:**
- ✅ Pas de duplication en DB (même user_id)
- ✅ Stage toujours "onboarding"
- ✅ Même adresse Solana

### Test 3: `/wallet`

**Action:**
1. Envoyer `/wallet`

**Résultat attendu:**
```
💼 YOUR WALLETS

🔷 POLYGON WALLET
📍 Address: [adresse_polygon]

🔶 SOLANA WALLET
📍 Address: [adresse_solana]

📊 Status: ONBOARDING

[🌉 Bridge SOL → USDC]
[💼 View Details]
[↩️ Back]
```

**Vérifications:**
- ✅ Adresses Polygon et Solana affichées
- ✅ Status correspond à DB
- ✅ Boutons présents

### Test 4: Callbacks - Boutons Non Implémentés

**Action:**
1. Cliquer sur "💰 I've Funded - Start Bridge"
2. Cliquer sur "💼 View Wallet Details"
3. Cliquer sur "🌉 Bridge SOL → USDC"

**Résultat attendu:**
- ⚠️ **Rien ne se passe** (normal, callbacks vides)
- ⚠️ Pas d'erreur visible pour l'utilisateur
- ⚠️ Erreur dans les logs (si callback non géré)

**Vérifications logs:**
```bash
# Vérifier qu'il n'y a pas d'erreurs fatales
# Les callbacks vides ne devraient pas causer de crash
```

### Test 5: Autres Commandes

**Actions:**
```bash
# Tester chaque commande une par une:
/start          # ✅ Devrait fonctionner (déjà testé)
/wallet         # ✅ Devrait fonctionner (déjà testé)
/markets        # ⚠️ "📊 Markets - To be implemented"
/positions      # ⚠️ "📈 Positions - To be implemented"
/smart_trading  # ⚠️ "🤖 Smart Trading - To be implemented"
/copy_trading   # ⚠️ "👥 Copy Trading - To be implemented"
/referral       # ⚠️ "👥 Referral - To be implemented"
/admin          # ⚠️ "⚡ Admin - To be implemented"
```

**Résultat attendu:**
- `/start` et `/wallet` → Fonctionnent ✅
- Autres commandes → Message "To be implemented" ⚠️

---

## 🗄️ Phase 4: Tests Database

### Test 1: Vérifier User Créé

```python
# Dans un shell Python
python3

>>> import asyncio
>>> from core.services.user.user_service import user_service
>>>
>>> async def test():
...     user = await user_service.get_by_telegram_id([ton_telegram_id])
...     print(f"User: {user}")
...     print(f"Stage: {user.stage if user else 'None'}")
...     print(f"Polygon: {user.polygon_address if user else 'None'}")
...     print(f"Solana: {user.solana_address if user else 'None'}")
...
>>> asyncio.run(test())
```

**Résultat attendu:**
- User existe
- Stage = "onboarding"
- Adresses Polygon et Solana présentes
- Clés privées encryptées (ne commencent pas par "0x" ou base58)

### Test 2: Vérifier Wallets Générés

```python
>>> from core.services.wallet.wallet_service import wallet_service
>>> from core.services.encryption.encryption_service import encryption_service
>>>
>>> # Générer wallets
>>> wallets = wallet_service.generate_user_wallets()
>>> print(wallets)
>>>
>>> # Vérifier encryption
>>> encrypted = wallets['polygon_private_key']
>>> decrypted = encryption_service.decrypt(encrypted)
>>> print(f"Decrypted: {decrypted[:10]}...")  # Premiers caractères seulement
```

**Résultat attendu:**
- Wallets générés avec toutes les clés
- Clés privées encryptées (base64)
- Décryptage fonctionne

---

## 🔍 Phase 5: Tests Services

### Test 1: EncryptionService

```python
>>> from core.services.encryption.encryption_service import EncryptionService
>>> service = EncryptionService()
>>>
>>> # Test encrypt/decrypt
>>> plaintext = "test_private_key_12345"
>>> encrypted = service.encrypt(plaintext)
>>> decrypted = service.decrypt(encrypted)
>>>
>>> assert decrypted == plaintext
>>> print("✅ Encryption OK")
```

### Test 2: WalletService

```python
>>> from core.services.wallet.wallet_service import WalletService
>>> service = WalletService()
>>>
>>> # Test Polygon
>>> addr, key = service.generate_polygon_wallet()
>>> assert addr.startswith("0x")
>>> assert len(addr) == 42
>>> print("✅ Polygon wallet OK")
>>>
>>> # Test Solana
>>> addr, key = service.generate_solana_wallet()
>>> assert len(addr) >= 32
>>> print("✅ Solana wallet OK")
```

### Test 3: UserService

```python
>>> from core.services.user.user_service import user_service
>>>
>>> # Test get user
>>> user = await user_service.get_by_telegram_id([ton_id])
>>> print(f"✅ User found: {user.username if user else 'None'}")
>>>
>>> # Test update stage
>>> if user:
...     success = await user_service.update_stage([ton_id], "ready")
...     print(f"✅ Stage updated: {success}")
```

---

## 📊 Phase 6: Vérification Logs

### Pendant les Tests

**Vérifier les logs pour:**
- ✅ Pas d'erreurs au démarrage
- ✅ Messages de log pour chaque commande
- ✅ Erreurs gracieusement gérées (pas de crash)
- ✅ Callbacks vides ne causent pas d'erreurs

**Commandes utiles:**
```bash
# Suivre les logs en temps réel
tail -f logs/bot.log  # Si logging vers fichier

# Ou regarder la sortie console
# Les logs devraient apparaître dans le terminal où le bot tourne
```

---

## ✅ Checklist Complète

### Avant de Démarrer
- [ ] Python 3.9+ installé
- [ ] Dépendances installées (`pip install -r requirements.txt`)
- [ ] `.env` configuré avec:
  - [ ] `BOT_TOKEN`
  - [ ] `DATABASE_URL`
  - [ ] `ENCRYPTION_KEY` (32 caractères)
  - [ ] `REDIS_URL`
- [ ] `STREAMER_ENABLED=false` (ou corrigé)
- [ ] `INDEXER_ENABLED=false`
- [ ] Database accessible
- [ ] Redis accessible (ou désactiver cache)

### Tests Fonctionnels
- [ ] Bot démarre sans erreur
- [ ] `/start` crée user en DB
- [ ] `/start` génère wallets (Polygon + Solana)
- [ ] `/start` affiche message de bienvenue
- [ ] `/wallet` affiche adresses
- [ ] Callbacks ne causent pas de crash
- [ ] Autres commandes répondent "To be implemented"

### Tests Database
- [ ] User créé avec bon `telegram_user_id`
- [ ] Stage = "onboarding"
- [ ] Wallets générés et stockés
- [ ] Clés privées encryptées
- [ ] Pas de duplication si `/start` répété

### Tests Services
- [ ] EncryptionService fonctionne
- [ ] WalletService génère wallets valides
- [ ] UserService CRUD fonctionne
- [ ] PositionService peut être instancié

---

## 🐛 Dépannage

### Erreur: "Bot token not configured"
**Solution:** Vérifier `BOT_TOKEN` dans `.env`

### Erreur: "Database connection failed"
**Solution:** Vérifier `DATABASE_URL` et que la DB est accessible

### Erreur: "Encryption key must be exactly 32 bytes"
**Solution:** Générer une nouvelle clé:
```python
import secrets
print(secrets.token_urlsafe(32))
```

### Erreur: "Module not found"
**Solution:**
```bash
pip install -r requirements.txt
python3 scripts/dev/test_imports.py
```

### Bot ne répond pas
**Vérifier:**
1. Bot démarre sans erreur
2. Token Telegram correct
3. Bot actif dans Telegram
4. Logs montrent réception des messages

### Callbacks ne fonctionnent pas
**Normal:** Callbacks sont vides (pas encore implémentés)
**Vérifier:** Pas d'erreurs dans les logs

---

## 📝 Résultats Attendus

### ✅ Succès Complet

Si tous les tests passent:
- ✅ Bot démarre
- ✅ `/start` fonctionne
- ✅ `/wallet` fonctionne
- ✅ User créé en DB
- ✅ Wallets générés
- ✅ Pas d'erreurs fatales

### ⚠️ Partiel

Si certains tests échouent:
- Vérifier logs pour erreurs spécifiques
- Vérifier configuration `.env`
- Vérifier connexions (DB, Redis)

### ❌ Échec

Si bot ne démarre pas:
- Vérifier imports dans `telegram_bot/main.py` (déjà corrigé)
- Vérifier toutes les variables `.env`
- Vérifier dépendances installées

---

## 🎯 Prochaines Étapes Après Tests

Une fois que les tests de base passent:

1. **Implémenter Markets Handler**
   - Réutiliser code existant
   - Hub, search, categories

2. **Implémenter Positions Handler**
   - Portfolio view
   - P&L calculation

3. **Implémenter Callbacks**
   - `start_bridge`
   - `view_wallet`
   - `markets_hub`

4. **Tester avec vraies données**
   - Markets depuis DB
   - Positions réelles

---

**Bon test ! 🚀**
