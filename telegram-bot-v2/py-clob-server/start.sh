#!/bin/bash
# Clear Python bytecode cache to prevent stale import errors
echo "🧹 Clearing Python bytecode cache..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo "✅ Python cache cleared"

# Start the application
echo "🚀 Starting application..."
exec python main.py

