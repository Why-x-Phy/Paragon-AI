#!/usr/bin/env python3
"""
Check Production Conversion

Verify how model predictions are being converted to price changes in production.
"""

import asyncio
import os
import sys
import numpy as np
from datetime import datetime
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

async def check_production_conversion():
    """Check how predictions are being converted"""
    try:
        print("🔍 Checking Production Prediction Conversion...")
        print("=" * 80)
        
        # Test with a sample model prediction
        from src.data.data_processor import DataProcessor
        from src.model.ml_model import MLModel
        
        # Initialize components
        data_processor = DataProcessor()
        ml_model = MLModel()
        
        # Find and load a model
        model_path = ml_model.get_latest_model_path()
        if model_path:
            print(f"📊 Found model: {model_path}")
            ml_model.load(model_path)
            
            # Get sample data to understand scaling
            print("\n" + "="*80)
            print("Testing Prediction Conversion Methods:")
            print("="*80 + "\n")
            
            # Simulate some raw model outputs (these would be scaled values)
            raw_predictions = np.array([0.001, 0.005, 0.01, 0.02, -0.001, -0.005, -0.01, -0.02])
            current_price = 100.0  # Example price
            
            print("Raw Model Outputs (scaled):")
            for i, raw_pred in enumerate(raw_predictions):
                print(f"  [{i}] Raw: {raw_pred:.6f}")
            
            print("\n1. Production Fallback Method (treating as direct percentage):")
            print("-" * 60)
            for i, raw_pred in enumerate(raw_predictions):
                # This is what happens in production when data_processor is not available
                predicted_price_fallback = current_price * (1 + raw_pred)
                change_pct = (predicted_price_fallback / current_price - 1) * 100
                print(f"  [{i}] Raw: {raw_pred:.6f} -> Price: ${predicted_price_fallback:.2f} -> Change: {change_pct:.3f}%")
            
            print("\n2. Correct Method (using inverse_transform_predictions):")
            print("-" * 60)
            print("  ⚠️  This requires the price_scaler from training, which may not be available in production!")
            
            # Check if we can access the scaler
            if hasattr(data_processor, 'price_scaler') and data_processor.price_scaler is not None:
                try:
                    # This would be the correct conversion
                    prices_at_sequence_end = np.full_like(raw_predictions, current_price)
                    predicted_prices_correct = data_processor.inverse_transform_predictions(
                        raw_predictions, prices_at_sequence_end
                    )
                    
                    for i, (raw_pred, pred_price) in enumerate(zip(raw_predictions, predicted_prices_correct)):
                        change_pct = (pred_price / current_price - 1) * 100
                        print(f"  [{i}] Raw: {raw_pred:.6f} -> Price: ${pred_price:.2f} -> Change: {change_pct:.3f}%")
                except Exception as e:
                    print(f"  ❌ Error: {e}")
                    print("  ⚠️  The scaler needs to be fit with training data!")
            else:
                print("  ❌ Price scaler not available - this is likely the issue in production!")
            
            print("\n" + "="*80)
            print("💡 Analysis:")
            print("  - The fallback method treats raw predictions as direct percentages")
            print("  - This results in very small predicted changes (0.1% - 2%)")
            print("  - The correct method would inverse transform using the training scaler")
            print("  - Production likely doesn't have access to the fitted scaler!")
            
        else:
            print("❌ No model found")
        
        # Check actual predictions in the database
        print("\n" + "="*80)
        print("Checking Recent Database Predictions:")
        print("="*80 + "\n")
        
        from src.database.production_db import get_db_manager
        db_manager = await get_db_manager()
        
        async with db_manager.pg_pool.acquire() as conn:
            # Get some recent predictions with raw data if available
            query = """
                SELECT 
                    tk.symbol,
                    mp.prediction_time,
                    mp.predicted_price_change * 100 as predicted_change_pct,
                    mp.confidence_score,
                    mp.input_features
                FROM model_predictions mp
                JOIN tokens tk ON mp.token_id = tk.token_id
                WHERE mp.prediction_time >= NOW() - INTERVAL '1 hour'
                ORDER BY mp.prediction_time DESC
                LIMIT 10
            """
            
            results = await conn.fetch(query)
            
            print("Recent Predictions (Last Hour):")
            print(f"{'Symbol':<10} {'Time':<20} {'Pred Change %':<15} {'Confidence':<10}")
            print("-" * 60)
            
            for row in results:
                time_str = row['prediction_time'].strftime('%H:%M:%S')
                print(f"{row['symbol']:<10} {time_str:<20} {row['predicted_change_pct']:<15.6f} {row['confidence_score']:<10.3f}")
            
            # Check if raw predictions are stored
            raw_query = """
                SELECT COUNT(*) as with_features
                FROM model_predictions
                WHERE input_features IS NOT NULL
                  AND prediction_time >= NOW() - INTERVAL '24 hours'
            """
            
            raw_result = await conn.fetchrow(raw_query)
            print(f"\nPredictions with stored raw features: {raw_result['with_features']}")
        
        await db_manager.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_production_conversion()) 