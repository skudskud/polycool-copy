"""
Telegram fixtures for E2E tests
Provides mock Telegram Update, Context, and related objects
"""

import pytest
from unittest.mock import Mock, MagicMock
from telegram import Update, User, Message, CallbackQuery, Chat
from telegram.ext import ContextTypes


@pytest.fixture
def telegram_update():
    """
    Mock Telegram Update object for command handlers

    - User ID: 123456789 (matches funded_user fixture)
    - Username: test_user
    - Message: Mock with basic attributes
    """
    # Create mock user
    mock_user = Mock(spec=User)
    mock_user.id = 123456789
    mock_user.username = "test_user"
    mock_user.first_name = "Test"
    mock_user.last_name = "User"

    # Create mock chat
    mock_chat = Mock(spec=Chat)
    mock_chat.id = 123456789
    mock_chat.type = "private"

    # Create mock message
    mock_message = Mock(spec=Message)
    mock_message.from_user = mock_user
    mock_message.chat = mock_chat
    mock_message.message_id = 12345
    mock_message.text = None  # Will be set by test
    mock_message.reply_text = Mock(return_value=Mock())  # Mock async method

    # Create mock update
    update = Mock(spec=Update)
    update.effective_user = mock_user
    update.effective_chat = mock_chat
    update.message = mock_message
    update.callback_query = None

    return update


@pytest.fixture
def telegram_callback_update():
    """
    Mock Telegram Update object for callback query handlers

    - Callback data can be customized per test
    - User matches telegram_update fixture
    """
    # Create mock user
    mock_user = Mock(spec=User)
    mock_user.id = 123456789
    mock_user.username = "test_user"

    # Create mock callback query
    mock_callback_query = Mock(spec=CallbackQuery)
    mock_callback_query.from_user = mock_user
    mock_callback_query.data = None  # Will be set by test
    mock_callback_query.id = "callback_123"
    mock_callback_query.answer = Mock(return_value=None)
    mock_callback_query.edit_message_text = Mock(return_value=None)

    # Create mock update
    update = Mock(spec=Update)
    update.effective_user = mock_user
    update.callback_query = mock_callback_query
    update.message = None

    return update


@pytest.fixture
def telegram_context():
    """
    Mock Telegram Context object with user_data and bot_data

    - Empty user_data dict (can be modified by tests)
    - Bot mock for sending messages
    """
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)

    # Mock user_data as dict
    context.user_data = {}

    # Mock bot for sending messages
    mock_bot = Mock()
    mock_bot.send_message = Mock(return_value=Mock())
    context.bot = mock_bot

    return context


@pytest.fixture
def telegram_message_update():
    """
    Mock Telegram Update object for message handlers (text input)

    Used for flows requiring user text input (addresses, amounts, etc.)
    """
    # Create mock user
    mock_user = Mock(spec=User)
    mock_user.id = 123456789
    mock_user.username = "test_user"

    # Create mock message with text
    mock_message = Mock(spec=Message)
    mock_message.from_user = mock_user
    mock_message.text = None  # Will be set by test
    mock_message.message_id = 12345
    mock_message.reply_text = Mock(return_value=Mock())

    # Create mock update
    update = Mock(spec=Update)
    update.effective_user = mock_user
    update.message = mock_message
    update.callback_query = None

    return update


@pytest.fixture
def onboarding_telegram_update():
    """
    Mock Telegram Update for new/onboarding user

    - Different user ID (987654321) to match onboarding_user fixture
    - Username: new_user
    """
    # Create mock user
    mock_user = Mock(spec=User)
    mock_user.id = 987654321
    mock_user.username = "new_user"
    mock_user.first_name = "New"
    mock_user.last_name = "User"

    # Create mock message
    mock_message = Mock(spec=Message)
    mock_message.from_user = mock_user
    mock_message.reply_text = Mock(return_value=Mock())

    # Create mock update
    update = Mock(spec=Update)
    update.effective_user = mock_user
    update.message = mock_message
    update.callback_query = None

    return update
