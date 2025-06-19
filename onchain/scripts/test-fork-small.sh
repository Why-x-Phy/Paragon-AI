#!/bin/bash

# 🧪 SMALL TEST FORK - Just to See if It Works
# Let's clone just a few key things to test the concept

echo "🧪 Testing Mainnet Fork Concept..."
echo "💡 This is just a small test - only cloning a few accounts"

# Kill any existing validator
pkill -f solana-test-validator || true
sleep 2

# Create test directory
TEST_DIR="/mnt/d/calvin_ai/test-fork-data"
echo "📂 Creating test directory: $TEST_DIR"
mkdir -p "$TEST_DIR"

# Just clone a few key accounts for testing
USDC="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL="So11111111111111111111111111111111111111112" 
BONK="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
PYTH_SOL="H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG"
JUPITER_V6="JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"

echo "🔄 Starting SMALL test fork..."
echo "📝 Only cloning: USDC, SOL, BONK, 1 oracle, Jupiter"

# Start minimal fork
solana-test-validator \
  --url https://api.mainnet-beta.solana.com \
  --ledger "$TEST_DIR" \
  --reset \
  --rpc-port 8899 \
  --log \
  --clone $USDC \
  --clone $SOL \
  --clone $BONK \
  --clone $PYTH_SOL \
  --clone $JUPITER_V6 &

VALIDATOR_PID=$!

echo "⏳ Waiting for test validator to start..."
sleep 15

# Check if it's working
echo "🔍 Testing connection..."
if curl -X POST -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}' http://localhost:8899 2>/dev/null | grep -q "ok"; then
    echo ""
    echo "🎉 TEST FORK WORKING!"
    echo ""
    echo "✅ Successfully cloned 5 accounts from mainnet"
    echo "✅ Validator running on http://localhost:8899"
    echo "✅ PID: $VALIDATOR_PID"
    echo ""
    echo "🧪 Test Commands:"
    echo "solana account $USDC --url http://localhost:8899"
    echo "solana account $BONK --url http://localhost:8899"
    echo ""
    echo "⚠️  To stop: kill $VALIDATOR_PID"
    echo "💾 Data stored in: $TEST_DIR"
    echo ""
    echo "💡 If this works, we can run the full version!"
else
    echo "❌ Test failed - validator didn't start properly"
    echo "💡 Check the logs or try again"
    kill $VALIDATOR_PID 2>/dev/null
fi

# Keep running
wait $VALIDATOR_PID 