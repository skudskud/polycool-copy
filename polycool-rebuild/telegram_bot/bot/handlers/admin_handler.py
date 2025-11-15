"""
Admin command handler
"""
from telegram import Update
from telegram.ext import ContextTypes

async def handle_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /admin command"""
    await update.message.reply_text("⚡ Admin - To be implemented")
