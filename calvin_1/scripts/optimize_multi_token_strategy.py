#!/usr/bin/env python3
"""
Multi-Token Strategy Optimization Script

This script runs the strategy optimization for multiple tokens sequentially,
maintaining separate optimized parameter sets for each token.

Each token gets its own:
- LSTM model (already trained)
- Optimized strategy parameters (14 parameters)
- Performance metrics and results

Usage:
    python scripts/optimize_multi_token_strategy.py
"""

import os
import sys
import json
import time
from datetime import datetime

# Add src directory to path
try:
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Get the parent directory (calvin_1)
    parent_dir = os.path.dirname(script_dir)
    
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
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
    sys.path.append(os.path.abspath('./src'))
    print("Added fallback paths")

from data.data_processor import DataProcessor
from model.ml_model import MLModel
from model.profit_functions import simple_backtest_strategy
from utils.logger import log_manager, log
import optuna
import pandas as pd
import numpy as np

logger = log

# --- Token Configuration ---
TOKENS_CONFIG = [
    {
        "token_address": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
        "symbol": "Fartcoin",
        "model_path": "models/Fartcoin_lstm_20250615.h5",
        "days_for_data": 90,
        "n_trials": 3000
    },
    {
        "token_address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 
        "symbol": "BONK",
        "model_path": "models/BONK_lstm_20250528.h5",
        "days_for_data": 90,
        "n_trials": 3000
    }
    # Add more tokens as needed:
    # {
    #     "token_address": "So11111111111111111111111111111111111111112",
    #     "symbol": "SOL",
    #     "model_path": "models/SOL_lstm_latest.h5",
    #     "days_for_data": 90,
    #     "n_trials": 3000
    # }
]

# --- Common Configuration ---
RESOLUTION = "1H"
SEQUENCE_LENGTH = 36
PREDICTION_HORIZON = 1
MIN_TRADES_FOR_VALID_STRATEGY = 10

def load_token_data_and_predictions(token_config):
    """Load data and predictions for a specific token."""
    logger.info(f"Loading data for {token_config['symbol']} ({token_config['token_address']})")
    
    data_processor = DataProcessor()
    
    # Use the same data processing as main.py
    df = data_processor.process_pipeline(
        token_config['token_address'],
        token_config['symbol'],
        RESOLUTION,
        token_config['days_for_data'],
        save_data=False,
        include_sentiment=True
    )

    if df.empty:
        logger.error(f"No data available for {token_config['symbol']}")
        raise ValueError(f"No data for {token_config['symbol']}")

    logger.info(f"Data loaded for {token_config['symbol']}. Shape: {df.shape}")

    # Load ML model
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
        sequence_length=SEQUENCE_LENGTH,
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
    
    # Slice the dataframe to match prediction length
    min_length = min(len(y_pred_orig), len(df))
    y_pred_orig = y_pred_orig[:min_length]
    df_for_backtest = df.tail(min_length).copy()  # Use same df processing as main.py
    
    logger.info(f"Data preparation complete for {token_config['symbol']}. "
               f"Predictions: {len(y_pred_orig)}, OHLCV: {len(df_for_backtest)}")
    
    return {
        'predictions': y_pred_orig,
        'prices': df_for_backtest['close'].values,
        'ohlcv_df': df_for_backtest,
        'symbol': token_config['symbol']
    }

def create_objective_function(token_data):
    """Create optimization objective function for a specific token."""
    
    def objective(trial):
        """Objective function for strategy optimization."""
        try:
            # Sample 14 strategy parameters (same as original optimize_strategy.py)
            stop_loss_atr_multiplier = trial.suggest_float('stop_loss_atr_multiplier', 0.5, 4.0)
            take_profit_atr_multiplier = trial.suggest_float('take_profit_atr_multiplier', 0.8, 5.0)
            trend_sma_period = trial.suggest_int('trend_sma_period', 3, 20)
            buy_threshold = trial.suggest_float('buy_threshold', 0.005, 0.08)
            sell_threshold = trial.suggest_float('sell_threshold', 0.01, 0.12)
            trailing_stop_atr_multiplier = trial.suggest_float('trailing_stop_atr_multiplier', 1.0, 4.0)
            trailing_activation_atr_multiplier = trial.suggest_float('trailing_activation_atr_multiplier', 0.5, 2.5)
            
            # Advanced risk management parameters
            kelly_fraction = trial.suggest_float('kelly_fraction', 0.1, 0.5)
            max_position_size = trial.suggest_float('max_position_size', 0.05, 0.25)
            volatility_percentile_threshold = trial.suggest_float('volatility_percentile_threshold', 0.6, 0.95)
            daily_loss_limit = trial.suggest_float('daily_loss_limit', 0.01, 0.05)
            max_consecutive_losses = trial.suggest_int('max_consecutive_losses', 2, 5)
            min_win_rate_threshold = trial.suggest_float('min_win_rate_threshold', 0.45, 0.70)
            rolling_performance_window = trial.suggest_int('rolling_performance_window', 10, 30)

            # Run backtest with these parameters
            result = simple_backtest_strategy(
                prices=token_data['prices'],
                predictions=token_data['predictions'],
                ohlcv_df=token_data['ohlcv_df'],
                include_detailed_trades=False,
                verbosity=0,
                resolution=RESOLUTION,
                stop_loss_atr_multiplier=stop_loss_atr_multiplier,
                take_profit_atr_multiplier=take_profit_atr_multiplier,
                trend_sma_period=trend_sma_period,
                buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
                trailing_stop_atr_multiplier=trailing_stop_atr_multiplier,
                trailing_activation_atr_multiplier=trailing_activation_atr_multiplier,
                use_kelly_sizing=True,  # Enable advanced features
                kelly_fraction=kelly_fraction,
                max_position_size=max_position_size,
                volatility_filter=True,
                volatility_percentile_threshold=volatility_percentile_threshold,
                daily_loss_limit=daily_loss_limit,
                max_consecutive_losses=max_consecutive_losses,
                min_win_rate_threshold=min_win_rate_threshold,
                rolling_performance_window=rolling_performance_window
            )

            # Check minimum trades requirement
            if result['Total Trades'] < MIN_TRADES_FOR_VALID_STRATEGY:
                return -1000.0  # Heavy penalty for insufficient trades

            # Single-objective optimization: Total Return (absolute profit percentage)
            return result['Total Return']

        except Exception as e:
            logger.error(f"Error in objective function for {token_data['symbol']}: {e}")
            return -1000.0

    return objective

def optimize_token_strategy(token_config):
    """Optimize strategy for a single token."""
    logger.info(f"\n{'='*60}")
    logger.info(f"OPTIMIZING STRATEGY FOR {token_config['symbol'].upper()}")
    logger.info(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        # Load token data and predictions
        token_data = load_token_data_and_predictions(token_config)
        
        # Create optimization study
        study_name = f"{token_config['symbol']}_strategy_optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        study = optuna.create_study(
            direction='maximize',
            study_name=study_name,
            sampler=optuna.samplers.TPESampler(seed=42)  # Reproducible results
        )
        
        # Create objective function for this token
        objective_func = create_objective_function(token_data)
        
        # Run optimization
        logger.info(f"Starting {token_config['n_trials']} optimization trials for {token_config['symbol']}...")
        study.optimize(objective_func, n_trials=token_config['n_trials'], timeout=3600)  # 1 hour max
        
        # Get best results
        best_trial = study.best_trial
        best_params = best_trial.params
        best_value = best_trial.value
        
        optimization_time = time.time() - start_time
        
        logger.info(f"\n{'='*40}")
        logger.info(f"OPTIMIZATION COMPLETE FOR {token_config['symbol']}")
        logger.info(f"{'='*40}")
        logger.info(f"Optimization time: {optimization_time:.1f} seconds")
        logger.info(f"Best total return: {best_value:.2f}%")
        logger.info(f"Best parameters:")
        for param, value in best_params.items():
            logger.info(f"  {param}: {value}")
        
        # Test the best parameters to get full metrics
        logger.info(f"\nTesting best parameters for {token_config['symbol']}...")
        test_result = simple_backtest_strategy(
            prices=token_data['prices'],
            predictions=token_data['predictions'],
            ohlcv_df=token_data['ohlcv_df'],
            include_detailed_trades=True,
            verbosity=1,
            resolution=RESOLUTION,
            **best_params
        )
        
        # Compile results
        results = {
            'symbol': token_config['symbol'],
            'token_address': token_config['token_address'],
            'model_path': token_config['model_path'],
            'optimization_time_seconds': optimization_time,
            'n_trials': token_config['n_trials'],
            'best_total_return_pct': best_value,
            'best_parameters': best_params,
            'test_metrics': {
                'total_return_pct': test_result['Total Return'],
                'buy_hold_return_pct': test_result['Buy & Hold Return'],
                'win_rate': test_result['Win Rate'],
                'sharpe_ratio': test_result['Sharpe Ratio'],
                'max_drawdown_pct': test_result['Max Drawdown'],
                'total_trades': test_result['Total Trades'],
                'final_portfolio_value': test_result['Final Portfolio Value']
            },
            'optimization_date': datetime.now().isoformat()
        }
        
        # Save results for this token
        results_file = f"models/{token_config['symbol']}_optimized_strategy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
    logger.info("MULTI-TOKEN STRATEGY OPTIMIZATION")
    logger.info("="*80)
    logger.info(f"Tokens to optimize: {[t['symbol'] for t in TOKENS_CONFIG]}")
    logger.info(f"Resolution: {RESOLUTION}")
    logger.info(f"Sequence length: {SEQUENCE_LENGTH}")
    logger.info(f"Min trades required: {MIN_TRADES_FOR_VALID_STRATEGY}")
    
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
        logger.info(f"\nBest performing tokens by total return:")
        sorted_results = sorted(all_results, key=lambda x: x['best_total_return_pct'], reverse=True)
        for result in sorted_results:
            logger.info(f"  {result['symbol']}: {result['best_total_return_pct']:.2f}%")
        
        # Save combined results
        combined_results_file = f"models/multi_token_optimization_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(combined_results_file, 'w') as f:
            json.dump({
                'summary': {
                    'total_time_seconds': total_time,
                    'successful_optimizations': successful_optimizations,
                    'total_tokens': len(TOKENS_CONFIG),
                    'optimization_date': datetime.now().isoformat()
                },
                'individual_results': all_results
            }, f, indent=2)
        
        logger.info(f"\nCombined results saved to: {combined_results_file}")
    
    logger.info("="*80)

if __name__ == "__main__":
    main() 