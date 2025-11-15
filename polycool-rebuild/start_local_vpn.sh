#!/bin/bash

# Script pour démarrer le bot en local avec VPN (sans DB)
# Usage: ./start_local_vpn.sh

echo "🚀 Starting Polycool Bot (Local + VPN - No DB)"
echo "==============================================="

# Vérifier si VPN est actif
echo "📡 Checking VPN status..."
curl -s https://httpbin.org/ip | jq -r '.origin'
echo ""

# Set environment variable to skip DB
export SKIP_DB=true

# Start the bot
echo "🤖 Starting bot with SKIP_DB=true..."
python -m telegram_bot.main
