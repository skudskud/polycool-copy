import requests

from py_clob_client.clob_types import (
    DropNotificationParams,
    BalanceAllowanceParams,
    OrderScoringParams,
    OrdersScoringParams,
    TradeParams,
    OpenOrderParams,
)

from ..exceptions import PolyApiException

GET = "GET"
POST = "POST"
DELETE = "DELETE"
PUT = "PUT"


def overloadHeaders(method: str, headers: dict) -> dict:
    if headers is None:
        headers = dict()
    # Use a legitimate browser User-Agent to avoid Cloudflare bot protection
    headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

    headers["Accept"] = "*/*"
    headers["Connection"] = "keep-alive"
    headers["Content-Type"] = "application/json"

    if method == GET:
        headers["Accept-Encoding"] = "gzip"

    return headers


def request(endpoint: str, method: str, headers=None, data=None):
    try:
        headers = overloadHeaders(method, headers)

        # Retry logic with exponential backoff
        max_retries = 3
        timeout_sec = 30  # Increased from 15 to 30 seconds for slower connections

        for attempt in range(max_retries):
            try:
                import time
                start_time = time.time()
                resp = requests.request(
                    method=method, url=endpoint, headers=headers, json=data if data else None,
                    timeout=timeout_sec  # 30 second timeout
                )
                elapsed = time.time() - start_time

                if resp.status_code != 200:
                    raise PolyApiException(resp)

                try:
                    return resp.json()
                except requests.JSONDecodeError:
                    return resp.text

            except requests.Timeout as timeout_err:
                elapsed_str = f"{time.time() - start_time:.2f}s"
                if attempt < max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s
                    import time
                    wait_time = 2 ** attempt
                    print(f"⏱️ Request timeout ({elapsed_str}). Attempt {attempt+1}/{max_retries}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ Request timeout after {max_retries} attempts ({elapsed_str} total)")
                    raise timeout_err

    except requests.RequestException:
        raise PolyApiException(error_msg="Request exception!")


def post(endpoint, headers=None, data=None):
    return request(endpoint, POST, headers, data)


def get(endpoint, headers=None, data=None):
    return request(endpoint, GET, headers, data)


def delete(endpoint, headers=None, data=None):
    return request(endpoint, DELETE, headers, data)


def build_query_params(url: str, param: str, val: str) -> str:
    url_with_params = url
    last = url_with_params[-1]
    # if last character in url string == "?", append the param directly: api.com?param=value
    if last == "?":
        url_with_params = "{}{}={}".format(url_with_params, param, val)
    else:
        # else add "&", then append the param
        url_with_params = "{}&{}={}".format(url_with_params, param, val)
    return url_with_params


def add_query_trade_params(
    base_url: str, params: TradeParams = None, next_cursor="MA=="
) -> str:
    """
    Adds query parameters to a url
    """
    url = base_url
    if params:
        url = url + "?"
        if params.market:
            url = build_query_params(url, "market", params.market)
        if params.asset_id:
            url = build_query_params(url, "asset_id", params.asset_id)
        if params.after:
            url = build_query_params(url, "after", params.after)
        if params.before:
            url = build_query_params(url, "before", params.before)
        if params.maker_address:
            url = build_query_params(url, "maker_address", params.maker_address)
        if params.id:
            url = build_query_params(url, "id", params.id)
        if next_cursor:
            url = build_query_params(url, "next_cursor", next_cursor)
    return url


def add_query_open_orders_params(
    base_url: str, params: OpenOrderParams = None, next_cursor="MA=="
) -> str:
    """
    Adds query parameters to a url
    """
    url = base_url
    if params:
        url = url + "?"
        if params.market:
            url = build_query_params(url, "market", params.market)
        if params.asset_id:
            url = build_query_params(url, "asset_id", params.asset_id)
        if params.id:
            url = build_query_params(url, "id", params.id)
        if next_cursor:
            url = build_query_params(url, "next_cursor", next_cursor)
    return url


def drop_notifications_query_params(
    base_url: str, params: DropNotificationParams = None
) -> str:
    """
    Adds query parameters to a url
    """
    url = base_url
    if params:
        url = url + "?"
        if params.ids:
            url = build_query_params(url, "ids", ",".join(params.ids))
    return url


def add_balance_allowance_params_to_url(
    base_url: str, params: BalanceAllowanceParams = None
) -> str:
    """
    Adds query parameters to a url
    """
    url = base_url
    if params:
        url = url + "?"
        if params.asset_type:
            url = build_query_params(url, "asset_type", params.asset_type.__str__())
        if params.token_id:
            url = build_query_params(url, "token_id", params.token_id)
        if params.signature_type is not None:
            url = build_query_params(url, "signature_type", params.signature_type)
    return url


def add_order_scoring_params_to_url(
    base_url: str, params: OrderScoringParams = None
) -> str:
    """
    Adds query parameters to a url
    """
    url = base_url
    if params:
        url = url + "?"
        if params.orderId:
            url = build_query_params(url, "order_id", params.orderId)
    return url


def add_orders_scoring_params_to_url(
    base_url: str, params: OrdersScoringParams = None
) -> str:
    """
    Adds query parameters to a url
    """
    url = base_url
    if params:
        url = url + "?"
        if params.orderIds:
            url = build_query_params(url, "order_ids", ",".join(params.orderIds))
    return url
