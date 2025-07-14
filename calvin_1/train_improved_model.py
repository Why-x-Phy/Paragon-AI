#!/usr/bin/env python3
"""
Train Improved Model

Quick script to train a model with all the improvements to prevent collapse.
"""

import os
import sys
import argparse
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

from src.model.ml_model_improved import ImprovedMLModel
from src.data.data_processor import DataProcessor
from datetime import datetime
import numpy as np
import re
import glob


def get_next_version(symbol: str, models_dir: str = "models") -> str:
    """
    Find the latest version for a symbol and increment it
    
    Returns:
        Next version string (e.g., "v1.0.1", "v1.1.0", "v2.0.0")
    """
    # Look for existing models
    pattern = f"{models_dir}/{symbol}_lstm_improved_v*.h5"
    existing_models = glob.glob(pattern)
    
    if not existing_models:
        return "v1.0.0"
    
    # Extract version numbers
    versions = []
    for model_path in existing_models:
        # Extract version from filename (e.g., "v1.0.0" from "BONK_lstm_improved_v1.0.0_20250710.h5")
        match = re.search(r'v(\d+)\.(\d+)\.(\d+)', model_path)
        if match:
            major, minor, patch = map(int, match.groups())
            versions.append((major, minor, patch))
    
    if not versions:
        return "v1.0.0"
    
    # Get the latest version
    latest = max(versions)
    major, minor, patch = latest
    
    # Increment patch version by default
    # You could add logic here to increment minor/major based on changes
    patch += 1
    
    return f"v{major}.{minor}.{patch}"


def train_improved_model(
    token_address: str,
    symbol: str,
    days: int = 30,
    resolution: str = "1H",
    epochs: int = 30,
    optimization_target: str = "anti_collapse"  # Use anti-collapse loss to fix constant predictions
):
    """Train an improved model with anti-collapse features"""
    
    print(f"\n🚀 Training Improved Model for {symbol}")
    print("=" * 60)
    print(f"📊 Configuration:")
    print(f"   - Optimization Target: {optimization_target}")
    print(f"   - Data: {days} days at {resolution} resolution")
    print(f"   - Max Epochs: {epochs} (with early stopping)")
    print(f"   - Reduced dropout: 0.2 (vs 0.4)")
    print(f"   - Output constraint: tanh with scaling")
    print(f"   - Better initialization: Fixed seeds")
    print("=" * 60)
    
    # Get data
    print("\n📈 Fetching market data...")
    data_processor = DataProcessor()
    df = data_processor.process_pipeline(
        token_address, 
        symbol, 
        resolution=resolution,
        days=days,
        save_data=False
    )
    
    if df is None or df.empty:
        print("❌ Failed to fetch market data")
        return None
    
    print(f"✅ Loaded {len(df)} data points")
    
    # Prepare ML data
    print("\n🔧 Preparing ML features...")
    X_train, X_test, y_train, y_test = data_processor.prepare_ml_data(
        df, 
        sequence_length=24,  # Fix #19: Try 18 hours (between 12 and 24)
        prediction_horizon=1,
        test_size=0.2,
        test_mode=False,  # Use proper train/test split
        include_feature_names=False  # Don't return feature names, just the 4 arrays
    )
    
    print(f"✅ Training samples: {len(X_train)}")
    print(f"✅ Validation samples: {len(X_test)}")
    
    # Check target distribution
    print(f"\n📊 Target Statistics (scaled):")
    print(f"   - Train mean: {y_train.mean():.4f}")
    print(f"   - Train std: {y_train.std():.4f}")
    print(f"   - Train min: {y_train.min():.4f}")
    print(f"   - Train max: {y_train.max():.4f}")
    
    # Create and build model
    print(f"\n🏗️ Building Improved LSTM Model...")
    ml_model = ImprovedMLModel(
        model_type="lstm",
        optimization_target=optimization_target
    )
    
    # Build model with improved settings
    ml_model.build_model(
        input_shape=(X_train.shape[1], X_train.shape[2]),
        use_bidirectional=False  # Changed to unidirectional LSTM
    )
    
    # Generate model name
    timestamp = datetime.now().strftime('%Y%m%d')
    next_version = get_next_version(symbol)
    model_name = f"{symbol}_lstm_improved_{next_version}_{timestamp}"
    
    # Train model
    print(f"\n🎯 Starting training...")
    print(f"   Model will be saved as: {model_name}")
    
    history = ml_model.train(
        X_train, y_train,
        X_test, y_test,
        epochs=epochs,
        batch_size=32,
        model_name=model_name,
        patience=10
    )
    
    # Evaluate
    print(f"\n📈 Evaluating model...")
    metrics = ml_model.evaluate(X_test, y_test, include_backtest=False)
    
    print(f"\n✅ Training Complete!")
    print(f"   Final validation loss: {min(history['val_loss']):.4f}")
    print(f"   Best epoch: {np.argmin(history['val_loss']) + 1}")
    
    # Test predictions to ensure no collapse and check for bias
    print(f"\n🔍 Checking for collapse and bias...")
    test_predictions = ml_model.predict(X_test[:100])  # Test on 100 samples
    
    # Check for collapse
    unique_preds = len(set([f"{x:.6f}" for x in test_predictions.flatten()]))
    pred_std = test_predictions.std()
    pred_mean = test_predictions.mean()
    pred_min = test_predictions.min()
    pred_max = test_predictions.max()
    
    # Check for extreme values
    extreme_predictions = np.sum(np.abs(test_predictions) > 0.25)  # More than 25% change
    negative_predictions = np.sum(test_predictions < 0)
    positive_predictions = np.sum(test_predictions > 0)
    negative_bias_pct = (negative_predictions / len(test_predictions.flatten())) * 100
    
    print(f"   Unique predictions: {unique_preds}/100")
    print(f"   Prediction std dev: {pred_std:.6f}")
    print(f"   Prediction mean: {pred_mean:.6f}")
    print(f"   Prediction range: [{pred_min:.6f}, {pred_max:.6f}]")
    print(f"   Extreme predictions (>25%): {extreme_predictions}")
    print(f"   Negative bias: {negative_bias_pct:.1f}% negative predictions")
    
    # Warnings
    if unique_preds < 5 or pred_std < 0.0001:
        print("   ⚠️  WARNING: Model may have collapsed!")
    elif extreme_predictions > 10:
        print("   ⚠️  WARNING: Model predicting extreme values!")
    elif negative_bias_pct > 70:
        print("   ⚠️  WARNING: Strong negative bias detected!")
    elif negative_bias_pct < 30:
        print("   ⚠️  WARNING: Strong positive bias detected!")
    else:
        print("   ✅ Model shows healthy variation and balanced predictions")
    
    # Save scalers for production
    data_processor.save_scalers(symbol, model_name)
    print(f"\n💾 Saved scalers for production use")
    
    return ml_model, history


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Train improved model')
    parser.add_argument('--token-address', type=str, required=True,
                        help='Token address to train on')
    parser.add_argument('--symbol', type=str, required=True,
                        help='Token symbol')
    parser.add_argument('--days', type=int, default=30,
                        help='Days of historical data')
    parser.add_argument('--resolution', type=str, default='1H',
                        help='Data resolution')
    parser.add_argument('--epochs', type=int, default=30,
                        help='Maximum training epochs')
    parser.add_argument('--optimization-target', type=str, 
                        default='anti_collapse',
                        choices=['mse', 'simple_directional', 'profit', 'direction', 'direction_focused', 'balanced_directional', 'magnitude_constrained', 'variance_encouraging', 'anti_collapse', 'robust_directional'],
                        help='Loss function to use (anti_collapse recommended for fixing constant predictions)')
    
    args = parser.parse_args()
    
    model, history = train_improved_model(
        token_address=args.token_address,
        symbol=args.symbol,
        days=args.days,
        resolution=args.resolution,
        epochs=args.epochs,
        optimization_target=args.optimization_target
    ) 