"""
deBridge API Client
Handles quotes and transaction building for cross-chain bridges
Adapted from telegram-bot-v2 for new architecture
"""
import time
from typing import Dict, Optional
import requests

from .config import BridgeConfig
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class DeBridgeClient:
    """Client for deBridge cross-chain bridge API"""

    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None):
        """Initialize deBridge client"""
        self.api_url = api_url or BridgeConfig.DEBRIDGE_API_URL
        self.api_key = api_key or BridgeConfig.DEBRIDGE_API_KEY
        self.session = requests.Session()
        self.session.headers.update(BridgeConfig.get_debridge_headers())

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
                params['dstChainTokenOutAmount'] = 'auto'  # Let deBridge calculate

            logger.info(f"📊 Requesting quote from deBridge...")
            logger.info(f"   Source: {amount} on chain {src_chain_id}")
            logger.info(f"   Destination: chain {dst_chain_id}")

            # Retry logic
            max_retries = 3
            response = None
            last_error = None

            for attempt in range(max_retries):
                try:
                    logger.info(f"   Attempt {attempt + 1}/{max_retries}...")
                    response = self.session.get(endpoint, params=params, timeout=30)
                    response.raise_for_status()
                    logger.info(f"   ✅ Quote received successfully!")
                    break
                except (requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️ deBridge API error on attempt {attempt + 1}/{max_retries}: {e}")
                        logger.info(f"   Retrying in 3 seconds...")
                        time.sleep(3)
                        continue
                    else:
                        logger.error(f"❌ deBridge API failed after {max_retries} attempts: {e}")
                except Exception as e:
                    logger.error(f"❌ Unexpected deBridge API error: {e}")
                    last_error = e
                    break

            if response is None or last_error is not None:
                logger.error(f"❌ Failed to get deBridge quote: {last_error}")
                return None

            quote_data = response.json()

            # Parse and format quote
            dst_amount_expected = quote_data.get('estimation', {}).get('dstChainTokenOut', {}).get('amount', '0')
            dst_amount = quote_data.get('estimation', {}).get('dst_amount')
            if dst_amount:
                logger.info(f"   Using dst_amount: {dst_amount} (overriding dst_amount_expected: {dst_amount_expected})")
                dst_amount_expected = dst_amount

            quote = {
                'estimation': quote_data.get('estimation', {}),
                'fixed_fee': quote_data.get('fixedFee', {}),
                'src_amount': amount,
                'dst_amount_expected': dst_amount_expected,
                'refuel_amount': quote_data.get('estimation', {}).get('costsDetails', [{}])[0].get('payload', {}).get('refuelAmount', '0') if enable_refuel else '0',
                'timestamp': int(time.time()),
                'raw_response': quote_data
            }

            logger.info(f"✅ Quote received:")
            logger.info(f"   Input: {amount} lamports")
            logger.info(f"   Output: {quote['dst_amount_expected']} (raw)")

            return quote

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to get deBridge quote: {e}")
            if hasattr(e, 'response') and e.response is not None:
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
        Create an order using deBridge /order/create-tx endpoint
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

            endpoint = f"{self.api_url}/dln/order/create-tx"

            # Prepare query parameters
            params = {
                'srcChainId': quote.get('raw_response', {}).get('estimation', {}).get('srcChainTokenIn', {}).get('chainId'),
                'srcChainTokenIn': quote.get('raw_response', {}).get('estimation', {}).get('srcChainTokenIn', {}).get('address'),
                'srcChainTokenInAmount': quote.get('src_amount'),
                'dstChainId': quote.get('raw_response', {}).get('estimation', {}).get('dstChainTokenOut', {}).get('chainId'),
                'dstChainTokenOut': quote.get('raw_response', {}).get('estimation', {}).get('dstChainTokenOut', {}).get('address'),
                'dstChainTokenOutAmount': 'auto',
                'srcChainOrderAuthorityAddress': src_address,
                'dstChainOrderAuthorityAddress': dst_address,
                'dstChainTokenOutRecipient': dst_address,
                'prependOperatingExpenses': 'true',
                'affiliateFeePercent': '0',
                'srcChainPriorityLevel': 'aggressive',  # Request high priority fees
                'allowedTakeTokenSlippageBps': str(BridgeConfig.DEBRIDGE_SLIPPAGE_BPS),
                'allowedGiveTokenSlippageBps': str(BridgeConfig.DEBRIDGE_SLIPPAGE_BPS),
            }

            logger.info(f"   ⚙️ Slippage tolerance: {BridgeConfig.DEBRIDGE_SLIPPAGE_BPS} BPS ({BridgeConfig.DEBRIDGE_SLIPPAGE_BPS/100}%)")

            response = self.session.get(endpoint, params=params, timeout=20)
            response.raise_for_status()

            order_data = response.json()

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


# Global instance
_debridge_client: Optional[DeBridgeClient] = None


def get_debridge_client() -> DeBridgeClient:
    """Get or create DeBridgeClient instance"""
    global _debridge_client
    if _debridge_client is None:
        _debridge_client = DeBridgeClient()
    return _debridge_client
