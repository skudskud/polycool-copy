# Guide de Test Local - Polycool Rebuild

## 🚀 Vérification Rapide (RECOMMANDÉ)

### Test Rapide Sans Pytest

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
python3 scripts/dev/quick_test.py
```

**OU** (version plus complète):

```bash
python3 scripts/dev/test_without_pytest.py
```

Ces scripts testent tout **sans utiliser pytest**, évitant les conflits avec `anchorpy`.

### Résultat Attendu

```
🚀 Quick Test Suite
==================================================
📦 Testing imports...
   ✅ All 12 imports OK

🔐 Testing EncryptionService...
   ✅ Encryption/Decryption OK

💼 Testing WalletService...
   ✅ Polygon wallet generation OK
   ✅ Solana wallet generation OK
   ✅ User wallet generation OK

==================================================
✅ 3/3 tests passed
🎉 All tests passed!
```

## 🐛 Problème avec Pytest

Si tu vois cette erreur :
```
TypeError: GetClusterNodes.__new__() missing 1 required positional argument: 'id'
```

C'est un conflit entre `anchorpy` (installé globalement) et pytest. **Solution** : Utilise les scripts de test sans pytest ci-dessus.

## ✅ Checklist de Vérification

### 1. Vérifier l'Environnement

```bash
# Vérifier Python version (3.9+ requis)
python3 --version

# Vérifier que vous êtes dans le bon dossier
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
```

### 2. Installer les Dépendances

```bash
# Installer toutes les dépendances
pip install -r requirements.txt

# Vérifier les installations critiques
python3 -c "import fastapi; import telegram; import sqlalchemy; import websockets; import redis; import cryptography; print('✅ Toutes les dépendances installées')"
```

### 3. Vérifier les Imports

```bash
# Script de vérification automatique
python3 scripts/dev/test_imports.py
```

### 4. Test Rapide (SANS DB)

```bash
# Test rapide - fonctionne sans DB ni Redis
python3 scripts/dev/quick_test.py
```

### 5. Test Complet (SANS DB)

```bash
# Test complet de tous les services
python3 scripts/dev/test_without_pytest.py
```

## 🧪 Tests Unitaires (Si Pytest Fonctionne)

Si pytest fonctionne dans ton environnement :

```bash
# Tous les tests
pytest tests/unit/

# Tests spécifiques
pytest tests/unit/test_services.py
pytest tests/unit/test_user_service.py

# Avec coverage
pytest tests/unit/ --cov=core --cov=data_ingestion --cov=telegram_bot
```

## 🔍 Vérification Manuelle

### 1. Test Encryption Service

```python
# Dans un shell Python
python3
>>> from core.services.encryption.encryption_service import EncryptionService
>>> service = EncryptionService()
>>> encrypted = service.encrypt("test_key")
>>> print(encrypted)
>>> decrypted = service.decrypt(encrypted)
>>> print(decrypted)  # Devrait afficher "test_key"
```

### 2. Test Wallet Service

```python
>>> from core.services.wallet.wallet_service import WalletService
>>> service = WalletService()
>>> wallets = service.generate_user_wallets()
>>> print(wallets)
# Devrait afficher: polygon_address, polygon_private_key (encrypted), solana_address, solana_private_key (encrypted)
```

### 3. Test User Service (nécessite DB)

```python
>>> from core.services.user.user_service import user_service
>>> user = await user_service.create_user(
...     telegram_user_id=123456789,
...     username="testuser",
...     polygon_address="0x...",
...     polygon_private_key="encrypted",
...     solana_address="...",
...     solana_private_key="encrypted"
... )
>>> print(user)
```

## 🐛 Dépannage

### Erreur: Module not found

```bash
# Vérifier que vous êtes dans le bon dossier
pwd
# Devrait être: .../polycool-rebuild

# Réinstaller les dépendances
pip install -r requirements.txt --force-reinstall
```

### Erreur: Database connection

```bash
# Vérifier que DATABASE_URL est configuré dans .env
cat .env | grep DATABASE_URL

# Tester la connexion (nécessite DB active)
python3 -c "from core.database.connection import get_db; print('✅ DB connection OK')"
```

### Erreur: Encryption key

```bash
# Vérifier que ENCRYPTION_KEY est configuré (32 caractères)
cat .env | grep ENCRYPTION_KEY

# Générer une nouvelle clé si nécessaire
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Erreur: Pytest avec anchorpy

Si pytest échoue avec l'erreur `GetClusterNodes`, utilise les scripts de test sans pytest :
- `python3 scripts/dev/quick_test.py`
- `python3 scripts/dev/test_without_pytest.py`

## ✅ Checklist de Vérification

- [ ] Python 3.9+ installé
- [ ] Dépendances installées (`pip install -r requirements.txt`)
- [ ] Fichier `.env` configuré avec:
  - [ ] `BOT_TOKEN`
  - [ ] `DATABASE_URL`
  - [ ] `ENCRYPTION_KEY` (32 caractères)
  - [ ] `REDIS_URL`
- [ ] Imports fonctionnent (`python scripts/dev/test_imports.py`)
- [ ] Tests rapides passent (`python scripts/dev/quick_test.py`)
- [ ] Database accessible (si tests DB nécessaires)
- [ ] Redis accessible (si utilisé)

## 📝 Prochaines Étapes

Une fois que tout fonctionne:

1. **Tester le bot Telegram**
   ```bash
   python main.py
   ```

2. **Tester le Streamer** (nécessite WebSocket actif)
   ```python
   from data_ingestion.streamer.streamer import StreamerService
   streamer = StreamerService()
   await streamer.start()
   ```

3. **Tester les Handlers**
   - Envoyer `/start` au bot
   - Envoyer `/wallet` au bot

## 🔗 Ressources

- **Documentation complète**: `docs/rebuild/`
- **Architecture**: `docs/rebuild/README_ARCHITECTURE.md`
- **Plan d'implémentation**: `docs/rebuild/00_MASTER_PLAN.md`

## 📊 Résumé des Scripts de Test

| Script | Usage | Nécessite DB | Nécessite Redis |
|--------|-------|--------------|-----------------|
| `quick_test.py` | Test rapide imports + encryption + wallets | ❌ | ❌ |
| `test_without_pytest.py` | Test complet sans pytest | ❌ | ❌ |
| `test_imports.py` | Vérification imports seulement | ❌ | ❌ |
| `verify_setup.sh` | Vérification environnement complet | ❌ | ❌ |
| `pytest tests/unit/` | Tests unitaires complets | ✅ | ❌ |
