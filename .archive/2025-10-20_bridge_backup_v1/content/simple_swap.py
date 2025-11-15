#!/usr/bin/env python3
"""Simple SOL -> USDC swap helper via Jupiter Lite API"""

import asyncio
import base64
import logging
from typing import Optional, Dict

import requests
from solders.hash import Hash as Blockhash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.transaction import VersionedTransaction

from .config import SOLANA_ADDRESS, SOLANA_PRIVATE_KEY
from .jupiter_client import SOL_MINT, USDC_MINT
from .solana_transaction import SolanaTransactionBuilder

logger = logging.getLogger(__name__)

JUPITER_LITE_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_LITE_SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"


class SimpleSolToUsdcSwap:
    """Minimal helper to perform SOL -> USDC swaps using Jupiter Lite API."""

    def __init__(self):
        self.solana_builder = SolanaTransactionBuilder()
        # No longer use global keys - each user has their own wallet
        logger.info("SimpleSolToUsdcSwap initialized (user wallets mode)")

    def _fetch_quote(self, amount_lamports: int, slippage_bps: int = 100) -> Dict:
        params = {
            "inputMint": SOL_MINT,
            "outputMint": USDC_MINT,
            "amount": str(amount_lamports),
            "slippageBps": str(slippage_bps),
        }

        logger.info("🔍 Requesting Jupiter Lite quote for %s lamports", amount_lamports)
        resp = requests.get(JUPITER_LITE_QUOTE_URL, params=params, timeout=10)
        resp.raise_for_status()
        quote = resp.json()

        if "outAmount" not in quote:
            raise ValueError(f"Quote response missing outAmount: {quote}")

        logger.info(
            "✅ Quote: %.6f SOL -> %.6f USDC (slippage %s bps)",
            amount_lamports / 1e9,
            int(quote["outAmount"]) / 1e6,
            slippage_bps,
        )
        return quote

    def _build_swap_tx(self, quote: Dict, solana_address: str, wrap_and_unwrap_sol: bool = True) -> Dict:
        payload = {
            "quoteResponse": quote,
            "userPublicKey": solana_address,
            "wrapAndUnwrapSol": wrap_and_unwrap_sol,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        }

        logger.info("🧱 Requesting Jupiter swap transaction (Lite API)...")
        resp = requests.post(JUPITER_LITE_SWAP_URL, json=payload, timeout=15)
        resp.raise_for_status()
        swap_payload = resp.json()

        if "swapTransaction" not in swap_payload:
            raise ValueError(f"Swap response missing swapTransaction: {swap_payload}")

        logger.info("✅ Received swap transaction from Jupiter Lite API")
        return swap_payload

    async def swap(self, amount_sol: float, solana_address: str, solana_private_key: str, slippage_bps: int = 100, check_balance: bool = True) -> Dict:
        """Execute a SOL -> USDC swap for a user's Solana wallet.

        Args:
            amount_sol: Amount of SOL to swap.
            solana_address: User's Solana address
            solana_private_key: User's Solana private key
            slippage_bps: Slippage tolerance in basis points (default 1%).
            check_balance: If True, verify sufficient balance before swapping.

        Returns:
            Dictionary with transaction signature and received amount.
        """

        if amount_sol <= 0:
            raise ValueError("amount_sol must be positive")

        amount_lamports = int(amount_sol * 1e9)

        # Check current balance if requested
        if check_balance:
            current_balance = await self.solana_builder.get_sol_balance(solana_address)
            logger.info(f"💰 Current SOL balance: {current_balance:.9f} SOL")

            if current_balance < amount_sol:
                raise ValueError(
                    f"Insufficient SOL balance: {current_balance:.6f} SOL < {amount_sol:.6f} SOL"
                )

        # STEP 1: Get quote
        quote = self._fetch_quote(amount_lamports, slippage_bps)

        # STEP 2: Get swap transaction from Jupiter
        swap_tx_payload = self._build_swap_tx(quote, solana_address)
        swap_tx_b64 = swap_tx_payload["swapTransaction"]

        # Extract fees from Jupiter response for logging
        signature_fee = swap_tx_payload.get("signatureFeeLamports", 5000)
        priority_fee = swap_tx_payload.get("prioritizationFeeLamports", 0)
        rent_fee = swap_tx_payload.get("rentFeeLamports", 0)

        total_fees_lamports = signature_fee + priority_fee + rent_fee
        total_fees_sol = total_fees_lamports / 1e9

        logger.info(f"💰 Jupiter transaction fees:")
        logger.info(f"   Signature: {signature_fee} lamports ({signature_fee/1e9:.9f} SOL)")
        logger.info(f"   Priority: {priority_fee} lamports ({priority_fee/1e9:.9f} SOL)")
        logger.info(f"   Rent: {rent_fee} lamports ({rent_fee/1e9:.9f} SOL)")
        logger.info(f"   Total fees: {total_fees_lamports} lamports ({total_fees_sol:.9f} SOL)")
        logger.info(f"   Total required: {amount_sol + total_fees_sol:.9f} SOL (swap + fees)")

        # Verify we have enough SOL for swap + fees
        if check_balance:
            current_balance = await self.solana_builder.get_sol_balance(solana_address)
            total_required = amount_sol + total_fees_sol

            if current_balance < total_required:
                raise ValueError(
                    f"Insufficient SOL for swap + fees:\n"
                    f"Balance: {current_balance:.6f} SOL\n"
                    f"Swap: {amount_sol:.6f} SOL\n"
                    f"Fees: {total_fees_sol:.6f} SOL\n"
                    f"Total needed: {total_required:.6f} SOL\n"
                    f"Missing: {(total_required - current_balance):.6f} SOL"
                )

        # STEP 3: Deserialize transaction
        swap_tx_bytes = base64.b64decode(swap_tx_b64)
        jupiter_tx = VersionedTransaction.from_bytes(swap_tx_bytes)

        logger.info("✍️ Jupiter transaction requires %s signature(s)", jupiter_tx.message.header.num_required_signatures)

        # STEP 4: Replace blockhash with fresh one to be safe
        fresh_blockhash = await self.solana_builder.get_recent_blockhash()
        if not fresh_blockhash:
            raise RuntimeError("Failed to retrieve fresh blockhash")

        # Create keypair from user's private key
        user_keypair = Keypair.from_base58_string(solana_private_key)

        new_message = MessageV0(
            header=jupiter_tx.message.header,
            account_keys=jupiter_tx.message.account_keys,
            recent_blockhash=Blockhash.from_string(fresh_blockhash),
            instructions=jupiter_tx.message.instructions,
            address_table_lookups=jupiter_tx.message.address_table_lookups,
        )

        signed_tx = VersionedTransaction(new_message, [user_keypair])
        signed_bytes = bytes(signed_tx)

        logger.info("📡 Broadcasting swap transaction (size: %s bytes)", len(signed_bytes))

        # STEP 5: Broadcast & confirm
        signature = await self.solana_builder.send_transaction(signed_bytes)
        if not signature:
            raise RuntimeError("Failed to broadcast swap transaction")

        # SIMPLE: Just confirm normally and ignore Custom(1) errors
        logger.info(f"⏳ Confirming swap transaction...")

        confirmed = await self.solana_builder.confirm_transaction(signature, timeout=30)

        if confirmed:
            logger.info(f"✅ Swap confirmed! Signature: {signature}")
        else:
            # Even if not confirmed in 30s, it might still succeed
            # We'll check with the USDC watcher
            logger.warning(f"⚠️ Swap not confirmed in 30s, but may still succeed")
            logger.warning(f"   Signature: {signature}")
            logger.warning(f"   Check: https://solscan.io/tx/{signature}")

        return {
            "signature": signature,
            "sol_amount": amount_sol,
            "usdc_estimate": int(quote["outAmount"]) / 1e6,
        }


# No longer create global instance - each user has their own wallet
# simple_swapper = SimpleSolToUsdcSwap()
