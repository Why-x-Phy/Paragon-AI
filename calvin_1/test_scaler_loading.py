#!/usr/bin/env python3
"""
Test Scaler Loading and Feature Scaling

Verifies that the inference data processor can correctly load and apply
the fitted scalers to generate properly scaled features for inference.
"""

import asyncio
import numpy as np
from datetime import datetime
from src.data.inference_data_processor import InferenceDataProcessor
from src.database.production_db import get_db_manager
from src.utils.logger import log

logger = log

async def test_scaler_loading():
    """Test loading scalers and applying them to features"""
    
    try:
        # Initialize components
        db_manager = await get_db_manager()
        processor = InferenceDataProcessor(db_manager)
        
        logger.info("🧪 Testing Scaler Loading and Feature Scaling")
        logger.info("=" * 60)
        
        # Test 1: Load scalers for $WIF (we know this exists)
        logger.info("\n📦 Test 1: Loading scalers for $WIF")
        feature_scaler, price_scaler = processor.load_scalers_for_model('$WIF')
        
        if feature_scaler is not None:
            logger.info(f"✅ Feature scaler loaded successfully")
            logger.info(f"   📊 Features: {len(feature_scaler.mean_)}")
            logger.info(f"   📈 Mean range: {feature_scaler.mean_.min():.3f} to {feature_scaler.mean_.max():.3f}")
            logger.info(f"   📊 Scale range: {feature_scaler.scale_.min():.6f} to {feature_scaler.scale_.max():.6f}")
        else:
            logger.error("❌ Failed to load feature scaler for $WIF")
            return
        
        if price_scaler is not None:
            logger.info(f"✅ Price scaler loaded successfully")
            logger.info(f"   📈 Data range: {price_scaler.data_min_[0]:.6f} to {price_scaler.data_max_[0]:.6f}")
            logger.info(f"   📊 Scale: {price_scaler.scale_[0]:.6f}")
        else:
            logger.error("❌ Failed to load price scaler for $WIF")
        
        # Test 2: Test with non-existent model
        logger.info("\n📦 Test 2: Loading scalers for non-existent model")
        no_scaler_feature, no_scaler_price = processor.load_scalers_for_model('NONEXISTENT')
        
        if no_scaler_feature is None and no_scaler_price is None:
            logger.info("✅ Correctly returned None for non-existent model")
        else:
            logger.error("❌ Should have returned None for non-existent model")
        
        # Test 3: Test actual inference data preparation with scaling
        logger.info("\n🔄 Test 3: Full inference data preparation with scaling")
        
        # Get $WIF token address
        wif_token_address = "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"
        
        # Prepare inference data (this should now apply scaling)
        inference_data = await processor.prepare_inference_data(wif_token_address, resolution='1H')
        
        if inference_data and inference_data.get('ready_for_inference'):
            logger.info("✅ Inference data prepared successfully")
            
            # Check scaling info
            scaling_info = inference_data.get('scaling_info', {})
            logger.info(f"   📊 Scaling applied: {scaling_info.get('scaled', False)}")
            logger.info(f"   📁 Feature scaler available: {scaling_info.get('feature_scaler_available', False)}")
            logger.info(f"   📁 Price scaler available: {scaling_info.get('price_scaler_available', False)}")
            logger.info(f"   🏷️ Symbol: {scaling_info.get('symbol', 'Unknown')}")
            
            # Check feature matrix
            feature_matrix = np.array(inference_data['feature_matrix'])
            logger.info(f"   📈 Feature matrix shape: {feature_matrix.shape}")
            logger.info(f"   📊 Feature count: {inference_data['feature_count']}")
            
            if scaling_info.get('scaled'):
                logger.info("🎉 SUCCESS: Features are properly scaled!")
                
                # Show some statistics of scaled features
                logger.info(f"   📊 Scaled feature stats:")
                logger.info(f"      Mean: {feature_matrix.mean():.6f}")
                logger.info(f"      Std: {feature_matrix.std():.6f}")
                logger.info(f"      Min: {feature_matrix.min():.6f}")
                logger.info(f"      Max: {feature_matrix.max():.6f}")
            else:
                logger.warning("⚠️ Features are not scaled (this is expected for tokens without scalers)")
        else:
            logger.error("❌ Failed to prepare inference data")
        
        # Test 4: Get scaler statistics
        logger.info("\n📊 Test 4: Scaler statistics")
        stats = processor.get_scaler_statistics()
        logger.info(f"   📦 Cached scalers: {stats['cached_scalers']}")
        logger.info(f"   🏷️ Available symbols: {stats['available_symbols']}")
        logger.info(f"   💾 Cache size: {stats['cache_size_mb']:.3f} MB")
        
        logger.info("\n" + "=" * 60)
        logger.info("🎉 All scaler loading tests completed!")
        
    except Exception as e:
        logger.error(f"💥 Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_scaler_loading()) 