"""
Unified User Service - PostgreSQL Version with Enhanced State Management
Manages ALL user data: Polygon wallet, Solana wallet, API credentials
Replaces: wallet_manager.py, api_key_manager.py, solana_wallet_manager_v2.py

Enhanced for streamlined onboarding flow with automatic SOL wallet generation
"""

import logging
from typing import Dict, Optional, Tuple, List
from eth_account import Account
from solders.keypair import Keypair
import base58
from datetime import datetime

from database import db_manager, User
from .user_states import UserStage, UserStateValidator, UserProgressTracker

logger = logging.getLogger(__name__)

# Enable HD wallet features for Ethereum wallet generation
Account.enable_unaudited_hdwallet_features()


class UserService:
    """
    Unified service for ALL user operations
    Single source of truth: users table in PostgreSQL
    """
    
    def __init__(self):
        logger.info("🔧 UserService initialized (PostgreSQL-backed)")
    
    # ========================================================================
    # User Management
    # ========================================================================
    
    def get_user(self, telegram_user_id: int) -> Optional[User]:
        """Get user by Telegram ID"""
        try:
            return db_manager.get_user(telegram_user_id)
        except Exception as e:
            logger.error(f"❌ Error getting user {telegram_user_id}: {e}")
            return None
    
    def user_exists(self, telegram_user_id: int) -> bool:
        """Check if user exists"""
        return self.get_user(telegram_user_id) is not None
    
    def create_user(self, telegram_user_id: int, username: str = None) -> Optional[User]:
        """
        Create new user with BOTH Polygon and Solana wallets (ENHANCED for streamlined flow)
        
        This replaces the old two-step process:
        1. Creates Polygon wallet immediately
        2. Creates Solana wallet immediately (no separate call needed)
        3. User is ready for funding step
        
        Returns user at SOL_GENERATED stage, ready for funding
        """
        try:
            # Check if user already exists
            existing = self.get_user(telegram_user_id)
            if existing:
                current_stage = UserStateValidator.get_user_stage(existing)
                logger.info(f"ℹ️ User {telegram_user_id} already exists at stage {current_stage.display_name}")
                return existing
            
            logger.info(f"🔧 Creating new user {telegram_user_id} with both Polygon + SOL wallets...")
            
            # Generate Polygon wallet
            polygon_address, polygon_private_key = self._generate_polygon_wallet()
            
            # Generate Solana wallet (NEW - automatic generation)
            solana_keypair = Keypair()
            solana_address = str(solana_keypair.pubkey())
            solana_private_key = base58.b58encode(bytes(solana_keypair)).decode('ascii')
            
            # Create user in database with BOTH wallets
            user = db_manager.create_user(
                telegram_user_id=telegram_user_id,
                username=username,
                polygon_address=polygon_address,
                polygon_private_key=polygon_private_key
            )
            
            # Immediately add Solana wallet
            success = db_manager.update_user_solana_wallet(
                telegram_user_id=telegram_user_id,
                solana_address=solana_address,
                solana_private_key=solana_private_key
            )
            
            if not success:
                logger.error(f"❌ Failed to add Solana wallet for user {telegram_user_id}")
                return None
            
            # Get updated user object
            user = self.get_user(telegram_user_id)
            
            # Log progression
            stage = UserStateValidator.get_user_stage(user)
            UserProgressTracker.log_stage_completion(telegram_user_id, stage)
            
            logger.info(
                f"✅ Created user {telegram_user_id} with BOTH wallets:\n"
                f"   🔷 Polygon: {polygon_address}\n"
                f"   🔶 Solana: {solana_address}\n"
                f"   📊 Stage: {stage.display_name} ({stage.progress_percentage}%)"
            )
            
            return user
            
        except Exception as e:
            logger.error(f"❌ Error creating user {telegram_user_id}: {e}")
            UserProgressTracker.log_stage_failure(telegram_user_id, UserStage.CREATED, str(e))
            return None
    
    # ========================================================================
    # Polygon Wallet
    # ========================================================================
    
    def _generate_polygon_wallet(self) -> Tuple[str, str]:
        """Generate new Polygon (Ethereum) wallet"""
        account = Account.create()
        return account.address, account.key.hex()
    
    def get_polygon_address(self, telegram_user_id: int) -> Optional[str]:
        """Get user's Polygon wallet address"""
        user = self.get_user(telegram_user_id)
        return user.polygon_address if user else None
    
    def get_polygon_private_key(self, telegram_user_id: int) -> Optional[str]:
        """Get user's Polygon private key (use carefully!)"""
        user = self.get_user(telegram_user_id)
        return user.polygon_private_key if user else None
    
    # ========================================================================
    # Solana Wallet
    # ========================================================================
    
    def generate_solana_wallet(self, telegram_user_id: int) -> Optional[Tuple[str, str]]:
        """Generate Solana wallet for user"""
        try:
            user = self.get_user(telegram_user_id)
            if not user:
                logger.error(f"❌ User {telegram_user_id} not found")
                return None
            
            # Check if already has Solana wallet
            if user.solana_address:
                logger.info(f"ℹ️ User {telegram_user_id} already has Solana wallet")
                return user.solana_address, user.solana_private_key
            
            # Generate new Solana keypair
            keypair = Keypair()
            address = str(keypair.pubkey())
            private_key = base58.b58encode(bytes(keypair)).decode('ascii')
            
            # Save to database
            success = db_manager.update_user_solana_wallet(
                telegram_user_id=telegram_user_id,
                solana_address=address,
                solana_private_key=private_key
            )
            
            if success:
                logger.info(f"✅ Generated Solana wallet for user {telegram_user_id}: {address}")
                return address, private_key
            else:
                logger.error(f"❌ Failed to save Solana wallet for user {telegram_user_id}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error generating Solana wallet for user {telegram_user_id}: {e}")
            return None
    
    def get_solana_address(self, telegram_user_id: int) -> Optional[str]:
        """Get user's Solana wallet address"""
        user = self.get_user(telegram_user_id)
        return user.solana_address if user else None
    
    def get_solana_private_key(self, telegram_user_id: int) -> Optional[str]:
        """Get user's Solana private key (use carefully!)"""
        user = self.get_user(telegram_user_id)
        return user.solana_private_key if user else None
    
    def get_solana_keypair(self, telegram_user_id: int) -> Optional[Keypair]:
        """Get Solana Keypair object for signing transactions"""
        try:
            private_key = self.get_solana_private_key(telegram_user_id)
            if not private_key:
                return None
            
            # Decode from base58
            private_key_bytes = base58.b58decode(private_key)
            keypair = Keypair.from_bytes(private_key_bytes)
            return keypair
            
        except Exception as e:
            logger.error(f"❌ Error getting Solana keypair for user {telegram_user_id}: {e}")
            return None
    
    # ========================================================================
    # API Credentials
    # ========================================================================
    
    def save_api_credentials(self, telegram_user_id: int, api_key: str, 
                            api_secret: str, api_passphrase: str) -> bool:
        """Save API credentials with stage tracking"""
        try:
            # Get old stage for progression tracking
            old_stage = self.get_user_stage(telegram_user_id)
            
            success = db_manager.update_user_api_keys(
                telegram_user_id=telegram_user_id,
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase
            )
            
            if success:
                # Track progression - user should now be READY
                new_stage = self.get_user_stage(telegram_user_id)
                if old_stage and new_stage and old_stage != new_stage:
                    UserProgressTracker.log_stage_progression(
                        telegram_user_id, old_stage, new_stage, "API credentials generated"
                    )
                
                logger.info(f"✅ Saved API credentials for user {telegram_user_id} - Stage: {new_stage.display_name if new_stage else 'Unknown'}")
            else:
                logger.error(f"❌ Failed to save API credentials for user {telegram_user_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Error saving API credentials for user {telegram_user_id}: {e}")
            return False
    
    def get_api_credentials(self, telegram_user_id: int) -> Optional[Dict]:
        """Get API credentials for user"""
        user = self.get_user(telegram_user_id)
        if not user or not user.api_key:
            return None
        
        return {
            'api_key': user.api_key,
            'api_secret': user.api_secret,
            'api_passphrase': user.api_passphrase
        }
    
    def has_api_credentials(self, telegram_user_id: int) -> bool:
        """Check if user has API credentials"""
        user = self.get_user(telegram_user_id)
        return user is not None and user.api_key is not None
    
    # ========================================================================
    # Enhanced State Management (NEW for streamlined flow)
    # ========================================================================
    
    def get_user_stage(self, telegram_user_id: int) -> Optional[UserStage]:
        """Get current user stage"""
        user = self.get_user(telegram_user_id)
        if not user:
            return None
        return UserStateValidator.get_user_stage(user)
    
    def get_user_progress_info(self, telegram_user_id: int) -> Dict:
        """Get comprehensive progress information"""
        user = self.get_user(telegram_user_id)
        return UserStateValidator.get_user_progress_info(user)
    
    def get_next_step_message(self, telegram_user_id: int) -> str:
        """Get user-friendly next step message"""
        user = self.get_user(telegram_user_id)
        if not user:
            return "User not found. Use /start to create account."
        return UserStateValidator.get_next_step_message(user)
    
    def is_user_ready_for_trading(self, telegram_user_id: int) -> bool:
        """Quick check if user is ready to trade"""
        user = self.get_user(telegram_user_id)
        if not user:
            return False
        return UserStateValidator.is_user_ready_for_trading(user)
    
    def validate_user_integrity(self, telegram_user_id: int) -> List[str]:
        """Check for data integrity issues"""
        user = self.get_user(telegram_user_id)
        return UserStateValidator.validate_user_data_integrity(user)
    
    def track_stage_progression(self, telegram_user_id: int, message: str = ""):
        """Track and log user stage progression"""
        user = self.get_user(telegram_user_id)
        if user:
            stage = UserStateValidator.get_user_stage(user)
            UserProgressTracker.log_stage_completion(telegram_user_id, stage)
    
    # ========================================================================
    # Status & Approvals (Enhanced with stage tracking)
    # ========================================================================
    
    def update_funding_status(self, telegram_user_id: int, funded: bool = True) -> bool:
        """Update funding status with stage tracking"""
        try:
            # Get old stage for progression tracking
            old_stage = self.get_user_stage(telegram_user_id)
            
            success = db_manager.update_user_approvals(
                telegram_user_id=telegram_user_id,
                funded=funded
            )
            
            if success and funded:
                # Track progression
                new_stage = self.get_user_stage(telegram_user_id)
                if old_stage and new_stage and old_stage != new_stage:
                    UserProgressTracker.log_stage_progression(
                        telegram_user_id, old_stage, new_stage, "funding detected"
                    )
                
            return success
            
        except Exception as e:
            logger.error(f"❌ Error updating funding status for user {telegram_user_id}: {e}")
            return False
    
    def update_approval_status(self, telegram_user_id: int, **kwargs) -> bool:
        """
        Update approval status with stage tracking
        
        Example:
            update_approval_status(user_id, usdc_approved=True, pol_approved=True)
        """
        try:
            # Get old stage for progression tracking
            old_stage = self.get_user_stage(telegram_user_id)
            
            success = db_manager.update_user_approvals(
                telegram_user_id=telegram_user_id,
                **kwargs
            )
            
            if success:
                # Track progression
                new_stage = self.get_user_stage(telegram_user_id)
                if old_stage and new_stage and old_stage != new_stage:
                    approval_types = list(kwargs.keys())
                    UserProgressTracker.log_stage_progression(
                        telegram_user_id, old_stage, new_stage, 
                        f"approvals updated: {', '.join(approval_types)}"
                    )
                
            return success
            
        except Exception as e:
            logger.error(f"❌ Error updating approval status for user {telegram_user_id}: {e}")
            return False
    
    def is_wallet_ready(self, telegram_user_id: int) -> Tuple[bool, str]:
        """Check if wallet is ready for trading"""
        user = self.get_user(telegram_user_id)
        if not user:
            return False, "No wallet found. Use /start to create one."
        
        if not user.funded:
            return False, "Wallet needs funding (USDC.e + POL)"
        
        if not user.usdc_approved:
            return False, "USDC.e approval needed"
        
        if not user.pol_approved:
            return False, "POL approval needed"
        
        if not user.polymarket_approved:
            return False, "Polymarket contract approval needed"
        
        if not user.api_key:
            return False, "API credentials needed"
        
        return True, "Wallet ready for trading!"
    
    def get_user_status(self, telegram_user_id: int) -> Optional[Dict]:
        """Get complete user status"""
        user = self.get_user(telegram_user_id)
        if not user:
            return None
        
        return {
            'telegram_user_id': user.telegram_user_id,
            'username': user.username,
            'polygon_address': user.polygon_address,
            'solana_address': user.solana_address,
            'has_api_credentials': user.api_key is not None,
            'funded': user.funded,
            'usdc_approved': user.usdc_approved,
            'pol_approved': user.pol_approved,
            'polymarket_approved': user.polymarket_approved,
            'auto_approval_completed': user.auto_approval_completed,
            'wallet_generation_count': user.wallet_generation_count,
            'is_ready': user.is_ready_to_trade(),
            'created_at': user.created_at,
            'last_active': user.last_active
        }
    
    # ========================================================================
    # Rollback Safety Mechanisms (NEW for streamlined flow)
    # ========================================================================
    
    def reset_user_to_stage(self, telegram_user_id: int, target_stage: UserStage) -> bool:
        """
        Reset user to a specific stage for retry/debugging
        
        Args:
            telegram_user_id: User to reset
            target_stage: Stage to reset to
            
        Returns:
            True if reset successful
        """
        try:
            user = self.get_user(telegram_user_id)
            if not user:
                logger.error(f"❌ User {telegram_user_id} not found for reset")
                return False
            
            current_stage = UserStateValidator.get_user_stage(user)
            logger.info(f"🔄 Resetting user {telegram_user_id} from {current_stage.display_name} to {target_stage.display_name}")
            
            # Reset based on target stage
            reset_data = {}
            
            if target_stage == UserStage.CREATED:
                # Reset to just having Polygon wallet
                reset_data.update({
                    'solana_address': None,
                    'solana_private_key': None,
                    'funded': False,
                    'usdc_approved': False,
                    'pol_approved': False,
                    'polymarket_approved': False,
                    'auto_approval_completed': False,
                    'api_key': None,
                    'api_secret': None,
                    'api_passphrase': None
                })
            
            elif target_stage == UserStage.SOL_GENERATED:
                # Reset to having both wallets, not funded
                reset_data.update({
                    'funded': False,
                    'usdc_approved': False,
                    'pol_approved': False,
                    'polymarket_approved': False,
                    'auto_approval_completed': False,
                    'api_key': None,
                    'api_secret': None,
                    'api_passphrase': None
                })
            
            elif target_stage == UserStage.FUNDED:
                # Reset to funded but no approvals
                reset_data.update({
                    'usdc_approved': False,
                    'pol_approved': False,
                    'polymarket_approved': False,
                    'auto_approval_completed': False,
                    'api_key': None,
                    'api_secret': None,
                    'api_passphrase': None
                })
            
            elif target_stage == UserStage.APPROVED:
                # Reset to approved but no API keys
                reset_data.update({
                    'api_key': None,
                    'api_secret': None,
                    'api_passphrase': None
                })
            
            # Apply the reset
            if reset_data:
                success = db_manager.update_user_approvals(
                    telegram_user_id=telegram_user_id,
                    **reset_data
                )
                
                if success:
                    UserProgressTracker.log_stage_progression(
                        telegram_user_id, current_stage, target_stage, 
                        f"manual reset for debugging"
                    )
                    logger.info(f"✅ Reset user {telegram_user_id} to {target_stage.display_name}")
                    return True
                else:
                    logger.error(f"❌ Failed to reset user {telegram_user_id}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error resetting user {telegram_user_id} to {target_stage}: {e}")
            return False
    
    def retry_current_stage(self, telegram_user_id: int) -> bool:
        """
        Retry the current stage for a user who got stuck
        
        Args:
            telegram_user_id: User to retry
            
        Returns:
            True if retry setup successful
        """
        try:
            user = self.get_user(telegram_user_id)
            if not user:
                return False
            
            current_stage = UserStateValidator.get_user_stage(user)
            logger.info(f"🔄 Retrying stage {current_stage.display_name} for user {telegram_user_id}")
            
            # Clear any "in progress" flags that might be blocking
            if current_stage == UserStage.FUNDED:
                # Reset auto-approval flags to allow retry
                success = db_manager.update_user_approvals(
                    telegram_user_id=telegram_user_id,
                    auto_approval_last_check=None
                )
                if success:
                    logger.info(f"✅ Cleared auto-approval blocks for user {telegram_user_id}")
                return success
            
            # For other stages, just log that retry was requested
            logger.info(f"ℹ️ Stage {current_stage.display_name} doesn't need special retry handling")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error retrying stage for user {telegram_user_id}: {e}")
            return False
    
    def fix_user_data_integrity(self, telegram_user_id: int) -> bool:
        """
        Attempt to fix common data integrity issues
        
        Args:
            telegram_user_id: User to fix
            
        Returns:
            True if fixes were applied
        """
        try:
            user = self.get_user(telegram_user_id)
            if not user:
                return False
            
            errors = UserStateValidator.validate_user_data_integrity(user)
            if not errors:
                logger.info(f"✅ User {telegram_user_id} data integrity is good")
                return True
            
            logger.info(f"🔧 Fixing {len(errors)} data integrity issues for user {telegram_user_id}")
            fixes_applied = False
            
            # Fix incomplete API credentials
            api_fields = [user.api_key, user.api_secret, user.api_passphrase]
            api_count = sum(1 for field in api_fields if field is not None)
            if 0 < api_count < 3:
                logger.info("🔧 Clearing incomplete API credentials")
                db_manager.update_user_api_keys(
                    telegram_user_id=telegram_user_id,
                    api_key=None,
                    api_secret=None,
                    api_passphrase=None
                )
                fixes_applied = True
            
            # Fix approval consistency
            if user.auto_approval_completed and not (user.usdc_approved and user.pol_approved and user.polymarket_approved):
                logger.info("🔧 Fixing approval consistency")
                db_manager.update_user_approvals(
                    telegram_user_id=telegram_user_id,
                    auto_approval_completed=False
                )
                fixes_applied = True
            
            if fixes_applied:
                logger.info(f"✅ Applied data integrity fixes for user {telegram_user_id}")
            
            return fixes_applied
            
        except Exception as e:
            logger.error(f"❌ Error fixing user data integrity for {telegram_user_id}: {e}")
            return False
    
    # ========================================================================
    # /restart Command Support (Enhanced)
    # ========================================================================
    
    def restart_user_wallets(self, telegram_user_id: int) -> bool:
        """
        Generate new wallets for user (/restart command)
        Resets: wallets, API keys, approvals
        Keeps: positions (archived to old wallet)
        """
        try:
            user = self.get_user(telegram_user_id)
            if not user:
                logger.error(f"❌ User {telegram_user_id} not found")
                return False
            
            # Generate new wallets
            new_polygon_address, new_polygon_private_key = self._generate_polygon_wallet()
            keypair = Keypair()
            new_solana_address = str(keypair.pubkey())
            new_solana_private_key = base58.b58encode(bytes(keypair)).decode('ascii')
            
            # Update user with new wallets and reset approvals
            with db_manager.get_session() as db:
                user = db.query(User).filter(User.telegram_user_id == telegram_user_id).first()
                if user:
                    # Update wallets
                    user.polygon_address = new_polygon_address
                    user.polygon_private_key = new_polygon_private_key
                    user.solana_address = new_solana_address
                    user.solana_private_key = new_solana_private_key
                    
                    # Reset API keys
                    user.api_key = None
                    user.api_secret = None
                    user.api_passphrase = None
                    
                    # Reset approvals
                    user.funded = False
                    user.usdc_approved = False
                    user.pol_approved = False
                    user.polymarket_approved = False
                    user.auto_approval_completed = False
                    
                    # Update metadata
                    user.wallet_generation_count += 1
                    user.last_restart = datetime.utcnow()
                    
                    db.commit()
                    
                    logger.info(f"✅ Restarted wallets for user {telegram_user_id} (generation #{user.wallet_generation_count})")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error restarting wallets for user {telegram_user_id}: {e}")
            return False
    
    # ========================================================================
    # Statistics
    # ========================================================================
    
    def get_stats(self) -> Dict:
        """Get service statistics"""
        try:
            with db_manager.get_session() as db:
                total_users = db.query(User).count()
                funded_users = db.query(User).filter(User.funded == True).count()
                ready_users = db.query(User).filter(
                    User.funded == True,
                    User.usdc_approved == True,
                    User.pol_approved == True,
                    User.polymarket_approved == True,
                    User.api_key.isnot(None)
                ).count()
                
                return {
                    'total_users': total_users,
                    'funded_users': funded_users,
                    'ready_users': ready_users
                }
        except Exception as e:
            logger.error(f"❌ Error getting stats: {e}")
            return {'error': str(e)}
    
    # ========================================================================
    # Backward Compatibility (for legacy handler code)
    # ========================================================================
    
    def get_user_wallet(self, user_id: int) -> Optional[Dict]:
        """
        LEGACY: Get user wallet in dict format (backward compatible)
        Returns polygon wallet data in old format for legacy handlers
        """
        user = self.get_user(user_id)
        if not user:
            return None
        
        return {
            'address': user.polygon_address,
            'private_key': user.polygon_private_key,
            'username': user.username,
            'funded': user.funded,
            'usdc_approved': user.usdc_approved,
            'polymarket_approved': user.polymarket_approved,
            'pol_approved': user.pol_approved,
            'api_credentials_generated': user.api_key is not None,
            'auto_approval_completed': user.auto_approval_completed,
            'created_at': user.created_at.timestamp() if user.created_at else None,
            'last_approval_check': user.auto_approval_last_check.timestamp() if user.auto_approval_last_check else None
        }
    
    def get_user_api_credentials(self, user_id: int) -> Optional[Dict]:
        """
        LEGACY: Get API credentials in old dict format
        Alias for get_api_credentials (backward compatible)
        """
        return self.get_api_credentials(user_id)
    
    def generate_wallet_for_user(self, user_id: int, username: str = None) -> Tuple[str, str]:
        """
        LEGACY: Generate wallet and return (address, private_key) tuple
        Creates user if doesn't exist, returns existing if exists
        """
        user = self.create_user(telegram_user_id=user_id, username=username)
        if user:
            return user.polygon_address, user.polygon_private_key
        return None, None
    
    def update_api_credentials_status(self, user_id: int, generated: bool = True):
        """LEGACY: Update API credentials status (does nothing, kept for compatibility)"""
        # API credentials status is now tracked by api_key IS NOT NULL
        pass


# Global user service instance
user_service = UserService()

