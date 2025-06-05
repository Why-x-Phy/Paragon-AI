#!/usr/bin/env python3
import os
import sys
import argparse
import asyncio
import json
from typing import Dict, Any
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path
import pandas as pd

# Add src directory to path for consistent imports
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Find and load environment variables from .env file
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent  # Navigate to project root
root_env_path = project_root / '.env'

if root_env_path.exists():
    load_dotenv(root_env_path)
else:
    # Fallback to the current directory
    current_dir_env = current_file.parent / '.env'
    if current_dir_env.exists():
        load_dotenv(current_dir_env)
    else:
        # Last resort, try default behavior
        load_dotenv()

from data.data_processor import DataProcessor
from model.ml_model import MLModel
from trading.trading_strategy import TradingStrategy
from trading.wallet import SolanaWallet
from src.config.config import config
from utils.logger import log_manager, log
from scripts.train_rl_model import train_rl_model
from scripts.train_fast_rl import train_fast_rl_model
from scripts.train_historical_rl import train_historical_rl
from scripts.train_prediction_guided import train_prediction_guided_model
from scripts.train_cross_token import train_cross_token_model

# Initialize global logger
logger = log

async def train_model(args: Dict[str, Any]) -> None:
    """Train the ML model with historical data"""
    logger.info("Starting model training")
    
    # Validate token address
    if not args['token_address']:
        logger.error("Token address is required for training")
        return
    
    token_address = args['token_address']
    symbol = args.get('symbol', 'SOL')
    days = args.get('days', 30)
    resolution = args.get('resolution', '5m')
    
    # Initialize data processor
    data_processor = DataProcessor()
    
    # Get and process data
    logger.info(f"Fetching and processing data for {symbol} ({token_address}), {days} days, {resolution} resolution")
    df = data_processor.process_pipeline(
        token_address, 
        symbol, 
        resolution, 
        days, 
        save_data=True,
        include_sentiment=True  # Skip sentiment data for now
    )
    
    if df.empty:
        logger.error("No data available for training")
        return
    
    # Prepare data for ML
    sequence_length = args.get('sequence_length', 26)
    prediction_steps = args.get('prediction_horizon', 24)
    
    logger.info(f"Preparing ML data with sequence_length={sequence_length}, prediction_horizon={prediction_steps} steps")
    X_train, X_test, y_train, y_test = data_processor.prepare_ml_data(
        df, 
        target_col='close',
        sequence_length=sequence_length,
        prediction_horizon=prediction_steps,
        include_feature_names=False
    )
    
    logger.info(f"Data prepared: {X_train.shape[0]} training samples, {X_test.shape[0]} testing samples")
    
    # Initialize and train model
    model_type = args.get('model_type', config.model_type)
    ml_model = MLModel(model_type=model_type)
    
    # Check if we should use bidirectional LSTM
    use_bidirectional = args.get('bidirectional', True)
    
    # Build the model
    ml_model.build_model(input_shape=(X_train.shape[1], X_train.shape[2]), use_bidirectional=use_bidirectional)
    
    # Train the model
    epochs = args.get('epochs', 100)
    batch_size = args.get('batch_size', 32)
    model_name = args.get('model_name', f"{symbol}_{model_type}_{datetime.now().strftime('%Y%m%d')}")
    
    history = ml_model.train(
        X_train, y_train,
        X_test, y_test,
        epochs=epochs,
        batch_size=batch_size,
        model_name=model_name
    )
    
    # Evaluate the model - DISABLE the broken backtest like in testing
    metrics = ml_model.evaluate(X_test, y_test, include_backtest=False)  # FIXED: Disable broken backtest
    ml_model.save_evaluation_metrics(metrics, model_name)
    
    # Plot results if requested
    if args.get('plot', False):
        ml_model.plot_training_history(history, f"{model_name}_training.png")
        
        # Make predictions and plot
        y_pred = ml_model.predict(X_test)
        y_true = y_test
        
        # Convert predictions back to original scale
        y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
        y_true_orig = data_processor.inverse_transform_predictions(y_true, data_processor.prices_at_sequence_end_test)
        
        ml_model.plot_predictions(y_true_orig, y_pred_orig, f"{model_name}_predictions.png")
    
    logger.info(f"Model training completed: {model_name}")
    logger.info(f"Evaluation metrics: {metrics}")

async def test_model(args: Dict[str, Any]) -> None:
    """Test the trained model against historical data"""
    logger.info("Starting model testing")
    
    # Find the model to test
    model_path = args.get('model_path')
    if not model_path:
        # Look for latest model
        ml_model = MLModel()
        model_path = ml_model.get_latest_model_path()
        
        if not model_path:
            logger.error("No model found for testing")
            return
    
    logger.info(f"Testing model: {model_path}")
    
    # Load the model
    ml_model = MLModel()
    ml_model.load(model_path)
    
    # Get test data
    token_address = args.get('token_address')
    symbol = args.get('symbol', 'SOL')
    days = args.get('days', 10)  # Use fewer days for testing
    resolution = args.get('resolution', '15m')  # Add resolution parameter with default
    
    data_processor = DataProcessor()
    df = data_processor.process_pipeline(token_address, symbol, resolution, days, save_data=False)
    
    if df.empty:
        logger.error("No data available for testing")
        return
    
    # Prepare test data using a consistent dataframe
    sequence_length = args.get('sequence_length', 36)  # Should match the model's expected input
    prediction_steps = args.get('prediction_horizon', 1)  # Use 1 to match optimization script default
    
    logger.info(f"Testing with sequence_length={sequence_length}, prediction_horizon={prediction_steps} steps")
    
    df_for_ml = df.copy()  # Use consistent processed dataframe
    _, X_test, _, y_test = data_processor.prepare_ml_data(
        df_for_ml,  # Use the same dataframe consistently
        target_col='close',
        sequence_length=sequence_length,
        prediction_horizon=prediction_steps,
        test_size=0.99,  # Use same test_size as optimization script for consistency
        include_feature_names=False
    )
    
    # Evaluate model - get basic metrics only (no backtest)
    metrics = ml_model.evaluate(X_test, y_test, include_backtest=False)  # DISABLE old backtest - it uses normalized data
    logger.info(f"Test metrics: {metrics}")
    
    # Make predictions and convert back to original scale
    y_pred = ml_model.predict(X_test)
    # Use the stored prices from the data_processor for inverse transform
    y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
    # Similarly for y_test - need prices at the *start* of the prediction horizon
    # Let's recalculate y_test_orig from the original dataframe for simplicity here
    # We need the price at the step *before* the target step
    original_indices = df_for_ml.index[-(len(y_test)+prediction_steps-1):-(prediction_steps-1)] if prediction_steps > 1 else df_for_ml.index[-len(y_test):]
    base_prices_for_y_test = df_for_ml.loc[original_indices, 'close'].values
    # Get the original target pct changes (we didn't store these)
    target_pct_changes = data_processor.price_scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()
    y_true_orig = base_prices_for_y_test * (1 + target_pct_changes)
    
    logger.info("\n" + "="*70)
    logger.info("RUNNING BACKTEST WITH REAL PRICE DATA")
    logger.info("="*70)

    # Run ONLY our new simple backtest using the optimized strategy
    from model.profit_functions import simple_backtest_strategy
    backtest_results = simple_backtest_strategy(
        prices=y_true_orig,
        predictions=y_pred_orig,
        ohlcv_df=df_for_ml, # Use the SAME processed DataFrame for consistent calculations
        include_detailed_trades=True,
        verbosity=1,
        resolution=resolution,
        buy_threshold=0.02,  # Buy when predicted increase >= 2%
        sell_threshold=0.04  # Sell when predicted decrease >= 3%
    )
    
    # Log backtest results (only the new/correct ones)
    logger.info(f"Backtest Results:")
    logger.info(f"  Total Return: {backtest_results['Total Return']:.2f}%")
    logger.info(f"  Buy & Hold Return: {backtest_results['Buy & Hold Return']:.2f}%")
    logger.info(f"  Win Rate: {backtest_results['Win Rate']:.2f}%")
    logger.info(f"  Max Drawdown: {backtest_results['Max Drawdown']:.2f}%")
    logger.info(f"  Sharpe Ratio: {backtest_results['Sharpe Ratio']:.2f}")
    logger.info(f"  Total Trades: {backtest_results['Total Trades']}")
    logger.info(f"  Final Portfolio Value: ${backtest_results['Final Portfolio Value']:.2f}")
    
    # Plot if requested
    if args.get('plot', False):
        # Original prediction plots
        ml_model.plot_predictions(
            y_true_orig, 
            y_pred_orig, 
            f"test_predictions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        
        # Add the price comparison plot
        ml_model.plot_price_comparison(
            y_true_orig,
            y_pred_orig,
            f"test_price_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        
        # NEW: Plot backtest with signals using the improved function
        from model.profit_functions import plot_backtest_with_signals
        
        # Use the REAL OHLCV data we already fetched, not fake data
        # Get the test period OHLCV data that corresponds to our predictions
        test_start_idx = len(df) - len(y_true_orig)
        real_ohlcv_df = df.iloc[test_start_idx:].copy()
        
        # DEBUG: Check original DataFrame structure
        logger.info(f"Original DataFrame index type: {type(df.index)}")
        logger.info(f"Original DataFrame index name: {df.index.name}")
        logger.info(f"Original DataFrame has timestamp column: {'timestamp' in df.columns}")
        logger.info(f"Original DataFrame columns containing 'time': {[col for col in df.columns if 'time' in col.lower()]}")
        
        # Ensure we have the required columns and proper indexing
        if len(real_ohlcv_df) == len(y_true_orig):
            # Reset index to avoid any issues and bring timestamp back as column if it's the index
            if real_ohlcv_df.index.name == 'timestamp' or 'timestamp' in str(type(real_ohlcv_df.index)):
                real_ohlcv_df = real_ohlcv_df.reset_index()
            else:
                real_ohlcv_df = real_ohlcv_df.reset_index(drop=True)
            
            # DEBUG: Check what columns we actually have
            logger.info(f"OHLCV DataFrame columns: {list(real_ohlcv_df.columns)}")
            logger.info(f"OHLCV DataFrame shape: {real_ohlcv_df.shape}")
            
            # Ensure timestamp column exists - if not, create one from index
            if 'timestamp' not in real_ohlcv_df.columns:
                # Check for common timestamp column names - but exclude sentiment data
                timestamp_cols = [col for col in real_ohlcv_df.columns 
                                if ('time' in col.lower() or 'date' in col.lower()) 
                                and 'sentiment' not in col.lower()]
                if timestamp_cols:
                    real_ohlcv_df['timestamp'] = real_ohlcv_df[timestamp_cols[0]]
                    logger.info(f"Using column '{timestamp_cols[0]}' as timestamp")
                else:
                    # Create timestamps from index (using the actual test period)
                    # Use the original DataFrame index as reference if available
                    test_start_idx = len(df) - len(y_true_orig)
                    if test_start_idx >= 0 and 'timestamp' in df.columns:
                        # Use actual timestamps from the original DataFrame
                        real_ohlcv_df['timestamp'] = df['timestamp'].iloc[test_start_idx:test_start_idx + len(y_true_orig)].values
                        logger.info("Using actual timestamps from original DataFrame")
                    else:
                        # Fall back to synthetic timestamps
                        start_time = datetime.now() - timedelta(hours=len(real_ohlcv_df))
                        real_ohlcv_df['timestamp'] = [start_time + timedelta(hours=i) for i in range(len(real_ohlcv_df))]
                        logger.info("Created synthetic timestamp column from index")
            
            # Plot backtest with signals using REAL market data
            plot_filename = f"test_backtest_signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            plot_path = plot_backtest_with_signals(
                ohlcv_data=real_ohlcv_df,
                trades=backtest_results.get('trades', []),
                filename=plot_filename,
                title=f"{symbol} Backtest Results - {resolution} Resolution (Real OHLCV)",
                output_dir="models"
            )
            
            if plot_path:
                logger.info(f"Backtest visualization saved to: {plot_path}")
        else:
            logger.warning(f"OHLCV data length mismatch: {len(real_ohlcv_df)} vs predictions: {len(y_true_orig)}")
            logger.info("Skipping backtest visualization due to data mismatch")
    
    # Calculate price change accuracy
    correct_direction = 0
    for i in range(1, len(y_true_orig)):
        actual_change = y_true_orig[i] - y_true_orig[i-1]
        predicted_change = y_pred_orig[i] - y_true_orig[i-1]
        
        if (actual_change >= 0 and predicted_change >= 0) or (actual_change < 0 and predicted_change < 0):
            correct_direction += 1
    
    direction_accuracy = correct_direction / (len(y_true_orig) - 1) if len(y_true_orig) > 1 else 0
    logger.info(f"Price direction accuracy: {direction_accuracy:.2%}")

async def run_trading_bot(args: Dict[str, Any]) -> None:
    """Run the trading bot"""
    logger.info("Starting trading bot")
    
    # Validate required parameters
    token_address = args.get('token_address')
    if not token_address:
        logger.error("Token address is required for trading")
        return
    
    symbol = args.get('symbol', 'SOL')
    model_path = args.get('model_path')
    
    # Initialize wallet
    wallet = SolanaWallet()
    balance = wallet.get_balance()
    logger.info(f"Wallet initialized: {wallet.public_key}")
    logger.info(f"Wallet balance: {balance} SOL")
    
    # Initialize trading strategy
    strategy = TradingStrategy(
        token_address=token_address,
        symbol=symbol,
        model_path=model_path,
        wallet=wallet
    )
    
    # Run strategy with specified interval
    interval_minutes = args.get('interval', config.trading_interval_minutes)
    await strategy.run(interval_minutes=interval_minutes)

async def create_wallet(args: Dict[str, Any]) -> None:
    """Create a new Solana wallet"""
    logger.info("Creating new Solana wallet")
    
    # Create wallet
    wallet = SolanaWallet()
    
    # Save wallet information (for development only)
    save_path = args.get('save_path', 'wallet.json')
    wallet.save_wallet_info(save_path)
    
    logger.info(f"New wallet created: {wallet.public_key}")
    logger.info(f"Wallet information saved to: {save_path}")
    logger.info("IMPORTANT: Store this file securely and never share your private key!")

async def get_token_info(args: Dict[str, Any]) -> None:
    """Get information about a token"""
    logger.info("Fetching token information")
    
    from data.birdeye_api import BirdEyeAPI
    from data.helius_api import HeliusAPI
    
    token_address = args.get('token_address')
    if not token_address:
        logger.error("Token address is required")
        return
    
    # Get info from BirdEye
    try:
        birdeye = BirdEyeAPI()
        price_data = birdeye.get_token_price(token_address)
        metadata = birdeye.get_token_metadata(token_address)
        
        print("\n===== Token Information =====")
        if 'data' in metadata:
            token_data = metadata['data']
            print(f"Name: {token_data.get('name', 'Unknown')}")
            print(f"Symbol: {token_data.get('symbol', 'Unknown')}")
            print(f"Decimals: {token_data.get('decimals', 'Unknown')}")
            
            # Check if we have extensions data in the v3 API format
            if 'extensions' in token_data:
                ext = token_data['extensions']
                if ext.get('website'):
                    print(f"Website: {ext['website']}")
                if ext.get('twitter'):
                    print(f"Twitter: {ext['twitter']}")
                if ext.get('description'):
                    print(f"Description: {ext['description']}")
        
        if 'data' in price_data and 'value' in price_data['data']:
            print(f"Price: ${float(price_data['data']['value']):.6f}")
        
        # Get more data
        print("\n===== Market Data =====")
        ohlcv = birdeye.get_token_ohlcv(token_address, "1d", 1)
        if not ohlcv.empty:
            print(f"24h Volume: ${ohlcv['volume'].iloc[0]:.2f}")
            print(f"24h High: ${ohlcv['high'].iloc[0]:.6f}")
            print(f"24h Low: ${ohlcv['low'].iloc[0]:.6f}")
    
    except Exception as e:
        logger.error(f"Error getting token info: {e}")

async def train_cross_token(args: Dict[str, Any]) -> None:
    """Train cross-token generalization agent on multiple tokens"""
    logger.info("Starting cross-token agent training")
    
    # Get token list
    tokens = args.get('tokens')
    if not tokens:
        logger.error("Token list is required for cross-token training")
        return
    
    # Parse comma-separated token list
    token_list = [t.strip() for t in tokens.split(',')]
    
    # Run training
    train_cross_token_model(
        token_list=token_list,
        days=args.get('days', 30),
        resolution=args.get('resolution', '5m'),
        episodes=args.get('episodes', 200),
        batch_size=args.get('batch_size', 64),
        ml_model_base_path="models",
        token_scheduling=args.get('scheduling', 'random'),
        use_predictions=not args.get('no_predictions', False),
        initial_balance=args.get('balance', 10000.0),
        sequence_length=args.get('sequence_length', 10)
    )
    
    logger.info("Cross-token agent training completed")

async def train_simple_model(args: Dict[str, Any]) -> None:
    """Train a model using simple directional prediction and backtesting"""
    logger.info("Starting simple model training")
    
    # Validate token address
    if not args['token_address']:
        logger.error("Token address is required for training")
        return
    
    token_address = args['token_address']
    symbol = args.get('symbol', 'SOL')
    days = args.get('days', 30)
    resolution = args.get('resolution', '5m')
    
    # Initialize data processor
    data_processor = DataProcessor()
    
    # Get and process data
    logger.info(f"Fetching and processing data for {symbol} ({token_address}), {days} days, {resolution} resolution")
    df = data_processor.process_pipeline(
        token_address, 
        symbol, 
        resolution, 
        days, 
        save_data=True,
        include_sentiment=False
    )
    
    if df.empty:
        logger.error("No data available for training")
        return
    
    # Prepare data for ML
    sequence_length = args.get('sequence_length', 26)
    prediction_steps = args.get('prediction_horizon', 1)
    
    logger.info(f"Preparing ML data with sequence_length={sequence_length}, prediction_horizon={prediction_steps} steps")
    X_train, X_test, y_train, y_test = data_processor.prepare_ml_data(
        df, 
        target_col='close',
        sequence_length=sequence_length,
        prediction_horizon=prediction_steps,
        include_feature_names=False
    )
    
    logger.info(f"Data prepared: {X_train.shape[0]} training samples, {X_test.shape[0]} testing samples")
    
    # Initialize and train model with simple directional optimization
    model_type = args.get('model_type', config.model_type)
    ml_model = MLModel(model_type=model_type, optimization_target="mse")
    
    logger.info(f"Using MSE optimization for training")
    
    # Build the model
    ml_model.build_model(input_shape=(X_train.shape[1], X_train.shape[2]))
    
    # Train the model
    epochs = args.get('epochs', 100)
    batch_size = args.get('batch_size', 32)
    model_name = args.get('model_name', f"{symbol}_simple_{datetime.now().strftime('%Y%m%d')}")
    
    history = ml_model.train(
        X_train, y_train,
        X_test, y_test,
        epochs=epochs,
        batch_size=batch_size,
        model_name=model_name
    )
    
    # Evaluate the model
    metrics = ml_model.evaluate(X_test, y_test, resolution=resolution)
    ml_model.save_evaluation_metrics(metrics, model_name)
    
    # Run simple backtest
    logger.info(f"Running simple backtest strategy")
    y_pred = ml_model.predict(X_test)
    
    # Convert predictions and test data back to original scale
    # Use the stored prices from the data_processor for inverse transform
    y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
    # Recalculate y_test_orig from original df
    original_indices = df.index[-(len(y_test)+prediction_steps-1):-(prediction_steps-1)] if prediction_steps > 1 else df.index[-len(y_test):]
    base_prices_for_y_test = df.loc[original_indices, 'close'].values
    target_pct_changes = data_processor.price_scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()
    y_test_orig = base_prices_for_y_test * (1 + target_pct_changes)
    
    # Run and plot simple backtest
    ml_model.plot_simple_backtest(
        y_test_orig, 
        y_pred_orig, 
        filename=f"{model_name}_simple_backtest.png",
        resolution=resolution
    )
    
    # Plot training history if requested
    if args.get('plot', False):
        ml_model.plot_training_history(history, f"{model_name}_training.png")
        ml_model.plot_predictions(y_test_orig, y_pred_orig, f"{model_name}_predictions.png")
        
        # Add the new price comparison plot
        ml_model.plot_price_comparison(y_test_orig, y_pred_orig, f"{model_name}_price_comparison.png")
    
    logger.info(f"Simple model training completed: {model_name}")
    logger.info(f"Evaluation metrics: {metrics}")

async def plot_price_comparison_cmd(args: Dict[str, Any]) -> None:
    """Generate a plot showing actual vs predicted closing prices for a specific model"""
    logger.info("Generating price comparison plot")
    
    # Find the model to use
    model_path = args.get('model_path')
    if not model_path:
        # Look for latest model
        ml_model = MLModel()
        model_path = ml_model.get_latest_model_path()
        
        if not model_path:
            logger.error("No model found for generating plot")
            return
    
    logger.info(f"Using model: {model_path}")
    
    # Load the model
    ml_model = MLModel()
    ml_model.load(model_path)
    
    # Get data for the plot
    token_address = args.get('token_address')
    symbol = args.get('symbol', 'SOL')
    days = args.get('days', 30)
    resolution = args.get('resolution', '1h')
    
    data_processor = DataProcessor()
    df = data_processor.process_pipeline(token_address, symbol, resolution, days, save_data=False)
    
    if df.empty:
        logger.error("No data available for plotting")
        return
    
    # Prepare test data
    sequence_length = args.get('sequence_length', 24)
    prediction_steps = args.get('prediction_horizon', 1)
    
    logger.info(f"Preparing data with sequence_length={sequence_length}, prediction_horizon={prediction_steps} steps")
    
    _, X_test, _, y_test = data_processor.prepare_ml_data(
        df, 
        target_col='close',
        sequence_length=sequence_length,
        prediction_horizon=prediction_steps,
        test_size=0.8,  # Use most of the data for testing
        include_feature_names=False
    )
    
    # Make predictions
    y_pred = ml_model.predict(X_test)
    
    # Transform predictions back to original scale
    # Use the stored prices from the data_processor for inverse transform
    y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
    # Recalculate y_test_orig from original df
    original_indices = df.index[-(len(y_test)+prediction_steps-1):-(prediction_steps-1)] if prediction_steps > 1 else df.index[-len(y_test):]
    base_prices_for_y_test = df.loc[original_indices, 'close'].values
    target_pct_changes = data_processor.price_scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()
    y_test_orig = base_prices_for_y_test * (1 + target_pct_changes)
    
    # Generate the price comparison plot
    output_file = args.get('output_file', f"{symbol}_price_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    ml_model.plot_price_comparison(y_test_orig, y_pred_orig, output_file)
    
    logger.info(f"Price comparison plot generated: {output_file}")

async def test_fast_rl_agent_cmd(args: Dict[str, Any]) -> None:
    """Wrapper to call the Fast RL agent testing logic."""
    logger.info(f"Starting Fast RL Agent testing for token {args['symbol']} ({args['token_address']})")
    # Import the actual testing function from the script where it will be defined
    # We assume it will be in scripts/train_fast_rl.py for now
    try:
        from scripts.train_fast_rl import test_fast_rl_agent # Assuming the test function is named this
        
        # Convert Namespace to dict if necessary, or pass args directly
        args_dict = vars(args) if isinstance(args, argparse.Namespace) else args
        
        # Set default values for optional arguments if not provided
        if 'initial_balance' not in args_dict:
            args_dict['initial_balance'] = 10000.0
            
        # Call the actual implementation
        test_fast_rl_agent(args_dict)
    except Exception as e:
        logger.error(f"Error testing Fast RL agent: {e}")
        # Print full traceback
        import traceback
        traceback.print_exc()

async def continue_fast_rl_model_cmd(args: Dict[str, Any]) -> None:
    """Wrapper to call the Fast RL model continuing training logic."""
    logger.info(f"Starting continued training of Fast RL Agent for token {args['symbol']} ({args['token_address']})")
    try:
        from scripts.train_fast_rl import main as train_fast_rl_main
        
        # Convert Namespace to dict if necessary
        args_dict = vars(args) if isinstance(args, argparse.Namespace) else args
        
        # Create sys.argv-like list for argparse in the train_fast_rl.py script
        argv = ['continue']  # Command for continue training
        
        # Add all arguments
        argv.extend(['--model-path', args_dict['model_path']])
        argv.extend(['--token-address', args_dict['token_address']])
        argv.extend(['--symbol', args_dict['symbol']])
        argv.extend(['--days', str(args_dict['days'])])
        argv.extend(['--resolution', args_dict['resolution']])
        argv.extend(['--episodes', str(args_dict['episodes'])])
        argv.extend(['--initial-balance', str(args_dict['initial_balance'])])
        
        if args_dict.get('include_social', True):
            argv.append('--include-social')
            
        if 'day_offset' in args_dict and args_dict['day_offset'] > 0:
            argv.extend(['--day-offset', str(args_dict['day_offset'])])
            
        # Add the new epsilon parameters
        if 'epsilon' in args_dict:
            argv.extend(['--epsilon', str(args_dict['epsilon'])])
            
        if args_dict.get('reset_epsilon', False):
            argv.append('--reset-epsilon')
            
        # Call the main function from train_fast_rl.py with our constructed arguments
        import sys
        original_argv = sys.argv
        try:
            sys.argv = [sys.argv[0]] + argv
            train_fast_rl_main()
        finally:
            sys.argv = original_argv
            
    except Exception as e:
        logger.error(f"Error continuing training of Fast RL agent: {e}")
        # Print full traceback
        import traceback
        traceback.print_exc()

def parse_arguments():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description="Solana Trading Bot")
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Train model command
    train_parser = subparsers.add_parser('train', help='Train the ML model')
    train_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to train on')
    train_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    train_parser.add_argument('--days', type=int, default=30, help='Number of days of historical data to use')
    train_parser.add_argument('--resolution', type=str, default='1H', help='Data resolution (1m, 5m, 15m, 1H, 4H, 1D)')
    train_parser.add_argument('--model-type', type=str, default=config.model_type, help='Type of ML model to use')
    train_parser.add_argument('--sequence-length', type=int, default=36, help='Number of time steps in each input sequence')
    train_parser.add_argument('--prediction-horizon', type=int, default=1, help='Number of time steps in the future to predict')
    train_parser.add_argument('--epochs', type=int, default=100, help='Number of training epochs')
    train_parser.add_argument('--batch-size', type=int, default=64, help='Training batch size')
    train_parser.add_argument('--plot', action='store_true', help='Plot training results')
    train_parser.add_argument('--bidirectional', action='store_true', default=True, help='Use bidirectional LSTM')
    train_parser.add_argument('--no-bidirectional', dest='bidirectional', action='store_false', help='Disable bidirectional LSTM')

    # Add RL train command
    rl_train_parser = subparsers.add_parser('train-rl', help='Train a Reinforcement Learning trading agent')
    rl_train_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to train on')
    rl_train_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    rl_train_parser.add_argument('--days', type=int, default=90, help='Number of days of historical data to use')
    rl_train_parser.add_argument('--resolution', type=str, default='5m', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    rl_train_parser.add_argument('--sequence-length', type=int, default=26, help='Number of time steps in RL state')
    rl_train_parser.add_argument('--episodes', type=int, default=200, help='Number of training episodes')
    rl_train_parser.add_argument('--batch-size', type=int, default=64, help='Training batch size')
    rl_train_parser.add_argument('--initial-balance', type=float, default=10000.0, help='Initial balance for trading')
    
    # Add Fast RL train command
    fast_rl_train_parser = subparsers.add_parser('train-fast-rl', help='Train an optimized fast Reinforcement Learning trading agent')
    fast_rl_train_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to train on')
    fast_rl_train_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    fast_rl_train_parser.add_argument('--days', type=int, default=30, help='Number of days of historical data to use')
    fast_rl_train_parser.add_argument('--resolution', type=str, default='5m', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    fast_rl_train_parser.add_argument('--episodes', type=int, default=100, help='Number of training episodes')
    fast_rl_train_parser.add_argument('--batch-size', type=int, default=256, help='Training batch size')
    fast_rl_train_parser.add_argument('--initial-balance', type=float, default=10000.0, help='Initial balance for trading')
    fast_rl_train_parser.add_argument('--network-type', type=str, default='simple', help='Neural network architecture to use: simple, deep, lstm, or dueling')
    fast_rl_train_parser.add_argument('--include-social', action='store_true', default=True, help='Include social sentiment data in training')
    
    # Add Sharpe ratio parameters
    fast_rl_train_parser.add_argument('--risk-free-rate', type=float, default=0.0, help='Annual risk-free rate for Sharpe ratio calculation')
    fast_rl_train_parser.add_argument('--sharpe-lookback', type=int, default=30, help='Number of steps to use for Sharpe ratio calculation')
    fast_rl_train_parser.add_argument('--sharpe-weight', type=float, default=2.0, help='Weight of Sharpe ratio in reward function')
    
    # Add position sizing parameters
    fast_rl_train_parser.add_argument('--position-sizing', type=str, default='fixed', choices=['fixed', 'kelly', 'random'], help='Position sizing strategy to use')
    fast_rl_train_parser.add_argument('--max-position-pct', type=float, default=0.5, help='Maximum position size as fraction of portfolio (0.5 = 50%)')
    
    # Add reward type parameter
    fast_rl_train_parser.add_argument('--reward-type', type=str, default='combined', choices=['combined', 'sharpe_only'], help='Type of reward function to use')
    
    # Add slippage parameter
    fast_rl_train_parser.add_argument('--slippage', type=float, default=0.0015, help='Amount of slippage to apply to trades (0.0015 = 15 basis points)')
    
    # Add Historical RL train command
    historical_rl_train_parser = subparsers.add_parser('train-historical-rl', help='Train a Reinforcement Learning agent with access to all previous history')
    historical_rl_train_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to train on')
    historical_rl_train_parser.add_argument('--symbol', type=str, default='Fartcoin', help='Symbol of the token')
    historical_rl_train_parser.add_argument('--days', type=int, default=90, help='Number of days of historical data to use')
    historical_rl_train_parser.add_argument('--resolution', type=str, default='5m', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    historical_rl_train_parser.add_argument('--episodes', type=int, default=100, help='Number of training episodes')
    historical_rl_train_parser.add_argument('--batch-size', type=int, default=64, help='Training batch size')
    historical_rl_train_parser.add_argument('--initial-balance', type=float, default=10000.0, help='Initial balance for trading')
    historical_rl_train_parser.add_argument('--history-limit', type=int, default=80, help='Maximum historical steps to consider')
    historical_rl_train_parser.add_argument('--train-every', type=int, default=1, help='Train the model every N steps for better speed')
    
    # Add Prediction-Guided RL train command
    prediction_guided_train_parser = subparsers.add_parser('train-prediction-guided', help='Train a Prediction-Guided RL trading agent using ML price predictions')
    prediction_guided_train_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to train on')
    prediction_guided_train_parser.add_argument('--ml-model-path', type=str, required=True, help='Path to trained ML price prediction model')
    prediction_guided_train_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    prediction_guided_train_parser.add_argument('--days', type=int, default=30, help='Number of days of historical data to use')
    prediction_guided_train_parser.add_argument('--resolution', type=str, default='1H', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    prediction_guided_train_parser.add_argument('--sequence-length', type=int, default=36, help='Number of time steps in each sequence')
    prediction_guided_train_parser.add_argument('--prediction-horizon', type=int, default=1, help='Number of steps into future to predict')
    prediction_guided_train_parser.add_argument('--episodes', type=int, default=100, help='Number of training episodes')
    prediction_guided_train_parser.add_argument('--batch-size', type=int, default=256, help='Training batch size')
    prediction_guided_train_parser.add_argument('--initial-balance', type=float, default=10000.0, help='Initial balance for trading')
    prediction_guided_train_parser.add_argument('--network-type', type=str, default='deep', help='Neural network architecture: simple, deep, lstm, or dueling')
    
    # Test model command
    test_parser = subparsers.add_parser('test', help='Test the ML model')
    test_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to test on')
    test_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    test_parser.add_argument('--model-path', type=str, help='Path to the model to test')
    test_parser.add_argument('--days', type=int, default=10, help='Number of days of historical data to use')
    test_parser.add_argument('--resolution', type=str, default='1H', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    test_parser.add_argument('--sequence-length', type=int, default=36, help='Number of time steps in each input sequence')
    test_parser.add_argument('--prediction-horizon', type=int, default=1, help='Number of time steps in the future to predict')
    test_parser.add_argument('--plot', action='store_true', help='Plot test results')
    
    # Run trading bot command
    run_parser = subparsers.add_parser('run', help='Run the trading bot')
    run_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to trade')
    run_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    run_parser.add_argument('--model-path', type=str, help='Path to the ML model to use')
    run_parser.add_argument('--interval', type=int, help='Trading interval in minutes')
    
    # Create wallet command
    wallet_parser = subparsers.add_parser('create-wallet', help='Create a new Solana wallet')
    wallet_parser.add_argument('--save-path', type=str, default='wallet.json', help='Path to save wallet information')
    
    # Get token info command
    info_parser = subparsers.add_parser('token-info', help='Get information about a token')
    info_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to get info about')
    
    # Add cross-token training command
    cross_token_parser = subparsers.add_parser('train-cross-token', help='Train cross-token generalization agent')
    cross_token_parser.add_argument('--tokens', required=True, help='Comma-separated list of token symbols')
    cross_token_parser.add_argument('--days', type=int, default=30, help='Days of historical data')
    cross_token_parser.add_argument('--resolution', default='5m', help='Data resolution')
    cross_token_parser.add_argument('--episodes', type=int, default=200, help='Training episodes')
    cross_token_parser.add_argument('--scheduling', default='random', 
                                   choices=['random', 'sequential', 'curriculum'],
                                   help='Token scheduling strategy')
    cross_token_parser.add_argument('--no-predictions', action='store_true', 
                                   help='Disable prediction guidance')
    cross_token_parser.add_argument('--balance', type=float, default=10000.0,
                                   help='Initial balance')
    cross_token_parser.add_argument('--sequence-length', type=int, default=10,
                                   help='Sequence length for prediction input')
    cross_token_parser.add_argument('--batch-size', type=int, default=64,
                                   help='Training batch size')
    
    # Add a simple training command
    simple_train_parser = subparsers.add_parser('train-simple', help='Train model with simple directional optimization')
    simple_train_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to train on')
    simple_train_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    simple_train_parser.add_argument('--days', type=int, default=30, help='Number of days of historical data to use')
    simple_train_parser.add_argument('--resolution', type=str, default='5m', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    simple_train_parser.add_argument('--model-type', type=str, default='lstm', help='Type of ML model to use')
    simple_train_parser.add_argument('--sequence-length', type=int, default=24, help='Number of time steps in each input sequence')
    simple_train_parser.add_argument('--prediction-horizon', type=int, default=1, help='Number of time steps in the future to predict')
    simple_train_parser.add_argument('--epochs', type=int, default=100, help='Number of training epochs')
    simple_train_parser.add_argument('--batch-size', type=int, default=64, help='Training batch size')
    simple_train_parser.add_argument('--plot', action='store_true', help='Plot training results')
    
    # Add plot-prices command
    plot_prices_parser = subparsers.add_parser('plot-prices', help='Generate a price comparison plot')
    plot_prices_parser.add_argument('--token-address', type=str, required=True, help='Address of the token')
    plot_prices_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    plot_prices_parser.add_argument('--model-path', type=str, help='Path to the model to use')
    plot_prices_parser.add_argument('--days', type=int, default=30, help='Number of days of historical data to use')
    plot_prices_parser.add_argument('--resolution', type=str, default='1h', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    plot_prices_parser.add_argument('--sequence-length', type=int, default=24, help='Number of time steps in each input sequence')
    plot_prices_parser.add_argument('--prediction-horizon', type=int, default=1, help='Number of time steps in the future to predict')
    plot_prices_parser.add_argument('--output-file', type=str, help='Output filename for the plot')
    
    # Add test-fast-rl command
    test_rl_parser = subparsers.add_parser('test-fast-rl', help='Test a trained Fast RL agent on new token data')
    test_rl_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to test on')
    test_rl_parser.add_argument('--symbol', type=str, default='TOKEN', help='Symbol of the token to test on')
    test_rl_parser.add_argument('--agent-path', type=str, required=True, help='Path to the saved trained agent/policy network')
    test_rl_parser.add_argument('--days', type=int, default=30, help='Number of days of historical data to use for testing')
    test_rl_parser.add_argument('--resolution', type=str, default='5m', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    test_rl_parser.add_argument('--initial-balance', type=float, default=10000.0, help='Initial balance for the test simulation')
    test_rl_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging for debugging')
    test_rl_parser.set_defaults(func=test_fast_rl_agent_cmd)
    
    # Add continue-fast-rl command for continuing training of an existing model
    continue_rl_parser = subparsers.add_parser('continue-fast-rl', help='Continue training an existing Fast RL agent model')
    continue_rl_parser.add_argument('--model-path', type=str, required=True, help='Path to the saved model file (.h5)')
    continue_rl_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to train on')
    continue_rl_parser.add_argument('--symbol', type=str, default='TOKEN', help='Symbol of the token to train on')
    continue_rl_parser.add_argument('--days', type=int, default=30, help='Number of days of historical data to use')
    continue_rl_parser.add_argument('--resolution', type=str, default='5m', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    continue_rl_parser.add_argument('--episodes', type=int, default=50, help='Number of training episodes for continued training')
    continue_rl_parser.add_argument('--initial-balance', type=float, default=10000.0, help='Initial balance for the trading simulation')
    continue_rl_parser.add_argument('--include-social', action='store_true', default=True, help='Include social sentiment data in training')
    continue_rl_parser.add_argument('--day-offset', type=int, default=0, help='Days to offset data collection (to get newer data)')
    continue_rl_parser.add_argument('--epsilon', type=float, default=0.1, help='Starting epsilon value for exploration-exploitation balance (lower = more exploitation)')
    continue_rl_parser.add_argument('--reset-epsilon', action='store_true', help='Whether to reset epsilon to the specified value (default: keeps original epsilon)')
    continue_rl_parser.set_defaults(func=continue_fast_rl_model_cmd)
    
    return parser.parse_args()

def main():
    """Main entry point for the application"""
    args = parse_arguments()
    
    # Convert arguments to dictionary
    args_dict = vars(args)
    command = args.command
    
    # Run appropriate function based on command
    try:
        if command == 'train':
            asyncio.run(train_model(args_dict))
        elif command == 'train-rl':
            train_rl_model(args)
        elif command == 'train-fast-rl':
            train_fast_rl_model(args)
        elif command == 'train-historical-rl':
            train_historical_rl(args)
        elif command == 'train-prediction-guided':
            train_prediction_guided_model(args)
        elif command == 'train-cross-token':
            asyncio.run(train_cross_token(args_dict))
        elif command == 'train-simple':
            asyncio.run(train_simple_model(args_dict))
        elif command == 'test':
            asyncio.run(test_model(args_dict))
        elif command == 'run':
            asyncio.run(run_trading_bot(args_dict))
        elif command == 'create-wallet':
            asyncio.run(create_wallet(args_dict))
        elif command == 'token-info':
            asyncio.run(get_token_info(args_dict))
        elif command == 'plot-prices':
            asyncio.run(plot_price_comparison_cmd(args_dict))
        elif command == 'test-fast-rl':
            asyncio.run(test_fast_rl_agent_cmd(args_dict))
        elif command == 'continue-fast-rl':
            asyncio.run(continue_fast_rl_model_cmd(args_dict))
        else:
            logger.error(f"Unknown command: {command}")
            
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Program stopped by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
