#!/usr/bin/env python3
"""
Check if multiple instances are using the same Telegram bot token
This will tell us if another instance is stealing updates
"""
import asyncio
import sys
from telegram import Bot
from telegram.error import TelegramError

BOT_TOKEN = "8290543310:AAHYLEky6hWoRNbEm_P5mAEC9k2vkDI_pIg"

async def check_bot_status():
    """Check bot status and get webhook info"""
    try:
        bot = Bot(token=BOT_TOKEN)
        
        print("🔍 Checking bot status...")
        print("=" * 60)
        
        # Get bot info
        me = await bot.get_me()
        print(f"✅ Bot Info:")
        print(f"   Name: {me.first_name}")
        print(f"   Username: @{me.username}")
        print(f"   ID: {me.id}")
        print()
        
        # Check webhook status (if webhook is set, polling won't work!)
        webhook_info = await bot.get_webhook_info()
        print(f"🔍 Webhook Status:")
        print(f"   URL: {webhook_info.url or 'None (using polling)'}")
        print(f"   Pending Updates: {webhook_info.pending_update_count}")
        print(f"   Max Connections: {webhook_info.max_connections}")
        print(f"   Last Error: {webhook_info.last_error_message or 'None'}")
        print()
        
        # If webhook is set, that's the problem!
        if webhook_info.url:
            print("❌ PROBLEM FOUND: Webhook is set!")
            print("   This prevents polling from working.")
            print("   Deleting webhook now...")
            await bot.delete_webhook(drop_pending_updates=False)
            print("✅ Webhook deleted! Try the bot again.")
        else:
            print("✅ No webhook set - polling should work")
            print()
            print("🔍 If bot still doesn't respond, possible causes:")
            print("   1. Another instance is running with same token")
            print("   2. Telegram API is having issues")
            print("   3. Bot is blocked by Telegram")
        
        print("=" * 60)
        
    except TelegramError as e:
        print(f"❌ Telegram API Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(check_bot_status())

