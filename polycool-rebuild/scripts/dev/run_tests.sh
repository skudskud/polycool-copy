#!/bin/bash
# Run tests while avoiding anchorpy plugin conflicts
# Usage: bash scripts/dev/run_tests.sh

set -e

cd "$(dirname "$0")/../.."

echo "🧪 Running tests (avoiding anchorpy conflicts)..."
echo ""

# Disable pytest plugin autoloading to avoid anchorpy conflicts
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

# Run pytest with explicit plugin list
python3 -m pytest \
    --override-ini="addopts=-v --tb=short" \
    --no-cov \
    tests/unit/ \
    "$@"
