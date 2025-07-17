#!/bin/bash

# =============================================================================
# Calvin AI Overnight Model Training Script
# =============================================================================
# This script trains models for multiple tokens sequentially with GPU cooling
# breaks between sessions. Configure tokens below and run overnight.

set -e  # Exit on any error

# =============================================================================
# CONFIGURATION - Edit these tokens as needed
# =============================================================================

# Token configurations: "TOKEN_ADDRESS:SYMBOL"
TOKENS=(
    "J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr:SPX"
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm:\$WIF"
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE:ORCA"
    "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN:TRUMP"
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263:Bonk"
    "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey:MNDE"
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE:ORCA"
    "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5:MEW"
    "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ:W"
    "3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y:VIRTUAL"
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3:PYTH"
    "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL:JTO"
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R:RAY"
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN:JUP"
    "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof:RENDER"
    "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump:Fartcoin"
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr:POPCAT"
    
)

# Training parameters (updated for regime-aware lgb model training)
DAYS=180
COOLING_MINUTES=0

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

train_model() {
    local token_address=$1
    local symbol=$2
    
    log "🚀 Starting regime-aware lgb model training for $symbol ($token_address)"
    log "⚙️  Training parameters: ${DAYS} days of data"
    
    # Run regime-aware lgb training command
    python train_regime_aware_lgb.py \
        --token-address "$token_address" \
        --symbol "$symbol" \
        --days "$DAYS" 
    
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log "✅ Successfully completed regime-aware lgb training for $symbol"
    else
        log "❌ regime-aware lgb training failed for $symbol (exit code: $exit_code)"
        return $exit_code
    fi
}

cooling_break() {
    log "🌡️  GPU cooling break: waiting ${COOLING_MINUTES} minutes..."
    for i in $(seq $COOLING_MINUTES -1 1); do
        echo -ne "\r⏰ Cooling down... ${i} minutes remaining  "
        sleep 60
    done
    echo -e "\r✅ Cooling break complete!                    "
}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

log "🌙 Starting overnight regime-aware lgb model training session"
log "📊 Will train ${#TOKENS[@]} models with ${COOLING_MINUTES}-minute cooling breaks"
log "💾 Models will be saved to: $(pwd)/models/"

# Record start time
start_time=$(date +%s)

# Train each token
for i in "${!TOKENS[@]}"; do
    # Parse token configuration
    IFS=':' read -r token_address symbol <<< "${TOKENS[i]}"
    
    current_num=$((i + 1))
    total_num=${#TOKENS[@]}
    
    log "📈 [${current_num}/${total_num}] Processing: $symbol"
    
    # Train the model
    if train_model "$token_address" "$symbol"; then
        log "🎯 regime-aware lgb model training completed for $symbol"
        
        # Cooling break (except after the last model)
        if [ $current_num -lt $total_num ]; then
            cooling_break
        fi
    else
        log "⚠️  Skipping to next token due to training failure"
        
        # Still do cooling break to let GPU recover
        if [ $current_num -lt $total_num ]; then
            cooling_break
        fi
    fi
    
    log "────────────────────────────────────────────────────────────"
done

# Calculate total time
end_time=$(date +%s)
total_minutes=$(( (end_time - start_time) / 60 ))
hours=$((total_minutes / 60))
minutes=$((total_minutes % 60))

log "🏁 Overnight regime-aware lgb model training session completed!"
log "⏱️  Total time: ${hours}h ${minutes}m"
log "📁 Check the models/ directory for your new regime-aware lgb models"
log "💤 Sweet dreams! Your regime-aware lgb models are ready for testing."

# List generated models
log "📋 Generated model files:"
ls -la models/*.pkl 2>/dev/null | tail -20 || log "No .pkl model files found" 