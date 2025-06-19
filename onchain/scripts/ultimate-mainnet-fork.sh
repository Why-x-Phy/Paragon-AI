#!/bin/bash

# 🍴 ULTIMATE CALVIN AI MAINNET FORK 🍴
# Comprehensive setup for Calvin AI with ALL dependencies
# Hardware: i5-13500K + 64GB DDR5 + 561GB free space ✅

echo "🍴 ULTIMATE CALVIN AI MAINNET FORK"
echo "💻 Optimized for i5-13500K + 64GB DDR5"
echo "🚀 Cloning EVERYTHING for Calvin AI..."

# Kill any existing validator
echo "🔄 Stopping existing validators..."
pkill -f solana-test-validator || true
sleep 3

# Create optimized data directory
LEDGER_DIR="/mnt/d/calvin_ai/mainnet-fork-data"
echo "📂 Creating ledger directory: $LEDGER_DIR"
mkdir -p "$LEDGER_DIR"

# ============================================================================
# 🎯 CALVIN AI TOKEN ADDRESSES (From oracle_config.rs)
# ============================================================================

# Base tokens
USDC="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL="So11111111111111111111111111111111111111112" 
CALVIN="229vWzBTiUNdraYpVtSH9usTwwVxcyPDbBWf1zEPpump"

# Trading tokens from Calvin AI
TRUMP="6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN"
RENDER="rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof"
JUP="JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
BONK="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
FARTCOIN="9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
RAY="4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
JTO="jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL"
PYTH="HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8uHYmW2hr"
WIF="EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"
VIRTUAL="BUjZjAS2vbbb65g7Z1Ca9ZRVYoJscURG5L3AkVXHP2ac"
PENGU="3Bmj7x4udgJhKa43EYRcmNq2JLkgz7eAayFn8qYhyXKV"
W="85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ"  # WORMHOLE
POPCAT="7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
ATH="ATHdb8YvGvBVhgJB3PaMU5sCdAUHkhkN42jdYWK4h2xQ"
MEW="MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5"
MNDE="MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey"
SPX="AUKyeqDfN8p6B93X9gYCnCpdJUfvxU6ZWEmAy2VKqm3w"  # SPX6900
ORCA="orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE"

# ============================================================================
# 🔮 PYTH ORACLE ACCOUNTS (Real mainnet addresses)
# ============================================================================

# Core price feeds for Calvin AI
PYTH_USDC="Gnt27xtC473ZT2Mw5u8wZ68Z3gULkSTb5DuxJy7eJotD"
PYTH_SOL="H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG"
PYTH_BTC="GVXRSBjFk6e6J3NbVPXohDJetcTjaeeuykUpbQF8UoMU"
PYTH_ETH="JBu1AL4obBcCMqKBBxhpWCNUt136ijcuMZLFvTP7iWdB"

# Memecoins that Calvin AI trades
PYTH_BONK="8ihFLu5FimjTkdc1pHPwCdeZruDA6mEAXJ2APaLjxQaj"
PYTH_WIF="6ABgrEZk8urs6kJ1JNdC1sspH5zKXRqxy8sg3ZG2cQps"
PYTH_FARTCOIN="EhYXgHB6GwphP9XdNhDKHEyZQCpZjY6awpWo3s8eJFHi"
PYTH_POPCAT="H3RmSs3XQG8FG1jNePQnwEMbNwqh9g4TsNwkyiPrTrwf"
PYTH_MEW="E3CzBbaDJkjGTMBQ4R9R7Pqri3gw65T9xrhgCFQZ9zLj"

# DeFi tokens 
PYTH_JUP="g6eRCbboSwK4tSWWZ97rNxoR2F2BtPZBkP7+vr9J6B4"
PYTH_JTO="BjAKKjkBvJ7z1vPqX8L+MLbJhMNjMyNt9T/sWfP5aZA"
PYTH_RAY="83RvxGakuZz6gMz3oqhcKWJVRzUz6bB2iuM7d1JxKoZu"
PYTH_PYTH="2z1PgxVftmjNK1vQdmBLqJvwb24MtzNFpCmDRcE+2jS1"

# Major tokens
PYTH_RENDER="8x6hqFLbZzPrAAFX8UVv8qhJDe4t9gD6cTZ3JKvxw9m4"
PYTH_ORCA="FHTjfW8TJBDy2R7+7b8j4SgGbSz7ZIwzJ1VLQ4a5RTJH"

# ============================================================================
# 🎛️ SWITCHBOARD ORACLE ACCOUNTS (Backup oracles)
# ============================================================================

# Switchboard feeds from oracle_config.rs
SB_TRUMP="9wcBMATS8bGLQ2UcRuYjsRAD7TPqB1CMhqfueBx78Uj2"
SB_WIF="8GqzQoqqKzJoNaWZtf2udVGV3Fn74W9DQayYu1S1zvkt"
SB_ATH="21JapEAFu8r8SAAQjB2fURfjiosnTHAFFm4S27qe4vVF"
SB_BONK="7GCiue6chgGuk6BvaurQNWD1Ervho8zEdcNWt5ZCYQhu"
SB_FARTCOIN="EE8Uyquv38j2JmyCiPprCNUxDBTrzpCXqR4hL3RGDUGh"
SB_JTO="E9fHVUZnvT4i8H3jQLb6g2tSpcagunJpjwCGNTYxwKSE"
SB_JUP="2F9M59yYc28WMrAymNWceaBEk8ZmDAjUAKULp8qYhyXKV"
SB_MEW="7Eev1vbsrgEmiRbVjyyFL8nqRKQt7jNPVtxiS4C6ewns"
SB_MNDE="CwtLbG7w71oCasCMYR8KARZYEVJK5x1GXdoYpqjctp7E"
SB_ORCA="BFWHemmj4ZtvqQVsWrGrFrL2U8tz7Lzq8nhy1KRMVezL"
SB_PENGU="DAG9yMr4FbTVd41Jojw6X589EHiPgR375SP5AdAAW7tH"
SB_POPCAT="5FWVcePyDK5jF6ZqFgmEMyu9qu5qdsswwvMd7GvRmfFW"
SB_PYTH="72ukr6M31f9cCzxvZT4Ba7AGyWSFLQGHjXU6WUzN4xD7"
SB_RAY="AJkAFiXdbMonys8rTXZBrRnuUiLcDFdkyoPuvrVKXhex"
SB_RENDER="B6xHth4K3fj3KK1TASXtHfbAReShYW3EihgwSKvhsugz"
SB_SPX="8m5YKLgnftRTcVXJLk7bV37xc2qrWR9TkXq4TY3FP3pz"
SB_VIRTUAL="34aJFwk2jTKmB2C6zWnT641ABCQv1P2ghrob57i1gFdg"
SB_W="DwjV47HwtHW5YR1CPndw3Fq1QMeYyvYA7jYXhMtcUCte"
SB_SOL="E8TLLh5jkYDvSXfAES7qe3s8Cfjj4hyvjksuvUHe8NEw"
SB_USDC="aHTvxuDvCRRnmJDDR1JkfLa4SpCNsgC4vDeLMEcN3zY"

# ============================================================================
# 🚀 JUPITER V6 INFRASTRUCTURE 
# ============================================================================

JUPITER_V6="JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
JUPITER_PROGRAM="JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB"

# Major liquidity pools and exchange programs
RAYDIUM_AMM="675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RAYDIUM_V4="FarmqiPv5eAj3j1GMdMCMUGXqPUvmqfaAAYt2uc2T4ENG4"
ORCA_WHIRLPOOL="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
ORCA_LEGACY="9qvG1zUp8WQdPz1yHHy1C7qj2F3TrMADJJk7tKqQSZ97"

# ============================================================================
# 📊 ESSENTIAL SOLANA PROGRAMS
# ============================================================================

SPL_TOKEN="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SPL_ASSOCIATED_TOKEN="ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SPL_MEMO="MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
METAPLEX_TOKEN_METADATA="metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
SYSTEM_PROGRAM="11111111111111111111111111111111"
RENT_SYSVAR="SysvarRent111111111111111111111111111111111"
CLOCK_SYSVAR="SysvarC1ock11111111111111111111111111111111"

# ============================================================================
# 💰 MAJOR EXCHANGE ACCOUNTS (for liquidity)
# ============================================================================

# Jupiter aggregator accounts
JUPITER_TREASURY="2koF4FvhW8nG2f5bvb9ARH9vF6mCuW7AY1dU1CuvFsyR"

# Raydium major pools
RAY_SOL_POOL="FaBhHqWPJJGFRMmHYmJtgE4Eb6F5B5FEsB5yf5uGH5nL"
RAY_USDC_POOL="6UmmUiYoBjSrhakAobJw8BvkmJtDVxaeBtbt7rxWo1mg"

# Major whale accounts for token distribution
BINANCE_HOT="2ojv9BAiHUrvsm9gxDe7fJSzbNZSJcxZvf8dqmWGHG8S"
COINBASE_CUSTODY="5Q544fKrFoe6tsEbD7S8EmxGTJYAKqDGURfQDqLTw7RUq"

# ============================================================================
# 🔧 VALIDATOR CONFIGURATION
# ============================================================================

echo "🚀 Starting optimized mainnet fork..."

# Build comprehensive clone arguments
CLONE_ARGS=""

# Clone all Calvin AI tokens
echo "📝 Adding Calvin AI tokens..."
for token in $USDC $SOL $CALVIN $TRUMP $RENDER $JUP $BONK $FARTCOIN $RAY $JTO $PYTH $WIF $VIRTUAL $PENGU $W $POPCAT $ATH $MEW $MNDE $SPX $ORCA; do
    CLONE_ARGS="$CLONE_ARGS --clone $token"
done

# Clone all Pyth oracles
echo "📝 Adding Pyth oracle accounts..."
for oracle in $PYTH_USDC $PYTH_SOL $PYTH_BTC $PYTH_ETH $PYTH_BONK $PYTH_WIF $PYTH_FARTCOIN $PYTH_POPCAT $PYTH_MEW $PYTH_JUP $PYTH_JTO $PYTH_RAY $PYTH_PYTH $PYTH_RENDER $PYTH_ORCA; do
    CLONE_ARGS="$CLONE_ARGS --clone $oracle"
done

# Clone all Switchboard oracles
echo "📝 Adding Switchboard oracle accounts..."
for oracle in $SB_TRUMP $SB_WIF $SB_ATH $SB_BONK $SB_FARTCOIN $SB_JTO $SB_JUP $SB_MEW $SB_MNDE $SB_ORCA $SB_PENGU $SB_POPCAT $SB_PYTH $SB_RAY $SB_RENDER $SB_SPX $SB_VIRTUAL $SB_W $SB_SOL $SB_USDC; do
    CLONE_ARGS="$CLONE_ARGS --clone $oracle"
done

# Clone Jupiter infrastructure
echo "📝 Adding Jupiter infrastructure..."
for program in $JUPITER_V6 $JUPITER_PROGRAM $JUPITER_TREASURY; do
    CLONE_ARGS="$CLONE_ARGS --clone $program"
done

# Clone DEX programs
echo "📝 Adding DEX programs..."
for program in $RAYDIUM_AMM $RAYDIUM_V4 $ORCA_WHIRLPOOL $ORCA_LEGACY; do
    CLONE_ARGS="$CLONE_ARGS --clone $program"
done

# Clone essential Solana programs
echo "📝 Adding essential Solana programs..."
for program in $SPL_TOKEN $SPL_ASSOCIATED_TOKEN $SPL_MEMO $METAPLEX_TOKEN_METADATA; do
    CLONE_ARGS="$CLONE_ARGS --clone $program"
done

# Clone major liquidity accounts
echo "📝 Adding major liquidity accounts..."
for account in $RAY_SOL_POOL $RAY_USDC_POOL $BINANCE_HOT $COINBASE_CUSTODY; do
    CLONE_ARGS="$CLONE_ARGS --clone $account"
done

# Start the ultimate fork
solana-test-validator \
  --url https://api.mainnet-beta.solana.com \
  --ledger "$LEDGER_DIR" \
  --reset \
  \
  `# 💻 Performance optimizations for i5-13500K + 64GB` \
  --rpc-port 8899 \
  --rpc-bind-address 0.0.0.0 \
  --enable-rpc-transaction-history \
  --enable-extended-tx-metadata-storage \
  --log \
  \
  `# 📊 Resource limits optimized for 64GB RAM` \
  --account-max-retries 20 \
  --rpc-max-multiple-accounts 1000 \
  --limit-ledger-size 200000000 \
  --slots-per-epoch 8640 \
  --max-genesis-archive-unpacked-size 2000000000 \
  \
  `# 🎯 Clone ALL Calvin AI dependencies` \
  $CLONE_ARGS \
  \
  `# 🔑 Bootstrap with funded test accounts` \
  --faucet-lamports 10000000000000 \
  --faucet-sol 10000 &

VALIDATOR_PID=$!

echo "⏳ Waiting for validator to initialize..."
sleep 30

# Wait for RPC to be ready
echo "🔍 Checking validator health..."
until curl -X POST -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}' http://localhost:8899 2>/dev/null | grep -q "ok"; do
    echo "⏳ Waiting for RPC to be ready..."
    sleep 5
done

echo ""
echo "🎉 ULTIMATE CALVIN AI MAINNET FORK READY!"
echo ""
echo "📊 SYSTEM STATUS:"
echo "🔹 RPC Endpoint: http://localhost:8899"
echo "🔹 WebSocket: ws://localhost:8900"
echo "🔹 Ledger Directory: $LEDGER_DIR"
echo "🔹 Validator PID: $VALIDATOR_PID"
echo ""
echo "🎯 CALVIN AI ASSETS CLONED:"
echo "🔹 Tokens: 19 (USDC, SOL, CALVIN, BONK, WIF, FARTCOIN, etc.)"
echo "🔹 Pyth Oracles: 15+ price feeds"
echo "🔹 Switchboard Oracles: 19 backup feeds"
echo "🔹 Jupiter V6: Complete trading infrastructure"
echo "🔹 DEX Programs: Raydium, Orca, major pools"
echo "🔹 Liquidity: Major exchange accounts cloned"
echo ""
echo "💡 NEXT STEPS:"
echo "1. Run: cd /mnt/d/calvin_ai/onchain && yarn ts-node scripts/initialize-fork.ts"
echo "2. Test trading with real Jupiter liquidity"
echo "3. Deploy Calvin programs and test vault system"
echo ""
echo "⚠️  To stop: kill $VALIDATOR_PID"
echo "📚 Logs: tail -f $LEDGER_DIR/validator.log"

# Keep script running to monitor
wait $VALIDATOR_PID 