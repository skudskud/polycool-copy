# 🚀 Quick Start - Tests Bot Local

## ⚡ Démarrage Rapide (5 minutes)

### 1. Préparation

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild

# Vérification automatique
bash scripts/dev/test_bot_local.sh
```

### 2. Configuration .env

```bash
# Copier template si pas existant
cp env.template .env

# Éditer .env avec tes credentials
nano .env
```

**Minimum requis:**
```bash
BOT_TOKEN=ton_token_telegram
DATABASE_URL=postgresql://user:pass@host:port/db
ENCRYPTION_KEY=une_clé_exactement_32_caractères
REDIS_URL=redis://localhost:6379

# IMPORTANT: Désactiver services non implémentés
STREAMER_ENABLED=false
INDEXER_ENABLED=false
```

### 3. Démarrer le Bot

```bash
# Option 1: Direct
python3 main.py

# Option 2: Via uvicorn (recommandé)
uvicorn telegram_bot.main:app --reload --port 8000
```

### 4. Tester dans Telegram

1. Cherche ton bot dans Telegram
2. Envoie `/start`
3. **Attendu:** Message de bienvenue + adresse Solana + boutons
4. Envoie `/wallet`
5. **Attendu:** Affichage des 2 wallets

---

## ✅ Ce Qui Devrait Fonctionner

### Commandes
- ✅ `/start` - Crée user + wallets, affiche onboarding
- ✅ `/wallet` - Affiche wallets (Polygon + Solana)

### Callbacks (Boutons)
- ⚠️ Tous les boutons sont **vides** (pas encore implémentés)
- ⚠️ Cliquer dessus ne fait rien (normal pour l'instant)

### Services
- ✅ UserService - CRUD users
- ✅ WalletService - Génération wallets
- ✅ EncryptionService - Chiffrement clés
- ✅ PositionService - Gestion positions
- ✅ CacheManager - Cache Redis

---

## ⚠️ Ce Qui Ne Fonctionne Pas Encore

### Commandes
- ❌ `/markets` - "To be implemented"
- ❌ `/positions` - "To be implemented"
- ❌ `/smart_trading` - "To be implemented"
- ❌ `/copy_trading` - "To be implemented"
- ❌ `/referral` - "To be implemented"
- ❌ `/admin` - "To be implemented"

### Callbacks
- ❌ Tous les callbacks sont vides (pas d'implémentation)

### Features
- ❌ Trading (buy/sell)
- ❌ TP/SL monitoring
- ❌ Bridge SOL → USDC
- ❌ Indexer (on-chain tracking)

---

## 🚨 Dangers Potentiels

### 1. ⚠️ Imports Manquants

**Problème:** `telegram_bot/main.py` peut référencer des modules qui n'existent pas.

**Solution:** Vérifier avant de démarrer:
```bash
python3 scripts/dev/test_imports.py
```

### 2. ⚠️ Database Connection

**Problème:** Si DB inaccessible, bot crash.

**Solution:** Vérifier `DATABASE_URL` dans `.env`

### 3. ⚠️ Encryption Key

**Problème:** Si clé != 32 caractères, bot crash.

**Solution:** Générer nouvelle clé:
```python
import secrets
print(secrets.token_urlsafe(32))
```

### 4. ⚠️ Callbacks Vides

**Problème:** Boutons ne font rien (UX cassée).

**Impact:** Utilisateurs confus.

**Solution:** Implémenter callbacks ou désactiver boutons temporairement.

---

## 📊 Résumé État Actuel

### ✅ Fonctionnel (~40%)
- Infrastructure (Settings, Logging, DB)
- Core Services (User, Wallet, Encryption, Position, Cache)
- Start Handler (onboarding complet)
- Wallet Handler (affichage)
- Streamer (WebSocket components)
- Poller (fonctionne et ingère données)

### ⚠️ Partiel (~20%)
- Callbacks (enregistrés mais vides)
- Main Application (corrigé mais à tester)

### ❌ Non Implémenté (~40%)
- Markets/Positions Handlers
- Smart/Copy Trading
- Trading Logic
- Indexer

---

## 🎯 Prochaines Étapes

1. **Tester le bot** avec cette suite de tests
2. **Corriger les problèmes** détectés
3. **Implémenter Markets Handler** (priorité 1)
4. **Implémenter Positions Handler** (priorité 2)
5. **Implémenter Callbacks** (priorité 3)

---

**Pour plus de détails:** Voir `docs/STATUS_RECAP.md` et `docs/TEST_SUITE.md`
