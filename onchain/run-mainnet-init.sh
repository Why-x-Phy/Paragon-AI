#!/bin/bash

# 🚀 Calvin AI Mainnet Initialization Script 🚀
# CRITICAL: This initializes the production vault with REAL MONEY

set -e  # Exit on any error

echo "🚀 CALVIN AI MAINNET INITIALIZATION"
echo "⚠️  CRITICAL: This involves REAL MONEY!"
echo ""

# Check we're in the onchain directory
if [ ! -f "Anchor.toml" ]; then
    echo "❌ Please run from the onchain directory"
    exit 1
fi

# Check wallet balance
echo "📊 Checking wallet balance..."
BALANCE=$(solana balance --url mainnet-beta | grep -o '[0-9.]*')
REQUIRED_BALANCE=5

if (( $(echo "$BALANCE < $REQUIRED_BALANCE" | bc -l) )); then
    echo "❌ Insufficient balance: $BALANCE SOL (need $REQUIRED_BALANCE SOL)"
    exit 1
fi

echo "✅ Wallet balance: $BALANCE SOL"

# Verify programs exist
echo ""
echo "🔍 Verifying deployed programs..."

VAULT_PROGRAM="HsRMhLLDiwAcAiLcYFmsSoE4Pz1Din4aW75TwP7usPCm"
STAKING_PROGRAM="5RBEFruhEtwXaXR6nMLxM94t9yEUcSZbtoR33rP22oqZ"

if ! solana program show $VAULT_PROGRAM --url mainnet-beta > /dev/null 2>&1; then
    echo "❌ Vault program not found: $VAULT_PROGRAM"
    exit 1
fi

if ! solana program show $STAKING_PROGRAM --url mainnet-beta > /dev/null 2>&1; then
    echo "❌ Staking program not found: $STAKING_PROGRAM"
    exit 1
fi

echo "✅ Both programs verified on mainnet"

# Build programs to generate IDLs
echo ""
echo "🔨 Building programs to generate IDLs..."
anchor build

# Warning about configuration
echo ""
echo "⚠️  CRITICAL CONFIGURATION CHECK ⚠️"
echo ""
echo "Before proceeding, you MUST edit the script to set:"
echo "1. Calvin AI Authority address (the wallet that executes trades)"
echo "2. Treasury address (where fees are collected)"
echo ""
echo "These are on lines 54-57 in initialize-mainnet-final.ts"
echo ""
read -p "Have you configured the authority addresses? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Please configure the addresses first"
    exit 1
fi

# Final confirmation
echo ""
echo "🚨 FINAL CONFIRMATION 🚨"
echo "This will initialize Calvin Vault & Staking on MAINNET with REAL MONEY"
echo ""
read -p "Are you absolutely sure you want to proceed? (type 'YES'): " CONFIRM

if [ "$CONFIRM" != "YES" ]; then
    echo "❌ Aborted by user"
    exit 1
fi

# Run the initialization
echo ""
echo "🚀 Starting initialization..."
echo ""

# Use npx/yarn to run the TypeScript file
if command -v yarn &> /dev/null; then
    yarn ts-node scripts/initialize-mainnet-final.ts
elif command -v npx &> /dev/null; then
    npx ts-node scripts/initialize-mainnet-final.ts
else
    echo "❌ Neither yarn nor npx found. Please install Node.js/npm or yarn"
    exit 1
fi

echo ""
echo "🎉 INITIALIZATION COMPLETE!"
echo "📄 Check mainnet-deployment.json for all addresses"
echo ""
echo "🚀 Your Calvin Vault is now live on mainnet!" 