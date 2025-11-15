#!/usr/bin/env python3
"""
Fix Railway Services Configuration
Correct start commands and Redis URLs for all services
"""

import json
import os
from pathlib import Path

# Correct service configurations
SERVICE_CONFIGS = {
    'polycool-api': {
        'path': '.',
        'start_command': 'python telegram_bot/main.py',
        'description': 'Main API and Bot service'
    },
    'polycool-bot': {
        'path': '.',
        'start_command': 'python telegram_bot/bot/main.py',
        'description': 'Dedicated Telegram Bot'
    },
    'polycool-streamer': {
        'path': '.',
        'start_command': 'python data_ingestion/streamer/streamer.py',
        'description': 'WebSocket Market Data Streamer'
    },
    'polycool-poller': {
        'path': '.',
        'start_command': 'python data_ingestion/poller/market_enricher.py',
        'description': 'Market Data Polling Service'
    }
}

def create_correct_railway_json(service_name, config):
    """Create correct railway.json for a service"""
    railway_config = {
        "build": {
            "builder": "NIXPACKS",
            "buildCommand": "pip install -r requirements.txt"
        },
        "deploy": {
            "startCommand": config['start_command'],
            "restartPolicyType": "ON_FAILURE",
            "restartPolicyMaxRetries": 10,
            "healthcheckPath": "/health" if "api" in service_name or "bot" in service_name else None,
            "readinessProbe": {
                "path": "/health",
                "port": "$PORT",
                "initialDelaySeconds": 30,
                "timeoutSeconds": 10,
                "periodSeconds": 15,
                "successThreshold": 1,
                "failureThreshold": 3
            } if "api" in service_name or "bot" in service_name else None,
            "healthcheckTimeout": 30
        }
    }

    # Remove None values
    deploy_config = railway_config['deploy']
    railway_config['deploy'] = {k: v for k, v in deploy_config.items() if v is not None}

    return railway_config

def fix_service_config(service_name, config):
    """Fix configuration for a specific service"""
    service_path = Path(config['path']).resolve()
    railway_json_path = service_path / 'railway.json'

    # Create correct railway.json
    correct_config = create_correct_railway_json(service_name, config)

    with open(railway_json_path, 'w') as f:
        json.dump(correct_config, f, indent=2)

    print(f"✅ Fixed railway.json for {service_name}")

def fix_redis_urls():
    """Fix Redis URLs to use Railway Redis instead of localhost"""
    redis_url = "redis://default:nAUqCeWhaVgoeAVoBpLJRNRSMyPMLWSG@redis.railway.internal:6379"

    services = ['polycool-api', 'polycool-bot', 'polycool-streamer', 'polycool-poller']

    for service in services:
        # Use subprocess to set Redis URL
        import subprocess
        cmd = f'railway variables set REDIS_URL="{redis_url}" --service {service}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"✅ Fixed Redis URL for {service}")
        else:
            print(f"❌ Failed to fix Redis URL for {service}: {result.stderr}")

def redeploy_services():
    """Redeploy all services with corrected configurations"""
    services = ['polycool-api', 'polycool-bot', 'polycool-streamer', 'polycool-poller']

    for service in services:
        print(f"🚀 Redeploying {service}...")

        # Change to appropriate directory
        config = SERVICE_CONFIGS.get(service, SERVICE_CONFIGS['polycool-api'])
        service_path = Path(config['path']).resolve()

        import subprocess
        os.chdir(service_path)

        cmd = f'railway up --service {service}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"✅ Redeployed {service}")
        else:
            print(f"❌ Failed to redeploy {service}: {result.stderr}")

def main():
    """Main fix function"""
    print("🔧 Fixing Railway Services Configuration")
    print("=" * 50)

    # Fix railway.json files
    print("📝 Fixing railway.json configurations...")
    for service_name, config in SERVICE_CONFIGS.items():
        fix_service_config(service_name, config)

    # Fix Redis URLs
    print("\n🔗 Fixing Redis URLs...")
    fix_redis_urls()

    # Redeploy services
    print("\n🚀 Redeploying services...")
    redeploy_services()

    print("\n🎉 All fixes applied!")
    print("\n📋 Services status:")
    print("  railway status")
    print("\n📋 Check logs:")
    print("  railway logs --service <service-name>")
    print("\n🌐 Get service URLs:")
    print("  railway domain --service <service-name>")

if __name__ == "__main__":
    main()
