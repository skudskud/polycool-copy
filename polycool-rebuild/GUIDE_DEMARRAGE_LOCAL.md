# 🚀 Guide de Démarrage Local - Polycool Bot

**Guide pratique pour lancer le bot Telegram en local et faire les premiers tests**

---

## ✅ État Actuel du Projet

### Services Docker
- ✅ PostgreSQL: **En cours d'exécution** (port 5432)
- ✅ Redis: **En cours d'exécution** (port 6379)

### Dépendances Python
- ✅ Python 3.11.4 installé
- ✅ Dépendances principales installées
- ✅ Tous les imports fonctionnent

### Configuration
- ✅ Fichier `.env` présent
- ⚠️ À vérifier: Variables d'environnement configurées

---

## 📋 Checklist Pré-Démarrage

### 1. Vérifier le fichier `.env`

Assure-toi que les variables suivantes sont configurées dans `.env`:

```bash
# Minimum requis pour démarrer
BOT_TOKEN=ton_token_telegram_bot
DATABASE_URL=postgresql://polycool:polycool2025@localhost:5432/polycool_dev
ENCRYPTION_KEY=une_clé_exactement_32_caractères
REDIS_URL=redis://localhost:6379

# IMPORTANT: Désactiver services non implémentés pour éviter les erreurs
STREAMER_ENABLED=false
INDEXER_ENABLED=false
```

**⚠️ Note:** Si `ENCRYPTION_KEY` n'est pas exactement 32 caractères, génère-en une nouvelle:
```python
python3 -c "import secrets; print(secrets.token_urlsafe(32)[:32])"
```

### 2. Vérifier les Services Docker

```bash
# Vérifier que PostgreSQL et Redis sont en cours d'exécution
docker compose ps

# Si pas démarrés, lancer:
docker compose up -d postgres redis

# Vérifier les logs si problème
docker compose logs postgres
docker compose logs redis
```

### 3. Vérifier les Dépendances Python

```bash
# Installer les dépendances si nécessaire
pip install -e ".[dev]"

# OU
pip install -r requirements.txt
```

### 4. Tester les Imports

```bash
# Vérifier que tous les modules peuvent être importés
python3 scripts/dev/test_imports.py
```

**Résultat attendu:** `✅ All imports successful!`

---

## 🚀 Démarrage du Bot

### Option 1: Via le script de démarrage (Recommandé)

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
./scripts/dev/start.sh
```

### Option 2: Via Python directement

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
python3 main.py
```

### Option 3: Via uvicorn (pour développement avec reload)

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
uvicorn telegram_bot.main:app --reload --port 8000
```

### Option 4: Via Makefile

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
make start
```

---

## ✅ Vérification du Démarrage

### Logs Attendus au Démarrage

Si tout fonctionne correctement, tu devrais voir:

```
🚀 Starting Polycool Telegram Bot
✅ Database initialized
✅ Cache manager initialized
✅ Telegram bot initialized successfully
🚀 Starting Telegram bot...
✅ All services started successfully
```

### Endpoints Disponibles

Une fois démarré, le bot expose:

- **API Root:** http://localhost:8000/
- **Health Check:** http://localhost:8000/health
- **API Docs:** http://localhost:8000/docs
- **Webhook Telegram:** http://localhost:8000/webhook/telegram

### Tester le Health Check

```bash
curl http://localhost:8000/health
```

**Résultat attendu:**
```json
{"status": "healthy"}
```

---

## 🧪 Tests dans Telegram

### Test 1: Commande `/start`

1. Ouvre Telegram et cherche ton bot
2. Envoie `/start`
3. **Attendu:**
   - Message de bienvenue avec adresse Solana
   - 3 boutons: "I've Funded", "View Wallet", "Help"
   - Adresse Solana cliquable/copiable

**Vérification en DB:**
```sql
-- Se connecter à PostgreSQL
docker exec -it polycool-postgres psql -U postgres -d polycool_dev

-- Vérifier l'utilisateur créé
SELECT telegram_user_id, stage, polygon_address, solana_address FROM users;
```

### Test 2: Commande `/wallet`

1. Envoie `/wallet` au bot
2. **Attendu:**
   - Affichage des 2 wallets (Polygon + Solana)
   - Status (ONBOARDING ou READY)
   - Boutons: "Bridge SOL → USDC", "View Details", "Back"

### Test 3: Autres Commandes (Placeholders)

Ces commandes répondent "To be implemented" pour l'instant:

- `/markets` → "📊 Markets - To be implemented"
- `/positions` → "📈 Positions - To be implemented"
- `/smart_trading` → "🤖 Smart Trading - To be implemented"
- `/copy_trading` → "👥 Copy Trading - To be implemented"
- `/referral` → "👥 Referral - To be implemented"
- `/admin` → "⚡ Admin - To be implemented"

### Test 4: Callbacks (Boutons)

**⚠️ Important:** Les callbacks sont enregistrés mais **vides** pour l'instant.

- Cliquer sur les boutons ne fait rien (normal, pas encore implémentés)
- Pas d'erreur visible pour l'utilisateur
- Erreurs dans les logs si callback non géré

---

## 🔧 Dépannage

### Problème 1: Bot ne démarre pas

**Erreur:** `BOT_TOKEN environment variable not set!`

**Solution:**
```bash
# Vérifier que BOT_TOKEN est dans .env
grep BOT_TOKEN .env

# Si absent, ajouter:
echo "BOT_TOKEN=ton_token_ici" >> .env
```

### Problème 2: Erreur de connexion à la base de données

**Erreur:** `Connection refused` ou `database does not exist`

**Solution:**
```bash
# Vérifier que PostgreSQL est démarré
docker compose ps postgres

# Si pas démarré:
docker compose up -d postgres

# Vérifier la connexion
docker exec -it polycool-postgres psql -U postgres -d polycool_dev -c "SELECT 1;"
```

### Problème 3: Erreur Encryption Key

**Erreur:** `Encryption key must be exactly 32 characters`

**Solution:**
```bash
# Générer une nouvelle clé de 32 caractères
python3 -c "import secrets; print(secrets.token_urlsafe(32)[:32])"

# Mettre à jour dans .env
# ENCRYPTION_KEY=la_nouvelle_clé_générée
```

### Problème 4: Erreur Redis Connection

**Erreur:** `Connection refused` pour Redis

**Solution:**
```bash
# Vérifier que Redis est démarré
docker compose ps redis

# Si pas démarré:
docker compose up -d redis

# Tester la connexion
redis-cli ping
# Devrait retourner: PONG
```

### Problème 5: Erreur d'imports

**Erreur:** `ModuleNotFoundError: No module named 'xxx'`

**Solution:**
```bash
# Réinstaller les dépendances
pip install -e ".[dev]"

# OU
pip install -r requirements.txt
```

### Problème 6: Services non démarrés (STREAMER_ENABLED/INDEXER_ENABLED)

**Erreur:** `ImportError` ou `NameError` pour Streamer/Indexer

**Solution:**
```bash
# Désactiver dans .env
echo "STREAMER_ENABLED=false" >> .env
echo "INDEXER_ENABLED=false" >> .env
```

---

## 📊 Vérification de l'État

### Script de Vérification Automatique

```bash
# Lancer le script de test complet
bash scripts/dev/test_bot_local.sh
```

Ce script vérifie:
- ✅ Version Python
- ✅ Fichier .env
- ✅ Variables requises
- ✅ Dépendances installées
- ✅ Imports fonctionnels
- ✅ Tests unitaires rapides

### Vérification Manuelle

```bash
# 1. Vérifier les services Docker
docker compose ps

# 2. Vérifier les imports
python3 scripts/dev/test_imports.py

# 3. Vérifier la connexion DB
python3 scripts/dev/test_local_db.py

# 4. Vérifier Redis
redis-cli ping
```

---

## 🎯 Prochaines Étapes Après Démarrage

Une fois le bot démarré et testé avec `/start` et `/wallet`:

1. **Implémenter Markets Handler** (priorité 1)
   - Réutiliser le code existant de `telegram-bot-v2`
   - Intégrer avec la table `markets` unifiée

2. **Implémenter Positions Handler** (priorité 2)
   - Afficher portfolio avec P&L
   - Intégrer avec WebSocket pour prix temps réel

3. **Implémenter les Callbacks** (priorité 3)
   - Ajouter des handlers basiques pour éviter UX cassée
   - Implémenter les callbacks utilisés dans Start/Wallet handlers

4. **Tester le Trading Flow** (priorité 4)
   - Buy/Sell orders
   - TP/SL monitoring

---

## 📚 Ressources Utiles

### Documentation
- `docs/STATUS_RECAP.md` - État détaillé du projet
- `docs/QUICK_START_TESTING.md` - Guide de tests rapides
- `docs/TEST_SUITE.md` - Suite de tests complète

### Scripts Utiles
- `scripts/dev/setup.sh` - Setup initial complet
- `scripts/dev/start.sh` - Démarrage du bot
- `scripts/dev/test_bot_local.sh` - Tests locaux
- `scripts/dev/test_imports.py` - Test des imports

### Makefile Commands
```bash
make help          # Afficher toutes les commandes
make setup         # Setup initial
make start         # Démarrer le bot
make test          # Lancer les tests
make docker-up     # Démarrer Docker services
make docker-logs   # Voir les logs Docker
```

---

## ✅ Checklist Finale

Avant de commencer les tests:

- [ ] `.env` configuré avec `BOT_TOKEN`, `DATABASE_URL`, `ENCRYPTION_KEY`
- [ ] `STREAMER_ENABLED=false` et `INDEXER_ENABLED=false` dans `.env`
- [ ] Services Docker démarrés (PostgreSQL + Redis)
- [ ] Dépendances Python installées
- [ ] Imports testés (`python3 scripts/dev/test_imports.py`)
- [ ] Bot démarré sans erreur
- [ ] Health check répond (`curl http://localhost:8000/health`)
- [ ] `/start` fonctionne dans Telegram
- [ ] `/wallet` fonctionne dans Telegram

---

**🎉 Prêt à tester !**

Si tu rencontres des problèmes, vérifie les logs du bot et les logs Docker pour plus de détails.
