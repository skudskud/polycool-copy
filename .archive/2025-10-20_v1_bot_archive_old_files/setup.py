#!/usr/bin/env python3
"""
Trading Bot Setup Script
Automated setup for the high-speed trading bot
"""

import os
import sys
import subprocess
import json
from pathlib import Path


def print_header(title):
    print(f"\n🚀 {title}")
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


def check_file_exists(file_path, description):
    if os.path.exists(file_path):
        print(f"✅ {description} found")
        return True
    else:
        print(f"❌ {description} missing")
        return False


def main():
    print_header("TRADING BOT SETUP")
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ required")
        sys.exit(1)
    else:
        print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")
    
    # Check required files
    print_header("CHECKING REQUIRED FILES")
    
    required_files = [
        ("config.py", "Configuration file"),
        ("market_database.py", "Market database module"),
        ("speed_trader.py", "Speed trader module"),
        ("database_updater.py", "Database updater module"),
        ("requirements.txt", "Requirements file"),
    ]
    
    all_files_exist = True
    for file_path, description in required_files:
        if not check_file_exists(file_path, description):
            all_files_exist = False
    
    if not all_files_exist:
        print("❌ Missing required files. Please ensure all bot files are present.")
        sys.exit(1)
    
    # Install requirements
    print_header("INSTALLING REQUIREMENTS")
    
    requirements = [
        ("pip install schedule", "Schedule library"),
        ("pip install python-dotenv", "Environment variables library"),
        ("pip install requests", "HTTP requests library")
    ]
    
    for command, description in requirements:
        run_command(command, description)
    
    # Initialize database
    print_header("INITIALIZING DATABASE")
    
    if os.path.exists("markets_database.json"):
        print("✅ Database already exists")
        
        # Check database content
        try:
            with open("markets_database.json", "r") as f:
                data = json.load(f)
                market_count = data.get("metadata", {}).get("total_markets", 0)
                print(f"📊 Database contains {market_count} markets")
        except Exception as e:
            print(f"⚠️ Database exists but couldn't read: {e}")
    else:
        print("📋 Initializing fresh database...")
        if run_command("python database_updater.py --init", "Database initialization"):
            print("✅ Database initialized successfully")
        else:
            print("❌ Database initialization failed")
    
    # Test basic functionality
    print_header("TESTING FUNCTIONALITY")
    
    test_commands = [
        ("python speed_trader.py search trump | head -20", "Search functionality"),
    ]
    
    for command, description in test_commands:
        run_command(command, description)
    
    # Final status
    print_header("SETUP COMPLETE")
    
    print("🎉 Trading bot setup completed!")
    print()
    print("📋 QUICK START:")
    print("   python speed_trader.py search <keyword>     # Find markets")
    print("   python speed_trader.py top                  # Show top markets") 
    print("   python speed_trader.py buy <id> yes 2.0     # Buy $2 YES tokens")
    print("   python speed_trader.py sell <id> yes 5      # Sell 5 YES tokens")
    print()
    print("🔧 BACKGROUND UPDATES:")
    print("   python database_updater.py                  # Auto-update database")
    print()
    print("📖 DOCUMENTATION:")
    print("   See README.md for detailed usage instructions")
    print()
    print("⚡ READY TO TRADE AT LIGHTNING SPEED!")


if __name__ == "__main__":
    main()
