#!/usr/bin/env python
"""
Script to train a fast reinforcement learning agent for trading
using vectorized operations and optimized implementation.

Usage:
    python src/scripts/train_fast_rl.py train --token-address 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump --symbol Fartcoin --days 180 --episodes 300 --network-type lstm_attention --resolution 1H --reward-type combined
"""

import os
import sys
import argparse
import time
import numpy as np
import pandas as pd
from datetime import datetime
import click
from typing import Dict, Any

# Add project root to import path
current_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(scripts_dir)
sys.path.append(project_root)

from src.data.data_processor import DataProcessor
from src.model.rl_agent import TradingEnvironment
from src.model.fast_rl_agent import (
    FastDQNAgent, 
    load_fast_rl_agent, 
    train_fast_rl_agent, 
    evaluate_fast_agent
)  # Import all needed functions
from src.utils.logger import log_manager

logger = log_manager.get_logger("train_fast_rl")

def add_lagged_features(df, columns=None, lag_periods=0):
    """
    Add lagged features to the dataframe
    
    Args:
        df: Pandas DataFrame with time series data
        columns: List of column names to create lags for. If None, uses recommended features.
        lag_periods: Number of lag periods to create
        
    Returns:
        DataFrame with added lag features
    """
    if lag_periods <= 0:
        return df
    
    # Define key features if not provided
    if columns is None:
        columns = [
            # Price action features
            'close', 'open', 'high', 'low',
            # Volume indicators
            'volume', 'obv',
            # Momentum indicators 
            'RSI_14', 'macd', 'roc',
            # Volatility measures
            'ATRr_14', 'yang_zhang_vol', 'vov',
            # Trend indicators
            'ema_12', 'ema_26', 'adx_20',
            # Support/Resistance
            'distance_to_fib_support', 'distance_to_fib_resistance',
            # Market regime
            'regime_numeric_20', 'volatility_regime_numeric'
        ]
    
    # Filter to only include columns that exist in the dataframe
    available_columns = [col for col in columns if col in df.columns]
    
    if not available_columns:
        logger.warning("None of the specified columns exist in the dataframe. No lag features added.")
        return df
        
    logger.info(f"Adding {lag_periods} lag periods for {len(available_columns)} columns")
    
    # Create a copy of the original dataframe
    original_df = df.copy()
    
    # Create a dictionary to store all the lagged features
    lagged_features_dict = {}
    
    # Generate all lagged features at once
    for col in available_columns:
        for lag in range(1, lag_periods + 1):
            lag_col_name = f"{col}_lag_{lag}"
            lagged_features_dict[lag_col_name] = original_df[col].shift(lag)
    
    # Convert the dictionary to a DataFrame
    lagged_features_df = pd.DataFrame(lagged_features_dict, index=original_df.index)
    
    # Fill NaN values created by shifting
    lagged_features_df = lagged_features_df.fillna(method='ffill').fillna(method='bfill')
    
    # Combine the original DataFrame with the lagged features DataFrame using concat
    enhanced_df = pd.concat([original_df, lagged_features_df], axis=1)
    
    logger.info(f"Added {len(available_columns) * lag_periods} lag features")
    return enhanced_df

def train_fast_rl_model(args, agent=None, day_offset=0, model_name=None):
    """Train a fast RL agent for trading"""
    logger.info(f"Starting fast RL model training for {args.symbol} ({args.token_address})")
    
    start_time = time.time()
    
    # Check if cached processed data exists - use pattern matching for existing files
    data_dir = os.path.join(project_root, "data")
    
    df = None
    if not args.force_reprocess and os.path.exists(data_dir):
        # Look for files matching the pattern: SYMBOL_RESOLUTION_Xdays_TIMESTAMP_with_social
        pattern = f"{args.symbol}_{args.resolution}_{args.days}days_*"
        matching_files = []
        
        try:
            import glob
            matching_files = glob.glob(os.path.join(data_dir, pattern))
            
            # Find the most recent file if multiple matches exist
            if matching_files:
                # Sort by modification time (newest first)
                matching_files.sort(key=os.path.getmtime, reverse=True)
                latest_file = matching_files[0]
                
                logger.info(f"Loading preprocessed data from {latest_file}")
                df = pd.read_csv(latest_file)
                
                # Convert timestamp to datetime if it exists
                if 'timestamp' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                
                logger.info(f"Loaded {len(df)} rows of preprocessed data")
            else:
                logger.info(f"No cached data found matching: {pattern}")
        except Exception as e:
            logger.warning(f"Error loading cached data: {e}. Will reprocess data.")
            df = None
    
    if df is None:
        # Initialize data processor
        data_processor = DataProcessor()
        
        # Get and process data
        logger.info(f"Fetching and processing data: {args.days} days, {args.resolution} resolution")
        df = data_processor.process_pipeline(
            args.token_address, 
            args.symbol, 
            args.resolution, 
            args.days, 
            save_data=True,
            include_sentiment=args.include_social,
            day_offset=day_offset  # Pass day offset to data processor
        )
        
        # Note: We don't need to manually save the data here since process_pipeline 
        # already saves it with the appropriate naming convention when save_data=True
    
    if df.empty:
        logger.error("No data available for training")
        return agent, None
    
    # Drop any NaN values to ensure clean data
    df = df.dropna()
    
    # Add lagged features if requested
    lag_periods = args.lag_periods 
    if lag_periods > 0:
        # Handle case when lag_features is None
        if args.lag_features is None:
            # Use our default set of lag features (already handled in add_lagged_features)
            df = add_lagged_features(df, lag_periods=lag_periods)
        else:
            # Use user-specified columns
            lag_columns = args.lag_features.split(',')
            df = add_lagged_features(df, columns=lag_columns, lag_periods=lag_periods)
    
    # Prepare data for RL
    logger.info(f"Preparing data for fast RL with optimized processing")
    
    # Extract price data (for environment)
    price_data = df['close'].values
    
    # Extract features (for state representation)
    # Drop columns not useful for features
    drop_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    all_possible_feature_cols = [col for col in df.columns if col not in drop_cols]

    if not all_possible_feature_cols:
        logger.error("No potential feature columns found after dropping core price/volume columns. Cannot proceed.")
        return agent, None

    # Create a DataFrame subset for features and attempt numeric conversion column by column
    df_feature_subset = df[all_possible_feature_cols].copy()
    successfully_coerced_cols = []
    for col in all_possible_feature_cols:
        try:
            # Attempt to convert to numeric; errors='raise' will trigger the except block if not possible
            df_feature_subset[col] = pd.to_numeric(df_feature_subset[col], errors='raise')
            # If conversion is successful, check if the column became all NaNs (e.g., a column of pure strings)
            if not df_feature_subset[col].isnull().all():
                successfully_coerced_cols.append(col)
            else:
                logger.warning(f"Column '{col}' became all NaN after numeric coercion and will be dropped from features.")
        except (ValueError, TypeError):
            logger.warning(f"Column '{col}' could not be converted to a numeric type and will be dropped from features.")
            
    feature_cols = successfully_coerced_cols

    if not feature_cols:
        logger.error("No valid numeric feature columns remain after explicit coercion. Cannot proceed with training.")
        return agent, None
    
    logger.info(f"Using {len(feature_cols)} strictly numeric feature columns after coercion: {feature_cols}")
    
    # Create the features array and ensure it's float64 for consistency with np.isnan/np.isinf
    features = df_feature_subset[feature_cols].values.astype(np.float64)
    
    # Verify features is a proper 2D array
    if features.ndim != 2:
        logger.error(f"Feature data has incorrect dimensions: {features.ndim}. Expected 2D array.")
        logger.error(f"Feature data shape: {features.shape}")
        logger.error(f"Feature columns used: {feature_cols}")
        return agent, None
    
    if features.shape[0] == 0 or features.shape[1] == 0:
        logger.error(f"Feature data has zero size in at least one dimension: {features.shape}")
        return agent, None
    
    # Get feature names for importance analysis (these are now strictly numeric columns)
    feature_names = feature_cols.copy()
    logger.info(f"Extracted {len(feature_names)} strictly numeric feature names for importance analysis.")
    
    # Clean the feature data. 'features' is now a float64 NumPy array.
    features_cleaned = features.copy() # Create a copy for cleaning operations
    
    # Direct NaN and Inf checks are now safe
    nan_count = np.isnan(features_cleaned).sum()
    inf_count = np.isinf(features_cleaned).sum()
    
    if nan_count > 0 or inf_count > 0:
        logger.warning(f"Found {nan_count} NaN values and {inf_count} Inf values in strictly numeric feature data. Cleaning with np.nan_to_num...")
        features_cleaned = np.nan_to_num(features_cleaned, nan=0.0, posinf=0.0, neginf=0.0)
    
    # Check for columns with zero variance which can cause problems
    feature_stds = np.std(features_cleaned, axis=0)
    zero_var_cols = np.where(feature_stds < 1e-8)[0]
    if len(zero_var_cols) > 0:
        logger.warning(f"Found {len(zero_var_cols)} features with zero variance. Setting their std to 1.0")
        # No need to modify here as we already handle this in the environment
    
    # Replace the original features with the cleaned version
    features = features_cleaned
    
    # Split into train and test sets
    split_idx = int(len(price_data) * 0.8)
    
    train_prices = price_data[:split_idx]
    test_prices = price_data[split_idx:]
    
    train_features = features[:split_idx]
    test_features = features[split_idx:]
    
    logger.info(f"Data prepared: {len(train_prices)} training samples, {len(test_features)} testing samples")
    
    # Generate model name if not provided (only for the first chunk)
    if model_name is None:
        model_name = f"{args.symbol}_fast_rl_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Enable memory optimization if requested
    memory_opts = {}
    if hasattr(args, 'memory_buffer_size'):
        memory_opts['memory_buffer_size'] = args.memory_buffer_size
    if hasattr(args, 'enable_memory_optimization'):
        memory_opts['enable_memory_optimization'] = args.enable_memory_optimization
    
    # Log whether we're using an existing agent
    if agent is not None:
        logger.info(f"Continuing training with existing agent (model: {model_name})")
        
        # Update feature names for existing agent
        agent.feature_names = feature_names
    else:
        logger.info(f"Creating new agent (model: {model_name})")
    
    agent, env = train_fast_rl_agent(
        price_data=train_prices,
        feature_data=train_features,
        episodes=args.episodes,
        batch_size=args.batch_size,
        initial_balance=args.initial_balance,
        model_name=model_name,
        network_type=args.network_type,
        risk_free_rate=args.risk_free_rate,
        sharpe_lookback=args.sharpe_lookback,
        sharpe_weight=args.sharpe_weight,
        position_sizing=args.position_sizing,
        max_position_pct=args.max_position_pct,
        resolution=args.resolution,
        reward_type=args.reward_type,
        slippage_pct=args.slippage,
        existing_agent=agent,  # Pass existing agent for continued training
        feature_names=feature_names,  # Pass feature names for importance analysis
        **memory_opts  # Pass memory optimization options
    )
    
    # Evaluate the agent on test data
    if len(test_prices) > 0:
        logger.info("Evaluating agent on test data")
        
        # Create OHLCV dataframe for visualization from the original df
        test_start_idx = split_idx
        test_ohlcv_df = None
        
        if 'timestamp' in df.columns:
            test_ohlcv_df = df.iloc[test_start_idx:][['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
            # Ensure timestamp is in datetime format
            if not pd.api.types.is_datetime64_any_dtype(test_ohlcv_df['timestamp']):
                test_ohlcv_df['timestamp'] = pd.to_datetime(test_ohlcv_df['timestamp'])
        
        eval_results = evaluate_fast_agent(
            agent=agent,
            price_data=test_prices,
            feature_data=test_features,
            initial_balance=args.initial_balance,
            risk_free_rate=args.risk_free_rate,
            sharpe_lookback=args.sharpe_lookback,
            sharpe_weight=args.sharpe_weight,
            position_sizing=args.position_sizing,
            max_position_pct=args.max_position_pct,
            resolution=args.resolution,
            reward_type=args.reward_type,
            slippage_pct=args.slippage,
            visualize_trades=True,
            orig_ohlcv_df=test_ohlcv_df
        )
        
        logger.info(f"Evaluation results:")
        logger.info(f"Final portfolio value: ${eval_results['final_value']:.2f}")
        logger.info(f"Cash balance: ${eval_results['cash_balance']:.2f}")
        logger.info(f"Position value: ${eval_results['position_value']:.2f}")
        logger.info(f"Return on investment: {eval_results['roi']:.2%}")
        logger.info(f"Buy & Hold return: {eval_results['buy_hold_return']:.2%}")
        logger.info(f"Win rate: {eval_results['win_rate']:.2%}")
        logger.info(f"Total trades: {eval_results['total_trades']}")
        logger.info(f"Sharpe ratio: {eval_results['sharpe_ratio']:.4f}")
    
    elapsed_time = time.time() - start_time
    logger.info(f"Fast RL model training completed in {elapsed_time:.2f} seconds: {model_name}")
    return agent, eval_results

def analyze_feature_importance_cmd(args):
    """Analyze feature importance for a trained RL agent"""
    from src.model.fast_rl_agent import FastDQNAgent, run_feature_importance_analysis
    import tensorflow as tf
    
    logger.info(f"Analyzing feature importance for model: {args.model_path}")
    
    # Load the agent
    try:
        # Check if file exists
        if not os.path.exists(args.model_path):
            logger.error(f"Model file not found: {args.model_path}")
            return
        
        # Load model
        model = tf.keras.models.load_model(args.model_path)
        
        # Create agent
        state_size = model.input_shape[1]
        action_size = model.output_shape[1]
        
        logger.info(f"Model loaded: state_size={state_size}, action_size={action_size}")
        
        # Create agent instance
        agent = FastDQNAgent(state_size, action_size)
        agent.model = model
        
    except Exception as e:
        logger.error(f"Error loading model: {e}")
        return
    
    # Get data to use for analysis
    data_processor = DataProcessor()
    
    logger.info(f"Fetching data for importance analysis: {args.days} days of {args.resolution} data")
    df = data_processor.process_pipeline(
        args.token_address, 
        args.symbol, 
        args.resolution, 
        args.days, 
        save_data=False,
        include_sentiment=args.include_social
    )
    
    if df.empty:
        logger.error("No data available for analysis")
        return
    
    # Drop any NaN values and extract features
    df = df.dropna()
    
    # Extract price data and features
    price_data = df['close'].values
    
    # Extract features excluding price data
    drop_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    feature_cols = [col for col in df.columns if col not in drop_cols]
    features = df[feature_cols].values
    
    feature_names = feature_cols.copy()
    logger.info(f"Extracted {len(feature_names)} feature names for importance analysis")
    
    # Run importance analysis
    output_dir = os.path.dirname(args.model_path)
    model_name = os.path.basename(args.model_path).replace('.h5', '')
    
    # Run the analysis
    importance_results = run_feature_importance_analysis(
        agent=agent,
        price_data=price_data,
        feature_data=features,
        feature_names=feature_names,
        n_repeats=args.n_repeats,
        sample_size=args.sample_size,
        output_dir=output_dir,
        prefix=f"{model_name}_importance"
    )
    
    logger.info(f"Feature importance analysis completed and saved to {output_dir}")

def test_fast_rl_agent(args: Dict[str, Any]):
    """
    Loads a trained Fast RL agent and evaluates it on historical data for a specified token.

    Args:
        args: Dictionary containing command-line arguments like:
            token_address: Address of the token to test on.
            symbol: Symbol of the token.
            agent_path: Path to the saved agent model/weights.
            days: Number of days of historical data for testing.
            resolution: Data resolution.
            initial_balance: Starting balance for the simulation.
    """
    logger.info(f"--- Starting Fast RL Agent Test --- ")
    logger.info(f"Token: {args['symbol']} ({args['token_address']})")
    logger.info(f"Agent Path: {args['agent_path']}")
    logger.info(f"Test Period: {args['days']} days, Resolution: {args['resolution']}")

    # 1. Load Data for the target token
    data_processor = DataProcessor()
    df = data_processor.process_pipeline(
        token_address=args['token_address'],
        symbol=args['symbol'],
        resolution=args['resolution'],
        days=args['days'],
        save_data=False, # Don't save data during testing
        include_sentiment=True # Include sentiment data to match training data features
    )

    if df.empty or len(df) < 50: # Need some data points to test
        logger.error("Not enough historical data available for testing. Exiting.")
        return

    logger.info(f"Loaded {len(df)} data points for testing.")

    # Save a copy of the original dataframe with timestamps for visualization
    original_df = df.copy()
    
    # Prepare data for the environment
    price_data = df['close'].values
    # Extract features (ensure this matches how features were prepared for training)
    drop_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume'] # Adjust if different
    feature_cols = [col for col in df.columns if col not in drop_cols]
    if not feature_cols:
        logger.error("No feature columns found after processing. Cannot create environment state.")
        return
    feature_data = df[feature_cols].values
    logger.info(f"Extracted {feature_data.shape[1]} features for environment state.")

    # 2. Initialize Environment with the new data
    try:
        # Import and use FastTradingEnvironment just like in training
        from src.model.fast_rl_agent import FastTradingEnvironment
        
        # Default values for parameters
        risk_free_rate = 0.0
        sharpe_lookback = 30
        sharpe_weight = 2.0
        position_sizing = "fixed"
        max_position_pct = 0.5
        reward_type = "combined"
        slippage_pct = 0.0015
        
        # Use the same environment class as in training with all required parameters
        env = FastTradingEnvironment(
            price_data, 
            feature_data, 
            initial_balance=args.get('initial_balance', 10000.0),
            risk_free_rate=risk_free_rate,
            sharpe_lookback=sharpe_lookback,
            sharpe_weight=sharpe_weight,
            position_sizing=position_sizing,
            max_position_pct=max_position_pct,
            resolution=args['resolution'],
            reward_type=reward_type,
            slippage_pct=slippage_pct
        )
        
        # Get a sample observation to determine state size
        sample_observation = env._get_observation()
        state_size = len(sample_observation)
        logger.info(f"Trading Environment initialized. State size: {state_size}")
    except NameError:
        logger.error("FastTradingEnvironment class not found. Please ensure it's defined or imported correctly.")
        return
    except Exception as e:
        logger.error(f"Error initializing Trading Environment: {e}", exc_info=True)
        return

    # 3. Initialize and Load Agent
    try:
        # Use the state_size determined from the environment
        action_size = 3  # Assuming 3 actions: hold, buy, sell
        agent = FastDQNAgent(state_size=state_size, action_size=action_size)
        agent.load(args['agent_path'])
        logger.info(f"Agent loaded successfully from {args['agent_path']}")
    except NameError:
        logger.error("FastDQNAgent class not found. Please ensure it's defined or imported correctly.")
        return
    except FileNotFoundError:
        logger.error(f"Agent file not found at: {args['agent_path']}")
        return
    except Exception as e:
        logger.error(f"Error initializing or loading Agent: {e}", exc_info=True)
        return

    # 4. Run Evaluation with visualization
    from src.model.fast_rl_agent import evaluate_fast_agent
    
    # Create properly formatted OHLCV DataFrame for visualization
    ohlcv_df = original_df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
    
    # Ensure timestamp is in datetime format for visualization
    if not pd.api.types.is_datetime64_any_dtype(ohlcv_df['timestamp']):
        ohlcv_df['timestamp'] = pd.to_datetime(ohlcv_df['timestamp'])
    
    evaluation_results = evaluate_fast_agent(
        agent=agent,
        price_data=price_data,
        feature_data=feature_data,
        initial_balance=args.get('initial_balance', 10000.0),
        risk_free_rate=risk_free_rate,
        sharpe_lookback=sharpe_lookback,
        sharpe_weight=sharpe_weight,
        position_sizing=position_sizing,
        max_position_pct=max_position_pct,
        resolution=args['resolution'],
        reward_type=reward_type,
        slippage_pct=slippage_pct,
        visualize_trades=True,
        orig_ohlcv_df=ohlcv_df
    )
    
    # 5. Report Results
    final_portfolio_value = evaluation_results['final_value']
    initial_balance = args.get('initial_balance', 10000.0)
    total_return_pct = (final_portfolio_value - initial_balance) / initial_balance * 100
    
    # Calculate Buy & Hold return for comparison
    buy_hold_return_pct = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100
    
    logger.info(f"--- Test Results for {args['symbol']} --- ")
    logger.info(f"Agent Path: {args['agent_path']}")
    logger.info(f"Test Period: {args['days']} days ({len(df)} steps)")
    logger.info(f"Initial Balance: ${initial_balance:.2f}")
    logger.info(f"Final Portfolio Value: ${final_portfolio_value:.2f}")
    logger.info(f"Total Return: {total_return_pct:.2f}%")
    logger.info(f"Buy & Hold Return: {buy_hold_return_pct:.2f}%")
    logger.info(f"Total Trades Executed: {evaluation_results['total_trades']}")
    logger.info(f"Win Rate: {evaluation_results['win_rate']:.2%}")
    
    # Report the path to the trade visualization if it was generated
    if evaluation_results.get('trade_visualization'):
        logger.info(f"Trade visualization saved to: {evaluation_results['trade_visualization']}")
        
    return evaluation_results

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Train a Fast RL agent for trading')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Add train command
    train_parser = subparsers.add_parser('train', help='Train a Fast RL agent')
    train_parser.add_argument('--token-address', type=str, required=True,
                        help='Address of the token to train on')
    train_parser.add_argument('--symbol', type=str, default='SOL',
                        help='Symbol of the token')
    train_parser.add_argument('--days', type=int, default=30,
                        help='Number of days of historical data to use')
    train_parser.add_argument('--resolution', type=str, default='1H',
                        help='Data resolution (1m, 5m, 15m, 1H, 4h, 1d)')
    train_parser.add_argument('--episodes', type=int, default=100,
                        help='Number of training episodes')
    train_parser.add_argument('--batch-size', type=int, default=128,
                        help='Training batch size')
    train_parser.add_argument('--initial-balance', type=float, default=30000.0,
                        help='Initial balance for trading')
    train_parser.add_argument('--force-reprocess', action='store_true',
                        help='Force reprocessing of data even if cached data exists')
    train_parser.add_argument('--network-type', type=str, default='simple',
                        choices=['simple', 'deep', 'lstm', 'stateful_lstm', 'stacked_lstm', 'lstm_attention', 'bidirectional_lstm', 'dueling'],
                        help='Neural network architecture to use: simple (fastest), deep (better), lstm (temporal patterns), stateful_lstm (maintains state between steps), or dueling (separate value/advantage)')
    
    # Add Sharpe ratio parameters
    train_parser.add_argument('--risk-free-rate', type=float, default=0.05,
                        help='Annual risk-free rate for Sharpe ratio calculation')
    train_parser.add_argument('--sharpe-lookback', type=int, default=30,
                        help='Number of steps to use for Sharpe ratio calculation')
    train_parser.add_argument('--sharpe-weight', type=float, default=2.0,
                        help='Weight of Sharpe ratio in reward function')
    
    # Add position sizing parameters
    train_parser.add_argument('--position-sizing', type=str, default='fixed',
                        choices=['fixed', 'kelly', 'random'],
                        help='Position sizing strategy to use')
    train_parser.add_argument('--max-position-pct', type=float, default=0.2,
                        help='Maximum position size as fraction of portfolio (0.2 = 20%)')
    
    # Add reward type parameter
    train_parser.add_argument('--reward-type', type=str, default='combined',
                        choices=['combined', 'sharpe_only', 'simplified_profit_sharpe', 'profit_focused'],
                        help='Type of reward function to use: combined (original complex), sharpe_only, or simplified_profit_sharpe')
    
    # Add slippage parameter
    train_parser.add_argument('--slippage', type=float, default=0.0015,
                        help='Amount of slippage to apply to trades (0.0015 = 15 basis points)')
    
    # Add social data parameter
    train_parser.add_argument('--include-social', action='store_true', default=True,
                        help='Include social data features in the model (default: True)')
    
    # Add lagged features parameters
    train_parser.add_argument('--lag-periods', type=int, default=0,
                        help='Number of lag periods to add for time series features')
    train_parser.add_argument('--lag-features', type=str, default=None,
                        help='Comma-separated list of columns to add lag features for. If not specified, uses a default set.')
                        
    # Add memory management parameters
    train_parser.add_argument('--memory-buffer-size', type=int, default=1000000,
                        help='Maximum size of experience replay buffer')
    train_parser.add_argument('--enable-memory-optimization', action='store_true',
                        help='Enable aggressive memory optimization for large models')
                        
    # Test command
    test_parser = subparsers.add_parser('test', help='Test a trained Fast RL agent')
    test_parser.add_argument('--model-path', type=str, required=True,
                        help='Path to the trained model (.h5 file)')
    test_parser.add_argument('--token-address', type=str, required=True,
                        help='Address of the token to test on')
    test_parser.add_argument('--symbol', type=str, default='SOL',
                        help='Symbol of the token')
    test_parser.add_argument('--days', type=int, default=30,
                        help='Number of days of historical data to use')
    test_parser.add_argument('--resolution', type=str, default='5m',
                        help='Data resolution (1m, 5m, 15m, 1H, 4h, 1d)')
    test_parser.add_argument('--include-social', action='store_true', default=True,
                        help='Include social data features in the model (default: True)')
    test_parser.add_argument('--day-offset', type=int, default=0,
                        help='Days to offset for test data (0 = most recent)')
    
    # Continue command
    continue_parser = subparsers.add_parser('continue', help='Continue training an existing Fast RL agent')
    continue_parser.add_argument('--model-path', type=str, required=True,
                            help='Path to the trained model (.h5 file)')
    continue_parser.add_argument('--token-address', type=str, required=True,
                            help='Address of the token to train on')
    continue_parser.add_argument('--symbol', type=str, default='SOL',
                            help='Symbol of the token')
    continue_parser.add_argument('--days', type=int, default=30,
                            help='Number of days of historical data to use')
    continue_parser.add_argument('--resolution', type=str, default='5m',
                            help='Data resolution (1m, 5m, 15m, 1H, 4h, 1d)')
    continue_parser.add_argument('--episodes', type=int, default=50,
                            help='Number of additional training episodes')
    continue_parser.add_argument('--include-social', action='store_true', default=True,
                            help='Include social data features in the model (default: True)')
    continue_parser.add_argument('--initial-balance', type=float, default=10000.0,
                            help='Initial balance for trading')
    continue_parser.add_argument('--day-offset', type=int, default=0,
                            help='Days to offset for training data (0 = most recent)')
    continue_parser.add_argument('--lag-periods', type=int, default=12,
                            help='Number of lag periods to add for time series features')
    continue_parser.add_argument('--batch-size', type=int, default=128,
                            help='Batch size for training')
    continue_parser.add_argument('--memory-buffer-size', type=int, default=1000000,
                            help='Maximum size of experience replay buffer')
    continue_parser.add_argument('--enable-memory-optimization', action='store_true',
                            help='Enable aggressive memory optimization for large models')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze feature importance of a trained agent')
    analyze_parser.add_argument('--model-path', type=str, required=True,
                            help='Path to the trained model (.h5 file)')
    analyze_parser.add_argument('--token-address', type=str, required=True,
                            help='Address of the token to analyze')
    analyze_parser.add_argument('--symbol', type=str, default='SOL',
                            help='Symbol of the token')
    analyze_parser.add_argument('--days', type=int, default=30,
                            help='Number of days of historical data to use')
    analyze_parser.add_argument('--resolution', type=str, default='5m',
                            help='Data resolution (1m, 5m, 15m, 1H, 4h, 1d)')
    analyze_parser.add_argument('--include-social', action='store_true', default=True,
                            help='Include social data features in the model (default: True)')
    analyze_parser.add_argument('--lag-periods', type=int, default=12,
                            help='Number of lag periods to add for time series features')
    
    return parser.parse_args()

def main():
    """Parse arguments and run training"""
    args = parse_args()
    
    # If no command is specified, default to 'train'
    if args.command is None:
        args.command = 'train'
    
    if args.command == 'train':
        # Train the model
        start_time = time.time()
        
        # Create a base agent if loading from saved model
        agent = None
        model_name = None
        
        # Process all data at once
        agent, results = train_fast_rl_model(args, agent=agent, model_name=model_name)
        
        elapsed_time = time.time() - start_time
        logger.info(f"Training completed in {elapsed_time:.2f} seconds")
    
    elif args.command == 'importance':
        # Run feature importance analysis
        analyze_feature_importance_cmd(args)
    
    elif args.command == 'continue':
        # Continue training an existing model
        start_time = time.time()
        
        try:
            # Load the existing model using our new utility function
            model_path = os.path.normpath(args.model_path)
            
            # Check if file exists
            if not os.path.exists(model_path):
                logger.error(f"Model file not found: {model_path}")
                return
                
            logger.info(f"Loading model from {model_path} for continued training")
            
            # Load the agent with the new utility function
            # Only reset epsilon if explicitly requested
            reset_epsilon = args.reset_epsilon
            agent = load_fast_rl_agent(model_path, reset_epsilon=reset_epsilon)
            
            # If reset_epsilon is specified, manually set the epsilon value
            if reset_epsilon:
                original_epsilon = agent.epsilon
                agent.epsilon = args.epsilon  # Use specified epsilon
                logger.info(f"Manually set epsilon from {original_epsilon:.4f} to {agent.epsilon:.4f}")
            else:
                logger.info(f"Continuing with existing epsilon value: {agent.epsilon:.4f}")
            
            # Extract model name from the file path
            model_name = os.path.basename(model_path).replace('.h5', '')
            
            # Create a new model name for this training session
            new_model_name = f"{model_name}_continued_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            logger.info(f"Will save continued model as: {new_model_name}")
            
            # Create args namespace for training
            train_args = argparse.Namespace(
                token_address=args.token_address,
                symbol=args.symbol,
                days=args.days,
                resolution=args.resolution,
                episodes=args.episodes,
                batch_size=256,  # Default batch size
                initial_balance=args.initial_balance,
                network_type="deep",  # Will be ignored as we're using existing agent
                risk_free_rate=0.0,
                sharpe_lookback=30,
                sharpe_weight=2.0,
                position_sizing="fixed",
                max_position_pct=0.5,
                reward_type="combined",
                slippage=0.0015,
                include_social=args.include_social,
                memory_buffer_size=10000,
                enable_memory_optimization=False
            )
            
            # Run training with the loaded agent
            agent, results = train_fast_rl_model(
                train_args, 
                agent=agent, 
                day_offset=args.day_offset,
                model_name=new_model_name
            )
            
            elapsed_time = time.time() - start_time
            logger.info(f"Continued training completed in {elapsed_time:.2f} seconds")
            
        except Exception as e:
            logger.error(f"Error during continued training: {e}")
            import traceback
            traceback.print_exc()
    
    else:
        args.parser.print_help()

if __name__ == "__main__":
    main() 