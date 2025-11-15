#!/usr/bin/env python3
"""
Telegram Trading Bot Setup Script
"""

import subprocess
import sys
import os

def print_header(title):
    print(f"\n🤖 {title}")
    print("=" * (len(title) + 4))

def run_command(command, description):
    print(f"⏳ {description}...")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ {description} completed")
            return True
        else:
            print(f"❌ {description} failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ {description} error: {e}")
        return False

def main():
    print_header("TELEGRAM TRADING BOT SETUP")
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ required")
        sys.exit(1)
    else:
        print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")
    
    # Install Telegram dependencies
    print_header("INSTALLING TELEGRAM DEPENDENCIES")
    
    dependencies = [
        ("pip install python-telegram-bot", "Telegram Bot Library"),
        ("pip install asyncio", "Async Support"),
    ]
    
    for command, description in dependencies:
        run_command(command, description)
    
    # Check bot files
    print_header("CHECKING BOT FILES")
    
    required_files = [
        "telegram_bot.py",
        "speed_trader.py", 
        "market_database.py",
        "config.py",
        "markets_database.json"
    ]
    
    all_files_exist = True
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ {file_path} found")
        else:
            print(f"❌ {file_path} missing")
            all_files_exist = False
    
    if not all_files_exist:
        print("\n❌ Missing required files. Ensure you're in the 'telegram bot' directory.")
        return
    
    # Check database
    print_header("CHECKING MARKET DATABASE")
    
    try:
        import json
        with open('markets_database.json', 'r') as f:
            data = json.load(f)
            market_count = data.get('metadata', {}).get('total_markets', 0)
            print(f"✅ Database loaded: {market_count} markets")
    except Exception as e:
        print(f"❌ Database error: {e}")
        return
    
    # Display bot information
    print_header("BOT INFORMATION")
    
    print("🤖 Bot Username: @NewTestLestFuckingGoNowBot")
    print("🔑 Bot Token: 8200317103:AAHfhbipcw6w5n6y0oQCKFJ2TYU2jfh3yB4")
    print("🌐 Bot URL: https://t.me/NewTestLestFuckingGoNowBot")
    print()
    print("📋 Commands:")
    print("   /start    - Welcome message")
    print("   /markets  - Browse top volume markets")
    print("   /positions - View trading positions") 
    print("   /help     - Detailed help")
    print()
    print("⚡ Features:")
    print("   • 0-2 second execution")
    print("   • 3,000+ active markets")
    print("   • Live pricing with buttons")
    print("   • Ultra-aggressive fills")
    
    # Final instructions
    print_header("READY TO LAUNCH")
    
    print("🚀 TO START THE BOT:")
    print("   python telegram_bot.py")
    print()
    print("📱 TO TEST THE BOT:")
    print("   1. Go to https://t.me/NewTestLestFuckingGoNowBot")
    print("   2. Send /start")
    print("   3. Use /markets to browse and trade")
    print()
    print("🎯 READY FOR LIGHTNING-SPEED TELEGRAM TRADING!")

if __name__ == "__main__":
    main()
