#!/usr/bin/env python3
"""
Pre-deployment check script - ensures bot is ready for deployment
"""

import os
import sys
import subprocess
from pathlib import Path

def check_environment():
    """Check that all required environment variables are set"""
    required = ['BOT_TOKEN', 'DATABASE_URL', 'REDIS_URL']
    missing = []

    for var in required:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        print("❌ MISSING REQUIRED ENVIRONMENT VARIABLES:")
        for var in missing:
            print(f"   - {var}")
        print("\nSet these in Railway environment variables before deploying.")
        return False

    print("✅ All required environment variables are set")
    return True

def check_dependencies():
    """Check that all Python dependencies are available"""
    try:
        import telegram
        import fastapi
        import redis
        import sqlalchemy
        print("✅ Core dependencies are available")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Run: pip install -r requirements.txt")
        return False

def check_syntax():
    """Check Python syntax of main files"""
    files_to_check = [
        'main.py',
        'telegram_bot/bot.py',
        'config/config.py'
    ]

    for file_path in files_to_check:
        if not Path(file_path).exists():
            print(f"❌ Required file missing: {file_path}")
            return False

        # Check syntax
        result = subprocess.run([sys.executable, '-m', 'py_compile', file_path],
                              capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Syntax error in {file_path}:")
            print(result.stderr)
            return False

    print("✅ Python syntax is valid")
    return True

def check_handlers():
    """Check for handler registration conflicts"""
    bot_file = Path('telegram_bot/bot.py')
    if not bot_file.exists():
        return True

    with open(bot_file, 'r') as f:
        content = f.read()

    # Check for duplicate category_handlers
    category_registrations = content.count('category_handlers.register(self.app')
    if category_registrations > 1:
        print(f"❌ Duplicate category_handlers registration ({category_registrations} times)")
        return False

    print("✅ Handler registrations are clean")
    return True

def run_diagnostic():
    """Run the diagnostic script"""
    try:
        result = subprocess.run([sys.executable, 'diagnose_bot_issues.py'],
                              capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ Diagnostic script failed:")
            print(result.stderr)
            return False

        # Check if critical issues were found
        output = result.stdout + result.stderr
        if 'CRITICAL:' in output:
            print("❌ Critical issues found in diagnostic:")
            # Extract critical issues
            lines = output.split('\n')
            for line in lines:
                if line.startswith('CRITICAL:'):
                    print(f"   {line}")
            return False

        print("✅ Diagnostic passed")
        return True

    except FileNotFoundError:
        print("⚠️ Diagnostic script not found - skipping")
        return True

def main():
    """Run all pre-deployment checks"""
    print("🚀 Pre-deployment check starting...\n")

    checks = [
        ("Environment variables", check_environment),
        ("Dependencies", check_dependencies),
        ("Python syntax", check_syntax),
        ("Handler conflicts", check_handlers),
        ("Bot diagnostic", run_diagnostic),
    ]

    all_passed = True
    for name, check_func in checks:
        print(f"🔍 Checking {name}...")
        if not check_func():
            all_passed = False

    print("\n" + "="*50)
    if all_passed:
        print("✅ ALL CHECKS PASSED - Ready for deployment!")
        print("\n🚀 You can now deploy with confidence.")
    else:
        print("❌ CHECKS FAILED - Fix issues before deploying!")
        print("\n🔧 Run the diagnostic script for detailed fixes:")
        print("   python diagnose_bot_issues.py")
        sys.exit(1)

if __name__ == "__main__":
    main()
