#!/usr/bin/env python3
"""
Smart Trading Pagination Handlers
Handles pagination callbacks for /smart_trading command
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from .smart_trading_handler import _build_page_message

logger = logging.getLogger(__name__)


async def smart_page_next_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """Handle 'Next Page' button click"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    session = session_manager.get(user_id)
    
    # Get pagination data
    pagination = session.get('smart_trades_pagination')
    if not pagination:
        await query.edit_message_text("⚠️ Session expired. Please run /smart_trading again.")
        return
    
    # Move to next page
    current_page = pagination['current_page']
    total_pages = pagination['total_pages']
    
    if current_page >= total_pages:
        await query.answer("Already on last page!", show_alert=True)
        return
    
    # Update session
    pagination['current_page'] = current_page + 1
    
    # Build new page
    message, buttons = _build_page_message(
        pagination['current_page'],
        pagination,
        pagination.get('wallets_cache', {}),
        pagination.get('markets_cache', {})
    )
    
    # Edit message (update in place)
    await query.edit_message_text(
        text=message,
        parse_mode='Markdown',
        reply_markup=buttons,
        disable_web_page_preview=True
    )
    
    logger.info(f"📄 [PAGINATION] User {user_id} navigated to page {pagination['current_page']}/{total_pages}")


async def smart_page_prev_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """Handle 'Previous Page' button click"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    session = session_manager.get(user_id)
    pagination = session.get('smart_trades_pagination')
    
    if not pagination:
        await query.edit_message_text("⚠️ Session expired. Please run /smart_trading again.")
        return
    
    current_page = pagination['current_page']
    
    if current_page <= 1:
        await query.answer("Already on first page!", show_alert=True)
        return
    
    # Update session
    pagination['current_page'] = current_page - 1
    
    # Build new page
    message, buttons = _build_page_message(
        pagination['current_page'],
        pagination,
        pagination.get('wallets_cache', {}),
        pagination.get('markets_cache', {})
    )
    
    # Edit message
    await query.edit_message_text(
        text=message,
        parse_mode='Markdown',
        reply_markup=buttons,
        disable_web_page_preview=True
    )
    
    logger.info(f"📄 [PAGINATION] User {user_id} navigated to page {pagination['current_page']}/{pagination['total_pages']}")


async def smart_page_first_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """Handle 'Back to Page 1' button click"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    session = session_manager.get(user_id)
    pagination = session.get('smart_trades_pagination')
    
    if not pagination:
        await query.edit_message_text("⚠️ Session expired. Please run /smart_trading again.")
        return
    
    # Set to page 1
    pagination['current_page'] = 1
    
    # Build page 1
    message, buttons = _build_page_message(
        1,
        pagination,
        pagination.get('wallets_cache', {}),
        pagination.get('markets_cache', {})
    )
    
    # Edit message
    await query.edit_message_text(
        text=message,
        parse_mode='Markdown',
        reply_markup=buttons,
        disable_web_page_preview=True
    )
    
    logger.info(f"📄 [PAGINATION] User {user_id} jumped back to page 1/{pagination['total_pages']}")


async def smart_page_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """Handle page indicator button (non-functional, just shows info)"""
    query = update.callback_query
    
    user_id = update.effective_user.id
    session = session_manager.get(user_id)
    pagination = session.get('smart_trades_pagination')
    
    if pagination:
        await query.answer(
            f"Showing page {pagination['current_page']} of {pagination['total_pages']}",
            show_alert=False
        )
    else:
        await query.answer()

