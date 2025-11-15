# 🔌 **BRIDGE INTEGRATION PLAN**
## How to Call Bridge from Streamlined User Flow

**Purpose:** Define how to trigger bridge automatically after funding detection in the new streamlined onboarding.

---

## 🎯 **CURRENT BRIDGE TRIGGER**

### **Manual Trigger (Current System)**
```
User sends SOL to wallet
    ↓
User types: /bridge
    ↓
Bot shows balance + options
    ↓
User clicks "Bridge (Auto)"
    ↓
Bot shows confirmation
    ↓
User clicks "✅ Confirm"
    ↓
Bridge executes
```

**Problem:** Too many steps (5+ user interactions)

---

## 🚀 **STREAMLINED TRIGGER (Phase 5 Goal)**

### **Automatic Trigger (New System)**
```
User sends SOL to wallet
    ↓
AutoApprovalService detects funding
    ↓
Automatically triggers bridge
    ↓
Live status updates in same message
    ↓
Bridge completes → Auto-approval → API gen
```

**Result:** 1 click instead of 5+

---

## 🔧 **INTEGRATION APPROACH**

### **Option A: Modify Auto-Approval Service (Recommended)**

**Current:** `AutoApprovalService` only monitors Polygon wallet for USDC.e funding

**New:** `AutoApprovalService` ALSO monitors Solana wallet for SOL funding

**File to modify:** `core/services/auto_approval_service.py`

**Integration Point:**
```python
# In auto_approval_service.py

async def monitor_funding(self):
    """Monitor for both Polygon AND Solana funding"""
    
    for user in self.get_users_awaiting_funding():
        # EXISTING: Check Polygon wallet for USDC.e
        if self.check_polygon_funding(user):
            await self.start_approval_process(user)
        
        # NEW: Check Solana wallet for SOL
        if user.solana_address and not user.funded:
            sol_balance = await self.check_sol_balance(user.solana_address)
            
            if sol_balance >= 0.1:  # Minimum for bridge
                # TRIGGER BRIDGE AUTOMATICALLY
                await self.trigger_automatic_bridge(user, sol_balance)
```

**New Method to Add:**
```python
async def trigger_automatic_bridge(self, user, sol_balance: float):
    """
    Automatically bridge SOL → Polygon when funding detected
    
    Replaces manual /bridge command flow
    """
    from solana_bridge.bridge_v3 import bridge_v3
    from telegram_bot.services.notification_service import notification_service
    
    # Update user status
    await notification_service.send_message(
        user.telegram_user_id,
        "⚡ SOL funding detected!\n\n"
        f"Balance: {sol_balance:.4f} SOL\n\n"
        "🚀 Starting automatic bridge..."
    )
    
    # Execute bridge
    result = await bridge_v3.execute_full_bridge(
        sol_amount=sol_balance - 0.00002,  # Keep tiny amount for fees
        solana_address=user.solana_address,
        solana_private_key=user.solana_private_key,
        polygon_address=user.polygon_address,
        polygon_private_key=user.polygon_private_key,
        status_callback=lambda msg: notification_service.send_message(
            user.telegram_user_id, msg
        )
    )
    
    if result and result.get('success'):
        # Mark as funded
        user.funded = True
        db.commit()
        
        # Continue to approval process
        await self.start_approval_process(user)
```

---

### **Option B: Create Dedicated Bridge Service**

**New file:** `core/services/bridge_service.py`

```python
#!/usr/bin/env python3
"""
Bridge Service - Automatic SOL bridging for streamlined flow
Coordinates between funding detection and bridge execution
"""

import logging
from typing import Optional, Callable
from solana_bridge.bridge_v3 import bridge_v3
from .user_service import UserService

logger = logging.getLogger(__name__)

class BridgeService:
    """
    Manages automatic bridge triggering for streamlined onboarding
    """
    
    def __init__(self):
        self.user_service = UserService()
    
    async def auto_bridge_on_funding(
        self,
        telegram_user_id: int,
        status_callback: Optional[Callable] = None
    ) -> bool:
        """
        Automatically bridge when SOL funding detected
        
        Called by:
        - AutoApprovalService when monitoring funding
        - /start command when user clicks "I've Funded"
        
        Returns:
            True if bridge successful, False otherwise
        """
        try:
            # Get user
            user = self.user_service.get_user(telegram_user_id)
            if not user or not user.solana_address:
                return False
            
            # Check balance
            from solana_bridge.solana_transaction import SolanaTransactionBuilder
            builder = SolanaTransactionBuilder()
            balance = await builder.get_sol_balance(user.solana_address)
            
            if balance < 0.1:
                logger.info(f"User {telegram_user_id} balance too low: {balance} SOL")
                return False
            
            # Bridge amount (keep tiny reserve for fees)
            bridge_amount = balance - 0.00002
            
            logger.info(f"🌉 Auto-bridging {bridge_amount} SOL for user {telegram_user_id}")
            
            # Execute bridge
            result = await bridge_v3.execute_full_bridge(
                sol_amount=bridge_amount,
                solana_address=user.solana_address,
                solana_private_key=user.solana_private_key,
                polygon_address=user.polygon_address,
                polygon_private_key=user.polygon_private_key,
                status_callback=status_callback
            )
            
            if result and result.get('success'):
                # Mark user as funded
                from database import db_manager
                db_manager.update_user_approvals(
                    telegram_user_id=telegram_user_id,
                    funded=True
                )
                logger.info(f"✅ Auto-bridge successful for user {telegram_user_id}")
                return True
            
            logger.error(f"❌ Auto-bridge failed for user {telegram_user_id}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error in auto_bridge_on_funding: {e}")
            return False
    
    def get_bridge_status(self, telegram_user_id: int) -> Optional[dict]:
        """Get current bridge status for user"""
        from solana_bridge.bridge_orchestrator import bridge_orchestrator
        return bridge_orchestrator.get_bridge_status(telegram_user_id)

# Global instance
bridge_service = BridgeService()
```

---

## 📍 **INTEGRATION POINTS**

### **1. From `/start` Command (Phase 5)**

**File:** `telegram_bot/handlers/setup_handlers.py`

```python
async def handle_start_funded_button(update: Update, context):
    """
    User clicked "I've Funded - Start Bridge" button in /start
    """
    user_id = update.effective_user.id
    query = update.callback_query
    
    # Edit message to show bridge starting
    await query.edit_message_text(
        "🚀 Checking your SOL balance...",
        parse_mode='Markdown'
    )
    
    # Define status callback
    async def status_update(message: str):
        try:
            await query.message.edit_text(
                f"🌉 **BRIDGE IN PROGRESS**\n\n{message}",
                parse_mode='Markdown'
            )
        except:
            pass
    
    # Trigger automatic bridge
    from core.services.bridge_service import bridge_service
    success = await bridge_service.auto_bridge_on_funding(
        telegram_user_id=user_id,
        status_callback=status_update
    )
    
    if success:
        await query.message.edit_text(
            "✅ **Bridge complete!**\n\n"
            "🔄 Auto-approving contracts...",
            parse_mode='Markdown'
        )
        # Auto-approval will continue automatically
    else:
        await query.message.edit_text(
            "❌ **Bridge failed**\n\n"
            "Please check your SOL balance and try again with /bridge",
            parse_mode='Markdown'
        )
```

---

### **2. From Auto-Approval Service (Background)**

**File:** `core/services/auto_approval_service.py`

```python
# Add to monitoring loop

async def check_and_process_new_funding(self):
    """Check for new SOL funding and trigger bridge"""
    
    users_waiting = self.get_users_at_stage(UserStage.SOL_GENERATED)
    
    for user in users_waiting:
        if not user.solana_address:
            continue
        
        # Check SOL balance
        from solana_bridge.solana_transaction import SolanaTransactionBuilder
        builder = SolanaTransactionBuilder()
        
        try:
            balance = await builder.get_sol_balance(user.solana_address)
            
            if balance >= 0.1:
                logger.info(f"💰 Funding detected for user {user.telegram_user_id}: {balance} SOL")
                
                # Notify user
                await self.telegram_service.send_message(
                    user.telegram_user_id,
                    f"⚡ **Funding detected!**\n\n"
                    f"Balance: {balance:.4f} SOL\n\n"
                    f"🚀 Starting automatic bridge..."
                )
                
                # Trigger bridge
                from core.services.bridge_service import bridge_service
                await bridge_service.auto_bridge_on_funding(
                    telegram_user_id=user.telegram_user_id,
                    status_callback=lambda msg: self.telegram_service.send_message(
                        user.telegram_user_id, msg
                    )
                )
        except Exception as e:
            logger.error(f"Error checking funding for user {user.telegram_user_id}: {e}")
```

---

## 🔗 **BRIDGE ENTRY POINTS SUMMARY**

### **Current Entry Points:**
1. `/bridge` command → Manual workflow
2. Direct callback: `confirm_bridge_{amount}`
3. Programmatic: `bridge_orchestrator.complete_bridge_workflow()`

### **New Entry Points (Phase 5):**
4. `/start` → "I've Funded" button → `bridge_service.auto_bridge_on_funding()`
5. `AutoApprovalService` → Background monitoring → Auto-trigger
6. Any future UI that needs bridge → Call `bridge_service.auto_bridge_on_funding()`

---

## 📊 **NOTIFICATION FLOW**

### **Current (Manual):**
```
User clicks button → Telegram shows confirmation → User confirms → Status updates
```

### **New (Automatic):**
```
Funding detected → Immediate notification:
  "⚡ Funding detected! Starting bridge..."
    ↓
  "✍️ Signing transaction..."
    ↓
  "📡 Broadcasting..."
    ↓
  "✅ Confirmed on Solana!"
    ↓
  "⏳ Waiting for Polygon..."
    ↓
  "✅ Received on Polygon!"
    ↓
  "🔄 Swapping POL..."
    ↓
  "🎉 Bridge complete!"
    ↓
  "🔄 Auto-approving contracts..."
```

All in same message (via edit_message_text)

---

## ⚙️ **CONFIGURATION**

### **Bridge Settings**

Add to `config.py`:
```python
# Automatic bridge settings
AUTO_BRIDGE_ENABLED = True
AUTO_BRIDGE_MIN_SOL = 0.1  # Minimum SOL to trigger
AUTO_BRIDGE_RESERVE = 0.00002  # Keep for fees
AUTO_BRIDGE_TIMEOUT = 600  # 10 minutes
```

### **Feature Flag**

Allow disabling auto-bridge if issues:
```python
if not config.AUTO_BRIDGE_ENABLED:
    # Fall back to manual /bridge command
    await send_message(user_id, "Please use /bridge to continue")
    return
```

---

## 🧪 **TESTING PLAN**

### **Test 1: Manual Trigger from /start**
```
1. User runs /start
2. Fund SOL wallet
3. Click "I've Funded" button
4. Verify bridge executes
5. Verify status updates appear
6. Verify bridge completes successfully
```

### **Test 2: Automatic Background Trigger**
```
1. User runs /start
2. Note SOL address
3. Send SOL from external wallet
4. Wait up to 1 minute (monitoring interval)
5. Verify bot sends "Funding detected!" message
6. Verify bridge executes automatically
7. Verify completion
```

### **Test 3: Error Handling**
```
1. Trigger bridge with insufficient SOL
2. Verify error message
3. Trigger bridge during network outage
4. Verify fallback to /bridge command
```

---

## ✅ **IMPLEMENTATION CHECKLIST**

### **Phase 3 (Command Redesign):**
- [ ] Keep `/bridge` command but hide from menu
- [ ] Command still works if typed manually
- [ ] All bridge functionality preserved

### **Phase 5 (/start Enhancement):**
- [ ] Add "I've Funded" button to /start
- [ ] Implement `handle_start_funded_button()`
- [ ] Connect to `bridge_service.auto_bridge_on_funding()`
- [ ] Test manual trigger

### **Phase 6 (Background Integration):**
- [ ] Create `BridgeService` class
- [ ] Add SOL balance checking to `AutoApprovalService`
- [ ] Implement automatic bridge trigger
- [ ] Add notification service integration
- [ ] Test background trigger

---

**Status:** Ready for Phase 5 implementation  
**Dependencies:** Phase 1 (User states) ✅, Phase 2 (Bridge backup) ✅  
**Next:** Implement in Phase 5 after command redesign

---

*Part of Streamlined User Onboarding Roadmap - Phase 2 Documentation*

