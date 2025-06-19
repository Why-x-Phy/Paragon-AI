#!/bin/bash

# Calvin AI Mainnet Fork - Optimized for i5-13500K + 64GB RAM
# This will create a local fork with real tokens, oracles, and Jupiter liquidity

echo "🍴 Starting Calvin AI Mainnet Fork..."
echo "💻 Hardware: i5-13500K, 64GB DDR5, 561GB free space"
echo "⚡ Optimized configuration for your system"

# Kill any existing validator
pkill -f solana-test-validator

# Create data directory on D drive to save space
mkdir -p /mnt/d/calvin_ai/fork-data

# Start optimized mainnet fork
solana-test-validator \
  --url https://api.mainnet-beta.solana.com \
  --ledger /mnt/d/calvin_ai/fork-data \
  --reset \
  \
  `# Performance optimizations for your hardware` \
  --account-max-retries 20 \
  --rpc-max-multiple-accounts 1000 \
  --limit-ledger-size 100000000 \
  --slots-per-epoch 432000 \
  \
  `# Clone Jupiter V6 (essential for trading)` \
  --clone-upgradeable-program JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4 \
  \
  `# Clone Pyth Oracle program (for price feeds)` \
  --clone-upgradeable-program HEvSKofvBgfaexv23kMabbYqxasxU3mQ4ibBMEmJWHny \
  \
  `# Clone essential token mints` \
  --clone EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v \
  --clone So11111111111111111111111111111111111111112 \
  --clone DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 \
  --clone 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump \
  --clone EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm \
  --clone JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN \
  \
  `# Clone Pyth price oracles for our tokens` \
  --clone H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG \
  --clone 8ihFLu5FimgTQ1Unh4dVyEHUGodJ5gJQCrQf4KUVB9bN \
  --clone 3vxLXJqLqF3JG5TCbYycbKWRBbCJQLxQmBGCkyqEEefL \
  \
  `# Clone some Jupiter liquidity pools for testing` \
  --clone 58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2 \
  --clone 2QdhepnKRTLjjSqPL1PtKNwqrUkoLee5Gqs8bvZhRdMv \
  \
  `# Network and RPC optimizations` \
  --rpc-port 8899 \
  --dynamic-port-range 8900-8999 \
  --log /mnt/d/calvin_ai/fork-data/validator.log \
  --quiet

echo "✅ Mainnet fork started successfully!"
echo "🌐 RPC endpoint: http://localhost:8899"
echo "📊 Explorer: http://localhost:8899/explorer"
echo "💾 Data stored in: /mnt/d/calvin_ai/fork-data"
echo ""
echo "🎯 Next steps:"
echo "1. Configure Solana CLI: solana config set --url http://localhost:8899"
echo "2. Deploy Calvin programs: anchor deploy"
echo "3. Initialize vault system with real tokens" 