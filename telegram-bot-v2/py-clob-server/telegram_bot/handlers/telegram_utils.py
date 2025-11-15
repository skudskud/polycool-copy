#!/usr/bin/env python3
"""
Telegram Utilities - Resilient Message Operations
Handles timeouts, retries, and fallbacks for Telegram API operations
"""

import asyncio
import logging
from telegram.error import TimedOut, NetworkError, BadRequest

logger = logging.getLogger(__name__)


async def safe_edit_text(message, text, reply_markup=None, parse_mode=None, max_attempts=3):
    """
    Safely edit a Telegram message with timeout resilience.
    Falls back to reply_text if edit_text fails after max_attempts.

    PROBLEM SOLVED:
    - Original: `await message.edit_text(...)` would fail with httpx.WriteTimeout
    - Solution: Retry logic + fallback to reply_text (sends new message if edit fails)
    - Benefit: Users always see the result, even if Telegram API is slow

    Args:
        message: Telegram message object
        text: New message text
        reply_markup: Keyboard markup (InlineKeyboardMarkup)
        parse_mode: Parse mode ('HTML', 'Markdown', etc)
        max_attempts: Max retry attempts (default: 3)

    Returns:
        True if update successful, False otherwise

    Example:
        await safe_edit_text(
            query.message,
            "🎉 Trade successful!",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    """
    for attempt in range(max_attempts):
        try:
            logger.debug(f"[SAFE_EDIT] Attempting to edit message (attempt {attempt+1}/{max_attempts})")
            await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            logger.debug(f"[SAFE_EDIT] ✅ Message edited successfully")
            return True
        except (TimedOut, NetworkError) as e:
            logger.warning(f"[SAFE_EDIT] ⏱️ Telegram timeout/network error on attempt {attempt+1}: {type(e).__name__}")
            if attempt < max_attempts - 1:
                # Retry with exponential backoff: 0.5s, 1s, 1.5s
                wait_time = (attempt + 1) * 0.5
                logger.debug(f"[SAFE_EDIT] Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                # Final attempt: send new message instead
                logger.warning(f"[SAFE_EDIT] ❌ Max edit attempts reached. Sending new message (fallback).")
                try:
                    await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                    logger.info(f"[SAFE_EDIT] ✅ Sent fallback message via reply_text")
                    return True
                except Exception as err:
                    logger.error(f"[SAFE_EDIT] ❌ Fallback message also failed: {err}")
                    # Trade may have succeeded anyway, just can't update UI
                    return False
        except BadRequest as e:
            # Message already deleted or other bad request - can't edit
            logger.warning(f"[SAFE_EDIT] Message error (likely deleted): {e}")
            try:
                await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                logger.info(f"[SAFE_EDIT] ✅ Sent new message as fallback")
                return True
            except Exception:
                return False
        except Exception as e:
            logger.error(f"[SAFE_EDIT] Unexpected error: {type(e).__name__}: {e}")
            return False

    return False


async def safe_send_message(chat_id, text, reply_markup=None, parse_mode=None, bot=None, context=None, max_attempts=3):
    """
    Safely send a Telegram message with timeout resilience.

    Args:
        chat_id: Telegram chat ID
        text: Message text
        reply_markup: Keyboard markup
        parse_mode: Parse mode
        bot: Telegram bot instance (from context.bot if not provided)
        context: CallbackContext (used to get bot if not provided)
        max_attempts: Max retry attempts

    Returns:
        Message object if successful, None otherwise
    """
    if bot is None and context is None:
        logger.error("[SAFE_SEND] No bot or context provided")
        return None

    if bot is None:
        bot = context.bot

    for attempt in range(max_attempts):
        try:
            logger.debug(f"[SAFE_SEND] Sending message to {chat_id} (attempt {attempt+1}/{max_attempts})")
            message = await bot.send_message(
                chat_id,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            logger.debug(f"[SAFE_SEND] ✅ Message sent successfully")
            return message
        except (TimedOut, NetworkError) as e:
            logger.warning(f"[SAFE_SEND] ⏱️ Timeout on attempt {attempt+1}: {type(e).__name__}")
            if attempt < max_attempts - 1:
                wait_time = (attempt + 1) * 0.5
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"[SAFE_SEND] ❌ Max send attempts reached")
                return None
        except Exception as e:
            logger.error(f"[SAFE_SEND] Error: {e}")
            return None

    return None


async def safe_answer_callback_query(query, text=None, show_alert=False, max_attempts=3):
    """
    Safely answer a Telegram callback query with timeout resilience.

    Args:
        query: Callback query
        text: Notification text (optional)
        show_alert: Show as alert popup instead of toast
        max_attempts: Max retry attempts

    Returns:
        True if successful, False otherwise
    """
    for attempt in range(max_attempts):
        try:
            logger.debug(f"[SAFE_ANSWER] Answering callback (attempt {attempt+1}/{max_attempts})")
            await query.answer(text=text, show_alert=show_alert)
            logger.debug(f"[SAFE_ANSWER] ✅ Callback answered successfully")
            return True
        except (TimedOut, NetworkError) as e:
            logger.warning(f"[SAFE_ANSWER] ⏱️ Timeout on attempt {attempt+1}: {type(e).__name__}")
            if attempt < max_attempts - 1:
                wait_time = (attempt + 1) * 0.5
                await asyncio.sleep(wait_time)
            else:
                logger.warning(f"[SAFE_ANSWER] ❌ Max answer attempts reached")
                return False
        except Exception as e:
            logger.error(f"[SAFE_ANSWER] Error: {e}")
            return False

    return False
