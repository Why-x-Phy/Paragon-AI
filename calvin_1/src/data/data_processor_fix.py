"""
Data Processor Event Loop Fix

Fixes the asyncio event loop conflict in add_intermarket_correlation_features
"""

import asyncio
import concurrent.futures
import pandas as pd
import numpy as np
from typing import Optional, List
from datetime import datetime
from src.utils.logger import log_manager

logger = log_manager.get_logger("data_processor_fix")


def create_new_event_loop_in_thread(coro):
    """
    Run an async coroutine in a new thread with its own event loop.
    This avoids conflicts with existing event loops.
    """
    def run_in_new_loop():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(run_in_new_loop)
        return future.result()


async def fetch_btc_eth_data_async(start_time, end_time):
    """Async function to fetch BTC and ETH data"""
    from ..database.production_db import ProductionDBManager
    
    # Create a new database manager for this operation
    db_manager = ProductionDBManager()
    await db_manager.initialize()
    
    try:
        # Get token IDs for BTC and ETH
        btc_token_id = 21  # WBTC (Wrapped BTC on Solana)
        eth_token_id = 22  # WETH (Wrapped Ether on Solana)
        
        btc_data = await db_manager.get_ohlcv_data(
            token_id=btc_token_id,
            resolution='1H',
            start_time=start_time,
            end_time=end_time
        )
        
        eth_data = await db_manager.get_ohlcv_data(
            token_id=eth_token_id,
            resolution='1H',
            start_time=start_time,
            end_time=end_time
        )
        
        return btc_data, eth_data
    finally:
        await db_manager.close()


def add_intermarket_correlation_features_fixed(
    df: pd.DataFrame, 
    symbol: str = None, 
    correlation_windows: list = [24, 48, 168]
) -> pd.DataFrame:
    """
    Fixed version of add_intermarket_correlation_features that handles event loop conflicts.
    
    Add correlation features with major cryptocurrencies (BTC, ETH) to capture
    market-wide movements and relative strength.
    
    Args:
        df: DataFrame with price data
        symbol: Token symbol (to avoid self-correlation)
        correlation_windows: List of window sizes for correlation calculation
        
    Returns:
        DataFrame with intermarket correlation features added
    """
    logger.info("Adding intermarket correlation features")
    
    # Skip if this is BTC or ETH itself
    if symbol and symbol.upper() in ['BTC', 'BITCOIN', 'ETH', 'ETHEREUM']:
        logger.info(f"Skipping intermarket features for {symbol} (self-correlation)")
        return df
    
    result = df.copy()
    
    try:
        # Get time range from current data
        start_time = df['timestamp'].min()
        end_time = df['timestamp'].max()
        
        # Fetch BTC and ETH data using thread-safe approach
        logger.debug("Fetching BTC/ETH data for correlation features")
        btc_data, eth_data = create_new_event_loop_in_thread(
            fetch_btc_eth_data_async(start_time, end_time)
        )
        
        if not btc_data or not eth_data:
            logger.warning("Could not fetch BTC/ETH data for correlation features")
            # Add placeholder columns
            for window in correlation_windows:
                result[f'btc_correlation_{window}h'] = 0.5
                result[f'eth_correlation_{window}h'] = 0.5
                result[f'btc_relative_strength_{window}h'] = 0.0
                result[f'eth_relative_strength_{window}h'] = 0.0
            
            result['btc_eth_spread'] = 0.0
            result['market_regime_correlation'] = 0.5
            result['beta_to_btc'] = 1.0
            result['beta_to_eth'] = 1.0
            result['btc_eth_dominance'] = 0.0
            return result
        
        # Convert to DataFrames
        btc_df = pd.DataFrame([{
            'timestamp': r.time,
            'close': float(r.close),
            'volume': float(r.volume)
        } for r in btc_data])
        btc_df['timestamp'] = pd.to_datetime(btc_df['timestamp'])
        btc_df.set_index('timestamp', inplace=True)
        btc_df['returns'] = btc_df['close'].pct_change()
        
        eth_df = pd.DataFrame([{
            'timestamp': r.time,
            'close': float(r.close),
            'volume': float(r.volume)
        } for r in eth_data])
        eth_df['timestamp'] = pd.to_datetime(eth_df['timestamp'])
        eth_df.set_index('timestamp', inplace=True)
        eth_df['returns'] = eth_df['close'].pct_change()
        
        # Calculate returns for current asset
        result['returns'] = result['close'].pct_change()
        
        # Align data by timestamp
        result_indexed = result.set_index('timestamp')
        
        # Calculate correlation features for each window
        for window in correlation_windows:
            # Rolling correlation with BTC
            btc_corr = result_indexed['returns'].rolling(window).corr(btc_df['returns'])
            result[f'btc_correlation_{window}h'] = btc_corr.values
            
            # Rolling correlation with ETH
            eth_corr = result_indexed['returns'].rolling(window).corr(eth_df['returns'])
            result[f'eth_correlation_{window}h'] = eth_corr.values
            
            # Relative strength vs BTC (cumulative return difference)
            asset_cum_return = result_indexed['returns'].rolling(window).sum()
            btc_cum_return = btc_df['returns'].rolling(window).sum()
            btc_relative = (asset_cum_return - btc_cum_return).values
            result[f'btc_relative_strength_{window}h'] = btc_relative
            
            # Relative strength vs ETH
            eth_cum_return = eth_df['returns'].rolling(window).sum()
            eth_relative = (asset_cum_return - eth_cum_return).values
            result[f'eth_relative_strength_{window}h'] = eth_relative
        
        # BTC-ETH spread (market regime indicator)
        btc_eth_spread = (btc_df['returns'].rolling(24).mean() - 
                         eth_df['returns'].rolling(24).mean()).values
        result['btc_eth_spread'] = btc_eth_spread
        
        # Market regime based on BTC-ETH correlation
        btc_eth_corr = btc_df['returns'].rolling(48).corr(eth_df['returns'])
        result['market_regime_correlation'] = btc_eth_corr.values
        
        # Beta to BTC (market sensitivity)
        btc_variance = btc_df['returns'].rolling(168).var()
        covariance = result_indexed['returns'].rolling(168).cov(btc_df['returns'])
        beta_btc = (covariance / btc_variance).values
        result['beta_to_btc'] = beta_btc
        
        # Beta to ETH
        eth_variance = eth_df['returns'].rolling(168).var()
        covariance_eth = result_indexed['returns'].rolling(168).cov(eth_df['returns'])
        beta_eth = (covariance_eth / eth_variance).values
        result['beta_to_eth'] = beta_eth
        
        # Market dominance indicator
        dominance = (abs(result[f'btc_correlation_24h']) - abs(result[f'eth_correlation_24h']))
        result['btc_eth_dominance'] = dominance
        
        # Fill NaN values
        correlation_cols = [col for col in result.columns if 'correlation' in col or 
                          'relative_strength' in col or 'beta' in col or 
                          'spread' in col or 'dominance' in col]
        
        for col in correlation_cols:
            # Forward fill then use neutral values
            result[col] = result[col].fillna(method='ffill')
            if 'correlation' in col or 'regime' in col:
                result[col] = result[col].fillna(0.5)  # Neutral correlation
            else:
                result[col] = result[col].fillna(0.0)  # Neutral relative strength
        
        # Drop temporary returns column if it wasn't there originally
        if 'returns' not in df.columns:
            result.drop('returns', axis=1, inplace=True)
        
        logger.info(f"Added {len(correlation_cols)} intermarket correlation features")
        
    except Exception as e:
        logger.error(f"Error adding intermarket correlation features: {e}")
        # Add placeholder columns on error
        for window in correlation_windows:
            result[f'btc_correlation_{window}h'] = 0.5
            result[f'eth_correlation_{window}h'] = 0.5
            result[f'btc_relative_strength_{window}h'] = 0.0
            result[f'eth_relative_strength_{window}h'] = 0.0
        
        result['btc_eth_spread'] = 0.0
        result['market_regime_correlation'] = 0.5
        result['beta_to_btc'] = 1.0
        result['beta_to_eth'] = 1.0
        result['btc_eth_dominance'] = 0.0
    
    return result 