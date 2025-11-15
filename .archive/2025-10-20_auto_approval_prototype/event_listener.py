#!/usr/bin/env python3
"""
Event Listener for Auto-Approval Prototype
Real-time WebSocket monitoring for wallet funding events
"""

import asyncio
import json
import time
import logging
from typing import Dict, List, Callable, Optional
from web3 import Web3
# from web3.middleware import geth_poa_middleware  # Not needed for HTTP RPC
from colorama import Fore, Style
from config import (
    POLYGON_RPC_HTTP, POLYGON_RPC_WSS, USDC_TOKEN_ADDRESS, 
    MIN_USDC_BALANCE, MIN_POL_BALANCE, EVENT_CHECK_INTERVAL,
    MAX_RECONNECT_ATTEMPTS, RECONNECT_DELAY
)

logger = logging.getLogger(__name__)

class EventListener:
    """Monitors blockchain events for wallet funding detection"""
    
    def __init__(self, target_wallet: str):
        self.target_wallet = target_wallet.lower()
        self.is_running = False
        self.reconnect_attempts = 0
        self.funding_callback: Optional[Callable] = None
        
        # Initialize Web3 connections
        self.w3_http = Web3(Web3.HTTPProvider(POLYGON_RPC_HTTP))
        # self.w3_http.middleware_onion.inject(geth_poa_middleware, layer=0)  # Not needed
        
        # ERC20 Transfer event signature
        self.transfer_event_signature = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        
        print(f"{Fore.GREEN}🔗 Event listener initialized for wallet: {target_wallet}{Style.RESET_ALL}")
    
    def set_funding_callback(self, callback: Callable):
        """Set callback function to trigger when funding is detected"""
        self.funding_callback = callback
        print(f"{Fore.BLUE}📞 Funding callback registered{Style.RESET_ALL}")
    
    async def check_current_balances(self) -> Dict:
        """Check current balances using HTTP RPC"""
        try:
            # Check POL balance
            pol_balance_wei = self.w3_http.eth.get_balance(
                Web3.to_checksum_address(self.target_wallet)
            )
            pol_balance = self.w3_http.from_wei(pol_balance_wei, 'ether')
            pol_sufficient = pol_balance >= MIN_POL_BALANCE
            
            # Check USDC.e balance
            usdc_contract = self.w3_http.eth.contract(
                address=Web3.to_checksum_address(USDC_TOKEN_ADDRESS),
                abi=[{
                    "constant": True,
                    "inputs": [{"name": "account", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function"
                }]
            )
            
            usdc_balance_raw = usdc_contract.functions.balanceOf(
                Web3.to_checksum_address(self.target_wallet)
            ).call()
            usdc_balance = usdc_balance_raw / (10 ** 6)  # USDC.e has 6 decimals
            usdc_sufficient = usdc_balance >= MIN_USDC_BALANCE
            
            balances = {
                'pol_balance': float(pol_balance),
                'pol_sufficient': pol_sufficient,
                'usdc_balance': float(usdc_balance),
                'usdc_sufficient': usdc_sufficient,
                'fully_funded': pol_sufficient and usdc_sufficient,
                'timestamp': time.time()
            }
            
            return balances
            
        except Exception as e:
            logger.error(f"Error checking balances: {e}")
            return {'error': str(e), 'fully_funded': False, 'timestamp': time.time()}
    
    async def start_monitoring(self):
        """Start the event monitoring loop"""
        print(f"{Fore.YELLOW}🔍 Starting wallet funding monitor...{Style.RESET_ALL}")
        print(f"{Fore.CYAN}📡 Monitoring: {self.target_wallet}{Style.RESET_ALL}")
        
        self.is_running = True
        last_balances = await self.check_current_balances()
        
        # Display initial status
        if 'error' not in last_balances:
            print(f"\n{Fore.WHITE}💰 Initial Balance Status:{Style.RESET_ALL}")
            print(f"   POL: {last_balances['pol_balance']:.4f} ({'✅' if last_balances['pol_sufficient'] else '❌'})")
            print(f"   USDC.e: ${last_balances['usdc_balance']:.2f} ({'✅' if last_balances['usdc_sufficient'] else '❌'})")
            
            if last_balances['fully_funded']:
                print(f"\n{Fore.GREEN}✅ Wallet already funded! Triggering auto-approval...{Style.RESET_ALL}")
                if self.funding_callback:
                    await self.funding_callback(last_balances)
                return
            else:
                print(f"\n{Fore.YELLOW}⏳ Waiting for funding... (checking every {EVENT_CHECK_INTERVAL}s){Style.RESET_ALL}")
        
        # Main monitoring loop
        while self.is_running:
            try:
                await asyncio.sleep(EVENT_CHECK_INTERVAL)
                
                # Check current balances
                current_balances = await self.check_current_balances()
                
                if 'error' in current_balances:
                    print(f"{Fore.RED}❌ Error checking balances: {current_balances['error']}{Style.RESET_ALL}")
                    continue
                
                # Check if funding status changed
                if current_balances['fully_funded'] and not last_balances.get('fully_funded', False):
                    print(f"\n{Fore.GREEN}🎉 FUNDING DETECTED!{Style.RESET_ALL}")
                    print(f"{Fore.GREEN}   POL: {current_balances['pol_balance']:.4f} ✅{Style.RESET_ALL}")
                    print(f"{Fore.GREEN}   USDC.e: ${current_balances['usdc_balance']:.2f} ✅{Style.RESET_ALL}")
                    
                    # Trigger auto-approval
                    if self.funding_callback:
                        print(f"{Fore.YELLOW}🚀 Triggering auto-approval process...{Style.RESET_ALL}")
                        await self.funding_callback(current_balances)
                    
                    break
                
                # Check for partial funding updates
                elif (current_balances['pol_balance'] != last_balances.get('pol_balance', 0) or 
                      current_balances['usdc_balance'] != last_balances.get('usdc_balance', 0)):
                    print(f"{Fore.BLUE}🔄 Balance update detected:{Style.RESET_ALL}")
                    print(f"   POL: {current_balances['pol_balance']:.4f} ({'✅' if current_balances['pol_sufficient'] else '❌'})")
                    print(f"   USDC.e: ${current_balances['usdc_balance']:.2f} ({'✅' if current_balances['usdc_sufficient'] else '❌'})")
                
                last_balances = current_balances
                
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}🛑 Monitoring stopped by user{Style.RESET_ALL}")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                print(f"{Fore.RED}❌ Monitoring error: {e}{Style.RESET_ALL}")
                await asyncio.sleep(RECONNECT_DELAY)
        
        self.is_running = False
        print(f"{Fore.BLUE}📡 Event monitoring stopped{Style.RESET_ALL}")
    
    def stop_monitoring(self):
        """Stop the event monitoring"""
        self.is_running = False

# Global instance will be created in main
event_listener: Optional[EventListener] = None
