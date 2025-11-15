#!/usr/bin/env python3
"""
Setup Callbacks Module
Handles all setup, onboarding, and restart callbacks
"""

import logging
import os
import sys

# Temporary: Import from parent callback_handlers.py
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ..callback_handlers import (
    handle_confirm_restart,
    handle_cancel_restart,
    handle_auto_approve,
    handle_generate_api,
    handle_test_api,
    handle_start_streamlined_bridge,
    handle_refresh_sol_balance_start,
    handle_refresh_start,
    handle_cancel_streamlined_bridge
)

logger = logging.getLogger(__name__)

__all__ = [
    'handle_confirm_restart',
    'handle_cancel_restart',
    'handle_auto_approve',
    'handle_generate_api',
    'handle_test_api',
    'handle_start_streamlined_bridge',
    'handle_refresh_sol_balance_start',
    'handle_refresh_start',
    'handle_cancel_streamlined_bridge'
]

