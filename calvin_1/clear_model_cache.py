#!/usr/bin/env python3
"""
Standalone script to clear Calvin AI model registry cache and reload metadata.

This script:
1. Clears the in-memory model cache
2. Clears the metadata cache
3. Reloads all metadata from JSON files (picks up any manual changes)
4. Clears Redis cache if available

Usage:
    python clear_model_cache.py
"""

import sys
import os
import json
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def clear_model_cache():
    """Clear all model registry caches and reload metadata"""
    print("🧹 Clearing Calvin AI model registry cache...")
    
    try:
        # Import after adding to path
        from src.inference.model_registry import get_model_registry
        from src.config.config import config
        
        # Get the registry instance
        registry = get_model_registry()
        
        print(f"📍 Registry path: {registry.registry_path}")
        print(f"📍 Models directory: {registry.models_dir}")
        
        # 1. Clear in-memory caches
        print("🗑️  Clearing in-memory caches...")
        registry._model_cache.clear()
        registry._metadata_cache.clear()
        print(f"   ✅ Cleared {len(registry._model_cache)} models from memory")
        print(f"   ✅ Cleared metadata cache")
        
        # 2. Clear Redis cache if available
        if registry.redis_client:
            try:
                print("🗑️  Clearing Redis cache...")
                
                # Clear model weights from Redis
                keys = registry.redis_client.keys("model_weights:*")
                if keys:
                    registry.redis_client.delete(*keys)
                    print(f"   ✅ Cleared {len(keys)} model weights from Redis")
                else:
                    print("   ℹ️  No model weights found in Redis")
                
                # Clear any other model-related keys
                signal_keys = registry.redis_client.keys("signal:*")
                if signal_keys:
                    registry.redis_client.delete(*signal_keys)
                    print(f"   ✅ Cleared {len(signal_keys)} signals from Redis")
                
            except Exception as e:
                print(f"   ⚠️  Redis cache clear failed: {e}")
        else:
            print("   ℹ️  Redis not available, skipping Redis cache clear")
        
        # 3. Reload metadata from JSON files
        print("📥 Reloading metadata from JSON files...")
        
        # Scan for metadata JSON files
        metadata_files = list(registry.registry_path.glob("*_metadata.json"))
        print(f"   📁 Found {len(metadata_files)} metadata files")
        
        loaded_count = 0
        for metadata_file in metadata_files:
            try:
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                
                # Deserialize metadata
                metadata = registry._deserialize_metadata(data)
                
                # Extract model key from filename
                model_key = metadata_file.stem.replace('_metadata', '')
                
                # Store in cache
                registry._metadata_cache[model_key] = metadata
                loaded_count += 1
                
                print(f"   ✅ {metadata.symbol}: buy={metadata.buy_threshold:.1%}, "
                      f"sell={metadata.sell_threshold:.1%}, "
                      f"confidence={metadata.confidence_threshold:.1%}")
                
            except Exception as e:
                print(f"   ❌ Failed to reload {metadata_file.name}: {e}")
        
        print(f"\n🎉 Cache clearing complete!")
        print(f"   📊 Reloaded metadata for {loaded_count} models")
        print(f"   🚀 Updated thresholds are now active")
        
        # Show summary of available models
        if loaded_count > 0:
            print(f"\n📋 Available models:")
            for symbol in sorted(set(m.symbol for m in registry._metadata_cache.values())):
                metadata = registry.get_model_metadata(symbol)
                if metadata:
                    print(f"   • {symbol}: buy={metadata.buy_threshold:.1%}, sell={metadata.sell_threshold:.1%}")
        
    except ImportError as e:
        print(f"❌ Failed to import Calvin AI modules: {e}")
        print("   Make sure you're running this script from the calvin_1 directory")
        return False
    except Exception as e:
        print(f"❌ Cache clearing failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("Calvin AI Model Registry Cache Cleaner")
    print("=" * 50)
    
    success = clear_model_cache()
    
    if success:
        print("\n✅ All done! Your updated model thresholds are now active.")
        print("   You can now run signal generation and it will use the new values.")
    else:
        print("\n❌ Cache clearing failed. You may need to restart the program instead.")
        sys.exit(1) 