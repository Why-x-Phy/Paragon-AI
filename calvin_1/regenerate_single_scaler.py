#!/usr/bin/env python3
"""
Regenerate Scalers for a Single Model

Simple script to regenerate scalers by retraining just the data processing part.
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

from src.data.data_processor import DataProcessor
import argparse

def main():
    parser = argparse.ArgumentParser(description='Regenerate scalers for a model')
    parser.add_argument('--symbol', required=True, help='Token symbol (e.g., $WIF)')
    parser.add_argument('--token-address', required=True, help='Token address')
    parser.add_argument('--model-version', required=True, help='Model version (e.g., 20250614)')
    parser.add_argument('--days', type=int, default=90, help='Days of data to use for fitting scalers')
    
    args = parser.parse_args()
    
    print(f"🔧 Regenerating scalers for {args.symbol} model {args.model_version}")
    
    # Initialize data processor
    data_processor = DataProcessor()
    
    # Fetch and process data (same as training)
    print(f"📊 Fetching {args.days} days of data...")
    df = data_processor.process_pipeline(
        token_address=args.token_address,
        symbol=args.symbol,
        resolution='1H',
        days=args.days,
        save_data=False,
        include_sentiment=True
    )
    
    if df.empty:
        print(f"❌ No data found for {args.symbol}")
        return
    
    print(f"✅ Got {len(df)} rows of data")
    
    # Prepare ML data to fit the scalers (same as training)
    print(f"🔄 Fitting scalers on data...")
    X_train, X_test, y_train, y_test = data_processor.prepare_ml_data(
        df,
        target_col='close',
        sequence_length=36,  # Standard sequence length
        prediction_horizon=1,
        test_size=0.2,
        include_feature_names=False,
        test_mode=False  # Important: use training mode to fit scalers properly
    )
    
    if X_train is None or len(X_train) == 0:
        print(f"❌ Failed to prepare training data")
        return
    
    print(f"✅ Prepared {len(X_train)} training sequences")
    
    # Save the fitted scalers
    data_processor.save_scalers(args.symbol, args.model_version)
    print(f"✅ Saved scalers for {args.symbol} model {args.model_version}")
    
    # Verify the files were created
    scaler_dir = os.path.join(data_processor.data_dir, "scalers")
    price_scaler_path = os.path.join(scaler_dir, f"{args.symbol}_{args.model_version}_price_scaler.pkl")
    feature_scaler_path = os.path.join(scaler_dir, f"{args.symbol}_{args.model_version}_feature_scaler.pkl")
    
    if os.path.exists(price_scaler_path) and os.path.exists(feature_scaler_path):
        print(f"✅ Verified scaler files exist:")
        print(f"   - {price_scaler_path} ({os.path.getsize(price_scaler_path)} bytes)")
        print(f"   - {feature_scaler_path} ({os.path.getsize(feature_scaler_path)} bytes)")
    else:
        print(f"❌ Scaler files not found after saving")

if __name__ == "__main__":
    main() 