#!/usr/bin/env python
"""
Script to train a prediction-guided reinforcement learning agent for trading
using both ML price predictions and RL-based decision making.

Usage:
    python main.py train-prediction-guided --token-address 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump --symbol Fartcoin --days 90 --ml-model-path models/Fartcoin_lstm_20250528.h5
"""

import os
import sys
import argparse
import time
import numpy as np
import pandas as pd
from datetime import datetime

# Add project root to import path
current_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(scripts_dir)
sys.path.append(project_root)

from src.data.data_processor import DataProcessor
from src.model.ml_model import MLModel
from src.model.prediction_guided_agent import train_prediction_guided_agent, evaluate_prediction_guided_agent
from src.utils.logger import log_manager

logger = log_manager.get_logger("train_prediction_guided")

def train_prediction_guided_model(args):
    """Train a prediction-guided RL agent for trading"""
    logger.info(f"Starting prediction-guided model training for {args.symbol} ({args.token_address})")
    logger.info(f"Using ML model from: {args.ml_model_path}")
    
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
        include_sentiment=False
    )
    
    if df.empty:
        logger.error("No data available for training")
        return
    
    # Prepare data for RL
    logger.info(f"Preparing data with sequence_length={args.sequence_length}")
    
    # Extract price data (for environment)
    price_data = df['close'].values
    
    # Extract features (for state representation)
    # Drop columns not useful for features
    drop_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    feature_cols = [col for col in df.columns if col not in drop_cols]
    features = df[feature_cols].values
    
    # Split into train and test sets
    split_idx = int(len(price_data) * 0.8)
    
    train_prices = price_data[:split_idx]
    test_prices = price_data[split_idx:]
    
    train_features = features[:split_idx]
    test_features = features[split_idx:]
    
    logger.info(f"Data prepared: {len(train_prices)} training samples, {len(test_prices)} testing samples")
    
    # Load ML price prediction model
    ml_model = MLModel()
    ml_model.load(args.ml_model_path)
    logger.info(f"Loaded ML model from {args.ml_model_path}")
    
    # Get feature and price scalers from data processor
    feature_scaler = data_processor.feature_scaler
    price_scaler = data_processor.price_scaler
    
    # Check model's expected sequence length
    sequence_length = args.sequence_length
    if ml_model.model and hasattr(ml_model.model, 'input_shape'):
        expected_shape = ml_model.model.input_shape
        if len(expected_shape) > 1 and expected_shape[1] is not None:
            model_seq_len = expected_shape[1]
            if model_seq_len != sequence_length:
                logger.warning(f"Command line sequence_length ({sequence_length}) doesn't match model's expected sequence length ({model_seq_len}). Using model's expected length.")
                sequence_length = model_seq_len
    
    logger.info(f"Using sequence_length={sequence_length} for prediction input")
    
    # Create model name
    model_name = f"{args.symbol}_prediction_guided_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Train the prediction-guided agent
    logger.info("Training prediction-guided agent...")
    agent, env = train_prediction_guided_agent(
        price_data=train_prices,
        feature_data=train_features,
        price_predictor=ml_model,
        feature_scaler=feature_scaler,
        price_scaler=price_scaler,
        sequence_length=sequence_length,
        prediction_horizon=args.prediction_horizon,
        episodes=args.episodes,
        batch_size=args.batch_size,
        initial_balance=args.initial_balance,
        model_name=model_name,
        network_type=args.network_type,
        resolution=args.resolution
    )
    
    # Evaluate the agent on test data
    if len(test_prices) > 0:
        logger.info("Evaluating agent on test data")
        results, _ = evaluate_prediction_guided_agent(
            agent=agent,
            price_data=test_prices,
            feature_data=test_features,
            price_predictor=ml_model,
            feature_scaler=feature_scaler,
            price_scaler=price_scaler,
            initial_balance=args.initial_balance,
            sequence_length=sequence_length,
            prediction_horizon=args.prediction_horizon,
            resolution=args.resolution
        )
        
        logger.info(f"Test results summary:")
        logger.info(f"Final portfolio value: ${results['final_value']:.2f}")
        logger.info(f"Return on investment: {results['roi']:.2f}%")
        logger.info(f"Buy & Hold return: {results['buy_hold_return']:.2f}%")
        logger.info(f"Outperformance: {results['outperformance']:.2f}%")
        logger.info(f"Sharpe ratio: {results['sharpe_ratio']:.4f}")
        logger.info(f"Win rate: {results['win_rate']:.2%}")
        logger.info(f"Prediction contribution: {results['prediction_correlation']:.4f}")
    
    logger.info(f"Prediction-guided model training completed: {model_name}")
    return agent, results

def main():
    """Parse arguments and run training"""
    parser = argparse.ArgumentParser(description="Train prediction-guided agent for trading")
    
    # Required arguments
    parser.add_argument('--token-address', type=str, required=True,
                        help='Address of the token to train on')
    parser.add_argument('--ml-model-path', type=str, required=True,
                        help='Path to the trained ML price prediction model')
    
    # Optional arguments
    parser.add_argument('--symbol', type=str, default='SOL',
                        help='Symbol of the token')
    parser.add_argument('--days', type=int, default=30,
                        help='Number of days of historical data to use')
    parser.add_argument('--resolution', type=str, default='1H',
                        help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    parser.add_argument('--sequence-length', type=int, default=36,
                        help='Number of time steps in each input sequence')
    parser.add_argument('--prediction-horizon', type=int, default=1,
                        help='Number of time steps to predict into the future')
    parser.add_argument('--episodes', type=int, default=100,
                        help='Number of training episodes')
    parser.add_argument('--batch-size', type=int, default=256,
                        help='Training batch size')
    parser.add_argument('--initial-balance', type=float, default=10000.0,
                        help='Initial balance for trading')
    parser.add_argument('--network-type', type=str, default='deep',
                        help='Neural network architecture: simple, deep, lstm, or dueling')
    
    args = parser.parse_args()
    
    # Train the model
    start_time = time.time()
    agent, results = train_prediction_guided_model(args)
    elapsed_time = time.time() - start_time
    
    logger.info(f"Training and evaluation completed in {elapsed_time:.2f} seconds")

if __name__ == "__main__":
    main() 