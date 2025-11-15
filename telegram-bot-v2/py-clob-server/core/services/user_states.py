#!/usr/bin/env python3
"""
User State Management System
Defines user onboarding stages and state validation for the streamlined flow
"""

import logging
from enum import Enum
from typing import Dict, Optional, Tuple, List
from datetime import datetime

logger = logging.getLogger(__name__)


class UserStage(Enum):
    """
    User onboarding stages for the streamlined flow
    Each stage represents a milestone in the user setup process
    """
    CREATED = "created"           # Has Polygon wallet, needs SOL wallet
    SOL_GENERATED = "sol_ready"   # Has both wallets, needs funding
    FUNDED = "funded"             # Funding detected, approvals in progress
    APPROVED = "approved"         # Contracts approved, API generation in progress
    READY = "ready"               # Fully ready to trade
    
    def __str__(self):
        return self.value
    
    @property
    def display_name(self) -> str:
        """Human-readable stage name"""
        display_names = {
            UserStage.CREATED: "Wallets Created",
            UserStage.SOL_GENERATED: "SOL Wallet Ready", 
            UserStage.FUNDED: "Wallet Funded",
            UserStage.APPROVED: "Contracts Approved",
            UserStage.READY: "Ready to Trade"
        }
        return display_names[self]
    
    @property
    def progress_percentage(self) -> int:
        """Progress percentage for this stage"""
        percentages = {
            UserStage.CREATED: 20,
            UserStage.SOL_GENERATED: 40,
            UserStage.FUNDED: 60,
            UserStage.APPROVED: 80,
            UserStage.READY: 100
        }
        return percentages[self]
    
    @property
    def emoji(self) -> str:
        """Emoji representation for UI"""
        emojis = {
            UserStage.CREATED: "🔧",
            UserStage.SOL_GENERATED: "💰",
            UserStage.FUNDED: "⚡",
            UserStage.APPROVED: "✅",
            UserStage.READY: "🚀"
        }
        return emojis[self]


class UserStateValidator:
    """
    Validates user state and determines current stage
    Core logic for user progression tracking
    """
    
    @staticmethod
    def get_user_stage(user) -> UserStage:
        """
        Determine current user stage based on database state
        
        Args:
            user: User database model instance
            
        Returns:
            UserStage enum representing current stage
        """
        if not user:
            raise ValueError("User cannot be None")
        
        # Stage 1: CREATED - has Polygon wallet only
        if not user.solana_address:
            return UserStage.CREATED
        
        # Stage 2: SOL_GENERATED - has both wallets, not funded
        if not user.funded:
            return UserStage.SOL_GENERATED
        
        # Stage 3: FUNDED - funded but approvals not completed
        if not user.auto_approval_completed:
            return UserStage.FUNDED
        
        # Stage 4: APPROVED - approvals done, no API keys yet
        if not user.api_key:
            return UserStage.APPROVED
        
        # Stage 5: READY - fully set up
        return UserStage.READY
    
    @staticmethod
    def get_next_step_message(user) -> str:
        """
        Get user-friendly message about what to do next
        
        Args:
            user: User database model instance
            
        Returns:
            Human-readable message about next steps
        """
        stage = UserStateValidator.get_user_stage(user)
        
        messages = {
            UserStage.CREATED: "⏳ Setting up your SOL wallet...",
            UserStage.SOL_GENERATED: f"💰 Fund your SOL wallet: `{user.solana_address}`\nSend 0.1+ SOL, then click the bridge button!",
            UserStage.FUNDED: "⚡ Processing bridge and approving contracts... (2-3 minutes)",
            UserStage.APPROVED: "🔑 Generating API keys... (30 seconds)",
            UserStage.READY: "🚀 Ready to trade! Use /markets to start trading!"
        }
        
        return messages[stage]
    
    @staticmethod
    def get_stage_requirements(stage: UserStage) -> Dict[str, bool]:
        """
        Get requirements that must be met for a specific stage
        
        Args:
            stage: Target stage to check requirements for
            
        Returns:
            Dict of requirement names and whether they're boolean checks
        """
        requirements = {
            UserStage.CREATED: {
                "polygon_address": True,
                "polygon_private_key": True
            },
            UserStage.SOL_GENERATED: {
                "polygon_address": True,
                "polygon_private_key": True,
                "solana_address": True,
                "solana_private_key": True
            },
            UserStage.FUNDED: {
                "polygon_address": True,
                "polygon_private_key": True,
                "solana_address": True,
                "solana_private_key": True,
                "funded": True
            },
            UserStage.APPROVED: {
                "polygon_address": True,
                "polygon_private_key": True,
                "solana_address": True,
                "solana_private_key": True,
                "funded": True,
                "usdc_approved": True,
                "pol_approved": True,
                "polymarket_approved": True,
                "auto_approval_completed": True
            },
            UserStage.READY: {
                "polygon_address": True,
                "polygon_private_key": True,
                "solana_address": True,
                "solana_private_key": True,
                "funded": True,
                "usdc_approved": True,
                "pol_approved": True,
                "polymarket_approved": True,
                "auto_approval_completed": True,
                "api_key": True,
                "api_secret": True,
                "api_passphrase": True
            }
        }
        
        return requirements.get(stage, {})
    
    @staticmethod
    def validate_user_data_integrity(user) -> List[str]:
        """
        Check for data inconsistencies in user record
        
        Args:
            user: User database model instance
            
        Returns:
            List of error messages (empty if no issues)
        """
        errors = []
        
        if not user:
            return ["User record not found"]
        
        # Basic required fields
        if not user.telegram_user_id:
            errors.append("Missing telegram_user_id")
        
        if not user.polygon_address:
            errors.append("Missing polygon_address")
        
        if not user.polygon_private_key:
            errors.append("Missing polygon_private_key")
        
        # Logical consistency checks
        if user.funded and not user.solana_address:
            errors.append("User marked as funded but has no SOL wallet")
        
        if user.auto_approval_completed and not user.funded:
            errors.append("Approvals completed but user not funded")
        
        if user.api_key and not user.auto_approval_completed:
            errors.append("Has API keys but approvals not completed")
        
        # API credentials consistency
        api_fields = [user.api_key, user.api_secret, user.api_passphrase]
        api_count = sum(1 for field in api_fields if field is not None)
        if 0 < api_count < 3:
            errors.append("Incomplete API credentials (should have all 3 or none)")
        
        # Approval consistency
        if user.auto_approval_completed:
            if not (user.usdc_approved and user.pol_approved and user.polymarket_approved):
                errors.append("Auto-approval marked complete but individual approvals missing")
        
        return errors
    
    @staticmethod
    def is_user_ready_for_trading(user) -> bool:
        """
        Quick check if user has completed all setup steps
        
        Args:
            user: User database model instance
            
        Returns:
            True if user is fully ready to trade
        """
        return UserStateValidator.get_user_stage(user) == UserStage.READY
    
    @staticmethod
    def get_user_progress_info(user) -> Dict:
        """
        Get comprehensive progress information for user
        
        Args:
            user: User database model instance
            
        Returns:
            Dict with stage, progress, next steps, etc.
        """
        if not user:
            return {
                "stage": None,
                "stage_name": "Not Found",
                "progress_percentage": 0,
                "next_step_message": "User not found. Use /start to create account.",
                "is_ready": False,
                "errors": ["User not found"]
            }
        
        stage = UserStateValidator.get_user_stage(user)
        errors = UserStateValidator.validate_user_data_integrity(user)
        
        return {
            "stage": stage,
            "stage_name": stage.display_name,
            "progress_percentage": stage.progress_percentage,
            "next_step_message": UserStateValidator.get_next_step_message(user),
            "is_ready": stage == UserStage.READY,
            "emoji": stage.emoji,
            "errors": errors,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_active": user.last_active.isoformat() if user.last_active else None
        }


class UserProgressTracker:
    """
    Tracks user progression through onboarding stages
    Provides logging and analytics for the streamlined flow
    """
    
    @staticmethod
    def log_stage_progression(user_id: int, old_stage: UserStage, new_stage: UserStage, message: str = ""):
        """
        Log user progression between stages
        
        Args:
            user_id: Telegram user ID
            old_stage: Previous stage
            new_stage: New stage
            message: Optional additional message
        """
        logger.info(
            f"👤 User {user_id} progressed: {old_stage.display_name} → {new_stage.display_name} "
            f"({old_stage.progress_percentage}% → {new_stage.progress_percentage}%) {message}"
        )
    
    @staticmethod
    def log_stage_completion(user_id: int, stage: UserStage, duration_seconds: Optional[float] = None):
        """
        Log completion of a specific stage
        
        Args:
            user_id: Telegram user ID
            stage: Completed stage
            duration_seconds: Optional time taken to complete stage
        """
        duration_msg = f" (took {duration_seconds:.1f}s)" if duration_seconds else ""
        logger.info(
            f"✅ User {user_id} completed {stage.display_name} "
            f"({stage.progress_percentage}% complete){duration_msg}"
        )
    
    @staticmethod
    def log_stage_failure(user_id: int, stage: UserStage, error: str):
        """
        Log failure during a stage
        
        Args:
            user_id: Telegram user ID
            stage: Stage where failure occurred
            error: Error message
        """
        logger.error(
            f"❌ User {user_id} failed at {stage.display_name} "
            f"({stage.progress_percentage}%): {error}"
        )
    
    @staticmethod
    def get_onboarding_analytics() -> Dict:
        """
        Get analytics about user onboarding (would need database queries)
        
        Returns:
            Dict with onboarding statistics
        """
        # This would be implemented with actual database queries
        # For now, return placeholder structure
        return {
            "total_users": 0,
            "users_by_stage": {
                "created": 0,
                "sol_generated": 0,
                "funded": 0,
                "approved": 0,
                "ready": 0
            },
            "average_completion_time": None,
            "common_failure_points": []
        }
