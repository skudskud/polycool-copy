#!/usr/bin/env python3
"""
Railway entry point - imports FastAPI app from the actual location
This fixes the hyphen-in-directory-name import issue
"""
import sys
import os

# Add the telegram-bot-v2/py-clob-server directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'telegram-bot-v2', 'py-clob-server'))

# Import the FastAPI app from the actual location
from main import app

# Export the app for Railway/Uvicorn
__all__ = ['app']
