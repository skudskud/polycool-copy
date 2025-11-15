#!/usr/bin/env python3
"""
Jupiter Client
Handles direct SOL → USDC swaps on Solana
"""

import logging
import requests
from typing import Dict, Optional
from .config import DEBRIDGE_SLIPPAGE_BPS, JUPITER_API_KEY

logger = logging.getLogger(__name__)

# Jupiter Ultra API
# Ultra API uses a different endpoint structure than Swap API:
# - Lite (free): https://lite-api.jup.ag/ultra/v1
# - Dynamic (with API key): https://api.jup.ag/ultra/v1
# Ultra API endpoints: /order (get transaction) and /execute (submit)
JUPITER_LITE_API = "https://lite-api.jup.ag"
JUPITER_PREMIUM_API = "https://api.jup.ag"
JUPITER_ULTRA_VERSION = "v1"  # Ultra API uses v1, not v6!

# Token addresses on Solana
SOL_MINT = "So11111111111111111111111111111111111111112"  # Native SOL (wrapped)
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC on Solana


class JupiterClient:
    """Client for Jupiter DEX on Solana"""

    def __init__(self):
        self.session = requests.Session()

        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        # Always use Lite API for now (free and working!)
        # Premium API requires valid API key (currently not working with provided key)
        self.tier = 'lite'
        self.api_base = f"{JUPITER_LITE_API}/ultra/{JUPITER_ULTRA_VERSION}"
        logger.info("ℹ️ Using Jupiter Ultra Lite API (free, fully functional)")
        logger.info(f"   Endpoint: {self.api_base}")
        logger.info(f"   Rate limit: Sufficient for our usage")

        # Note: If you have a valid premium API key in the future:
        # Uncomment below and set JUPITER_API_KEY in .env
        # if JUPITER_API_KEY:
        #     self.tier = 'premium'
        #     self.api_base = f"{JUPITER_PREMIUM_API}/ultra/{JUPITER_ULTRA_VERSION}"
        #     params['apiKey'] = JUPITER_API_KEY

        self.session.headers.update(headers)

    def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        taker: str,
        slippage_bps: int = DEBRIDGE_SLIPPAGE_BPS
    ) -> Optional[Dict]:
        """
        Get a swap order from Jupiter Ultra API

        Args:
            input_mint: Input token mint address (e.g. SOL_MINT)
            output_mint: Output token mint address (e.g. USDC_MINT)
            amount: Amount in smallest unit (lamports for SOL, micro-USDC for USDC)
            taker: User's wallet address (REQUIRED for Ultra API)
            slippage_bps: Slippage tolerance in basis points (1000 = 10%)

        Returns:
            Order data or None if failed
        """
        try:
            logger.info(f"🔍 Getting Jupiter Ultra order...")
            logger.info(f"   Input: {amount} lamports {input_mint[:8]}...")
            logger.info(f"   Output: {output_mint[:8]}...")
            logger.info(f"   Taker: {taker[:16]}...")
            logger.info(f"   Slippage: {slippage_bps} BPS ({slippage_bps/100}%)")

            # Ultra API uses /order endpoint (not /quote)
            endpoint = f"{self.api_base}/order"

            params = {
                'inputMint': input_mint,
                'outputMint': output_mint,
                'amount': str(amount),
                'taker': taker,  # REQUIRED for Ultra API
                'slippageBps': str(slippage_bps)
            }

            # Note: Lite API doesn't need API key
            # If using premium in the future, add: params['apiKey'] = JUPITER_API_KEY

            logger.info(f"   Full URL: {endpoint}")
            logger.info(f"   Params: {list(params.keys())}")

            response = self.session.get(endpoint, params=params, timeout=15)

            logger.info(f"   Response status: {response.status_code}")
            logger.info(f"   Response text: {response.text[:200]}...")

            response.raise_for_status()

            quote_data = response.json()

            logger.info(f"✅ Jupiter quote received:")
            logger.info(f"   Input amount: {quote_data.get('inAmount')} ({amount / 1e9:.9f} SOL)")
            logger.info(f"   Output amount: {quote_data.get('outAmount')} ({int(quote_data.get('outAmount', 0)) / 1e6:.6f} USDC)")
            logger.info(f"   Price impact: {quote_data.get('priceImpactPct', 0)}%")
            logger.info(f"   Route: {len(quote_data.get('routePlan', []))} step(s)")

            return quote_data

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to get Jupiter quote: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   Status: {e.response.status_code}")
                logger.error(f"   Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Error in get_quote: {e}")
            return None

    def execute_order(
        self,
        signed_transaction: str,
        request_id: str
    ) -> Optional[Dict]:
        """
        Execute a signed Ultra API order

        Ultra API workflow:
        1. Call /order to get transaction + requestId
        2. Sign the transaction locally
        3. Call /execute to submit (Jupiter handles everything)

        Args:
            signed_transaction: Base64-encoded signed transaction
            request_id: Request ID from the order response

        Returns:
            Execute response with status and signature
        """
        try:
            logger.info(f"🚀 Executing Jupiter Ultra order...")
            logger.info(f"   Request ID: {request_id[:20]}...")

            endpoint = f"{self.api_base}/execute"

            payload = {
                'signedTransaction': signed_transaction,
                'requestId': request_id
            }

            response = self.session.post(endpoint, json=payload, timeout=30)
            response.raise_for_status()

            execute_data = response.json()

            status = execute_data.get('status')
            signature = execute_data.get('signature')

            if status == 'Success':
                logger.info(f"✅ Swap executed successfully!")
                logger.info(f"   Signature: {signature}")
                logger.info(f"   View on Solscan: https://solscan.io/tx/{signature}")
            else:
                logger.error(f"❌ Swap execution failed: {status}")
                logger.error(f"   Error: {execute_data.get('error')}")
                logger.error(f"   Code: {execute_data.get('code')}")
                if signature:
                    logger.error(f"   TX: https://solscan.io/tx/{signature}")

            return execute_data

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to execute order: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   Status: {e.response.status_code}")
                logger.error(f"   Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Error in execute_order: {e}")
            return None


# Singleton instance
jupiter_client = JupiterClient()
