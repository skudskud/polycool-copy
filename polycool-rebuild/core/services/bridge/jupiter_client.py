"""
Jupiter Client - SOL to USDC Swap
Handles swapping SOL to USDC on Solana via Jupiter Lite API
Adapted from simple_swap_v2.py for new architecture
"""
import asyncio
import base64
from typing import Dict, Optional
from solders.hash import Hash as Blockhash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from solders.instruction import CompiledInstruction
from solders.pubkey import Pubkey
import requests

from .config import BridgeConfig
from .solana_transaction import SolanaTransactionBuilder
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

JUPITER_LITE_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_LITE_SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"


class JupiterClient:
    """Jupiter swap client for SOL → USDC"""

    def __init__(self):
        """Initialize Jupiter client"""
        self.solana_builder = SolanaTransactionBuilder()

    async def swap_sol_to_usdc(
        self,
        solana_address: str,
        solana_private_key: str,
        amount_sol: float,
        slippage_bps: int = 100
    ) -> Dict:
        """
        Swap SOL to USDC for any user wallet

        Args:
            solana_address: User's Solana address
            solana_private_key: User's Solana private key (base58, decrypted)
            amount_sol: Amount of SOL to swap
            slippage_bps: Slippage tolerance in basis points (default: 100 = 1%)

        Returns:
            Dict with signature, sol_amount, and usdc_estimate

        Raises:
            ValueError: If amount_sol <= 0
            RuntimeError: If swap fails
        """
        if amount_sol <= 0:
            raise ValueError("amount_sol must be positive")

        amount_lamports = int(amount_sol * 1e9)

        # Step 1: Get quote
        logger.info(f"🔍 Jupiter quote for {amount_sol:.6f} SOL...")

        params = {
            "inputMint": BridgeConfig.SOL_MINT,
            "outputMint": BridgeConfig.USDC_MINT,
            "amount": str(amount_lamports),
            "slippageBps": str(slippage_bps),
        }

        resp = requests.get(JUPITER_LITE_QUOTE_URL, params=params, timeout=10)
        resp.raise_for_status()
        quote = resp.json()

        usdc_estimate = int(quote["outAmount"]) / 1e6
        logger.info(f"✅ Quote: {amount_sol:.6f} SOL → {usdc_estimate:.2f} USDC")

        # Step 2: Get swap transaction
        logger.info(f"🧱 Getting swap transaction...")

        payload = {
            'quoteResponse': quote,
            'userPublicKey': solana_address,
            'wrapAndUnwrapSol': True,
            'dynamicComputeUnitLimit': True,
            'prioritizationFeeLamports': 'auto'
        }

        resp = requests.post(JUPITER_LITE_SWAP_URL, json=payload, timeout=15)
        resp.raise_for_status()
        swap_payload = resp.json()

        swap_tx_b64 = swap_payload["swapTransaction"]

        # Step 3: Deserialize and replace blockhash
        swap_tx_bytes = base64.b64decode(swap_tx_b64)
        jupiter_tx = VersionedTransaction.from_bytes(swap_tx_bytes)

        logger.info(f"✍️ Jupiter transaction requires {jupiter_tx.message.header.num_required_signatures} signature(s)")

        # Get fresh blockhash
        fresh_blockhash_str = await self.solana_builder.get_recent_blockhash()
        if not fresh_blockhash_str:
            raise RuntimeError("Failed to get fresh blockhash")

        fresh_blockhash = Blockhash.from_string(fresh_blockhash_str)

        # Add/modify compute budget instructions for high CU limit (Jupiter needs ~3M CU)
        compute_unit_limit = 3000000  # 3M compute units for complex Jupiter swaps
        priority_fee_price = 200000   # 200k microlamports per CU (aggressive)

        logger.info(f"⚡ Setting compute budget: {compute_unit_limit} CU, {priority_fee_price} microlamports/CU")

        # Check if Compute Budget program is already in account keys
        COMPUTE_BUDGET_PROGRAM = Pubkey.from_string("ComputeBudget111111111111111111111111111111")

        account_keys = list(jupiter_tx.message.account_keys)
        compute_budget_index = None

        for i, key in enumerate(account_keys):
            if key == COMPUTE_BUDGET_PROGRAM:
                compute_budget_index = i
                break

        # If not found, add it to account keys
        if compute_budget_index is None:
            account_keys.append(COMPUTE_BUDGET_PROGRAM)
            compute_budget_index = len(account_keys) - 1
            logger.info(f"   Added ComputeBudget program at index {compute_budget_index}")

        # Create compiled compute budget instructions
        # SetComputeUnitLimit instruction (type 2)
        limit_data = bytes([2]) + compute_unit_limit.to_bytes(4, 'little')
        limit_ix = CompiledInstruction(
            program_id_index=compute_budget_index,
            accounts=bytes(),
            data=limit_data
        )

        # SetComputeUnitPrice instruction (type 3)
        price_data = bytes([3]) + priority_fee_price.to_bytes(8, 'little')
        price_ix = CompiledInstruction(
            program_id_index=compute_budget_index,
            accounts=bytes(),
            data=price_data
        )

        # Remove existing compute budget instructions and prepend new ones
        existing_instructions = list(jupiter_tx.message.instructions)
        filtered_instructions = []

        for instruction in existing_instructions:
            if instruction.program_id_index != compute_budget_index:
                filtered_instructions.append(instruction)

        # Prepend compute budget instructions
        enhanced_instructions = [limit_ix, price_ix] + filtered_instructions
        logger.info(f"   Prepended 2 compute budget instructions, total: {len(enhanced_instructions)}")

        # CRITICAL: Replace Jupiter's fee payer with user's wallet address
        keypair = Keypair.from_base58_string(solana_private_key)
        user_wallet_pubkey = keypair.pubkey()

        # Replace the fee payer with the user's wallet address
        if account_keys and len(account_keys) > 0:
            account_keys[0] = user_wallet_pubkey
            logger.info(f"   ✅ Set fee payer to user's wallet: {user_wallet_pubkey}")
        else:
            raise ValueError("Jupiter transaction has no account keys")

        # Verify the fix worked
        if account_keys[0] != user_wallet_pubkey:
            raise ValueError(f"Failed to set correct fee payer: got {account_keys[0]}, expected {user_wallet_pubkey}")

        # Rebuild message with fresh blockhash, enhanced account keys, and enhanced instructions
        new_message = MessageV0(
            header=jupiter_tx.message.header,
            account_keys=account_keys,
            recent_blockhash=fresh_blockhash,
            instructions=enhanced_instructions,
            address_table_lookups=jupiter_tx.message.address_table_lookups,
        )

        # Sign with user's keypair
        signed_tx = VersionedTransaction(new_message, [keypair])
        signed_bytes = bytes(signed_tx)

        logger.info(f"📡 Broadcasting swap ({len(signed_bytes)} bytes)...")

        # Step 4: Broadcast
        signature = await self.solana_builder.send_transaction(signed_bytes)
        if not signature:
            raise RuntimeError("Failed to broadcast")

        # Step 5: Quick confirm
        logger.info(f"⏳ Confirming...")
        confirmed = await self.solana_builder.confirm_transaction(signature, timeout=30)

        if confirmed:
            logger.info(f"✅ Swap confirmed! {signature}")
        else:
            logger.warning(f"⚠️ Swap not confirmed in 30s (may still succeed): {signature}")

        return {
            "signature": signature,
            "sol_amount": amount_sol,
            "usdc_estimate": usdc_estimate,
        }

    async def close(self):
        """Close Solana builder connection"""
        await self.solana_builder.close()


# Global instance
_jupiter_client: Optional[JupiterClient] = None


def get_jupiter_client() -> JupiterClient:
    """Get or create JupiterClient instance"""
    global _jupiter_client
    if _jupiter_client is None:
        _jupiter_client = JupiterClient()
    return _jupiter_client
