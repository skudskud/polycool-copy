# Polycool Telegram Bot - Complete Rebuild

🚀 **Telegram bot for Polymarket trading with real-time data ingestion**

## 🎯 Overview

This is a complete rebuild of the Polycool Telegram bot, featuring:
- **Unified data architecture** with single source of truth
- **Real-time market data** via WebSocket selective streaming
- **Modular architecture** with strict file size limits (<700 lines)
- **Comprehensive testing** (70% coverage target)
- **Production-ready** infrastructure

## 🏗️ Architecture

```
polycool-rebuild/
├── telegram_bot/           # FastAPI + Telegram bot
│   ├── api/                # REST API endpoints
│   ├── bot/                # Telegram handlers
│   └── main.py             # FastAPI application
├── core/                   # Business logic
│   ├── database/           # SQLAlchemy models & connection
│   ├── models/             # Pydantic models
│   └── services/           # Core services (Cache, WebSocket, etc.)
├── data_ingestion/         # Data pipelines
│   ├── poller/             # Gamma API polling
│   ├── streamer/           # WebSocket real-time data
│   └── indexer/            # On-chain data indexing
├── infrastructure/         # Infrastructure code
│   ├── config/             # Settings & configuration
│   ├── logging/            # Structured logging
│   └── monitoring/         # Health checks & metrics
└── tests/                  # Test suites
```

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.9+
- Git

### 1. Clone & Setup

```bash
git clone <repository-url>
cd polycool-rebuild

# One-command setup
./scripts/dev/setup.sh
```

This will:
- ✅ Create `.env` file from template
- ✅ Start PostgreSQL & Redis containers
- ✅ Install Python dependencies
- ✅ Initialize database schema

### 2. Configure Environment

Edit `.env` with your credentials:

```bash
# Required
BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql://polycool:polycool2025@localhost:5432/polycool_dev
REDIS_URL=redis://localhost:6379

# Polymarket API
CLOB_API_KEY=your_api_key
CLOB_API_SECRET=your_api_secret
CLOB_API_PASSPHRASE=your_passphrase

# Optional
OPENAI_API_KEY=your_openai_key  # For smart trading
```

### 3. Start Development

```bash
# Start all services
./scripts/dev/start.sh

# Or manually:
docker-compose up -d postgres redis
python -m telegram_bot.main
```

### 4. Access Services

- **Bot**: Telegram (message your bot)
- **API**: http://localhost:8000
- **Health Checks**: http://localhost:8000/health
- **API Docs**: http://localhost:8000/docs
- **pgAdmin**: http://localhost:5050
- **Redis Commander**: http://localhost:8081

## 🧪 Testing

```bash
# Run full test suite
./scripts/dev/test.sh

# Run specific tests
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/

# With coverage
pytest --cov=telegram_bot --cov-report=html
```

## 📊 Data Schema

### Core Tables

```sql
-- Users with encrypted wallets
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE,
    polygon_address TEXT UNIQUE,  -- Encrypted
    solana_address TEXT UNIQUE,   -- Encrypted
    stage TEXT DEFAULT 'onboarding'
);

-- Unified markets (single source of truth)
CREATE TABLE markets (
    id TEXT PRIMARY KEY,          -- Polymarket market ID
    source TEXT,                  -- 'poll', 'ws', 'api'
    title TEXT,
    outcomes JSONB,
    outcome_prices JSONB,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_outcome TEXT,
    resolved_at TIMESTAMPTZ
);

-- Positions with P&L
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    market_id TEXT REFERENCES markets(id),
    outcome TEXT,
    amount DECIMAL,
    entry_price DECIMAL,
    pnl_amount DECIMAL DEFAULT 0,
    status TEXT DEFAULT 'active'
);
```

## 🔧 Development Workflow

### Adding New Features

1. **Create database migrations** in `scripts/dev/`
2. **Add models** in `core/database/models.py`
3. **Implement services** in `core/services/`
4. **Create API endpoints** in `telegram_bot/api/v1/`
5. **Add Telegram handlers** in `telegram_bot/bot/handlers/`
6. **Write tests** (TDD approach)

### Code Quality

- **File size limit**: 700 lines maximum
- **Test coverage**: 70% overall, 90% for security-critical code
- **Type hints**: Full typing with mypy
- **Linting**: black + isort + flake8

### Database Operations

```python
# Using the unified schema
from core.database.connection import get_db
from core.models.market import Market

async def get_active_markets(db: AsyncSession):
    result = await db.execute(
        select(Market).where(Market.is_active == True)
    )
    return result.scalars().all()
```

### Caching Strategy

```python
from core.services.cache_manager import CacheManager

cache = CacheManager()

# Get with TTL strategy
markets = await cache.get_or_set(
    key="markets:active",
    fetch_func=fetch_active_markets,
    data_type="markets"  # 5min TTL
)
```

## 🔐 Security

- **Encrypted private keys** (AES-256-GCM)
- **Webhook signatures** validation
- **Rate limiting** on API endpoints
- **Input validation** with Pydantic
- **SQL injection protection** with SQLAlchemy

## 📈 Monitoring

- **Health checks**: `/health/ready`, `/health/live`
- **Metrics**: Response times, error rates, cache hit rates
- **Structured logging**: JSON format with context
- **Sentry integration**: Error tracking (optional)

## 🚢 Deployment

### Docker Production

```bash
# Build and deploy
docker-compose -f docker-compose.prod.yml up -d

# With environment
docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

### Railway Deployment

```bash
# Deploy to Railway
railway deploy

# Environment variables
railway variables set BOT_TOKEN=...
railway variables set DATABASE_URL=...
```

## 📚 Documentation

- **[Architecture Overview](./docs/README_ARCHITECTURE.md)**
- **[Data Schema](./docs/01_PHASE_ARCHITECTURE.md)**
- **[Security Implementation](./docs/02_PHASE_SECURITY.md)**
- **[Core Features](./docs/03_PHASE_CORE_FEATURES.md)**
- **[Trading Features](./docs/04_PHASE_TRADING.md)**
- **[Advanced Trading](./docs/05_PHASE_ADVANCED_TRADING.md)**
- **[Data Ingestion](./docs/06_PHASE_DATA_INGESTION.md)**
- **[Performance](./docs/07_PHASE_PERFORMANCE.md)**

## 🤝 Contributing

1. **Branch naming**: `feature/`, `bugfix/`, `hotfix/`
2. **Commits**: Conventional commits (`feat:`, `fix:`, `docs:`)
3. **PR reviews**: Required for all changes
4. **Testing**: All PRs must pass CI tests

## 📞 Support

- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions
- **Architecture decisions**: ADRs in `/docs/architecture/decisions/`

---

**Built with ❤️ for the Polymarket community**

# Force Railway rebuild - change this comment to trigger new deployment
# Attempt 13 - Final fix for DB connection issue

