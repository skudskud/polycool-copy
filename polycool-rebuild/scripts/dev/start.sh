#!/bin/bash
# Polycool Development Start Script

set -e

echo "🚀 Starting Polycool in development mode..."

# Check if Docker services are running
if ! docker compose ps postgres | grep -q "running\|healthy"; then
    echo "❌ PostgreSQL is not running. Run 'docker compose up -d postgres redis' first."
    exit 1
fi

if ! docker compose ps redis | grep -q "running\|healthy"; then
    echo "❌ Redis is not running. Run 'docker compose up -d postgres redis' first."
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Run './scripts/dev/setup.sh' first."
    exit 1
fi

# Export environment variables
export $(grep -v '^#' .env | xargs)

# Start the application
echo "🌟 Starting FastAPI server..."
python -m telegram_bot.main
