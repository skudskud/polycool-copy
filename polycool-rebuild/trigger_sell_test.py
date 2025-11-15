import asyncio
import os
import sys
sys.path.insert(0, '.')

# Simuler un appel HTTP au webhook Telegram
import httpx

async def trigger_sell():
    webhook_url = "http://localhost:8000/webhook"  # Assumant que le bot tourne sur le port 8000
    
    # Simuler un callback "Sell 100%" sur la position 1
    callback_data = "sell_amount_1_100"  # sell_position_{position_id}_{percentage}
    
    payload = {
        "update_id": 123456,
        "callback_query": {
            "id": "123456789",
            "from": {
                "id": 6500527972,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser"
            },
            "message": {
                "message_id": 123,
                "from": {
                    "id": 123456789,
                    "is_bot": True,
                    "first_name": "Polycool Bot",
                    "username": "polycool_bot"
                },
                "chat": {
                    "id": 6500527972,
                    "type": "private"
                },
                "date": 1731080000,
                "text": "💰 **Sell Position**\n\nSelect amount to sell:",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "25%", "callback_data": "sell_amount_1_25"}],
                        [{"text": "50%", "callback_data": "sell_amount_1_50"}],
                        [{"text": "75%", "callback_data": "sell_amount_1_75"}],
                        [{"text": "100%", "callback_data": "sell_amount_1_100"}]
                    ]
                }
            },
            "chat_instance": "123456789",
            "data": callback_data
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=10)
            print(f"Response status: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Erreur webhook: {e}")

if __name__ == "__main__":
    asyncio.run(trigger_sell())
