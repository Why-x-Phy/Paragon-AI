"""
Test script that uses the EXACT same logic as test_model function for inference.

This proves we can get valid predictions by following the same pattern.
"""

import asyncio
import numpy as np
from datetime import datetime

from src.model.ml_model import MLModel
from src.data.data_processor import DataProcessor
from src.model.profit_functions import simple_backtest_strategy
from src.utils.logger import log

logger = log

async def test_simple_inference():
    """Test inference using the EXACT same logic as test_model function"""
    
    # Use one of the newer models from 20250615
    token_address = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"  # JUP
    symbol = "JUP"
    
    # Model path (use the newer model)
    model_path = "models/JUP_lstm_v1.0.0_20250615.h5"
    
    logger.info("=== TESTING SIMPLE INFERENCE (EXACT SAME LOGIC AS test_model) ===")
    logger.info(f"Token: {symbol} ({token_address})")
    logger.info(f"Model: {model_path}")
    
    # 1. EXACT SAME: Load the model
    logger.info("\n1. Loading model...")
    ml_model = MLModel()
    ml_model.load(model_path)
    logger.info("✅ Model loaded successfully")
    
    # 2. EXACT SAME: Get data using DataProcessor
    logger.info("\n2. Processing data...")
    data_processor = DataProcessor()
    df = data_processor.process_pipeline(
        token_address=token_address,
        symbol=symbol,
        resolution='1H',  # Same as hourly scheduler
        days=15,  # Enough for features
        save_data=False
    )
    
    if df.empty:
        logger.error("❌ No data available")
        return
    
    logger.info(f"✅ Data processed: {len(df)} rows")
    
    # 3. EXACT SAME: Prepare ML data with test_mode=True
    logger.info("\n3. Preparing ML data...")
    sequence_length = 36  # Default from test_model
    prediction_steps = 1  # Default from test_model
    
    df_for_ml = df.copy()
    _, X_test, _, y_test = data_processor.prepare_ml_data(
        df_for_ml,
        target_col='close',
        sequence_length=sequence_length,
        prediction_horizon=prediction_steps,
        test_size=0.2,  # Not used in test_mode
        include_feature_names=False,
        test_mode=True  # CRITICAL: This handles all scaling automatically
    )
    
    logger.info(f"✅ ML data prepared: X_test shape {X_test.shape}, y_test shape {y_test.shape}")
    
    # 4. EXACT SAME: Make predictions
    logger.info("\n4. Making predictions...")
    y_pred = ml_model.predict(X_test)
    logger.info(f"Raw predictions shape: {y_pred.shape}")
    logger.info(f"Raw predictions sample: {y_pred[:5].flatten()}")
    
    # Check for NaN predictions
    nan_count = np.isnan(y_pred).sum()
    if nan_count > 0:
        logger.error(f"❌ Found {nan_count} NaN predictions!")
        return
    else:
        logger.info("✅ No NaN predictions!")
    
    # 5. EXACT SAME: Inverse transform predictions
    logger.info("\n5. Inverse transforming predictions...")
    y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
    
    # EXACT SAME: Calculate y_true_orig
    original_indices = df_for_ml.index[-(len(y_test)+prediction_steps-1):-(prediction_steps-1)] if prediction_steps > 1 else df_for_ml.index[-len(y_test):]
    base_prices_for_y_test = df_for_ml.loc[original_indices, 'close'].values
    target_pct_changes = data_processor.price_scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()
    y_true_orig = base_prices_for_y_test * (1 + target_pct_changes)
    
    logger.info(f"✅ Inverse transform complete:")
    logger.info(f"   Actual prices: ${y_true_orig[0]:.4f} to ${y_true_orig[-1]:.4f}")
    logger.info(f"   Predicted prices: ${y_pred_orig[0]:.4f} to ${y_pred_orig[-1]:.4f}")
    
    # 6. EXACT SAME: Run simple backtest strategy
    logger.info("\n6. Running simple backtest strategy...")
    backtest_results = simple_backtest_strategy(
        prices=y_true_orig,
        predictions=y_pred_orig,
        ohlcv_df=df_for_ml,
        include_detailed_trades=True,
        verbosity=1,
        resolution='1H',
        buy_threshold=0.02,  # Buy when predicted increase >= 2%
        sell_threshold=0.03  # Sell when predicted decrease >= 3%
    )
    
    # 7. Log results
    logger.info("\n7. RESULTS:")
    logger.info(f"   Total Return: {backtest_results['Total Return']:.2f}%")
    logger.info(f"   Buy & Hold Return: {backtest_results['Buy & Hold Return']:.2f}%")
    logger.info(f"   Win Rate: {backtest_results['Win Rate']:.2f}%")
    logger.info(f"   Max Drawdown: {backtest_results['Max Drawdown']:.2f}%")
    logger.info(f"   Sharpe Ratio: {backtest_results['Sharpe Ratio']:.2f}")
    logger.info(f"   Total Trades: {backtest_results['Total Trades']}")
    
    # 8. NOW - Show how to do SINGLE PREDICTION for inference
    logger.info("\n8. SINGLE PREDICTION INFERENCE (HOW TO USE IN SCHEDULER):")
    
    # Get the most recent data for single prediction
    # Take the last sequence_length rows for prediction
    recent_data = df_for_ml.iloc[-sequence_length:].copy()
    logger.info(f"Recent data for inference: {len(recent_data)} rows")
    
    # Process this recent data exactly the same way
    _, X_recent, _, _ = data_processor.prepare_ml_data(
        recent_data,
        target_col='close',
        sequence_length=sequence_length,
        prediction_horizon=prediction_steps,
        test_size=0.0,  # Use all data
        include_feature_names=False,
        test_mode=True  # Still use test_mode for proper scaling
    )
    
    if len(X_recent) > 0:
        # Make prediction for the most recent data point
        single_pred = ml_model.predict(X_recent[-1:])  # Just the last sequence
        
        # Get the current price (last price in our data)
        current_price = df_for_ml['close'].iloc[-1]
        
        # Inverse transform the prediction
        # For single prediction, we need to provide the base price
        single_pred_orig = data_processor.inverse_transform_predictions(single_pred, np.array([current_price]))
        
        predicted_price = single_pred_orig[0]
        prediction_change_pct = (predicted_price / current_price - 1) * 100
        
        logger.info(f"   Current price: ${current_price:.4f}")
        logger.info(f"   Predicted price: ${predicted_price:.4f}")
        logger.info(f"   Predicted change: {prediction_change_pct:.2f}%")
        
        # Generate trading signal using the same logic as simple_backtest_strategy
        if prediction_change_pct >= 2.0:  # buy_threshold
            signal = "BUY"
        elif prediction_change_pct <= -3.0:  # -sell_threshold
            signal = "SELL"
        else:
            signal = "HOLD"
        
        logger.info(f"   Trading Signal: {signal}")
        
        logger.info("\n✅ SUCCESS! This is exactly how inference should work in the scheduler!")
    else:
        logger.warning("❌ Not enough recent data for single prediction")

if __name__ == "__main__":
    asyncio.run(test_simple_inference()) 