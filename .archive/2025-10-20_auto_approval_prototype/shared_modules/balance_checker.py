#!/usr/bin/env python3
"""
Balance Checker for Telegram Trading Bot V2
Helps users check their wallet balances for USDC.e and POL
"""

import logging
from typing import Dict, Tuple
from web3 import Web3

logger = logging.getLogger(__name__)

class BalanceChecker:
    """Checks wallet balances for trading requirements"""
    
    # Contract addresses
    USDC_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
    POLYGON_RPC = "https://polygon-rpc.com"
    
    def __init__(self):
        """Initialize balance checker"""
        self.w3 = Web3(Web3.HTTPProvider(self.POLYGON_RPC))
        
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
    
    def check_pol_balance(self, wallet_address: str) -> Tuple[float, bool]:
        """Check POL (native token) balance"""
        try:
            balance_wei = self.w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
            balance_pol = self.w3.from_wei(balance_wei, 'ether')
            
            # Need at least 0.01 POL for gas fees (conservative estimate)
            sufficient = balance_pol >= 0.01
            
            return float(balance_pol), sufficient
            
        except Exception as e:
            logger.error(f"Error checking POL balance: {e}")
            return 0.0, False
    
    def check_usdc_balance(self, wallet_address: str) -> Tuple[float, bool]:
        """Check USDC.e balance"""
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
