#!/usr/bin/env python3
"""
Auto-Approval Prototype Main Script
Tests event-driven wallet funding detection and auto-approval
"""

import asyncio
import logging
import signal
import sys
import os
from colorama import init, Fore, Style

# Initialize colorama
init()

# Import our prototype modules
from wallet_generator import wallet_generator
from event_listener import EventListener
from auto_approval_engine import AutoApprovalEngine
from config import LOG_LEVEL, ENABLE_DEBUG_LOGS

# Set up logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PrototypeRunner:
    """Main prototype runner"""
    
    def __init__(self):
        self.event_listener = None
        self.auto_approval_engine = None
        self.wallet_address = None
        self.private_key = None
        self.is_running = False
    
    async def funding_detected_callback(self, balance_info: dict):
        """Callback triggered when wallet funding is detected"""
        print(f"\n{Fore.GREEN}🎉 FUNDING CALLBACK TRIGGERED!{Style.RESET_ALL}")
        
        if self.auto_approval_engine:
            try:
                # Run the complete auto-approval flow
                results = await self.auto_approval_engine.run_complete_setup(balance_info)
                
                if results['success']:
                    print(f"\n{Fore.GREEN}🎊 PROTOTYPE TEST SUCCESSFUL!{Style.RESET_ALL}")
                    print(f"{Fore.GREEN}Total time from funding to ready: {results['total_time']:.2f} seconds{Style.RESET_ALL}")
                else:
                    print(f"\n{Fore.RED}❌ PROTOTYPE TEST FAILED{Style.RESET_ALL}")
                    if 'error' in results:
                        print(f"{Fore.RED}Error: {results['error']}{Style.RESET_ALL}")
                
                # Stop monitoring after completion
                if self.event_listener:
                    self.event_listener.stop_monitoring()
                
                self.is_running = False
                
            except Exception as e:
                logger.error(f"Error in funding callback: {e}")
                print(f"{Fore.RED}❌ Callback error: {e}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}❌ Auto-approval engine not initialized{Style.RESET_ALL}")
    
    async def initialize_prototype(self):
        """Initialize the prototype components"""
        print(f"{Fore.YELLOW}🚀 INITIALIZING AUTO-APPROVAL PROTOTYPE{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
        
        try:
            # Step 1: Generate or load test wallet
            self.wallet_address, self.private_key = wallet_generator.get_or_create_wallet()
            
            # Step 2: Initialize auto-approval engine
            self.auto_approval_engine = AutoApprovalEngine(
                self.wallet_address, 
                self.private_key
            )
            
            # Step 3: Initialize event listener
            self.event_listener = EventListener(self.wallet_address)
            self.event_listener.set_funding_callback(self.funding_detected_callback)
            
            print(f"{Fore.GREEN}✅ Prototype initialized successfully!{Style.RESET_ALL}")
            return True
            
        except Exception as e:
            logger.error(f"Prototype initialization error: {e}")
            print(f"{Fore.RED}❌ Initialization failed: {e}{Style.RESET_ALL}")
            return False
    
    async def run_prototype(self):
        """Run the complete prototype test"""
        print(f"\n{Fore.CYAN}🧪 STARTING PROTOTYPE TEST{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'='*40}{Style.RESET_ALL}")
        
        # Display funding instructions
        wallet_generator.display_funding_instructions(self.wallet_address)
        
        # Start event monitoring
        self.is_running = True
        
        try:
            await self.event_listener.start_monitoring()
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}🛑 Prototype stopped by user{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"Prototype runtime error: {e}")
            print(f"{Fore.RED}❌ Runtime error: {e}{Style.RESET_ALL}")
        finally:
            self.is_running = False
    
    def cleanup(self):
        """Cleanup prototype resources"""
        if self.event_listener:
            self.event_listener.stop_monitoring()
        print(f"{Fore.BLUE}🧹 Prototype cleanup completed{Style.RESET_ALL}")

async def main():
    """Main entry point"""
    print(f"{Fore.MAGENTA}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}🔬 AUTO-APPROVAL PROTOTYPE - EVENT-DRIVEN TESTING{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}This prototype tests real-time wallet funding detection{Style.RESET_ALL}")
    print(f"{Fore.WHITE}and automatic approval + API generation on Polygon mainnet.{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}{'='*80}{Style.RESET_ALL}")
    
    runner = PrototypeRunner()
    
    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        print(f"\n{Fore.YELLOW}🛑 Received interrupt signal{Style.RESET_ALL}")
        runner.cleanup()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Initialize and run prototype
        if await runner.initialize_prototype():
            await runner.run_prototype()
        else:
            print(f"{Fore.RED}❌ Failed to initialize prototype{Style.RESET_ALL}")
            return 1
            
    except Exception as e:
        logger.error(f"Main prototype error: {e}")
        print(f"{Fore.RED}❌ Prototype failed: {e}{Style.RESET_ALL}")
        return 1
    finally:
        runner.cleanup()
    
    print(f"\n{Fore.BLUE}👋 Prototype testing completed{Style.RESET_ALL}")
    return 0

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}🛑 Prototype interrupted{Style.RESET_ALL}")
        sys.exit(0)
