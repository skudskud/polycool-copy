#!/usr/bin/env python3
"""
Debug script to check token ordering and orderbook availability
"""

import requests
import json

def test_market_tokens(market_id):
    """Test a market's tokens and orderbooks"""

    print(f"\n=== Testing Market {market_id} ===")

    # Get market from API
    api_url = f"https://gamma-api.polymarket.com/markets/{market_id}"
    response = requests.get(api_url)

    if response.status_code != 200:
        print(f"❌ API returned {response.status_code}")
        return

    market = response.json()

    print(f"Title: {market.get('question', 'Unknown')[:80]}...")
    print(f"Active: {market.get('active')}")
    print(f"Accepting orders: {market.get('accepting_orders')}")
    print(f"Tradeable: {market.get('tradeable')}")

    tokens = market.get('tokens')
    clob_token_ids = market.get('clob_token_ids', [])
    outcomes = market.get('outcomes', [])

    print(f"Tokens from API: {len(tokens) if tokens else 0}")
    print(f"Outcomes: {outcomes}")
    print(f"CLOB token IDs: {len(clob_token_ids) if clob_token_ids else 0}")

    if tokens:
        for i, token in enumerate(tokens):
            print(f"  Token {i}: outcome='{token.get('outcome')}', id={token.get('token_id', 'MISSING')[:20]}...")

    # Test orderbooks
    if clob_token_ids:
        for i, token_id in enumerate(clob_token_ids):
            ob_url = f"https://clob.polymarket.com/orderbook?token_id={token_id}"
            ob_response = requests.get(ob_url)

            if ob_response.status_code == 200:
                try:
                    ob_data = ob_response.json()
                    success = ob_data.get('success', False)
                    print(f"  Token {i} orderbook: {'✅ ACTIVE' if success else '❌ INACTIVE'}")
                except:
                    print(f"  Token {i} orderbook: ❌ INVALID JSON")
            else:
                print(f"  Token {i} orderbook: ❌ {ob_response.status_code}")

if __name__ == "__main__":
    # Test the problematic market
    test_market_tokens("600453")

    # Test a working market for comparison
    test_market_tokens("538932")
