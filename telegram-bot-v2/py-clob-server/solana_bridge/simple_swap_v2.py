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
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.instruction import Instruction, AccountMeta
from solders.pubkey import Pubkey

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

    logger.info("   Jupiter transaction account keys (pre-modification):")
    for idx, key in enumerate(account_keys):
        markers = []
        if idx == 0:
            markers.append("fee payer")
        if key == Pubkey.from_string(solana_address):
            markers.append("user wallet")
        marker_str = f" ({', '.join(markers)})" if markers else ""
        logger.info(f"     [{idx}] {key}{marker_str}")

    # If not found, add it to account keys
    if compute_budget_index is None:
        account_keys.append(COMPUTE_BUDGET_PROGRAM)
        compute_budget_index = len(account_keys) - 1
        logger.info(f"   Added ComputeBudget program at index {compute_budget_index}")

    # Create compiled compute budget instructions
    from solders.instruction import CompiledInstruction

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

    # CRITICAL FIX: Remove-and-Prepend Pattern to avoid keypair-pubkey mismatch
    # Never insert instructions in the middle - this breaks transaction structure!
    existing_instructions = list(jupiter_tx.message.instructions)
    original_instruction_count = len(existing_instructions)

    # Count and remove ALL existing compute budget instructions
    compute_budget_removed = 0
    filtered_instructions = []

    for i, instruction in enumerate(existing_instructions):
        if instruction.program_id_index == compute_budget_index:
            # This is a compute budget instruction - remove it (we'll replace with our own)
            compute_budget_removed += 1
            if len(instruction.data) > 0:
                if instruction.data[0] == 2:  # SetComputeUnitLimit
                    logger.info(f"   Removed existing SetComputeUnitLimit at index {i}")
                elif instruction.data[0] == 3:  # SetComputeUnitPrice
                    logger.info(f"   Removed existing SetComputeUnitPrice at index {i}")
        else:
            # Keep non-compute-budget instructions
            filtered_instructions.append(instruction)

    logger.info(f"   Removed {compute_budget_removed} compute budget instructions, kept {len(filtered_instructions)} other instructions")

    # Always prepend our compute budget instructions (both limit and price)
    # This ensures proper ordering and prevents index shifting issues that cause keypair-pubkey mismatch
    enhanced_instructions = [limit_ix, price_ix] + filtered_instructions
    logger.info(f"   Prepended 2 new compute budget instructions, final instruction count: {len(enhanced_instructions)} (was {original_instruction_count})")

    # VERIFICATION: Log final instruction structure to ensure correctness
    logger.info(f"   Final instruction structure:")
    for i, inst in enumerate(enhanced_instructions[:5]):  # Log first 5 instructions
        if hasattr(inst, 'program_id_index') and inst.program_id_index == compute_budget_index:
            if len(inst.data) > 0 and inst.data[0] == 2:
                logger.info(f"     Instruction {i}: SetComputeUnitLimit (3M CU)")
            elif len(inst.data) > 0 and inst.data[0] == 3:
                logger.info(f"     Instruction {i}: SetComputeUnitPrice (200k microlamports/CU)")
        else:
            logger.info(f"     Instruction {i}: Other instruction")

    # CRITICAL FIX: Replace Jupiter's fee payer with user's wallet address
    keypair = Keypair.from_base58_string(solana_private_key)
    user_wallet_pubkey = keypair.pubkey()

    # Jupiter sometimes sets fee payer to a different account - we must fix this!
    original_fee_payer = account_keys[0] if account_keys else None

    logger.info(f"   Fee payer fix:")
    logger.info(f"   - Jupiter's fee payer: {original_fee_payer}")
    logger.info(f"   - User's wallet: {user_wallet_pubkey}")

    # Replace the fee payer with the user's wallet address
    if account_keys and len(account_keys) > 0:
        account_keys[0] = user_wallet_pubkey
        logger.info(f"   ✅ Replaced fee payer: {original_fee_payer} → {user_wallet_pubkey}")
    else:
        logger.error(f"   ❌ No account keys found in Jupiter transaction!")
        raise ValueError("Jupiter transaction has no account keys")

    # Verify the fix worked
    final_fee_payer = account_keys[0]
    user_wallet_indices = [idx for idx, key in enumerate(account_keys) if key == user_wallet_pubkey]
    logger.info(f"   - User wallet appears at indices: {user_wallet_indices}")
    if final_fee_payer != user_wallet_pubkey:
        logger.error(f"   ❌ Fee payer replacement failed: {final_fee_payer} != {user_wallet_pubkey}")
        raise ValueError(f"Failed to set correct fee payer: got {final_fee_payer}, expected {user_wallet_pubkey}")

    logger.info(f"   ✅ Fee payer successfully set to user's wallet: {user_wallet_pubkey}")

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
