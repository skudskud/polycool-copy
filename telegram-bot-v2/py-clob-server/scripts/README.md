# Scripts Directory

This directory contains utility scripts for development, debugging, analysis, and diagnostics.

## Directory Structure

```
scripts/
├── debug/           # Debug and troubleshooting scripts
├── analysis/        # Data analysis and audit scripts
├── diagnostics/     # Diagnostic and system check scripts
└── migrations/      # Database migration utilities (ad-hoc)
```

## Debug Scripts

Debug scripts help troubleshoot issues with the application.

**Location**: `scripts/debug/`

- `debug_market_issue.py` - Debug market data issues and inconsistencies
- `debug_outcomes_count.py` - Debug outcome counting logic
- `debug_smart_trading_filters.py` - Debug smart trading filter logic

**Usage**:
```bash
python scripts/debug/debug_market_issue.py
```

## Analysis Scripts

Analysis scripts perform data analysis, audits, and generate reports.

**Location**: `scripts/analysis/`

- `analyze_scheduler_issue.py` - Analyze scheduler and task timing issues
- `analyze_smart_wallet_markets.py` - Analyze smart wallet market behavior
- `audit_smart_trading.py` - Comprehensive audit of smart trading system

**Usage**:
```bash
python scripts/analysis/analyze_smart_wallet_markets.py
```

## Diagnostics Scripts

Diagnostic scripts check system health, market status, and other operational concerns.

**Location**: `scripts/diagnostics/`

- `diagnose_fed_markets.py` - Diagnose Fed-related markets
- `diagnose_scheduler.py` - Diagnose scheduler and scheduler tasks
- `check_expected_smart_trades.py` - Check smart trade expectations
- `check_last_trade.py` - Check the last executed trade
- `check_market_status.py` - Check overall market status
- `check_recent_smart_trades.py` - Check recent smart trading activity
- `force_events_update.py` - Force manual events update
- `force_smart_wallet_sync.py` - Force smart wallet synchronization
- `force_sync_smart_wallets.py` - Force smart wallet sync (alternative)
- `sync_smart_wallet_markets.py` - Synchronize smart wallet market data

**Usage**:
```bash
python scripts/diagnostics/check_market_status.py
```

## Migrations Scripts

Ad-hoc migration scripts for database operations.

**Location**: `scripts/migrations/`

**Note**: Primary migrations are in the `migrations/` directory with proper versioning. These scripts are for ad-hoc operations.

## Running Scripts

### From Project Root

```bash
cd "telegram bot v2/py-clob-server"
python scripts/debug/debug_market_issue.py
```

### With Environment Setup

```bash
export PYTHONPATH="${PWD}:${PYTHONPATH}"
python scripts/analysis/audit_smart_trading.py
```

## Safety & Best Practices

- Always review scripts before running, especially diagnostics and migrations
- Ensure database backups exist before running migration scripts
- Run in development environment first
- Check logs after execution: `tail -f logs/app.log`

## Adding New Scripts

1. Create the script in the appropriate subdirectory (debug/, analysis/, diagnostics/, or migrations/)
2. Add detailed docstring and usage instructions
3. Update this README with the script description
4. Test in development before production use

## Script Maintenance

- Remove unused scripts regularly
- Keep scripts focused on a single purpose
- Document any external dependencies
- Include error handling and logging
