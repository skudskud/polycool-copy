#!/usr/bin/env python3
"""
Final Railway Setup - Create Missing Services and Fix Everything
"""

import subprocess
import os
from pathlib import Path

SERVICES_TO_CREATE = {
    'polycool-bot': {
        'path': '.',
        'start_command': 'python telegram_bot/bot/main.py',
        'description': 'Telegram Bot Service'
    },
    'polycool-streamer': {
        'path': '.',
        'start_command': 'python data_ingestion/streamer/streamer.py',
        'description': 'WebSocket Market Streamer'
    },
    'polycool-poller': {
        'path': '.',
        'start_command': 'python data_ingestion/poller/market_enricher.py',
        'description': 'Market Data Polling Service'
    }
}

REDIS_URL = "redis://default:nAUqCeWhaVgoeAVoBpLJRNRSMyPMLWSG@redis.railway.internal:6379"
DB_URL = "postgresql://polycool:polycool2025@aws-1-eu-north-1.pooler.supabase.com:5432/postgres"

def run_cmd(cmd, cwd=None):
    """Run command safely"""
    print(f"🔧 {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Failed: {result.stderr}")
        return False
    return True

def create_service(service_name, config):
    """Create a service with correct configuration"""
    print(f"\n📦 Creating {service_name}...")

    # Create railway.json
    railway_config = {
        "build": {
            "builder": "NIXPACKS",
            "buildCommand": "pip install -r requirements.txt"
        },
        "deploy": {
            "startCommand": config['start_command'],
            "restartPolicyType": "ON_FAILURE",
            "restartPolicyMaxRetries": 10
        }
    }

    import json
    config_path = Path(config['path']) / 'railway.json'
    with open(config_path, 'w') as f:
        json.dump(railway_config, f, indent=2)

    # Deploy
    service_path = Path(config['path']).resolve()
    if run_cmd("railway up", cwd=service_path):
        print(f"✅ {service_name} deployed")
        return True
    else:
        print(f"❌ {service_name} deployment failed")
        return False

def fix_environment_variables():
    """Fix environment variables for all services"""
    print("\n🔧 Fixing environment variables...")

    services = ['polycool-api', 'polycool-bot', 'polycool-streamer', 'polycool-poller']

    for service in services:
        print(f"  📝 Configuring {service}...")

        # Redis URL
        run_cmd(f'railway variables --service {service} --set "REDIS_URL={REDIS_URL}"')

        # Database URL
        run_cmd(f'railway variables --service {service} --set "DATABASE_URL={DB_URL}"')

        # Other essential vars
        run_cmd(f'railway variables --service {service} --set "LOG_LEVEL=INFO"')
        run_cmd(f'railway variables --service {service} --set "DEBUG=false"')

def main():
    """Main setup"""
    print("🚀 Final Railway Services Setup")
    print("=" * 40)

    # Fix existing polycool-api first
    print("🔧 Fixing polycool-api configuration...")
    api_config = {
        'path': '.',
        'start_command': 'python telegram_bot/main.py',
        'description': 'Main API and Bot'
    }

    railway_config = {
        "build": {
            "builder": "NIXPACKS",
            "buildCommand": "pip install -r requirements.txt"
        },
        "deploy": {
            "startCommand": api_config['start_command'],
            "restartPolicyType": "ON_FAILURE",
            "restartPolicyMaxRetries": 10,
            "healthcheckPath": "/health"
        }
    }

    import json
    with open('railway.json', 'w') as f:
        json.dump(railway_config, f, indent=2)

    print("✅ polycool-api config fixed")

    # Create missing services
    for service_name, config in SERVICES_TO_CREATE.items():
        create_service(service_name, config)

    # Fix environment variables
    fix_environment_variables()

    # Final redeploy of polycool-api
    print("\n🔄 Redeploying polycool-api...")
    run_cmd("railway up")

    print("\n🎉 Setup complete!")
    print("\n📋 Check status:")
    print("  railway status")
    print("  railway logs --service <service-name>")
    print("\n🌐 Service URLs:")
    print("  railway domain --service polycool-api")

if __name__ == "__main__":
    main()
