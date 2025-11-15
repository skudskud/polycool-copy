#!/usr/bin/env python3
"""
Escape utilities for Telegram Markdown
"""

import re


def escape_markdown(text: str) -> str:
    """
    Escape special Markdown characters for Telegram

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for Telegram Markdown
    """
    if not text:
        return ""

    # Characters that need escaping in Markdown
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!', ':']

    escaped_text = text
    for char in escape_chars:
        escaped_text = escaped_text.replace(char, f'\\{char}')

    return escaped_text


def escape_error_message(error: Exception) -> str:
    """
    Escape error message for safe display in Telegram Markdown

    Args:
        error: Exception object

    Returns:
        Escaped error message safe for Telegram Markdown
    """
    return escape_markdown(str(error))
