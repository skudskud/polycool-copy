# SKIP_DB = true - Explication Simple

**Date:** 2025-01-27
**Objectif:** Comprendre l'architecture micro-services et l'adaptation du code

---

## 🎯 Qu'est-ce que SKIP_DB = true ?

### Concept Simple

**SKIP_DB = true** signifie: **"Ce service n'a PAS accès direct à la base de données"**

C'est une variable d'environnement qui contrôle si le code peut faire des requêtes SQL directement ou doit passer par l'API.

---

## 🏗️ Architecture Micro-Services

### Pourquoi SKIP_DB?

Dans une architecture micro-services, chaque service a des responsabilités séparées:

```
┌─────────────────────────────────────────────────────────┐
│              SERVICE BOT (SKIP_DB=true)                 │
│  - Code du bot Telegram                                 │
│  - Handlers, callbacks                                  │
│  - ❌ PAS d'accès DB                                    │
│  - ✅ Utilise APIClient pour communiquer avec API       │
└───────────────────────┬─────────────────────────────────┘
                        │
                        │ HTTP Requests
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              SERVICE API (SKIP_DB=false)                │
│  - Endpoints REST                                       │
│  - ✅ Accès DB direct                                   │
│  - Traite les requêtes du bot                           │
└───────────────────────┬─────────────────────────────────┘
                        │
                        │ SQL Queries
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                    SUPABASE DB                          │
│  - Tables: users, positions, trades, etc.               │
└─────────────────────────────────────────────────────────┘
```

### Avantages

1. **Sécurité:** Le bot n'a pas les credentials DB
2. **Séparation:** Chaque service fait son job
3. **Scalabilité:** On peut avoir plusieurs instances du bot
4. **Maintenance:** Plus facile de changer la DB sans toucher le bot

---

## 🔍 Comment ça fonctionne dans le code?

### Vérification SKIP_DB

```python
import os

# Vérifie la variable d'environnement
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Si SKIP_DB=true → Pas d'accès DB
# Si SKIP_DB=false → Accès DB direct
```

### Deux Chemins dans le Code

#### ❌ AVANT (Accès DB Direct - Ne marche PAS si SKIP_DB=true)

```python
# ❌ MAUVAIS: Accès DB direct
async def get_user_positions(user_id):
    async with get_db() as db:
        result = await db.execute(
            select(Position).where(Position.user_id == user_id)
        )
        return result.scalars().all()
```

**Problème:** Si `SKIP_DB=true`, `get_db()` va échouer car pas de connexion DB.

#### ✅ APRÈS (Utilise APIClient si SKIP_DB=true)

```python
# ✅ BON: Utilise APIClient si SKIP_DB=true
import os
from core.services.api_client.api_client import get_api_client

SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

async def get_user_positions(user_id):
    if SKIP_DB:
        # Pas d'accès DB → Utilise API
        api_client = get_api_client()
        return await api_client.get_user_positions(user_id)
    else:
        # Accès DB direct
        async with get_db() as db:
            result = await db.execute(
                select(Position).where(Position.user_id == user_id)
            )
            return result.scalars().all()
```

---

## 📝 Règles d'Adaptation du Code

### Règle 1: Toujours vérifier SKIP_DB avant accès DB

```python
# ❌ MAUVAIS
async def get_user(user_id):
    async with get_db() as db:  # Va échouer si SKIP_DB=true
        ...

# ✅ BON
async def get_user(user_id):
    if SKIP_DB:
        api_client = get_api_client()
        return await api_client.get_user(user_id)
    else:
        async with get_db() as db:
            ...
```

### Règle 2: Utiliser les helpers existants

Certains helpers gèrent déjà SKIP_DB:

```python
# ✅ BON: get_user_data() gère déjà SKIP_DB
from core.services.user.user_helper import get_user_data

user_data = await get_user_data(user_id)
# Fonctionne avec ou sans SKIP_DB
```

### Règle 3: Services peuvent avoir accès DB

Les **services** (dans `core/services/`) peuvent avoir accès DB car ils sont utilisés par le **service API** qui a `SKIP_DB=false`.

**Exemple:**
```python
# core/services/copy_trading/service.py
# Ce service peut utiliser get_db() car il est appelé par:
# 1. Service API (SKIP_DB=false) → Accès DB ✅
# 2. Service Bot (SKIP_DB=true) → Via APIClient ✅
```

### Règle 4: Handlers doivent utiliser APIClient

Les **handlers** (dans `telegram_bot/handlers/`) sont dans le **service bot** qui a `SKIP_DB=true`.

**Exemple:**
```python
# telegram_bot/handlers/smart_trading/view_handler.py
# ✅ CORRIGÉ: Utilise APIClient si SKIP_DB=true

if SKIP_DB and api_client:
    result = await api_client.get_smart_trading_recommendations(...)
else:
    result = await smart_trading_service.get_paginated_recommendations(...)
```

---

## 🔄 Exemples Concrets

### Exemple 1: Get User Positions

#### ❌ Code qui ne marche PAS avec SKIP_DB=true

```python
# Dans un handler
async def show_positions(update, context):
    user_id = update.effective_user.id

    # ❌ Accès DB direct - Va échouer si SKIP_DB=true
    async with get_db() as db:
        result = await db.execute(
            select(Position).where(Position.user_id == user_id)
        )
        positions = result.scalars().all()

    # Affiche positions...
```

#### ✅ Code qui marche avec SKIP_DB=true

```python
# Dans un handler
import os
from core.services.api_client.api_client import get_api_client

SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

async def show_positions(update, context):
    user_id = update.effective_user.id

    if SKIP_DB:
        # ✅ Utilise API
        api_client = get_api_client()
        positions_data = await api_client.get_user_positions(user_id)
        positions = positions_data.get('positions', [])
    else:
        # Accès DB direct
        async with get_db() as db:
            result = await db.execute(
                select(Position).where(Position.user_id == user_id)
            )
            positions = result.scalars().all()

    # Affiche positions...
```

### Exemple 2: Smart Trading (Corrigé)

#### ❌ AVANT (Ne marchait pas avec SKIP_DB=true)

```python
# telegram_bot/handlers/smart_trading/view_handler.py

# ❌ Accès service direct (qui utilise DB)
smart_trading_service = SmartTradingService()

async def handle_smart_trading_command(update, context):
    result = await smart_trading_service.get_paginated_recommendations(...)
    # ❌ Échoue si SKIP_DB=true car service utilise get_db()
```

#### ✅ APRÈS (Marche avec SKIP_DB=true)

```python
# telegram_bot/handlers/smart_trading/view_handler.py

import os
from core.services.api_client.api_client import get_api_client

SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"
api_client = get_api_client() if SKIP_DB else None

async def handle_smart_trading_command(update, context):
    if SKIP_DB and api_client:
        # ✅ Utilise API
        result = await api_client.get_smart_trading_recommendations(...)
    else:
        # Service direct (si SKIP_DB=false)
        result = await smart_trading_service.get_paginated_recommendations(...)
```

---

## 🎯 Checklist pour Adapter le Code

### Quand tu écris du code dans un Handler:

- [ ] **Vérifie SKIP_DB** avant tout accès DB
- [ ] **Utilise APIClient** si SKIP_DB=true
- [ ] **Utilise helpers existants** qui gèrent déjà SKIP_DB (comme `get_user_data()`)
- [ ] **Teste avec SKIP_DB=true** et `SKIP_DB=false`

### Quand tu écris du code dans un Service:

- [ ] **Peut utiliser get_db()** car appelé par API service (SKIP_DB=false)
- [ ] **Mais peut aussi être appelé via API** depuis bot service
- [ ] **Vérifie si le service est appelé directement** depuis handlers

---

## 🔍 Comment Vérifier si le Code est Adapté?

### Test 1: Cherche les accès DB directs dans handlers

```bash
# Cherche get_db() dans les handlers
grep -r "get_db()" telegram_bot/handlers/

# Si tu trouves des résultats → Vérifie qu'ils sont dans un if SKIP_DB
```

### Test 2: Vérifie que les handlers utilisent APIClient

```bash
# Cherche APIClient dans les handlers
grep -r "api_client\|APIClient" telegram_bot/handlers/

# Devrait y avoir des résultats pour les handlers qui accèdent aux données
```

### Test 3: Teste avec SKIP_DB=true

```bash
# Dans le service bot
export SKIP_DB=true
python bot_only.py

# Si ça crash avec des erreurs DB → Code pas adapté
```

---

## 📊 Résumé Simple

### SKIP_DB = true (Service Bot)

```
Handlers → APIClient → HTTP → Service API → DB
```

**Règle:** Pas d'accès DB direct, utilise APIClient

### SKIP_DB = false (Service API)

```
Handlers → Services → DB direct
```

**Règle:** Accès DB direct OK

---

## ✅ Code Déjà Adapté

### Services qui gèrent déjà SKIP_DB:

- ✅ `get_user_data()` - Helper qui gère SKIP_DB
- ✅ `TradeService` - Vérifie SKIP_DB avant accès DB
- ✅ `CopyTradingService` - Peut être appelé via API ou direct
- ✅ Smart Trading handlers - **CORRIGÉ** pour utiliser APIClient

### Services qui doivent être appelés via API:

- ✅ `SmartTradingService` - Maintenant accessible via `APIClient.get_smart_trading_recommendations()`
- ✅ `CopyTradingService` - Accessible via `APIClient.subscribe_to_leader()`, etc.

---

## 🚨 Points d'Attention

### 1. Cache Redis

Le cache Redis fonctionne dans les deux cas (bot et API) car c'est un cache externe.

### 2. Services vs Handlers

- **Services** (`core/services/`): Peuvent avoir accès DB car utilisés par API
- **Handlers** (`telegram_bot/handlers/`): Doivent utiliser APIClient si SKIP_DB=true

### 3. Helpers

Certains helpers comme `get_user_data()` gèrent déjà SKIP_DB automatiquement. Utilise-les!

---

**Conclusion:** `SKIP_DB=true` signifie que le bot n'a pas accès DB et doit utiliser l'API. Le code doit vérifier cette variable et utiliser `APIClient` quand nécessaire.
