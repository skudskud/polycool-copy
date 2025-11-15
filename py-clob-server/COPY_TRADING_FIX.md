# Copy Trading Address Resolution Fix

## Problem Description

When users tried to search for a leader using the `/copy_trading` command and entered a Polygon address, they received the error:

```
❌ *Leader Not Found*

No active trader found with address:
`0x339e9Ff971C3AeFa7c48367008978c5dAb0e1aD5`

Try another address or use /copy_trading to search again.
```

Even though the address existed and belonged to an active trader on the platform.

## Root Cause

The method `resolve_leader_by_address()` was **called but never implemented** in the `CopyTradingService` class.

### File: `telegram_bot/handlers/copy_trading/main.py` (Line 99)
```python
leader_id = service.resolve_leader_by_address(polygon_address)
```

This method call would raise an `AttributeError`, which was caught and converted to the "Leader Not Found" error message.

## Solution Implemented

### 1. Added `resolve_leader_by_address()` method to CopyTradingService

**File:** `core/services/copy_trading/service.py`

```python
def resolve_leader_by_address(self, polygon_address: str) -> int:
    """
    Resolve a Polygon wallet address to a leader's telegram user ID

    Searches the database for a user with the given Polygon address
    and returns their telegram_user_id to use as a leader_id
    """
    try:
        repo = self._get_repo()
        user = repo.find_user_by_polygon_address(polygon_address)

        if not user:
            raise LeaderNotFoundError(f"No trader found with address: {polygon_address}")

        logger.info(f"✅ Resolved address {polygon_address[:10]}... to user {user.telegram_user_id}")
        return user.telegram_user_id

    except LeaderNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error resolving leader by address: {e}")
        raise LeaderNotFoundError(f"Failed to resolve address: {str(e)}")
```

### 2. Added utility method to CopyTradingRepository

**File:** `core/services/copy_trading/repository.py`

```python
def find_user_by_polygon_address(self, polygon_address: str):
    """
    Find a user by their Polygon wallet address
    Uses case-insensitive matching to handle address format variations
    """
    try:
        from database import User

        user = self.db.query(User).filter(
            User.polygon_address.ilike(polygon_address)
        ).first()

        return user
    except Exception as e:
        logger.error(f"Error querying user by address: {e}")
        return None
```

## How It Works

### Flow Diagram

```
User enters address via /copy_trading
            ↓
handle_leader_address() receives text
            ↓
Validate address format (0x... format)
            ↓
service.resolve_leader_by_address(address)
            ↓
repo.find_user_by_polygon_address(address)
            ↓
Query users table: WHERE polygon_address ILIKE 'address'
            ↓
Found? → Return user.telegram_user_id
Not Found? → Raise LeaderNotFoundError
            ↓
Get leader stats for confirmation
            ↓
Show confirmation prompt to user
```

## Database Queries

The solution queries the `users` table with a case-insensitive match:

```sql
SELECT telegram_user_id, username, polygon_address, ...
FROM users
WHERE polygon_address ILIKE '0x339e9ff971c3aefa7c48367008978c5dab0e1ad5'
LIMIT 1
```

The index `idx_users_polygon_address` on the `polygon_address` column ensures fast lookup.

## Testing

To verify the fix works:

1. Get a valid Polygon address of an existing user in your database:
   ```sql
   SELECT telegram_user_id, polygon_address FROM users LIMIT 1;
   ```

2. In Telegram, use `/copy_trading` → "🔄 Search Leader"

3. Enter the Polygon address from step 1

4. You should now see the leader's stats and be able to confirm following them

## Error Handling

The solution properly handles various error scenarios:

- **Address not found** → Raises `LeaderNotFoundError`
- **Database connection error** → Logs error and raises `LeaderNotFoundError`
- **Invalid address format** → Caught by handler before calling service (line 89)

## Potential Future Enhancements

### 1. Leader Validation Criteria

Currently, any user with a Polygon address can be a leader. Consider adding:

```python
# Check if leader has minimum trading history
if not leader_has_trades(user.telegram_user_id):
    raise LeaderNotFoundError("Leader must have trading history")

# Check if leader is not blacklisted
if user in blacklisted_leaders:
    raise LeaderNotFoundError("This leader is not available")

# Check if leader is currently accepting followers
if not user.accepting_followers:
    raise LeaderNotFoundError("Leader is not accepting followers")
```

### 2. Support for External/Smart Wallet Addresses

The codebase has a `smart_wallets` table for tracking external trader addresses. Could extend to:

```python
def resolve_leader_by_address_extended(self, polygon_address: str):
    # First check internal users
    user = repo.find_user_by_polygon_address(polygon_address)
    if user:
        return user.telegram_user_id

    # Then check smart wallets
    smart_wallet = repo.find_smart_wallet(polygon_address)
    if smart_wallet:
        return smart_wallet.create_virtual_leader_id()
```

### 3. Address Normalization

Add normalization for address consistency:

```python
def normalize_polygon_address(address: str) -> str:
    """Convert to checksum address for consistency"""
    from web3 import Web3
    return Web3.to_checksum_address(address.lower())
```

### 4. Caching for Performance

Add Redis caching for frequently resolved addresses:

```python
def resolve_leader_by_address_cached(self, polygon_address: str) -> int:
    # Check cache first
    cache_key = f"leader_addr:{polygon_address.lower()}"
    cached_id = redis_client.get(cache_key)
    if cached_id:
        return int(cached_id)

    # Resolve from DB
    leader_id = self.resolve_leader_by_address(polygon_address)

    # Cache for 24 hours
    redis_client.setex(cache_key, 86400, leader_id)
    return leader_id
```

## Files Modified

- ✅ `core/services/copy_trading/service.py` - Added `resolve_leader_by_address()`
- ✅ `core/services/copy_trading/repository.py` - Added `find_user_by_polygon_address()`

## Deployment Notes

- No database migrations needed
- Existing `idx_users_polygon_address` index already supports efficient lookups
- No breaking changes to existing APIs
- Backward compatible with existing subscriptions

## Summary

The fix implements the missing address resolution logic by:
1. ✅ Querying the `users` table by Polygon address
2. ✅ Using case-insensitive matching for flexibility
3. ✅ Returning the user's Telegram ID as the leader ID
4. ✅ Proper error handling with `LeaderNotFoundError`
5. ✅ Clean separation of concerns (service → repository)

Users can now successfully find and follow leaders by entering their Polygon wallet address.
