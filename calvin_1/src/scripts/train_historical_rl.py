#!/usr/bin/env python
"""
Script to train a historical reinforcement learning agent for trading
that has access to all previous history, not just a fixed window.

Usage:
    python train_historical_rl.py --token-address <TOKEN_ADDRESS> --symbol FART --days 30 --episodes 100
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
from src.model.historical_rl_agent import train_historical_rl_agent, evaluate_historical_agent
from src.utils.logger import log_manager

logger = log_manager.get_logger("train_historical_rl")

def train_historical_rl(args):
    """Train a historical RL agent for trading with full history access"""
    logger.info(f"Starting historical RL model training for {args.symbol} ({args.token_address})")
    
    start_time = time.time()
    
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
    
    # Drop any NaN values to ensure clean data
    df = df.dropna()
    
    # Prepare data for RL
    logger.info(f"Preparing data for historical RL with full history access")
    
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
    
    logger.info(f"Data prepared: {len(train_prices)} training samples, {len(test_features)} testing samples")
    
    # Train the historical RL agent
    model_name = f"{args.symbol}_historical_rl_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    agent, env = train_historical_rl_agent(
        price_data=train_prices,
        feature_data=train_features,
        episodes=args.episodes,
        batch_size=args.batch_size,
        initial_balance=args.initial_balance,
        model_name=model_name,
        history_limit=args.history_limit,
        train_every=args.train_every,
        memory_efficient=True
    )
    
    # Evaluate the agent on test data
    if len(test_prices) > 0:
        logger.info("Evaluating agent on test data")
        eval_results = evaluate_historical_agent(
            agent=agent,
            price_data=test_prices,
            feature_data=test_features,
            initial_balance=args.initial_balance,
            max_eval_time=600  # Increased to 10 minutes
        )
        
        logger.info(f"Evaluation results:")
        logger.info(f"Final portfolio value: ${eval_results['final_value']:.2f}")
        logger.info(f"Cash balance: ${eval_results['cash_balance']:.2f}")
        logger.info(f"Position value: ${eval_results['position_value']:.2f}")
        logger.info(f"Return on investment: {eval_results['roi']:.2%}")
        logger.info(f"Buy & Hold return: {eval_results['buy_hold_return']:.2%}")
        logger.info(f"Win rate: {eval_results['win_rate']:.2%}")
        logger.info(f"Total trades: {eval_results['total_trades']}")
    
    elapsed_time = time.time() - start_time
    logger.info(f"Historical RL model training completed in {elapsed_time:.2f} seconds: {model_name}")
    return agent, eval_results

def main():
    """Parse arguments and run training"""
    parser = argparse.ArgumentParser(description="Train historical RL agent for trading")
    
    # Required arguments
    parser.add_argument('--token-address', type=str, required=True,
                        help='Address of the token to train on')
    
    # Optional arguments
    parser.add_argument('--symbol', type=str, default='SOL',
                        help='Symbol of the token')
    parser.add_argument('--days', type=int, default=30,
                        help='Number of days of historical data to use')
    parser.add_argument('--resolution', type=str, default='5m',
                        help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    parser.add_argument('--episodes', type=int, default=100,
                        help='Number of training episodes')
    parser.add_argument('--batch-size', type=int, default=64,
                        help='Training batch size')
    parser.add_argument('--initial-balance', type=float, default=10000.0,
                        help='Initial balance for trading')
    parser.add_argument('--history-limit', type=int, default=30,
                        help='Maximum historical steps to consider')
    parser.add_argument('--train-every', type=int, default=1,
                        help='Train the model every N steps for better speed')
    
    args = parser.parse_args()
    
    # Train the model
    start_time = time.time()
    agent, results = train_historical_rl(args)
    elapsed_time = time.time() - start_time
    
    logger.info(f"Training completed in {elapsed_time:.2f} seconds")

if __name__ == "__main__":
    main() 