#!/usr/bin/env python3
"""
Multi-Token Strategy Testing Script

This script tests trading strategies using token-specific optimized parameters.
It can load optimization results and test any token with its specific parameters.

Usage:
    python scripts/test_multi_token_strategies.py --token Fartcoin
    python scripts/test_multi_token_strategies.py --token BONK
    python scripts/test_multi_token_strategies.py --results_file models/multi_token_optimization_results_20250531_123456.json
"""

import os
import sys
import json
import argparse
import glob
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
from utils.logger import log_manager
import pandas as pd
import numpy as np

logger = log_manager.get_logger("test_multi_token_strategies")

# Default token configurations (fallback if no optimization results found)
DEFAULT_TOKEN_CONFIGS = {
    "Fartcoin": {
        "token_address": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
        "model_path": "models/Fartcoin_lstm_20250528.h5"
    },
    "BONK": {
        "token_address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "model_path": "models/BONK_lstm_20250528.h5"
    }
}

# Common configuration
RESOLUTION = "1H"
SEQUENCE_LENGTH = 36
PREDICTION_HORIZON = 1
DAYS_FOR_DATA = 90

def find_latest_results_file():
    """Find the most recent multi-token optimization results file."""
    pattern = "models/multi_token_optimization_results_*.json"
    files = glob.glob(pattern)
    if not files:
        return None
    
    # Sort by timestamp in filename
    latest_file = max(files, key=lambda x: os.path.getmtime(x))
    return latest_file

def find_token_specific_results_file(token_symbol):
    """Find the most recent optimization results file for a specific token."""
    pattern = f"models/{token_symbol}_optimized_strategy_*.json"
    files = glob.glob(pattern)
    if not files:
        return None
    
    latest_file = max(files, key=lambda x: os.path.getmtime(x))
    return latest_file

def load_optimization_results(results_file=None, token_symbol=None):
    """Load optimization results from file."""
    if results_file and os.path.exists(results_file):
        logger.info(f"Loading optimization results from: {results_file}")
        with open(results_file, 'r') as f:
            return json.load(f)
    
    if token_symbol:
        # Try to find token-specific results
        token_file = find_token_specific_results_file(token_symbol)
        if token_file:
            logger.info(f"Loading token-specific results from: {token_file}")
            with open(token_file, 'r') as f:
                token_results = json.load(f)
                # Convert single token results to multi-token format
                return {
                    'individual_results': [token_results]
                }
    
    # Try to find latest multi-token results
    latest_file = find_latest_results_file()
    if latest_file:
        logger.info(f"Loading latest multi-token results from: {latest_file}")
        with open(latest_file, 'r') as f:
            return json.load(f)
    
    logger.warning("No optimization results found!")
    return None

def get_token_config_and_params(token_symbol, optimization_results=None):
    """Get token configuration and optimized parameters."""
    
    # Get basic token config
    if token_symbol in DEFAULT_TOKEN_CONFIGS:
        token_config = DEFAULT_TOKEN_CONFIGS[token_symbol].copy()
        token_config['symbol'] = token_symbol
    else:
        logger.error(f"Unknown token: {token_symbol}")
        return None, None
    
    # Get optimized parameters
    optimized_params = None
    if optimization_results and 'individual_results' in optimization_results:
        for result in optimization_results['individual_results']:
            if result['symbol'] == token_symbol:
                optimized_params = result['best_parameters']
                logger.info(f"Found optimized parameters for {token_symbol}")
                break
    
    if not optimized_params:
        logger.warning(f"No optimized parameters found for {token_symbol}, using defaults")
        # Use reasonable defaults if no optimization results
        optimized_params = {
            'stop_loss_atr_multiplier': 2.56,
            'take_profit_atr_multiplier': 1.74,
            'trend_sma_period': 4,
            'buy_threshold': 0.0188,
            'sell_threshold': 0.058,
            'trailing_stop_atr_multiplier': 2.0,
            'trailing_activation_atr_multiplier': 1.0,
            'kelly_fraction': 0.25,
            'max_position_size': 0.15,
            'volatility_percentile_threshold': 0.8,
            'daily_loss_limit': 0.02,
            'max_consecutive_losses': 3,
            'min_win_rate_threshold': 0.55,
            'rolling_performance_window': 20
        }
    
    return token_config, optimized_params

def load_token_data_and_predictions(token_config):
    """Load data and predictions for a specific token."""
    logger.info(f"Loading data for {token_config['symbol']} ({token_config['token_address']})")
    
    data_processor = DataProcessor()
    
    # Use the same data processing as main.py
    df = data_processor.process_pipeline(
        token_config['token_address'],
        token_config['symbol'],
        RESOLUTION,
        DAYS_FOR_DATA,
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

def test_token_strategy(token_symbol, optimization_results=None):
    """Test strategy for a specific token using its optimized parameters."""
    logger.info(f"\n{'='*60}")
    logger.info(f"TESTING STRATEGY FOR {token_symbol.upper()}")
    logger.info(f"{'='*60}")
    
    try:
        # Get token configuration and optimized parameters
        token_config, optimized_params = get_token_config_and_params(token_symbol, optimization_results)
        if not token_config or not optimized_params:
            return None
        
        # Load token data and predictions
        token_data = load_token_data_and_predictions(token_config)
        
        # Log the parameters being used
        logger.info(f"Using parameters for {token_symbol}:")
        for param, value in optimized_params.items():
            logger.info(f"  {param}: {value}")
        
        # Run backtest with optimized parameters
        logger.info(f"\nRunning backtest for {token_symbol}...")
        result = simple_backtest_strategy(
            prices=token_data['prices'],
            predictions=token_data['predictions'],
            ohlcv_df=token_data['ohlcv_df'],
            include_detailed_trades=True,
            verbosity=1,
            resolution=RESOLUTION,
            **optimized_params
        )
        
        # Display results
        logger.info(f"\n{'='*40}")
        logger.info(f"BACKTEST RESULTS FOR {token_symbol}")
        logger.info(f"{'='*40}")
        logger.info(f"Total Return: {result['Total Return']:.2f}%")
        logger.info(f"Buy & Hold Return: {result['Buy & Hold Return']:.2f}%")
        logger.info(f"Win Rate: {result['Win Rate']:.2f}%")
        logger.info(f"Sharpe Ratio: {result['Sharpe Ratio']:.2f}")
        logger.info(f"Max Drawdown: {result['Max Drawdown']:.2f}%")
        logger.info(f"Total Trades: {result['Total Trades']}")
        logger.info(f"Final Portfolio Value: ${result['Final Portfolio Value']:,.2f}")
        
        # Calculate alpha (excess return over buy & hold)
        alpha = result['Total Return'] - result['Buy & Hold Return']
        
        # Return the results
        return {
            'symbol': token_symbol,
            'test_results': result,
            'parameters_used': optimized_params,
            'test_date': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error testing strategy for {token_symbol}: {e}")
        return None

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Test trading strategies for specific tokens')
    parser.add_argument('--token', type=str, help='Token symbol to test (e.g., Fartcoin, BONK)')
    parser.add_argument('--results_file', type=str, help='Path to optimization results file')
    parser.add_argument('--list_tokens', action='store_true', help='List available tokens')
    
    args = parser.parse_args()
    
    if args.list_tokens:
        logger.info("Available tokens:")
        for token in DEFAULT_TOKEN_CONFIGS.keys():
            logger.info(f"  {token}")
        return
    
    if not args.token:
        logger.error("Please specify a token symbol with --token")
        logger.info("Available tokens: " + ", ".join(DEFAULT_TOKEN_CONFIGS.keys()))
        return
    
    # Load optimization results
    optimization_results = load_optimization_results(args.results_file, args.token)
    
    # Test the specified token
    result = test_token_strategy(args.token, optimization_results)
    
    if result:
        # Save test results
        results_file = f"models/{args.token}_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, 'w') as f:
            json.dump(result, f, indent=2)
        logger.info(f"\nTest results saved to: {results_file}")
    else:
        logger.error(f"Failed to test {args.token}")

if __name__ == "__main__":
    main() 