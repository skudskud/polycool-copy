"""
Markets Hub Module
Handles the main markets interface and navigation
"""
from telegram import InlineKeyboardButton


# Categories configuration
CATEGORIES = {
    'geopolitics': {'name': '🌍 Geopolitics', 'desc': 'Politics & World Events'},
    'sports': {'name': '⚽ Sports', 'desc': 'Sports & Entertainment'},
    'finance': {'name': '💰 Finance', 'desc': 'Finance & Economics'},
    'crypto': {'name': '₿ Crypto', 'desc': 'Crypto & Technology'},
    'other': {'name': '🎭 Other', 'desc': 'Other Markets'}
}


def get_hub_message() -> str:
    """
    Get the main markets hub message
    """
    message = """
📊 **MARKET HUB**

Browse trending markets, explore categories, or search for specific topics.

🔥 **Popular Now**
• Trending markets across all categories
• Real-time prices and volume

📂 **Categories**
• 🌍 Geopolitics - Politics & World Events
• ⚽ Sports - Sports & Entertainment
• 💰 Finance - Finance & Economics
• ₿ Crypto - Crypto & Technology
• 🎭 Other - Other Markets

🔍 **Search**
• Find any market by keyword
"""

    return message.strip()


def build_hub_keyboard():
    """
    Build the main hub keyboard with trending, categories, and search
    """
    keyboard = []

    # Trending
    keyboard.append([
        InlineKeyboardButton("🔥 Trending Markets", callback_data="trending_markets_0")
    ])

    # Categories (2 per row)
    keyboard.extend([
        [
            InlineKeyboardButton(CATEGORIES['geopolitics']['name'], callback_data="cat_geopolitics_0"),
            InlineKeyboardButton(CATEGORIES['sports']['name'], callback_data="cat_sports_0")
        ],
        [
            InlineKeyboardButton(CATEGORIES['finance']['name'], callback_data="cat_finance_0"),
            InlineKeyboardButton(CATEGORIES['crypto']['name'], callback_data="cat_crypto_0")
        ],
        [InlineKeyboardButton(CATEGORIES['other']['name'], callback_data="cat_other_0")]
    ])

    # Search
    keyboard.append([
        InlineKeyboardButton("🔍 Search Markets", callback_data="trigger_search")
    ])

    return keyboard


def get_category_name(category_key: str) -> str:
    """
    Get display name for a category key
    """
    return CATEGORIES.get(category_key, {}).get('name', category_key.capitalize())


def get_category_description(category_key: str) -> str:
    """
    Get description for a category key
    """
    return CATEGORIES.get(category_key, {}).get('desc', '')
