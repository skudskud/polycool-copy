#!/usr/bin/env python3
"""
Railway Services Setup Script for Polycool
Automates the creation and configuration of all Railway services
"""

import os
import subprocess
import time
from pathlib import Path

# Service definitions
SERVICES = {
    'polycool-api': {
        'description': 'API service for business logic',
        'source_dir': '.',
        'start_command': 'python -m uvicorn telegram_bot.api.routes:app --host 0.0.0.0 --port $PORT'
    },
    'polycool-bot': {
        'description': 'Telegram bot interface',
        'source_dir': '.',
        'start_command': 'python telegram_bot/bot/main.py'
    },
    'polycool-indexer': {
        'description': 'Subsquid indexer for trades',
        'source_dir': '../apps/subsquid-silo-tests/indexer-ts',
        'start_command': 'npm start'
    },
    'polycool-streamer': {
        'description': 'WebSocket market data streamer',
        'source_dir': '.',
        'start_command': 'python data_ingestion/streamer/streamer.py'
    },
    'polycool-poller': {
        'description': 'Market data polling service',
        'source_dir': '.',
        'start_command': 'python data_ingestion/poller/market_enricher.py'
    }
}

# Environment variables to set
ENV_VARS = {
    'DATABASE_URL': 'postgresql://polycool:polycool2025@aws-1-eu-north-1.pooler.supabase.com:5432/postgres',
    'REDIS_URL': 'redis://default:nAUqCeWhaVgoeAVoBpLJRNRSMyPMLWSG@redis.railway.internal:6379',
    'LOG_LEVEL': 'INFO',
    'DEBUG': 'false',
    'TESTING': 'false'
}

def run_command(cmd, cwd=None, check=True):
    """Run a command and return the result"""
    print(f"🔧 Running: {cmd}")
    if cwd:
        print(f"📁 In directory: {cwd}")

    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)

    if check and result.returncode != 0:
        print(f"❌ Command failed: {cmd}")
        print(f"Error: {result.stderr}")
        return False

    print(f"✅ Command succeeded: {cmd}")
    return True

def create_service(service_name, service_config):
    """Create a Railway service"""
    print(f"📦 Creating service: {service_name} ({service_config['description']})")

    # Navigate to source directory
    original_dir = os.getcwd()
    source_dir = Path(service_config['source_dir']).resolve()

    try:
        os.chdir(source_dir)

        # Create railway.json for this service
        railway_config = {
            "build": {
                "builder": "NIXPACKS",
                "buildCommand": "pip install -r requirements.txt" if "python" in service_config['start_command'] else "npm install"
            },
            "deploy": {
                "startCommand": service_config['start_command'],
                "restartPolicyType": "ON_FAILURE",
                "restartPolicyMaxRetries": 10,
                "healthcheckPath": "/health" if "api" in service_name else None,
                "readinessProbe": {
                    "path": "/health",
                    "port": "$PORT",
                    "initialDelaySeconds": 10,
                    "timeoutSeconds": 5,
                    "periodSeconds": 5,
                    "successThreshold": 1,
                    "failureThreshold": 3
                } if "api" in service_name else None
            }
        }

        # Remove None values
        railway_config['deploy'] = {k: v for k, v in railway_config['deploy'].items() if v is not None}

        import json
        with open('railway.json', 'w') as f:
            json.dump(railway_config, f, indent=2)

        print(f"📄 Created railway.json for {service_name}")

        # Deploy the service
        if run_command("railway up", cwd=source_dir):
            print(f"🚀 Deployed {service_name}")
        else:
            print(f"⚠️ Failed to deploy {service_name}")

    finally:
        os.chdir(original_dir)

    return True

def setup_environment_variables():
    """Setup environment variables for all services"""
    print("🔧 Setting up environment variables...")

    # Read .env.local if exists
    env_file = Path('.env.local')
    if env_file.exists():
        print("📄 Reading .env.local...")
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        ENV_VARS[key] = value

    # Set variables for each service
    for service_name in SERVICES.keys():
        print(f"📝 Setting variables for {service_name}...")
        for key, value in ENV_VARS.items():
            cmd = f'railway variables set "{key}"="{value}" --service "{service_name}"'
            run_command(cmd, check=False)  # Don't fail if variable already exists

def main():
    """Main setup function"""
    print("🚀 Polycool Railway Services Setup")
    print("=" * 50)

    # Check if we're in the right project
    result = subprocess.run("railway status", shell=True, capture_output=True, text=True)
    if "cheerful-fulfillment" not in result.stdout:
        print("❌ Not linked to cheerful-fulfillment project")
        print("Run: railway link -p cheerful-fulfillment")
        return

    print("✅ Connected to cheerful-fulfillment project")

    # Setup environment variables first
    setup_environment_variables()

    # Create and deploy services
    for service_name, service_config in SERVICES.items():
        create_service(service_name, service_config)
        time.sleep(2)  # Brief pause between deployments

    print("\n🎉 Setup complete!")
    print("\n📋 Services created:")
    for name, config in SERVICES.items():
        print(f"  • {name}: {config['description']}")

    print("\n🔍 Check deployment status:")
    print("  railway logs --service <service-name>")
    print("\n🌐 Service URLs:")
    print("  railway domain --service <service-name>")

if __name__ == "__main__":
    main()
