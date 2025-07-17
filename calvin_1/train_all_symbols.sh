#!/bin/bash

# Train all symbols with optimized LightGBM
# This script trains each symbol sequentially to avoid event loop issues

echo "🚀 Starting LightGBM training for all symbols"
echo "================================================"

# Configuration
DAYS=180
TRIALS=300
TIMEOUT=7200

# Create logs directory if it doesn't exist
mkdir -p logs/lgb_training

# Function to train a single symbol
train_symbol() {
    local symbol=$1
    local logfile="logs/lgb_training/${symbol}_optimization_$(date +%Y%m%d_%H%M%S).log"
    
    echo ""
    echo "============================================================"
    echo "🎯 Training $symbol"
    echo "📝 Log file: $logfile"
    echo "⏰ Started at: $(date)"
    echo "============================================================"
    
    # Run the training (tee shows output on screen AND saves to log)
    python train_regime_aware_lgb.py --symbol "$symbol" --days $DAYS --trials $TRIALS --timeout $TIMEOUT --gpu 2>&1 | tee "$logfile"
    
    # Check if it succeeded
    if [ $? -eq 0 ]; then
        echo "✅ $symbol completed successfully"
        # Extract final accuracy from log
        tail -20 "$logfile" | grep -E "Final accuracy:|accuracy:" || echo "   (Check log for details)"
    else
        echo "❌ $symbol failed - check $logfile for errors"
    fi
    
    echo "⏰ Finished at: $(date)"
}

# Train each symbol
train_symbol "FARTCOIN"
train_symbol "BONK"
train_symbol "JUP"
train_symbol "ORCA"
train_symbol "PYTH"
train_symbol "RAY"
train_symbol "MNDE"
train_symbol "\$WIF"  # Escape the $ sign
train_symbol "POPCAT"
train_symbol "MEW"
train_symbol "W"
train_symbol "JTO"
train_symbol "PENGU"
train_symbol "SPX"
train_symbol "TRUMP"
train_symbol "VIRTUAL"
train_symbol "RENDER"

echo ""
echo "============================================================"
echo "🎉 All training complete!"
echo "📊 Check logs/lgb_training/ for detailed results"
echo "⏰ Finished at: $(date)"
echo "============================================================"

# Optional: Generate summary report
echo ""
echo "📊 Summary Report:"
echo "=================="
for logfile in logs/lgb_training/*_optimization_*.log; do
    if [ -f "$logfile" ]; then
        symbol=$(basename "$logfile" | cut -d'_' -f1)
        if grep -q "Final accuracy:" "$logfile"; then
            accuracy=$(grep "Final accuracy:" "$logfile" | tail -1)
            echo "$symbol: $accuracy"
        else
            echo "$symbol: Check log file"
        fi
    fi
done 