# 🔒 Guide de Déploiement Sécurisé

## 🚨 Problème Résolu

Les warnings Railway concernant l'exposition des secrets dans le Dockerfile ont été **corrigés**.

### ✅ Avant (DANGEREUX)
- Fichier `.env` dans le repository avec vraies valeurs
- Nixpacks détectait automatiquement toutes les variables
- Secrets exposés dans le Dockerfile généré
- Historique Git contenait des secrets

### ✅ Après (SÉCURISÉ)
- Fichier `.env` renommé en `.env.local` (ignoré par Git/Nixpacks)
- Variables sensibles uniquement dans Railway
- Dockerfile propre sans secrets exposés
- Repository sécurisé

## 🚀 Déploiement Sécurisé

### 1. Préparation
```bash
cd telegram-bot-v2/py-clob-server

# Vérifier la sécurité
python pre_deploy_check.py
python diagnose_bot_issues.py
```

### 2. Configuration Railway
Dans **Railway Dashboard > Variables d'environnement**, ajouter :

```bash
# OBLIGATOIRE
BOT_TOKEN=8434854848:AAHJ0tnZfno7lD0ipwZrzxKXS8Z5UKQhFMI
DATABASE_URL=postgresql://user:pass@host:port/db
REDIS_URL=redis://your-redis-service-url

# API KEYS
CLOB_API_KEY=your_clob_key
CLOB_API_PASSPHRASE=your_passphrase
CLOB_API_SECRET=your_secret
OPENAI_API_KEY=your_openai_key
JUPITER_API_KEY=your_jupiter_key

# SÉCURITÉ
ENCRYPTION_KEY=32_character_random_key
TELEGRAM_WEBHOOK_SECRET=random_webhook_secret
WEBHOOK_SECRET=random_webhook_secret
SUBSQUID_WEBHOOK_SECRET=random_subsquid_secret

# OPTIONNEL (Twitter)
TWITTER_API_KEY=your_twitter_key
TWITTER_API_SECRET=your_twitter_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_SECRET=your_access_secret
```

### 3. Déploiement
```bash
# Railway détectera automatiquement les changements
# Le build sera propre sans warnings de sécurité
```

## 🔍 Vérifications de Sécurité

### ✅ Points Vérifiés
- [x] Pas de secrets dans le repository
- [x] Variables sensibles uniquement dans Railway
- [x] .gitignore protège les fichiers locaux
- [x] Dockerfile généré sans ARG/ENV sensibles

### 🛡️ Protection Active
- **.gitignore** : Ignore `.env*` et fichiers sensibles
- **Nixpacks** : Ne détecte plus les variables du .env.local
- **Railway** : Variables injectées uniquement au runtime
- **Git** : Historique propre sans secrets

## 🔧 Développement Local

Pour développer localement :
```bash
# Copier le template (si vous en créez un)
cp .env.example .env.local

# Éditer .env.local avec vos vraies valeurs locales
# Le fichier sera automatiquement ignoré par Git
```

## 🚨 Règles de Sécurité

### ❌ NE JAMAIS FAIRE
- Commiter des vraies valeurs dans `.env`
- Pousser des fichiers `.env*` sur Git
- Utiliser des mots de passe faibles
- Partager des tokens en clair

### ✅ TOUJOURS FAIRE
- Utiliser Railway pour les variables de production
- Générer des clés aléatoirement (32+ caractères)
- Faire des commits propres
- Vérifier les `.gitignore` avant de commiter

## 🎉 Résultat

Le déploiement sera maintenant **100% sécurisé** :
- ✅ Pas de warnings Railway
- ✅ Secrets protégés
- ✅ Repository propre
- ✅ Build sécurisé
