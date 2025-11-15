# Subsquid Continuous Indexing

## Le problème

L'indexeur Subsquid traite les blocs historiques (backfill) puis **s'arrête** au lieu de continuer à écouter les nouveaux blocs en temps réel.

### Pourquoi il s'arrête ?

Quand `processor.run()` termine le traitement de tous les blocs disponibles, il retourne normalement. Subsquid **ne boucle pas automatiquement** pour chercher de nouveaux blocs - c'est un comportement attendu.

**Note :** On ne peut pas appeler `processor.run()` plusieurs fois sur le même processor car Subsquid bloque les modifications après le premier démarrage.

## ✅ La solution : Script de restart automatique

On utilise un script bash qui relance automatiquement l'indexeur quand il termine son cycle.

### 🚀 Démarrage en mode continu

```bash
cd /Users/ulyssepiediscalzi/Documents/polycool_last2/py-clob-client-with-bots/apps/subsquid-silo-tests/indexer-ts

# Démarrer l'indexeur avec auto-restart
./start-continuous.sh
```

### 📊 Ce qui se passe

1. **Premier run** : Indexe les blocs manquants (ex: 78227587 → 78229667)
2. **Completion** : Le processor termine normalement
3. **Restart automatique** : Le script relance le processor après 5 secondes
4. **Boucle infinie** : Continue indéfiniment pour capturer tous les nouveaux blocs

### 🛑 Arrêter l'indexeur

Appuyez sur `Ctrl+C` pour arrêter proprement.

## 📝 Logs typiques

```
[CONTINUOUS] 🚀 Starting Subsquid indexer with auto-restart...
[CONTINUOUS] Press Ctrl+C to stop

[CONTINUOUS] ═══════════════════════════════════════════════
[CONTINUOUS] 🔄 Starting indexer (run #1) at 2024-10-27 14:30:00
[CONTINUOUS] ═══════════════════════════════════════════════

[MAIN] Starting processor...
last processed final block was 78227586
processing blocks from 78227587
using archive data source
prometheus metrics are served at port 45171

[MAIN] ✅ Processor completed (caught up to latest block)

[CONTINUOUS] ✅ Indexer completed normally (caught up to latest block)
[CONTINUOUS] ⏳ Waiting 5 seconds before checking for new blocks...

[CONTINUOUS] ═══════════════════════════════════════════════
[CONTINUOUS] 🔄 Starting indexer (run #2) at 2024-10-27 14:30:15
[CONTINUOUS] ═══════════════════════════════════════════════
...
```

## 🏗️ Architecture

### Configuration du Processor (`processor.ts`)

```typescript
export const processor = new EvmBatchProcessor()
    .setGateway('https://v2.archive.subsquid.io/network/polygon-mainnet')
    .setRpcEndpoint({
      url: process.env.RPC_POLYGON_HTTP || 'https://polygon-rpc.com',
      rateLimit: 10,
      maxBatchCallSize: 100
    })
    .setFinalityConfirmation(75)
    .setBlockRange({ from: 78200000 })
```

**Important :**
- ✅ Archive : Pour le backfill historique rapide
- ✅ RPC : Pour récupérer les blocs récents/actuels
- ✅ Block range : Définit le bloc de départ

### Déploiement en Production (Railway/PM2)

Pour un environnement de production, utilisez un process manager :

#### ✅ Option 1 : Railway (déjà configuré)

Le Dockerfile et `railway.json` sont déjà configurés pour utiliser le script de restart automatique.

**Configuration Railway actuelle :**

```json
{
  "deploy": {
    "startCommand": "./start-continuous.sh",
    "restartPolicyType": "ALWAYS",
    "restartPolicyMaxRetries": 0
  }
}
```

**Dockerfile :**

```dockerfile
# Make the continuous script executable
RUN chmod +x /app/start-continuous.sh

# Start the indexer with migration applied first, then use continuous restart script
CMD ["sh", "-c", "npx squid-typeorm-migration apply && /app/start-continuous.sh"]
```

**⚠️ Important pour Railway :**

- ✅ Le script bash `start-continuous.sh` gère la boucle infinie
- ✅ `restartPolicyType: ALWAYS` garantit que Railway redémarre le container si le script bash crashe
- ✅ Le script bash handle les restarts internes (pas besoin que Railway le fasse)
- ⚠️ Le script bash ne sortira jamais (boucle infinie), donc Railway ne le redémarrera jamais sauf crash

**Déploiement :**

```bash
# Commit les changements
git add .
git commit -m "Fix: Add continuous indexing with auto-restart"
git push origin main

# Railway va automatiquement déployer avec la nouvelle config
```

**Variables d'environnement Railway :**

Assurez-vous d'avoir ces variables configurées sur Railway :

```bash
DATABASE_URL=postgresql://user:pass@host:port/db?sslmode=require
RPC_POLYGON_HTTP=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY
NODE_OPTIONS=--dns-result-order=ipv4first
NODE_TLS_REJECT_UNAUTHORIZED=0
```

#### Option 2 : PM2 (si déployé sur VPS)

```bash
# Installer PM2
npm install -g pm2

# Créer fichier ecosystem.config.js
module.exports = {
  apps: [{
    name: 'subsquid-indexer',
    script: './start-continuous.sh',
    interpreter: '/bin/bash',
    autorestart: true,
    watch: false,
    max_memory_restart: '2G',
    env: {
      NODE_ENV: 'production',
      DATABASE_URL: 'postgresql://...',
      RPC_POLYGON_HTTP: 'https://polygon-mainnet.g.alchemy.com/v2/...'
    }
  }]
}

# Démarrer
pm2 start ecosystem.config.js

# Voir les logs
pm2 logs subsquid-indexer

# Status
pm2 status
```

## 🔧 Modifications apportées

### 1. `processor.ts`
- ✅ Ajout de `maxBatchCallSize: 100` pour éviter les timeouts RPC
- ✅ Configuration RPC simplifiée et consolidée
- ✅ Block range unique (suppression des ranges redondants dans addLog)

### 2. `main.ts`
- ✅ Suppression de la boucle `while(true)` qui causait l'erreur
- ✅ Message clair de completion pour le restart externe

### 3. `start-continuous.sh` (nouveau)
- ✅ Script bash qui relance automatiquement l'indexeur
- ✅ Gestion propre des erreurs et signaux
- ✅ Logs clairs avec compteur de cycles

## ⚠️ Notes importantes

1. **Latence normale** : Le processor s'exécute toutes les ~5-10 secondes, donc latence maximale de 10s pour détecter un nouveau bloc
2. **Webhooks intégrés** : Les transactions sont notifiées via webhook pour le copy trading (<10s de latence)
3. **Fallback polling** : Si le webhook échoue, le système de polling principal prendra le relais
4. **Pas de duplication** : L'upsert en DB évite les doublons si le processor redémarre

## 📈 Performance

- **Backfill** : ~10,000 blocs/minute (via Archive)
- **Real-time** : ~2 blocs/seconde (Polygon = 2s par bloc)
- **Latence** : 5-10 secondes max pour détecter une nouvelle transaction
- **Mémoire** : ~500MB-1GB en usage normal

## 🐛 Troubleshooting

### Le processor s'arrête toujours
✅ **Solution** : Utilisez `./start-continuous.sh` au lieu de `npm run start`

### Erreur "Settings modifications are not allowed"
✅ **Solution** : C'est normal si vous essayez de boucler sur `processor.run()`. Le script bash gère le restart proprement.

### Les nouveaux blocs ne sont pas indexés
- Vérifiez que le RPC_ENDPOINT est configuré
- Vérifiez les logs pour voir si le processor redémarre bien
- Vérifiez la hauteur du dernier bloc traité vs bloc actuel Polygon

### Connexion DB perdue
- Le script bash va automatiquement retry après 10 secondes
- Vérifiez la configuration Supabase (pooler, SSL, etc.)
