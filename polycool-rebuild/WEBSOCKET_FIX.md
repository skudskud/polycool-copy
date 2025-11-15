# 🔧 Correction du WebSocket - Streaming de Prix

## ❌ Problème Identifié

Le WebSocket ne fonctionne pas actuellement pour **2 raisons principales** :

### 1. **STREAMER_ENABLED=false**
Le streamer est **désactivé** dans `.env.local` :
```bash
STREAMER_ENABLED=false
```

### 2. **Vérification des positions actives échoue avec SKIP_DB**
Quand `SKIP_DB=true`, le streamer ne peut pas vérifier les positions actives dans la DB au démarrage, donc le WebSocket ne démarre pas automatiquement.

## ✅ Solutions

### Solution 1 : Activer le Streamer

**Modifier `.env.local`** :
```bash
# Activer le streamer WebSocket
STREAMER_ENABLED=true
```

### Solution 2 : Amélioration du Code (Déjà Corrigé)

J'ai corrigé le code pour que le streamer puisse vérifier les positions actives via l'API quand `SKIP_DB=true`.

## 🚀 Comment Tester

1. **Activer le streamer** :
```bash
cd polycool-rebuild
# Modifier .env.local
echo "STREAMER_ENABLED=true" >> .env.local
```

2. **Redémarrer le bot** :
```bash
./scripts/dev/test-bot-simple.sh
```

3. **Vérifier les logs** :
Vous devriez voir :
```
🌐 Streamer Service starting...
✅ Active positions found - starting WebSocket client
🔌 Connecting to Polymarket CLOB WebSocket: wss://ws-subscriptions-clob.polymarket.com/ws/market
✅ WebSocket connected
📡 Subscribed to X token IDs from Y markets with active positions
```

4. **Tester avec un trade** :
- Exécutez un trade via le bot
- Les prix devraient se mettre à jour en temps réel via WebSocket

## 📊 Vérification du Statut

Le WebSocket devrait :
- ✅ Se connecter automatiquement au démarrage si positions actives
- ✅ S'abonner automatiquement après un trade
- ✅ Mettre à jour les prix en temps réel
- ✅ Se reconnecter automatiquement en cas de déconnexion

## 🔍 Diagnostic

Si le WebSocket ne fonctionne toujours pas après activation :

1. **Vérifier les logs** pour :
   - `⚠️ Streamer service disabled` → STREAMER_ENABLED=false
   - `⚠️ No active positions` → Normal, démarrera après premier trade
   - `❌ WebSocket error` → Problème de connexion

2. **Vérifier la configuration** :
```bash
grep STREAMER_ENABLED .env.local
grep CLOB_WSS_URL .env.local
```

3. **Vérifier les positions actives** :
Le streamer vérifie automatiquement les positions au démarrage et s'abonne aux marchés correspondants.
