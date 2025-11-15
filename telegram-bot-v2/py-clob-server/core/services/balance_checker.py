#!/usr/bin/env python3
"""
Balance Checker for Telegram Trading Bot V2
Helps users check their wallet balances for USDC.e and POL
"""

import logging
from typing import Dict, Tuple
from web3 import Web3

# Import config for RPC URL
from config.config import AUTO_APPROVAL_RPC_HTTP

logger = logging.getLogger(__name__)

class BalanceChecker:
    """Checks wallet balances for trading requirements

    PERFORMANCE: Uses Redis cache to avoid slow RPC calls (500ms → 5ms)
    """

    # Contract addresses
    USDC_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
    POLYGON_RPC = AUTO_APPROVAL_RPC_HTTP  # Use reliable Alchemy RPC from config

    # Cache TTL for balances (30 seconds - balances don't change frequently)
    BALANCE_CACHE_TTL = 30

    def __init__(self):
        """Initialize balance checker (Web3 connection is lazy)"""
        self._w3 = None  # Lazy initialization
        self._redis_cache = None  # Lazy Redis cache
        logger.info(f"🔧 BalanceChecker initialized (will connect to {self.POLYGON_RPC[:50]}... on first use)")

        # ERC20 balance ABI
        self.erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            }
        ]

    @property
    def w3(self):
        """Lazy Web3 connection - only created when actually needed"""
        if self._w3 is None:
            logger.info(f"🔗 Connecting to Polygon RPC: {self.POLYGON_RPC[:50]}...")
            self._w3 = Web3(Web3.HTTPProvider(self.POLYGON_RPC))
            logger.info(f"✅ Web3 connected: {self._w3.is_connected()}")
        return self._w3

    @property
    def redis_cache(self):
        """Lazy Redis cache - only created when actually needed"""
        if self._redis_cache is None:
            try:
                from core.services.redis_price_cache import get_redis_cache
                self._redis_cache = get_redis_cache()
                if self._redis_cache.enabled:
                    logger.info(f"✅ Balance cache enabled (TTL: {self.BALANCE_CACHE_TTL}s)")
            except Exception as e:
                logger.warning(f"⚠️ Redis cache unavailable for balances: {e}")
                self._redis_cache = None
        return self._redis_cache

    def check_pol_balance(self, wallet_address: str) -> Tuple[float, bool]:
        """Check POL (native token) balance

        PERFORMANCE: Cached in Redis (500ms RPC → 5ms cache hit)
        """
        # Try cache first
        if self.redis_cache and self.redis_cache.enabled:
            try:
                cache_key = f"balance:pol:{wallet_address.lower()}"
                cached = self.redis_cache.redis_client.get(cache_key)
                if cached:
                    balance_pol = float(cached)
                    sufficient = balance_pol >= 0.01
                    logger.debug(f"🚀 CACHE HIT: POL balance {wallet_address[:10]}... = {balance_pol:.4f}")
                    return balance_pol, sufficient
            except Exception as cache_err:
                logger.debug(f"Cache lookup failed (non-fatal): {cache_err}")

        # Cache miss - fetch from RPC
        try:
            balance_wei = self.w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
            balance_pol = self.w3.from_wei(balance_wei, 'ether')

            # Need at least 0.01 POL for gas fees (conservative estimate)
            sufficient = balance_pol >= 0.01

            # Cache the result
            if self.redis_cache and self.redis_cache.enabled:
                try:
                    cache_key = f"balance:pol:{wallet_address.lower()}"
                    self.redis_cache.redis_client.setex(cache_key, self.BALANCE_CACHE_TTL, str(balance_pol))
                    logger.debug(f"💾 Cached POL balance for {wallet_address[:10]}... (TTL: {self.BALANCE_CACHE_TTL}s)")
                except Exception as cache_err:
                    logger.debug(f"Cache write failed (non-fatal): {cache_err}")

            return float(balance_pol), sufficient

        except Exception as e:
            logger.error(f"Error checking POL balance: {e}")
            return 0.0, False

    def check_usdc_balance(self, wallet_address: str) -> Tuple[float, bool]:
        """Check USDC.e balance

        PERFORMANCE: Cached in Redis (500ms RPC → 5ms cache hit)
        """
        # Try cache first
        if self.redis_cache and self.redis_cache.enabled:
            try:
                cache_key = f"balance:usdc:{wallet_address.lower()}"
                cached = self.redis_cache.redis_client.get(cache_key)
                if cached:
                    balance_usdc = float(cached)
                    sufficient = balance_usdc >= 1.0
                    logger.debug(f"🚀 CACHE HIT: USDC balance {wallet_address[:10]}... = ${balance_usdc:.2f}")
                    return balance_usdc, sufficient
            except Exception as cache_err:
                logger.debug(f"Cache lookup failed (non-fatal): {cache_err}")

        # Cache miss - fetch from RPC
        try:
            usdc_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.USDC_TOKEN_ADDRESS),
                abi=self.erc20_abi
            )

            balance = usdc_contract.functions.balanceOf(
                Web3.to_checksum_address(wallet_address)
            ).call()

            # USDC.e has 6 decimals
            balance_usdc = balance / (10 ** 6)

            # Need at least $1 USDC.e for trading
            sufficient = balance_usdc >= 1.0

            # Cache the result
            if self.redis_cache and self.redis_cache.enabled:
                try:
                    cache_key = f"balance:usdc:{wallet_address.lower()}"
                    self.redis_cache.redis_client.setex(cache_key, self.BALANCE_CACHE_TTL, str(balance_usdc))
                    logger.debug(f"💾 Cached USDC balance for {wallet_address[:10]}... (TTL: {self.BALANCE_CACHE_TTL}s)")
                except Exception as cache_err:
                    logger.debug(f"Cache write failed (non-fatal): {cache_err}")

            return float(balance_usdc), sufficient

        except Exception as e:
            logger.error(f"Error checking USDC.e balance: {e}")
            return 0.0, False

    def check_all_balances(self, wallet_address: str) -> Dict:
        """Check all required balances"""
        try:
            pol_balance, pol_sufficient = self.check_pol_balance(wallet_address)
            usdc_balance, usdc_sufficient = self.check_usdc_balance(wallet_address)

            # Overall funding status
            fully_funded = pol_sufficient and usdc_sufficient

            return {
                'pol_balance': pol_balance,
                'pol_sufficient': pol_sufficient,
                'usdc_balance': usdc_balance,
                'usdc_sufficient': usdc_sufficient,
                'fully_funded': fully_funded,
                'wallet_address': wallet_address,
                'requirements': {
                    'min_pol': 0.01,
                    'min_usdc': 1.0
                }
            }

        except Exception as e:
            logger.error(f"Error checking balances: {e}")
            return {
                'error': str(e),
                'fully_funded': False,
                'wallet_address': wallet_address
            }

    def check_balance(self, wallet_address: str) -> Dict:
        """Check balance - compatibility method for handlers"""
        balances = self.check_all_balances(wallet_address)

        # Return format expected by handlers
        return {
            'usdc': balances.get('usdc_balance', 0),
            'pol': balances.get('pol_balance', 0)
        }

    def invalidate_balance_cache(self, wallet_address: str, balance_type: str = 'all') -> bool:
        """
        Invalidate cached balance after trades/transactions

        Args:
            wallet_address: Wallet address
            balance_type: 'pol', 'usdc', 'sol', or 'all'

        Returns:
            True if invalidated
        """
        if not self.redis_cache or not self.redis_cache.enabled:
            return False

        try:
            keys_to_delete = []
            addr_lower = wallet_address.lower()

            if balance_type == 'all':
                keys_to_delete = [
                    f"balance:pol:{addr_lower}",
                    f"balance:usdc:{addr_lower}",
                    f"balance:sol:{addr_lower}"
                ]
            else:
                keys_to_delete = [f"balance:{balance_type}:{addr_lower}"]

            deleted = self.redis_cache.redis_client.delete(*keys_to_delete)
            logger.debug(f"🗑️ Invalidated {deleted} balance cache(s) for {wallet_address[:10]}...")
            return True

        except Exception as e:
            logger.debug(f"Cache invalidation failed (non-fatal): {e}")
            return False

    def format_balance_report(self, wallet_address: str) -> str:
        """Format a nice balance report for users"""
        balances = self.check_all_balances(wallet_address)

        if 'error' in balances:
            return f"❌ **Balance Check Failed**\n\nError: {balances['error']}"

        pol_status = "✅" if balances['pol_sufficient'] else "❌"
        usdc_status = "✅" if balances['usdc_sufficient'] else "❌"

        report = f"""
💰 **WALLET BALANCE REPORT**

📍 **Wallet:** `{wallet_address[:10]}...{wallet_address[-4:]}`

🪙 **POL Balance:** {pol_status}
• Current: {balances['pol_balance']:.4f} POL
• Required: {balances['requirements']['min_pol']:.4f} POL (gas fees)
• Status: {"Sufficient" if balances['pol_sufficient'] else "Need more POL"}

💵 **USDC.e Balance:** {usdc_status}
• Current: ${balances['usdc_balance']:.2f} USDC.e
• Required: ${balances['requirements']['min_usdc']:.2f} USDC.e (trading)
• Status: {"Sufficient" if balances['usdc_sufficient'] else "Need more USDC.e"}

🎯 **Overall Status:** {"✅ Ready for trading!" if balances['fully_funded'] else "⚠️ Need funding"}
        """

        if not balances['fully_funded']:
            report += "\n💡 **Next Steps:**\n"
            if not balances['pol_sufficient']:
                needed_pol = balances['requirements']['min_pol'] - balances['pol_balance']
                report += f"• Send at least {needed_pol:.4f} POL for gas fees\n"
            if not balances['usdc_sufficient']:
                needed_usdc = balances['requirements']['min_usdc'] - balances['usdc_balance']
                report += f"• Send at least ${needed_usdc:.2f} USDC.e for trading\n"
                report += f"• ⚠️ **IMPORTANT**: Must be USDC.e, not regular USDC!\n"
                report += f"• Contract: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`\n"

        return report

# Global balance checker instance
balance_checker = BalanceChecker()
