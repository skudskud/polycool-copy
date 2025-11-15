#!/bin/bash
# Polycool Development Setup Script
# One-command setup for new developers

set -e

echo "🚀 Setting up Polycool development environment..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "📝 Creating .env file from template..."
    cp env.template .env
    echo "✅ .env file created. Please edit it with your credentials."
fi

# Start Docker services
echo "🐳 Starting Docker services..."
docker compose up -d postgres redis

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 10

# Check if services are healthy
if docker compose ps postgres | grep -q "healthy\|running"; then
    echo "✅ PostgreSQL is ready"
else
    echo "❌ PostgreSQL failed to start"
    exit 1
fi

if docker compose ps redis | grep -q "healthy\|running"; then
    echo "✅ Redis is ready"
else
    echo "❌ Redis failed to start"
    exit 1
fi

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -e ".[dev]"

# Run database migrations (placeholder)
echo "🗄️ Setting up database..."
python -c "import asyncio; from core.database.connection import init_db; asyncio.run(init_db())"

echo ""
echo "🎉 Setup complete! You can now:"
echo "  • Start the bot: python -m telegram_bot.main"
echo "  • View logs: docker compose logs -f"
echo "  • Access pgAdmin: http://localhost:5050"
echo "  • Access Redis Commander: http://localhost:8081"
echo ""
echo "Happy coding! 🎯"
