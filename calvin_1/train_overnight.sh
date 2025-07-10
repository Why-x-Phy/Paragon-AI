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
    "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv:PENGU"
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
    
)

# Training parameters (updated for improved model training)
EPOCHS=50
DAYS=60
OPTIMIZATION_TARGET="direction_focused"
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
    
    log "🚀 Starting improved model training for $symbol ($token_address)"
    log "⚙️  Training parameters: ${EPOCHS} epochs, ${DAYS} days of data, ${OPTIMIZATION_TARGET} optimization"
    
    # Run improved training command with direction-focused optimization
    python train_improved_model.py \
        --token-address "$token_address" \
        --symbol "$symbol" \
        --days "$DAYS" \
        --epochs "$EPOCHS" \
        --optimization-target "$OPTIMIZATION_TARGET"
    
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log "✅ Successfully completed improved training for $symbol"
    else
        log "❌ Improved training failed for $symbol (exit code: $exit_code)"
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

log "🌙 Starting overnight improved model training session"
log "📊 Will train ${#TOKENS[@]} models with ${COOLING_MINUTES}-minute cooling breaks"
log "🎯 Using ${OPTIMIZATION_TARGET} optimization for better direction accuracy"
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
        log "🎯 Improved model training completed for $symbol"
        
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

log "🏁 Overnight improved model training session completed!"
log "⏱️  Total time: ${hours}h ${minutes}m"
log "📁 Check the models/ directory for your new direction-focused models"
log "💤 Sweet dreams! Your improved models are ready for testing."

# List generated models
log "📋 Generated model files:"
ls -la models/*.h5 2>/dev/null | tail -3 || log "No .h5 model files found" 