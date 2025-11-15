#!/usr/bin/env python3
"""
Auto-Approval Engine for Prototype
Orchestrates the complete auto-approval and API generation flow
"""

import asyncio
import time
import logging
import sys
import os
from typing import Dict, Tuple
from colorama import Fore, Style

# Add shared modules to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'shared_modules'))

from approval_manager import ApprovalManager
from api_key_manager import ApiKeyManager

logger = logging.getLogger(__name__)

class AutoApprovalEngine:
    """Orchestrates the complete auto-approval flow"""
    
    def __init__(self, wallet_address: str, private_key: str):
        self.wallet_address = wallet_address
        self.private_key = private_key
        self.approval_manager = ApprovalManager()
        self.api_key_manager = ApiKeyManager()
        
        # Performance tracking
        self.start_time = None
        self.approval_start_time = None
        self.api_generation_start_time = None
        self.completion_time = None
        
        print(f"{Fore.GREEN}⚙️  Auto-approval engine initialized{Style.RESET_ALL}")
    
    async def run_complete_setup(self, balance_info: Dict) -> Dict:
        """Run the complete auto-approval and API generation flow"""
        print(f"\n{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}🚀 STARTING AUTO-APPROVAL FLOW{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
        
        self.start_time = time.time()
        results = {
            'success': False,
            'approval_success': False,
            'api_generation_success': False,
            'total_time': 0,
            'approval_time': 0,
            'api_generation_time': 0,
            'balance_info': balance_info
        }
        
        try:
            # Step 1: Contract Approvals
            print(f"\n{Fore.CYAN}⚡ Step 1/2: Approving contracts...{Style.RESET_ALL}")
            approval_success, approval_results = await self.run_approvals()
            
            results['approval_success'] = approval_success
            results['approval_results'] = approval_results
            results['approval_time'] = time.time() - self.approval_start_time
            
            if not approval_success:
                print(f"{Fore.RED}❌ Approval failed - stopping flow{Style.RESET_ALL}")
                return results
            
            # Step 2: API Key Generation
            print(f"\n{Fore.CYAN}🔑 Step 2/2: Generating API keys...{Style.RESET_ALL}")
            api_success, api_results = await self.run_api_generation()
            
            results['api_generation_success'] = api_success
            results['api_results'] = api_results
            results['api_generation_time'] = time.time() - self.api_generation_start_time
            
            # Calculate total time
            self.completion_time = time.time()
            results['total_time'] = self.completion_time - self.start_time
            results['success'] = approval_success and api_success
            
            # Display final results
            await self.display_final_results(results)
            
            return results
            
        except Exception as e:
            logger.error(f"Auto-approval flow error: {e}")
            print(f"{Fore.RED}❌ Fatal error in auto-approval flow: {e}{Style.RESET_ALL}")
            results['error'] = str(e)
            return results
    
    async def run_approvals(self) -> Tuple[bool, Dict]:
        """Run the contract approval process"""
        self.approval_start_time = time.time()
        
        try:
            print(f"{Fore.BLUE}   🔄 Approving USDC.e and Conditional Token contracts...{Style.RESET_ALL}")
            print(f"{Fore.BLUE}   📋 Contracts to approve: {len(self.approval_manager.EXCHANGE_CONTRACTS)}{Style.RESET_ALL}")
            
            # This runs synchronously but we'll make it async-compatible
            success, results = await asyncio.get_event_loop().run_in_executor(
                None, self.approval_manager.approve_all_for_trading, self.private_key
            )
            
            if success:
                print(f"{Fore.GREEN}   ✅ All contracts approved successfully!{Style.RESET_ALL}")
                print(f"{Fore.GREEN}   📝 USDC.e approvals: ✅{Style.RESET_ALL}")
                print(f"{Fore.GREEN}   📝 Conditional Token approvals: ✅{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}   ❌ Approval failed: {results.get('error', 'Unknown error')}{Style.RESET_ALL}")
            
            return success, results
            
        except Exception as e:
            logger.error(f"Approval process error: {e}")
            print(f"{Fore.RED}   ❌ Approval error: {e}{Style.RESET_ALL}")
            return False, {'error': str(e)}
    
    async def run_api_generation(self) -> Tuple[bool, Dict]:
        """Run the API key generation process"""
        self.api_generation_start_time = time.time()
        
        try:
            print(f"{Fore.BLUE}   🔄 Generating API credentials...{Style.RESET_ALL}")
            
            # Generate API credentials (also make async-compatible)
            creds = await asyncio.get_event_loop().run_in_executor(
                None, self.api_key_manager.generate_api_credentials, 
                999999, self.private_key, self.wallet_address  # Use dummy user_id for testing
            )
            
            if creds:
                print(f"{Fore.GREEN}   ✅ API credentials generated successfully!{Style.RESET_ALL}")
                print(f"{Fore.GREEN}   🔑 API Key: {creds.api_key[:20]}...{Style.RESET_ALL}")
                
                # Test the credentials
                print(f"{Fore.BLUE}   🧪 Testing API credentials...{Style.RESET_ALL}")
                test_success, test_msg = await asyncio.get_event_loop().run_in_executor(
                    None, self.api_key_manager.test_api_credentials,
                    999999, self.private_key, self.wallet_address
                )
                
                if test_success:
                    print(f"{Fore.GREEN}   ✅ API credentials test successful!{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}   ⚠️  API credentials test failed: {test_msg}{Style.RESET_ALL}")
                
                return True, {
                    'api_key': creds.api_key,
                    'test_success': test_success,
                    'test_message': test_msg
                }
            else:
                print(f"{Fore.RED}   ❌ API generation failed{Style.RESET_ALL}")
                return False, {'error': 'API generation returned None'}
                
        except Exception as e:
            logger.error(f"API generation error: {e}")
            print(f"{Fore.RED}   ❌ API generation error: {e}{Style.RESET_ALL}")
            return False, {'error': str(e)}
    
    async def display_final_results(self, results: Dict):
        """Display comprehensive final results"""
        print(f"\n{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}📊 FINAL RESULTS{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
        
        # Overall status
        if results['success']:
            print(f"{Fore.GREEN}🎉 AUTO-APPROVAL COMPLETED SUCCESSFULLY!{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}❌ AUTO-APPROVAL FAILED{Style.RESET_ALL}")
        
        # Timing information
        print(f"\n{Fore.WHITE}⏱️  Performance Metrics:{Style.RESET_ALL}")
        print(f"   Approval Time: {results['approval_time']:.2f} seconds")
        print(f"   API Generation Time: {results['api_generation_time']:.2f} seconds")
        print(f"   Total Process Time: {results['total_time']:.2f} seconds")
        
        # Balance information
        balance_info = results['balance_info']
        print(f"\n{Fore.WHITE}💰 Final Wallet Status:{Style.RESET_ALL}")
        print(f"   POL Balance: {balance_info['pol_balance']:.4f} ({'✅' if balance_info['pol_sufficient'] else '❌'})")
        print(f"   USDC.e Balance: ${balance_info['usdc_balance']:.2f} ({'✅' if balance_info['usdc_sufficient'] else '❌'})")
        
        # Component status
        print(f"\n{Fore.WHITE}🔧 Component Status:{Style.RESET_ALL}")
        print(f"   Contract Approvals: {'✅' if results['approval_success'] else '❌'}")
        print(f"   API Key Generation: {'✅' if results['api_generation_success'] else '❌'}")
        
        if results['success']:
            print(f"\n{Fore.GREEN}🚀 Wallet is now ready for trading!{Style.RESET_ALL}")
            if 'api_results' in results and results['api_results'].get('api_key'):
                print(f"{Fore.GREEN}🔑 API Key: {results['api_results']['api_key'][:20]}...{Style.RESET_ALL}")
        
        print(f"{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
        
        # Save results to file
        await self.save_test_results(results)
    
    async def save_test_results(self, results: Dict):
        """Save test results to file"""
        try:
            import json
            
            # Prepare results for JSON serialization
            json_results = {
                'timestamp': time.time(),
                'wallet_address': self.wallet_address,
                'success': results['success'],
                'total_time': results['total_time'],
                'approval_time': results['approval_time'],
                'api_generation_time': results['api_generation_time'],
                'balance_info': results['balance_info'],
                'approval_success': results['approval_success'],
                'api_generation_success': results['api_generation_success']
            }
            
            # Save to test results
            os.makedirs('test_results', exist_ok=True)
            with open('test_results/latest_test.json', 'w') as f:
                json.dump(json_results, f, indent=2)
            
            print(f"{Fore.BLUE}💾 Test results saved to test_results/latest_test.json{Style.RESET_ALL}")
            
        except Exception as e:
            logger.error(f"Error saving test results: {e}")

# Global instance will be created in main
auto_approval_engine = None
