#!/usr/bin/env python3
"""
Simple SOL -> USDC swap helper V2
Works with any user wallet (not singleton)
"""

import asyncio
import base64
import logging
from typing import Optional, Dict

import requests
from solders.hash import Hash as Blockhash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.transaction import VersionedTransaction

from .jupiter_client import SOL_MINT, USDC_MINT
from .solana_transaction import SolanaTransactionBuilder

logger = logging.getLogger(__name__)

JUPITER_LITE_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_LITE_SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"


async def swap_sol_to_usdc(
    solana_address: str,
    solana_private_key: str,
    amount_sol: float,
    slippage_bps: int = 100
) -> Dict:
    """
    Swap SOL to USDC for any user wallet

    Args:
        solana_address: User's Solana address
        solana_private_key: User's Solana private key (base58)
        amount_sol: Amount of SOL to swap
        slippage_bps: Slippage tolerance in basis points

    Returns:
        Dict with signature and usdc_estimate
    """

    if amount_sol <= 0:
        raise ValueError("amount_sol must be positive")

    amount_lamports = int(amount_sol * 1e9)

    # Step 1: Get quote
    logger.info(f"🔍 Jupiter quote for {amount_sol:.6f} SOL...")

    params = {
        "inputMint": SOL_MINT,
        "outputMint": USDC_MINT,
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
    solana_builder = SolanaTransactionBuilder()
    fresh_blockhash_str = await solana_builder.get_recent_blockhash()
    if not fresh_blockhash_str:
        raise RuntimeError("Failed to get fresh blockhash")

    fresh_blockhash = Blockhash.from_string(fresh_blockhash_str)

    # Rebuild message with fresh blockhash
    new_message = MessageV0(
        header=jupiter_tx.message.header,
        account_keys=jupiter_tx.message.account_keys,
        recent_blockhash=fresh_blockhash,
        instructions=jupiter_tx.message.instructions,
        address_table_lookups=jupiter_tx.message.address_table_lookups,
    )

    # Sign with user's keypair
    keypair = Keypair.from_base58_string(solana_private_key)
    signed_tx = VersionedTransaction(new_message, [keypair])
    signed_bytes = bytes(signed_tx)

    logger.info(f"📡 Broadcasting swap ({len(signed_bytes)} bytes)...")

    # Step 4: Broadcast
    signature = await solana_builder.send_transaction(signed_bytes)
    if not signature:
        raise RuntimeError("Failed to broadcast")

    # Step 5: Quick confirm
    logger.info(f"⏳ Confirming...")
    confirmed = await solana_builder.confirm_transaction(signature, timeout=30)

    if confirmed:
        logger.info(f"✅ Swap confirmed! {signature}")
    else:
        logger.warning(f"⚠️ Swap not confirmed in 30s (may still succeed): {signature}")

    return {
        "signature": signature,
        "sol_amount": amount_sol,
        "usdc_estimate": usdc_estimate,
    }
