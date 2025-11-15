# 🐛 BUG: PROPOSED Markets Never Transitioning to RESOLVED

**Date Found:** Nov 3, 2025
**Severity:** 🔴 CRITICAL
**Impact:** Redeem system completely blocked

---

## 🚨 The Problem

```
After redeploy, markets are still stuck in PROPOSED status:

PROPOSED: 7,635 markets (UNCHANGED!)
RESOLVED: 0 markets  ← Should be growing!

After first redeploy with key name fix, still NO change!
```

---

## 🔍 Root Cause Analysis: TWO BUGS Found!

### BUG #1: Key Name Mismatch (Already Fixed)

**Location:** `src/polling/poller.py` line 956

```python
prices = market_data.get("outcomePrices", [])  ← Looked for camelCase
# But data has:
outcome_prices (snake_case)
```

**Fix Applied:**
```python
prices = market_data.get("outcomePrices") or market_data.get("outcome_prices") or []
```

✅ This alone WASN'T enough...

---

### 🔴 BUG #2: CRITICAL - Missing @staticmethod Decorator!

**Location:** `src/polling/poller.py` line 941

```python
# BEFORE (BROKEN):
def _extract_winning_outcome(market_data: Dict) -> Optional[int]:  ← NO @staticmethod!
    ...

# Called with self:
outcome = self._extract_winning_outcome(market_data)  ← Line 918, 929
```

**What Happens:**

```
When called as self._extract_winning_outcome(market_data):

Python does:
1. Look up _extract_winning_outcome on instance
2. It's an unbound method (no @staticmethod)
3. Python passes `self` as FIRST argument automatically
4. Method signature: def _extract_winning_outcome(market_data)
5. Receives: market_data = self (the PollerService instance!)
6. Tries: market_data.get("outcome") → Looks for .get() on PollerService
7. CRASHES silently or behaves weirdly!

Result: Method NEVER executes, outcome always None!
```

**The Fix (Applied):**

```python
@staticmethod
def _extract_winning_outcome(market_data: Dict) -> Optional[int]:
    # Now works correctly!
```

---

## 💥 Combined Effect

```
Bug #1 + Bug #2:
├─ Bug #1: Get key name wrong → prices = []
├─ Bug #2: Method not @staticmethod → Crashes/hangs silently
└─ Result: _extract_winning_outcome() NEVER works
           winning_outcome always stays NULL
           Markets stuck in PROPOSED forever
```

---

## 📊 Why First Redeploy Didn't Work

**I fixed Bug #1 but NOT Bug #2!**

```
First redeploy (only Bug #1 fixed):
├─ Now checks both outcomePrices AND outcome_prices ✓
├─ But _extract_winning_outcome still has NO @staticmethod ✗
├─ Method crashes when called with self._extract_winning_outcome()
└─ Result: STILL doesn't work!

Second redeploy (BUG #2 fixed):
├─ @staticmethod decorator added ✓
├─ Both key names checked ✓
└─ Should finally work! 🎯
```

---

## 🔧 Complete Solution

**File:** `src/polling/poller.py`

```python
# Line 940 - ADD @staticmethod
@staticmethod
def _extract_winning_outcome(market_data: Dict) -> Optional[int]:
    """
    Extract winning outcome from API
    """
    # Method 1: Explicit field
    outcome_str = market_data.get("outcome")
    if outcome_str:
        return 1 if outcome_str.lower() == "yes" else 0

    # Method 2: Try BOTH camelCase AND snake_case
    prices = market_data.get("outcomePrices") or market_data.get("outcome_prices") or []

    if len(prices) == 2:
        try:
            yes_price, no_price = float(prices[0]), float(prices[1])
            if yes_price > 0.99 and no_price < 0.01:
                return 1
            elif no_price > 0.99 and yes_price < 0.01:
                return 0
        except Exception as e:
            logger.warning(f"⚠️ [OUTCOME] Failed to parse prices {prices}: {e}")

    return None
```

**Changes:**
1. ✅ Added `@staticmethod` decorator
2. ✅ Try BOTH key formats (outcomePrices + outcome_prices)
3. ✅ Add error logging

---

## ⚡ Lesson Learned

**Python @staticmethod Gotcha:**

```python
# These are DIFFERENT:
def _method(self, data):        # Instance method
@staticmethod
def _method(data):              # Static method - no self!

# Calling:
self._method(data)              # Instance: Python adds self automatically
self._method(data)              # Static: No automatic self! Just data
```

**If you forget @staticmethod on a static method and call with self,
Python passes self as the first argument → Instant bugs!**

---

## 🚀 Action Items

- [x] Identified Bug #1: Key name mismatch
- [x] Identified Bug #2: Missing @staticmethod (CRITICAL!)
- [x] Applied BOTH fixes
- [ ] Redeploy poller (final)
- [ ] Monitor: PROPOSED count should decrease within 10 minutes
- [ ] Verify: winning_outcome NOW populated
- [ ] Enable redeem queue filler

---

**Status:** 🟢 BOTH BUGS FIXED IN CODE, READY FOR FINAL REDEPLOY
**Next:** Deploy and verify resolution_status changes within 5 min
