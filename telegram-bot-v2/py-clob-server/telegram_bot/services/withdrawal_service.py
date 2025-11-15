#!/usr/bin/env python3
"""
Withdrawal Service
Handles SOL and USDC withdrawal execution
Includes rate limiting, gas estimation, transaction tracking
"""

import logging
import os
import asyncio
from typing import Tuple, Dict, Optional
from datetime import datetime, timedelta
from decimal import Decimal

# Solana imports
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction as SoldersTransaction
from solders.message import Message

# Ethereum/Polygon imports
from web3 import Web3
from eth_account import Account

# Database imports
from database import db_manager, Withdrawal

# Core services
from core.services import user_service

logger = logging.getLogger(__name__)

# Configuration
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"  # Fallback/default
SOLANA_WITHDRAWAL_RPC_URL = os.getenv('SOLANA_WITHDRAWAL_RPC_URL', SOLANA_RPC_URL)  # Helius RPC for withdrawals
WITHDRAWAL_RPC_URL = os.getenv('WITHDRAWAL_RPC_URL', 'https://polygon-rpc.com')  # Alchemy RPC for withdrawals
USDC_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon

# Rate limits
MAX_WITHDRAWALS_PER_DAY = 10
MAX_USD_VOLUME_PER_DAY = 1000.0
COOLDOWN_SECONDS = 60  # 1 minute between withdrawals

# Minimums
MIN_SOL_WITHDRAWAL = 0.01  # 0.01 SOL (~$2)
MIN_USDC_WITHDRAWAL = 5.0  # $5 USDC

# Gas limits
MAX_GAS_PRICE_GWEI = 300  # Max 300 gwei for Polygon (can spike during busy times)


class WithdrawalService:
    """
    Service for executing cryptocurrency withdrawals
    Supports: SOL (Solana) and USDC.e (Polygon)
    """
    
    def __init__(self):
        """Initialize withdrawal service"""
        # Import solana bridge transaction builder for SOL withdrawals
        try:
            from solana_bridge.solana_transaction import SolanaTransactionBuilder
            self.solana_builder = SolanaTransactionBuilder(SOLANA_WITHDRAWAL_RPC_URL)
            logger.info(f"✅ Solana builder initialized with RPC: {SOLANA_WITHDRAWAL_RPC_URL[:50]}...")
        except ImportError:
            logger.warning("⚠️ Solana bridge not available, SOL withdrawals disabled")
            self.solana_builder = None
        
        self.web3 = Web3(Web3.HTTPProvider(WITHDRAWAL_RPC_URL))
        logger.info("🔧 WithdrawalService initialized")
    
    # ========================================================================
    # Rate Limiting
    # ========================================================================
    
    def check_rate_limit(self, user_id: int) -> Tuple[bool, str]:
        """
        Check if user is within rate limits
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            (can_withdraw, message) - message explains limit if False
        """
        try:
            # Get withdrawals in last 24 hours
            with db_manager.get_session() as db:
                twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
                
                recent_withdrawals = db.query(Withdrawal).filter(
                    Withdrawal.user_id == user_id,
                    Withdrawal.created_at > twenty_four_hours_ago,
                    Withdrawal.status.in_(['pending', 'confirmed'])
                ).all()
                
                # Check count limit
                count = len(recent_withdrawals)
                if count >= MAX_WITHDRAWALS_PER_DAY:
                    hours_until_reset = 24 - (datetime.utcnow() - min(w.created_at for w in recent_withdrawals)).total_seconds() / 3600
                    return False, (
                        f"⚠️ **Rate Limit Reached**\n\n"
                        f"**Daily Limits:**\n"
                        f"• Max withdrawals: {MAX_WITHDRAWALS_PER_DAY} per day\n"
                        f"• Your count: {count}/{MAX_WITHDRAWALS_PER_DAY}\n\n"
                        f"This limit resets in: **{hours_until_reset:.1f} hours**\n\n"
                        f"💡 Security measure to protect your account."
                    )
                
                # Check volume limit
                total_usd = sum(float(w.estimated_usd_value or 0) for w in recent_withdrawals)
                if total_usd >= MAX_USD_VOLUME_PER_DAY:
                    return False, (
                        f"⚠️ **Daily Volume Limit Reached**\n\n"
                        f"**Daily Volume Limit:** ${MAX_USD_VOLUME_PER_DAY:,.2f}\n"
                        f"**Your volume today:** ${total_usd:,.2f}\n\n"
                        f"This limit resets in 24 hours.\n\n"
                        f"💡 For higher limits, contact support."
                    )
                
                # Check cooldown (most recent withdrawal)
                if recent_withdrawals:
                    most_recent = max(recent_withdrawals, key=lambda w: w.created_at)
                    seconds_since = (datetime.utcnow() - most_recent.created_at).total_seconds()
                    if seconds_since < COOLDOWN_SECONDS:
                        wait_seconds = int(COOLDOWN_SECONDS - seconds_since)
                        return False, (
                            f"⏳ **Cooldown Period**\n\n"
                            f"Please wait **{wait_seconds} seconds** before next withdrawal.\n\n"
                            f"💡 Security measure to prevent spam."
                        )
                
                # All checks passed!
                return True, ""
                
        except Exception as e:
            logger.error(f"❌ Error checking rate limit: {e}")
            return False, f"Error checking rate limit: {str(e)}"
    
    # ========================================================================
    # Database Logging
    # ========================================================================
    
    def log_withdrawal(
        self,
        user_id: int,
        network: str,
        token: str,
        amount: float,
        from_address: str,
        destination_address: str,
        status: str = 'pending',
        tx_hash: Optional[str] = None,
        gas_cost: Optional[float] = None,
        error_message: Optional[str] = None,
        estimated_usd_value: Optional[float] = None
    ) -> Optional[int]:
        """
        Log withdrawal to database
        
        Returns:
            withdrawal_id if successful, None otherwise
        """
        try:
            with db_manager.get_session() as db:
                withdrawal = Withdrawal(
                    user_id=user_id,
                    network=network,
                    token=token,
                    amount=Decimal(str(amount)),
                    gas_cost=Decimal(str(gas_cost)) if gas_cost else None,
                    from_address=from_address,
                    destination_address=destination_address,
                    tx_hash=tx_hash,
                    status=status,
                    error_message=error_message,
                    estimated_usd_value=Decimal(str(estimated_usd_value)) if estimated_usd_value else None
                )
                
                if status == 'pending':
                    withdrawal.created_at = datetime.utcnow()
                elif status == 'confirmed':
                    withdrawal.submitted_at = datetime.utcnow()
                    withdrawal.confirmed_at = datetime.utcnow()
                elif status == 'failed':
                    withdrawal.failed_at = datetime.utcnow()
                
                db.add(withdrawal)
                db.commit()
                db.refresh(withdrawal)
                
                logger.info(f"✅ Logged withdrawal {withdrawal.id} for user {user_id}")
                return withdrawal.id
                
        except Exception as e:
            logger.error(f"❌ Error logging withdrawal: {e}")
            return None
    
    def update_withdrawal_status(
        self,
        withdrawal_id: int,
        status: str,
        tx_hash: Optional[str] = None,
        gas_cost: Optional[float] = None,
        error_message: Optional[str] = None
    ) -> bool:
        """Update withdrawal status in database"""
        try:
            with db_manager.get_session() as db:
                withdrawal = db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).first()
                if not withdrawal:
                    logger.error(f"❌ Withdrawal {withdrawal_id} not found")
                    return False
                
                withdrawal.status = status
                if tx_hash:
                    withdrawal.tx_hash = tx_hash
                if gas_cost:
                    withdrawal.gas_cost = Decimal(str(gas_cost))
                if error_message:
                    withdrawal.error_message = error_message
                
                if status == 'pending':
                    withdrawal.submitted_at = datetime.utcnow()
                elif status == 'confirmed':
                    withdrawal.confirmed_at = datetime.utcnow()
                elif status == 'failed':
                    withdrawal.failed_at = datetime.utcnow()
                
                db.commit()
                logger.info(f"✅ Updated withdrawal {withdrawal_id} to status: {status}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error updating withdrawal status: {e}")
            return False
    
    # ========================================================================
    # Gas Estimation
    # ========================================================================
    
    def estimate_gas_sol(self) -> float:
        """
        Estimate gas cost for Solana transfer
        
        Returns:
            Gas cost in SOL
        """
        # Solana transfer costs ~0.000005 SOL (5000 lamports)
        return 0.000005
    
    def estimate_gas_polygon(self) -> Tuple[float, float]:
        """
        Estimate gas cost for Polygon USDC transfer
        
        Returns:
            (gas_cost_in_pol, gas_cost_in_usd)
        """
        try:
            # Get current gas price
            gas_price = self.web3.eth.gas_price
            
            # Cap at max gas price (safety)
            max_gas_price = self.web3.to_wei(MAX_GAS_PRICE_GWEI, 'gwei')
            if gas_price > max_gas_price:
                logger.warning(f"⚠️ Gas price {gas_price} exceeds max {max_gas_price}, capping")
                gas_price = max_gas_price
            
            # ERC-20 transfer typically costs ~45,000 gas
            estimated_gas_units = 45000
            
            # Calculate cost in wei, then convert to POL
            gas_cost_wei = gas_price * estimated_gas_units
            gas_cost_pol = self.web3.from_wei(gas_cost_wei, 'ether')
            
            # Estimate USD value (rough estimate, POL ~$1.50)
            gas_cost_usd = float(gas_cost_pol) * 1.5
            
            return float(gas_cost_pol), gas_cost_usd
            
        except Exception as e:
            logger.error(f"❌ Error estimating Polygon gas: {e}")
            # Return safe estimate
            return 0.002, 0.003
    
    # ========================================================================
    # SOL Withdrawal
    # ========================================================================
    
    async def withdraw_sol(
        self,
        user_id: int,
        amount: float,
        destination_address: str,
        estimated_usd_value: Optional[float] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Execute SOL withdrawal
        
        Args:
            user_id: Telegram user ID
            amount: Amount in SOL
            destination_address: Solana address to send to
            estimated_usd_value: Estimated USD value (for rate limiting)
            
        Returns:
            (success, message, tx_hash)
        """
        try:
            logger.info(f"🔄 Starting SOL withdrawal: {amount} SOL for user {user_id}")
            
            # Check if Solana builder is available
            if not self.solana_builder:
                return False, "❌ SOL withdrawals are temporarily unavailable", None
            
            # Check minimum
            if amount < MIN_SOL_WITHDRAWAL:
                return False, f"Minimum withdrawal is {MIN_SOL_WITHDRAWAL} SOL", None
            
            # Get user's Solana keypair
            keypair = user_service.get_solana_keypair(user_id)
            if not keypair:
                return False, "❌ Could not load Solana wallet", None
            
            from_address = str(keypair.pubkey())
            
            # CRITICAL: Verify the derived address matches the stored address
            stored_address = user_service.get_solana_address(user_id)
            logger.info(f"🔍 Address verification:")
            logger.info(f"   Stored address: {stored_address}")
            logger.info(f"   Derived from keypair: {from_address}")
            
            if stored_address != from_address:
                error_msg = (
                    f"❌ CRITICAL: Address mismatch!\n"
                    f"• Stored in DB: {stored_address}\n"
                    f"• Derived from private key: {from_address}\n\n"
                    f"This means the private key does not match the public address.\n"
                    f"Contact support immediately!"
                )
                logger.error(error_msg)
                return False, error_msg, None
            
            # Log to database (pending)
            withdrawal_id = self.log_withdrawal(
                user_id=user_id,
                network='SOL',
                token='SOL',
                amount=amount,
                from_address=from_address,
                destination_address=destination_address,
                status='pending',
                estimated_usd_value=estimated_usd_value
            )
            
            if not withdrawal_id:
                return False, "❌ Failed to log withdrawal", None
            
            logger.info("🔨 Building Solana transaction...")
            
            # ====================================================================
            # PRE-FLIGHT CHECK 1: Real-time SOL balance check
            # ====================================================================
            try:
                current_balance = await self.solana_builder.get_sol_balance(from_address)
                logger.info(f"💰 Current SOL balance: {current_balance:.9f} SOL")
            except Exception as e:
                error_msg = (
                    f"Failed to check SOL balance\n"
                    f"• Error: {str(e)}\n"
                    f"• This might be an RPC issue. Please try again in a moment.\n\n"
                    f"💡 If problem persists, contact support."
                )
                logger.error(f"❌ Balance check failed: {e}")
                self.update_withdrawal_status(withdrawal_id, 'failed', error_message=error_msg)
                return False, f"❌ {error_msg}", None
            
            # Reserve 0.001 SOL for transaction fee
            transaction_fee_reserve = 0.001
            required_balance = amount + transaction_fee_reserve
            
            if current_balance < required_balance:
                error_msg = (
                    f"Insufficient SOL balance!\n"
                    f"• Balance: {current_balance:.6f} SOL\n"
                    f"• Need: {required_balance:.6f} SOL (including {transaction_fee_reserve} SOL fee reserve)"
                )
                logger.error(f"❌ {error_msg}")
                self.update_withdrawal_status(withdrawal_id, 'failed', error_message=error_msg)
                return False, f"❌ {error_msg}", None
            
            # ====================================================================
            # BUILD TRANSACTION: Simple SOL transfer
            # ====================================================================
            
            # Convert SOL to lamports (1 SOL = 1e9 lamports)
            amount_lamports = int(amount * 1e9)
            
            # Create transfer instruction
            transfer_ix = transfer(
                TransferParams(
                    from_pubkey=keypair.pubkey(),
                    to_pubkey=Pubkey.from_string(destination_address),
                    lamports=amount_lamports
                )
            )
            
            # Get recent blockhash
            logger.info("🔄 Fetching recent blockhash...")
            blockhash_str = await self.solana_builder.get_recent_blockhash()
            if not blockhash_str:
                error_msg = "Failed to get recent blockhash"
                logger.error(f"❌ {error_msg}")
                self.update_withdrawal_status(withdrawal_id, 'failed', error_message=error_msg)
                return False, f"❌ {error_msg}", None
            
            from solders.hash import Hash as Blockhash
            recent_blockhash = Blockhash.from_string(blockhash_str)
            
            # Build message and transaction
            message = Message.new_with_blockhash(
                [transfer_ix],
                keypair.pubkey(),
                recent_blockhash
            )
            
            transaction = SoldersTransaction([keypair], message, recent_blockhash)
            transaction_bytes = bytes(transaction)
            
            logger.info(f"✅ Transaction built ({len(transaction_bytes)} bytes)")
            logger.info(f"💸 Sending {amount} SOL to {destination_address[:8]}...{destination_address[-8:]}")
            
            # ====================================================================
            # BROADCAST AND CONFIRM
            # ====================================================================
            
            self.update_withdrawal_status(withdrawal_id, 'pending')
            logger.info("📡 Broadcasting transaction to Solana network...")
            
            # Send transaction
            signature = await self.solana_builder.send_transaction(transaction_bytes)
            
            if not signature:
                error_msg = "Failed to broadcast transaction"
                logger.error(f"❌ {error_msg}")
                self.update_withdrawal_status(withdrawal_id, 'failed', error_message=error_msg)
                return False, f"❌ {error_msg}", None
            
            logger.info(f"✅ Transaction submitted: {signature}")
            logger.info("⏳ Waiting for confirmation (up to 60 seconds)...")
            
            # Confirm transaction (60 second timeout for busy Solana network)
            logger.info(f"🔍 [DIAGNOSTIC-WS] Calling solana_builder.confirm_transaction...")
            logger.info(f"🔍 [DIAGNOSTIC-WS] Signature: {signature}")
            logger.info(f"🔍 [DIAGNOSTIC-WS] Timeout: 60s")
            
            confirmed = await self.solana_builder.confirm_transaction(signature, timeout=60)
            
            logger.info(f"🔍 [DIAGNOSTIC-WS] confirm_transaction returned: {confirmed} (type: {type(confirmed)})")
            
            if confirmed:
                logger.info(f"🎉 Transaction confirmed: {signature}")
                
                # Update database
                self.update_withdrawal_status(
                    withdrawal_id,
                    'confirmed',
                    tx_hash=signature
                )
                
                # Ensure signature has proper format for Solscan
                solscan_url = f"https://solscan.io/tx/{signature}"
                
                success_message = (
                    f"✅ **Withdrawal Successful!** ✅\n\n"
                    f"💸 Sent: **{amount} SOL**\n"
                    f"📍 To: `{destination_address}`\n"
                    f"🔗 [View on Solscan]({solscan_url})\n\n"
                    f"Your SOL has been sent! 🎉"
                )
                
                return True, success_message, signature
            else:
                # Transaction may still be pending on-chain
                logger.info(f"🔍 [DIAGNOSTIC-WS] confirmed = False, entering else branch")
                logger.warning(f"⚠️ Confirmation timeout, but transaction was submitted: {signature}")
                
                self.update_withdrawal_status(
                    withdrawal_id,
                    'pending',
                    tx_hash=signature
                )
                
                solscan_url = f"https://solscan.io/tx/{signature}"
                
                pending_message = (
                    f"⏳ **Transaction Submitted**\n\n"
                    f"💸 Amount: **{amount} SOL**\n"
                    f"📍 To: `{destination_address}`\n\n"
                    f"⏱️ Confirmation is taking longer than expected.\n"
                    f"Your transaction was broadcast and may still be processing.\n\n"
                    f"🔗 [Check status on Solscan]({solscan_url})\n\n"
                    f"If it doesn't confirm in 2-3 minutes, please contact support."
                )
                
                return False, pending_message, signature
            
        except Exception as e:
            logger.error(f"❌ SOL withdrawal error: {e}")
            
            # Update database with failure
            if 'withdrawal_id' in locals():
                self.update_withdrawal_status(
                    withdrawal_id,
                    'failed',
                    error_message=str(e)
                )
            
            return False, f"❌ Withdrawal failed: {str(e)}", None
    
    # ========================================================================
    # USDC Withdrawal (Polygon)
    # ========================================================================
    
    def withdraw_usdc(
        self,
        user_id: int,
        amount: float,
        destination_address: str,
        estimated_usd_value: Optional[float] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Execute USDC.e withdrawal on Polygon
        
        Args:
            user_id: Telegram user ID
            amount: Amount in USDC.e
            destination_address: Ethereum/Polygon address to send to
            estimated_usd_value: Estimated USD value (for rate limiting)
            
        Returns:
            (success, message, tx_hash)
        """
        try:
            logger.info(f"🔄 Starting USDC withdrawal: {amount} USDC for user {user_id}")
            
            # Check minimum
            if amount < MIN_USDC_WITHDRAWAL:
                return False, f"Minimum withdrawal is ${MIN_USDC_WITHDRAWAL}", None
            
            # Get user's Polygon private key
            private_key = user_service.get_polygon_private_key(user_id)
            if not private_key:
                return False, "❌ Could not load Polygon wallet", None
            
            # Get user's address
            from_address = user_service.get_polygon_address(user_id)
            
            # CHECK BALANCE RIGHT BEFORE WITHDRAWAL (critical!)
            # Balance might have changed since conversation started
            usdc_contract_check = self.web3.eth.contract(
                address=Web3.to_checksum_address(USDC_TOKEN_ADDRESS),
                abi=[{
                    "constant": True,
                    "inputs": [{"name": "account", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function"
                }]
            )
            
            current_balance_raw = usdc_contract_check.functions.balanceOf(
                Web3.to_checksum_address(from_address)
            ).call()
            current_balance = current_balance_raw / 1_000_000  # USDC.e has 6 decimals
            
            logger.info(f"💰 Current USDC.e balance: {current_balance:.2f} (attempting to withdraw {amount:.2f})")
            
            if current_balance < amount:
                return False, (
                    f"❌ **Insufficient Balance**\n\n"
                    f"Current balance: ${current_balance:.2f}\n"
                    f"Requested: ${amount:.2f}\n"
                    f"Shortfall: ${(amount - current_balance):.2f}\n\n"
                    f"💡 Your balance may have changed since you started this withdrawal.\n"
                    f"Please try again with a lower amount."
                ), None
            
            # CHECK POL BALANCE FOR GAS (critical!)
            pol_balance_wei = self.web3.eth.get_balance(Web3.to_checksum_address(from_address))
            pol_balance = self.web3.from_wei(pol_balance_wei, 'ether')
            
            # Estimate gas cost: 45,000 gas * 100 gwei = 0.0045 POL
            estimated_gas_cost_pol = 0.0045
            
            logger.info(f"⛽ Current POL balance: {pol_balance:.6f} (need ~{estimated_gas_cost_pol} for gas)")
            
            if pol_balance < estimated_gas_cost_pol:
                return False, (
                    f"❌ **Insufficient Gas Balance**\n\n"
                    f"Current POL balance: {pol_balance:.6f} POL\n"
                    f"Required for gas: ~{estimated_gas_cost_pol} POL\n"
                    f"Shortfall: {(estimated_gas_cost_pol - pol_balance):.6f} POL\n\n"
                    f"💡 You need POL to pay for transaction gas fees.\n"
                    f"Please add POL to your wallet first."
                ), None
            
            # Log to database (pending)
            withdrawal_id = self.log_withdrawal(
                user_id=user_id,
                network='POLYGON',
                token='USDC.e',
                amount=amount,
                from_address=from_address,
                destination_address=destination_address,
                status='pending',
                estimated_usd_value=estimated_usd_value or amount
            )
            
            if not withdrawal_id:
                return False, "❌ Failed to log withdrawal", None
            
            # Build transaction
            logger.info(f"🔨 Building Polygon transaction...")
            
            # Load account from private key
            if private_key.startswith('0x'):
                private_key = private_key[2:]
            account = Account.from_key(private_key)
            
            # USDC.e has 6 decimals
            amount_in_smallest_unit = int(amount * 1_000_000)
            
            # ERC-20 transfer function signature
            # transfer(address to, uint256 amount)
            usdc_contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(USDC_TOKEN_ADDRESS),
                abi=[{
                    "constant": False,
                    "inputs": [
                        {"name": "to", "type": "address"},
                        {"name": "value", "type": "uint256"}
                    ],
                    "name": "transfer",
                    "outputs": [{"name": "", "type": "bool"}],
                    "type": "function"
                }]
            )
            
            # Estimate gas using actual estimation (more accurate than hardcoding)
            try:
                gas_estimate = usdc_contract.functions.transfer(
                    Web3.to_checksum_address(destination_address),
                    amount_in_smallest_unit
                ).estimate_gas({'from': account.address})
                
                # Add 20% buffer for safety
                gas_estimate = int(gas_estimate * 1.2)
                logger.info(f"📊 Estimated gas: {gas_estimate} (with 20% buffer)")
            except Exception as e:
                # If estimation fails, it means the transaction would revert!
                logger.error(f"❌ Gas estimation failed: {e}")
                return False, (
                    f"❌ **Transaction Would Fail**\n\n"
                    f"Pre-flight check failed: {str(e)}\n\n"
                    f"💡 Possible reasons:\n"
                    f"• Insufficient balance\n"
                    f"• Contract paused\n"
                    f"• Address blocked\n\n"
                    f"Please check your wallet and try again."
                ), None
            
            base_gas_price = self.web3.eth.gas_price
            
            # AGGRESSIVE boost: 50% + minimum 100 gwei for Polygon congestion
            # Polygon network has been very congested lately
            boosted_gas_price = int(base_gas_price * 1.5)  # 50% boost
            min_gas_price = self.web3.to_wei(100, 'gwei')  # Minimum 100 gwei
            gas_price = max(boosted_gas_price, min_gas_price)
            
            # Cap gas price for safety (but allow high gas during network congestion)
            max_gas_price = self.web3.to_wei(MAX_GAS_PRICE_GWEI, 'gwei')
            if gas_price > max_gas_price:
                logger.warning(f"⚠️ Gas price {gas_price} ({self.web3.from_wei(gas_price, 'gwei'):.2f} gwei) exceeds max {self.web3.from_wei(max_gas_price, 'gwei')} gwei, capping")
                gas_price = max_gas_price
            
            logger.info(f"⛽ Gas price: {self.web3.from_wei(gas_price, 'gwei'):.2f} gwei (base: {self.web3.from_wei(base_gas_price, 'gwei'):.2f} gwei, +50%, min 100 gwei)")
            
            # Get nonce (include pending transactions to avoid nonce conflicts)
            nonce = self.web3.eth.get_transaction_count(account.address, 'pending')
            logger.info(f"🔢 Using nonce: {nonce} (includes pending txs)")
            
            # Build transaction
            tx = usdc_contract.functions.transfer(
                Web3.to_checksum_address(destination_address),
                amount_in_smallest_unit
            ).build_transaction({
                'from': account.address,
                'gas': gas_estimate,
                'gasPrice': gas_price,
                'nonce': nonce,
                'chainId': 137  # Polygon mainnet
            })
            
            # Sign transaction
            logger.info(f"🔐 Signing transaction...")
            signed_tx = account.sign_transaction(tx)
            
            # Update status to pending (submitted)
            self.update_withdrawal_status(withdrawal_id, 'pending')
            
            # Broadcast transaction
            logger.info(f"📡 Broadcasting transaction to Polygon network...")
            # Use raw_transaction (web3.py v6+) or rawTransaction (web3.py v5)
            raw_tx = getattr(signed_tx, 'raw_transaction', None) or getattr(signed_tx, 'rawTransaction', None)
            if not raw_tx:
                raise Exception("Could not get raw transaction from signed transaction")
            
            tx_hash = self.web3.eth.send_raw_transaction(raw_tx)
            # Ensure 0x prefix is included for PolygonScan links
            tx_hash_hex = tx_hash.hex() if tx_hash.hex().startswith('0x') else f"0x{tx_hash.hex()}"
            
            logger.info(f"✅ Transaction submitted: {tx_hash_hex}")
            
            # Wait for confirmation (with timeout)
            # Polygon can be slow during congestion - allow up to 5 minutes
            logger.info(f"⏳ Waiting for confirmation (up to 5 minutes)...")
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            
            # Calculate actual gas cost
            gas_used = receipt['gasUsed']
            gas_cost_wei = gas_used * gas_price
            gas_cost_pol = self.web3.from_wei(gas_cost_wei, 'ether')
            
            # Check if transaction succeeded
            if receipt['status'] == 1:
                # Update database with success
                self.update_withdrawal_status(
                    withdrawal_id,
                    'confirmed',
                    tx_hash=tx_hash_hex,
                    gas_cost=float(gas_cost_pol)
                )
                
                logger.info(f"✅ USDC withdrawal successful: {tx_hash_hex}")
                return True, "✅ Withdrawal successful!", tx_hash_hex
            else:
                # Transaction reverted
                error_msg = "Transaction reverted on blockchain"
                self.update_withdrawal_status(
                    withdrawal_id,
                    'failed',
                    tx_hash=tx_hash_hex,
                    error_message=error_msg
                )
                return False, f"❌ {error_msg}", tx_hash_hex
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"❌ USDC withdrawal error: {e}")
            
            # Update database with failure
            if 'withdrawal_id' in locals():
                self.update_withdrawal_status(
                    withdrawal_id,
                    'failed',
                    error_message=error_str
                )
            
            # Check for common errors and provide helpful messages
            if 'ALREADY_EXISTS' in error_str or 'already known' in error_str.lower():
                return False, (
                    "⚠️ **Transaction Pending**\n\n"
                    "You have a pending withdrawal.\n"
                    "Please wait for it to confirm or be dropped (~24 hours).\n\n"
                    "Check your recent transactions on PolygonScan."
                ), None
            elif 'insufficient funds' in error_str.lower():
                return False, (
                    "❌ **Insufficient Gas**\n\n"
                    "You need more POL for gas fees.\n"
                    "Please add ~0.1 POL to your wallet."
                ), None
            elif 'not in the chain after' in error_str.lower():
                # Transaction was broadcast but not confirmed (timeout)
                tx_hash_for_msg = locals().get('tx_hash_hex', 'unknown')
                return False, (
                    "⏱️ **Transaction Timeout**\n\n"
                    "Your transaction was submitted but didn't confirm within 5 minutes.\n\n"
                    "🔍 **What this means:**\n"
                    "• Your transaction is in the mempool (pending)\n"
                    "• Polygon network is congested right now\n"
                    "• Gas price may have been too low\n\n"
                    "💡 **What to do:**\n"
                    "1. Check PolygonScan for your transaction status\n"
                    f"2. TX: `{tx_hash_for_msg}`\n"
                    "3. If it confirms, your withdrawal succeeded!\n"
                    "4. If it's stuck, wait 10-15 minutes then try again\n\n"
                    "⚠️ **Do NOT retry immediately** - you may create duplicate pending transactions"
                ), tx_hash_for_msg if tx_hash_for_msg != 'unknown' else None
            else:
                return False, f"❌ Withdrawal failed: {error_str}", None


# Global service instance
_withdrawal_service = None

def get_withdrawal_service() -> WithdrawalService:
    """Get global withdrawal service instance"""
    global _withdrawal_service
    if _withdrawal_service is None:
        _withdrawal_service = WithdrawalService()
    return _withdrawal_service

