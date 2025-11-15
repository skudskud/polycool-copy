"""
Simple Telegram Bot Test - Hello World
Just to verify that the bot can receive and respond to messages
"""
import os
import logging
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import uvicorn

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI()

# Telegram bot token - this should be set as environment variable
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
    exit(1)

# Initialize Telegram application
application = Application.builder().token(BOT_TOKEN).build()

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "bot_token_configured": bool(BOT_TOKEN)}

# Webhook endpoint for Telegram
@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        logger.info(f"✅ Webhook processed for user {update.effective_user.id if update.effective_user else 'unknown'}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}

# Telegram bot handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    logger.info(f"Received /start from user {update.effective_user.id}")
    await update.message.reply_text(
        "🤖 Hello! I'm your test bot.\n\n"
        "I can receive and respond to messages!\n\n"
        "Try sending me any message and I'll echo it back."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    logger.info(f"Received /help from user {update.effective_user.id}")
    await update.message.reply_text(
        "📋 Available commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/status - Check bot status\n\n"
        "Send any message and I'll echo it back!"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    logger.info(f"Received /status from user {update.effective_user.id}")
    await update.message.reply_text(
        f"✅ Bot is running!\n\n"
        f"User ID: {update.effective_user.id}\n"
        f"Username: {update.effective_user.username or 'N/A'}\n"
        f"Bot Token: {'✅ Configured' if BOT_TOKEN else '❌ Missing'}"
    )

async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Echo back any text message"""
    logger.info(f"Echoing message from user {update.effective_user.id}: {update.message.text}")
    await update.message.reply_text(
        f"🔄 You said: {update.message.text}\n\n"
        f"Message echoed successfully! ✅"
    )

# Add handlers
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("status", status_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_message))

# Startup event
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Telegram Test Bot starting up...")
    logger.info(f"🤖 Bot token configured: {bool(BOT_TOKEN)}")

    # Initialize Telegram application
    try:
        await application.initialize()
        logger.info("✅ Telegram application initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Telegram application: {e}")

    logger.info("✅ Webhook handlers registered")
    logger.info("🌐 FastAPI app ready")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
