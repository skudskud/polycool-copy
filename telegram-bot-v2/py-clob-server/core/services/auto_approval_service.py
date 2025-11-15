#!/usr/bin/env python3
"""
Auto-Approval Service for Telegram Trading Bot V2
Event-driven wallet monitoring and automatic approval + API generation
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Tuple
from web3 import Web3

# Import new unified service
from .user_service import user_service
from .approval_manager import approval_manager
from .balance_checker import balance_checker

# Import configuration
from config.config import (
    AUTO_APPROVAL_ENABLED,
    AUTO_API_GENERATION_ENABLED,
    AUTO_APPROVAL_RPC_HTTP,
    MIN_POL_BALANCE_FOR_APPROVAL,
    MIN_USDC_BALANCE_FOR_APPROVAL,
    MAX_AUTO_APPROVAL_ATTEMPTS
)

logger = logging.getLogger(__name__)

class AutoApprovalService:
    """Manages automatic wallet monitoring and approval process"""
    
    def __init__(self):
        self.is_running = False
        
        logger.info(f"🚀 AutoApprovalService initializing...")
        logger.info(f"🔧 RPC will be used by balance_checker: {AUTO_APPROVAL_RPC_HTTP[:60]}...")
        logger.info("✅ Auto-approval service initialized")
    
    async def monitor_unfunded_wallets(self):
        """Main monitoring function - checks unfunded wallets for funding"""
        logger.info("🔍 [AUTO-APPROVAL] monitor_unfunded_wallets() called")
        
        if not AUTO_APPROVAL_ENABLED:
            logger.debug("Auto-approval disabled, skipping wallet monitoring")
            return
        
        logger.info(f"🔍 [AUTO-APPROVAL] AUTO_APPROVAL_ENABLED = {AUTO_APPROVAL_ENABLED}")
        
        try:
            # Get all wallets that need monitoring
            wallets_to_check = self._get_wallets_to_monitor()
            
            if not wallets_to_check:
                logger.debug("No wallets need monitoring")
                return
            
            logger.info(f"Monitoring {len(wallets_to_check)} wallets for funding")
            
            # Check each wallet for funding
            for user_id, wallet_data in wallets_to_check.items():
                try:
                    await self._check_wallet_funding(user_id, wallet_data)
                except Exception as e:
                    logger.error(f"Error checking wallet for user {user_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in wallet monitoring: {e}")
    
    def _get_wallets_to_monitor(self) -> Dict[int, Dict]:
        """Get wallets that need funding monitoring"""
        wallets_to_check = {}
        
        try:
            # Get all unfunded users from PostgreSQL
            from database import db_manager, User
            
            with db_manager.get_session() as db:
                # Query unfunded users that need auto-approval
                unfunded_users = db.query(User).filter(
                    User.funded == False,
                    User.auto_approval_completed == False
                ).all()
                
                for user in unfunded_users:
                    # Convert to dict format for compatibility
                    wallet_data = {
                        'address': user.polygon_address,
                        'private_key': user.polygon_private_key,
                        'username': user.username,
                        'funded': user.funded,
                        'usdc_approved': user.usdc_approved,
                        'pol_approved': user.pol_approved,
                        'polymarket_approved': user.polymarket_approved,
                        'auto_approval_completed': user.auto_approval_completed
                    }
                    wallets_to_check[user.telegram_user_id] = wallet_data
            
            return wallets_to_check
            
        except Exception as e:
            logger.error(f"Error getting wallets to monitor: {e}")
            return {}
    
    async def _check_wallet_funding(self, user_id: int, wallet_data: Dict):
        """Check if a specific wallet is funded and trigger auto-approval"""
        try:
            wallet_address = wallet_data.get('address')
            if not wallet_address:
                return
            
            # Check current balances
            balances = balance_checker.check_all_balances(wallet_address)
            
            if balances.get('error'):
                logger.warning(f"Balance check failed for user {user_id}: {balances['error']}")
                return
            
            # Check if wallet meets funding requirements
            pol_sufficient = balances.get('pol_balance', 0) >= MIN_POL_BALANCE_FOR_APPROVAL
            usdc_sufficient = balances.get('usdc_balance', 0) >= MIN_USDC_BALANCE_FOR_APPROVAL
            
            # For now, we only require POL (USDC requirement is 0)
            is_funded = pol_sufficient and usdc_sufficient
            
            if is_funded:
                logger.info(f"🎉 Funding detected for user {user_id}! POL: {balances['pol_balance']:.4f}, USDC.e: ${balances['usdc_balance']:.2f}")
                
                # Update funding status
                user_service.update_funding_status(user_id, True)
                
                # Trigger auto-approval process
                await self._process_funded_wallet(user_id, wallet_data, balances)
            
        except Exception as e:
            logger.error(f"Error checking funding for user {user_id}: {e}")
    
    async def _process_funded_wallet(self, user_id: int, wallet_data: Dict, balance_info: Dict):
        """Process a newly funded wallet - run approvals and API generation"""
        try:
            # Mark as in progress to prevent duplicate processing
            self._update_auto_approval_status(user_id, in_progress=True, last_attempt=time.time())
            
            # PHASE 4: Enhanced funding detection notification
            from .notification_service import notification_service
            await notification_service.send_message(
                user_id,
                f"🎉 **FUNDING DETECTED!**\n\n"
                f"💰 Balance confirmed:\n"
                f"• USDC.e: {balance_info.get('usdc', 0):.2f}\n"
                f"• POL: {balance_info.get('pol', 0):.2f}\n\n"
                f"⚡ **Starting automatic setup:**\n"
                f"1. Approve contracts (~30-60s)\n"
                f"2. Generate API keys (~15-30s)\n\n"
                f"⏱️ **Total time: ~1-2 minutes**"
            )
            
            # Step 1: Contract Approvals
            logger.info(f"Starting auto-approval for user {user_id}")
            
            # PHASE 4: Send approval start notification
            await notification_service.send_approval_started(user_id)
            
            approval_success = await self._run_contract_approvals(user_id, wallet_data)
            
            if not approval_success:
                # Mark as failed and send notification
                self._update_auto_approval_status(user_id, in_progress=False, failure_count=wallet_data.get('auto_approval_failure_count', 0) + 1)
                await notification_service.send_error_notification(
                    user_id,
                    "Contract Approval",
                    "Contract approvals were not successful. You can try manual approval with /autoapprove"
                )
                return
            
            # PHASE 4: Send approval complete notification
            await notification_service.send_approval_complete(user_id)
            
            # Step 2: API Key Generation (if enabled)
            api_success = True
            if AUTO_API_GENERATION_ENABLED:
                logger.info(f"Starting API generation for user {user_id}")
                
                # PHASE 4: Send API generation start notification
                await notification_service.send_api_generation_started(user_id)
                
                api_success = await self._run_api_generation(user_id, wallet_data)
            
            # Mark as completed
            self._update_auto_approval_status(
                user_id, 
                in_progress=False, 
                completed=True,
                api_generated=api_success
            )
            
            # PHASE 4: Send final success notification
            if api_success:
                await notification_service.send_setup_complete(user_id)
            else:
                await notification_service.send_message(
                    user_id,
                    "🎉 **AUTO-APPROVAL COMPLETE!**\n\n✅ Contracts approved\n⚠️ API generation failed (you can try /generateapi manually)\n\n🚀 Your wallet is ready for trading!"
                )
            
            logger.info(f"Auto-approval completed successfully for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error processing funded wallet for user {user_id}: {e}")
            
            # Mark as failed
            self._update_auto_approval_status(user_id, in_progress=False, failure_count=wallet_data.get('auto_approval_failure_count', 0) + 1)
            
            # Send error notification
            await self._send_telegram_notification(
                user_id,
                f"❌ **Auto-setup failed!**\n\nError: {str(e)}\n\nYou can try manual setup with /autoapprove and /generateapi"
            )
    
    async def _run_contract_approvals(self, user_id: int, wallet_data: Dict) -> bool:
        """Run contract approvals for a user"""
        try:
            # Send progress notification
            await self._send_telegram_notification(
                user_id,
                "⚡ **Approving contracts...** (1/2)\n\nApproving USDC.e and Conditional Token contracts for Polymarket trading..."
            )
            
            private_key = wallet_data.get('private_key')
            if not private_key:
                logger.error(f"No private key found for user {user_id}")
                return False
            
            # Run approvals using existing approval manager
            success, results = await asyncio.get_event_loop().run_in_executor(
                None, approval_manager.approve_all_for_trading, private_key
            )
            
            if success:
                # Update wallet approval status
                user_service.update_approval_status(
                    user_id,
                    usdc_approved=True,
                    pol_approved=True,  # Both should be approved together
                    polymarket_approved=True,
                    auto_approval_completed=True
                )
                logger.info(f"Contract approvals successful for user {user_id}")
                return True
            else:
                logger.error(f"Contract approvals failed for user {user_id}: {results}")
                return False
                
        except Exception as e:
            logger.error(f"Error running contract approvals for user {user_id}: {e}")
            return False
    
    async def _run_api_generation(self, user_id: int, wallet_data: Dict) -> bool:
        """Run API key generation for a user"""
        try:
            # Send progress notification
            await self._send_telegram_notification(
                user_id,
                "🔑 **Generating API keys...** (2/2)\n\nCreating your personal API credentials for enhanced trading rates..."
            )
            
            private_key = wallet_data.get('private_key')
            wallet_address = wallet_data.get('address')
            
            if not private_key or not wallet_address:
                logger.error(f"Missing wallet data for user {user_id}")
                return False
            
            # Generate API credentials
            from .api_key_manager import api_key_manager
            creds = await asyncio.get_event_loop().run_in_executor(
                None, api_key_manager.generate_api_credentials, user_id, private_key, wallet_address
            )
            
            if creds:
                # Save API credentials to PostgreSQL
                user_service.save_api_credentials(
                    telegram_user_id=user_id,
                    api_key=creds['api_key'],
                    api_secret=creds['api_secret'],
                    api_passphrase=creds['api_passphrase']
                )
                logger.info(f"API generation successful for user {user_id}")
                return True
            else:
                logger.error(f"API generation failed for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error running API generation for user {user_id}: {e}")
            return False
    
    def _update_auto_approval_status(self, user_id: int, **kwargs):
        """Update auto-approval status fields in PostgreSQL"""
        try:
            # Map kwargs to user_service updates
            if 'completed' in kwargs:
                user_service.update_approval_status(user_id, auto_approval_completed=kwargs['completed'])
            
            # Note: in_progress, last_attempt, failure_count fields removed from schema
            # These were transient state - not critical for persistence
                
        except Exception as e:
            logger.error(f"Error updating auto-approval status for user {user_id}: {e}")
    
    async def _send_telegram_notification(self, user_id: int, message: str):
        """Send Telegram notification to user - PHASE 4: Using notification service"""
        try:
            from .notification_service import notification_service
            await notification_service.send_message(user_id, message)
        except Exception as e:
            logger.error(f"Error sending notification to user {user_id}: {e}")

# Global auto-approval service instance
auto_approval_service = AutoApprovalService()
