#!/usr/bin/env python3
"""
Category Callbacks Module
Handles category browsing and filtering callbacks
"""

import logging
import os
import sys

# Import directly from callback_handlers to avoid circular imports
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# We'll define our own wrapper functions instead of importing
async def handle_category_menu_callback(query, callback_data, *args, **kwargs):
    """Wrapper for category menu callback"""
    # Import here to avoid circular imports
    from ..callback_handlers import handle_category_callback
    # For menu callbacks, pass minimal args
    return await handle_category_callback(query, callback_data, None, None)

async def handle_category_view_callback(query, callback_data, *args, **kwargs):
    """Wrapper for category view callback"""
    # Import here to avoid circular imports
    from ..callback_handlers import handle_category_callback
    # Extract session_manager and market_service from args if provided
    session_manager = args[0] if len(args) > 0 else None
    market_service = args[1] if len(args) > 1 else None
    return await handle_category_callback(query, callback_data, session_manager, market_service)

async def handle_category_filter_callback(query, callback_data, *args, **kwargs):
    """Wrapper for category filter callback"""
    # Import here to avoid circular imports
    from ..callback_handlers import handle_category_filter_callback as _filter_callback
    # Extract args
    session_manager = args[0] if len(args) > 0 else None
    market_db = args[1] if len(args) > 1 else None
    return await _filter_callback(query, callback_data, session_manager, market_db)

logger = logging.getLogger(__name__)

# Wrapper to handle both menu and view
async def handle_category_menu_or_view(query, callback_data, *args, kwargs):
    """Route to appropriate category handler"""
    if callback_data.startswith("cat_menu_"):
        return await handle_category_menu_callback(query, callback_data, *args, kwargs)
    else:
        return await handle_category_view_callback(query, callback_data, *args, kwargs)

__all__ = [
    'handle_category_menu_or_view',
    'handle_category_filter_callback'
]

