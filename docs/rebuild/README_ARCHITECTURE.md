# 📐 ARCHITECTURE DE DOSSIER - Polycool Rebuild

**Contrainte:** Fichiers < 700 lignes (STRICT)
**Principe:** Modulaire, maintenable, testable

---

## 🎯 STRUCTURE PROPOSÉE

```
polycool-rebuild/
├── .env.example              # Template environment variables
├── .env                      # ❌ IGNORED - Variables locales (ne pas commit)
├── .gitignore
├── README.md
├── requirements.txt
├── docker-compose.yml        # Local dev (Postgres + Redis)
├── railway.json              # Railway deployment config
│
├── config/                   # ⚙️ Configuration centralisée
│   ├── __init__.py
│   ├── settings.py           # Environment variables loading (< 300 lignes)
│   ├── database.py           # DB connection + models (< 400 lignes)
│   ├── redis_config.py       # Redis client config (< 200 lignes)
│   └── constants.py          # Constants (TTLs, limits, etc.)
│
├── core/                     # 🔧 Business Logic & Services
│   ├── __init__.py
│   │
│   ├── models/               # 📊 Data models (SQLAlchemy)
│   │   ├── __init__.py
│   │   ├── user.py           # User model (< 300 lignes)
│   │   ├── market.py         # Market model (< 300 lignes)
│   │   ├── position.py       # Position model (< 300 lignes)
│   │   ├── trade.py          # Trade model (< 200 lignes)
│   │   ├── tpsl_order.py     # TP/SL model (< 200 lignes)
│   │   └── referral.py       # Referral models (< 200 lignes)
│   │
│   ├── services/             # 🛠️ Business logic services
│   │   ├── __init__.py
│   │   │
│   │   ├── user/
│   │   │   ├── __init__.py
│   │   │   ├── user_service.py       # User CRUD (< 400 lignes)
│   │   │   ├── wallet_service.py     # Wallet generation (< 300 lignes)
│   │   │   └── onboarding_service.py # Onboarding flow (< 300 lignes)
│   │   │
│   │   ├── trading/
│   │   │   ├── __init__.py
│   │   │   ├── market_service.py     # Market data (< 500 lignes)
│   │   │   ├── position_service.py   # Positions (< 500 lignes)
│   │   │   ├── trade_service.py      # Trade execution (< 600 lignes)
│   │   │   └── tpsl_service.py       # TP/SL logic (< 500 lignes)
│   │   │
│   │   ├── advanced/
│   │   │   ├── __init__.py
│   │   │   ├── smart_trading.py      # Smart wallets (< 600 lignes)
│   │   │   └── copy_trading.py       # Copy trading (< 600 lignes)
│   │   │
│   │   ├── blockchain/
│   │   │   ├── __init__.py
│   │   │   ├── bridge_service.py     # SOL → USDC (< 500 lignes)
│   │   │   └── approval_service.py   # Contract approvals (< 300 lignes)
│   │   │
│   │   ├── security/
│   │   │   ├── __init__.py
│   │   │   ├── encryption.py         # AES-256-GCM (< 300 lignes)
│   │   │   └── api_keys.py           # Polymarket API keys (< 200 lignes)
│   │   │
│   │   └── cache_manager.py          # ⭐ Cache centralisé (< 500 lignes)
│   │
│   ├── repositories/         # 💾 Data access layer
│   │   ├── __init__.py
│   │   ├── user_repo.py      # User queries (< 300 lignes)
│   │   ├── market_repo.py    # Market queries (< 400 lignes)
│   │   ├── position_repo.py  # Position queries (< 300 lignes)
│   │   └── trade_repo.py     # Trade queries (< 300 lignes)
│   │
│   └── utils/                # 🔧 Utility functions
│       ├── __init__.py
│       ├── formatters.py     # Text formatting (< 300 lignes)
│       ├── validators.py     # Input validation (< 200 lignes)
│       └── helpers.py        # Helper functions (< 300 lignes)
│
├── telegram_bot/             # 🤖 Telegram Bot Layer
│   ├── __init__.py
│   ├── bot.py                # Bot initialization (< 200 lignes)
│   │
│   ├── handlers/             # 📨 Command handlers
│   │   ├── __init__.py
│   │   │
│   │   ├── start/
│   │   │   ├── __init__.py
│   │   │   ├── onboarding.py         # /start logic (< 400 lignes)
│   │   │   └── funding_check.py      # Funding detection (< 300 lignes)
│   │   │
│   │   ├── wallet/
│   │   │   ├── __init__.py
│   │   │   ├── view.py               # /wallet display (< 300 lignes)
│   │   │   ├── bridge.py             # Bridge flow (< 400 lignes)
│   │   │   └── withdrawal.py         # Withdrawal (< 400 lignes)
│   │   │
│   │   ├── markets/
│   │   │   ├── __init__.py
│   │   │   ├── hub.py                # /markets hub (< 300 lignes)
│   │   │   ├── search.py             # Search logic (< 200 lignes)
│   │   │   ├── categories.py         # Category browsing (< 300 lignes)
│   │   │   └── detail.py             # Market detail (< 300 lignes)
│   │   │
│   │   ├── positions/
│   │   │   ├── __init__.py
│   │   │   ├── view.py               # /positions display (< 400 lignes)
│   │   │   ├── trade.py              # Buy/Sell (< 500 lignes)
│   │   │   └── tpsl.py               # TP/SL setup (< 400 lignes)
│   │   │
│   │   ├── smart_trading/
│   │   │   ├── __init__.py
│   │   │   ├── view.py               # Smart trading view (< 400 lignes)
│   │   │   └── quick_buy.py          # Quick buy logic (< 300 lignes)
│   │   │
│   │   ├── copy_trading/
│   │   │   ├── __init__.py
│   │   │   ├── setup.py              # Setup flow (< 500 lignes)
│   │   │   ├── budget.py             # Budget management (< 400 lignes)
│   │   │   └── execution.py          # Copy execution (< 500 lignes)
│   │   │
│   │   └── referral/
│   │       ├── __init__.py
│   │       ├── view.py               # /referral view (< 300 lignes)
│   │       └── claim.py              # Commission claims (< 300 lignes)
│   │
│   ├── callbacks/            # 🔘 Callback handlers
│   │   ├── __init__.py
│   │   ├── market_callbacks.py       # Market interactions (< 500 lignes)
│   │   ├── position_callbacks.py     # Position actions (< 400 lignes)
│   │   ├── tpsl_callbacks.py         # TP/SL callbacks (< 300 lignes)
│   │   └── copy_trading_callbacks.py # Copy trading (< 400 lignes)
│   │
│   └── middleware/           # 🔒 Middleware (auth, logging, etc.)
│       ├── __init__.py
│       ├── auth.py           # User authentication (< 200 lignes)
│       ├── logging.py        # Request logging (< 200 lignes)
│       └── error_handler.py  # Error handling (< 300 lignes)
│
├── data_ingestion/           # 📡 Data ingestion services
│   ├── __init__.py
│   │
│   ├── poller/
│   │   ├── __init__.py
│   │   ├── gamma_api.py              # Gamma API polling (< 600 lignes)
│   │   └── market_enricher.py        # Market enrichment (< 400 lignes)
│   │
│   ├── streamer/
│   │   ├── __init__.py
│   │   ├── websocket_client.py       # WebSocket client (< 500 lignes)
│   │   └── subscription_manager.py   # Subscriptions (< 400 lignes)
│   │
│   └── indexer/
│       ├── __init__.py
│       ├── blockchain_indexer.py     # On-chain indexing (< 600 lignes)
│       ├── watched_addresses.py      # Watched addresses (< 300 lignes)
│       └── webhook_handler.py        # Webhook receiver (< 400 lignes)
│
├── migrations/               # 📊 Database migrations
│   ├── 001_initial_schema.sql
│   ├── 002_add_tpsl_tables.sql
│   ├── 003_add_copy_trading.sql
│   └── ...
│
├── tests/                    # ✅ Tests (structure miroir de src)
│   ├── __init__.py
│   ├── conftest.py           # Pytest config + fixtures
│   │
│   ├── unit/                 # Tests unitaires (60% coverage)
│   │   ├── core/
│   │   │   ├── services/
│   │   │   │   ├── test_user_service.py
│   │   │   │   ├── test_market_service.py
│   │   │   │   └── ...
│   │   │   └── repositories/
│   │   │       └── ...
│   │   └── telegram_bot/
│   │       └── ...
│   │
│   ├── integration/          # Tests d'intégration (30%)
│   │   ├── test_onboarding_flow.py
│   │   ├── test_trading_flow.py
│   │   ├── test_tpsl_flow.py
│   │   └── ...
│   │
│   └── e2e/                  # Tests end-to-end (10%)
│       ├── test_user_journey.py
│       └── ...
│
├── scripts/                  # 🛠️ Utility scripts
│   ├── setup_local.sh
│   ├── run_migrations.py
│   ├── seed_data.py
│   └── ...
│
└── main.py                   # 🚀 Application entry point (< 150 lignes)
```

---

## 🔒 ENVIRONMENT VARIABLES (.env)

**⚠️ IMPORTANT:** Le fichier `.env` **NE DOIT PAS** être committé (ajouté à `.gitignore`)

### Template (.env.example)
```bash
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Database (Supabase)
SUPABASE_URL=https://xxzdlbwfyetaxcmodiec.supabase.co
SUPABASE_KEY=your_supabase_anon_key
DATABASE_URL=postgresql://user:pass@host:port/db

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
ENCRYPTION_KEY=base64_encoded_32_byte_key
ENCRYPTION_SALT=polymarket_trading_bot_v2_salt

# Polymarket
POLYGON_RPC_URL=https://polygon-rpc.com
CLOB_API_URL=https://clob.polymarket.com

# Feature Flags
USE_WEBSOCKET=true
USE_POLLER=true
USE_INDEXER=true

# Monitoring
SENTRY_DSN=optional_sentry_dsn
LOG_LEVEL=INFO
```

### Où Mettre le `.env`?
```bash
# Racine du projet
polycool-rebuild/
├── .env              # ← ICI (ignored par git)
├── .env.example      # ← Template committé
└── ...
```

---

## 📦 DEPENDENCIES (requirements.txt)

```txt
# Core
python>=3.11
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-telegram-bot>=20.0

# Database
sqlalchemy>=2.0
psycopg2-binary>=2.9
alembic>=1.12

# Cache
redis>=5.0
hiredis>=2.2  # Performance boost

# Security
cryptography>=41.0
python-dotenv>=1.0

# Blockchain
web3>=6.0
solders>=0.18  # Solana
eth-account>=0.10

# Utilities
pydantic>=2.0
httpx>=0.25
python-dateutil>=2.8

# Testing
pytest>=7.4
pytest-asyncio>=0.21
pytest-cov>=4.1
pytest-mock>=3.12

# Development
black>=23.0
ruff>=0.1
mypy>=1.7

# Monitoring
sentry-sdk>=1.35
prometheus-client>=0.19
```

---

## 🐳 DOCKER COMPOSE (Local Dev)

```yaml
# docker-compose.yml
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
      - ./migrations:/docker-entrypoint-initdb.d

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  # Optional: Redis Commander (GUI)
  redis-commander:
    image: rediscommander/redis-commander:latest
    environment:
      - REDIS_HOSTS=local:redis:6379
    ports:
      - "8081:8081"

volumes:
  postgres_data:
  redis_data:
```

**Usage:**
```bash
# Start local dev environment
docker-compose up -d

# Stop
docker-compose down

# Rebuild
docker-compose up -d --build
```

---

## 🚀 SETUP LOCAL DEVELOPMENT

### 1. Clone & Setup
```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/
git clone <repo> polycool-rebuild
cd polycool-rebuild

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Variables
```bash
# Copy template
cp .env.example .env

# Edit .env avec vos credentials
nano .env  # ou votre éditeur préféré
```

### 3. Start Local Services
```bash
# Start Postgres + Redis
docker-compose up -d

# Verify services
docker-compose ps

# Check logs
docker-compose logs -f
```

### 4. Run Migrations
```bash
# Apply migrations
python scripts/run_migrations.py

# Seed test data (optional)
python scripts/seed_data.py
```

### 5. Start Bot
```bash
# Development mode (auto-reload)
uvicorn main:app --reload --port 8000

# Production mode
python main.py
```

---

## 🔍 FILE SIZE ENFORCEMENT

### Pre-commit Hook
```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Checking file sizes..."

# Find Python files > 700 lignes
oversized=$(find . -name "*.py" -not -path "./venv/*" -exec wc -l {} \; | awk '$1 > 700 {print $2}')

if [ -n "$oversized" ]; then
    echo "❌ ERROR: Files exceed 700 lines limit:"
    echo "$oversized"
    exit 1
fi

echo "✅ All files within size limit"
exit 0
```

### CI Check (GitHub Actions)
```yaml
# .github/workflows/lint.yml
name: Lint

on: [push, pull_request]

jobs:
  check-file-sizes:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Check file sizes
        run: |
          oversized=$(find . -name "*.py" -exec wc -l {} \; | awk '$1 > 700 {print $2}')
          if [ -n "$oversized" ]; then
            echo "Files exceed 700 lines:"
            echo "$oversized"
            exit 1
          fi
```

---

## 📊 METRICS & MONITORING

### Prometheus Metrics
```python
# core/utils/metrics.py (< 200 lignes)
from prometheus_client import Counter, Histogram, Gauge

# Request metrics
REQUEST_COUNT = Counter('telegram_requests_total', 'Total requests', ['handler', 'status'])
REQUEST_LATENCY = Histogram('telegram_request_duration_seconds', 'Request latency', ['handler'])

# Cache metrics
CACHE_HITS = Counter('cache_hits_total', 'Cache hits', ['cache_type'])
CACHE_MISSES = Counter('cache_misses_total', 'Cache misses', ['cache_type'])

# Trading metrics
TRADES_EXECUTED = Counter('trades_executed_total', 'Trades executed', ['outcome'])
TPSL_TRIGGERED = Counter('tpsl_triggered_total', 'TP/SL triggered', ['trigger_type'])
```

---

## ✅ NEXT STEPS

1. **Créer le projet** avec cette structure
2. **Setup .env** avec vos credentials
3. **Démarrer Docker Compose** (Postgres + Redis local)
4. **Lire [Phase 1](./01_PHASE_ARCHITECTURE.md)** pour détails d'implémentation

---

**Dernière mise à jour:** 6 novembre 2025
**Architecture:** Modulaire, testable, maintenable (< 700 lignes par fichier)
