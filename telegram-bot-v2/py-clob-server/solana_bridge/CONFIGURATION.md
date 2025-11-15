# 🔧 Configuration du Module Bridge Solana

## Variables d'Environnement Requises

### 1. Configuration Solana

Créez ou modifiez votre fichier `.env` à la racine de `py-clob-server/` :

```bash
# Telegram Bot Configuration (REQUIS pour tests locaux)
TELEGRAM_BOT=VotreTokenBotTelegramIci
BOT_USERNAME=VotreUsernameBotIci

# Solana Configuration (REQUIS pour bridge)
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
SOLANA_ADDRESS=VotreAdresseSolanaPubliqueIci
SOLANA_PRIVATE_KEY=VotreCléPrivéeSolanaEnBase58Ici
```

#### Comment obtenir votre wallet Solana :

**Option A : Utiliser Phantom Wallet**
1. Installer Phantom : https://phantom.app/
2. Créer nouveau wallet
3. Exporter clé privée : Settings → Security & Privacy → Export Private Key
4. Copier l'adresse publique et la clé privée

**Option B : Utiliser Solana CLI**
```bash
# Installer Solana CLI
sh -c "$(curl -sSfL https://release.solana.com/stable/install)"

# Générer nouveau keypair
solana-keygen new --outfile ~/solana-wallet.json

# Obtenir l'adresse
solana-keygen pubkey ~/solana-wallet.json

# La clé privée est dans le fichier JSON
```

**Option C : Générer programmatiquement (Python)**
```python
from solders.keypair import Keypair

keypair = Keypair()
print(f"Address: {keypair.pubkey()}")
print(f"Private Key: {bytes(keypair.secret()).hex()}")
```

### 2. Configuration deBridge (Optionnel)

```bash
# deBridge API Key (optionnel, améliore rate limits)
DEBRIDGE_API_KEY=VotreCléAPIdeBridge
```

Obtenir une clé API : https://debridge.finance/

### 3. Configuration Polygon RPC (Recommandé)

```bash
# Option 1 : RPC public (gratuit mais limité)
POLYGON_RPC_URL=https://polygon-rpc.com

# Option 2 : Alchemy (recommandé pour production)
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/VOTRE_KEY

# Option 3 : Infura
POLYGON_RPC_URL=https://polygon-mainnet.infura.io/v3/VOTRE_KEY
```

**Obtenir une clé RPC :**
- Alchemy : https://dashboard.alchemy.com/ (gratuit jusqu'à 300M compute units/mois)
- Infura : https://infura.io/ (gratuit jusqu'à 100k requests/jour)

### 4. Configuration Telegram Bot

```bash
# Déjà configuré dans config.py
BOT_TOKEN=VotreBotTokenTelegram
```

## Configuration Avancée (Optionnelle)

### Paramètres de Bridge

Modifier dans `solana/config.py` :

```python
# Montant minimum de POL à garder pour gas
MIN_POL_RESERVE = 2.5  # Défaut: 2.5 POL

# Slippage maximum sur QuickSwap
MAX_SLIPPAGE_PERCENT = 1.0  # Défaut: 1%

# Timeout pour confirmation bridge
BRIDGE_CONFIRMATION_TIMEOUT = 600  # Défaut: 10 minutes

# Priority fee Solana
SOLANA_PRIORITY_FEE = 5000  # Défaut: 5000 lamports

# Gas price Polygon
POLYGON_GAS_PRICE_GWEI = 50  # Défaut: 50 gwei
```

### Alternative Solana RPCs

Si le RPC par défaut est lent :

```bash
# RPCPool (rapide)
SOLANA_RPC_URL=https://solana-mainnet.rpcpool.com

# Ankr (gratuit)
SOLANA_RPC_URL=https://rpc.ankr.com/solana

# QuickNode (payant, très rapide)
SOLANA_RPC_URL=https://VOTRE_ENDPOINT.quiknode.pro/
```

### Alternative Polygon RPCs

```bash
# Public RPCs
POLYGON_RPC_URL=https://rpc-mainnet.matic.network
POLYGON_RPC_URL=https://polygon-mainnet.public.blastapi.io
POLYGON_RPC_URL=https://rpc.ankr.com/polygon

# Payant (meilleure performance)
POLYGON_RPC_URL=https://VOTRE_ENDPOINT.quiknode.pro/
```

## Fichiers de Stockage

Le module créera automatiquement ces fichiers :

```
py-clob-server/
├── solana_wallets.json          # Wallets Solana des users
├── solana_wallets.json.backup   # Backup automatique
├── bridge_transactions.json     # Historique des bridges
```

### Format `solana_wallets.json`

```json
{
  "12345": {
    "address": "Dv2eQDBh...",
    "private_key": "3f4a7b...",
    "username": "user123",
    "created_at": 1696089600,
    "polygon_address": "0x..."
  }
}
```

## Sécurité

### ⚠️ IMPORTANT : Protection des Clés

1. **Ne JAMAIS commit le fichier `.env`**
   ```bash
   # Vérifier .gitignore contient :
   .env
   solana_wallets.json
   bridge_transactions.json
   ```

2. **Permissions fichiers**
   ```bash
   chmod 600 .env
   chmod 600 solana_wallets.json
   ```

3. **Backup sécurisé**
   ```bash
   # Sauvegarder .env et wallets de façon sécurisée
   tar -czf backup.tar.gz .env solana_wallets.json
   gpg -c backup.tar.gz  # Chiffrer avec mot de passe
   ```

4. **Production : Variables d'environnement**
   ```bash
   # Sur Railway/Heroku/etc
   railway variables set SOLANA_PRIVATE_KEY="..."
   heroku config:set SOLANA_PRIVATE_KEY="..."
   ```

## Vérification de Configuration

### Script de test

Créer `test_config.py` :

```python
#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from solana.solana_wallet_manager import solana_wallet_manager
from solana.debridge_client import debridge_client
from solana.quickswap_client import quickswap_client

load_dotenv()

print("🔍 Vérification de la configuration...\n")

# Check Solana
solana_address = os.getenv("SOLANA_ADDRESS")
solana_pk = os.getenv("SOLANA_PRIVATE_KEY")
solana_rpc = os.getenv("SOLANA_RPC_URL")

print(f"✓ Solana RPC: {solana_rpc}")
print(f"✓ Solana Address: {solana_address[:10]}...{solana_address[-10:] if solana_address else 'NOT SET'}")
print(f"✓ Solana Private Key: {'SET' if solana_pk else 'NOT SET'}\n")

# Check Polygon RPC
polygon_rpc = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
print(f"✓ Polygon RPC: {polygon_rpc}\n")

# Test connections
print("🔗 Test de connexion...\n")

# Test QuickSwap (Polygon)
try:
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(polygon_rpc))
    if w3.is_connected():
        print("✅ Polygon RPC: Connected")
        block = w3.eth.block_number
        print(f"   Latest block: {block}")
    else:
        print("❌ Polygon RPC: Not connected")
except Exception as e:
    print(f"❌ Polygon RPC Error: {e}")

# Test Solana RPC
try:
    import asyncio
    from solana.solana_transaction import SolanaTransactionBuilder

    async def test_solana():
        builder = SolanaTransactionBuilder()
        blockhash = await builder.get_recent_blockhash()
        if blockhash:
            print(f"✅ Solana RPC: Connected")
            print(f"   Blockhash: {blockhash[:16]}...")
        else:
            print("❌ Solana RPC: Failed to get blockhash")
        await builder.close()

    asyncio.run(test_solana())
except Exception as e:
    print(f"❌ Solana RPC Error: {e}")

print("\n✅ Configuration check complete!")
```

Exécuter :
```bash
python test_config.py
```

### Vérification manuelle

```bash
# Check .env existe
ls -la .env

# Check variables chargées
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('SOLANA_ADDRESS:', os.getenv('SOLANA_ADDRESS'))"

# Check Solana RPC
curl https://api.mainnet-beta.solana.com \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}'

# Check Polygon RPC
curl https://polygon-rpc.com \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
```

## Troubleshooting

### Erreur : "SOLANA_ADDRESS not set"

**Solution :**
```bash
# Vérifier .env existe et contient :
cat .env | grep SOLANA_ADDRESS

# Si vide, ajouter :
echo "SOLANA_ADDRESS=VotreAdresseIci" >> .env
```

### Erreur : "Failed to connect to Solana RPC"

**Solutions :**
1. Essayer autre RPC :
   ```bash
   export SOLANA_RPC_URL=https://rpc.ankr.com/solana
   ```

2. Vérifier firewall/proxy

3. Tester connectivité :
   ```bash
   curl https://api.mainnet-beta.solana.com
   ```

### Erreur : "Polygon RPC rate limited"

**Solutions :**
1. Utiliser Alchemy/Infura (meilleurs rate limits)
2. Implémenter retry logic
3. Utiliser multiple RPCs en fallback

### Erreur : "Invalid private key format"

**Solutions :**
1. Vérifier format :
   - Solana : base58 string OU hex string
   - Polygon : hex string commençant par 0x

2. Regénérer wallet si corrompu

## Migration Production

### Railway

```bash
# Set variables
railway variables set SOLANA_ADDRESS="..."
railway variables set SOLANA_PRIVATE_KEY="..."
railway variables set POLYGON_RPC_URL="https://polygon-mainnet.g.alchemy.com/v2/..."

# Deploy
railway up
```

### Heroku

```bash
# Set config vars
heroku config:set SOLANA_ADDRESS="..."
heroku config:set SOLANA_PRIVATE_KEY="..."
heroku config:set POLYGON_RPC_URL="..."

# Deploy
git push heroku main
```

### Docker

```dockerfile
# Dockerfile
FROM python:3.10

ENV SOLANA_ADDRESS=""
ENV SOLANA_PRIVATE_KEY=""
ENV POLYGON_RPC_URL=""

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

```bash
# Build & run
docker build -t polymarket-bot .
docker run -e SOLANA_ADDRESS="..." \
           -e SOLANA_PRIVATE_KEY="..." \
           -e POLYGON_RPC_URL="..." \
           polymarket-bot
```

---

**📝 Note :** Toujours tester en testnet (Devnet Solana + Mumbai Polygon) avant production !

**🔒 Sécurité :** Ne partagez JAMAIS vos clés privées. Utilisez des wallets dédiés pour les bots.
