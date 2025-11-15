#!/bin/bash
# Quick status checker for backfill progress

echo "🎯 Market Categorization Backfill Status"
echo "=========================================="
echo ""

# Check if process is running
if ps aux | grep -v grep | grep backfill_categories_local > /dev/null; then
    echo "✅ Status: RUNNING"
    echo ""
    
    # Get latest progress
    echo "📊 Latest Progress:"
    tail -20 /tmp/backfill_full.log | grep "Progress:" | tail -1
    echo ""
    
    echo "🎯 Last 5 Categorizations:"
    tail -30 /tmp/backfill_full.log | grep "→" | tail -5
    echo ""
    
    echo "📈 Category Breakdown So Far:"
    tail -500 /tmp/backfill_full.log | grep "→" | awk -F'→' '{print $2}' | awk '{print $1}' | sort | uniq -c | sort -rn
    
else
    echo "⏹️  Status: COMPLETED or NOT RUNNING"
    echo ""
    
    # Check for completion message
    if tail -20 /tmp/backfill_full.log | grep "BACKFILL COMPLETE" > /dev/null; then
        echo "✅ BACKFILL COMPLETED SUCCESSFULLY!"
        echo ""
        tail -15 /tmp/backfill_full.log | grep -A10 "BACKFILL COMPLETE"
    else
        echo "⚠️  Process may have stopped unexpectedly"
        echo "Last 10 lines:"
        tail -10 /tmp/backfill_full.log
    fi
fi

echo ""
echo "📄 Full log: /tmp/backfill_full.log"
echo "Monitor live: tail -f /tmp/backfill_full.log"

