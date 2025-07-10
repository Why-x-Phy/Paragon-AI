#!/usr/bin/env python3
"""
Multi-Token Strategy Optimization Script - Pure Buy/Sell Thresholds

This script runs the same optimization as optimize_strategy.py but for multiple tokens.
Only optimizes buy_threshold and sell_threshold with trade range optimization.

Usage:
    python scripts/optimize_multi_token_strategy.py
"""

import os
import sys
import json
import time
from datetime import datetime
import pandas as pd
import numpy as np
import optuna

# Add src directory to path and fix relative imports
try:
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Get the parent directory (calvin_1)
    parent_dir = os.path.dirname(script_dir)
    
    # Add the parent directory to path (so we can import calvin_1.src.*)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        print(f"Added parent to path: {parent_dir}")
    
    # Add the src directory to path
    src_path = os.path.join(parent_dir, 'src')
    if os.path.isdir(src_path) and src_path not in sys.path:
        sys.path.insert(0, src_path)
        print(f"Added to path: {src_path}")
    
    # If we're already in calvin_1 directory, also try adding ./src
    current_src_path = os.path.join(os.getcwd(), 'src')
    if os.path.isdir(current_src_path) and current_src_path not in sys.path:
        sys.path.insert(0, current_src_path)
        print(f"Added to path: {current_src_path}")

except Exception as e:
    print(f"Error setting up sys.path: {e}")
    # Fallback paths
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
    sys.path.append(os.path.abspath('./src'))
    print("Added fallback paths")

# Use absolute imports to avoid relative import issues
from src.data.data_processor import DataProcessor
from src.model.ml_model import MLModel
from src.model.profit_functions import simple_backtest_strategy
from src.utils.logger import log_manager, log

logger = log

# --- Token Configuration ---
TOKENS_CONFIG = [
    # Major Memecoins
    {
        "token_address": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
        "symbol": "Fartcoin",
        "model_path": "models/Fartcoin_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 
        "symbol": "Bonk",
        "model_path": "models/Bonk_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "symbol": "$WIF",
        "model_path": "models/$WIF_lstm_v1.0.0_20250614.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
        "symbol": "POPCAT",
        "model_path": "models/POPCAT_lstm_v1.0.1_20250617.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5",
        "symbol": "MEW",
        "model_path": "models/MEW_lstm_v1.0.0_20250709.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv",
        "symbol": "PENGU",
        "model_path": "models/PENGU_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    
    # DeFi Tokens
    {
        "token_address": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "symbol": "JUP",
        "model_path": "models/JUP_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
        "symbol": "RAY",
        "model_path": "models/RAY_lstm_v1.0.0_20250614.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
        "symbol": "JTO",
        "model_path": "models/JTO_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
        "symbol": "ORCA",
        "model_path": "models/ORCA_lstm_v1.0.0_20250709.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
        "symbol": "PYTH",
        "model_path": "models/PYTH_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey",
        "symbol": "MNDE",
        "model_path": "models/MNDE_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    
    # Other Major Tokens
    {
        "token_address": "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof",
        "symbol": "RENDER",
        "model_path": "models/RENDER_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN",
        "symbol": "TRUMP",
        "model_path": "models/TRUMP_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ",
        "symbol": "W",  # WORMHOLE
        "model_path": "models/W_lstm_v1.0.0_20250614.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr",
        "symbol": "SPX",  # SPX6900
        "model_path": "models/SPX_lstm_v1.0.0_20250615.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y",
        "symbol": "VIRTUAL",
        "model_path": "models/VIRTUAL_lstm_v1.0.0_20250708.h5",
        "days_for_data": 15,
        "n_trials": 300
    },
    {
        "token_address": "Ey59PH7Z4BFU4HjyKnyMdWt5GGN76KazTAwQihoUXRnk",
        "symbol": "LAUNCHCOIN",
        "model_path": "models/LAUNCHCOIN_lstm_v1.0.0_20250708.h5",
        "days_for_data": 15,
        "n_trials": 300
    }
]

# --- Common Configuration (same as optimize_strategy.py) ---
RESOLUTION = "1H"
SEQUENCE_LENGTH = 36
PREDICTION_HORIZON = 1

# TRADE RANGE OPTIMIZATION: Target a specific range of trades
MIN_TRADES_FOR_VALID_STRATEGY = 5  # Minimum trades required
MAX_TRADES_FOR_VALID_STRATEGY = 90  # Maximum trades desired
OPTIMAL_TRADE_RANGE = (10, 60)  # Ideal range for trade count (min, max)

# Penalty weights for trades outside the optimal range
TRADE_RANGE_PENALTY_WEIGHT = 0.3  # How much to penalize for being outside optimal range

# Global cache for data and predictions to avoid reloading in each trial
DATA_CACHE = {}

def clear_data_cache():
    """Clear the global data cache to force fresh data loading."""
    global DATA_CACHE
    DATA_CACHE.clear()
    logger.info("Data cache cleared - will load fresh data")

def load_data_and_predictions(token_config):
    """Loads data and gets model predictions for a specific token, caching the result."""
    cache_key = token_config['symbol']
    
    if cache_key in DATA_CACHE:
        logger.info(f"Using cached data and predictions for {token_config['symbol']}")
        return DATA_CACHE[cache_key]

    logger.info(f"Loading data for {token_config['symbol']} ({token_config['token_address']}), {token_config['days_for_data']} days, {RESOLUTION} resolution")
    data_processor = DataProcessor()
    
    # Fix async event loop issue by using sync-compatible approach
    import asyncio
    
    # Create a new event loop for this thread to avoid conflicts
    try:
        # Set up a new event loop for this synchronous context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Use the EXACT same data processing as main.py but with proper event loop
        df = data_processor.process_pipeline(
            token_config['token_address'],
            token_config['symbol'],
            RESOLUTION,
            token_config['days_for_data'],
            save_data=False,
            include_sentiment=True
        )
        
    except Exception as e:
        logger.error(f"Error in data processing with new event loop: {e}")
        # Try without setting new loop
        df = data_processor.process_pipeline(
            token_config['token_address'],
            token_config['symbol'],
            RESOLUTION,
            token_config['days_for_data'],
            save_data=False,
            include_sentiment=True
        )
    finally:
        # Clean up the event loop
        try:
            loop.close()
        except:
            pass

    if df.empty:
        logger.error(f"No data available for optimization of {token_config['symbol']}")
        raise ValueError(f"No data for optimization of {token_config['symbol']}")

    logger.info(f"Data loaded for {token_config['symbol']}. Shape: {df.shape}")

    # Load ML model - use exact same approach as main.py
    ml_model = MLModel()
    model_path = token_config['model_path']
    
    if not os.path.exists(model_path):
        logger.error(f"Model not found: {model_path}")
        raise ValueError(f"Model not found: {model_path}")
    
    logger.info(f"Loading model: {model_path}")
    ml_model.load(model_path)

    # Use EXACT same data preparation as main.py test_model()
    _, X_test, _, y_test = data_processor.prepare_ml_data(
        df.copy(),
        target_col='close',
        sequence_length=SEQUENCE_LENGTH if SEQUENCE_LENGTH else 24,  # Default to 24 for new models
        prediction_horizon=PREDICTION_HORIZON,
        test_size=0.99,  # Same as main.py
        include_feature_names=False
    )
    
    if X_test.shape[0] == 0:
        logger.error(f"No data samples generated for {token_config['symbol']} after prepare_ml_data.")
        raise ValueError(f"No data samples for {token_config['symbol']}")

    logger.info(f"Making predictions for {token_config['symbol']} with {X_test.shape[0]} samples.")
    y_pred = ml_model.predict(X_test)
    
    # Use EXACT same inverse transform approach as main.py
    y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
    
    # Get actual prices using the SAME approach as main.py
    original_indices = df.index[-(len(y_test)+PREDICTION_HORIZON-1):-(PREDICTION_HORIZON-1)] if PREDICTION_HORIZON > 1 else df.index[-len(y_test):]
    base_prices_for_y_test = df.loc[original_indices, 'close'].values
    target_pct_changes = data_processor.price_scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()
    y_true_orig = base_prices_for_y_test * (1 + target_pct_changes)

    # CRITICAL FIX: Slice dataframe to match prediction length
    ohlcv_df_aligned = df.iloc[-len(y_pred_orig):].copy()

    logger.info(f"Aligned data for {token_config['symbol']} backtest: Prices shape {y_true_orig.shape}, Predictions shape {y_pred_orig.shape}, OHLCV_DF shape {ohlcv_df_aligned.shape}")

    DATA_CACHE[cache_key] = (ohlcv_df_aligned, y_true_orig.copy(), y_pred_orig.copy())
    return DATA_CACHE[cache_key]

def create_objective_function(token_config):
    """Create optimization objective function for a specific token."""
    
    def objective(trial: optuna.Trial) -> float:
        """Objective function identical to optimize_strategy.py"""
        try:
            ohlcv_df, prices, predictions = load_data_and_predictions(token_config)
        except ValueError as e:
            logger.error(f"Failed to load data/predictions for {token_config['symbol']} trial: {e}")
            return -100.0 # Penalize heavily if data loading fails

        # SIMPLIFIED: Only optimize buy and sell thresholds for magnitude-based strategy
        buy_threshold = trial.suggest_float("buy_threshold", 0.005, 0.08)  # 0.5% to 8%
        sell_threshold = trial.suggest_float("sell_threshold", 0.01, 0.10)   # 1% to 10%
        
        # Run the simplified backtest strategy
        try:
            results = simple_backtest_strategy(
                prices=prices,
                predictions=predictions,
                ohlcv_df=ohlcv_df.copy(), # Pass a copy to be safe
                include_detailed_trades=False, # We only need summary metrics
                verbosity=0,
                resolution=RESOLUTION,
                buy_threshold=buy_threshold,    # Buy when predicted increase >= this %
                sell_threshold=sell_threshold   # Sell when predicted decrease >= this %
            )
        except Exception as e:
            logger.error(f"Backtest failed for {token_config['symbol']} trial {trial.number} with params {trial.params}: {e}")
            return -100.0 # Penalize heavily

        total_return = results.get('Total Return', -100.0) # Default to very low if not found
        total_trades = results.get('Total Trades', 0)

        # Check minimum and maximum trades requirements
        if total_trades < MIN_TRADES_FOR_VALID_STRATEGY:
            logger.info(f"{token_config['symbol']} trial {trial.number} pruned due to insufficient trades ({total_trades}). Return: {total_return if total_return is not None else 'N/A'}")
            return -50.0 # Penalize for insufficient trades
        
        if total_trades > MAX_TRADES_FOR_VALID_STRATEGY:
            logger.info(f"{token_config['symbol']} trial {trial.number} pruned due to excessive trades ({total_trades}). Return: {total_return if total_return is not None else 'N/A'}")
            return -30.0 # Penalize for too many trades (less severe than too few)

        # Handle invalid metrics
        if total_return is None or np.isnan(total_return) or np.isinf(total_return):
            total_return = -100.0

        if total_return == -100.0:
            logger.warning(f"{token_config['symbol']} trial {trial.number} resulted in invalid metrics. Return: {total_return}, Trades: {total_trades}. Params: {trial.params}")

        # TRADE RANGE OPTIMIZATION: Apply bonus/penalty based on trade count
        trade_adjustment = 0.0
        optimal_min, optimal_max = OPTIMAL_TRADE_RANGE
        
        if optimal_min <= total_trades <= optimal_max:
            # Bonus for being in optimal range
            trade_adjustment = 2.0  # Small bonus for optimal trade count
            logger.info(f"{token_config['symbol']} trial {trial.number}: OPTIMAL RANGE - Buy={buy_threshold:.3f}, Sell={sell_threshold:.3f}, Total Return={total_return:.2f}%, Trades={total_trades} ✓")
        else:
            # Penalty for being outside optimal range
            if total_trades < optimal_min:
                # Too few trades - penalty proportional to how far below optimal
                distance_penalty = (optimal_min - total_trades) * TRADE_RANGE_PENALTY_WEIGHT
                trade_adjustment = -distance_penalty
            else:
                # Too many trades - penalty proportional to how far above optimal
                distance_penalty = (total_trades - optimal_max) * TRADE_RANGE_PENALTY_WEIGHT
                trade_adjustment = -distance_penalty
            
            logger.info(f"{token_config['symbol']} trial {trial.number}: Buy={buy_threshold:.3f}, Sell={sell_threshold:.3f}, Total Return={total_return:.2f}%, Trades={total_trades}, Adjustment={trade_adjustment:.2f}")

        # Return adjusted score (total return + trade range adjustment)
        adjusted_score = total_return + trade_adjustment
        return adjusted_score

    return objective

def get_trial_results(token_config, trial_params: dict) -> dict:
    """Get backtest results for a specific set of trial parameters."""
    try:
        ohlcv_df, prices, predictions = load_data_and_predictions(token_config)
        
        # SIMPLIFIED: Only use buy_threshold and sell_threshold
        results = simple_backtest_strategy(
            prices=prices,
            predictions=predictions,
            ohlcv_df=ohlcv_df.copy(),
            include_detailed_trades=False,
            verbosity=0,
            resolution=RESOLUTION,
            buy_threshold=trial_params.get("buy_threshold", 0.02),
            sell_threshold=trial_params.get("sell_threshold", 0.03)
        )
        return results
    except Exception as e:
        logger.error(f"Failed to get trial results for {token_config['symbol']}: {e}")
        return {}

def safe_format_percent(value, default='N/A'):
    """Safely format percentage values, handling 'N/A' strings"""
    if value == 'N/A' or value is None:
        return default
    try:
        return f"{float(value):.2f}%"
    except (ValueError, TypeError):
        return default

def safe_format_currency(value, default='N/A'):
    """Safely format currency values, handling 'N/A' strings"""
    if value == 'N/A' or value is None:
        return default
    try:
        return f"${float(value):.2f}"
    except (ValueError, TypeError):
        return default

def optimize_token_strategy(token_config):
    """Optimize strategy for a single token using the same logic as optimize_strategy.py"""
    logger.info(f"\n{'='*60}")
    logger.info(f"OPTIMIZING STRATEGY FOR {token_config['symbol'].upper()}")
    logger.info(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        # Clear cache for this token
        cache_key = token_config['symbol']
        if cache_key in DATA_CACHE:
            del DATA_CACHE[cache_key]
        
        # Pre-load data and predictions to cache them
        logger.info(f"Pre-loading data and predictions for {token_config['symbol']}...")
        load_data_and_predictions(token_config)
        logger.info(f"Data and predictions pre-loaded and cached for {token_config['symbol']}")
        
        # Create optimization study
        study_name = f"simple_strategy_opt_{token_config['symbol']}_{RESOLUTION}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Sampler for more efficient search (same as optimize_strategy.py)
        sampler = optuna.samplers.TPESampler(seed=42)
        pruner = optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=0, interval_steps=1)

        study = optuna.create_study(
            study_name=study_name,
            direction="maximize",
            sampler=sampler,
            pruner=pruner
        )
        
        # Create objective function for this token
        objective_func = create_objective_function(token_config)
        
        # Run optimization
        logger.info(f"Starting {token_config['n_trials']} optimization trials for {token_config['symbol']}...")
        
        try:
            study.optimize(objective_func, n_trials=token_config['n_trials'], timeout=7200)  # 2 hours max
        except KeyboardInterrupt:
            logger.info(f"Optimization interrupted by user for {token_config['symbol']}")
        except Exception as e:
            logger.error(f"An error occurred during optimization for {token_config['symbol']}: {e}")
        
        optimization_time = time.time() - start_time
        
        logger.info(f"Optimization finished for {token_config['symbol']}. Number of trials: {len(study.trials)}")
        
        if not study.trials:
            logger.warning(f"No trials were completed for {token_config['symbol']}. Cannot show best parameters.")
            return None
        
        # Get best results
        best_trial = study.best_trial
        best_params = best_trial.params
        best_value = best_trial.value
        
        # Get complete results for the best trial
        best_results = get_trial_results(token_config, best_params)
        total_trades = best_results.get('Total Trades', 'N/A')
        win_rate = best_results.get('Win Rate', 'N/A')
        max_drawdown = best_results.get('Max Drawdown', 'N/A')
        final_value = best_results.get('Final Portfolio Value', 'N/A')
        sharpe_ratio = best_results.get('Sharpe Ratio', 'N/A')
        
        # Calculate trade range performance
        optimal_min, optimal_max = OPTIMAL_TRADE_RANGE
        trade_range_status = "OPTIMAL" if optimal_min <= total_trades <= optimal_max else "OUTSIDE RANGE"
        
        logger.info(f"\n{'='*40}")
        logger.info(f"OPTIMIZATION COMPLETE FOR {token_config['symbol']}")
        logger.info(f"{'='*40}")
        logger.info(f"Optimization time: {optimization_time:.1f} seconds")
        logger.info(f"Best Trial (Trade Range Optimized):")
        logger.info(f"  Adjusted Score: {best_value:.2f}% (includes trade range bonus/penalty)")
        logger.info(f"  Total Return: {best_results.get('Total Return', 'N/A'):.2f}%")
        logger.info(f"  Trade Count: {total_trades} ({trade_range_status}) - Target: {optimal_min}-{optimal_max}")
        logger.info(f"  Sharpe Ratio: {sharpe_ratio:.2f}" if sharpe_ratio != 'N/A' else "  Sharpe Ratio: N/A")
        logger.info(f"  Win Rate: {safe_format_percent(win_rate)}")
        logger.info(f"  Max Drawdown: {safe_format_percent(max_drawdown)}")
        logger.info(f"  Final Portfolio Value: {safe_format_currency(final_value)}")
        logger.info(f"  Parameters: {best_params}")
        
        # Compile results
        results = {
            'symbol': token_config['symbol'],
            'token_address': token_config['token_address'],
            'model_path': token_config['model_path'],
            'optimization_type': 'trade_range_optimized',
            'optimization_time_seconds': optimization_time,
            'n_trials': len(study.trials),
            'best_adjusted_score': best_value,
            'best_parameters': best_params,
            'test_metrics': {
                'total_return_pct': best_results.get('Total Return', 'N/A'),
                'buy_hold_return_pct': best_results.get('Buy & Hold Return', 'N/A'),
                'win_rate': win_rate,
                'sharpe_ratio': sharpe_ratio,
                'max_drawdown_pct': max_drawdown,
                'total_trades': total_trades,
                'trade_range_status': trade_range_status,
                'final_portfolio_value': final_value
            },
            'trade_range_config': {
                'optimal_range': OPTIMAL_TRADE_RANGE,
                'penalty_weight': TRADE_RANGE_PENALTY_WEIGHT,
                'min_valid_trades': MIN_TRADES_FOR_VALID_STRATEGY,
                'max_valid_trades': MAX_TRADES_FOR_VALID_STRATEGY
            },
            'optimization_date': datetime.now().isoformat()
        }
        
        # Save results for this token
        results_file = f"models/{token_config['symbol']}_trade_range_optimized_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Results saved to: {results_file}")
        
        return results
        
    except Exception as e:
        logger.error(f"Error optimizing strategy for {token_config['symbol']}: {e}")
        return None

def main():
    """Main function to optimize strategies for all tokens."""
    logger.info("="*80)
    logger.info("MULTI-TOKEN TRADE RANGE OPTIMIZATION")
    logger.info("="*80)
    logger.info(f"Tokens to optimize: {[t['symbol'] for t in TOKENS_CONFIG]}")
    logger.info(f"Resolution: {RESOLUTION}")
    logger.info(f"Sequence length: {SEQUENCE_LENGTH}")
    logger.info(f"Target trade range: {OPTIMAL_TRADE_RANGE[0]}-{OPTIMAL_TRADE_RANGE[1]} trades")
    logger.info(f"Trade range penalty weight: {TRADE_RANGE_PENALTY_WEIGHT}")
    logger.info("Parameters: buy_threshold (0.5%-8%), sell_threshold (1%-10%)")
    
    start_time = time.time()
    all_results = []
    successful_optimizations = 0
    
    # Optimize each token sequentially
    for i, token_config in enumerate(TOKENS_CONFIG):
        logger.info(f"\n[{i+1}/{len(TOKENS_CONFIG)}] Processing {token_config['symbol']}...")
        
        result = optimize_token_strategy(token_config)
        if result:
            all_results.append(result)
            successful_optimizations += 1
        else:
            logger.error(f"Failed to optimize {token_config['symbol']}")
    
    # Summary
    total_time = time.time() - start_time
    logger.info(f"\n{'='*80}")
    logger.info("MULTI-TOKEN OPTIMIZATION SUMMARY")
    logger.info(f"{'='*80}")
    logger.info(f"Total time: {total_time:.1f} seconds ({total_time/60:.1f} minutes)")
    logger.info(f"Successful optimizations: {successful_optimizations}/{len(TOKENS_CONFIG)}")
    
    if all_results:
        logger.info(f"\nBest performing tokens by adjusted score:")
        sorted_results = sorted(all_results, key=lambda x: x['best_adjusted_score'], reverse=True)
        for result in sorted_results:
            metrics = result['test_metrics']
            logger.info(f"  {result['symbol']}: {result['best_adjusted_score']:.2f}% adjusted score "
                       f"({metrics['total_return_pct']:.2f}% return, {metrics['total_trades']} trades, "
                       f"{metrics['trade_range_status']})")
        
        # Save combined results
        combined_results_file = f"models/multi_token_trade_range_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(combined_results_file, 'w') as f:
            json.dump({
                'summary': {
                    'optimization_type': 'trade_range_optimized',
                    'total_time_seconds': total_time,
                    'successful_optimizations': successful_optimizations,
                    'total_tokens': len(TOKENS_CONFIG),
                    'trade_range_config': {
                        'optimal_range': OPTIMAL_TRADE_RANGE,
                        'penalty_weight': TRADE_RANGE_PENALTY_WEIGHT,
                        'min_valid_trades': MIN_TRADES_FOR_VALID_STRATEGY,
                        'max_valid_trades': MAX_TRADES_FOR_VALID_STRATEGY
                    },
                    'optimization_date': datetime.now().isoformat()
                },
                'individual_results': all_results
            }, f, indent=2)
        
        logger.info(f"\nCombined results saved to: {combined_results_file}")
    
    logger.info("="*80)

if __name__ == "__main__":
    main() 