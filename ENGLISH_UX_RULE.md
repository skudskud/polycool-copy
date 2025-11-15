# 🎯 RULE: ENGLISH ONLY FOR UX

## 🚨 CRITICAL RULE

**ALL user-facing text in the Telegram bot MUST be in ENGLISH.**

**NO FRENCH TEXT ALLOWED in any user interface elements:**

### ✅ ALLOWED (English)
- Error messages
- Button labels
- Help text
- Command descriptions
- Status messages
- Onboarding flow
- All user communications

### ❌ FORBIDDEN (French)
- "Une erreur s'est produite"
- "Veuillez réessayer"
- "Erreur lors de la création"
- Any French text in UI

## 📋 Implementation

**Files to check regularly:**
- `telegram_bot/bot/handlers/*.py`
- `telegram_bot/bot/application.py`
- All user-facing strings

**Pattern to avoid:**
```python
"❌ Une erreur s'est produite. Veuillez réessayer."
```

**Correct pattern:**
```python
"❌ An error occurred. Please try again."
```

## 🔍 Validation

**Before committing any UX changes:**
1. Search for French words: `grep -r "Une erreur\|Veuillez\|réessayer" telegram_bot/`
2. If found → Fix immediately
3. Only then commit

## 🎯 Why This Matters

- **International users:** English is universal
- **Consistency:** All UI in one language
- **Professional:** English for crypto/trading apps
- **Maintenance:** Easier for international dev team

## 📝 Quick Translation Guide

| French | English |
|--------|---------|
| Une erreur s'est produite | An error occurred |
| Veuillez réessayer | Please try again |
| Erreur lors de la création | Error creating account |
| Voir vos positions | View your positions |
| Gérer votre wallet | Manage your wallet |

**REMINDER: This rule applies to ALL user-facing text. No exceptions.**
