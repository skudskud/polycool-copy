#!/usr/bin/env python3
"""
deBridge API Client
Handles quotes and transaction building for cross-chain bridges
"""

import logging
import requests
import time
from typing import Dict, Optional
from .config import (
    DEBRIDGE_API_URL,
    DEBRIDGE_API_KEY,
    SOLANA_CHAIN_ID,
    POLYGON_CHAIN_ID,
    SOL_TOKEN_ADDRESS,
    USDC_E_POLYGON,
    MAX_SLIPPAGE_PERCENT,
    DEBRIDGE_SLIPPAGE_BPS
)

logger = logging.getLogger(__name__)


class DeBridgeClient:
    """Client for deBridge cross-chain bridge API"""

    def __init__(self, api_url: str = DEBRIDGE_API_URL, api_key: str = DEBRIDGE_API_KEY):
        """Initialize deBridge client"""
        self.api_url = api_url
        self.api_key = api_key
        self.session = requests.Session()

        if api_key:
            self.session.headers.update({'Authorization': f'Bearer {api_key}'})

    def get_quote(
        self,
        src_chain_id: str,
        src_token: str,
        dst_chain_id: str,
        dst_token: str,
        amount: str,
        src_address: str,
        dst_address: str,
        enable_refuel: bool = True
    ) -> Optional[Dict]:
        """
        Get bridge quote from deBridge

        Args:
            src_chain_id: Source chain ID (e.g., Solana)
            src_token: Source token address
            dst_chain_id: Destination chain ID (e.g., Polygon)
            dst_token: Destination token address
            amount: Amount to bridge (in smallest units, e.g., lamports)
            src_address: Source wallet address
            dst_address: Destination wallet address
            enable_refuel: Whether to include gas refuel on destination

        Returns:
            Quote dictionary with fee breakdown and expected output
        """
        try:
            endpoint = f"{self.api_url}/dln/order/quote"

            params = {
                'srcChainId': src_chain_id,
                'srcChainTokenIn': src_token,
                'srcChainTokenInAmount': amount,
                'dstChainId': dst_chain_id,
                'dstChainTokenOut': dst_token,
                'affiliateFeePercent': '0',  # No affiliate fee
                'prependOperatingExpenses': 'true',
                'srcChainOrderAuthorityAddress': src_address,
                'dstChainTokenOutRecipient': dst_address,
            }

            # Add refuel if enabled
            if enable_refuel:
                # Request ~3 POL for gas (in wei)
                params['dstChainTokenOutAmount'] = 'auto'  # Let deBridge calculate

            logger.info(f"📊 Requesting quote from deBridge...")
            logger.info(f"   Source: {amount} on chain {src_chain_id}")
            logger.info(f"   Destination: chain {dst_chain_id}")

            # Try with longer timeout and retry if it fails
            max_retries = 3
            response = None
            last_error = None

            for attempt in range(max_retries):
                try:
                    logger.info(f"   Attempt {attempt + 1}/{max_retries}...")
                    response = self.session.get(endpoint, params=params, timeout=30)
                    response.raise_for_status()
                    logger.info(f"   ✅ Quote received successfully!")
                    break  # Success, exit retry loop
                except (requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️ deBridge API error on attempt {attempt + 1}/{max_retries}: {e}")
                        logger.info(f"   Retrying in 3 seconds...")
                        time.sleep(3)  # Wait 3 seconds before retry
                        continue
                    else:
                        logger.error(f"❌ deBridge API failed after {max_retries} attempts: {e}")
                except Exception as e:
                    logger.error(f"❌ Unexpected deBridge API error: {e}")
                    last_error = e
                    break  # Don't retry on unexpected errors

            # Check if we got a response
            if response is None or last_error is not None:
                logger.error(f"❌ Failed to get deBridge quote: {last_error}")
                return None

            quote_data = response.json()

            # DEBUG: Log structure de la réponse
            logger.info(f"🔍 deBridge quote response:")
            logger.info(f"   Keys: {list(quote_data.keys())}")
            if 'estimation' in quote_data:
                estimation = quote_data['estimation']
                logger.info(f"   Estimation available: {bool(estimation)}")
                if 'dstChainTokenOut' in estimation:
                    dst_token = estimation['dstChainTokenOut']
                    logger.info(f"   Destination token: {dst_token.get('symbol', 'unknown')}")
                    logger.info(f"   Estimated amount: {dst_token.get('amount', '0')}")

            # Parse and format quote
            quote = {
                'estimation': quote_data.get('estimation', {}),
                'fixed_fee': quote_data.get('fixedFee', {}),
                'src_amount': amount,
                'dst_amount_expected': quote_data.get('estimation', {}).get('dstChainTokenOut', {}).get('amount', '0'),
                'refuel_amount': quote_data.get('estimation', {}).get('costsDetails', [{}])[0].get('payload', {}).get('refuelAmount', '0') if enable_refuel else '0',
                'timestamp': int(time.time()),
                'raw_response': quote_data
            }

            logger.info(f"✅ Quote received:")
            logger.info(f"   Input: {amount} lamports")
            logger.info(f"   Output: {quote['dst_amount_expected']} (raw)")
            if enable_refuel:
                logger.info(f"   Refuel: {quote['refuel_amount']} wei (raw)")

            return quote

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to get deBridge quote: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"   Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Error in get_quote: {e}")
            return None

    def create_order(
        self,
        quote: Dict,
        src_address: str,
        dst_address: str
    ) -> Optional[Dict]:
        """
        Create an order using deBridge /order/create endpoint
        This returns the actual transaction data for Solana

        Args:
            quote: Quote from get_quote()
            src_address: Source Solana address
            dst_address: Destination Polygon address

        Returns:
            Order creation response with orderId and transaction data
        """
        try:
            logger.info(f"🔨 Creating deBridge order...")

            # Use the CORRECT endpoint: /dln/order/create-tx (GET with query params)
            endpoint = f"{self.api_url}/dln/order/create-tx"

            # Prepare query parameters (as per deBridge docs)
            params = {
                'srcChainId': quote.get('raw_response', {}).get('estimation', {}).get('srcChainTokenIn', {}).get('chainId'),
                'srcChainTokenIn': quote.get('raw_response', {}).get('estimation', {}).get('srcChainTokenIn', {}).get('address'),
                'srcChainTokenInAmount': quote.get('src_amount'),
                'dstChainId': quote.get('raw_response', {}).get('estimation', {}).get('dstChainTokenOut', {}).get('chainId'),
                'dstChainTokenOut': quote.get('raw_response', {}).get('estimation', {}).get('dstChainTokenOut', {}).get('address'),
                'dstChainTokenOutAmount': 'auto',  # Let deBridge calculate optimal amount
                'srcChainOrderAuthorityAddress': src_address,
                'dstChainOrderAuthorityAddress': dst_address,  # Must be user-controlled
                'dstChainTokenOutRecipient': dst_address,
                'prependOperatingExpenses': 'true',
                'affiliateFeePercent': '0',
                'srcChainPriorityLevel': 'aggressive',  # CRITICAL: Request high priority fees from deBridge!
                'allowedTakeTokenSlippageBps': str(DEBRIDGE_SLIPPAGE_BPS),  # Slippage pour AfterSwap (USDC→POL sur Polygon)
                'allowedGiveTokenSlippageBps': str(DEBRIDGE_SLIPPAGE_BPS),  # CRITICAL: Slippage pour PreSwap (SOL→USDC sur Solana)!
            }

            logger.info(f"   ⚙️ Slippage tolerance: {DEBRIDGE_SLIPPAGE_BPS} BPS ({DEBRIDGE_SLIPPAGE_BPS/100}%)")
            logger.info(f"   ⚙️ Applied to BOTH PreSwap (SOL→USDC) AND AfterSwap (USDC→POL)")

            logger.info(f"   Endpoint: {endpoint}")
            logger.info(f"   Params: {params}")

            # Use GET request with query parameters (as per deBridge docs)
            response = self.session.get(endpoint, params=params, timeout=20)
            response.raise_for_status()

            order_data = response.json()

            logger.info(f"🔍 DEBUG CREATE ORDER RESPONSE:")
            logger.info(f"   Keys: {list(order_data.keys())}")
            if 'tx' in order_data:
                logger.info(f"   tx keys: {list(order_data['tx'].keys())}")
                logger.info(f"   tx content: {order_data['tx']}")
            if 'orderId' in order_data:
                logger.info(f"   orderId: {order_data['orderId']}")

            logger.info(f"✅ Order created successfully!")
            logger.info(f"   Order ID: {order_data.get('orderId')}")

            return {
                'orderId': order_data.get('orderId'),
                'tx': order_data.get('tx', {}),
                'estimation': order_data.get('estimation', {}),
                'estimatedTransactionFee': order_data.get('estimatedTransactionFee', {}),
                'raw_response': order_data
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to create order: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   Status: {e.response.status_code}")
                logger.error(f"   Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Error in create_order: {e}")
            return None

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Get order status from deBridge API
        Docs: https://docs.debridge.finance/api-reference/dln/this-endpoint-returns-the-data-of-order

        Args:
            order_id: Order ID from create_order()

        Returns:
            Order status data
        """
        try:
            logger.info(f"📊 Fetching deBridge order status for {order_id[:20]}...")

            endpoint = f"{self.api_url}/dln/order/{order_id}"

            response = self.session.get(endpoint, timeout=10)
            response.raise_for_status()

            order_status = response.json()

            logger.info(f"✅ Order status received:")
            logger.info(f"   Status: {order_status.get('status')}")
            logger.info(f"   Full data: {order_status}")

            return order_status

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to get order status: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   Status: {e.response.status_code}")
                logger.error(f"   Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Error in get_order_status: {e}")
            return None

    def build_transaction(
        self,
        quote: Dict,
        src_address: str,
        recent_blockhash: str
    ) -> Optional[Dict]:
        """
        Build Solana transaction using quote data

        Args:
            quote: Quote from get_quote()
            src_address: Source Solana address
            recent_blockhash: Recent Solana blockhash

        Returns:
            Transaction data ready for signing
        """
        try:
            logger.info(f"🔨 Building transaction from quote...")
            logger.info(f"   Quote keys available: {list(quote.keys())}")

            # deBridge returns transaction data in the quote itself
            tx_data = quote.get('tx', {})
            logger.info(f"   tx_data found: {bool(tx_data)}")

            if tx_data:
                logger.info(f"   tx_data keys: {list(tx_data.keys())}")
            else:
                logger.warning("⚠️ No 'tx' key in quote!")
                logger.warning("   deBridge quote structure may be different for Solana")
                logger.warning("   Quote might need to be used differently for Solana transactions")

            if not tx_data:
                logger.error("❌ No transaction data in quote - cannot build transaction")
                logger.error("   This means deBridge API doesn't return ready-to-sign transaction for Solana")
                logger.error("   Need to investigate deBridge Solana integration documentation")
                return None

            # For Solana, deBridge typically returns serialized transaction
            # or instruction data that needs to be used with the blockhash
            transaction = {
                'data': tx_data.get('data'),
                'to': tx_data.get('to'),
                'value': tx_data.get('value', '0'),
                'blockhash': recent_blockhash,
                'from': src_address,
                'chainId': SOLANA_CHAIN_ID,
                'quote_id': quote.get('order', {}).get('orderId'),
                'timestamp': int(time.time())
            }

            logger.info(f"✅ Transaction built successfully")
            logger.info(f"   Order ID: {transaction['quote_id']}")

            return transaction

        except Exception as e:
            logger.error(f"❌ Error building transaction: {e}")
            return None

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Check status of a bridge order

        Args:
            order_id: Order ID from deBridge

        Returns:
            Order status information
        """
        try:
            endpoint = f"{self.api_url}/dln/order/{order_id}"

            response = self.session.get(endpoint, timeout=10)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            print(f"❌ Error checking order status: {e}")
            return None

    def estimate_sol_to_usdc(self, sol_amount: float) -> Optional[Dict]:
        """
        Quick estimation helper for SOL → USDC.e + POL refuel

        Args:
            sol_amount: Amount in SOL (e.g., 5.0)

        Returns:
            Estimated amounts
        """
        try:
            # Convert SOL to lamports (1 SOL = 1e9 lamports)
            lamports = int(sol_amount * 1_000_000_000)

            # Placeholder addresses for estimation
            dummy_src = "11111111111111111111111111111111"
            dummy_dst = "0x0000000000000000000000000000000000000001"

            quote = self.get_quote(
                src_chain_id=SOLANA_CHAIN_ID,
                src_token=SOL_TOKEN_ADDRESS,
                dst_chain_id=POLYGON_CHAIN_ID,
                dst_token=USDC_E_POLYGON,
                amount=str(lamports),
                src_address=dummy_src,
                dst_address=dummy_dst,
                enable_refuel=True
            )

            if not quote:
                return None

            # Convert amounts to human-readable
            usdc_amount = float(quote['dst_amount_expected']) / 1_000_000  # USDC has 6 decimals
            pol_refuel = float(quote['refuel_amount']) / 1_000_000_000_000_000_000  # POL has 18 decimals

            return {
                'sol_input': sol_amount,
                'usdc_output': usdc_amount,
                'pol_refuel': pol_refuel,
                'quote': quote
            }

        except Exception as e:
            print(f"❌ Error estimating SOL to USDC: {e}")
            return None


# Global deBridge client instance
debridge_client = DeBridgeClient()
