#!/usr/bin/env python3
"""
Callback Registry System
Centralized pattern-to-handler mapping for all Telegram inline button callbacks
"""

import logging
from typing import Callable, Dict, Tuple, Optional

logger = logging.getLogger(__name__)


class CallbackRegistry:
    """
    Registry for mapping callback patterns to handler functions
    Supports:
    - Exact matches: "button_name"
    - Prefix matches: "button_" (matches anything starting with "button_")
    - Pattern matches: regex-like matching
    """

    def __init__(self):
        self.handlers: Dict[str, Callable] = {}
        self.patterns: list = []  # List of (pattern_type, pattern_str, handler) tuples
        self._initialized = False

    def register(self, pattern: str, handler: Callable, pattern_type: str = "prefix"):
        """
        Register a callback pattern with its handler

        Args:
            pattern: The pattern to match (e.g., "quick_buy_", "confirm_order")
            handler: The async handler function to call
            pattern_type: Type of matching - "exact", "prefix", or "regex"
        """
        self.patterns.append((pattern_type, pattern, handler))
        logger.debug(f"📌 Registered callback pattern: {pattern} ({pattern_type})")

    def get_handler(self, callback_data: str) -> Optional[Callable]:
        """
        Find and return the handler for a given callback_data

        Returns the first matching handler based on registration order
        """
        for pattern_type, pattern, handler in self.patterns:
            if pattern_type == "exact" and callback_data == pattern:
                return handler
            elif pattern_type == "prefix" and callback_data.startswith(pattern):
                return handler
            elif pattern_type == "regex":
                import re
                if re.match(pattern, callback_data):
                    return handler

        return None

    def initialize(self):
        """Initialize all callback handlers (import modules and register patterns)"""
        if self._initialized:
            return

        logger.info("🚀 Initializing callback registry...")

        # Import and register all callback modules
        try:
            from . import buy_callbacks
            self._register_buy_callbacks(buy_callbacks)
        except Exception as e:
            logger.error(f"Error registering buy callbacks: {e}")

        try:
            from . import sell_callbacks
            self._register_sell_callbacks(sell_callbacks)
        except Exception as e:
            logger.error(f"Error registering sell callbacks: {e}")

        try:
            from . import positions_callbacks
            self._register_positions_callbacks(positions_callbacks)
        except Exception as e:
            logger.error(f"Error registering positions callbacks: {e}")

        try:
            from . import analytics_callbacks
            self._register_analytics_callbacks(analytics_callbacks)
        except Exception as e:
            logger.error(f"Error registering analytics callbacks: {e}")

        try:
            from . import market_callbacks
            self._register_market_callbacks(market_callbacks)
        except Exception as e:
            logger.error(f"Error registering market callbacks: {e}")

        try:
            from . import wallet_callbacks
            self._register_wallet_callbacks(wallet_callbacks)
        except Exception as e:
            logger.error(f"Error registering wallet callbacks: {e}")

        try:
            from . import setup_callbacks
            self._register_setup_callbacks(setup_callbacks)
        except Exception as e:
            logger.error(f"Error registering setup callbacks: {e}")

        try:
            from . import smart_trading_callbacks
            self._register_smart_trading_callbacks(smart_trading_callbacks)
        except Exception as e:
            logger.error(f"Error registering smart trading callbacks: {e}")

        try:
            from . import tpsl_callbacks
            self._register_tpsl_callbacks(tpsl_callbacks)
        except Exception as e:
            logger.error(f"Error registering TPSL callbacks: {e}")

        try:
            from . import category_callbacks
            self._register_category_callbacks(category_callbacks)
        except Exception as e:
            logger.error(f"Error registering category callbacks: {e}")

        try:
            from . import bridge_callbacks
            self._register_bridge_callbacks(bridge_callbacks)
        except Exception as e:
            logger.error(f"Error registering bridge callbacks: {e}")

        try:
            from . import copy_trading_callbacks
            self._register_copy_trading_callbacks(copy_trading_callbacks)
        except Exception as e:
            logger.error(f"Error registering copy trading callbacks: {e}")

        self._initialized = True
        logger.info(f"✅ Callback registry initialized with {len(self.patterns)} patterns")

    def _register_buy_callbacks(self, module):
        """Register all buy-related callbacks"""
        self.register("quick_buy_", module.handle_quick_buy_callback, "prefix")
        self.register("confirm_order", module.handle_confirm_order_callback, "prefix")
        self.register("buy_custom", module.handle_custom_buy_callback, "exact")
        # handle_buy_prompt_callback is handled directly in callback_handlers.py, not via registry

    def _register_sell_callbacks(self, module):
        """Register all sell-related callbacks"""
        self.register("sell_", module.handle_sell_callback, "prefix")
        self.register("sell_usd_", module.handle_sell_usd_callback, "prefix")
        self.register("sell_all_", module.handle_sell_all_callback, "prefix")
        self.register("sell_quick_", module.handle_sell_quick_callback, "prefix")
        self.register("conf_sell_", module.handle_confirm_sell_callback, "prefix")
        self.register("conf_usd_sell_", module.handle_confirm_usd_sell_callback, "prefix")
        self.register("sell_idx_", module.handle_sell_idx_callback, "prefix")

    def _register_positions_callbacks(self, module):
        """Register all position-related callbacks"""
        self.register("pos_", module.handle_position_callback, "prefix")
        self.register("sell_pos_", module.handle_sell_position, "prefix")
        self.register("execute_sell_", module.handle_execute_sell, "prefix")

    def _register_analytics_callbacks(self, module):
        """Register all analytics callbacks"""
        self.register("detailed_pnl", module.handle_detailed_pnl, "exact")
        self.register("trading_stats", module.handle_trading_stats, "exact")
        self.register("refresh_pnl", module.handle_refresh_pnl, "exact")
        self.register("show_pnl", module.handle_show_pnl, "exact")
        self.register("refresh_history", module.handle_refresh_history, "exact")
        self.register("export_history", module.handle_export_history, "exact")
        self.register("show_history", module.handle_show_history, "exact")
        self.register("stats_", module.handle_stats_period, "prefix")
        self.register("refresh_performance", module.handle_refresh_performance, "exact")

    def _register_market_callbacks(self, module):
        """Register all market-related callbacks"""
        self.register("market_select_", module.handle_market_select_callback, "prefix")
        self.register("market_", module.handle_market_callback, "prefix")
        self.register("markets_page_", module.handle_markets_page_callback, "prefix")
        self.register("filter_", module.handle_market_filter_callback, "prefix")
        self.register("event_select_", module.handle_event_select_callback, "prefix")
        self.register("group_select_", module.handle_event_select_callback, "prefix")
        self.register("smart_view_", module.handle_smart_view_market_callback, "prefix")
        self.register("smart_buy_", module.handle_smart_quick_buy_callback, "prefix")

    def _register_wallet_callbacks(self, module):
        """Register all wallet-related callbacks"""
        self.register("show_wallet", module.handle_show_wallet, "exact")
        self.register("show_funding", module.handle_show_funding, "exact")
        self.register("show_polygon_key", module.handle_show_polygon_key, "exact")
        self.register("show_solana_key", module.handle_show_solana_key, "exact")
        self.register("hide_polygon_key", module.handle_hide_polygon_key, "exact")
        self.register("hide_solana_key", module.handle_hide_solana_key, "exact")
        self.register("check_balance", module.handle_check_balance, "exact")
        self.register("check_approvals", module.handle_check_approvals, "exact")
        self.register("bridge_from_wallet", module.handle_bridge_from_wallet, "exact")

    def _register_setup_callbacks(self, module):
        """Register all setup/onboarding callbacks"""
        self.register("confirm_restart_", module.handle_confirm_restart, "prefix")
        self.register("cancel_restart", module.handle_cancel_restart, "exact")
        self.register("auto_approve", module.handle_auto_approve, "exact")
        self.register("generate_api", module.handle_generate_api, "exact")
        self.register("test_api_credentials", module.handle_test_api, "exact")
        self.register("start_streamlined_bridge", module.handle_start_streamlined_bridge, "exact")
        self.register("refresh_sol_balance_start", module.handle_refresh_sol_balance_start, "exact")
        self.register("refresh_start", module.handle_refresh_start, "exact")
        self.register("cancel_streamlined_bridge", module.handle_cancel_streamlined_bridge, "exact")

    def _register_smart_trading_callbacks(self, module):
        """Register smart trading callbacks"""
        # These are already registered in market_callbacks, no need to duplicate
        pass

    def _register_tpsl_callbacks(self, module):
        """Register take profit / stop loss callbacks"""
        self.register("set_tpsl:", module.set_tpsl_callback, "prefix")
        self.register("edit_tpsl_by_id:", module.edit_tpsl_by_id_callback, "prefix")
        self.register("edit_tpsl:", module.edit_tpsl_callback, "prefix")
        self.register("update_tp_preset:", module.update_tp_preset_callback, "prefix")
        self.register("update_sl_preset:", module.update_sl_preset_callback, "prefix")
        self.register("update_tp:", module.update_tp_callback, "prefix")
        self.register("update_sl:", module.update_sl_callback, "prefix")
        self.register("view_all_tpsl", module.view_all_tpsl_callback, "exact")
        self.register("cancel_tpsl:", module.cancel_tpsl_callback, "prefix")

    def _register_category_callbacks(self, module):
        """Register category browsing callbacks"""
        self.register("cat_", module.handle_category_menu_or_view, "prefix")
        self.register("catfilter_", module.handle_category_filter_callback, "prefix")


    def _register_copy_trading_callbacks(self, module):
        """Register copy trading callbacks"""
        self.register("switch_leader", module.handle_switch_leader, "exact")
        self.register("settings", module.handle_settings, "exact")
        self.register("history", module.handle_history, "exact")
        self.register("stop_following", module.handle_stop_following, "exact")
        self.register("modify_budget", module.handle_modify_budget, "exact")
        self.register("modify_mode", module.handle_modify_mode, "exact")
        self.register("mode_proportional", module.handle_mode_proportional, "exact")
        self.register("mode_fixed", module.handle_mode_fixed, "exact")
        self.register("back_to_dashboard", module.handle_back_to_dashboard, "exact")
        self.register("back_to_settings", module.handle_back_to_settings, "exact")
        self.register("confirm_leader_", module.handle_confirm_leader_inline, "prefix")
        self.register("cancel_leader_search", module.handle_cancel_leader_search, "exact")

    def _register_bridge_callbacks(self, module):
        """Register bridge-related callbacks"""
        self.register("fund_bridge_solana", module.handle_fund_bridge_solana, "exact")
        self.register("confirm_bridge_", module.handle_confirm_bridge, "prefix")
        self.register("cancel_bridge", module.handle_cancel_bridge, "exact")
        self.register("refresh_sol_balance", module.handle_refresh_sol_balance, "exact")
        self.register("bridge_auto_", module.handle_bridge_auto, "prefix")
        self.register("bridge_custom_amount", module.handle_bridge_custom_amount, "exact")
        self.register("copy_solana_address", module.handle_copy_solana_address, "exact")
        self.register("back_to_bridge_menu", module.handle_back_to_bridge_menu, "exact")


# Global registry instance
_registry = CallbackRegistry()


def get_registry() -> CallbackRegistry:
    """Get the global callback registry"""
    return _registry


def initialize_registry():
    """Initialize the callback registry"""
    _registry.initialize()
