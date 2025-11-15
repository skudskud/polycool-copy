#!/usr/bin/env python3
"""
TPSL Callbacks Module
Handles all Take Profit / Stop Loss callbacks
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

# Try to import from tpsl_handlers module
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from tpsl_handlers import (
        set_tpsl_callback,
        edit_tpsl_by_id_callback,
        edit_tpsl_callback,
        update_tp_preset_callback,
        update_sl_preset_callback,
        update_tp_callback,
        update_sl_callback,
        view_all_tpsl_callback,
        cancel_tpsl_callback
    )
except ImportError:
    # Fallback stubs if module doesn't exist
    async def set_tpsl_callback(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ TPSL feature not available")
    
    async def edit_tpsl_by_id_callback(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ TPSL feature not available")
    
    async def edit_tpsl_callback(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ TPSL feature not available")
    
    async def update_tp_preset_callback(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ TPSL feature not available")
    
    async def update_sl_preset_callback(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ TPSL feature not available")
    
    async def update_tp_callback(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ TPSL feature not available")
    
    async def update_sl_callback(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ TPSL feature not available")
    
    async def view_all_tpsl_callback(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ TPSL feature not available")
    
    async def cancel_tpsl_callback(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ TPSL feature not available")

__all__ = [
    'set_tpsl_callback',
    'edit_tpsl_by_id_callback',
    'edit_tpsl_callback',
    'update_tp_preset_callback',
    'update_sl_preset_callback',
    'update_tp_callback',
    'update_sl_callback',
    'view_all_tpsl_callback',
    'cancel_tpsl_callback'
]

