"""
Approval Service - Contract Approvals for Polymarket Trading
Handles automatic USDC.e and Conditional Token approvals
Adapted from telegram-bot-v2 for new architecture
"""
from typing import Dict, Optional, Tuple
from web3 import Web3
from eth_account import Account

from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Contract addresses from official Polymarket docs
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
CONDITIONAL_TOKEN_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"  # Conditional Tokens

# Exchange contracts to approve (from official docs)
EXCHANGE_CONTRACTS = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",  # Main exchange
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",  # Neg risk markets
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",  # Neg risk adapter
]

# ERC20 approve function ABI
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]

# ERC1155 approve function ABI (for conditional tokens)
ERC1155_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "operator", "type": "address"},
            {"name": "approved", "type": "bool"}
        ],
        "name": "setApprovalForAll",
        "outputs": [],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "operator", "type": "address"}
        ],
        "name": "isApprovedForAll",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }
]


class ApprovalService:
    """Manages contract approvals for Polymarket trading"""

    def __init__(self, rpc_url: Optional[str] = None):
        """Initialize approval service"""
        self.rpc_url = rpc_url or settings.web3.polygon_rpc_url
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        if not self.w3.is_connected():
            raise RuntimeError(f"Failed to connect to Polygon RPC: {self.rpc_url}")

        logger.info(f"✅ ApprovalService initialized")

    def check_usdc_e_approvals(self, wallet_address: str) -> Dict[str, bool]:
        """Check USDC.e approval status for all exchange contracts"""
        try:
            usdc_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(USDC_E_ADDRESS),
                abi=ERC20_ABI
            )

            approvals = {}
            for contract_address in EXCHANGE_CONTRACTS:
                try:
                    allowance = usdc_contract.functions.allowance(
                        Web3.to_checksum_address(wallet_address),
                        Web3.to_checksum_address(contract_address)
                    ).call()

                    # Consider approved if allowance > 0
                    approvals[contract_address] = allowance > 0

                except Exception as e:
                    logger.error(f"Error checking USDC.e approval for {contract_address}: {e}")
                    approvals[contract_address] = False

            return approvals

        except Exception as e:
            logger.error(f"Error checking USDC.e approvals: {e}")
            return {addr: False for addr in EXCHANGE_CONTRACTS}

    def check_conditional_token_approvals(self, wallet_address: str) -> Dict[str, bool]:
        """Check conditional token approval status for all exchange contracts"""
        try:
            ct_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(CONDITIONAL_TOKEN_ADDRESS),
                abi=ERC1155_ABI
            )

            approvals = {}
            for contract_address in EXCHANGE_CONTRACTS:
                try:
                    is_approved = ct_contract.functions.isApprovedForAll(
                        Web3.to_checksum_address(wallet_address),
                        Web3.to_checksum_address(contract_address)
                    ).call()

                    approvals[contract_address] = is_approved

                except Exception as e:
                    logger.error(f"Error checking CT approval for {contract_address}: {e}")
                    approvals[contract_address] = False

            return approvals

        except Exception as e:
            logger.error(f"Error checking conditional token approvals: {e}")
            return {addr: False for addr in EXCHANGE_CONTRACTS}

    def check_all_approvals(self, wallet_address: str) -> Dict:
        """Check all approval statuses for a wallet"""
        try:
            usdc_approvals = self.check_usdc_e_approvals(wallet_address)
            ct_approvals = self.check_conditional_token_approvals(wallet_address)

            usdc_ready = all(usdc_approvals.values())
            ct_ready = all(ct_approvals.values())
            all_ready = usdc_ready and ct_ready

            return {
                'usdc_approvals': usdc_approvals,
                'conditional_token_approvals': ct_approvals,
                'usdc_ready': usdc_ready,
                'ct_ready': ct_ready,
                'all_ready': all_ready,
                'total_contracts': len(EXCHANGE_CONTRACTS),
                'usdc_approved_count': sum(usdc_approvals.values()),
                'ct_approved_count': sum(ct_approvals.values())
            }

        except Exception as e:
            logger.error(f"Error checking all approvals: {e}")
            return {'error': str(e), 'all_ready': False}

    def approve_usdc_e_for_trading(self, private_key: str) -> Dict[str, bool]:
        """Approve USDC.e spending for all exchange contracts"""
        try:
            account = Account.from_key(private_key)
            wallet_address = account.address

            usdc_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(USDC_E_ADDRESS),
                abi=ERC20_ABI
            )

            # Maximum approval amount (2^256 - 1)
            max_approval = 2**256 - 1

            results = {}

            for contract_address in EXCHANGE_CONTRACTS:
                try:
                    # Check POL balance for gas fees
                    balance = self.w3.eth.get_balance(wallet_address)
                    gas_price = self.w3.eth.gas_price
                    estimated_gas_cost = gas_price * 100000  # Conservative gas estimate

                    if balance < estimated_gas_cost:
                        logger.error(f"Insufficient POL balance for gas. Need: {self.w3.from_wei(estimated_gas_cost, 'ether')} POL")
                        results[contract_address] = False
                        continue

                    # Build approval transaction
                    transaction = usdc_contract.functions.approve(
                        Web3.to_checksum_address(contract_address),
                        max_approval
                    ).build_transaction({
                        'from': wallet_address,
                        'gas': 100000,
                        'gasPrice': gas_price,
                        'nonce': self.w3.eth.get_transaction_count(wallet_address),
                        'chainId': 137
                    })

                    # Sign and send transaction
                    signed_txn = account.sign_transaction(transaction)
                    raw_tx = signed_txn.raw_transaction if hasattr(signed_txn, 'raw_transaction') else signed_txn.rawTransaction
                    tx_hash = self.w3.eth.send_raw_transaction(raw_tx)

                    # Wait for confirmation
                    receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                    results[contract_address] = receipt['status'] == 1

                    logger.info(f"USDC.e approval for {contract_address}: {'Success' if results[contract_address] else 'Failed'}")

                except Exception as e:
                    logger.error(f"Error approving USDC.e for {contract_address}: {e}")
                    results[contract_address] = False

            return results

        except Exception as e:
            logger.error(f"Error in USDC.e approval process: {e}")
            return {addr: False for addr in EXCHANGE_CONTRACTS}

    def approve_conditional_tokens_for_trading(self, private_key: str) -> Dict[str, bool]:
        """Approve conditional token spending for all exchange contracts"""
        try:
            account = Account.from_key(private_key)
            wallet_address = account.address

            ct_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(CONDITIONAL_TOKEN_ADDRESS),
                abi=ERC1155_ABI
            )

            results = {}

            for contract_address in EXCHANGE_CONTRACTS:
                try:
                    # Check POL balance for gas fees
                    balance = self.w3.eth.get_balance(wallet_address)
                    gas_price = self.w3.eth.gas_price
                    estimated_gas_cost = gas_price * 100000  # Conservative gas estimate

                    if balance < estimated_gas_cost:
                        logger.error(f"Insufficient POL balance for gas. Need: {self.w3.from_wei(estimated_gas_cost, 'ether')} POL")
                        results[contract_address] = False
                        continue

                    # Build approval transaction
                    transaction = ct_contract.functions.setApprovalForAll(
                        Web3.to_checksum_address(contract_address),
                        True
                    ).build_transaction({
                        'from': wallet_address,
                        'gas': 100000,
                        'gasPrice': gas_price,
                        'nonce': self.w3.eth.get_transaction_count(wallet_address),
                        'chainId': 137
                    })

                    # Sign and send transaction
                    signed_txn = account.sign_transaction(transaction)
                    raw_tx = signed_txn.raw_transaction if hasattr(signed_txn, 'raw_transaction') else signed_txn.rawTransaction
                    tx_hash = self.w3.eth.send_raw_transaction(raw_tx)

                    # Wait for confirmation
                    receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                    results[contract_address] = receipt['status'] == 1

                    logger.info(f"CT approval for {contract_address}: {'Success' if results[contract_address] else 'Failed'}")

                except Exception as e:
                    logger.error(f"Error approving CT for {contract_address}: {e}")
                    results[contract_address] = False

            return results

        except Exception as e:
            logger.error(f"Error in conditional token approval process: {e}")
            return {addr: False for addr in EXCHANGE_CONTRACTS}

    def approve_all_for_trading(self, private_key: str) -> Tuple[bool, Dict]:
        """Approve both USDC.e and conditional tokens for trading"""
        try:
            logger.info("Starting comprehensive approval process...")

            # Approve USDC.e
            usdc_results = self.approve_usdc_e_for_trading(private_key)
            usdc_success = all(usdc_results.values())

            # Approve Conditional Tokens
            ct_results = self.approve_conditional_tokens_for_trading(private_key)
            ct_success = all(ct_results.values())

            overall_success = usdc_success and ct_success

            results = {
                'usdc_approvals': usdc_results,
                'conditional_token_approvals': ct_results,
                'usdc_success': usdc_success,
                'ct_success': ct_success,
                'overall_success': overall_success
            }

            logger.info(f"Approval process completed. Success: {overall_success}")
            return overall_success, results

        except Exception as e:
            logger.error(f"Error in comprehensive approval process: {e}")
            return False, {'error': str(e)}


# Global instance
_approval_service: Optional[ApprovalService] = None


def get_approval_service() -> ApprovalService:
    """Get or create ApprovalService instance"""
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service

