# ⚡ QUICKSTART - Démarrer l'Implémentation

**5 minutes pour setup environnement local**

---

## 📁 OÙ METTRE LE `.env`?

### ✅ RÉPONSE: À LA RACINE DU PROJET

```bash
polycool-rebuild/
├── .env              # ← ICI (votre fichier avec credentials RÉELS)
├── .env.example      # ← Template (committé dans git)
├── .gitignore        # ← Doit contenir ".env"
├── main.py
├── config/
├── core/
└── ...
```

### 🔒 IMPORTANT: Sécurité `.env`

```bash
# .gitignore (vérifier que .env est bien ignoré)
.env
.env.local
*.env.local
__pycache__/
*.pyc
venv/
.pytest_cache/
```

**⚠️ NE JAMAIS COMMIT `.env` AVEC VRAIES CREDENTIALS!**

---

## 🚀 SETUP EN 5 MINUTES

### 1. Créer le Projet (2 min)

```bash
# Créer dossier
cd /Users/ulyssepiediscalzi/Documents/polynuclear
mkdir polycool-rebuild
cd polycool-rebuild

# Structure basique
mkdir -p config core telegram_bot tests migrations scripts

# Virtual environment
python3.11 -m venv venv
source venv/bin/activate
```

### 2. Setup `.env` (1 min)

```bash
# Créer .env
touch .env

# Éditer avec vos credentials
nano .env  # ou VSCode, vim, etc.
```

**Template `.env`:**
```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_token_here

# Supabase (project: xxzdlbwfyetaxcmodiec)
SUPABASE_URL=https://xxzdlbwfyetaxcmodiec.supabase.co
SUPABASE_KEY=your_supabase_anon_key
DATABASE_URL=postgresql://postgres:[password]@db.xxzdlbwfyetaxcmodiec.supabase.co:5432/postgres

# Redis (local pour dev)
REDIS_URL=redis://localhost:6379/0

# Security (générer avec: python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())")
ENCRYPTION_KEY=your_32_byte_key_base64_encoded
ENCRYPTION_SALT=polymarket_trading_bot_v2_salt

# Polymarket
POLYGON_RPC_URL=https://polygon-rpc.com
CLOB_API_URL=https://clob.polymarket.com

# Feature Flags
USE_WEBSOCKET=true
USE_POLLER=true

# Logs
LOG_LEVEL=INFO
```

### 3. Docker Compose (1 min)

```bash
# Créer docker-compose.yml
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: polycool_dev
      POSTGRES_USER: polycool
      POSTGRES_PASSWORD: localdev123
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
EOF

# Start services
docker-compose up -d
```

### 4. Install Dependencies (1 min)

```bash
# Créer requirements.txt basique
cat > requirements.txt << 'EOF'
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-telegram-bot>=20.0
sqlalchemy>=2.0
psycopg2-binary>=2.9
redis>=5.0
cryptography>=41.0
python-dotenv>=1.0
web3>=6.0
solders>=0.18
eth-account>=0.10
pydantic>=2.0
httpx>=0.25
pytest>=7.4
pytest-asyncio>=0.21
black>=23.0
EOF

# Install
pip install -r requirements.txt
```

### 5. Test Setup (< 1 min)

```bash
# Test que tout fonctionne
python -c "import fastapi, sqlalchemy, redis, cryptography, web3; print('✅ All imports OK')"

# Test Docker services
docker-compose ps
# Should show postgres and redis as "Up"

# Test Redis
redis-cli ping
# Should return "PONG"
```

---

## 🎯 STRUCTURE INITIALE RECOMMANDÉE

```bash
polycool-rebuild/
├── .env                    # ← Vos credentials (JAMAIS commit)
├── .env.example            # ← Template (committé)
├── .gitignore
├── docker-compose.yml
├── requirements.txt
├── README.md
│
├── config/
│   └── __init__.py
│
├── core/
│   ├── __init__.py
│   ├── models/
│   │   └── __init__.py
│   ├── services/
│   │   └── __init__.py
│   └── repositories/
│       └── __init__.py
│
├── telegram_bot/
│   ├── __init__.py
│   └── handlers/
│       └── __init__.py
│
├── tests/
│   └── __init__.py
│
├── migrations/
│   └── 001_initial_schema.sql
│
└── main.py
```

---

## 📝 CRÉER FICHIERS DE BASE

### main.py (Entry Point)

```python
#!/usr/bin/env python3
"""
Polycool Telegram Bot - Main Entry Point
"""
import logging
from fastapi import FastAPI
import uvicorn

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(title="Polycool Bot")

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    port = 8000
    logger.info(f"🚀 Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
```

### config/__init__.py

```python
"""Configuration module"""
import os
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Validate required env vars
REQUIRED_VARS = [
    'TELEGRAM_BOT_TOKEN',
    'DATABASE_URL',
    'REDIS_URL',
    'ENCRYPTION_KEY'
]

for var in REQUIRED_VARS:
    if not os.getenv(var):
        raise ValueError(f"❌ Missing required env var: {var}")

print("✅ Environment variables loaded")
```

---

## ✅ VÉRIFICATION FINALE

```bash
# 1. Vérifier que .env existe et est ignoré
ls -la | grep .env
# Doit montrer .env et .env.example

git status
# .env NE DOIT PAS apparaître dans "Untracked files"

# 2. Test import config
python -c "import config; print('✅ Config OK')"

# 3. Test Docker services
docker-compose ps
# postgres et redis doivent être "Up"

# 4. Run app
python main.py
# Devrait démarrer sur http://localhost:8000

# 5. Test health endpoint
curl http://localhost:8000/health
# Devrait retourner {"status":"healthy"}
```

---

## 🚀 PROCHAINES ÉTAPES

### Phase 1: Architecture

1. **Lire** [01_PHASE_ARCHITECTURE.md](./01_PHASE_ARCHITECTURE.md)
2. **Créer tables SQL** (migrations/001_initial_schema.sql)
3. **Implémenter models** (core/models/)
4. **Setup repositories** (core/repositories/)
5. **Tests unitaires** (tests/unit/)

### Durée Phase 1: 3-4 jours

---

## 📚 RESSOURCES

### Documentation Plans
- [00_MASTER_PLAN.md](./00_MASTER_PLAN.md) - Vue d'ensemble
- [README_ARCHITECTURE.md](./README_ARCHITECTURE.md) - Architecture détaillée
- [SUMMARY.md](./SUMMARY.md) - Récapitulatif complet

### Code Existant à Réutiliser
```
/Users/ulyssepiediscalzi/Documents/polynuclear/polycool/telegram-bot-v2/py-clob-server/
```

### MCP Tools
- Supabase: `project xxzdlbwfyetaxcmodiec`
- Context7: Documentation APIs

---

## ❓ QUESTIONS FRÉQUENTES

**Q: Dois-je créer `.env.example`?**
A: Oui, avec template sans credentials. Committé dans git.

**Q: Où est le `.env` dans le dummy bot?**
A: Non présent. À créer manuellement à la racine.

**Q: Comment générer ENCRYPTION_KEY?**
A: `python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"`

**Q: Local DB ou Supabase?**
A: Local (Docker) pour dev, Supabase pour production.

---

**Setup complet en 5 minutes ✅**
**Prêt pour Phase 1 implementation 🚀**
