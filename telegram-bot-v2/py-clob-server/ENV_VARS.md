# Variables d'Environnement Requises

Ce fichier liste toutes les variables d'environnement nécessaires pour faire fonctionner le bot.

## 🚨 Sécurité Importante
- **NE JAMAIS committer** de vraies valeurs dans le repository
- Les vraies valeurs doivent être configurées uniquement dans Railway
- Le fichier `.env.local` est ignoré par Git et Nixpacks

## Variables Obligatoires

### Bot Telegram
```bash
BOT_TOKEN=your_telegram_bot_token_here
```

### Base de Données
```bash
DATABASE_URL=postgresql://user:password@host:port/database
```

### Redis
```bash
REDIS_URL=redis://your-redis-url:6379
```

### API Polymarket
```bash
CLOB_API_KEY=your_clob_api_key
CLOB_API_PASSPHRASE=your_clob_passphrase
CLOB_API_SECRET=your_clob_secret
```

## Variables Optionnelles

### APIs Externes
```bash
OPENAI_API_KEY=your_openai_key
JUPITER_API_KEY=your_jupiter_key
ENCRYPTION_KEY=your_32_char_encryption_key
```

### Sécurité Webhook
```bash
TELEGRAM_WEBHOOK_SECRET=your_webhook_secret
WEBHOOK_SECRET=your_webhook_secret
SUBSQUID_WEBHOOK_SECRET=your_subsquid_secret
```

### Twitter Bot (si utilisé)
```bash
TWITTER_API_KEY=your_twitter_api_key
TWITTER_API_SECRET=your_twitter_api_secret
TWITTER_ACCESS_TOKEN=your_twitter_access_token
TWITTER_ACCESS_SECRET=your_twitter_access_secret
```

## Configuration dans Railway

1. Aller dans **Railway Dashboard > Variables d'environnement**
2. Ajouter chaque variable ci-dessus avec sa vraie valeur
3. Redéployer le service

## Développement Local

Pour le développement local :
1. Copier `.env.local` depuis `.env.example` (si disponible)
2. Remplir les vraies valeurs
3. Le fichier `.env.local` est automatiquement ignoré
