#!/usr/bin/env python3
"""
Debug script for signal generation and feature processing
"""

import asyncio
import numpy as np
from datetime import datetime
from src.inference.strategy_engine import SimpleStrategyEngine
from src.database.production_db import get_db_manager

async def debug_signal_generation():
    """Debug the signal generation process step by step"""
    
    # Initialize components
    db_manager = await get_db_manager()
    engine = SimpleStrategyEngine(backtest_mode=True)
    await engine._ensure_db_manager()
    
    print("=== FEATURE DEBUGGING ===")
    
    try:
        # Get model and metadata separately
        model_registry = engine.model_registry
        model = model_registry.get_model('$WIF')
        metadata = model_registry.get_model_metadata('$WIF')
        print(f"Model loaded: {model is not None}")
        print(f"Metadata: {metadata}")
        
        # Get features (this should now use scaled features)
        if metadata:
            print("\n=== TESTING INFERENCE PROCESSOR DIRECTLY ===")
            
            # Test the inference processor directly
            inference_processor = engine.inference_processor
            if not inference_processor:
                await engine._ensure_inference_processor()
                inference_processor = engine.inference_processor
            
            # Get $WIF token info
            token_info = await inference_processor._get_token_info('EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm')
            print(f"Token info: {token_info}")
            
            # Prepare inference data directly through the processor
            inference_data = await inference_processor.prepare_inference_data(
                'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm',
                resolution='1H',
                simulation_time=datetime(2025, 5, 10, 0, 0)
            )
            
            if inference_data and inference_data.get('ready_for_inference'):
                print(f"\n✅ Direct inference data prepared successfully")
                
                # Check scaling info
                scaling_info = inference_data.get('scaling_info', {})
                print(f"📊 Scaling applied: {scaling_info.get('scaled', False)}")
                print(f"📁 Feature scaler available: {scaling_info.get('feature_scaler_available', False)}")
                print(f"🏷️ Symbol: {scaling_info.get('symbol', 'Unknown')}")
                
                # Get the actual feature matrix
                feature_matrix = np.array(inference_data['feature_matrix'])
                print(f"\n=== FEATURE MATRIX FROM INFERENCE PROCESSOR ===")
                print(f"Shape: {feature_matrix.shape}")
                print(f"Dtype: {feature_matrix.dtype}")
                print(f"Min: {feature_matrix.min():.6f}")
                print(f"Max: {feature_matrix.max():.6f}")
                print(f"Mean: {feature_matrix.mean():.6f}")
                print(f"Std: {feature_matrix.std():.6f}")
                
                if scaling_info.get('scaled'):
                    print("🎉 Features ARE scaled!")
                else:
                    print("⚠️ Features are NOT scaled")
            else:
                print("❌ Direct inference data preparation failed")
                return
            
            # Now test the strategy engine's _prepare_features method
            print(f"\n=== TESTING STRATEGY ENGINE _prepare_features ===")
            features = await engine._prepare_features('$WIF', metadata, simulation_time=datetime(2025, 5, 10, 0, 0))
            
            if features is not None:
                print(f"Features shape: {features.shape}")
                print(f"Features dtype: {features.dtype}")
                print(f"Features has NaN: {np.isnan(features).any()}")
                print(f"Features has Inf: {np.isinf(features).any()}")
                print(f"Features min: {features.min()}")
                print(f"Features max: {features.max()}")
                print(f"Features mean: {features.mean()}")
                print(f"Features std: {features.std()}")
                print(f"NaN count: {np.isnan(features).sum()}")
                print(f"Inf count: {np.isinf(features).sum()}")
                
                # Compare the two feature matrices
                print(f"\n=== COMPARISON ===")
                # The strategy engine trims to sequence length, so compare the last 36 rows
                inference_trimmed = feature_matrix[-36:]
                print(f"Inference processor (trimmed): shape {inference_trimmed.shape}")
                print(f"Strategy engine: shape {features.shape}")
                print(f"Arrays equal: {np.allclose(inference_trimmed, features, equal_nan=True)}")
                
                if not np.allclose(inference_trimmed, features, equal_nan=True):
                    print("⚠️ Arrays are different! Strategy engine might not be using scaled features")
                    print(f"Max difference: {np.abs(inference_trimmed - features).max()}")
                else:
                    print("✅ Arrays are identical - scaling is working correctly")
            else:
                print("Failed to prepare features for $WIF")
                return
        else:
            print("No metadata found!")
            return
    
    except Exception as e:
        print(f"Feature debugging failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n=== SIGNAL DEBUGGING ===")
    signal = await engine.generate_signal('$WIF', simulation_time=datetime(2025, 5, 10, 0, 0))
    
    if signal:
        print(f"Symbol: {signal.symbol}")
        print(f"Predicted change: {signal.predicted_change_pct:.6f}")
        print(f"Signal type: {signal.signal_type.value}")
        print(f"Strength: {signal.strength.value}")
        print(f"Confidence: {signal.confidence:.6f}")
        print(f"Buy threshold: {signal.strategy_params['buy_threshold']:.6f}")
        print(f"Raw prediction: {signal.raw_prediction}")
        print(f"Current price: {signal.current_price:.6f}")
        print(f"Predicted price: {signal.predicted_price:.6f}")
        
        print(f"\nStrength calculation debug:")
        buy_threshold = signal.strategy_params['buy_threshold']
        predicted_change = signal.predicted_change_pct
        print(f"Buy threshold: {buy_threshold:.6f}")
        print(f"Predicted change: {predicted_change:.6f}")
        print(f"Strong threshold (2x): {buy_threshold * 2:.6f}")
        print(f"Moderate threshold (1.5x): {buy_threshold * 1.5:.6f}")
        
        if abs(predicted_change) >= buy_threshold * 2:
            print("Should be STRONG")
        elif abs(predicted_change) >= buy_threshold * 1.5:
            print("Should be MODERATE")
        else:
            print("Should be WEAK")
    else:
        print("No signal generated")

if __name__ == "__main__":
    asyncio.run(debug_signal_generation()) 