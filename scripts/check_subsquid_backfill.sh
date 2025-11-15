#!/bin/bash
echo "🎯 SUBSQUID Markets Backfill Status (ACTIVE TABLE)"
echo "=========================================="
echo ""

if ps aux | grep -v grep | grep backfill_subsquid_categories > /dev/null; then
    echo "✅ Status: RUNNING"
    echo ""
    
    echo "📊 Latest Progress:"
    tail -20 /tmp/subsquid_backfill.log | grep "Progress:" | tail -1
    echo ""
    
    echo "🎯 Last 5 Categorizations:"
    tail -30 /tmp/subsquid_backfill.log | grep "→" | tail -5
    echo ""
    
    echo "📈 Category Breakdown:"
    tail -1000 /tmp/subsquid_backfill.log | grep "→" | awk -F'→' '{print $2}' | awk '{print $1}' | sort | uniq -c | sort -rn
else
    echo "⏹️  Status: COMPLETED or NOT RUNNING"
    echo ""
    
    if tail -20 /tmp/subsquid_backfill.log | grep "COMPLETE" > /dev/null; then
        echo "✅ BACKFILL COMPLETED!"
        tail -10 /tmp/subsquid_backfill.log
    else
        echo "Last output:"
        tail -10 /tmp/subsquid_backfill.log
    fi
fi

echo ""
echo "📄 Full log: /tmp/subsquid_backfill.log"
