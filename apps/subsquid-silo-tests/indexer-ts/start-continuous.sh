#!/bin/bash

# Subsquid Continuous Indexer
# Automatically restarts the processor when it catches up to the latest block
# This ensures continuous real-time indexing of new blocks

echo "[CONTINUOUS] 🚀 Starting Subsquid indexer with auto-restart..."
echo "[CONTINUOUS] Press Ctrl+C to stop"
echo ""

# Trap Ctrl+C to allow clean exit
trap 'echo ""; echo "[CONTINUOUS] 🛑 Received stop signal, exiting..."; exit 0' INT TERM

RESTART_COUNT=0

while true; do
    RESTART_COUNT=$((RESTART_COUNT + 1))

    echo "[CONTINUOUS] ═══════════════════════════════════════════════"
    echo "[CONTINUOUS] 🔄 Starting indexer (run #$RESTART_COUNT) at $(date '+%Y-%m-%d %H:%M:%S')"
    echo "[CONTINUOUS] ═══════════════════════════════════════════════"
    echo ""

    npm run start

    EXIT_CODE=$?

    echo ""

    if [ $EXIT_CODE -eq 0 ]; then
        echo "[CONTINUOUS] ✅ Indexer completed normally (caught up to latest block)"
        echo "[CONTINUOUS] ⏳ Waiting 5 seconds before checking for new blocks..."
        sleep 5
    else
        echo "[CONTINUOUS] ❌ Indexer exited with error code $EXIT_CODE"
        echo "[CONTINUOUS] ⏳ Waiting 10 seconds before retry..."
        sleep 10
    fi

    echo ""
done
