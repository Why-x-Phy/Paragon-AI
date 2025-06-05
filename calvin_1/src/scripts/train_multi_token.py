#!/usr/bin/env python3
"""
Train Multi-Token ATCGAN-RL model for trading portfolio of crypto assets
"""

import os
import click
import pandas as pd
import logging
import sys
from datetime import datetime

from src.data.data_processor import DataProcessor
from src.model.multi_token_agent import train_multi_token_agent
from src.database.utils import get_all_active_tokens

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

@click.command()
@click.option('--token-addresses', help='Comma-separated list of token contract addresses (optional, if not specified will use all active tokens from database)')
@click.option('--symbols', help='Comma-separated list of token symbols (optional, must be provided if token-addresses is provided)')
@click.option('--days', default=90, help='Number of days of historical data to use')
@click.option('--resolution', default='5m', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
@click.option('--training-days', default=60, help='Number of days to use for training')
@click.option('--testing-days', default=30, help='Number of days to use for testing')
@click.option('--initial-balance', default=10000, help='Initial balance for trading simulation')
@click.option('--sequence-length', default=40, help='Sequence length for ATCGAN')
@click.option('--lookback-window', default=30, help='Lookback window for trading environment')
@click.option('--episodes', default=50, help='Number of training episodes')
@click.option('--batch-size', default=32, help='Batch size for training')
@click.option('--pretrain-epochs', default=50, help='Number of epochs for pretraining ATCGAN')
@click.option('--epsilon-decay', default=0.995, help='Decay rate for exploration')
@click.option('--epsilon-min', default=0.05, help='Minimum exploration rate')
@click.option('--model-dir', default='models', help='Directory to save models')
@click.option('--save-interval', default=10, help='Episodes interval for saving model')
@click.option('--min-tokens', default=2, help='Minimum number of tokens required to train')
@click.option('--max-tokens', default=5, help='Maximum number of tokens to use in training')
def train_multi_token_cmd(token_addresses, symbols, days, resolution, training_days, testing_days, 
                    initial_balance, sequence_length, lookback_window, episodes, 
                    batch_size, pretrain_epochs, epsilon_decay, epsilon_min, 
                    model_dir, save_interval, min_tokens, max_tokens):
    """
    Train Multi-Token ATCGAN-RL agent for portfolio management.
    
    This advanced model allows trading multiple tokens simultaneously using
    attention-based temporal convolutional networks and reinforcement learning.
    
    If no token addresses are specified, the system will automatically use
    tokens from the database that have sufficient historical data.
    """
    # Create model directory
    os.makedirs(model_dir, exist_ok=True)
    
    # Initialize data processor
    data_processor = DataProcessor()
    
    # Process provided tokens or get from database
    price_data_dict = {}
    
    if token_addresses and symbols:
        # Parse token addresses and symbols
        token_addresses = [addr.strip() for addr in token_addresses.split(',')]
        symbols = [symbol.strip() for symbol in symbols.split(',')]
        
        if len(token_addresses) != len(symbols):
            logger.error("Number of token addresses and symbols must match")
            return
            
        # Process the specified tokens
        for address, symbol in zip(token_addresses, symbols):
            logger.info(f"Fetching data for {symbol} ({address})")
            
            df = data_processor.process_pipeline(
                address,
                symbol,
                resolution,
                days,
                save_data=True,
                include_sentiment=False
            )
            
            if df.empty:
                logger.error(f"No data available for {symbol}")
                continue
            
            # Drop any NaN values
            df = df.dropna()
            
            # Ensure we have a timestamp column
            if 'timestamp' not in df.columns:
                if isinstance(df.index, pd.DatetimeIndex):
                    df.reset_index(inplace=True)
                else:
                    logger.error(f"No timestamp column found for {symbol}")
                    continue
            
            logger.info(f"Successfully fetched {len(df)} data points for {symbol}")
            price_data_dict[symbol] = df
    else:
        # Get all active tokens from database
        logger.info("No specific tokens provided. Getting tokens from database...")
        
        # Get all active tokens from database
        tokens = get_all_active_tokens()
        
        if not tokens:
            logger.error("No tokens found in database")
            return
            
        logger.info(f"Found {len(tokens)} tokens in database")
        
        # Process data for each token
        for token in tokens:
            symbol = token['symbol']
            address = token['address']
            
            logger.info(f"Fetching data for {symbol} ({address})")
            
            df = data_processor.process_pipeline(
                address,
                symbol,
                resolution,
                days,
                save_data=True,
                include_sentiment=False
            )
            
            if df.empty:
                logger.warning(f"No data available for {symbol}")
                continue
            
            # Drop any NaN values
            df = df.dropna()
            
            # Ensure we have a timestamp column
            if 'timestamp' not in df.columns:
                if isinstance(df.index, pd.DatetimeIndex):
                    df.reset_index(inplace=True)
                else:
                    logger.warning(f"No timestamp column found for {symbol}")
                    continue
                    
            # Check if we have enough data
            if len(df) < training_days + testing_days:
                logger.warning(f"Insufficient data for {symbol}: {len(df)} data points. Skipping.")
                continue
                
            logger.info(f"Successfully fetched {len(df)} data points for {symbol}")
            price_data_dict[symbol] = df
            
            # Stop when we reach the maximum number of tokens
            if len(price_data_dict) >= max_tokens:
                logger.info(f"Reached maximum token limit ({max_tokens})")
                break
    
    # Check if we have enough tokens
    if len(price_data_dict) < min_tokens:
        logger.error(f"Not enough tokens with sufficient data. Minimum required: {min_tokens}, Found: {len(price_data_dict)}")
        return
    
    # Log the tokens we're using
    token_symbols = list(price_data_dict.keys())
    logger.info(f"Training with {len(token_symbols)} tokens: {', '.join(token_symbols)}")
    
    # Generate model name
    model_name = f"multi_token_atcgan_{'_'.join(token_symbols)}_seq{sequence_length}_win{lookback_window}_e{episodes}"
    
    # Train the agent
    agent, history = train_multi_token_agent(
        price_data_dict=price_data_dict,
        token_symbols=token_symbols,
        initial_balance=initial_balance,
        sequence_length=sequence_length,
        lookback_window=lookback_window,
        training_days=training_days,
        testing_days=testing_days,
        model_dir=model_dir,
        episodes=episodes,
        batch_size=batch_size,
        pretrain_epochs=pretrain_epochs,
        epsilon_decay=epsilon_decay,
        epsilon_min=epsilon_min,
        model_name=model_name,
        save_interval=save_interval
    )
    
    # Log training results
    if 'test_roi' in history:
        logger.info(f"Training completed with test ROI: {history['test_roi']:.2f}%")
        logger.info(f"Final test portfolio value: ${history['test_portfolio']:.2f}")
        
        # Compare with buy & hold
        logger.info(f"Buy & Hold performance: {history['avg_buy_hold_roi']:.2f}%")
        outperformance = history['test_roi'] - history['avg_buy_hold_roi']
        logger.info(f"Agent outperformance: {outperformance:+.2f}%")
    
    return agent, history

if __name__ == "__main__":
    train_multi_token_cmd() 