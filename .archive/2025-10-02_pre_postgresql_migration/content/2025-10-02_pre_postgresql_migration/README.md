# Archived Files: Pre-PostgreSQL Migration

**Date:** October 2, 2025  
**Reason:** Migrated from JSON-based storage to PostgreSQL-exclusive architecture

---

## 📁 Archived Files

### Python Modules (Old JSON-based managers)
- `wallet_manager.py` - Managed Polygon wallets via JSON
- `api_key_manager.py` - Managed API credentials via JSON
- `solana_wallet_manager_v2.py` - Managed Solana wallets via JSON
- `market_database.py` - Managed markets via JSON file
- `position_persistence.py` - Old position persistence system
- `data_persistence.py` - Generic JSON persistence layer

### JSON Data Files
- `user_wallets.json` - Polygon wallet data (superseded by PostgreSQL `users` table)
- `user_api_keys.json` - API credentials (superseded by `users` table)
- `solana_wallets.json` - Solana wallets (superseded by `users` table)
- `user_positions.json` - Positions (superseded by `positions` table)
- `markets_database.json` - Markets (superseded by Gamma API → PostgreSQL)

---

## ✅ Replaced By

### New Unified Architecture

**Single User Service:**
- `user_service.py` - **Manages ALL user data** (Polygon + Solana + API keys)
  - Replaces: wallet_manager.py, api_key_manager.py, solana_wallet_manager_v2.py

**Market Fetcher Service:**
- `market_fetcher_service.py` - **Fetches from Gamma API → PostgreSQL**
  - Replaces: market_database.py + markets_database.json

**PostgreSQL Tables:**
- `users` table - All user data (wallets + API keys)
- `positions` table - Trading positions
- `markets` table - Live market data from Gamma API

---

## 🔄 Migration Path

1. **Phase 1:** Created new PostgreSQL schema
2. **Phase 2:** Built Gamma API → PostgreSQL pipeline  
3. **Phase 3:** Updated all code to use new services
4. **Phase 4:** Archived old files (this directory)
5. **Phase 5:** Deployed to Railway

---

## ⚠️ Important Notes

### Data Preservation
- All user data migrated to PostgreSQL `users` table
- All positions migrated to PostgreSQL `positions` table
- Markets will be fetched fresh from Gamma API (8,075 active markets)

### Why Archive (Not Delete)
- Safety: Can reference old code if needed
- Debugging: Can compare old vs new logic
- Recovery: JSON files retained as emergency backup

### DO NOT Use These Files
- They are incompatible with new PostgreSQL schema
- Using them will cause errors
- Kept for reference only

---

## 📊 Benefits of New System

| Aspect | Old (JSON) | New (PostgreSQL) |
|--------|-----------|------------------|
| **Reliability** | ❌ Lost on restart | ✅ Persistent |
| **Data Integrity** | ❌ File corruption risk | ✅ ACID compliant |
| **Performance** | ❌ Load all → filter | ✅ Indexed queries |
| **Scalability** | ❌ Limited | ✅ Unlimited |
| **Code Complexity** | ❌ 3 managers | ✅ 1 service |
| **Market Data** | ❌ Stale JSON (manual update) | ✅ Live from API |

---

**Archived:** October 2, 2025  
**Status:** Safe to delete after successful deployment verification  
**Retention:** Keep for 30 days, then can be permanently deleted

