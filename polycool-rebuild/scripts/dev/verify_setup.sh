#!/bin/bash
# Quick verification script
# Run: bash scripts/dev/verify_setup.sh

set -e

echo "🔍 Verifying Polycool Rebuild Setup..."
echo ""

# Check Python version
echo "1. Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "   Python: $python_version"
if [[ $(echo "$python_version 3.9" | awk '{print ($1 >= $2)}') == 1 ]]; then
    echo "   ✅ Python version OK"
else
    echo "   ⚠️  Python 3.9+ recommended"
fi

# Check if virtual environment is active
echo ""
echo "2. Checking virtual environment..."
if [[ -n "$VIRTUAL_ENV" ]]; then
    echo "   ✅ Virtual environment active: $VIRTUAL_ENV"
else
    echo "   ⚠️  No virtual environment detected (recommended)"
fi

# Check dependencies
echo ""
echo "3. Checking dependencies..."
if python3 -c "import fastapi" 2>/dev/null; then
    echo "   ✅ fastapi installed"
else
    echo "   ❌ fastapi not installed"
fi

if python3 -c "import telegram" 2>/dev/null; then
    echo "   ✅ python-telegram-bot installed"
else
    echo "   ❌ python-telegram-bot not installed"
fi

if python3 -c "import sqlalchemy" 2>/dev/null; then
    echo "   ✅ sqlalchemy installed"
else
    echo "   ❌ sqlalchemy not installed"
fi

if python3 -c "import websockets" 2>/dev/null; then
    echo "   ✅ websockets installed"
else
    echo "   ❌ websockets not installed"
fi

if python3 -c "import redis" 2>/dev/null; then
    echo "   ✅ redis installed"
else
    echo "   ❌ redis not installed"
fi

if python3 -c "import cryptography" 2>/dev/null; then
    echo "   ✅ cryptography installed"
else
    echo "   ❌ cryptography not installed"
fi

# Check .env file
echo ""
echo "4. Checking .env file..."
if [[ -f ".env" ]]; then
    echo "   ✅ .env file exists"
    if grep -q "BOT_TOKEN" .env 2>/dev/null; then
        echo "   ✅ BOT_TOKEN configured"
    else
        echo "   ⚠️  BOT_TOKEN not found in .env"
    fi
    if grep -q "DATABASE_URL" .env 2>/dev/null; then
        echo "   ✅ DATABASE_URL configured"
    else
        echo "   ⚠️  DATABASE_URL not found in .env"
    fi
else
    echo "   ⚠️  .env file not found (create from env.template)"
fi

# Test imports
echo ""
echo "5. Testing imports..."
if python3 scripts/dev/test_imports.py 2>/dev/null; then
    echo "   ✅ All imports successful"
else
    echo "   ❌ Some imports failed (run: python scripts/dev/test_imports.py)"
fi

echo ""
echo "✅ Verification complete!"
echo ""
echo "Next steps:"
echo "  1. Install dependencies: pip install -r requirements.txt"
echo "  2. Configure .env file"
echo "  3. Run tests: pytest tests/unit/"
echo "  4. Start bot: python main.py"
