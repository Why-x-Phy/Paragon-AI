#!/usr/bin/env python
"""
Script to train a reinforcement learning agent for trading
using historical price data and technical indicators.

Usage:
    python train_rl_model.py --token-address <TOKEN_ADDRESS> --symbol SOL --days 90 --episodes 200
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
from src.model.rl_agent import train_rl_agent, evaluate_agent
from src.utils.logger import log_manager

logger = log_manager.get_logger("train_rl_model")

def train_rl_model(args):
    """Train an RL agent for trading"""
    logger.info(f"Starting RL model training for {args.symbol} ({args.token_address})")
    
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
    logger.info(f"Preparing data for RL with sequence_length={args.sequence_length}")
    
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
    
    # Train the RL agent
    model_name = f"{args.symbol}_rl_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    agent, env = train_rl_agent(
        price_data=train_prices,
        feature_data=train_features,
        episodes=args.episodes,
        batch_size=args.batch_size,
        initial_balance=args.initial_balance,
        model_name=model_name
    )
    
    # Evaluate the agent on test data
    if len(test_prices) > 0:
        logger.info("Evaluating agent on test data")
        eval_results = evaluate_agent(
            agent=agent,
            price_data=test_prices,
            feature_data=test_features,
            initial_balance=args.initial_balance
        )
        
        logger.info(f"Evaluation results:")
        logger.info(f"Final portfolio value: ${eval_results['final_value']:.2f}")
        logger.info(f"Return on investment: {eval_results['roi']:.2%}")
        logger.info(f"Buy & Hold return: {eval_results['buy_hold_return']:.2%}")
        logger.info(f"Win rate: {eval_results['win_rate']:.2%}")
        logger.info(f"Total trades: {eval_results['total_trades']}")
    
    logger.info(f"RL model training completed: {model_name}")
    return agent, eval_results

def main():
    """Parse arguments and run training"""
    parser = argparse.ArgumentParser(description="Train RL agent for trading")
    
    # Required arguments
    parser.add_argument('--token-address', type=str, required=True,
                        help='Address of the token to train on')
    
    # Optional arguments
    parser.add_argument('--symbol', type=str, default='SOL',
                        help='Symbol of the token')
    parser.add_argument('--days', type=int, default=90,
                        help='Number of days of historical data to use')
    parser.add_argument('--resolution', type=str, default='5m',
                        help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    parser.add_argument('--sequence-length', type=int, default=26,
                        help='Number of time steps in each input sequence')
    parser.add_argument('--episodes', type=int, default=200,
                        help='Number of training episodes')
    parser.add_argument('--batch-size', type=int, default=64,
                        help='Training batch size')
    parser.add_argument('--initial-balance', type=float, default=10000.0,
                        help='Initial balance for trading')
    
    args = parser.parse_args()
    
    # Train the model
    start_time = time.time()
    agent, results = train_rl_model(args)
    elapsed_time = time.time() - start_time
    
    logger.info(f"Training completed in {elapsed_time:.2f} seconds")

if __name__ == "__main__":
    main() 