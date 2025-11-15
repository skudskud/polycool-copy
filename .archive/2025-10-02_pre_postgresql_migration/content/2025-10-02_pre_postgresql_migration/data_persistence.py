#!/usr/bin/env python3
"""
Data Persistence Manager for Telegram Trading Bot V2
Prevents data loss during deployments by implementing multiple backup strategies
"""

import json
import os
import time
import logging
import shutil
from datetime import datetime
from typing import Dict, Optional, Any, List
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

class DataPersistenceManager:
    """
    Comprehensive data persistence system that prevents data loss during deployments
    
    Features:
    - Multiple backup locations (local, persistent volume, cloud)
    - Automatic recovery from backups
    - Deployment-safe storage
    - Data integrity validation
    - Automatic migration between formats
    """
    
    def __init__(self):
        """Initialize data persistence manager"""
        
        # Primary data directory (persistent volume if available)
        self.data_dir = self._get_persistent_data_dir()
        
        # Backup directories
        self.backup_dirs = [
            os.path.join(self.data_dir, "backups"),
            "/tmp/bot_backups",  # Fallback for Railway
            "data/backups"  # Local fallback
        ]
        
        # Ensure all directories exist
        self._ensure_directories()
        
        logger.info(f"Data persistence initialized: {self.data_dir}")
        
    def _get_persistent_data_dir(self) -> str:
        """Get the best persistent data directory for the platform"""
        
        # Check for Railway persistent volume
        if os.path.exists("/app/data"):
            return "/app/data"
        
        # Check for Docker volume mount
        if os.path.exists("/data"):
            return "/data"
        
        # Check for environment variable
        if "DATA_DIR" in os.environ:
            return os.environ["DATA_DIR"]
        
        # Default to local data directory
        return "data"
    
    def _ensure_directories(self):
        """Ensure all required directories exist"""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            
            for backup_dir in self.backup_dirs:
                try:
                    os.makedirs(backup_dir, exist_ok=True)
                except Exception as e:
                    logger.warning(f"Could not create backup dir {backup_dir}: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to create data directories: {e}")
            raise
    
    def get_file_path(self, filename: str) -> str:
        """Get the full path for a data file - check current directory first"""
        # CRITICAL FIX: Check current working directory first (where files actually are)
        current_dir_path = os.path.join(os.getcwd(), filename)
        if os.path.exists(current_dir_path):
            return current_dir_path
        
        # Fallback to data directory
        return os.path.join(self.data_dir, filename)
    
    def save_data(self, filename: str, data: Dict, create_backup: bool = True) -> bool:
        """
        Save data with atomic writes and backup creation
        
        Args:
            filename: Name of the file to save
            data: Data to save
            create_backup: Whether to create a backup before saving
            
        Returns:
            True if successful, False otherwise
        """
        file_path = self.get_file_path(filename)
        
        try:
            # Create backup if requested and file exists
            if create_backup and os.path.exists(file_path):
                self._create_backup(filename)
            
            # Use atomic write
            temp_file = f"{file_path}.tmp"
            
            # Write to temporary file
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # Verify the temporary file
            with open(temp_file, 'r') as f:
                verification_data = json.load(f)
                if verification_data != data:
                    raise ValueError("Data verification failed")
            
            # Atomically replace the original file
            shutil.move(temp_file, file_path)
            
            # Create additional backups in multiple locations
            if create_backup:
                self._create_distributed_backups(filename, data)
            
            logger.info(f"✅ Saved {filename} successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to save {filename}: {e}")
            
            # Clean up temporary file
            temp_file = f"{file_path}.tmp"
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
            
            return False
    
    def load_data(self, filename: str, default: Dict = None) -> Dict:
        """
        Load data with automatic recovery from backups if needed
        
        Args:
            filename: Name of the file to load
            default: Default data if file doesn't exist
            
        Returns:
            Loaded data or default
        """
        if default is None:
            default = {}
            
        file_path = self.get_file_path(filename)
        
        # Try to load from primary location
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    logger.info(f"✅ Loaded {filename} from primary location")
                    return data
        except Exception as e:
            logger.warning(f"Failed to load {filename} from primary location: {e}")
        
        # Try to recover from backups
        logger.info(f"🔄 Attempting to recover {filename} from backups...")
        recovered_data = self._recover_from_backups(filename)
        
        if recovered_data is not None:
            # Save recovered data back to primary location
            self.save_data(filename, recovered_data, create_backup=False)
            logger.info(f"✅ Recovered {filename} from backup")
            return recovered_data
        
        # No data found, return default
        logger.info(f"📝 No existing {filename} found, starting with default data")
        return default
    
    def _create_backup(self, filename: str):
        """Create a timestamped backup of a file"""
        file_path = self.get_file_path(filename)
        
        if not os.path.exists(file_path):
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{filename}.backup_{timestamp}"
        
        try:
            # Create backup in primary backup directory
            primary_backup_dir = self.backup_dirs[0]
            backup_path = os.path.join(primary_backup_dir, backup_name)
            shutil.copy2(file_path, backup_path)
            
            # Also create a simple .backup file
            simple_backup = f"{file_path}.backup"
            shutil.copy2(file_path, simple_backup)
            
            logger.info(f"📋 Created backup: {backup_name}")
            
        except Exception as e:
            logger.warning(f"Failed to create backup for {filename}: {e}")
    
    def _create_distributed_backups(self, filename: str, data: Dict):
        """Create backups in multiple locations for redundancy"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{filename}.backup_{timestamp}"
        
        for backup_dir in self.backup_dirs:
            try:
                if os.path.exists(backup_dir):
                    backup_path = os.path.join(backup_dir, backup_name)
                    with open(backup_path, 'w') as f:
                        json.dump(data, f, indent=2)
                    
                    # Keep only last 10 backups per location
                    self._cleanup_old_backups(backup_dir, filename, keep=10)
                    
            except Exception as e:
                logger.warning(f"Failed to create distributed backup in {backup_dir}: {e}")
    
    def _recover_from_backups(self, filename: str) -> Optional[Dict]:
        """Try to recover data from backup locations"""
        
        # List of backup files to try (in order of preference)
        backup_candidates = []
        
        # Add simple .backup files
        primary_backup = f"{self.get_file_path(filename)}.backup"
        if os.path.exists(primary_backup):
            backup_candidates.append(primary_backup)
        
        # Add timestamped backups from all backup directories
        for backup_dir in self.backup_dirs:
            if os.path.exists(backup_dir):
                try:
                    backup_files = [
                        os.path.join(backup_dir, f) 
                        for f in os.listdir(backup_dir) 
                        if f.startswith(f"{filename}.backup_")
                    ]
                    # Sort by modification time (newest first)
                    backup_files.sort(key=os.path.getmtime, reverse=True)
                    backup_candidates.extend(backup_files)
                except Exception as e:
                    logger.warning(f"Error scanning backup directory {backup_dir}: {e}")
        
        # Try each backup candidate
        for backup_path in backup_candidates:
            try:
                with open(backup_path, 'r') as f:
                    data = json.load(f)
                    logger.info(f"🔄 Successfully recovered from backup: {backup_path}")
                    return data
            except Exception as e:
                logger.warning(f"Failed to load backup {backup_path}: {e}")
        
        return None
    
    def _cleanup_old_backups(self, backup_dir: str, filename: str, keep: int = 10):
        """Clean up old backup files, keeping only the most recent ones"""
        try:
            backup_files = [
                f for f in os.listdir(backup_dir) 
                if f.startswith(f"{filename}.backup_")
            ]
            
            if len(backup_files) <= keep:
                return
            
            # Sort by modification time and remove oldest
            backup_paths = [os.path.join(backup_dir, f) for f in backup_files]
            backup_paths.sort(key=os.path.getmtime, reverse=True)
            
            for old_backup in backup_paths[keep:]:
                try:
                    os.remove(old_backup)
                    logger.debug(f"🗑️ Cleaned up old backup: {old_backup}")
                except Exception as e:
                    logger.warning(f"Failed to remove old backup {old_backup}: {e}")
                    
        except Exception as e:
            logger.warning(f"Error during backup cleanup: {e}")
    
    def create_deployment_backup(self):
        """Create a comprehensive backup before deployment"""
        logger.info("🚀 Creating pre-deployment backup...")
        
        # Files to backup
        critical_files = [
            "user_wallets.json",
            "user_api_keys.json", 
            "user_positions.json"
        ]
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        deployment_backup_dir = os.path.join(self.backup_dirs[0], f"deployment_{timestamp}")
        
        try:
            os.makedirs(deployment_backup_dir, exist_ok=True)
            
            backed_up_files = []
            for filename in critical_files:
                file_path = self.get_file_path(filename)
                if os.path.exists(file_path):
                    backup_path = os.path.join(deployment_backup_dir, filename)
                    shutil.copy2(file_path, backup_path)
                    backed_up_files.append(filename)
            
            logger.info(f"✅ Deployment backup created: {len(backed_up_files)} files backed up")
            return deployment_backup_dir
            
        except Exception as e:
            logger.error(f"❌ Failed to create deployment backup: {e}")
            return None
    
    def get_data_stats(self) -> Dict:
        """Get statistics about stored data"""
        stats = {
            'data_directory': self.data_dir,
            'backup_directories': self.backup_dirs,
            'files': {},
            'backups': {}
        }
        
        # Check main files
        critical_files = ["user_wallets.json", "user_api_keys.json", "user_positions.json"]
        
        for filename in critical_files:
            file_path = self.get_file_path(filename)
            if os.path.exists(file_path):
                stat = os.stat(file_path)
                stats['files'][filename] = {
                    'exists': True,
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                }
            else:
                stats['files'][filename] = {'exists': False}
        
        # Check backups
        for backup_dir in self.backup_dirs:
            if os.path.exists(backup_dir):
                try:
                    backup_files = os.listdir(backup_dir)
                    stats['backups'][backup_dir] = len(backup_files)
                except:
                    stats['backups'][backup_dir] = 'error'
            else:
                stats['backups'][backup_dir] = 'not_found'
        
        return stats

# Global instance
data_persistence = DataPersistenceManager()
