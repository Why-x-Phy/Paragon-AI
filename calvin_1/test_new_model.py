#!/usr/bin/env python3
"""
Test New Model Comprehensively

Test if a newly trained model actually responds to different inputs
and doesn't output constants.
"""

import os
import sys
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

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

from src.model.ml_model import MLModel
from src.data.data_processor import DataProcessor

def test_model(model_path, token_address, symbol):
    """Test if model produces varied outputs"""
    print(f"🔍 Testing Model: {model_path}")
    print("=" * 60)
    
    # Load model
    ml_model = MLModel()
    ml_model.load(model_path)
    
    # Get real market data
    print("📈 Fetching market data...")
    data_processor = DataProcessor()
    df = data_processor.process_pipeline(
        token_address, 
        symbol, 
        resolution="1H",
        days=30,
        save_data=False
    )
    
    if df is None or df.empty:
        print("❌ Failed to fetch market data")
        return
    
    # Prepare ML data with test mode = True (uses entire dataset)
    print("🔧 Preparing ML features...")
    X, y, train_idx, test_idx = data_processor.prepare_ml_data(
        df, 
        sequence_length=36, 
        prediction_horizon=1,
        test_size=0.2,
        test_mode=True
    )
    
    # Test on different parts of the data
    test_indices = [0, len(X)//4, len(X)//2, 3*len(X)//4, -10, -5, -1]
    
    print("\n📊 Raw Model Outputs:")
    print("-" * 40)
    raw_outputs = []
    
    for idx in test_indices:
        if idx < 0:
            idx = len(X) + idx
        if 0 <= idx < len(X):
            raw_pred = ml_model.predict(X[idx:idx+1])
            raw_outputs.append(raw_pred[0])
            print(f"  Sample {idx:4d}: {raw_pred[0]:.6f}")
    
    # Check if outputs vary
    unique_outputs = len(set([f"{x:.6f}" for x in raw_outputs]))
    output_range = max(raw_outputs) - min(raw_outputs)
    
    print(f"\n📈 Output Statistics:")
    print(f"  Unique values: {unique_outputs}/{len(raw_outputs)}")
    print(f"  Min: {min(raw_outputs):.6f}")
    print(f"  Max: {max(raw_outputs):.6f}")
    print(f"  Range: {output_range:.6f}")
    print(f"  Std Dev: {np.std(raw_outputs):.6f}")
    
    # Now test with inverse transform
    print("\n🔄 Checking Predictions with Inverse Transform:")
    print("-" * 40)
    
    # Get predictions for test set
    y_pred = ml_model.predict(X[test_idx])
    
    # Inverse transform
    y_pred_orig = data_processor.inverse_transform_predictions(
        y_pred, df, test_idx, prediction_horizon=1
    )
    
    # Calculate percentage changes
    base_prices = df['close'].iloc[test_idx].values
    predicted_changes = ((y_pred_orig - base_prices) / base_prices) * 100
    
    # Show some predictions
    print(f"  First 10 predicted changes:")
    for i in range(min(10, len(predicted_changes))):
        print(f"    {i+1}: {predicted_changes[i]:+.2f}%")
    
    # Statistics
    print(f"\n  Prediction Statistics:")
    print(f"    Min change: {predicted_changes.min():+.2f}%")
    print(f"    Max change: {predicted_changes.max():+.2f}%")
    print(f"    Mean change: {predicted_changes.mean():+.2f}%")
    print(f"    Std Dev: {predicted_changes.std():.2f}%")
    
    # Check for issues
    print("\n✅ Model Health Check:")
    if unique_outputs == 1:
        print("  ❌ FAILED: Model outputs constant values!")
    elif output_range < 0.001:
        print("  ⚠️  WARNING: Model outputs have very low variance")
    elif predicted_changes.std() < 0.1:
        print("  ⚠️  WARNING: Predicted changes have very low variance")
    else:
        print("  ✅ PASSED: Model produces varied outputs")
        
    # Check if predictions are reasonable
    if abs(predicted_changes.mean()) > 50:
        print("  ⚠️  WARNING: Predictions seem unreasonably large")
    if predicted_changes.std() > 20:
        print("  ⚠️  WARNING: Predictions have very high variance")
        
    return {
        'raw_outputs': raw_outputs,
        'predicted_changes': predicted_changes,
        'unique_outputs': unique_outputs,
        'output_range': output_range
    }

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test a new model')
    parser.add_argument('--model-path', type=str, required=True, 
                        help='Path to the model file')
    parser.add_argument('--token-address', type=str, 
                        default="9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
                        help='Token address')
    parser.add_argument('--symbol', type=str, default="Fartcoin",
                        help='Token symbol')
    
    args = parser.parse_args()
    
    test_model(args.model_path, args.token_address, args.symbol) 