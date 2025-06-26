#!/bin/bash

# 🚀 Calvin AI Complete Mainnet Initialization 🚀
# Initializes vault + staking + ALL trading token accounts with Calvin AI authority

set -e  # Exit on any error

echo "🚀 CALVIN AI COMPLETE MAINNET INITIALIZATION"
echo "⚠️  CRITICAL: This involves REAL MONEY!"
echo "🎯 Will initialize ALL trading tokens from oracle config"
echo ""

# Check we're in the onchain directory
if [ ! -f "Anchor.toml" ]; then
    echo "❌ Please run from the onchain directory"
    exit 1
fi

# Check wallet balance
echo "📊 Checking wallet balance..."
BALANCE=$(solana balance --url mainnet-beta | grep -o '[0-9.]*')
REQUIRED_BALANCE=2

if (( $(echo "$BALANCE < $REQUIRED_BALANCE" | bc -l) )); then
    echo "❌ Insufficient balance: $BALANCE SOL (need $REQUIRED_BALANCE SOL)"
    echo "💡 More SOL needed for creating all trading token accounts"
    exit 1
fi

echo "✅ Wallet balance: $BALANCE SOL"

# Verify programs exist
echo ""
echo "🔍 Verifying deployed programs..."

VAULT_PROGRAM="tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z"
STAKING_PROGRAM="8kMj6gYFVUC3Ya6qwu3tyaZweyXUUuR8t8aCtA47aX7W"

if ! solana program show $VAULT_PROGRAM --url mainnet-beta > /dev/null 2>&1; then
    echo "❌ Vault program not found: $VAULT_PROGRAM"
    exit 1
fi

if ! solana program show $STAKING_PROGRAM --url mainnet-beta > /dev/null 2>&1; then
    echo "❌ Staking program not found: $STAKING_PROGRAM"
    exit 1
fi

echo "✅ Both programs verified on mainnet"

# Check for Calvin AI authority keypair
echo ""
echo "🔍 Checking for Calvin AI authority keypair..."

CALVIN_AI_PUBKEY="8mxVsgQQ6kkbfZ7t2AvxBh7jqQd7Lu2kg8bPvLwA1het"
KEYPAIR_FOUND=false

# Check possible locations
if [ -f "./calvin-ai-authority.json" ]; then
    echo "✅ Found: ./calvin-ai-authority.json"
    KEYPAIR_FOUND=true
elif [ -f "./scripts/calvin-ai-authority.json" ]; then
    echo "✅ Found: ./scripts/calvin-ai-authority.json"
    KEYPAIR_FOUND=true
elif [ -f "/home/ubuntu/calvin-ai-authority.json" ]; then
    echo "✅ Found: /home/ubuntu/calvin-ai-authority.json"
    KEYPAIR_FOUND=true
elif [ -f "/home/ubuntu/.config/solana/calvin-ai-authority.json" ]; then
    echo "✅ Found: /home/ubuntu/.config/solana/calvin-ai-authority.json"
    KEYPAIR_FOUND=true
fi

if [ "$KEYPAIR_FOUND" = false ]; then
    echo "❌ Calvin AI authority keypair not found!"
    echo "💡 Expected pubkey: $CALVIN_AI_PUBKEY"
    echo "💡 Please place calvin-ai-authority.json in one of these locations:"
    echo "   - ./calvin-ai-authority.json"
    echo "   - ./scripts/calvin-ai-authority.json"
    echo "   - /home/ubuntu/calvin-ai-authority.json"
    exit 1
fi

# Build programs to generate IDLs
echo ""
echo "🔨 Building programs to generate IDLs..."
anchor build

# Count trading tokens
echo ""
echo "📊 Trading Tokens Configuration:"
echo "   USDC, SOL (base)"
echo "   TRUMP (political)"
echo "   RENDER, JUP, RAY, JTO, PYTH, ORCA, MNDE (DeFi)"
echo "   BONK, FARTCOIN, WIF, VIRTUAL, PENGU, POPCAT, ATH, MEW, SPX (memecoins)"
echo "   W (cross-chain)"
echo "   Total: ~19 trading tokens"

# Final warnings
echo ""
echo "⚠️  CRITICAL WARNINGS ⚠️"
echo "1. This will create ~19 token accounts (~0.5 SOL total)"
echo "2. Calvin AI authority will be set to: $CALVIN_AI_PUBKEY"
echo "3. Emergency owner will be set to your current wallet"
echo "4. Treasury will be set to: 2zGsubjG1i1VXem7ADkS1KAT6ryFTdPQboozPK6EufMQ"
echo "5. Per NFT cap set to: 500 USDC"
echo "6. This is MAINNET with REAL MONEY"
echo ""

# Final confirmation
read -p "Ready to initialize complete Calvin Vault system? (type 'YES'): " CONFIRM

if [ "$CONFIRM" != "YES" ]; then
    echo "❌ Aborted by user"
    exit 1
fi

# Run the initialization
echo ""
echo "🚀 Starting complete initialization..."
echo "⏱️  This may take several minutes..."
echo ""

# Use npx/yarn to run the TypeScript file
if command -v yarn &> /dev/null; then
    yarn ts-node scripts/initialize-mainnet-complete.ts
elif command -v npx &> /dev/null; then
    npx ts-node scripts/initialize-mainnet-complete.ts
else
    echo "❌ Neither yarn nor npx found. Please install Node.js/npm or yarn"
    exit 1
fi

echo ""
echo "🎉 COMPLETE INITIALIZATION FINISHED!"
echo ""
echo "📄 Check mainnet-complete-deployment.json for all addresses"
echo "🎯 All trading token accounts have been created"
echo "🤖 Calvin AI authority: $CALVIN_AI_PUBKEY"
echo "💰 Treasury: 2zGsubjG1i1VXem7ADkS1KAT6ryFTdPQboozPK6EufMQ"
echo "🎫 Per NFT cap: 500 USDC"
echo ""
echo "🚀 Your Calvin Vault is now FULLY operational on mainnet!"
echo "💰 Ready for production trading with all supported tokens" 