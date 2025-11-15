# 🔄 **BRIDGE SYSTEM ROLLBACK PLAN**

## **Emergency Restoration Guide**

If the bridge system breaks during Phase 3+ modifications, follow this plan to restore functionality.

---

## ⚡ **QUICK RESTORE (2 minutes)**

### **Step 1: Stop the Server**
```bash
cd "/Users/huyvunguyen/Desktop/py-clob-client-with-bots/telegram bot v2/py-clob-server"

# If running locally
# Ctrl+C or kill process

# If on Railway
railway down
```

### **Step 2: Backup Broken Version**
```bash
# Move broken bridge out of the way
mv solana_bridge solana_bridge_broken_$(date +%Y%m%d_%H%M%S)
```

### **Step 3: Restore from Backup**
```bash
# Copy clean backup
cp -r archive_bridge_backup solana_bridge
```

### **Step 4: Verify Restoration**
```bash
# Check files exist
ls -la solana_bridge/

# Should see 14 files:
# __init__.py, bridge_orchestrator.py, bridge_v3.py, 
# solana_transaction.py, debridge_client.py, jupiter_client.py,
# quickswap_client.py, solana_wallet_manager.py, config.py, etc.
```

### **Step 5: Restart Server**
```bash
# If local
python3 main.py

# If Railway
railway up
```

### **Step 6: Test Bridge**
```
1. Open Telegram bot
2. Type: /bridge
3. Verify SOL balance shows
4. If balance shows correctly → ✅ Restore successful!
```

---

## 🔍 **VERIFICATION CHECKLIST**

After restore, verify these work:

- [ ] `/bridge` command shows SOL balance
- [ ] Inline buttons appear (Bridge Auto, Custom Amount)
- [ ] No errors in Railway logs
- [ ] `from solana_bridge.bridge_orchestrator import bridge_orchestrator` works in Python
- [ ] Bridge quote generation works (if balance > 0.1 SOL)

---

## 📁 **BACKUP CONTENTS**

**Location:** `archive_bridge_backup/`

**Files (14 total):**
```
__init__.py                          (672 bytes)
bridge_orchestrator.py               (34,272 bytes) ← MOST CRITICAL
bridge_v3.py                         (26,283 bytes)
bridge_v3.py.backup                  (24,019 bytes)
config.py                            (2,103 bytes)
CONFIGURATION.md                     (9,060 bytes)
debridge_client.py                   (16,269 bytes)
jupiter_client.py                    (7,161 bytes)
quickswap_client.py                  (10,142 bytes)
README.md                            (13,608 bytes)
simple_swap_v2.py                    (4,076 bytes)
simple_swap.py                       (8,119 bytes)
solana_transaction.py                (29,838 bytes) ← SECOND MOST CRITICAL
solana_wallet_manager.py             (5,617 bytes)
telegram_integration_example.py     (8,689 bytes)
```

**Total Size:** ~200 KB

**Backup Date:** Oct 4, 2025

---

## 🛠️ **PARTIAL RESTORE (Single File)**

If only one file is broken, restore just that file:

```bash
# Example: Restore bridge_orchestrator.py
cp archive_bridge_backup/bridge_orchestrator.py solana_bridge/

# Example: Restore solana_transaction.py
cp archive_bridge_backup/solana_transaction.py solana_bridge/

# Restart server
railway restart
```

---

## 🚨 **WHAT IF BACKUP IS MISSING?**

If `archive_bridge_backup/` is deleted, restore from git:

```bash
# Check if it's in git history
git log --all --full-history -- "telegram bot v2/py-clob-server/solana_bridge/"

# Restore from specific commit (Phase 1 commit)
git show 1e85412:telegram\ bot\ v2/py-clob-server/solana_bridge/ > restore_bridge.txt

# Or checkout to phase-2-bridge-backup-safety branch
git checkout phase-2-bridge-backup-safety
cp -r "telegram bot v2/py-clob-server/solana_bridge" "solana_bridge_restored"
```

---

## 🔐 **BACKUP VERIFICATION**

To verify backup integrity before you need it:

```bash
cd "/Users/huyvunguyen/Desktop/py-clob-client-with-bots/telegram bot v2/py-clob-server"

# Count files
ls -1 archive_bridge_backup/*.py | wc -l
# Should output: 12 (12 Python files)

# Check critical files exist
test -f archive_bridge_backup/bridge_orchestrator.py && echo "✅ bridge_orchestrator.py exists"
test -f archive_bridge_backup/bridge_v3.py && echo "✅ bridge_v3.py exists"
test -f archive_bridge_backup/solana_transaction.py && echo "✅ solana_transaction.py exists"

# Check files are not empty
du -sh archive_bridge_backup/bridge_orchestrator.py
# Should output: ~34K
```

---

## 📊 **ROLLBACK DECISION TREE**

```
Bridge not working?
    ↓
Is /bridge command recognized?
    ↓ No
    Import error in bridge_handlers.py
    → Check telegram_bot/handlers/bridge_handlers.py
    ↓ Yes
    ↓
Does /bridge show balance?
    ↓ No
    solana_transaction.py issue
    → Restore solana_transaction.py
    ↓ Yes
    ↓
Does bridge execution fail?
    ↓ At signing?
    bridge_orchestrator.py issue
    → Restore bridge_orchestrator.py
    ↓ At broadcast?
    debridge_client.py or jupiter_client.py issue
    → Restore specific client
    ↓ At Polygon?
    quickswap_client.py issue
    → Restore quickswap_client.py
```

---

## ⏱️ **EXPECTED RESTORE TIME**

- **Quick Restore (full system):** 2 minutes
- **Partial Restore (single file):** 30 seconds
- **Git Restore (if backup missing):** 5 minutes
- **Verification:** 2 minutes

**Total Max Time:** 10 minutes

---

## ✅ **POST-RESTORE VALIDATION**

Run these tests after restore:

### **1. Import Test**
```python
python3 -c "from solana_bridge.bridge_orchestrator import bridge_orchestrator; print('✅ Import works')"
```

### **2. Balance Check Test** (if you have SOL)
```python
import asyncio
from solana_bridge.solana_transaction import SolanaTransactionBuilder

async def test():
    builder = SolanaTransactionBuilder()
    balance = await builder.get_sol_balance("YOUR_SOLANA_ADDRESS")
    print(f"Balance: {balance} SOL")

asyncio.run(test())
```

### **3. Quote Test** (if you have SOL)
```python
import asyncio
from solana_bridge.bridge_orchestrator import bridge_orchestrator

async def test():
    quote = await bridge_orchestrator.get_bridge_quote(
        user_id=12345,
        sol_amount=0.1,
        polygon_address="YOUR_POLYGON_ADDRESS"
    )
    print(f"✅ Quote works: {quote is not None}")

asyncio.run(test())
```

---

## 📞 **IF RESTORE FAILS**

1. **Check Railway logs:**
   ```bash
   railway logs
   ```

2. **Check Python syntax:**
   ```bash
   python3 -m py_compile solana_bridge/bridge_orchestrator.py
   ```

3. **Check imports:**
   ```bash
   cd solana_bridge
   python3 -c "import bridge_orchestrator"
   ```

4. **Nuclear option - Full git reset:**
   ```bash
   git checkout main
   git pull origin main
   ```

---

## 🎯 **PREVENTION**

To avoid needing rollback:

1. ✅ Always test in a separate branch
2. ✅ Make small, incremental changes
3. ✅ Test after each change
4. ✅ Keep Railway logs open during modifications
5. ✅ Have backup terminal with backup commands ready

---

**Created:** Phase 2, Oct 4, 2025  
**Status:** Ready for emergency use  
**Next Update:** After Phase 3 modifications (if any)

