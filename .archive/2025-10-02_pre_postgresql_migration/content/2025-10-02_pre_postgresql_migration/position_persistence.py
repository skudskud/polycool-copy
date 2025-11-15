#!/usr/bin/env python3
"""
Position Persistence System for Telegram Trading Bot
Ensures user positions are never lost during bot restarts
"""

import json
import os
import time
import logging
import traceback
from datetime import datetime
from typing import Dict, Optional, Any
import shutil

logger = logging.getLogger(__name__)

class PositionPersistence:
    """Handles saving and loading user positions to/from disk with bulletproof persistence"""
    
    def __init__(self, storage_file: str = "user_positions.json"):
        """Initialize position persistence system with triple redundancy"""
        # PHASE 1 FIX: Move to root directory for Railway compatibility
        self.storage_file = storage_file  # Main file: user_positions.json (root)
        self.backup_file = "user_positions.backup.json"  # Immediate backup
        self.emergency_file = "user_positions.emergency.json"  # Emergency backup
        self.backup_dir = "position_backups"  # Timestamped backups (root level)
        
        # Ensure backup directory exists (root level, not data/)
        os.makedirs(self.backup_dir, exist_ok=True)
        
        # Initialize logging with position-specific logger
        self.logger = logging.getLogger('position_persistence')
        self.logger.setLevel(logging.INFO)
        
        # Create file handler if not exists
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        self.logger.info(f"🔧 Position persistence initialized:")
        self.logger.info(f"   - Main file: {self.storage_file}")
        self.logger.info(f"   - Backup file: {self.backup_file}")
        self.logger.info(f"   - Emergency file: {self.emergency_file}")
        self.logger.info(f"   - Backup directory: {self.backup_dir}")
        
        # Verify file system access
        self._verify_file_system_access()
    
    def _verify_file_system_access(self):
        """Verify we can read/write to the file system"""
        try:
            # Test write access
            test_file = "test_write_access.tmp"
            with open(test_file, 'w') as f:
                f.write("test")
            
            # Test read access
            with open(test_file, 'r') as f:
                content = f.read()
            
            # Cleanup
            os.remove(test_file)
            
            if content == "test":
                self.logger.info("✅ File system access verified")
                return True
            else:
                self.logger.error("❌ File system read/write test failed")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ File system access verification failed: {e}")
            return False
    
    def save_positions(self, user_sessions: Dict[int, Dict]) -> bool:
        """Save all user positions to disk with triple redundancy and bulletproof error handling"""
        self.logger.info("💾 Starting position save operation...")
        
        try:
            # Extract only position data (not other session data)
            positions_data = {}
            position_count = 0
            
            for user_id, session in user_sessions.items():
                if 'positions' in session and session['positions']:
                    user_positions = session['positions']
                    if user_positions:  # Only add if user actually has positions
                        positions_data[str(user_id)] = {
                            'positions': user_positions,
                            'last_updated': time.time(),
                            'version': '3.0',  # Updated version for new system
                            'user_id': user_id,
                            'position_count': len(user_positions)
                        }
                        position_count += len(user_positions)
            
            # Log what we're about to save
            self.logger.info(f"📊 Preparing to save {position_count} positions for {len(positions_data)} users")
            
            if position_count == 0:
                self.logger.warning("⚠️ No positions to save - all users have empty positions")
                # Still save empty state to maintain file consistency
            
            # PHASE 2: Triple redundancy save
            success_count = 0
            
            # Save to all three files
            files_to_save = [
                (self.storage_file, "MAIN"),
                (self.backup_file, "BACKUP"),
                (self.emergency_file, "EMERGENCY")
            ]
            
            for file_path, file_type in files_to_save:
                try:
                    # Create timestamped backup before overwriting
                    if os.path.exists(file_path):
                        self._create_timestamped_backup(file_path, file_type.lower())
                    
                    # Write the data
                    with open(file_path, 'w') as f:
                        json.dump(positions_data, f, indent=2, default=str)
                    
                    # Verify the write was successful
                    if self._verify_file_integrity(file_path, positions_data):
                        self.logger.info(f"✅ {file_type} file saved successfully: {file_path}")
                        success_count += 1
                    else:
                        self.logger.error(f"❌ {file_type} file verification failed: {file_path}")
                        
                except Exception as e:
                    self.logger.error(f"❌ Failed to save {file_type} file {file_path}: {e}")
            
            # Evaluate success
            if success_count >= 2:
                self.logger.info(f"✅ Position save successful: {success_count}/3 files saved")
                self.logger.info(f"📊 Saved {position_count} positions for {len(positions_data)} users")
                return True
            elif success_count >= 1:
                self.logger.warning(f"⚠️ Partial save success: {success_count}/3 files saved")
                self.logger.warning("Position data partially saved - some redundancy lost")
                return True
            else:
                self.logger.error("❌ CRITICAL: All position saves failed!")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ CRITICAL ERROR in save_positions: {e}")
            self.logger.error(f"Exception details: {traceback.format_exc()}")
            return False
    
    def _verify_file_integrity(self, file_path: str, expected_data: Dict) -> bool:
        """Verify that a file was written correctly by reading it back"""
        try:
            with open(file_path, 'r') as f:
                saved_data = json.load(f)
            
            # Basic integrity checks
            if not isinstance(saved_data, dict):
                return False
            
            # Check if the data structure matches what we expect
            if len(saved_data) != len(expected_data):
                return False
            
            # Check if all user IDs are present
            for user_id in expected_data.keys():
                if user_id not in saved_data:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ File integrity verification failed for {file_path}: {e}")
            return False
    
    def _create_timestamped_backup(self, file_path: str, file_type: str):
        """Create timestamped backup of a file before overwriting"""
        try:
            if os.path.exists(file_path):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"{file_type}_backup_{timestamp}.json"
                backup_path = os.path.join(self.backup_dir, backup_name)
                shutil.copy2(file_path, backup_path)
                self.logger.debug(f"📁 Created timestamped backup: {backup_path}")
                
                # Keep only last 20 backups per type
                self._cleanup_old_backups(file_type)
                
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to create timestamped backup for {file_path}: {e}")
    
    def load_positions(self) -> Dict[int, Dict]:
        """Load user positions from disk with bulletproof recovery and migration support"""
        self.logger.info("📂 Starting position load operation...")
        
        # Try loading from multiple sources in priority order
        load_sources = [
            (self.storage_file, "MAIN"),
            (self.backup_file, "BACKUP"), 
            (self.emergency_file, "EMERGENCY")
        ]
        
        for file_path, source_type in load_sources:
            try:
                if not os.path.exists(file_path):
                    self.logger.info(f"📄 {source_type} file not found: {file_path}")
                    continue
                
                self.logger.info(f"📖 Attempting to load from {source_type} file: {file_path}")
                
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                # Process and validate the loaded data
                user_sessions = self._process_loaded_data(data, source_type)
                
                if user_sessions:
                    position_count = sum(len(session.get('positions', {})) for session in user_sessions.values())
                    self.logger.info(f"✅ Successfully loaded {position_count} positions for {len(user_sessions)} users from {source_type}")
                    
                    # If we loaded from backup/emergency, save to main file
                    if source_type != "MAIN":
                        self.logger.info(f"🔄 Restoring {source_type} data to MAIN file")
                        self.save_positions(user_sessions)
                    
                    return user_sessions
                else:
                    self.logger.warning(f"⚠️ {source_type} file exists but contains no valid position data")
                    
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ {source_type} file corrupted (JSON decode error): {e}")
                continue
            except Exception as e:
                self.logger.error(f"❌ Failed to load from {source_type} file: {e}")
                continue
        
        # If all files failed, try loading from timestamped backups
        self.logger.warning("⚠️ All primary files failed, attempting backup recovery...")
        backup_data = self._load_from_timestamped_backup()
        if backup_data:
            return backup_data
        
        # Final fallback - return empty but log the critical situation
        self.logger.error("❌ CRITICAL: All position recovery methods failed!")
        self.logger.error("❌ Starting with empty position data - previous positions may be lost!")
        return {}
    
    def _process_loaded_data(self, data: Dict, source_type: str) -> Dict[int, Dict]:
        """Process and validate loaded position data"""
        try:
            user_sessions = {}
            migrated_count = 0
            
            for user_id_str, user_data in data.items():
                try:
                    user_id = int(user_id_str)
                    user_sessions[user_id] = {}
                    
                    # Handle different data format versions
                    if 'positions' in user_data:
                        # New format (v2.0+)
                        positions = user_data['positions']
                        version = user_data.get('version', '2.0')
                    else:
                        # Old format - migrate
                        positions = user_data
                        migrated_count += 1
                        version = '1.0'
                    
                    # Migrate position data structure if needed
                    migrated_positions = {}
                    for market_id, position in positions.items():
                        migrated_positions[market_id] = self._migrate_position_format(position)
                    
                    user_sessions[user_id]['positions'] = migrated_positions
                    
                    self.logger.debug(f"📊 Loaded {len(migrated_positions)} positions for user {user_id}")
                    
                except ValueError as e:
                    self.logger.error(f"❌ Invalid user ID in {source_type} data: {user_id_str}")
                    continue
                except Exception as e:
                    self.logger.error(f"❌ Error processing user data for {user_id_str}: {e}")
                    continue
            
            if migrated_count > 0:
                self.logger.info(f"🔄 Migrated {migrated_count} users from older format to v3.0")
                
            return user_sessions
            
        except Exception as e:
            self.logger.error(f"❌ Error processing loaded data from {source_type}: {e}")
            return {}
    
    def _load_from_timestamped_backup(self) -> Dict[int, Dict]:
        """Try to load from most recent timestamped backup"""
        try:
            if not os.path.exists(self.backup_dir):
                self.logger.warning("📁 Backup directory doesn't exist")
                return {}
            
            backup_files = [f for f in os.listdir(self.backup_dir) if f.endswith('.json')]
            if not backup_files:
                self.logger.warning("📁 No backup files found in backup directory")
                return {}
            
            # Sort by modification time (most recent first)
            backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(self.backup_dir, f)), reverse=True)
            
            # Try loading from the most recent backups
            for backup_file in backup_files[:5]:  # Try up to 5 most recent backups
                backup_path = os.path.join(self.backup_dir, backup_file)
                try:
                    self.logger.info(f"🔄 Attempting backup recovery from: {backup_file}")
                    
                    with open(backup_path, 'r') as f:
                        data = json.load(f)
                    
                    user_sessions = self._process_loaded_data(data, f"BACKUP({backup_file})")
                    
                    if user_sessions:
                        position_count = sum(len(session.get('positions', {})) for session in user_sessions.values())
                        self.logger.info(f"✅ Recovered {position_count} positions from backup: {backup_file}")
                        
                        # Save recovered data to main files
                        self.save_positions(user_sessions)
                        return user_sessions
                        
                except Exception as e:
                    self.logger.error(f"❌ Failed to load backup {backup_file}: {e}")
                    continue
            
            self.logger.error("❌ All backup recovery attempts failed")
            return {}
            
        except Exception as e:
            self.logger.error(f"❌ Error during backup recovery: {e}")
            return {}
    
    def _cleanup_old_backups(self, file_type: str):
        """Keep only the most recent backups for each file type"""
        try:
            backup_files = [f for f in os.listdir(self.backup_dir) 
                          if f.startswith(f'{file_type}_backup_') and f.endswith('.json')]
            backup_files.sort(reverse=True)  # Most recent first
            
            # Remove old backups (keep only 20 per type)
            for old_backup in backup_files[20:]:
                old_path = os.path.join(self.backup_dir, old_backup)
                os.remove(old_path)
                self.logger.debug(f"🗑️ Removed old backup: {old_backup}")
                
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to cleanup old backups for {file_type}: {e}")
    
    def get_position_health_status(self) -> Dict[str, Any]:
        """Get comprehensive health status of position storage system"""
        status = {
            'timestamp': datetime.now().isoformat(),
            'storage_files': {},
            'backup_info': {},
            'health_score': 0,
            'issues': [],
            'recommendations': []
        }
        
        try:
            # Check main storage files
            files_to_check = [
                (self.storage_file, "main"),
                (self.backup_file, "backup"),
                (self.emergency_file, "emergency")
            ]
            
            healthy_files = 0
            
            for file_path, file_type in files_to_check:
                file_info = {
                    'exists': os.path.exists(file_path),
                    'size': 0,
                    'modified': None,
                    'readable': False,
                    'valid_json': False
                }
                
                if file_info['exists']:
                    try:
                        stat = os.stat(file_path)
                        file_info['size'] = stat.st_size
                        file_info['modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                        
                        # Test readability and JSON validity
                        with open(file_path, 'r') as f:
                            data = json.load(f)
                            file_info['readable'] = True
                            file_info['valid_json'] = True
                            file_info['user_count'] = len(data)
                            file_info['position_count'] = sum(
                                len(user_data.get('positions', {})) 
                                for user_data in data.values() 
                                if isinstance(user_data, dict)
                            )
                            healthy_files += 1
                            
                    except json.JSONDecodeError:
                        file_info['readable'] = True
                        file_info['valid_json'] = False
                        status['issues'].append(f"{file_type} file exists but contains invalid JSON")
                    except Exception as e:
                        status['issues'].append(f"{file_type} file error: {str(e)}")
                else:
                    status['issues'].append(f"{file_type} file missing")
                
                status['storage_files'][file_type] = file_info
            
            # Check backup directory
            if os.path.exists(self.backup_dir):
                backup_files = [f for f in os.listdir(self.backup_dir) if f.endswith('.json')]
                status['backup_info'] = {
                    'backup_count': len(backup_files),
                    'latest_backup': max(backup_files, key=lambda f: os.path.getmtime(os.path.join(self.backup_dir, f))) if backup_files else None
                }
            else:
                status['backup_info'] = {'backup_count': 0, 'latest_backup': None}
                status['issues'].append("Backup directory missing")
            
            # Calculate health score (0-100)
            status['health_score'] = min(100, (healthy_files / 3) * 100)
            
            # Add recommendations based on health
            if status['health_score'] < 50:
                status['recommendations'].append("CRITICAL: Multiple storage files missing or corrupted")
            elif status['health_score'] < 80:
                status['recommendations'].append("WARNING: Some redundancy lost, check backup files")
            else:
                status['recommendations'].append("Position storage system healthy")
            
            return status
            
        except Exception as e:
            status['issues'].append(f"Health check error: {str(e)}")
            status['health_score'] = 0
            return status
    
    def _migrate_position_format(self, position: Dict) -> Dict:
        """Migrate old position format to new format with enhanced error handling"""
        try:
            # If position already has 'market' key, it's already in new format
            if 'market' in position:
                # Validate the market structure
                market = position['market']
                if not isinstance(market, dict) or 'id' not in market:
                    self.logger.warning("⚠️ Position has invalid market structure, attempting repair")
                    position['market'] = {
                        'id': position.get('market_id', 'unknown'),
                        'question': position.get('question', 'Unknown Market'),
                        'volume': market.get('volume', 0) if isinstance(market, dict) else 0
                    }
                return position
            
            # Old format migration - create minimal market object
            migrated_position = position.copy()
            
            # Create a minimal market object if missing
            if 'market' not in migrated_position:
                migrated_position['market'] = {
                    'id': migrated_position.get('market_id', 'unknown'),
                    'question': migrated_position.get('question', 'Unknown Market'),
                    'volume': migrated_position.get('volume', 0)
                }
            
            # Ensure required fields exist with defaults
            required_fields = {
                'buy_price': migrated_position.get('avg_price', 0.5),
                'total_cost': migrated_position.get('total_cost', 0),
                'tokens': migrated_position.get('tokens', 0),
                'outcome': migrated_position.get('outcome', 'unknown'),
                'token_id': migrated_position.get('token_id', None),
                'buy_time': migrated_position.get('timestamp', time.time())
            }
            
            for field, default_value in required_fields.items():
                if field not in migrated_position:
                    migrated_position[field] = default_value
            
            self.logger.debug(f"🔄 Migrated position for market {migrated_position.get('market_id', 'unknown')}")
            return migrated_position
            
        except Exception as e:
            self.logger.error(f"❌ Failed to migrate position: {e}")
            # Return position as-is if migration fails, with minimal required fields
            fallback_position = position.copy()
            if 'market' not in fallback_position:
                fallback_position['market'] = {
                    'id': 'migration_failed',
                    'question': 'Position Migration Failed',
                    'volume': 0
                }
            return fallback_position
    
    def create_manual_backup(self) -> Optional[str]:
        """Create a manual backup with 'manual' prefix"""
        try:
            # Check if any position files exist to backup
            files_to_backup = [
                (self.storage_file, "main"),
                (self.backup_file, "backup"),
                (self.emergency_file, "emergency")
            ]
            
            backup_created = False
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            for file_path, file_type in files_to_backup:
                if os.path.exists(file_path):
                    backup_name = f"manual_{file_type}_backup_{timestamp}.json"
                    backup_path = os.path.join(self.backup_dir, backup_name)
                    shutil.copy2(file_path, backup_path)
                    self.logger.info(f"📁 Manual backup created: {backup_name}")
                    backup_created = True
            
            if backup_created:
                return f"manual_backup_{timestamp}"
            else:
                self.logger.warning("⚠️ No position files found to backup")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Failed to create manual backup: {e}")
            return None
    
    def get_file_info(self) -> Dict[str, Any]:
        """Get comprehensive information about position storage files"""
        info = {
            'main_file': self.storage_file,
            'main_exists': os.path.exists(self.storage_file),
            'main_size': 0,
            'main_modified': None,
            'backup_file': self.backup_file,
            'backup_exists': os.path.exists(self.backup_file),
            'backup_size': 0,
            'backup_modified': None,
            'emergency_file': self.emergency_file,
            'emergency_exists': os.path.exists(self.emergency_file),
            'emergency_size': 0,
            'emergency_modified': None,
            'backup_count': 0,
            'latest_backup': None,
            'total_storage_used': 0
        }
        
        try:
            # Check main file
            if info['main_exists']:
                stat = os.stat(self.storage_file)
                info['main_size'] = stat.st_size
                info['main_modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                info['total_storage_used'] += stat.st_size
            
            # Check backup file
            if info['backup_exists']:
                stat = os.stat(self.backup_file)
                info['backup_size'] = stat.st_size
                info['backup_modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                info['total_storage_used'] += stat.st_size
            
            # Check emergency file
            if info['emergency_exists']:
                stat = os.stat(self.emergency_file)
                info['emergency_size'] = stat.st_size
                info['emergency_modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                info['total_storage_used'] += stat.st_size
            
            # Count timestamped backups
            if os.path.exists(self.backup_dir):
                backup_files = [f for f in os.listdir(self.backup_dir) if f.endswith('.json')]
                info['backup_count'] = len(backup_files)
                
                if backup_files:
                    # Get latest backup by modification time
                    latest_backup = max(backup_files, 
                                      key=lambda f: os.path.getmtime(os.path.join(self.backup_dir, f)))
                    info['latest_backup'] = latest_backup
                    
                    # Calculate total backup storage
                    backup_storage = sum(
                        os.path.getsize(os.path.join(self.backup_dir, f)) 
                        for f in backup_files
                    )
                    info['total_storage_used'] += backup_storage
                    info['backup_storage_used'] = backup_storage
                    
        except Exception as e:
            self.logger.error(f"❌ Error getting file info: {e}")
            info['error'] = str(e)
        
        return info
    
    def recover_positions_from_blockchain(self, user_id: int, wallet_address: str) -> Dict[str, Dict]:
        """
        Recover positions by scanning blockchain transactions
        This is a fallback when position files are lost
        """
        self.logger.info(f"🔍 Starting blockchain position recovery for user {user_id}")
        
        try:
            # This is a placeholder for blockchain scanning functionality
            # In a full implementation, this would:
            # 1. Connect to Polygon RPC
            # 2. Scan wallet transactions for Polymarket trades
            # 3. Parse trade events to reconstruct positions
            # 4. Cross-reference with current market prices
            
            recovered_positions = {}
            
            # For now, we'll implement a basic recovery system
            # that could be extended with actual blockchain scanning
            
            self.logger.warning("🚧 Blockchain recovery not fully implemented yet")
            self.logger.warning("🚧 This would scan Polygon blockchain for Polymarket transactions")
            self.logger.warning("🚧 And reconstruct positions from trade history")
            
            # Placeholder recovery data structure
            # In real implementation, this would come from blockchain scan
            recovery_info = {
                'method': 'blockchain_scan',
                'wallet_address': wallet_address,
                'scan_timestamp': time.time(),
                'positions_recovered': 0,
                'status': 'placeholder_implementation'
            }
            
            self.logger.info(f"📊 Blockchain recovery completed: {recovery_info}")
            return recovered_positions
            
        except Exception as e:
            self.logger.error(f"❌ Blockchain position recovery failed: {e}")
            return {}
    
    def emergency_position_recovery(self, user_id: int) -> Dict[str, Dict]:
        """
        Emergency position recovery using all available methods
        Called when all position files are lost or corrupted
        """
        self.logger.critical(f"🚨 EMERGENCY POSITION RECOVERY for user {user_id}")
        
        recovery_attempts = []
        recovered_positions = {}
        
        try:
            # Method 1: Try loading from any available backup files
            self.logger.info("🔄 Attempt 1: Backup file recovery")
            backup_positions = self._load_from_timestamped_backup()
            if backup_positions and user_id in backup_positions:
                user_positions = backup_positions[user_id].get('positions', {})
                if user_positions:
                    recovered_positions.update(user_positions)
                    recovery_attempts.append(f"✅ Recovered {len(user_positions)} positions from backup files")
                else:
                    recovery_attempts.append("❌ No positions found in backup files")
            else:
                recovery_attempts.append("❌ No backup files available or user not found")
            
            # Method 2: Try blockchain recovery (if wallet address available)
            try:
                from wallet_manager import wallet_manager
                wallet = wallet_manager.get_user_wallet(user_id)
                if wallet and 'address' in wallet:
                    self.logger.info("🔄 Attempt 2: Blockchain position recovery")
                    blockchain_positions = self.recover_positions_from_blockchain(user_id, wallet['address'])
                    if blockchain_positions:
                        recovered_positions.update(blockchain_positions)
                        recovery_attempts.append(f"✅ Recovered {len(blockchain_positions)} positions from blockchain")
                    else:
                        recovery_attempts.append("❌ No positions found on blockchain")
                else:
                    recovery_attempts.append("❌ No wallet address available for blockchain scan")
            except Exception as e:
                recovery_attempts.append(f"❌ Blockchain recovery failed: {str(e)}")
            
            # Method 3: Check if user has any manual position data
            # This could be extended to check external APIs, user input, etc.
            
            # Log recovery results
            total_recovered = len(recovered_positions)
            self.logger.critical(f"🏥 EMERGENCY RECOVERY COMPLETE:")
            self.logger.critical(f"   - Total positions recovered: {total_recovered}")
            
            for attempt in recovery_attempts:
                self.logger.info(f"   {attempt}")
            
            if total_recovered > 0:
                # Save recovered positions immediately
                user_sessions = {user_id: {'positions': recovered_positions}}
                self.save_positions(user_sessions)
                self.logger.critical("✅ Recovered positions saved to all storage files")
            else:
                self.logger.critical("❌ CRITICAL: No positions could be recovered!")
                self.logger.critical("❌ User may have lost position data permanently")
            
            return recovered_positions
            
        except Exception as e:
            self.logger.critical(f"❌ EMERGENCY RECOVERY FAILED: {e}")
            return {}
    
    def verify_position_integrity(self, user_sessions: Dict[int, Dict]) -> Dict[str, Any]:
        """
        Verify the integrity of position data and detect potential issues
        """
        self.logger.info("🔍 Starting position integrity verification...")
        
        verification_report = {
            'timestamp': datetime.now().isoformat(),
            'total_users': len(user_sessions),
            'total_positions': 0,
            'issues_found': [],
            'warnings': [],
            'users_verified': {},
            'integrity_score': 100
        }
        
        try:
            for user_id, session in user_sessions.items():
                user_report = {
                    'user_id': user_id,
                    'position_count': 0,
                    'issues': [],
                    'warnings': []
                }
                
                if 'positions' not in session:
                    user_report['issues'].append("No positions key in session")
                    verification_report['issues_found'].append(f"User {user_id}: Missing positions key")
                    continue
                
                positions = session['positions']
                user_report['position_count'] = len(positions)
                verification_report['total_positions'] += len(positions)
                
                # Verify each position
                for market_id, position in positions.items():
                    # Check required fields
                    required_fields = ['outcome', 'tokens', 'buy_price', 'total_cost', 'market']
                    for field in required_fields:
                        if field not in position:
                            issue = f"Position {market_id} missing required field: {field}"
                            user_report['issues'].append(issue)
                            verification_report['issues_found'].append(f"User {user_id}: {issue}")
                    
                    # Check data types and ranges
                    if 'tokens' in position:
                        try:
                            tokens = float(position['tokens'])
                            if tokens <= 0:
                                warning = f"Position {market_id} has invalid token count: {tokens}"
                                user_report['warnings'].append(warning)
                                verification_report['warnings'].append(f"User {user_id}: {warning}")
                        except (ValueError, TypeError):
                            issue = f"Position {market_id} has invalid tokens value: {position['tokens']}"
                            user_report['issues'].append(issue)
                            verification_report['issues_found'].append(f"User {user_id}: {issue}")
                    
                    # Check market data integrity
                    if 'market' in position:
                        market = position['market']
                        if not isinstance(market, dict) or 'id' not in market:
                            issue = f"Position {market_id} has invalid market data"
                            user_report['issues'].append(issue)
                            verification_report['issues_found'].append(f"User {user_id}: {issue}")
                
                verification_report['users_verified'][str(user_id)] = user_report
            
            # Calculate integrity score
            total_issues = len(verification_report['issues_found'])
            total_warnings = len(verification_report['warnings'])
            
            if total_issues == 0 and total_warnings == 0:
                verification_report['integrity_score'] = 100
            elif total_issues == 0:
                verification_report['integrity_score'] = max(80, 100 - (total_warnings * 5))
            else:
                verification_report['integrity_score'] = max(0, 100 - (total_issues * 20) - (total_warnings * 5))
            
            self.logger.info(f"✅ Position integrity verification complete:")
            self.logger.info(f"   - Users: {verification_report['total_users']}")
            self.logger.info(f"   - Positions: {verification_report['total_positions']}")
            self.logger.info(f"   - Issues: {total_issues}")
            self.logger.info(f"   - Warnings: {total_warnings}")
            self.logger.info(f"   - Integrity Score: {verification_report['integrity_score']}/100")
            
            return verification_report
            
        except Exception as e:
            self.logger.error(f"❌ Position integrity verification failed: {e}")
            verification_report['issues_found'].append(f"Verification error: {str(e)}")
            verification_report['integrity_score'] = 0
            return verification_report

# Global instance
position_persistence = PositionPersistence()
