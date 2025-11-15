# Guide de Dépannage - Test Local Multi-Services

Ce guide aide à résoudre les problèmes courants lors des tests locaux en mode production-like.

## Problèmes de Configuration

### Problème: Variables d'environnement manquantes

**Symptômes** :
```
❌ ENCRYPTION_KEY is not set
❌ DATABASE_URL is not set
```

**Solution** :
1. Vérifiez que `.env.local` existe :
   ```bash
   ls -la .env.local
   ```

2. Si absent, créez-le depuis le template :
   ```bash
   cp env.template .env.local
   ```

3. Remplissez les variables requises dans `.env.local`

4. Vérifiez la configuration :
   ```bash
   ./scripts/dev/verify-config.sh
   ```

### Problème: ENCRYPTION_KEY incorrecte

**Symptômes** :
```
❌ Encryption key must be exactly 32 characters
```

**Solution** :
1. Générez une nouvelle clé de 32 caractères :
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32)[:32])"
   ```

2. Mettez à jour dans `.env.local` :
   ```bash
   ENCRYPTION_KEY=votre_nouvelle_cle_32_caracteres
   ```

### Problème: API_URL incorrecte

**Symptômes** :
```
⚠️ API_URL points to non-local address
```

**Solution** :
1. Vérifiez que `API_URL` est défini pour local :
   ```bash
   grep API_URL .env.local
   ```

2. Si absent ou incorrect, ajoutez :
   ```bash
   API_URL=http://localhost:8000
   ```

## Problèmes de Services

### Problème: Redis n'est pas accessible

**Symptômes** :
```
❌ Redis is not accessible
Connection refused
```

**Solution** :
1. Vérifiez que Redis est démarré :
   ```bash
   docker compose -f docker-compose.local.yml ps redis
   ```

2. Si non démarré, démarrez-le :
   ```bash
   docker compose -f docker-compose.local.yml up -d redis
   ```

3. Vérifiez la connexion :
   ```bash
   redis-cli ping
   # Devrait retourner: PONG
   ```

4. Si Redis n'est pas dans Docker, démarrez-le localement :
   ```bash
   redis-server
   ```

### Problème: API Service ne démarre pas

**Symptômes** :
```
❌ API service is not running
Connection refused
```

**Solution** :
1. Vérifiez les logs :
   ```bash
   tail -f logs/api.log
   ```

2. Vérifiez que le port 8000 n'est pas déjà utilisé :
   ```bash
   lsof -i :8000
   ```

3. Si le port est occupé, tuez le processus :
   ```bash
   kill $(lsof -ti:8000)
   ```

4. Redémarrez l'API :
   ```bash
   ./scripts/dev/start-api.sh
   ```

5. Vérifiez que l'API répond :
   ```bash
   curl http://localhost:8000/health/live
   ```

### Problème: Bot Service ne peut pas se connecter à l'API

**Symptômes** :
```
❌ API service health check failed
Bot may not function correctly if API is unavailable
```

**Solution** :
1. Vérifiez que l'API est démarrée :
   ```bash
   curl http://localhost:8000/health/live
   ```

2. Vérifiez que `API_URL` est correct dans `.env.local` :
   ```bash
   grep API_URL .env.local
   ```

3. Vérifiez les logs du bot :
   ```bash
   tail -f logs/bot.log
   ```

4. Redémarrez le bot après avoir démarré l'API :
   ```bash
   ./scripts/dev/start-bot.sh
   ```

### Problème: Workers Service ne démarre pas

**Symptômes** :
```
❌ Database initialization failed
❌ Workers service not running
```

**Solution** :
1. Vérifiez que `DATABASE_URL` est défini :
   ```bash
   grep DATABASE_URL .env.local
   ```

2. Vérifiez la connexion à la base de données :
   ```bash
   ./scripts/dev/verify-config.sh
   ```

3. Vérifiez les logs des workers :
   ```bash
   tail -f logs/workers.log
   ```

4. Vérifiez que `SKIP_DB=false` pour les workers (défini dans `start-workers.sh`)

## Problèmes d'Intégration

### Problème: Handlers utilisent l'accès DB direct

**Symptômes** :
```
❌ Handler has direct DB access without SKIP_DB check
```

**Solution** :
1. Vérifiez les handlers problématiques :
   ```bash
   ./scripts/dev/verify-handlers-skip-db.sh
   ```

2. Les handlers doivent utiliser `APIClient` quand `SKIP_DB=true`

3. Vérifiez que le bot utilise bien `SKIP_DB=true` :
   ```bash
   grep SKIP_DB logs/bot.log
   ```

### Problème: Cache Redis ne fonctionne pas

**Symptômes** :
```
⚠️ Cache key not found
⚠️ No cache keys found
```

**Solution** :
1. Vérifiez que Redis est accessible :
   ```bash
   redis-cli ping
   ```

2. Testez le cache :
   ```bash
   ./scripts/dev/test-cache-integration.sh
   ```

3. Vérifiez les clés de cache :
   ```bash
   redis-cli KEYS "api:*"
   ```

4. Vérifiez que `REDIS_URL` est correct :
   ```bash
   grep REDIS_URL .env.local
   ```

### Problème: Workers ne démarrent pas correctement

**Symptômes** :
```
⚠️ Poller services not found in logs
⚠️ Streamer service not launched
```

**Solution** :
1. Vérifiez les logs des workers :
   ```bash
   tail -f logs/workers.log
   ```

2. Vérifiez les feature flags dans `.env.local` :
   ```bash
   grep -E "STREAMER_ENABLED|POLLER_ENABLED|TPSL_MONITORING_ENABLED" .env.local
   ```

3. Testez les workers :
   ```bash
   ./scripts/dev/test-workers.sh
   ```

4. Redémarrez les workers :
   ```bash
   ./scripts/dev/start-workers.sh
   ```

## Problèmes de Base de Données

### Problème: Connexion à Supabase échoue

**Symptômes** :
```
❌ Could not connect to Supabase database
Connection timeout
```

**Solution** :
1. Vérifiez que `DATABASE_URL` est correct :
   ```bash
   grep DATABASE_URL .env.local
   ```

2. Vérifiez la connexion :
   ```bash
   ./scripts/dev/verify-config.sh
   ```

3. Testez la connexion directement :
   ```bash
   python3 -c "
   import os
   from sqlalchemy import create_engine, text
   url = os.environ['DATABASE_URL']
   if not url.startswith('postgresql+'):
       url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
   engine = create_engine(url, connect_args={'connect_timeout': 5})
   with engine.connect() as conn:
       result = conn.execute(text('SELECT 1'))
       print('Connection OK')
   "
   ```

4. Vérifiez que vous utilisez le pooler Supabase (port 6543 ou 5432)

### Problème: Timeout de connexion à la DB

**Symptômes** :
```
Connection timeout
Database initialization failed
```

**Solution** :
1. Vérifiez votre connexion internet
2. Vérifiez que le pooler Supabase est accessible
3. Augmentez le timeout si nécessaire dans le code (non recommandé pour les tests)

## Problèmes de Logs

### Problème: Logs ne s'affichent pas

**Symptômes** :
```
Log file not found
```

**Solution** :
1. Vérifiez que les services sont démarrés :
   ```bash
   ./scripts/dev/verify-services.sh
   ```

2. Vérifiez que le répertoire `logs/` existe :
   ```bash
   ls -la logs/
   ```

3. Créez le répertoire si nécessaire :
   ```bash
   mkdir -p logs
   ```

4. Redémarrez les services pour générer les logs

### Problème: Trop de logs / Logs trop volumineux

**Symptômes** :
```
Log files are very large
```

**Solution** :
1. Vérifiez la taille des logs :
   ```bash
   du -h logs/*.log
   ```

2. Archivez les anciens logs :
   ```bash
   mkdir -p logs/archive
   mv logs/*.log logs/archive/
   ```

3. Redémarrez les services pour créer de nouveaux logs

## Problèmes de Tests

### Problème: Tests échouent

**Symptômes** :
```
❌ Tests failed
```

**Solution** :
1. Vérifiez que tous les services sont démarrés :
   ```bash
   ./scripts/dev/verify-services.sh
   ```

2. Exécutez les tests individuellement pour identifier le problème :
   ```bash
   ./scripts/dev/test-bot-api-integration.sh
   ./scripts/dev/test-cache-integration.sh
   ./scripts/dev/test-workers.sh
   ```

3. Vérifiez les logs pour plus de détails :
   ```bash
   tail -f logs/*.log
   ```

### Problème: Tests passent mais fonctionnalités ne marchent pas

**Symptômes** :
```
✅ Tests passed but features don't work
```

**Solution** :
1. Vérifiez que vous testez avec les bons services démarrés
2. Vérifiez les logs en temps réel :
   ```bash
   ./scripts/dev/monitor-all.sh
   ```
3. Testez manuellement via Telegram bot
4. Vérifiez que les données sont bien dans la base de données

## Commandes Utiles

### Vérification Rapide

```bash
# Vérifier la configuration
./scripts/dev/verify-config.sh

# Vérifier les services
./scripts/dev/verify-services.sh

# Vérifier les handlers
./scripts/dev/verify-handlers-skip-db.sh
```

### Tests

```bash
# Test bot-API integration
./scripts/dev/test-bot-api-integration.sh

# Test cache
./scripts/dev/test-cache-integration.sh

# Test workers
./scripts/dev/test-workers.sh

# Test end-to-end
./scripts/dev/test-e2e-scenarios.sh
```

### Monitoring

```bash
# Monitor tous les logs
./scripts/dev/monitor-all.sh

# Logs individuels
tail -f logs/api.log
tail -f logs/bot.log
tail -f logs/workers.log
```

### Redémarrage

```bash
# Arrêter tous les services
./scripts/dev/stop-all.sh

# Redémarrer tous les services
./scripts/dev/start-all.sh
```

## Obtenir de l'Aide

Si les problèmes persistent :

1. Vérifiez les logs détaillés :
   ```bash
   ./scripts/dev/monitor-all.sh
   ```

2. Exécutez tous les scripts de vérification :
   ```bash
   ./scripts/dev/verify-config.sh
   ./scripts/dev/verify-services.sh
   ./scripts/dev/verify-handlers-skip-db.sh
   ```

3. Consultez la documentation :
   - [Guide de Test Local Production-Like](LOCAL_TESTING_PRODUCTION_LIKE.md)
   - [Architecture WebSocket](ARCHITECTURE_WEBSOCKET_VERIFICATION.md)
   - [Audit Copy Trading & Smart Trading](AUDIT_COPY_SMART_TRADING.md)

4. Vérifiez les fichiers de configuration existants :
   - `QUICK_START_LOCAL.md`
   - `GUIDE_DEMARRAGE_LOCAL.md`
