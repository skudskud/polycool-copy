# Copy Trading Architecture (DipDup + Telegram Bot)

## Overview

This document describes how DipDup indexes blockchain transactions and how the bot enables "copy trading anyone" - allowing users to follow and automatically copy trades from ANY blockchain address, not just registered bot users.

---

## User Flow (Telegram)

### 1. User Initiates Copy Trading

```
User: /copytrading
  ↓
Bot: "Who do you want to copy? (Enter blockchain address)"
  ↓
Bot: Shows inline keyboard with options:
     - "Enter address" (inline button)
     - "Cancel"
  ↓
User: Clicks "Enter address"
  ↓
Bot: "Send me the blockchain address (you can copy-paste)"
  ↓
User: Sends message: "0xABC123..."
  ↓
Bot: Validates address format
  ↓
Bot stores in copy_trading_subscriptions table:
   {
     follower_id: 123456 (user's telegram_user_id),
     leader_address: "0xABC123...",
     copy_mode: "PROPORTIONAL",
     status: "ACTIVE"
   }
  ↓
Bot: "✅ Now copying trades from 0xABC123..."
```

---

## Data Flow (Backend)

### 1. Blockchain → DipDup → Database

```
Blockchain (Polygon)
    ↓
Smart trader sends transaction:
  - Buys 100 YES tokens on market 248905
  - tx_hash: 0x1234...
    ↓
Conditional Tokens contract emits Transfer event
    ↓
DipDup indexer receives event (Polygon RPC)
    ↓
DipDup handler parses:
  - token_id: 497811 (market 248905 * 2 + outcome 1)
  - market_id: "248905" (numeric)
  - from: "0xZERO" → Type: BUY
  - to: "0xSMART..." (trader address)
  - amount: 100
    ↓
INSERT INTO subsquid_user_transactions:
  {
    user_address: "0xSMART...",
    market_id: "248905",
    outcome: 1,
    amount: 100,
    tx_hash: "0x1234...",
    timestamp: 2025-10-22 12:34:56
  }
    ↓
T+60s: Background job enriches price from subsquid_markets_poll.last_mid
```

### 2. Database → Bot Detection

```
Bot's background job (every 10-30 seconds):

1. Query subsquid_user_transactions:
   SELECT * FROM subsquid_user_transactions
   WHERE timestamp > NOW() - INTERVAL '5 minutes'
   ORDER BY timestamp DESC
   LIMIT 100
   
2. For each transaction, find followers:
   SELECT follower_id 
   FROM copy_trading_subscriptions
   WHERE (
     leader_address = transaction.user_address
     OR leader_id IN (SELECT telegram_user_id FROM users WHERE polygon_address = transaction.user_address)
   )
   AND status = 'ACTIVE'
   
3. If followers found:
   - Calculate copy amount based on follower's budget
   - Place order for each follower
   - Record in copy_trading_history
```

---

## Database Schema

### 1. Tables Created by DipDup

#### `subsquid_user_transactions`
```sql
tx_id              -- Primary key (tx_hash_log_index)
user_address       -- Blockchain address (from Transfer event)
market_id          -- Market ID (numeric, extracted from token_id)
outcome            -- 0=NO, 1=YES
amount             -- Tokens transferred
price              -- NULL initially, enriched after 60s
tx_hash            -- Blockchain transaction hash
timestamp          -- When transaction occurred on blockchain
```

### 2. Tables for Copy Trading (Bot Integration)

#### `copy_trading_subscriptions` (existing, updated)
```sql
id                 -- Primary key
follower_id        -- Telegram user ID (bot user)
leader_id          -- Telegram user ID (if leader is bot user)
leader_address     -- [NEW] Blockchain address (if leader is external)
copy_mode          -- PROPORTIONAL or FIXED_AMOUNT
status             -- ACTIVE, PAUSED, CANCELLED
created_at         -- When subscription created
updated_at         -- Last update
```

**Key difference:**
- `leader_id`: For copying other bot users
- `leader_address`: For copying ANY blockchain address

#### `external_leaders` (new, for analytics)
```sql
virtual_id         -- Generated ID from address
polygon_address    -- Blockchain address (0x...)
last_trade_id      -- Last transaction tracked
trade_count        -- Number of trades indexed
is_active          -- Whether we're tracking this address
last_poll_at       -- Last time we checked for trades
```

#### `copy_trading_history` (existing)
```sql
leader_id          -- Telegram user ID (if bot user)
-- OR use leader_address field if external
follower_id        -- Telegram user ID (bot user copying)
market_id          -- Market ID
leader_trade_amount -- How much leader traded
calculated_copy_amount -- Calculated for this follower
actual_copy_amount -- Actually executed
status             -- PENDING, EXECUTED, FAILED
```

---

## Lookup Fallback Chain

When a blockchain transaction is detected:

```
Transaction: user_address = 0xABC123
    ↓
Query copy_trading_subscriptions:

WHERE (
  leader_address = '0xABC123'           -- Direct address subscription
  OR
  leader_id IN (                        -- User subscription
    SELECT telegram_user_id 
    FROM users 
    WHERE polygon_address = '0xABC123'
  )
)
AND status = 'ACTIVE'

Result: followers to copy trade
```

**Three possible outcomes:**

1. **Direct subscription**: `leader_address = 0xABC123`
   - User explicitly added this blockchain address via `/copytrading`
   
2. **User subscription**: `leader_id IN users.telegram_user_id`
   - Address is a registered bot user's wallet
   - User followed this bot user
   
3. **Not found**: Address not in subscriptions
   - Transaction indexed but no one copying it yet
   - Tracked in `external_leaders` for analytics

---

## DipDup Integration Points

### Helper Functions in `transfers.py`

#### `find_copy_traders_for_address(db, leader_address) -> List[follower_id]`
```python
# Called when transaction detected
# Returns list of users who should copy trade this address
followers = await find_copy_traders_for_address(db, "0xABC123")
# Returns: [123456, 789012, 345678]
```

#### `track_external_leader(db, polygon_address, trade_id) -> bool`
```python
# Track blockchain addresses in external_leaders
# Useful for analytics and future copy trading decisions
await track_external_leader(db, "0xABC123", "0x1234...")
```

### Future: Webhook Notification
```python
# TODO: notify_copy_traders webhook
# Would send HTTP POST to bot service:
# {
#   market_id: "248905",
#   leader_address: "0xABC123",
#   follower_ids: [123456, 789012],
#   amount: 100,
#   outcome: 1
# }
```

---

## Timeline Example

```
T+0s:   Smart trader sends tx on blockchain
        Buys 100 YES tokens on market 248905 (tx_hash: 0x1234...)

T+2s:   Tx confirmed on Polygon

T+5s:   DipDup receives Transfer event from Polygon RPC

T+60s:  DipDup batch job indexes transaction:
        INSERT INTO subsquid_user_transactions:
          user_address: 0xSMART...
          market_id: 248905
          amount: 100
          outcome: 1

T+65s:  DipDup price enrichment job runs:
        UPDATE subsquid_user_transactions SET price = 0.75
        (from subsquid_markets_poll.last_mid)

T+70s:  Bot background job detects new transaction:
        SELECT * FROM subsquid_user_transactions 
        WHERE timestamp > NOW() - 5 minutes

T+75s:  Bot finds followers:
        SELECT follower_id FROM copy_trading_subscriptions
        WHERE leader_address = 0xSMART...
        Result: follower_id = 123456, 789012

T+80s:  Bot places copy orders:
        FOR each follower:
          - Calculate copy amount based on budget
          - Place order on CLOB
          - Record in copy_trading_history (status: PENDING)

T+85s:  Copy orders confirmed on blockchain

T+90s:  Bot updates copy_trading_history:
        status: EXECUTED
```

---

## Implementation Status

### ✅ Implemented
- [x] DipDup handlers for Transfer events
- [x] Numeric market_id extraction from token_id
- [x] Price enrichment (Option C - 60s background job)
- [x] `external_leaders` table for tracking external addresses
- [x] `copy_trading_subscriptions.leader_address` column
- [x] `find_copy_traders_for_address()` helper function
- [x] `track_external_leader()` helper function

### ⏳ Pending (Bot Integration)
- [ ] Telegram `/copytrading` command with inline keyboard
- [ ] Address validation and parsing
- [ ] Copy trading execution logic
- [ ] Webhook notification from DipDup to bot
- [ ] Budget calculation and scaling
- [ ] Failure handling and retries
- [ ] Analytics dashboard

---

## Notes

- **Latency**: ~70-90 seconds from transaction to copy execution (due to DipDup 60s batch window)
- **Flexibility**: Users can follow ANY blockchain address (not just bot users)
- **Fallback chain**: Lookup supports both registered users and external addresses
- **Scalability**: All queries use indexes for fast lookups even with thousands of followers

