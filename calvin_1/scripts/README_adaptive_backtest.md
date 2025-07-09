# Adaptive Strategy Backtest

This script simulates how the Calvin AI adaptive strategy would have performed historically by dynamically adjusting trading thresholds based on market conditions and performance.

## What Makes It "Adaptive"?

Unlike traditional backtests that use fixed thresholds throughout the entire test period, this backtest simulates the adaptive strategy engine's behavior:

1. **Dynamic Threshold Adjustment**: Buy/sell thresholds change over time based on:
   - Market volatility (high volatility → higher thresholds)
   - Recent performance (poor win rate → higher thresholds)
   - Market momentum (trending markets → adjusted thresholds)
   - Market regime (different settings for different market conditions)

2. **Path Dependency**: The backtest accurately simulates how:
   - Early trades affect later threshold adjustments
   - Performance history influences future parameters
   - Market conditions at each point in time drive adaptations

3. **Realistic Constraints**: 
   - Adaptations only occur after minimum signals (default: 5)
   - Smoothing prevents wild parameter swings
   - Thresholds stay within reasonable bounds (0.2%-3% buy, 0.3%-4% sell)

## Usage

```bash
# Basic adaptive backtest
python scripts/backtest_adaptive.py --token-address 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump --symbol Fartcoin --days 30

# With plots and comparison to static strategy
python scripts/backtest_adaptive.py --token-address 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump --symbol Fartcoin --days 30 --plot --compare

# Custom resolution
python scripts/backtest_adaptive.py --token-address 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump --symbol Fartcoin --days 30 --resolution 1H --plot
```

## Parameters

- `--token-address`: Solana token address (required)
- `--symbol`: Token symbol (default: SOL)
- `--days`: Days of historical data to test (default: 30)
- `--resolution`: Data resolution - 1H, 4H, etc (default: 1H)
- `--model-path`: Path to specific model (uses latest if not specified)
- `--plot`: Generate visualization plots
- `--compare`: Compare results with static strategy

## Output

The script provides:

1. **Performance Metrics**:
   - Total return vs buy & hold
   - Win rate
   - Maximum drawdown
   - Number of trades and adaptations

2. **Adaptation History**:
   - When thresholds were adjusted
   - Market conditions at adaptation points
   - Performance metrics at each adaptation

3. **Visualizations** (with --plot):
   - Portfolio value over time
   - Threshold evolution chart
   - Trade returns distribution
   - Market regime analysis

## Example Output

```
============================================================
ADAPTIVE STRATEGY BACKTEST RESULTS
============================================================
Total Return: 12.45%
Buy & Hold Return: 8.32%
Win Rate: 58.33%
Max Drawdown: 6.21%
Total Trades: 24
Total Adaptations: 18
Outperformance vs Buy & Hold: 4.13%

------------------------------------------------------------
SAMPLE ADAPTATIONS
------------------------------------------------------------
Adaptation 1:
  Buy Threshold: 0.80%
  Sell Threshold: 1.20%
  Market Regime: low_volatility
  Volatility: 0.85%
  Win Rate at Time: 0.00%

Adaptation 2:
  Buy Threshold: 1.25%
  Sell Threshold: 1.88%
  Market Regime: high_volatility
  Volatility: 2.45%
  Win Rate at Time: 66.67%
```

## How It Works

1. **Market Analysis**: At each time step, the script analyzes:
   - 24-hour volatility (rolling standard deviation)
   - 24-hour momentum (price change)
   - Market regime classification

2. **Adaptation Logic**: Every hour (configurable), the system:
   - Evaluates recent performance
   - Analyzes current market conditions
   - Adjusts thresholds using multiple methods:
     - Volatility-based: Higher volatility → higher thresholds
     - Performance-based: Poor win rate → higher thresholds
     - Momentum-based: Strong trends → adjusted entry/exit points

3. **Smoothing**: Changes are smoothed (30% weight) to prevent:
   - Overreaction to short-term conditions
   - Oscillation between extreme values
   - Unrealistic parameter jumps

## Comparison with Static Backtest

The `--compare` flag runs both adaptive and static backtests to show the improvement:

```
IMPROVEMENT WITH ADAPTIVE STRATEGY
------------------------------------------------------------
Return Improvement: 3.21%
Win Rate Improvement: 5.44%
Drawdown Improvement: 1.32%
```

## Key Differences from Production

This is a **simulation** for research purposes:
- Uses historical data with perfect hindsight for market analysis
- Doesn't affect any production parameters
- Simplified adaptation logic compared to full production system
- No database or Redis interactions

## Tips for Best Results

1. **Longer Time Periods**: Use 30+ days to see meaningful adaptations
2. **Different Market Conditions**: Test during both trending and volatile periods
3. **Multiple Tokens**: Compare how adaptation works across different assets
4. **Resolution Matters**: Higher resolution (1H) shows more adaptation opportunities

## Understanding the Plots

The generated plot includes:
1. **Portfolio Performance**: Shows value over time with adaptive strategy
2. **Threshold Evolution**: Visualizes how buy/sell thresholds changed
3. **Trade Returns**: Distribution of profitable vs losing trades
4. **Market Conditions**: Shows volatility and regime at adaptation points

This helps understand not just *what* happened, but *why* the strategy adapted the way it did. 