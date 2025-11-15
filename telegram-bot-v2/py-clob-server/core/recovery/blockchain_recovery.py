"""
Blockchain Position Recovery System
Reads actual token balances directly from Polygon blockchain
"""

import logging
import requests
import time
from typing import Dict, List, Any, Optional
from web3 import Web3
from decimal import Decimal

logger = logging.getLogger(__name__)

class BlockchainPositionRecovery:
    """Recover positions by reading actual token balances from blockchain"""
    
    def __init__(self):
        # Polygon RPC endpoints
        self.rpc_endpoints = [
            "https://polygon-rpc.com",
            "https://rpc-mainnet.matic.network",
            "https://matic-mainnet.chainstacklabs.com"
        ]
        self.web3 = None
        self._init_web3()
        
        # ERC-1155 Contract ABI (for Polymarket tokens)
        self.erc1155_abi = [
            {
                "inputs": [
                    {"internalType": "address", "name": "account", "type": "address"},
                    {"internalType": "uint256", "name": "id", "type": "uint256"}
                ],
                "name": "balanceOf",
                "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        # Polymarket Conditional Tokens contract
        self.conditional_tokens_contract = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
        
    def _init_web3(self):
        """Initialize Web3 connection with fallback endpoints"""
        for endpoint in self.rpc_endpoints:
            try:
                web3 = Web3(Web3.HTTPProvider(endpoint))
                if web3.is_connected():
                    self.web3 = web3
                    logger.info(f"✅ Connected to Polygon via {endpoint}")
                    return
            except Exception as e:
                logger.warning(f"Failed to connect to {endpoint}: {e}")
                continue
        
        logger.error("❌ Failed to connect to any Polygon RPC endpoint")
        
    def get_token_balance(self, wallet_address: str, token_id: str) -> int:
        """Get actual token balance from blockchain"""
        if not self.web3:
            logger.error("❌ No Web3 connection available")
            return 0
            
        try:
            # Create contract instance
            contract = self.web3.eth.contract(
                address=self.conditional_tokens_contract,
                abi=self.erc1155_abi
            )
            
            # Convert addresses to checksum format
            wallet_address = Web3.to_checksum_address(wallet_address)
            token_id_int = int(token_id)
            
            # Call balanceOf function
            balance = contract.functions.balanceOf(wallet_address, token_id_int).call()
            
            logger.info(f"🔍 Token balance for {wallet_address[:10]}...{wallet_address[-4:]}: {balance} tokens (ID: {token_id})")
            return balance
            
        except Exception as e:
            logger.error(f"❌ Error getting token balance: {e}")
            return 0
    
    def get_polymarket_positions_from_api(self, wallet_address: str) -> List[Dict]:
        """
        Get REAL positions from Polymarket API - NO HARDCODING!
        This is the ULTIMATE dynamic approach.
        """
        logger.info(f"🔍 POLYMARKET API: Getting real positions for {wallet_address}")
        
        try:
            import requests
            
            # Official Polymarket API endpoint
            url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
            
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                positions_data = response.json()
                logger.info(f"✅ POLYMARKET API: Found {len(positions_data)} positions")
                
                for i, pos in enumerate(positions_data):
                    asset_id = pos.get('asset', 'unknown')  # Changed from 'asset_id' to 'asset'
                    size = pos.get('size', 0)
                    outcome = pos.get('outcome', 'unknown')
                    title = pos.get('title', 'Unknown Market')
                    logger.info(f"📊 Position {i+1}: {size} {outcome} tokens - {title[:50]}... (Asset: {asset_id})")
                
                return positions_data
            else:
                logger.warning(f"⚠️ POLYMARKET API: HTTP {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"❌ POLYMARKET API failed: {e}")
            return []
    
    def recover_from_polymarket_api(self, wallet_address: str) -> Dict[str, Dict]:
        """
        ULTIMATE DYNAMIC RECOVERY: Use Polymarket API to get real positions.
        NO HARDCODING - finds ALL positions automatically!
        """
        logger.info(f"🎯 ULTIMATE DYNAMIC RECOVERY: Using Polymarket API for {wallet_address}")
        
        # Get positions from Polymarket API
        api_positions = self.get_polymarket_positions_from_api(wallet_address)
        
        if not api_positions:
            logger.info("⚪ No positions found via Polymarket API")
            return {}
        
        recovered_positions = {}
        
        for pos in api_positions:
            try:
                asset_id = pos.get('asset')  # Changed from 'asset_id' to 'asset'
                size = float(pos.get('size', 0))
                outcome = pos.get('outcome', 'unknown')
                avg_price = float(pos.get('avgPrice', 0))  # Changed from 'avg_price' to 'avgPrice'
                title = pos.get('title', f"Market {asset_id}")
                
                if size <= 0:
                    continue
                
                # Create position entry with unique ID per position
                position_id = f"api_{asset_id}"
                
                recovered_positions[position_id] = {
                    'outcome': outcome.lower(),
                    'tokens': size,
                    'buy_price': avg_price,
                    'total_cost': size * avg_price,
                    'token_id': asset_id,
                    'market': {
                        'id': position_id,
                        'question': title,
                        'volume': pos.get('volume', 0)
                    },
                    'buy_time': time.time(),
                    'recovered_from_api': True,
                    'api_data': pos  # Store full API data
                }
                
                logger.info(f"✅ API POSITION: {size} {outcome} tokens at ${avg_price:.4f} - {title[:50]}...")
                
            except Exception as e:
                logger.error(f"❌ Error processing API position: {e}")
                logger.error(f"Position data: {pos}")
                continue
        
        logger.info(f"🎯 API RECOVERY COMPLETE: {len(recovered_positions)} positions")
        return recovered_positions

    def get_all_wallet_tokens(self, wallet_address: str) -> Dict[str, int]:
        """
        Get ALL ERC-1155 tokens in a wallet directly from blockchain.
        This is the ULTIMATE approach - no database comparison needed!
        """
        logger.info(f"🔍 DIRECT WALLET SCAN: Getting ALL tokens for {wallet_address}")
        
        # Unfortunately, ERC-1155 doesn't have a built-in way to enumerate all tokens
        # We need to use events or external APIs like PolygonScan
        
        # For now, let's use the known token IDs approach
        # TODO: Implement event log scanning or PolygonScan API integration
        
        known_tokens = {}
        
        # REMOVE HARDCODING: Try to get from Polymarket API first
        try:
            api_positions = self.get_polymarket_positions_from_api(wallet_address)
            
            for pos in api_positions:
                asset_id = pos.get('asset')  # Changed from 'asset_id' to 'asset'
                if asset_id:
                    try:
                        balance = self.get_token_balance(wallet_address, asset_id)
                        if balance > 0:
                            known_tokens[asset_id] = balance
                            logger.info(f"✅ API TOKEN: {balance} tokens for ID {asset_id}")
                    except Exception as e:
                        logger.error(f"❌ Error checking API token {asset_id}: {e}")
        
        except Exception as e:
            logger.error(f"❌ API token discovery failed: {e}")
        
        # FALLBACK: Your specific tokens from PolygonScan (temporary)
        if not known_tokens:
            logger.info("🔄 FALLBACK: Using known token IDs")
            specific_token_ids = [
                "105832362350788616148612362642992403996714020918558917275151746177525518770551",
                "37996229390440240146587017237938254706160177953974319874002048470954673333092"
            ]
            
            for token_id in specific_token_ids:
                try:
                    balance = self.get_token_balance(wallet_address, token_id)
                    if balance > 0:
                        known_tokens[token_id] = balance
                        logger.info(f"✅ FALLBACK TOKEN: {balance} tokens for ID {token_id[:20]}...")
                except Exception as e:
                    logger.error(f"❌ Error checking fallback token {token_id}: {e}")
        
        logger.info(f"🎯 WALLET SCAN COMPLETE: Found {len(known_tokens)} tokens")
        return known_tokens
    
    def recover_from_direct_wallet_scan(self, wallet_address: str) -> Dict[str, Dict]:
        """
        ULTIMATE RECOVERY: Scan wallet directly, no database needed!
        This is the most accurate approach.
        """
        logger.info(f"🎯 ULTIMATE RECOVERY: Direct wallet scan for {wallet_address}")
        
        # Get all tokens in wallet
        wallet_tokens = self.get_all_wallet_tokens(wallet_address)
        
        if not wallet_tokens:
            logger.info("⚪ No tokens found in direct wallet scan")
            return {}
        
        recovered_positions = {}
        
        for token_id, balance in wallet_tokens.items():
            # Create position even without market data
            position_id = f"token_{token_id[:20]}"
            
            recovered_positions[position_id] = {
                'outcome': 'unknown',  # We don't know YES/NO without market data
                'tokens': float(balance),
                'buy_price': 0.15,  # Estimate
                'total_cost': float(balance) * 0.15,
                'token_id': token_id,
                'market': {
                    'id': position_id,
                    'question': f"Polymarket Token ({token_id[:20]}...)",
                    'volume': 0
                },
                'buy_time': time.time(),
                'recovered_from_blockchain': True,
                'direct_wallet_scan': True
            }
            
            logger.info(f"✅ DIRECT POSITION: {balance} tokens for {token_id[:20]}...")
        
        logger.info(f"🎯 DIRECT RECOVERY COMPLETE: {len(recovered_positions)} positions")
        return recovered_positions
    
    def recover_specific_token_ids(self, wallet_address: str, token_ids: List[str], markets: List[Dict]) -> Dict[str, Dict]:
        
        recovered_positions = {}
        
        for token_id in token_ids:
            try:
                balance = self.get_token_balance(wallet_address, token_id)
                
                if balance > 0:
                    logger.info(f"✅ FOUND BALANCE: {balance} tokens for ID {token_id}")
                    
                    # Try to find matching market
                    matching_market = None
                    matching_outcome = "UNKNOWN"
                    
                    for market in markets:
                        clob_token_ids_str = market.get('clob_token_ids')
                        outcomes_str = market.get('outcomes')
                        
                        if not clob_token_ids_str or not outcomes_str:
                            continue
                        
                        try:
                            import ast
                            clob_token_ids = ast.literal_eval(clob_token_ids_str)
                            outcomes = ast.literal_eval(outcomes_str)
                            
                            if token_id in clob_token_ids:
                                token_index = clob_token_ids.index(token_id)
                                matching_market = market
                                matching_outcome = outcomes[token_index] if token_index < len(outcomes) else "UNKNOWN"
                                logger.info(f"🎯 MATCHED MARKET: {market['question'][:50]}... - {matching_outcome}")
                                break
                        except (ValueError, SyntaxError):
                            continue
                    
                    # Create position entry
                    if matching_market:
                        market_id = matching_market.get('id')
                        recovered_positions[market_id] = {
                            'outcome': matching_outcome.lower(),
                            'tokens': float(balance),
                            'buy_price': 0.15,  # Rough estimate - we can't know exact price from blockchain
                            'total_cost': float(balance) * 0.15,  # Estimate
                            'token_id': token_id,
                            'market': matching_market,
                            'buy_time': time.time(),
                            'recovered_from_blockchain': True
                        }
                        logger.info(f"✅ POSITION CREATED: {balance} {matching_outcome} tokens in {market['question'][:30]}...")
                    else:
                        # Create unknown market entry
                        unknown_market_id = f"unknown_{token_id[:20]}"
                        recovered_positions[unknown_market_id] = {
                            'outcome': 'unknown',
                            'tokens': float(balance),
                            'buy_price': 0.15,
                            'total_cost': float(balance) * 0.15,
                            'token_id': token_id,
                            'market': {
                                'id': unknown_market_id,
                                'question': f"Unknown Market (Token: {token_id[:20]}...)",
                                'volume': 0
                            },
                            'buy_time': time.time(),
                            'recovered_from_blockchain': True
                        }
                        logger.info(f"✅ UNKNOWN POSITION: {balance} tokens for unknown market")
                else:
                    logger.info(f"⚪ No balance for token ID: {token_id}")
                    
            except Exception as e:
                logger.error(f"❌ Error checking token {token_id}: {e}")
                continue
        
        logger.info(f"🎯 TARGETED RECOVERY COMPLETE: Found {len(recovered_positions)} positions")
        return recovered_positions

    def recover_all_positions(self, wallet_address: str, known_markets: List[Dict]) -> Dict[str, Dict]:
        """Recover all positions for a wallet by checking token balances"""
        logger.info(f"🔍 Starting blockchain position recovery for wallet {wallet_address}")
        
        # ULTIMATE APPROACH: Use Polymarket API (NO HARDCODING!)
        logger.info(f"🎯 ULTIMATE APPROACH: Polymarket API (dynamic discovery)")
        api_positions = self.recover_from_polymarket_api(wallet_address)
        
        if api_positions:
            logger.info(f"✅ SUCCESS: Found {len(api_positions)} positions via Polymarket API")
            return api_positions
        
        # FIRST FALLBACK: Direct wallet scan (uses API for token discovery)
        logger.info(f"🎯 FALLBACK 1: Direct wallet scan with API token discovery")
        direct_positions = self.recover_from_direct_wallet_scan(wallet_address)
        
        if direct_positions:
            logger.info(f"✅ SUCCESS: Found {len(direct_positions)} positions via direct wallet scan")
            return direct_positions
        
        # SECOND FALLBACK: Try specific known token IDs from PolygonScan (temporary)
        known_token_ids = [
            "105832362350788616148612362642992403996714020918558917275151746177525518770551",
            "37996229390440240146587017237938254706160177953974319874002048470954673333092"
        ]
        
        logger.info(f"🎯 FALLBACK 2: Checking {len(known_token_ids)} known token IDs from PolygonScan")
        targeted_positions = self.recover_specific_token_ids(wallet_address, known_token_ids, known_markets)
        
        if targeted_positions:
            logger.info(f"✅ SUCCESS: Found {len(targeted_positions)} positions via targeted recovery")
            return targeted_positions
        
        # THIRD FALLBACK: Original market-based recovery
        logger.info(f"🔄 FALLBACK 3: Market-based recovery ({len(known_markets)} markets)")
        recovered_positions = {}
        
        for market in known_markets:
            try:
                market_id = market['id']
                # FIXED: Use outcome-based token matching instead of array index
                # Polymarket API does NOT guarantee token ordering in clob_token_ids
                try:
                    from telegram_bot.utils.token_utils import get_both_token_ids
                    
                    yes_token_id, no_token_id = get_both_token_ids(market)
                    
                    if not yes_token_id or not no_token_id:
                        logger.warning(f"⚠️ Cannot get token IDs for market {market_id}, skipping")
                        continue
                        
                    logger.debug(f"🔍 TOKEN LOOKUP (RECOVERY): market={market.get('question', 'Unknown')[:50]}..., "
                                f"yes={yes_token_id[:20]}..., no={no_token_id[:20]}...")
                except Exception as e:
                    logger.error(f"❌ Token lookup failed for market {market_id}: {e}")
                    continue
                
                # Check balances for both YES and NO tokens
                yes_balance = self.get_token_balance(wallet_address, yes_token_id)
                no_balance = self.get_token_balance(wallet_address, no_token_id)
                
                # If user has any tokens, create position
                if yes_balance > 0:
                    recovered_positions[market_id] = {
                        'outcome': 'yes',
                        'tokens': float(yes_balance),
                        'token_id': yes_token_id,
                        'market': market,
                        'buy_price': 0.5,  # We don't know the buy price from blockchain
                        'total_cost': float(yes_balance) * 0.5,  # Estimate
                        'buy_time': time.time(),  # Current time as placeholder
                        'recovered_from_blockchain': True
                    }
                    logger.info(f"✅ Recovered YES position: {market['question'][:50]}... - {yes_balance} tokens")
                
                if no_balance > 0:
                    recovered_positions[market_id] = {
                        'outcome': 'no',
                        'tokens': float(no_balance),
                        'token_id': no_token_id,
                        'market': market,
                        'buy_price': 0.5,  # We don't know the buy price from blockchain
                        'total_cost': float(no_balance) * 0.5,  # Estimate
                        'buy_time': time.time(),  # Current time as placeholder
                        'recovered_from_blockchain': True
                    }
                    logger.info(f"✅ Recovered NO position: {market['question'][:50]}... - {no_balance} tokens")
                    
            except Exception as e:
                logger.error(f"❌ Error recovering position for market {market.get('id', 'unknown')}: {e}")
                continue
        
        logger.info(f"🎯 Blockchain recovery complete: Found {len(recovered_positions)} positions")
        return recovered_positions
    
    def get_polygonscan_transactions(self, wallet_address: str, limit: int = 100) -> List[Dict]:
        """Get recent transactions from PolygonScan API"""
        try:
            # PolygonScan API endpoint (you might need an API key for production)
            url = f"https://api.polygonscan.com/api"
            params = {
                'module': 'account',
                'action': 'txlist',
                'address': wallet_address,
                'startblock': 0,
                'endblock': 99999999,
                'page': 1,
                'offset': limit,
                'sort': 'desc'
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data['status'] == '1':
                    return data['result']
            
            logger.warning(f"⚠️ PolygonScan API response: {response.status_code}")
            return []
            
        except Exception as e:
            logger.error(f"❌ Error fetching PolygonScan transactions: {e}")
            return []

# Global instance
blockchain_recovery = BlockchainPositionRecovery()
