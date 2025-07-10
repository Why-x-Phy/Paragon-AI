#!/usr/bin/env python3
"""
Regenerate Scalers for Existing Models

This script regenerates the scaler files for existing models by:
1. Loading model metadata to get training parameters
2. Fetching the same historical data
3. Fitting the scalers on that data
4. Saving the scalers for production use
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

async def regenerate_scalers_for_model(metadata_file: str):
    """Regenerate scalers for a specific model"""
    try:
        # Load model metadata
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        symbol = metadata['symbol']
        model_version = metadata['version']
        
        print(f"\n🔧 Regenerating scalers for {symbol} model {model_version}...")
        
        # Initialize data processor
        data_processor = DataProcessor()
        
        # Determine training date range
        # Most models were trained with 90 days of data
        created_date = datetime.fromisoformat(metadata['created_at'].replace('Z', '+00:00'))
        end_date = created_date - timedelta(days=1)  # Day before model creation
        start_date = end_date - timedelta(days=90)  # 90 days of training data
        
        print(f"📊 Fetching training data from {start_date.date()} to {end_date.date()}...")
        
        # Fetch historical data using process_pipeline
        # First, we need to get the token address for the symbol
        from src.database.production_db import ProductionDBManager
        db_manager = ProductionDBManager()
        try:
            await db_manager.initialize()
            token_info = await db_manager.get_token_by_symbol(symbol)
            if not token_info:
                print(f"❌ Token {symbol} not found in database")
                return False
            
            # Handle both dictionary and object returns from get_token_by_symbol
            if hasattr(token_info, 'address'):
                token_address = token_info.address
            else:
                token_address = token_info['address']
            
            # Calculate day offset from current time to end_date
            from datetime import datetime as dt
            current_date = dt.now()
            day_offset = (current_date - end_date).days
            
            # Use process_pipeline to fetch and process data
            df = data_processor.process_pipeline(
                token_address=token_address,
                symbol=symbol,
                resolution='1H',
                days=90,
                save_data=False,
                include_sentiment=True,
                day_offset=day_offset
            )
        finally:
            await db_manager.close()
        
        if df is None or df.empty:
            print(f"❌ No data found for {symbol}")
            return False
        
        print(f"✅ Got {len(df)} rows of data")
        
        # Prepare ML data to fit the scalers
        print(f"🔄 Fitting scalers on training data...")
        X_train, _, _, _ = data_processor.prepare_ml_data(
            df,
            target_col='close',
            sequence_length=metadata.get('sequence_length', 36),
            prediction_horizon=metadata.get('prediction_horizon', 1),
            test_size=0.2,  # Same as training
            include_feature_names=False
        )
        
        if X_train is None or len(X_train) == 0:
            print(f"❌ Failed to prepare training data for {symbol}")
            return False
        
        # Save the fitted scalers
        data_processor.save_scalers(symbol, model_version)
        print(f"✅ Saved scalers for {symbol} model {model_version}")
        
        # Verify the scalers were saved
        scaler_dir = os.path.join(data_processor.data_dir, "scalers")
        price_scaler_path = os.path.join(scaler_dir, f"{symbol}_{model_version}_price_scaler.pkl")
        feature_scaler_path = os.path.join(scaler_dir, f"{symbol}_{model_version}_feature_scaler.pkl")
        
        if os.path.exists(price_scaler_path) and os.path.exists(feature_scaler_path):
            print(f"✅ Verified scaler files exist:")
            print(f"   - {price_scaler_path}")
            print(f"   - {feature_scaler_path}")
            return True
        else:
            print(f"❌ Scaler files not found after saving")
            return False
            
    except Exception as e:
        print(f"❌ Error regenerating scalers for {metadata_file}: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main function to regenerate scalers for all models"""
    print("🚀 Starting Scaler Regeneration...")
    
    # Find all model metadata files
    models_dir = os.path.join(os.getcwd(), "models", "registry")
    if not os.path.exists(models_dir):
        print(f"❌ Models directory not found: {models_dir}")
        return
    
    metadata_files = [f for f in os.listdir(models_dir) if f.endswith('_metadata.json')]
    
    if not metadata_files:
        print(f"❌ No model metadata files found in {models_dir}")
        return
    
    print(f"📋 Found {len(metadata_files)} models to process")
    
    # Process each model
    success_count = 0
    for metadata_file in metadata_files:
        metadata_path = os.path.join(models_dir, metadata_file)
        success = await regenerate_scalers_for_model(metadata_path)
        if success:
            success_count += 1
    
    print(f"\n✅ Successfully regenerated scalers for {success_count}/{len(metadata_files)} models")
    
    # Create summary
    scaler_dir = os.path.join(os.getcwd(), "data", "scalers")
    if os.path.exists(scaler_dir):
        scaler_files = [f for f in os.listdir(scaler_dir) if f.endswith('.pkl')]
        print(f"\n📂 Scaler directory contains {len(scaler_files)} files:")
        for f in sorted(scaler_files)[:5]:  # Show first 5
            print(f"   - {f}")
        if len(scaler_files) > 5:
            print(f"   ... and {len(scaler_files) - 5} more")

if __name__ == "__main__":
    asyncio.run(main()) 