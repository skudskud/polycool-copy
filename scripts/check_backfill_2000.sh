#!/bin/bash
# Monitor backfill_2000.log progress

echo "📊 Top 2000 Markets Backfill Monitor"
echo "====================================="

while true; do
    sleep 30
    echo ""
    echo "⏱️  $(date +%H:%M:%S):"
    
    # Show latest progress
    tail -20 /tmp/backfill_2000.log | grep -E "\[.*\]|Progress:" | tail -5
    
    # Check if done
    if tail -5 /tmp/backfill_2000.log | grep -q "COMPLETE"; then
        echo ""
        echo "✅ BACKFILL COMPLETE!"
        tail -10 /tmp/backfill_2000.log
        break
    fi
done


