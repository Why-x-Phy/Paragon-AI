#!/usr/bin/env python3
"""
Test Enhanced Model Registry

Tests the enhanced model registry with both legacy and new model formats.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.inference.model_registry import get_model_registry, register_model
from src.utils.logger import log

logger = log

def test_enhanced_model_registry():
    """Test enhanced model registry functionality"""
    
    print("🧪 Testing Enhanced Model Registry")
    print("=" * 50)
    
    try:
        # Get registry instance
        registry = get_model_registry()
        
        # Test 1: List all models
        print("\n📋 Test 1: List all registered models")
        models = registry.list_models()
        print(f"Found {len(models)} models:")
        
        for model in models[:5]:  # Show first 5
            display_version = registry.get_display_version(model)
            format_type = "Legacy" if model.is_legacy else "New"
            print(f"  - {model.symbol}: {display_version} ({format_type})")
        
        if len(models) > 5:
            print(f"  ... and {len(models) - 5} more models")
        
        # Test 2: Test legacy model loading
        print("\n🔄 Test 2: Load legacy format models")
        legacy_models = [m for m in models if m.is_legacy]
        
        if legacy_models:
            test_model = legacy_models[0]
            print(f"Testing legacy model: {test_model.symbol}")
            
            # Test loading by symbol (should get latest)
            model = registry.get_model(test_model.symbol)
            if model:
                print(f"✅ Successfully loaded {test_model.symbol} (latest version)")
            else:
                print(f"❌ Failed to load {test_model.symbol}")
            
            # Test loading by specific version
            model_specific = registry.get_model(test_model.symbol, test_model.version)
            if model_specific:
                print(f"✅ Successfully loaded {test_model.symbol} version {test_model.version}")
            else:
                print(f"❌ Failed to load {test_model.symbol} version {test_model.version}")
        else:
            print("No legacy models found to test")
        
        # Test 3: Test model metadata
        print("\n📊 Test 3: Model metadata")
        if models:
            test_model = models[0]
            metadata = registry.get_model_metadata(test_model.symbol)
            if metadata:
                print(f"Model: {metadata.symbol}")
                print(f"  Path: {metadata.model_path}")
                print(f"  Format: {'Legacy' if metadata.is_legacy else 'New'}")
                print(f"  Date Version: {metadata.version}")
                print(f"  Semantic Version: {metadata.semantic_version or 'N/A'}")
                print(f"  Input Shape: {metadata.input_shape}")
                print(f"  Sequence Length: {metadata.sequence_length}")
                print(f"  Strategy Params: buy={metadata.buy_threshold}, sell={metadata.sell_threshold}")
            else:
                print("❌ Failed to get metadata")
        
        # Test 4: Strategy parameters
        print("\n⚙️ Test 4: Strategy parameters")
        if models:
            test_model = models[0]
            params = registry.get_strategy_parameters(test_model.symbol)
            print(f"Strategy parameters for {test_model.symbol}:")
            print(f"  Buy threshold: {params['buy_threshold']}")
            print(f"  Sell threshold: {params['sell_threshold']}")
            print(f"  Confidence threshold: {params['confidence_threshold']}")
        
        # Test 5: Health status
        print("\n🏥 Test 5: Health status")
        health = registry.get_health_status()
        print("Registry health status:")
        print(f"  Total models: {health['total_models']}")
        print(f"  Legacy format: {health['legacy_format_models']}")
        print(f"  New format: {health['new_format_models']}")
        print(f"  Models in memory: {health['models_in_memory']}")
        print(f"  Redis status: {health['redis_status']}")
        
        # Test 6: Model finding logic
        print("\n🔍 Test 6: Model finding logic")
        if models:
            test_symbol = models[0].symbol
            
            # Test finding latest
            latest_key = registry._find_model_key(test_symbol)
            if latest_key:
                latest_metadata = registry._metadata_cache[latest_key]
                print(f"Latest model for {test_symbol}: {registry.get_display_version(latest_metadata)}")
            
            # Test finding by date version
            date_key = registry._find_model_key(test_symbol, models[0].version)
            if date_key:
                print(f"Found model by date version: {models[0].version}")
            
            # Test finding by semantic version (if available)
            semantic_models = [m for m in models if m.symbol == test_symbol and m.semantic_version]
            if semantic_models:
                semantic_key = registry._find_model_key(test_symbol, semantic_models[0].semantic_version)
                if semantic_key:
                    print(f"Found model by semantic version: {semantic_models[0].semantic_version}")
        
        print("\n✅ Enhanced Model Registry tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_enhanced_model_registry()
    sys.exit(0 if success else 1) 