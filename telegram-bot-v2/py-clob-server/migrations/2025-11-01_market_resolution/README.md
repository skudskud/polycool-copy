# Market Resolution & Redemption System

**Created:** 2025-11-01  
**Status:** ✅ Applied to EU Database

## Overview

This migration creates the infrastructure for:
- Detecting when markets resolve
- Notifying users of wins/losses
- Managing token redemption lifecycle

## Migration Applied

✅ `001_create_resolved_positions.sql` - Applied via Supabase MCP

## Files Created

1. `core/services/market_resolution_monitor.py` - Detection service
2. `telegram_bot/services/resolution_notification_service.py` - Notifications
3. Database model added to `database.py`
4. Scheduler integrated in `main.py`

## Features

- ✅ Scans every 5 minutes for newly resolved markets
- ✅ Calculates P&L from transaction history
- ✅ Sends Telegram notifications  
- ✅ Retroactive (detects existing won positions)
- ✅ Winners stay forever until redeemed
- ✅ Losers expire after 3 days

