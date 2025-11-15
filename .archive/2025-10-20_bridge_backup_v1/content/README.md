# 🌉 Solana → Polygon Bridge Module

Module d'intégration deBridge pour bridger SOL → USDC.e/POL sur Polygon, avec auto-swap QuickSwap et préparation automatique pour Polymarket.

## 📋 Vue d'ensemble

Ce module implémente le workflow complet suivant :

```
SOL (Solana)
    ↓
[deBridge API - Quote]
    ↓
[User Confirmation]
    ↓
[Build & Sign TX Solana]
    ↓
[Broadcast to Solana]
    ↓
[Wait for Polygon Credits]
    ↓
[QuickSwap: POL → USDC.e]
    ↓
Wallet Ready for Polymarket! 🎉
```

## 🏗️ Architecture

### Modules

#### 1. **solana_wallet_manager.py**
Gestion des wallets Solana par utilisateur (séparés des wallets Polygon)

**Fonctionnalités :**
- Génération de wallets Solana automatique par user
- Stockage sécurisé des clés privées
- Liaison avec adresses Polygon
- Support des Keypairs Solana (solders)

**API principale :**
```python
from solana.solana_wallet_manager import solana_wallet_manager

# Générer wallet Solana pour user
address, private_key = solana_wallet_manager.generate_solana_wallet_for_user(user_id)

# Récupérer Keypair pour signing
keypair = solana_wallet_manager.get_solana_keypair(user_id)
```

#### 2. **debridge_client.py**
Client API deBridge pour quotes et transactions cross-chain

**Fonctionnalités :**
- Fetch quotes SOL → USDC.e avec refuel POL
- Build transactions via deBridge API
- Tracking des ordres bridge
- Estimations de montants

**API principale :**
```python
from solana.debridge_client import debridge_client

# Obtenir quote
quote = debridge_client.get_quote(
    src_chain_id="7565164",  # Solana
    src_token=SOL_TOKEN_ADDRESS,
    dst_chain_id="137",  # Polygon
    dst_token=USDC_E_POLYGON,
    amount="5000000000",  # 5 SOL en lamports
    src_address=solana_address,
    dst_address=polygon_address,
    enable_refuel=True
)

# Build transaction
tx = debridge_client.build_transaction(quote, solana_address, blockhash)
```

#### 3. **solana_transaction.py**
Builder de transactions Solana (signing & broadcasting)

**Fonctionnalités :**
- Fetch recent blockhash
- Signature de transactions avec Keypair
- Broadcast vers Solana RPC
- Confirmation de transactions
- Gestion des balances SOL

**API principale :**
```python
from solana.solana_transaction import SolanaTransactionBuilder

builder = SolanaTransactionBuilder()

# Get blockhash
blockhash = await builder.get_recent_blockhash()

# Sign & send
signature = await builder.send_and_confirm_transaction(
    transaction_data=tx_bytes,
    keypair=user_keypair
)
```

#### 4. **quickswap_client.py**
Client DEX QuickSwap pour swaps POL → USDC.e

**Fonctionnalités :**
- Fetch quotes POL → USDC.e
- Exécution de swaps avec slippage protection
- Auto-swap de l'excès de POL (garde MIN_POL_RESERVE pour gas)
- Vérification des balances POL et USDC.e

**API principale :**
```python
from solana.quickswap_client import quickswap_client

# Quote
quote = quickswap_client.get_swap_quote(pol_amount=3.0)

# Auto-swap (garde 2.5 POL pour gas)
swapped_amount, tx_hash = quickswap_client.auto_swap_excess_pol(
    address=polygon_address,
    private_key=polygon_private_key,
    reserve_pol=2.5
)
```

#### 5. **bridge_orchestrator.py** 🎯
Orchestrateur principal coordonnant tout le workflow

**Fonctionnalités :**
- Workflow complet end-to-end
- Gestion d'état des bridges actifs
- Callbacks pour updates en temps réel
- Monitoring des confirmations Polygon
- Integration complète des étapes (a) à (i)

**API principale :**
```python
from solana.bridge_orchestrator import bridge_orchestrator

# Workflow complet automatique
result = await bridge_orchestrator.complete_bridge_workflow(
    user_id=telegram_user_id,
    sol_amount=5.0,
    polygon_address=user_polygon_address,
    polygon_private_key=user_polygon_private_key,
    status_callback=async_status_update_function
)
```

#### 6. **config.py**
Configuration centralisée du module bridge

**Variables clés :**
```python
# Solana
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
SOLANA_ADDRESS = os.getenv("SOLANA_ADDRESS")
SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")

# deBridge
DEBRIDGE_API_URL = "https://api.dln.trade/v1.0"
SOLANA_CHAIN_ID = "7565164"
POLYGON_CHAIN_ID = "137"

# QuickSwap
QUICKSWAP_ROUTER_V2 = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"
MIN_POL_RESERVE = 2.5  # POL à garder pour gas
MAX_SLIPPAGE_PERCENT = 1.0
```

## 🚀 Workflow Détaillé

### Étape par étape

#### **(a) Get Quote**
```python
quote = await bridge_orchestrator.get_bridge_quote(
    user_id=user_id,
    sol_amount=5.0,
    polygon_address="0x..."
)
# → Quote avec fees, output USDC.e, refuel POL
```

#### **(b) User Confirmation**
L'utilisateur confirme le quote via Telegram inline button

#### **(c) Get Recent Blockhash**
```python
blockhash = await solana_tx_builder.get_recent_blockhash()
# → Fresh blockhash pour transaction Solana
```

#### **(d) Build Transaction**
```python
tx = debridge_client.build_transaction(
    quote=quote,
    src_address=solana_address,
    recent_blockhash=blockhash
)
# → Transaction prête à signer
```

#### **(e) Sign Transaction**
```python
keypair = solana_wallet_manager.get_solana_keypair(user_id)
signed_tx = solana_tx_builder.sign_transaction(tx_data, keypair)
# → Transaction signée
```

#### **(f) Broadcast Transaction**
```python
signature = await solana_tx_builder.send_transaction(signed_tx)
# → TX hash Solana
# View on: https://solscan.io/tx/{signature}
```

#### **(g) Wait for Polygon Credits**
```python
result = await _wait_for_polygon_credit(
    polygon_address="0x...",
    order_id=debridge_order_id,
    timeout=600  # 10 minutes
)
# → Monitor balances POL + USDC.e toutes les 10s
```

#### **(h) QuickSwap Auto-Swap**
```python
swap_result = quickswap_client.auto_swap_excess_pol(
    address=polygon_address,
    private_key=polygon_private_key,
    reserve_pol=2.5
)
# → Swap (balance_POL - 2.5) → USDC.e
```

#### **(i) Wallet Ready!**
Le wallet est maintenant prêt pour trader sur Polymarket avec :
- USDC.e (bridgé + swappé)
- 2.5 POL (réservé pour gas fees)

## 📦 Installation

### 1. Dépendances
Ajoutées automatiquement dans `requirements.txt` :

```txt
# Solana bridge integration
solders>=0.18.0
solana>=0.30.0
base58>=2.1.1
```

### 2. Installation
```bash
cd "telegram bot v2/py-clob-server"
pip install -r requirements.txt
```

### 3. Configuration `.env`
Créer/modifier `.env` avec :

```bash
# Solana Configuration
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
SOLANA_ADDRESS=VotreAdresseSolanaIci
SOLANA_PRIVATE_KEY=VotreCléPrivéeSolanaIci

# deBridge (optionnel)
DEBRIDGE_API_KEY=VotreCléAPIDebridgeIci

# Polygon RPC (recommandé Alchemy/Infura)
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/VOTRE_KEY
```

## 🔌 Intégration Telegram Bot

### Méthode 1 : ConversationHandler (Recommandé)

Voir `telegram_integration_example.py` pour l'implémentation complète.

**Ajout dans `telegram_bot.py` :**

```python
from solana.bridge_orchestrator import bridge_orchestrator

# Dans setup_handlers()
bridge_conv_handler = ConversationHandler(
    entry_points=[CommandHandler("bridge", self.bridge_command)],
    states={
        AWAITING_SOL_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_sol_amount),
        ],
        CONFIRMING_BRIDGE: [
            CallbackQueryHandler(self.confirm_bridge_callback, pattern="^confirm_bridge_"),
        ],
    },
    fallbacks=[CommandHandler("cancel", self.cancel_bridge_command)],
)
self.app.add_handler(bridge_conv_handler)
```

### Méthode 2 : Simple Callback

```python
async def quick_bridge_callback(self, update: Update, context):
    """Quick bridge with default amount"""
    user_id = update.effective_user.id
    polygon_wallet = wallet_manager.get_user_wallet(user_id)

    result = await bridge_orchestrator.complete_bridge_workflow(
        user_id=user_id,
        sol_amount=5.0,  # Default
        polygon_address=polygon_wallet['address'],
        polygon_private_key=polygon_wallet['private_key'],
        status_callback=lambda msg: update.message.edit_text(msg)
    )
```

## 🧪 Tests

### Test unitaire de chaque module

```python
# Test wallet manager
from solana.solana_wallet_manager import solana_wallet_manager

address, pk = solana_wallet_manager.generate_solana_wallet_for_user(12345)
print(f"Wallet créé : {address}")

# Test deBridge quote
from solana.debridge_client import debridge_client

estimation = debridge_client.estimate_sol_to_usdc(sol_amount=5.0)
print(f"5 SOL → {estimation['usdc_output']} USDC.e")
print(f"Refuel: {estimation['pol_refuel']} POL")

# Test QuickSwap quote
from solana.quickswap_client import quickswap_client

quote = quickswap_client.get_swap_quote(pol_amount=3.0)
print(f"3 POL → {quote['usdc_out']} USDC.e")
```

### Test workflow complet

```python
import asyncio
from solana.bridge_orchestrator import bridge_orchestrator

async def test_bridge():
    result = await bridge_orchestrator.complete_bridge_workflow(
        user_id=12345,
        sol_amount=5.0,
        polygon_address="0xYourPolygonAddress",
        polygon_private_key="0xYourPrivateKey",
        status_callback=lambda msg: print(f"Status: {msg}")
    )
    print(f"Result: {result}")

asyncio.run(test_bridge())
```

## ⚙️ Configuration Avancée

### Modifier le reserve POL
```python
# Dans config.py
MIN_POL_RESERVE = 5.0  # Garder 5 POL au lieu de 2.5
```

### Modifier le slippage QuickSwap
```python
# Dans config.py
MAX_SLIPPAGE_PERCENT = 2.0  # 2% slippage au lieu de 1%
```

### Changer Solana RPC
```python
# Dans config.py ou .env
SOLANA_RPC_URL = "https://solana-mainnet.rpcpool.com"
```

### Utiliser Polygon testnet
```python
# Dans config.py
POLYGON_CHAIN_ID = "80001"  # Mumbai testnet
USDC_E_POLYGON = "0x..."    # USDC testnet
```

## 📊 Monitoring & Logs

Tous les modules incluent des logs détaillés :

```
🌉 BRIDGE QUOTE REQUEST
   User ID: 12345
   Amount: 5.0 SOL
========================================

📊 Requesting quote from deBridge...
   Source: 5000000000 on chain 7565164
   Destination: chain 137

✅ Quote received:
   Input: 5000000000 lamports SOL
   Output: 4987.50 USDC.e
   Refuel: 3000000000000000000 wei POL

🔗 Fetching recent blockhash from Solana...
✅ Got blockhash: 9fK7HQr3...

✍️ Signing transaction with Dv2eQDBh...
✅ Transaction signed successfully

📡 Broadcasting to Solana...
✅ Transaction sent! Signature: 3nZ8R...
   View on Solscan: https://solscan.io/tx/3nZ8R...

👀 Watching Polygon for credits...
✅ Credits detected on Polygon!
   USDC.e: +4987.50
   POL: +3.0

🔄 QUICKSWAP AUTO-SWAP
========================================
💰 POL balance: 3.0 POL
🔄 Auto-swapping 0.5 POL (keeping 2.5 POL for gas)

✅ Swap complete!
   Swapped: 0.5 POL → USDC.e

✅ WORKFLOW COMPLETED SUCCESSFULLY
```

## 🔐 Sécurité

### Bonnes pratiques

1. **Ne jamais commit les clés privées**
   - Utiliser `.env` (déjà dans `.gitignore`)
   - Variables d'environnement en production

2. **Backup des wallets**
   - `solana_wallets.json` est auto-backupé
   - Sauvegarder régulièrement

3. **Limites de montants**
   - Implémenter `MAX_BRIDGE_AMOUNT` si besoin
   - Validation côté serveur

4. **Rate limiting**
   - Limiter 1 bridge par user toutes les 5 min
   - Protéger contre spam

### Exemple rate limiting

```python
# Dans bridge_orchestrator.py
from time import time

user_last_bridge = {}

async def get_bridge_quote(self, user_id, sol_amount, polygon_address):
    # Check rate limit
    last_bridge = user_last_bridge.get(user_id, 0)
    if time() - last_bridge < 300:  # 5 minutes
        raise Exception("Please wait 5 minutes between bridges")

    # ... rest of method

    user_last_bridge[user_id] = time()
```

## 🐛 Debugging

### Check balances
```python
from solana.solana_transaction import SolanaTransactionBuilder
from solana.quickswap_client import quickswap_client

builder = SolanaTransactionBuilder()

# Solana balance
sol_balance = await builder.get_balance("VotreAdresseSolana")

# Polygon balances
pol_balance = quickswap_client.get_pol_balance("0xVotreAdressePolygon")
usdc_balance = quickswap_client.get_usdc_balance("0xVotreAdressePolygon")
```

### Check bridge status
```python
status = bridge_orchestrator.get_bridge_status(user_id)
print(f"Status: {status}")
```

### Check deBridge order
```python
order_status = debridge_client.get_order_status(order_id)
print(f"Order: {order_status}")
```

## 📈 Roadmap

### À implémenter
- [ ] Support multi-tokens (SOL, USDC, ETH → Polygon)
- [ ] Estimation de temps de bridge dynamique
- [ ] Retry automatique si échec
- [ ] History des bridges par user
- [ ] Dashboard analytics (volumes, fees)
- [ ] Support testnet (Devnet Solana + Mumbai Polygon)
- [ ] Webhooks deBridge pour notifications instantanées

### Optimisations futures
- [ ] Cache des quotes pendant 30s
- [ ] Batch multiple bridges
- [ ] MEV protection sur QuickSwap
- [ ] Alternative DEX si QuickSwap price pas optimal

## 🆘 Support & Contact

**Issues communes :**

1. **"Failed to get blockhash"**
   → Vérifier SOLANA_RPC_URL, essayer autre RPC

2. **"Swap failed"**
   → Vérifier balance POL suffisante
   → Augmenter MAX_SLIPPAGE_PERCENT

3. **"Bridge timeout"**
   → Augmenter BRIDGE_CONFIRMATION_TIMEOUT
   → Vérifier status order deBridge manuellement

4. **"No Solana wallet"**
   → User doit /start pour générer wallet

---

**🎉 Module créé par Claude pour polycool_git**

*Dernière mise à jour : 30 septembre 2025*
