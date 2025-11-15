# Archive Directory

This directory contains archived code, backups, and deprecated components that are no longer in active use but preserved for historical reference and recovery.

## Directory Structure

```
.archive/
├── 2025-10-20_bridge_backup_v1/              # Bridge system backup
├── 2025-10-02_pre_postgresql_migration/       # Pre-PostgreSQL migration archive
├── 2025-10-20_v1_bot_legacy/                  # V1 bot legacy code
├── 2025-10-20_auto_approval_prototype/        # Auto-approval prototype
└── README.md                                   # This file
```

## Contents

### 2025-10-20_bridge_backup_v1/

**Purpose**: Backup of the Solana bridge system

**Location**: `content/` subdirectory

**Contains**:
- `bridge_orchestrator.py` - Bridge orchestration logic (critical)
- `bridge_v3.py` - Latest bridge implementation
- `solana_transaction.py` - Blockchain transaction handling
- `debridge_client.py` - deBridge integration
- `jupiter_client.py` - Jupiter DEX integration
- `quickswap_client.py` - QuickSwap DEX integration
- `solana_wallet_manager.py` - Solana wallet management
- Configuration and documentation files

**Why Archived**: Backup for emergency restoration if main solana_bridge/ breaks

**Recovery**: If bridge fails, restore with:
```bash
cp -r .archive/2025-10-20_bridge_backup_v1/content/* solana_bridge/
```

### 2025-10-02_pre_postgresql_migration/

**Purpose**: Old JSON-based data managers (superseded by PostgreSQL)

**Location**: `content/` subdirectory

**Contains**:
- `wallet_manager.py` - OLD: Managed wallets via JSON
- `api_key_manager.py` - OLD: Managed API keys via JSON
- `solana_wallet_manager_v2.py` - OLD: Managed Solana wallets via JSON
- `market_database.py` - OLD: JSON-based market database
- `position_persistence.py` - OLD: Position persistence layer
- `data_persistence.py` - OLD: Generic JSON persistence
- JSON data files (user_wallets.json, user_api_keys.json, etc.)

**Why Archived**: Replaced by PostgreSQL unified architecture

**Replacement**: All functionality now in:
- `core/services/user_service.py` - Unified user management
- `core/services/market_fetcher_service.py` - Market data from Gamma API
- PostgreSQL tables (users, positions, markets)

**Reference**: If needing to understand old logic or migrate legacy data

### 2025-10-20_v1_bot_legacy/

**Purpose**: Original V1 bot code and prototypes

**Contains**:
- Old bot implementations
- Legacy handlers and services
- Previous versions and iterations
- Test files and examples

**Why Archived**: V2 bot is complete replacement

**Note**: Do not use in production - reference only

### 2025-10-20_auto_approval_prototype/

**Purpose**: Auto-approval prototype/exploration

**Contains**:
- `auto_approval_engine.py` - Prototype auto-approval engine
- `event_listener.py` - Event listening prototype
- `prototype_main.py` - Prototype entry point
- `shared_modules/` - Shared functionality
- Configuration and documentation

**Why Archived**: Logic moved to `core/services/auto_approval_service.py`

**Current Implementation**: See `core/services/auto_approval_service.py`

## Recovery Procedures

### Emergency: Bridge System Broken

```bash
# Backup broken version
mv solana_bridge solana_bridge_broken_$(date +%Y%m%d_%H%M%S)

# Restore from archive
cp -r .archive/2025-10-20_bridge_backup_v1/content/* solana_bridge/

# Verify
python -c "from solana_bridge.bridge_orchestrator import bridge_orchestrator; print('✅ Bridge restored')"
```

### Data Migration: Old JSON to PostgreSQL

Reference files in `2025-10-02_pre_postgresql_migration/` to understand old data format, but use PostgreSQL for current data.

## Maintenance Guidelines

1. **Do Not Delete** - Archives preserve history and recovery options
2. **Do Not Use in Production** - Archived code is outdated
3. **Document Changes** - When archiving new code, update this README
4. **Review Periodically** - Quarterly reviews to ensure archives are still needed
5. **Size Management** - Monitor archive size; move very old items to separate storage if needed

## Adding to Archive

When retiring code:

1. Create timestamped directory: `.archive/YYYY-MM-DD_description/`
2. Move code: `mv old_component .archive/YYYY-MM-DD_description/`
3. Create content subdirectory: `mkdir -p .archive/YYYY-MM-DD_description/content`
4. If moving files: `mv .archive/YYYY-MM-DD_description/* .archive/YYYY-MM-DD_description/content/`
5. Update this README with directory description

## Gitignore Status

Archive directory is version controlled (not ignored) to preserve history and recovery options.

## Contact

For questions about archived code or recovery procedures, refer to:
- REFACTORING_NOTES.md - Recent refactoring decisions
- PROJECT_STRUCTURE.md - Current project structure
- Individual component READMEs in archived directories
