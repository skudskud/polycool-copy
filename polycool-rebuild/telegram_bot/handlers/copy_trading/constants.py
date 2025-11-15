"""
Copy Trading Constants
Conversation states and shared configuration
"""
import os
import logging

logger = logging.getLogger(__name__)

# Conversation states
VIEWING_DASHBOARD = 0
ASKING_POLYGON_ADDRESS = 1
CONFIRMING_LEADER = 2
SELECTING_BUDGET_PERCENTAGE = 3
SELECTING_COPY_MODE = 4
ENTERING_BUDGET = 5  # Legacy state for budget modification
ENTERING_FIXED_AMOUNT = 6  # State for entering fixed amount value

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"
