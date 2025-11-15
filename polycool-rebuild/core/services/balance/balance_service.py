"""
Balance Service - USDC.e balance checking
Checks wallet balances for USDC.e on Polygon
"""
from typing import Dict, Tuple, Optional
from web3 import Web3
from infrastructure.logging.logger import get_logger
from infrastructure.config.settings import settings

logger = get_logger(__name__)

class BalanceService:
    """
    Balance Service - Checks USDC.e balances on Polygon
    """

    # USDC.e contract on Polygon
    USDC_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    POLYGON_RPC = settings.web3.polygon_rpc_url

    def __init__(self):
        self._w3 = None
        self._usdc_contract = None

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
        """Lazy Web3 connection"""
        if self._w3 is None:
            logger.info("🔗 Connecting to Polygon RPC for balance checking...")
            self._w3 = Web3(Web3.HTTPProvider(self.POLYGON_RPC))
            logger.info(f"✅ Web3 connected: {self._w3.is_connected()}")
        return self._w3

    @property
    def usdc_contract(self):
        """Lazy USDC.e contract"""
        if self._usdc_contract is None:
            self._usdc_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.USDC_TOKEN_ADDRESS),
                abi=self.erc20_abi
            )
        return self._usdc_contract

    async def get_usdc_balance(self, wallet_address: str) -> Optional[float]:
        """
        Get USDC.e balance for wallet

        Args:
            wallet_address: Polygon wallet address

        Returns:
            USDC.e balance in dollars or None if error
        """
        try:
            # Call balanceOf function
            balance = self.usdc_contract.functions.balanceOf(
                Web3.to_checksum_address(wallet_address)
            ).call()

            # USDC.e has 6 decimals
            balance_usdc = balance / (10 ** 6)

            logger.info(f"💵 USDC.e balance for {wallet_address[:10]}...: ${balance_usdc:.2f}")
            return float(balance_usdc)

        except Exception as e:
            logger.error(f"❌ Error checking USDC.e balance for {wallet_address}: {e}")
            return None

    async def get_pol_balance(self, wallet_address: str) -> Optional[float]:
        """
        Get POL (native token) balance

        Args:
            wallet_address: Polygon wallet address

        Returns:
            POL balance or None if error
        """
        try:
            balance_wei = self.w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
            balance_pol = self.w3.from_wei(balance_wei, 'ether')

            logger.info(f"🪙 POL balance for {wallet_address[:10]}...: {balance_pol:.4f} POL")
            return float(balance_pol)

        except Exception as e:
            logger.error(f"❌ Error checking POL balance for {wallet_address}: {e}")
            return None

    async def get_balances(self, wallet_address: str) -> Dict[str, float]:
        """
        Get all balances for wallet

        Args:
            wallet_address: Polygon wallet address

        Returns:
            Dictionary with usdc and pol balances
        """
        usdc_balance = await self.get_usdc_balance(wallet_address)
        pol_balance = await self.get_pol_balance(wallet_address)

        return {
            'usdc': usdc_balance or 0.0,
            'pol': pol_balance or 0.0
        }

    def format_balance_display(self, usdc_balance: float, pol_balance: float = None) -> str:
        """
        Format balance for display in UI

        Args:
            usdc_balance: USDC.e balance
            pol_balance: POL balance (optional)

        Returns:
            Formatted balance string
        """
        balance_str = f"💵 **${usdc_balance:.2f} USDC.e**"

        if pol_balance is not None:
            balance_str += f" | 🪙 **{pol_balance:.4f} POL**"

        return balance_str

# Global instance
balance_service = BalanceService()
