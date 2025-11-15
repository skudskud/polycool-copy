#!/usr/bin/env python3
"""
Real-time monitor to detect if bot token is being used by multiple instances
Run this WHILE sending /start to the bot to see if updates arrive
"""
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8290543310:AAHYLEky6hWoRNbEm_P5mAEC9k2vkDI_pIg"

async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log every single update"""
    if update.message:
        print(f"✅ RECEIVED: Message from @{update.effective_user.username} (ID: {update.effective_user.id})")
        print(f"   Text: {update.message.text}")
        print(f"   Time: {update.message.date}")
    elif update.callback_query:
        print(f"✅ RECEIVED: Callback from @{update.effective_user.username} (ID: {update.effective_user.id})")
        print(f"   Data: {update.callback_query.data}")
    else:
        print(f"✅ RECEIVED: Update type {type(update)}")
    print()

async def main():
    print("🔍 Starting bot update monitor...")
    print("=" * 60)
    print("📱 Send /start to your bot NOW and watch for updates here")
    print("=" * 60)
    print()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Catch ALL updates
    app.add_handler(MessageHandler(filters.ALL, log_update))
    
    # Initialize and start polling
    await app.initialize()
    await app.start()
    
    print("✅ Polling started - listening for updates...")
    print("   If you send /start and see NOTHING here, another instance is stealing updates!")
    print()
    
    await app.updater.start_polling(drop_pending_updates=False)
    
    # Keep alive
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping monitor...")
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())

