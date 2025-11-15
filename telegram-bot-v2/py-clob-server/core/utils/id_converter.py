#!/usr/bin/env python3
"""
HOTFIX: Convert token_id (decimal) to condition_id (0x format)
The token_id IS the decimal representation of condition_id!
"""

def token_id_to_condition_id(token_id_str: str) -> str:
    """
    Convert token ID (decimal string) to condition ID (0x hex format)
    
    Example:
    token_id = "13270961618826476343958587807832018084590864079392809290051794705223426186741"
    condition_id = "0x1d2e3f4..." (hex representation)
    
    Args:
        token_id_str: Token ID as decimal string
        
    Returns:
        Condition ID in 0x format
    """
    try:
        # Convert decimal string to integer
        token_id_int = int(token_id_str)
        
        # Convert to hex (without 0x prefix)
        hex_str = hex(token_id_int)[2:]  # Remove '0x' prefix
        
        # Pad to 64 characters (32 bytes) and add 0x prefix
        condition_id = "0x" + hex_str.zfill(64)
        
        return condition_id
    except (ValueError, TypeError) as e:
        print(f"Error converting token_id '{token_id_str}': {e}")
        return None


# Test
if __name__ == "__main__":
    test_token_id = "13270961618826476343958587807832018084590864079392809290051794705223426186741"
    result = token_id_to_condition_id(test_token_id)
    print(f"Token ID: {test_token_id}")
    print(f"Condition ID: {result}")
    print(f"Length: {len(result)}")

