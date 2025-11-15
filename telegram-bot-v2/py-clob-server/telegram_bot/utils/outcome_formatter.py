#!/usr/bin/env python3
"""
Outcome Formatter Utility
Handles smart formatting of market outcomes (YES/NO vs custom team/player names)
"""


def should_show_custom_outcomes(outcomes):
    """
    Determine if market has custom outcomes (not YES/NO)
    
    Args:
        outcomes: List of outcome names
        
    Returns:
        True if custom outcomes, False if YES/NO market
    """
    if not outcomes or len(outcomes) != 2:
        return False
    
    # Check if it's YES/NO market (case insensitive)
    outcome1 = str(outcomes[0]).strip().lower()
    outcome2 = str(outcomes[1]).strip().lower()
    
    is_yes_no = (outcome1 == 'yes' and outcome2 == 'no')
    
    return not is_yes_no


def get_outcome_emoji(category, outcome_name):
    """
    Get context-appropriate emoji for outcome based on category
    
    Args:
        category: Market category (Sports, Crypto, etc)
        outcome_name: Name of the outcome
        
    Returns:
        Emoji string
    """
    if not category:
        # Check outcome name for crypto direction
        outcome_lower = str(outcome_name).lower()
        if 'up' in outcome_lower:
            return '📈'
        elif 'down' in outcome_lower:
            return '📉'
        return '🏆'
    
    category_lower = category.lower()
    
    if category_lower in ['sports', 'esports']:
        return '🏆'
    elif category_lower == 'crypto':
        # Check if Up/Down
        outcome_lower = str(outcome_name).lower()
        if 'up' in outcome_lower:
            return '📈'
        elif 'down' in outcome_lower:
            return '📉'
        return '₿'
    else:
        return '🏆'


def format_outcome_display(outcomes, outcome_prices, category=''):
    """
    Format outcome display - either YES/NO or custom outcome names
    
    Args:
        outcomes: List of outcome names (e.g., ["Yes", "No"] or ["Lakers", "Grizzlies"])
        outcome_prices: List of prices (e.g., [0.47, 0.53])
        category: Market category for emoji selection
        
    Returns:
        Formatted string like "✅ YES 47¢ • ❌ NO 53¢" or "🏆 Lakers 47¢ • 🏆 Grizzlies 53¢"
    """
    if not outcomes or not outcome_prices or len(outcomes) != 2 or len(outcome_prices) != 2:
        return "N/A"
    
    # Format prices
    try:
        price1 = int(outcome_prices[0] * 100)
        price2 = int(outcome_prices[1] * 100)
        price1_str = f"{price1}¢"
        price2_str = f"{price2}¢"
    except:
        price1_str = "N/A"
        price2_str = "N/A"
    
    # Check if custom outcomes
    if should_show_custom_outcomes(outcomes):
        # Show custom outcome names
        emoji1 = get_outcome_emoji(category, outcomes[0])
        emoji2 = get_outcome_emoji(category, outcomes[1])
        return f"{emoji1} {outcomes[0]} {price1_str}  •  {emoji2} {outcomes[1]} {price2_str}"
    else:
        # Traditional YES/NO
        return f"✅ YES {price1_str}  •  ❌ NO {price2_str}"

