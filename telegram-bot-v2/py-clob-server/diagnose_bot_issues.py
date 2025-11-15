#!/usr/bin/env python3
"""
Bot Diagnostic Script - Identifies and fixes common deployment issues
"""

import os
import sys
import logging
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BotDiagnostic:
    """Diagnoses common bot deployment issues"""

    def __init__(self):
        self.issues = []
        self.fixes = []

    def add_issue(self, severity: str, title: str, description: str, fix: str = None):
        """Add an identified issue"""
        self.issues.append({
            'severity': severity,
            'title': title,
            'description': description,
            'fix': fix
        })

    def run_all_checks(self):
        """Run all diagnostic checks"""
        logger.info("🔍 Starting bot diagnostic...")

        self.check_environment_variables()
        self.check_redis_connection()
        self.check_handler_conflicts()
        self.check_background_services()
        self.check_polling_configuration()

        self.print_report()

    def check_environment_variables(self):
        """Check critical environment variables"""
        logger.info("📋 Checking environment variables...")

        required_vars = ['BOT_TOKEN', 'DATABASE_URL', 'REDIS_URL']
        optional_vars = ['TELEGRAM_WEBHOOK_SECRET']

        for var in required_vars:
            if not os.getenv(var):
                self.add_issue(
                    'CRITICAL',
                    f'Missing {var}',
                    f'Environment variable {var} is not set',
                    f'Set {var} in Railway environment variables'
                )

        for var in optional_vars:
            if not os.getenv(var):
                self.add_issue(
                    'WARNING',
                    f'Missing {var}',
                    f'Optional variable {var} not set - webhook security reduced',
                    f'Consider setting {var} for enhanced webhook security'
                )

    def check_redis_connection(self):
        """Check Redis connectivity"""
        logger.info("🔄 Checking Redis connection...")

        try:
            import redis
            redis_url = os.getenv('REDIS_URL')
            if not redis_url:
                self.add_issue(
                    'CRITICAL',
                    'Redis URL not configured',
                    'REDIS_URL environment variable missing',
                    'Set REDIS_URL in Railway environment variables'
                )
                return

            client = redis.from_url(redis_url, decode_responses=True, socket_timeout=5)
            client.ping()
            logger.info("✅ Redis connection successful")

            # Check queue status
            queue_length = client.llen('telegram_updates')
            if queue_length > 0:
                self.add_issue(
                    'WARNING',
                    'Telegram queue has pending messages',
                    f'Telegram update queue has {queue_length} pending messages',
                    'Check if Telegram worker is running or restart the service'
                )

        except ImportError:
            self.add_issue(
                'CRITICAL',
                'Redis package not installed',
                'redis package missing from requirements.txt',
                'Add redis>=4.0.0 to requirements.txt'
            )
        except Exception as e:
            self.add_issue(
                'CRITICAL',
                'Redis connection failed',
                f'Cannot connect to Redis: {e}',
                'Check REDIS_URL configuration and Redis service status'
            )

    def check_handler_conflicts(self):
        """Check for handler registration conflicts"""
        logger.info("🎯 Checking handler conflicts...")

        bot_file = Path(__file__).parent / 'telegram_bot' / 'bot.py'
        if not bot_file.exists():
            return

        with open(bot_file, 'r') as f:
            content = f.read()

        # Check for duplicate handler registrations
        lines = content.split('\n')
        registrations = []

        for i, line in enumerate(lines):
            if 'category_handlers.register(self.app' in line:
                registrations.append(i + 1)

        if len(registrations) > 1:
            self.add_issue(
                'ERROR',
                'Duplicate handler registration',
                f'category_handlers.register() called {len(registrations)} times on lines {registrations}',
                'Remove duplicate registration in telegram_bot/bot.py'
            )

    def check_background_services(self):
        """Check background services configuration"""
        logger.info("⚙️ Checking background services...")

        # Check PriceMonitor interval
        main_file = Path(__file__).parent / 'main.py'
        if main_file.exists():
            with open(main_file, 'r') as f:
                content = f.read()

            if 'check_interval=10' in content:
                self.add_issue(
                    'WARNING',
                    'Frequent PriceMonitor checks',
                    'PriceMonitor checks TP/SL orders every 10 seconds',
                    'Consider increasing interval to 30-60 seconds to reduce load'
                )

            # Check number of scheduled jobs
            scheduler_jobs = content.count('scheduler.add_job(')
            if scheduler_jobs > 15:
                self.add_issue(
                    'WARNING',
                    'High number of scheduled jobs',
                    f'Found {scheduler_jobs} scheduled jobs - may cause performance issues',
                    'Review and optimize scheduled job intervals'
                )

    def check_polling_configuration(self):
        """Check polling configuration"""
        logger.info("🔄 Checking polling configuration...")

        main_file = Path(__file__).parent / 'main.py'
        if not main_file.exists():
            return

        with open(main_file, 'r') as f:
            content = f.read()

        # Check if polling is configured
        if 'run_polling' not in content:
            self.add_issue(
                'CRITICAL',
                'Telegram polling not configured',
                'Bot is not configured to use polling mode',
                'Check that start_telegram_bot_polling() is called'
            )

        # Check if threading is used for polling
        if 'threading.Thread' not in content:
            self.add_issue(
                'WARNING',
                'Polling may block FastAPI',
                'Telegram polling might block FastAPI health checks',
                'Ensure polling runs in background thread'
            )

    def print_report(self):
        """Print diagnostic report"""
        print("\n" + "="*80)
        print("🤖 BOT DIAGNOSTIC REPORT")
        print("="*80)

        if not self.issues:
            print("✅ No issues found! Bot should be working correctly.")
            return

        severity_order = {'CRITICAL': 0, 'ERROR': 1, 'WARNING': 2}

        # Sort issues by severity
        sorted_issues = sorted(self.issues, key=lambda x: severity_order.get(x['severity'], 3))

        for issue in sorted_issues:
            print(f"\n{issue['severity']}: {issue['title']}")
            print(f"   {issue['description']}")
            if issue['fix']:
                print(f"   🔧 FIX: {issue['fix']}")

        print("\n" + "="*80)

        critical_count = sum(1 for i in self.issues if i['severity'] == 'CRITICAL')
        if critical_count > 0:
            print(f"🚨 {critical_count} critical issues found - bot likely not functional")
        else:
            print("✅ No critical issues - check Railway logs for runtime errors")

def main():
    diagnostic = BotDiagnostic()
    diagnostic.run_all_checks()

if __name__ == "__main__":
    main()
