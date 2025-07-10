#!/usr/bin/env python3
"""
Test Backtest Comparison

Compare the original backtest (with look-ahead bias) against the fixed version.
"""

import os
import sys
import numpy as np
from pathlib import Path

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Load environment variables
from dotenv import load_dotenv
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from src.model.profit_functions import simple_backtest_strategy
from src.model.profit_functions_fixed import fixed_backtest_strategy, validate_predictions_alignment
from src.model.ml_model import MLModel
from src.data.data_processor import DataProcessor


def compare_backtests(
    token_address: str,
    symbol: str,
    model_path: str = None,
    days: int = 30,
    resolution: str = "1H"
):
    """Compare original vs fixed backtest to show the difference"""
    
    print("\n🔍 BACKTEST COMPARISON: Original vs Fixed")
    print("=" * 60)
    
    # Load model
    ml_model = MLModel()
    if model_path:
        ml_model.load(model_path)
    else:
        model_path = ml_model.get_latest_model_path()
        if not model_path:
            print("❌ No model found")
            return
        ml_model.load(model_path)
    
    print(f"📊 Using model: {os.path.basename(model_path)}")
    
    # Get data
    print(f"\n📈 Fetching {days} days of {resolution} data...")
    data_processor = DataProcessor()
    df = data_processor.process_pipeline(
        token_address, 
        symbol, 
        resolution=resolution,
        days=days,
        save_data=False
    )
    
    if df is None or df.empty:
        print("❌ Failed to fetch data")
        return
    
    # Prepare test data
    X, y, train_idx, test_idx = data_processor.prepare_ml_data(
        df, 
        sequence_length=36, 
        prediction_horizon=1,
        test_size=0.2,
        test_mode=True
    )
    
    print(f"✅ Prepared {len(test_idx)} test samples")
    
    # Make predictions
    print("\n🤖 Generating predictions...")
    X_test = X[test_idx]
    y_pred = ml_model.predict(X_test)
    
    # Get actual prices
    y_pred_orig = data_processor.inverse_transform_predictions(
        y_pred, df, test_idx, prediction_horizon=1
    )
    
    # Get corresponding actual prices
    actual_prices = df['close'].iloc[test_idx].values
    
    # Validate alignment
    print("\n🔍 Validating prediction alignment...")
    alignment = validate_predictions_alignment(actual_prices, y_pred_orig)
    
    print(f"Alignment check: {'✅ PASSED' if alignment['aligned'] else '❌ FAILED'}")
    if alignment['issues']:
        for issue in alignment['issues']:
            print(f"  - {issue}")
    
    print("\nCorrelations (higher = more similar):")
    for lag, corr in alignment['correlations'].items():
        print(f"  {lag}: {corr:.4f}")
    
    # Run original backtest (with potential look-ahead bias)
    print("\n📊 Running ORIGINAL backtest...")
    original_results = simple_backtest_strategy(
        prices=actual_prices,
        predictions=y_pred_orig,
        include_detailed_trades=True,
        verbosity=0,
        resolution=resolution,
        buy_threshold=0.01,
        sell_threshold=0.015
    )
    
    # Run fixed backtest (no look-ahead bias)
    print("📊 Running FIXED backtest...")
    fixed_results = fixed_backtest_strategy(
        actual_prices=actual_prices,
        predicted_prices=y_pred_orig,
        buy_threshold=0.01,
        sell_threshold=0.015,
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
        enable_stops=True,
        verbosity=0,
        resolution=resolution
    )
    
    # Compare results
    print("\n" + "=" * 60)
    print("📊 RESULTS COMPARISON")
    print("=" * 60)
    
    print(f"\n{'Metric':<25} {'Original':>15} {'Fixed':>15} {'Difference':>15}")
    print("-" * 70)
    
    # Compare key metrics
    metrics_map = {
        'Total Return (%)': ('Total Return', 'total_return_pct'),
        'Buy & Hold Return (%)': ('Buy & Hold Return', 'buy_hold_return_pct'),
        'Win Rate (%)': ('Win Rate', 'win_rate'),
        'Number of Trades': ('Total Trades', 'num_trades'),
        'Sharpe Ratio': ('Sharpe Ratio', 'sharpe_ratio'),
        'Max Drawdown (%)': ('Max Drawdown', 'max_drawdown_pct')
    }
    
    for display_name, (orig_key, fixed_key) in metrics_map.items():
        orig_val = original_results.get(orig_key, 0)
        fixed_val = fixed_results.get(fixed_key, 0)
        
        if 'Return' in display_name or 'Rate' in display_name or 'Drawdown' in display_name:
            diff = fixed_val - orig_val
            print(f"{display_name:<25} {orig_val:>14.2f}% {fixed_val:>14.2f}% {diff:>+14.2f}%")
        elif 'Sharpe' in display_name:
            diff = fixed_val - orig_val
            print(f"{display_name:<25} {orig_val:>14.2f} {fixed_val:>14.2f} {diff:>+14.2f}")
        else:
            diff = fixed_val - orig_val
            print(f"{display_name:<25} {orig_val:>14.0f} {fixed_val:>14.0f} {diff:>+14.0f}")
    
    # Additional metrics from fixed backtest
    if 'exit_reasons' in fixed_results:
        print("\n📊 Exit Reasons (Fixed Backtest):")
        for reason, count in fixed_results['exit_reasons'].items():
            print(f"  - {reason}: {count}")
    
    # Check for look-ahead bias indicators
    print("\n⚠️  BIAS INDICATORS:")
    
    # If original performs much better, likely has look-ahead bias
    return_diff = original_results['Total Return'] - fixed_results['total_return_pct']
    if return_diff > 5:
        print(f"  ❌ Original outperforms by {return_diff:.1f}% - likely look-ahead bias!")
    elif return_diff > 2:
        print(f"  ⚠️  Original outperforms by {return_diff:.1f}% - possible bias")
    else:
        print(f"  ✅ Returns are similar (diff: {return_diff:.1f}%)")
    
    # Check win rates
    win_diff = original_results['Win Rate'] - fixed_results['win_rate']
    if win_diff > 10:
        print(f"  ❌ Original win rate {win_diff:.1f}% higher - likely look-ahead bias!")
    elif win_diff > 5:
        print(f"  ⚠️  Original win rate {win_diff:.1f}% higher - possible bias")
    else:
        print(f"  ✅ Win rates are similar (diff: {win_diff:.1f}%)")
    
    # Sample some trades to show the difference
    if 'trades' in original_results and 'trades' in fixed_results:
        orig_trades = original_results['trades']
        fixed_trades = fixed_results['trades']
        
        print(f"\n📈 Trade Comparison (first 5 trades):")
        print(f"{'Type':<6} {'Original Time':>15} {'Fixed Time':>15} {'Difference':>15}")
        print("-" * 55)
        
        # Compare first few buy trades
        orig_buys = [t for t in orig_trades if t['type'] == 'buy'][:5]
        fixed_buys = [t for t in fixed_trades if t['type'] == 'buy'][:5]
        
        for i in range(min(len(orig_buys), len(fixed_buys))):
            orig_time = orig_buys[i].get('step', orig_buys[i].get('time', 0))
            fixed_time = fixed_buys[i].get('time', 0)
            diff = fixed_time - orig_time
            print(f"{'BUY':<6} {orig_time:>15} {fixed_time:>15} {diff:>+15}")
    
    print("\n💡 KEY DIFFERENCES:")
    print("1. Original uses predictions[i] to trade at time i (look-ahead)")
    print("2. Fixed uses predictions[i+1] to trade at time i (no look-ahead)")
    print("3. Fixed includes realistic slippage and better position sizing")
    print("4. Fixed includes stop-loss and take-profit for risk management")
    
    return original_results, fixed_results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Compare backtest strategies')
    parser.add_argument('--token-address', type=str, 
                        default="9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
                        help='Token address')
    parser.add_argument('--symbol', type=str, default="Fartcoin",
                        help='Token symbol')
    parser.add_argument('--model-path', type=str,
                        help='Path to model file')
    parser.add_argument('--days', type=int, default=30,
                        help='Days of historical data')
    parser.add_argument('--resolution', type=str, default='1H',
                        help='Data resolution')
    
    args = parser.parse_args()
    
    compare_backtests(
        token_address=args.token_address,
        symbol=args.symbol,
        model_path=args.model_path,
        days=args.days,
        resolution=args.resolution
    ) 