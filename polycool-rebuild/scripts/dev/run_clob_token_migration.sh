#!/bin/bash
"""
Script to run clob_token_ids migration in Railway environment
"""

set -e

echo "🚀 Starting clob_token_ids migration on Railway..."

# Navigate to the correct directory
cd /app

# Run the migration script
echo "📊 Running migration script..."
python scripts/dev/fix_clob_token_ids_migration.py

echo "✅ Migration completed successfully!"
