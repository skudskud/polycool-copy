# 🗑️ Guide to Delete US Supabase Project

## Project Details

**Project to Delete:**
- **Name:** "skudskud's Project"
- **ID:** `gvckzwmuuyrlcyjmgdpo`
- **Region:** US East (us-east-1)
- **Status:** ACTIVE_HEALTHY
- **Plan:** Pro Plan

**Active Project (Keep This One):**
- **Name:** "polycool v2 europe"
- **ID:** `fkksycggxaaohlfdwfle`
- **Region:** EU West (eu-west-2)
- **Status:** ACTIVE_HEALTHY

## ⚠️ Important Warnings

1. **Deletion is PERMANENT** - Cannot be undone
2. **All data will be lost** - Make sure you have backups if needed
3. **Verify nothing is using it** - Check Railway/Docker env vars first

## Pre-Deletion Checklist

### ✅ Step 1: Verify Nothing is Using It

Check all your services:

```bash
# Check Railway services
railway variables --service "Data Ingestion" | grep DATABASE_URL
railway variables --service "resolution-worker" | grep DATABASE_URL

# Should NOT contain: db.gvckzwmuuyrlcyjmgdpo.supabase.co
# Should contain: db.fkksycggxaaohlfdwfle.supabase.co
```

### ✅ Step 2: Check Local Environment Files

```bash
# Search for the US project ID
grep -r "gvckzwmuuyrlcyjmgdpo" .
grep -r "db.gvckzwmuuyrlcyjmgdpo" .

# If found, update to EU project
```

### ✅ Step 3: Verify Active Project Has All Data

Make sure your EU project has everything you need:
- All tables and data
- All migrations applied
- All environment variables point to EU project

## How to Delete (Supabase Dashboard)

### Method 1: Via Web Dashboard

1. **Go to Supabase Dashboard:**
   - https://supabase.com/dashboard
   - Login to your account

2. **Select the Project:**
   - Click on "skudskud's Project" (US East)

3. **Navigate to Settings:**
   - Click on "Settings" (gear icon) in the sidebar
   - Go to "General" section

4. **Delete Project:**
   - Scroll to bottom of General settings
   - Find "Danger Zone" section
   - Click "Delete Project" button
   - Type project name to confirm: `skudskud's Project`
   - Click "Delete Project" to confirm

5. **Wait for Deletion:**
   - Project will be deleted (may take a few minutes)
   - You'll receive a confirmation email

### Method 2: Via Supabase CLI (if installed)

```bash
# Login to Supabase CLI
supabase login

# List projects
supabase projects list

# Delete project (WARNING: This deletes immediately!)
supabase projects delete gvckzwmuuyrlcyjmgdpo
```

⚠️ **Note:** CLI delete might not be available for Pro plans. Use dashboard method.

## After Deletion

### Verify It's Gone

1. Check Supabase dashboard - project should no longer appear
2. Check billing - should stop charging for this project
3. Verify active project still works

### Update Documentation

If you find any references to the US project in your codebase, update them:

```bash
# Find all references
grep -r "gvckzwmuuyrlcyjmgdpo" .

# Update to EU project ID if needed
```

## Cost Impact

**Current:**
- US Project: Pro Plan (~$25/month base + usage)
- EU Project: Pro Plan (~$25/month base + usage)
- **Total:** ~$50/month base + usage for both

**After Deletion:**
- EU Project only: ~$25/month base + usage
- **Savings:** ~$25/month base fee

**Plus:** This will **STOP the egress charges from the US project** if anything was accidentally using it!

## Safety Check

Before deleting, double-check:

- [ ] Railway `DATABASE_URL` variables all point to EU project
- [ ] No local `.env` files reference US project
- [ ] No Docker containers using US project
- [ ] No cron jobs or scheduled tasks using US project
- [ ] You have backups of any data you need from US project

## If You're Unsure

If you want to be extra safe:

1. **Pause it first** (if downgraded to free tier)
2. **Monitor for 1 week** - see if anything breaks
3. **Then delete** once confirmed nothing is using it

But since Pro plan projects can't be paused, you'll need to either:
- Downgrade to free tier first (then pause)
- Or just delete it directly

## Quick Decision Tree

**If you're 100% sure nothing uses it:**
→ Delete it now (saves $25/month + stops any egress charges)

**If you're not sure:**
→ Check Railway env vars first, then delete

**If you want to be super safe:**
→ Monitor for 24 hours, then delete

