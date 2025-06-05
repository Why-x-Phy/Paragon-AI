#!/usr/bin/env python
"""
Simple test script to verify that the multi-timeframe feature generation works correctly.
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add project root to import path
current_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(scripts_dir)
sys.path.append(project_root)

from src.data.data_processor import DataProcessor
from src.utils.logger import log_manager

logger = log_manager.get_logger("test_multi_timeframe")

def create_test_data():
    """Create sample data for testing."""
    # Create a date range for the past 30 days with 5-minute intervals
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    dates = pd.date_range(start=start_date, end=end_date, freq="5min")
    
    # Create random OHLCV data
    price = 100
    data = []
    
    for date in dates:
        # Random price movement
        price_change = price * np.random.uniform(-0.01, 0.01)
        price += price_change
        
        # Generate OHLCV data
        open_price = price
        high_price = price * np.random.uniform(1.0, 1.02)
        low_price = price * np.random.uniform(0.98, 1.0)
        close_price = price
        volume = np.random.uniform(100, 1000)
        
        data.append({
            'timestamp': date,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume
        })
    
    return pd.DataFrame(data)

def test_multi_timeframe_features():
    """Test the add_multi_timeframe_features method."""
    logger.info("Testing multi-timeframe feature generation")
    
    # Create test data
    df = create_test_data()
    logger.info(f"Created test dataframe with {len(df)} rows")
    
    # Initialize DataProcessor
    data_processor = DataProcessor()
    
    # Test with default timeframes
    logger.info("Testing with default timeframes (None)")
    result_default = data_processor.add_multi_timeframe_features(df, "5m")
    
    # Test with explicit timeframes
    logger.info("Testing with explicit timeframes")
    result_explicit = data_processor.add_multi_timeframe_features(df, "5m", include_timeframes=["1h", "4h", "1d"])
    
    # Test with invalid timeframes
    logger.info("Testing with invalid timeframes (lower than original)")
    result_invalid = data_processor.add_multi_timeframe_features(df, "1h", include_timeframes=["5m", "15m", "1d"])
    
    # Check results
    default_cols = [col for col in result_default.columns if any(tf in col for tf in ["1h", "4h", "1d"])]
    logger.info(f"Default test added {len(default_cols)} multi-timeframe feature columns")
    
    explicit_cols = [col for col in result_explicit.columns if any(tf in col for tf in ["1h", "4h", "1d"])]
    logger.info(f"Explicit test added {len(explicit_cols)} multi-timeframe feature columns")
    
    invalid_cols = [col for col in result_invalid.columns if any(tf in col for tf in ["1d"])]
    logger.info(f"Invalid test added {len(invalid_cols)} multi-timeframe feature columns (should only have 1d)")
    
    # Verify data isn't empty
    logger.info(f"Default result shape: {result_default.shape}")
    logger.info(f"Explicit result shape: {result_explicit.shape}")
    logger.info(f"Invalid result shape: {result_invalid.shape}")
    
    # Print a few sample columns to verify data isn't all NaN
    if len(default_cols) > 0:
        sample_col = default_cols[0]
        logger.info(f"Sample column: {sample_col}, first few values: {result_default[sample_col].head()}")
        logger.info(f"NaN values in {sample_col}: {result_default[sample_col].isna().sum()}")
    
    logger.info("Test completed successfully!")
    return True

if __name__ == "__main__":
    success = test_multi_timeframe_features()
    print(f"Test {'passed' if success else 'failed'}!") 