#!/usr/bin/env python3
"""
Wallet Generator for Auto-Approval Prototype
Generates test wallets for funding detection testing
"""

import json
import os
import time
from typing import Tuple
from eth_account import Account
from colorama import init, Fore, Style

# Initialize colorama for colored output
init()

class WalletGenerator:
    """Generates and manages test wallets"""
    
    def __init__(self, storage_file: str = "test_wallet.json"):
        self.storage_file = storage_file
        # Enable unaudited HD wallet features
        Account.enable_unaudited_hdwallet_features()
    
    def generate_test_wallet(self) -> Tuple[str, str]:
        """Generate a new test wallet"""
        print(f"{Fore.YELLOW}🔑 Generating new test wallet...{Style.RESET_ALL}")
        
        # Generate new account
        account = Account.create()
        address = account.address
        private_key = account.key.hex()
        
        # Store wallet data
        wallet_data = {
            'address': address,
            'private_key': private_key,
            'created_at': time.time(),
            'funded': False,
            'test_purpose': 'auto_approval_prototype'
        }
        
        # Save to file
        with open(self.storage_file, 'w') as f:
            json.dump(wallet_data, f, indent=2)
        
        print(f"{Fore.GREEN}✅ Test wallet generated successfully!{Style.RESET_ALL}")
        print(f"{Fore.CYAN}📍 Address: {address}{Style.RESET_ALL}")
        
        return address, private_key
    
    def load_existing_wallet(self) -> Tuple[str, str]:
        """Load existing test wallet if it exists"""
        if os.path.exists(self.storage_file):
            with open(self.storage_file, 'r') as f:
                wallet_data = json.load(f)
            return wallet_data['address'], wallet_data['private_key']
        return None, None
    
    def get_or_create_wallet(self) -> Tuple[str, str]:
        """Get existing wallet or create new one"""
        address, private_key = self.load_existing_wallet()
        
        if address and private_key:
            print(f"{Fore.BLUE}🔄 Using existing test wallet...{Style.RESET_ALL}")
            print(f"{Fore.CYAN}📍 Address: {address}{Style.RESET_ALL}")
            return address, private_key
        else:
            return self.generate_test_wallet()
    
    def display_funding_instructions(self, address: str):
        """Display clear funding instructions"""
        print(f"\n{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}💰 FUNDING INSTRUCTIONS{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
        
        print(f"\n{Fore.WHITE}📍 Wallet Address:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{address}{Style.RESET_ALL}")
        
        print(f"\n{Fore.WHITE}🪙 Required Tokens:{Style.RESET_ALL}")
        print(f"{Fore.GREEN}1. USDC.e (Trading Currency):{Style.RESET_ALL}")
        print(f"   • Contract: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        print(f"   • Minimum: $1 USDC.e")
        print(f"   • Network: Polygon (MATIC)")
        
        print(f"\n{Fore.GREEN}2. POL (Gas Token):{Style.RESET_ALL}")
        print(f"   • Native Polygon token")
        print(f"   • Minimum: 0.01 POL")
        print(f"   • Network: Polygon (MATIC)")
        
        print(f"\n{Fore.RED}⚠️  IMPORTANT:{Style.RESET_ALL}")
        print(f"   • Use Polygon network (Chain ID: 137)")
        print(f"   • Double-check address before sending")
        print(f"   • Start with small test amounts")
        
        print(f"\n{Fore.YELLOW}🚀 Once funded, the auto-approval will trigger automatically!{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")

# Global instance
wallet_generator = WalletGenerator()
