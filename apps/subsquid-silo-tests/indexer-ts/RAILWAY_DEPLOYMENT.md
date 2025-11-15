# 🚂 Railway Deployment - Subsquid Indexer

## ✅ Configuration actuelle (prête pour Railway)

Tous les fichiers sont déjà configurés pour fonctionner sur Railway avec indexation continue.

### Fichiers modifiés

1. **`railway.json`** - Configuration Railway avec restart automatique
2. **`Dockerfile`** - Utilise le script de boucle infinie
3. **`start-continuous.sh`** - Script bash qui relance l'indexeur automatiquement
4. **`processor.ts`** - Configuration RPC optimisée
5. **`main.ts`** - Suppression de la boucle while invalide

## 🚀 Déploiement sur Railway

### 1. Commit et Push

```bash
git add .
git commit -m "Fix: Add continuous indexing with auto-restart for Railway"
git push origin main
```

### 2. Variables d'environnement sur Railway

Assurez-vous que ces variables sont configurées dans votre projet Railway :

| Variable | Valeur | Description |
|----------|--------|-------------|
| `DATABASE_URL` | `postgresql://user:pass@host:port/db?sslmode=require` | Connexion Supabase avec SSL |
| `RPC_POLYGON_HTTP` | `https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY` | RPC Alchemy ou Infura |
| `NODE_OPTIONS` | `--dns-result-order=ipv4first` | Force IPv4 (résout ENETUNREACH) |
| `NODE_TLS_REJECT_UNAUTHORIZED` | `0` | Accepte les certificats Supabase pooler |

### 3. Railway Auto-Deploy

Railway va automatiquement :
1. ✅ Détecter le changement sur `main`
2. ✅ Builder avec le Dockerfile
3. ✅ Lancer `start-continuous.sh` qui boucle indéfiniment
4. ✅ Redémarrer le container si crash (grâce à `restartPolicyType: ALWAYS`)

## 📊 Ce qui se passe sur Railway

```
[Railway] Starting deployment...
[Railway] Building Dockerfile...
[Railway] Running migrations...
[Railway] Starting container...

[CONTINUOUS] 🚀 Starting Subsquid indexer with auto-restart...
[CONTINUOUS] Press Ctrl+C to stop

[CONTINUOUS] ═══════════════════════════════════════════════
[CONTINUOUS] 🔄 Starting indexer (run #1) at 2024-10-27 14:30:00
[CONTINUOUS] ═══════════════════════════════════════════════

[MAIN] Starting processor...
last processed final block was 78227586
processing blocks from 78227587
using archive data source

[MAIN] ✅ Processor completed (caught up to latest block)

[CONTINUOUS] ✅ Indexer completed normally
[CONTINUOUS] ⏳ Waiting 5 seconds before checking for new blocks...

[CONTINUOUS] ═══════════════════════════════════════════════
[CONTINUOUS] 🔄 Starting indexer (run #2) at 2024-10-27 14:30:15
[CONTINUOUS] ═══════════════════════════════════════════════
...
```

## 🔍 Vérifier que ça fonctionne

### Consulter les logs Railway

```bash
# Via Railway CLI
railway logs

# Ou via le dashboard Railway
# https://railway.app/project/YOUR_PROJECT/deployments
```

### Ce que vous devriez voir

✅ **Bon signe** :
- `[CONTINUOUS] 🔄 Starting indexer (run #X)` avec X qui augmente
- `processing blocks from XXXXX` avec des blocs qui progressent
- Pas d'erreurs `FATAL ERROR` ou `EvmBatchProcessor.assertNotRunning`

❌ **Mauvais signe** :
- Le processor crash et ne redémarre pas
- Erreur `Settings modifications are not allowed` (boucle while invalide)
- Le container se termine et Railway ne le redémarre pas

## ⚠️ Important : Pourquoi cette solution ?

### Le problème initial

Sur Railway, l'ancienne config utilisait :

```json
{
  "startCommand": "npm start",
  "restartPolicyType": "ON_FAILURE"
}
```

**Problème** : Quand le processor termine normalement (exit code 0), Railway ne le redémarre PAS car `ON_FAILURE` signifie "restart seulement sur erreur".

### La solution

```json
{
  "startCommand": "./start-continuous.sh",
  "restartPolicyType": "ALWAYS"
}
```

**Avantages** :
1. ✅ Le script bash boucle indéfiniment = le container ne termine jamais
2. ✅ Si le script bash crash, Railway le redémarre (policy ALWAYS)
3. ✅ Attente de 5 secondes entre chaque cycle = pas de spam de restarts
4. ✅ Logs clairs avec compteur de cycles

## 🐛 Troubleshooting Railway

### Le deployment fail avec "script not found"

```bash
# Vérifier que le script est bien dans le repo
git ls-files | grep start-continuous.sh

# Si absent, l'ajouter
git add apps/subsquid-silo-tests/indexer-ts/start-continuous.sh
git commit -m "Add continuous restart script"
git push
```

### Le processor ne redémarre pas après completion

✅ **Solution** : C'est normal maintenant ! Le script bash handle le restart automatiquement. Vous devriez voir `[CONTINUOUS] 🔄 Starting indexer (run #2)` après 5 secondes.

### Erreur "Permission denied" sur start-continuous.sh

Le Dockerfile devrait avoir :
```dockerfile
RUN chmod +x /app/start-continuous.sh
```

Si ce n'est pas le cas, ajoutez cette ligne et redéployez.

### Le container utilise trop de mémoire

Railway limite la RAM selon le plan. Si vous dépassez :
- **Free plan** : 512 MB
- **Hobby plan** : 8 GB

Surveillez avec `railway logs` et ajustez si nécessaire. L'indexeur devrait utiliser ~500MB-1GB normalement.

### Connexion DB timeout

Vérifiez que vous utilisez le **pooler Supabase** (pas la connexion directe) :

```
✅ aws-1-us-east-1.pooler.supabase.com:6543
❌ db.gvckzwmuuyrlcyjmgdpo.supabase.co:5432
```

Le pooler est IPv4 uniquement et compatible Railway.

## 📈 Monitoring

### Vérifier l'indexation en temps réel

Connectez-vous à Supabase et exécutez :

```sql
-- Dernier bloc indexé
SELECT MAX(block_number) as last_block
FROM user_transactions;

-- Transactions des 5 dernières minutes
SELECT COUNT(*) as recent_txs
FROM user_transactions
WHERE timestamp > NOW() - INTERVAL '5 minutes';
```

Si `last_block` augmente régulièrement, ça fonctionne ! 🎉

### Alertes recommandées

Configurez des alertes sur Railway si :
- Le container redémarre plus de 5 fois en 10 minutes
- L'utilisation CPU > 90% pendant 5 minutes
- L'utilisation RAM > 80% de la limite

## 🎯 Résumé

| Aspect | Status |
|--------|--------|
| Configuration | ✅ Prête |
| Dockerfile | ✅ Optimisé |
| Script auto-restart | ✅ Fonctionnel |
| Variables d'env | ⚠️ À configurer sur Railway |
| Déploiement | ✅ Commit + Push = Auto-deploy |

**Pour déployer :**

```bash
git add .
git commit -m "Fix: Continuous indexing for Railway"
git push origin main
```

Ensuite, vérifiez les logs Railway pour confirmer que ça tourne en boucle !
