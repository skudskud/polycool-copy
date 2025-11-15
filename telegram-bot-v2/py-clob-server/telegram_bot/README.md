# 🤖 Polymarket Telegram Trading Bot - Architecture Refactorisée

## 📋 Vue d'ensemble

Ce bot Telegram a été refactorisé depuis un monolithe de **~4000 lignes** vers une **architecture modulaire propre** avec séparation claire des responsabilités.

## 🏗️ Architecture

```
telegram_bot/
├── bot.py                      # Point d'entrée principal (~120 lignes)
├── session_manager.py          # Gestion des sessions utilisateur (~240 lignes)
│
├── handlers/                   # Interface Telegram (commandes & callbacks)
│   ├── setup_handlers.py       # /start, /help, /wallet, /fund, etc.
│   ├── trading_handlers.py     # /markets, /search, inputs montants
│   ├── position_handlers.py    # /positions, recovery commands
│   └── callback_handlers.py    # Tous les boutons inline
│
├── services/                   # Logique métier
│   ├── user_trader.py          # Trading avec wallet utilisateur
│   ├── trading_service.py      # Exécution des trades
│   ├── position_service.py     # Gestion positions & P&L
│   └── market_service.py       # Recherche & validation marchés
│
└── utils/                      # Utilitaires
    ├── validators.py           # Validation des inputs
    └── formatters.py           # Formatage messages Telegram
```

## 🎯 Principes de Design

### 1. **Séparation des Responsabilités**
- **Handlers** : Interface utilisateur uniquement (commandes Telegram)
- **Services** : Logique métier pure (trading, positions, marchés)
- **Utils** : Fonctions utilitaires réutilisables

### 2. **Injection de Dépendances**
```python
# Les services sont injectés dans les handlers
def register(app, session_manager, trading_service):
    handler = partial(markets_command, session_manager=session_manager)
    app.add_handler(CommandHandler("markets", handler))
```

### 3. **SessionManager Centralisé**
```python
# Accès unifié aux sessions utilisateur
session = session_manager.get(user_id)
session_manager.save_all_positions()
session_manager.load_all_positions()
```

### 4. **Services Découplés**
```python
# TradingService utilise PositionService
self.trading_service = TradingService(session_manager, position_service)

# Pas de dépendances circulaires
```

## 📊 Flux de Données

```
Telegram User
    ↓
[Handler] (setup/trading/position/callback)
    ↓
[Service] (trading/position/market)
    ↓
[SessionManager] ← → [PostgreSQL/Files]
    ↓
[External APIs] (Polymarket, Blockchain)
```

## 🔧 Utilisation

### Démarrer le Bot

```python
from telegram_bot.bot import TelegramTradingBot

bot = TelegramTradingBot()
bot.run()
```

### Ajouter un Nouveau Handler

```python
# Dans telegram_bot/handlers/my_new_handler.py
async def my_command(update, context, session_manager):
    user_id = update.effective_user.id
    session = session_manager.get(user_id)
    # Votre logique ici
    await update.message.reply_text("✅ Done!")

def register(app, session_manager):
    from functools import partial
    handler_with_deps = partial(my_command, session_manager=session_manager)
    app.add_handler(CommandHandler("mycommand", handler_with_deps))
```

### Ajouter un Nouveau Service

```python
# Dans telegram_bot/services/my_service.py
class MyService:
    def __init__(self, session_manager):
        self.session_manager = session_manager

    def do_something(self, user_id):
        session = self.session_manager.get(user_id)
        # Logique métier
        return result
```

## 📦 Modules Principaux

### `bot.py` - Point d'Entrée
- Initialise tous les services
- Enregistre tous les handlers
- Configure le bot Telegram
- Gère le cycle de vie

### `session_manager.py` - Gestion Sessions
- Interface unique pour accéder aux sessions
- Persistance PostgreSQL + fichiers
- Méthodes utilitaires (get, set, init_user, etc.)
- Compatible avec l'ancien code (`user_sessions` global)

### Services

#### `user_trader.py`
- Classe extraite du monolithe original
- Trading avec wallet utilisateur
- Méthodes : `speed_buy()`, `speed_sell()`, `monitor_order()`

#### `trading_service.py`
- Orchestration des trades
- Création des traders utilisateur
- Méthodes : `execute_buy()`, `execute_sell()`, `get_trader()`

#### `position_service.py`
- Gestion des positions
- Calcul P&L en temps réel
- Recovery et synchronisation
- Méthodes : `calculate_pnl()`, `sync_wallet_positions()`, etc.

#### `market_service.py`
- Recherche de marchés
- Validation
- Short IDs pour callbacks Telegram
- Méthodes : `get_market_by_id()`, `search_markets()`, etc.

### Handlers

#### `setup_handlers.py`
Commandes de configuration :
- `/start` - Création wallet
- `/help` - Aide
- `/wallet` - Détails wallet
- `/fund` - Instructions financement
- `/approve` - Approbations contrats
- `/balance` - Vérification balances

#### `trading_handlers.py`
Commandes de trading :
- `/markets` - Liste des marchés
- `/search` - Recherche par mot-clé
- Gestion des inputs de montants

#### `position_handlers.py`
Commandes de positions :
- `/positions` - Voir positions
- `/positionhealth` - Santé du stockage
- Recovery commands

#### `callback_handlers.py`
Router principal pour tous les boutons inline :
- `market_*` - Sélection marché
- `buy_*` / `sell_*` - Actions trading
- `conf_*` - Confirmations
- `pos_*` - Détails positions
- Et tous les autres callbacks

### Utilitaires

#### `validators.py`
- `validate_amount_input()` - Validation montants
- `validate_wallet_address()` - Validation adresses
- `validate_api_credentials()` - Validation API keys
- Et autres validateurs

#### `formatters.py`
- `format_market_info()` - Formatage marchés
- `format_position()` - Formatage positions
- `format_trade_confirmation()` - Confirmations
- `format_error_message()` - Messages d'erreur
- Et autres formatters

## 🔄 Migration depuis l'Ancien Code

### Import Changes

```python
# Avant
from telegram_bot import TelegramTradingBot, user_sessions

# Après
from telegram_bot.bot import TelegramTradingBot
from telegram_bot.session_manager import user_sessions
```

### Backward Compatibility

Le `user_sessions` global est maintenu pour compatibilité avec :
- `position_persistence.py`
- `postgresql_persistence.py`
- `main.py`

## 🧪 Testing

Pour tester le bot localement :

```bash
# Tester l'import
python3 -c "from telegram_bot.session_manager import session_manager; print('✅ OK')"

# Lancer le bot
python3 -m telegram_bot.bot
```

## 📈 Métriques de Refactorisation

### Avant
- **1 fichier** : `telegram_bot.py` (~4000 lignes)
- **77 méthodes** dans une seule classe
- Difficile à maintenir et tester

### Après
- **13 fichiers** modulaires
- **~2000 lignes** de logique séparée
- Architecture propre et testable
- Respect des principes SOLID

### Gains
- ✅ **Maintenabilité** : Code organisé par domaine
- ✅ **Testabilité** : Services isolés
- ✅ **Scalabilité** : Facile d'ajouter features
- ✅ **Lisibilité** : Fichiers de ~200-400 lignes max
- ✅ **Réutilisabilité** : Validators et formatters partagés

## 🚀 Prochaines Étapes

1. **Tests unitaires** pour chaque service
2. **Tests d'intégration** pour les handlers
3. **Documentation API** pour chaque service
4. **Monitoring** et logging amélioré
5. **CI/CD** pour validation automatique

## 📝 Notes de Développement

- **Pas de dépendances circulaires** : Architecture en couches
- **Lazy loading** : Services créés à l'initialization
- **Type hints** : Partout pour meilleure IDE experience
- **Docstrings** : Documentation inline pour chaque fonction
- **Error handling** : Try/except avec logging approprié

## 🤝 Contribution

Pour ajouter une feature :
1. Créer le service si nécessaire (`services/`)
2. Créer le handler (`handlers/`)
3. Enregistrer dans `bot.py`
4. Ajouter la documentation ici
5. Tester !

---

**Version**: 2.0 (Refactorée)
**Date**: Octobre 2024
**Auteur**: Architecture refactorisée pour scalabilité et maintenabilité
