#!/usr/bin/env python3
"""
Check Production Predictions

Verify how predictions are being calculated in the production system.
"""

import os
import sys
from pathlib import Path

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Load environment variables
from dotenv import load_dotenv
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from src.strategy.strategy_engine import StrategyEngine
from src.database.production_db import get_db_manager
import asyncio

async def check_production_predictions():
    """Check how predictions are calculated in production"""
    print("🔍 Checking Production Prediction Calculations")
    print("=" * 60)
    
    # Initialize strategy engine
    db_manager = await get_db_manager()
    strategy_engine = StrategyEngine(db_manager)
    
    # Test token
    token_info = {
        'token_id': 6,
        'symbol': 'Fartcoin',
        'token_address': '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump'
    }
    
    print(f"\n📊 Testing with {token_info['symbol']}")
    
    # Get inference data
    from src.data.inference_data_processor import InferenceDataProcessor
    inference_processor = InferenceDataProcessor(db_manager)
    
    inference_data = await inference_processor.prepare_inference_data(
        token_address=token_info['token_address'],
        resolution='1H'
    )
    
    if not inference_data or not inference_data.get('ready_for_inference'):
        print("❌ Failed to get inference data")
        return
    
    # Get the features DataFrame
    features_df = inference_data['features_dataframe']
    current_price = float(features_df['close'].iloc[-1])
    
    print(f"\n💰 Current price: ${current_price:.4f}")
    
    # Make prediction
    prediction_result = await strategy_engine._make_model_prediction(
        token_info=token_info,
        inference_data=inference_data
    )
    
    if not prediction_result:
        print("❌ No prediction result")
        return
    
    print(f"\n🎯 Prediction Results:")
    print(f"   Raw model output: {prediction_result.get('raw_prediction', 'N/A')}")
    print(f"   Predicted price: ${prediction_result['predicted_price']:.4f}")
    print(f"   Predicted change: {prediction_result['predicted_change']:.2f}%")
    print(f"   Confidence: {prediction_result['confidence']:.2f}")
    
    # Check how the percentage is calculated
    print(f"\n🔍 Calculation Check:")
    
    # Method 1: How production calculates it
    prod_pct = prediction_result['predicted_change']
    print(f"   Production calculation: {prod_pct:.2f}%")
    
    # Method 2: Simple percentage from prices
    simple_pct = ((prediction_result['predicted_price'] - current_price) / current_price) * 100
    print(f"   Simple (pred/current - 1): {simple_pct:.2f}%")
    
    # Method 3: If we had the base price
    # The prediction was made from the previous hour's price
    if len(features_df) > 1:
        prev_price = float(features_df['close'].iloc[-2])
        print(f"   Previous hour price: ${prev_price:.4f}")
        
        # What percentage change from prev to predicted?
        from_prev_pct = ((prediction_result['predicted_price'] - prev_price) / prev_price) * 100
        print(f"   From previous hour: {from_prev_pct:.2f}%")
    
    print("\n" + "=" * 60)
    await db_manager.close()

if __name__ == "__main__":
    asyncio.run(check_production_predictions()) 