#!/usr/bin/env python
"""
Script to clear feature caches that might be causing feature mismatch issues.
This clears Redis caches and forces fresh feature generation.
"""

import os
import sys
import asyncio
import redis
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
env_path = project_root / '.env'

if env_path.exists():
    print(f"Loading environment from: {env_path}")
    load_dotenv(env_path)
else:
    print("No .env file found, using default environment")
    load_dotenv()

def clear_redis_caches():
    """Clear all Redis caches related to features and models"""
    try:
        # Connect to Redis
        redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD'),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=True
        )
        
        # Test connection
        redis_client.ping()
        print("✅ Connected to Redis")
        
        # Clear feature-related caches
        feature_patterns = [
            "inference_features:*",
            "batch_inference:*", 
            "feature_cache:*",
            "model_cache:*",
            "price:current:*",
            "signal_cache:*"
        ]
        
        total_cleared = 0
        for pattern in feature_patterns:
            keys = redis_client.keys(pattern)
            if keys:
                deleted = redis_client.delete(*keys)
                total_cleared += deleted
                print(f"   Cleared {deleted} keys matching '{pattern}'")
            else:
                print(f"   No keys found for '{pattern}'")
        
        print(f"\n✅ Total cache entries cleared: {total_cleared}")
        
        # Also clear the binary Redis client (for model weights)
        redis_binary = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD'),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=False  # Binary mode
        )
        
        binary_keys = redis_binary.keys(b"*")
        if binary_keys:
            deleted = redis_binary.delete(*binary_keys)
            print(f"✅ Cleared {deleted} binary cache entries (model weights)")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to clear Redis caches: {e}")
        return False

def clear_memory_caches():
    """Clear in-memory caches in the strategy engine"""
    try:
        from src.inference.strategy_engine import get_strategy_engine
        
        # Get strategy engine and clear its caches
        engine = get_strategy_engine()
        engine.clear_caches()
        print("✅ Cleared strategy engine memory caches")
        
        # Also clear model registry caches
        from src.inference.model_registry import get_model_registry
        registry = get_model_registry()
        
        # Clear in-memory model cache
        if hasattr(registry, '_model_cache'):
            registry._model_cache.clear()
            print("✅ Cleared model registry memory cache")
        
        # Clear metadata cache
        if hasattr(registry, '_metadata_cache'):
            registry._metadata_cache.clear()
            print("✅ Cleared model registry metadata cache")
            
        return True
        
    except Exception as e:
        print(f"❌ Failed to clear memory caches: {e}")
        return False

def clear_feature_files():
    """Clear any cached feature files on disk"""
    try:
        # Look for feature cache directories
        cache_dirs = [
            "data/cache",
            "data/features", 
            "cache",
            "temp"
        ]
        
        cleared_files = 0
        for cache_dir in cache_dirs:
            if os.path.exists(cache_dir):
                for root, dirs, files in os.walk(cache_dir):
                    for file in files:
                        if file.endswith(('.pkl', '.npy', '.h5', '.json')):
                            try:
                                os.remove(os.path.join(root, file))
                                cleared_files += 1
                            except:
                                pass
        
        if cleared_files > 0:
            print(f"✅ Cleared {cleared_files} cached feature files")
        else:
            print("   No cached feature files found")
            
        return True
        
    except Exception as e:
        print(f"❌ Failed to clear feature files: {e}")
        return False

async def main():
    """Main function to clear all caches"""
    print("🧹 Clearing Feature Caches")
    print("=" * 50)
    
    # 1. Clear Redis caches
    print("\n1. Clearing Redis caches...")
    redis_cleared = clear_redis_caches()
    
    # 2. Clear memory caches
    print("\n2. Clearing memory caches...")
    memory_cleared = clear_memory_caches()
    
    # 3. Clear feature files
    print("\n3. Clearing cached feature files...")
    files_cleared = clear_feature_files()
    
    # Summary
    print("\n" + "=" * 50)
    print("🎯 Cache Clearing Summary:")
    print(f"   Redis caches: {'✅ Cleared' if redis_cleared else '❌ Failed'}")
    print(f"   Memory caches: {'✅ Cleared' if memory_cleared else '❌ Failed'}")
    print(f"   Feature files: {'✅ Cleared' if files_cleared else '❌ Failed'}")
    
    if redis_cleared and memory_cleared:
        print("\n✅ All caches cleared successfully!")
        print("   Next time you run predictions, fresh features will be generated.")
        print("   This should resolve the feature mismatch issue.")
    else:
        print("\n⚠️  Some caches could not be cleared.")
        print("   You may need to restart the application to clear all caches.")

if __name__ == "__main__":
    asyncio.run(main()) 