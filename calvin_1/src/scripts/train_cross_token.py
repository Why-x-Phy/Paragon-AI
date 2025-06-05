#!/usr/bin/env python
"""
Cross-Token Agent Training Script

This script trains a reinforcement learning agent that can generalize
across multiple tokens for trading.
"""

import os
import time
import argparse
import numpy as np
import pandas as pd
import tensorflow as tf
from datetime import datetime

from src.utils.logger import log_manager
from src.data.data_processor import DataProcessor
from src.model.ml_model import PricePredictor
from src.model.cross_token_agent import (
    MultiTokenEnvironment, 
    CrossTokenActorCritic,
    train_cross_token_agent
)

# Set up logger
logger = log_manager.get_logger("train_cross_token")

def train_cross_token_model(
    token_list,
    days=30,
    resolution="5m",
    episodes=200,
    batch_size=64,
    ml_model_base_path="models",
    token_scheduling="random",
    use_predictions=True,
    initial_balance=10000,
    sequence_length=10
):
    """
    Train a cross-token generalization agent on multiple tokens.
    
    Args:
        token_list: List of token symbols to train on
        days: Number of days of historical data
        resolution: Time resolution of the data
        episodes: Number of episodes to train for
        batch_size: Training batch size
        ml_model_base_path: Base path to ML price prediction models
        token_scheduling: How to schedule tokens during training
        use_predictions: Whether to use prediction-guided environments
        initial_balance: Starting balance for trading
        sequence_length: Sequence length for prediction models
    """
    start_time = time.time()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    logger.info(f"Starting cross-token model training with {len(token_list)} tokens")
    logger.info(f"Token list: {', '.join(token_list)}")
    logger.info(f"Training for {episodes} episodes with {days} days of {resolution} data")
    
    # Configure GPU if available
    physical_devices = tf.config.list_physical_devices('GPU')
    if physical_devices:
        for device in physical_devices:
            try:
                tf.config.experimental.set_memory_growth(device, True)
                logger.info(f"Configured GPU {device} for memory growth")
            except Exception as e:
                logger.warning(f"Could not configure GPU: {e}")
    
    # Get token addresses from database
    token_addresses = {}
    try:
        from src.database.token_db import get_token_address
        
        for token_symbol in token_list:
            token_address = get_token_address(token_symbol)
            if token_address:
                token_addresses[token_symbol] = token_address
                logger.info(f"Found address for {token_symbol}: {token_address}")
            else:
                logger.warning(f"No address found for {token_symbol}, metadata features will be limited")
                token_addresses[token_symbol] = None
    except Exception as e:
        logger.warning(f"Could not fetch token addresses: {e}")
        # Initialize with empty addresses if database lookup fails
        token_addresses = {token: None for token in token_list}
    
    # Set up environment configs for all tokens
    env_configs = []
    
    for token_symbol in token_list:
        logger.info(f"Preparing data for {token_symbol}")
        
        # Process data for this token
        processor = DataProcessor(token_symbol=token_symbol)
        
        # Try to load cached data first
        data_path = f"data/{token_symbol}_{resolution}_{days}days"
        if os.path.exists(data_path):
            logger.info(f"Loading cached data from {data_path}")
            df, feature_scaler, price_scaler = processor.load_data(data_path)
        else:
            # Fetch and process data if no cache exists
            logger.info(f"Fetching and processing data for {token_symbol}")
            df, feature_scaler, price_scaler = processor.process_pipeline(
                days=days,
                resolution=resolution,
                save_path=data_path
            )
        
        # Create features and price arrays
        # Prepare sequences for the prediction model
        X, y, price_data = processor.prepare_sequences(
            df, 
            sequence_length=sequence_length, 
            prediction_horizon=1,
            feature_cols=None,  # Use all features
            target_col='close'
        )
        
        # Extract feature data
        feature_data = np.array(df.iloc[sequence_length:].drop(['close'], axis=1))
        
        # Get price data as numpy array
        price_data = np.array(df['close'])
        
        # Load ML model for predictions if requested
        price_predictor = None
        if use_predictions:
            ml_model_path = os.path.join(ml_model_base_path, f"{token_symbol}_lstm_latest.h5")
            
            # Check for token-specific model
            if not os.path.exists(ml_model_path):
                # Try to find any model for this token
                alternative_models = [f for f in os.listdir(ml_model_base_path) 
                                     if f.startswith(f"{token_symbol}_") and f.endswith(".h5")]
                if alternative_models:
                    ml_model_path = os.path.join(ml_model_base_path, alternative_models[0])
                    logger.info(f"Using alternative model: {ml_model_path}")
                else:
                    logger.warning(f"No ML model found for {token_symbol}, will not use predictions")
            
            if os.path.exists(ml_model_path):
                # Load price prediction model
                price_predictor = PricePredictor()
                try:
                    price_predictor.load(ml_model_path)
                    logger.info(f"Loaded ML model from {ml_model_path}")
                except Exception as e:
                    logger.error(f"Failed to load ML model: {e}")
                    price_predictor = None
        
        # Create environment config for this token
        config = {
            'token_symbol': token_symbol,
            'token_address': token_addresses.get(token_symbol),
            'price_data': price_data,
            'feature_data': feature_data,
            'feature_scaler': feature_scaler,
            'price_scaler': price_scaler,
            'initial_balance': initial_balance,
            'resolution': resolution,
            'risk_free_rate': 0.0,
            'sharpe_lookback': 30,
            'sharpe_weight': 2.0,
            'position_sizing': 'fixed',
            'max_position_pct': 0.2,
            'reward_type': 'combined',
            'slippage_pct': 0.0015,
            'sequence_length': sequence_length,
            'prediction_horizon': 1
        }
        
        # Add predictor if available
        if price_predictor is not None:
            config['price_predictor'] = price_predictor
            
            # Add prediction save path
            pred_dir = os.path.join("models", "predictions")
            os.makedirs(pred_dir, exist_ok=True)
            
            config['save_predictions_to'] = os.path.join(
                pred_dir,
                f"{token_symbol}_{days}d_{resolution}_{timestamp}.csv"
            )
        
        env_configs.append(config)
    
    # Create multi-token environment
    multi_env = MultiTokenEnvironment(
        env_configs=env_configs,
        use_predictions=use_predictions
    )
    
    # Create model save path
    model_name = f"cross_token_{len(token_list)}tokens_{days}d_{resolution}_{timestamp}"
    save_path = os.path.join("models", model_name)
    
    # Train cross-token agent
    agent, stats = train_cross_token_agent(
        multi_env=multi_env,
        episodes=episodes,
        batch_size=batch_size,
        token_scheduling=token_scheduling,
        save_path=save_path,
        actor_lr=0.0001,
        critic_lr=0.001,
        gamma=0.99,
        tau=0.001,
        memory_size=50000,
        evaluation_interval=10,
        temperature_start=5.0,
        temperature_end=0.1,
        temperature_decay=0.995
    )
    
    # Log final stats
    total_time = time.time() - start_time
    logger.info(f"Training completed in {total_time:.1f} seconds")
    logger.info(f"Model saved to {save_path}")
    logger.info(f"Tokens trained: {len(stats['token_episodes'])}")
    logger.info(f"Episodes per token: {stats['token_episodes']}")
    
    return agent, stats, multi_env

def main():
    """Parse arguments and train cross-token agent"""
    parser = argparse.ArgumentParser(description="Train a cross-token trading agent")
    parser.add_argument("--tokens", required=True, help="Comma-separated list of token symbols")
    parser.add_argument("--days", type=int, default=30, help="Days of historical data")
    parser.add_argument("--resolution", default="5m", help="Data resolution")
    parser.add_argument("--episodes", type=int, default=200, help="Training episodes")
    parser.add_argument("--scheduling", default="random", 
                        choices=["random", "sequential", "curriculum"],
                        help="Token scheduling strategy")
    parser.add_argument("--no-predictions", action="store_true", 
                        help="Disable prediction guidance")
    parser.add_argument("--balance", type=float, default=10000.0,
                        help="Initial balance")
    parser.add_argument("--sequence-length", type=int, default=10,
                        help="Sequence length for prediction input")
    
    args = parser.parse_args()
    
    # Parse token list
    token_list = [t.strip() for t in args.tokens.split(",")]
    
    # Train model
    train_cross_token_model(
        token_list=token_list,
        days=args.days,
        resolution=args.resolution,
        episodes=args.episodes,
        token_scheduling=args.scheduling,
        use_predictions=not args.no_predictions,
        initial_balance=args.balance,
        sequence_length=args.sequence_length
    )

if __name__ == "__main__":
    main() 