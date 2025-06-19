#!/usr/bin/env python3
"""
Calvin AI Memory Profiling Script

Simulates actual inference workload to measure real memory requirements:
- Loads all LSTM models into memory (hot loading simulation)
- Processes 362 features for all active tokens
- Measures memory usage at each stage
- Provides AWS instance sizing recommendations

This gives us real data instead of theoretical estimates.
"""

import asyncio
import psutil
import gc
import time
import tracemalloc
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database.production_db import get_db_manager
from src.inference.model_registry import get_model_registry
from src.inference.strategy_engine import SimpleStrategyEngine, StrategyConfig
from src.data.inference_data_processor import create_inference_data_processor
from src.utils.logger import log

logger = log

class MemoryProfiler:
    """Memory profiling utility for Calvin AI inference system"""
    
    def __init__(self):
        self.process = psutil.Process()
        self.memory_snapshots = []
        self.peak_memory = 0
        
    def get_memory_usage(self) -> Dict[str, float]:
        """Get current memory usage in MB"""
        memory_info = self.process.memory_info()
        virtual_memory = self.process.memory_percent()
        
        memory_mb = memory_info.rss / (1024 * 1024)
        self.peak_memory = max(self.peak_memory, memory_mb)
        
        return {
            'rss_mb': memory_mb,
            'vms_mb': memory_info.vms / (1024 * 1024),
            'percent': virtual_memory,
            'peak_mb': self.peak_memory
        }
    
    def snapshot(self, stage: str) -> Dict[str, Any]:
        """Take a memory snapshot at a specific stage"""
        gc.collect()  # Force garbage collection for accurate measurement
        time.sleep(0.1)  # Let GC finish
        
        memory = self.get_memory_usage()
        
        snapshot = {
            'stage': stage,
            'timestamp': datetime.now(),
            'memory_mb': memory['rss_mb'],
            'peak_mb': memory['peak_mb'],
            'virtual_mb': memory['vms_mb'],
            'cpu_percent': self.process.cpu_percent()
        }
        
        self.memory_snapshots.append(snapshot)
        print(f"📊 {stage}: {memory['rss_mb']:.1f} MB (Peak: {memory['peak_mb']:.1f} MB)")
        
        return snapshot

async def profile_calvin_memory_usage():
    """
    Profile actual Calvin AI memory usage during inference simulation
    """
    print("🔍 Calvin AI Memory Profiling - Inference Simulation")
    print("=" * 80)
    
    # Start memory tracking
    tracemalloc.start()
    profiler = MemoryProfiler()
    
    # Baseline memory
    profiler.snapshot("1. Baseline (Python + imports)")
    
    try:
        # Initialize database connection
        print("\n🔌 Initializing database connection...")
        db_manager = await get_db_manager()
        await db_manager.health_check()
        profiler.snapshot("2. Database connected")
        
        # Get active tokens
        print("\n🪙 Loading active tokens...")
        active_tokens_query = """
        SELECT token_id, symbol, address 
        FROM tokens 
        WHERE is_active = true 
        ORDER BY symbol
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            token_results = await conn.fetch(active_tokens_query)
        
        active_tokens = [dict(row) for row in token_results]
        token_addresses = [token['address'] for token in active_tokens]
        
        print(f"Found {len(active_tokens)} active tokens: {[t['symbol'] for t in active_tokens]}")
        profiler.snapshot("3. Active tokens loaded")
        
        # Initialize model registry (this will discover all models)
        print("\n🤖 Initializing model registry...")
        model_registry = get_model_registry()
        available_models = model_registry.list_models()
        print(f"Found {len(available_models)} available models")
        profiler.snapshot("4. Model registry initialized")
        
        # Load ALL models into memory (hot loading simulation)
        print("\n🔥 Loading all models into memory (hot loading simulation)...")
        loaded_models = {}
        model_load_start = time.time()
        
        for i, model_metadata in enumerate(available_models):
            symbol = model_metadata.symbol
            version = model_metadata.version
            
            print(f"  Loading model {i+1}/{len(available_models)}: {symbol} v{version}")
            
            try:
                model = model_registry.get_model(symbol, version)
                if model:
                    loaded_models[symbol] = model
                    # Take snapshot every 5 models
                    if (i + 1) % 5 == 0:
                        profiler.snapshot(f"4.{i+1}. Loaded {i+1} models")
                
            except Exception as e:
                logger.warning(f"Failed to load model for {symbol}: {e}")
        
        model_load_time = time.time() - model_load_start
        print(f"✅ Loaded {len(loaded_models)} models in {model_load_time:.1f} seconds")
        profiler.snapshot("5. All models loaded (hot cache)")
        
        # Initialize inference data processor
        print("\n⚙️ Initializing inference data processor...")
        inference_processor = await create_inference_data_processor(db_manager)
        profiler.snapshot("6. Inference processor initialized")
        
        # Process features for ALL tokens (simulating hourly inference)
        print("\n🧮 Processing features for all tokens (362 features per token)...")
        feature_start = time.time()
        
        # Process tokens in batches to monitor memory growth
        batch_size = 5
        processed_tokens = 0
        
        for i in range(0, len(token_addresses), batch_size):
            batch_addresses = token_addresses[i:i + batch_size]
            batch_symbols = [active_tokens[j]['symbol'] for j in range(i, min(i + batch_size, len(active_tokens)))]
            
            print(f"  Processing batch {i//batch_size + 1}: {batch_symbols}")
            
            # Process inference data for this batch
            batch_data = await inference_processor.get_batch_inference_data(
                token_addresses=batch_addresses,
                resolution='1H'
            )
            
            # Count successful feature processing
            successful = sum(1 for data in batch_data.values() if data.get('ready_for_inference', False))
            processed_tokens += successful
            
            # Check feature count for one successful token
            if successful > 0:
                sample_data = next(data for data in batch_data.values() if data.get('ready_for_inference', False))
                feature_count = len(sample_data.get('features', []))
                print(f"    ✅ {successful}/{len(batch_addresses)} tokens processed, {feature_count} features each")
            
            profiler.snapshot(f"7.{i//batch_size + 1}. Processed {processed_tokens} tokens")
        
        feature_time = time.time() - feature_start
        print(f"✅ Processed features for {processed_tokens} tokens in {feature_time:.1f} seconds")
        profiler.snapshot("8. All features processed")
        
        # Initialize strategy engine (with all models hot)
        print("\n🎯 Initializing strategy engine...")
        strategy_config = StrategyConfig(max_models_in_memory=len(loaded_models))
        strategy_engine = SimpleStrategyEngine(config=strategy_config)
        await strategy_engine._ensure_db_manager()
        await strategy_engine._ensure_inference_processor()
        profiler.snapshot("9. Strategy engine initialized")
        
        # Simulate generating signals for all tokens
        print("\n📈 Simulating signal generation for all tokens...")
        signal_start = time.time()
        
        generated_signals = 0
        for i, token in enumerate(active_tokens[:10]):  # Test with first 10 tokens
            symbol = token['symbol']
            if symbol in loaded_models:
                try:
                    print(f"  Generating signal {i+1}/10: {symbol}")
                    
                    # This simulates the full inference pipeline
                    signal = await strategy_engine.generate_signal(symbol)
                    if signal:
                        generated_signals += 1
                        
                except Exception as e:
                    logger.warning(f"Signal generation failed for {symbol}: {e}")
        
        signal_time = time.time() - signal_start
        print(f"✅ Generated {generated_signals} signals in {signal_time:.1f} seconds")
        profiler.snapshot("10. All signals generated")
        
        # Final memory analysis
        print("\n💾 Redis memory usage analysis...")
        try:
            redis_info = await db_manager.redis_client.info('memory')
            redis_memory_mb = redis_info.get('used_memory', 0) / (1024 * 1024)
            print(f"Redis memory usage: {redis_memory_mb:.1f} MB")
        except Exception as e:
            print(f"Could not get Redis memory info: {e}")
        
        profiler.snapshot("11. Final state (all systems active)")
        
    except Exception as e:
        logger.error(f"Memory profiling failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Clean up
        if 'db_manager' in locals():
            await db_manager.close()
    
    # Print comprehensive memory analysis
    print_memory_analysis(profiler)
    
    # Get tracemalloc statistics
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    print(f"\n🔍 Tracemalloc Analysis:")
    print(f"Current memory: {current / 1024 / 1024:.1f} MB")
    print(f"Peak memory: {peak / 1024 / 1024:.1f} MB")

def print_memory_analysis(profiler: MemoryProfiler):
    """Print detailed memory analysis and AWS recommendations"""
    print("\n" + "=" * 80)
    print("📊 MEMORY USAGE ANALYSIS")
    print("=" * 80)
    
    if not profiler.memory_snapshots:
        print("No memory snapshots available")
        return
    
    # Print all snapshots
    print(f"{'Stage':<50} {'Memory (MB)':<15} {'Peak (MB)':<15}")
    print("-" * 80)
    
    baseline = profiler.memory_snapshots[0]['memory_mb']
    for snapshot in profiler.memory_snapshots:
        stage = snapshot['stage']
        memory = snapshot['memory_mb']
        peak = snapshot['peak_mb']
        
        print(f"{stage:<50} {memory:<15.1f} {peak:<15.1f}")
    
    # Calculate deltas
    final_memory = profiler.memory_snapshots[-1]['memory_mb']
    peak_memory = profiler.peak_memory
    
    print(f"\n📈 MEMORY GROWTH ANALYSIS:")
    print(f"Baseline memory: {baseline:.1f} MB")
    print(f"Final memory: {final_memory:.1f} MB")
    print(f"Peak memory: {peak_memory:.1f} MB")
    print(f"Total growth: {final_memory - baseline:.1f} MB")
    
    # Find memory-intensive stages
    print(f"\n🔥 MEMORY-INTENSIVE STAGES:")
    for i in range(1, len(profiler.memory_snapshots)):
        current = profiler.memory_snapshots[i]
        previous = profiler.memory_snapshots[i-1]
        delta = current['memory_mb'] - previous['memory_mb']
        
        if delta > 100:  # Significant memory increase
            print(f"  {current['stage']}: +{delta:.1f} MB")
    
    # AWS Instance Recommendations
    print(f"\n🚀 AWS INSTANCE RECOMMENDATIONS:")
    print(f"Based on peak memory usage of {peak_memory:.1f} MB")
    
    # Add safety margins for production
    recommended_memory = peak_memory * 1.5  # 50% safety margin
    with_growth = recommended_memory * 1.3   # 30% growth margin
    
    print(f"Minimum required: {peak_memory:.1f} MB")
    print(f"With safety margin: {recommended_memory:.1f} MB") 
    print(f"With growth margin: {with_growth:.1f} MB")
    
    # Instance recommendations
    if with_growth <= 8000:  # 8 GB
        print("✅ RECOMMENDED: t3.large or m6i.large (8 GB)")
        print("   Cost: ~$60-80/month")
    elif with_growth <= 16000:  # 16 GB
        print("✅ RECOMMENDED: t3.xlarge or m6i.xlarge (16 GB)")
        print("   Cost: ~$120-170/month")
    elif with_growth <= 32000:  # 32 GB
        print("✅ RECOMMENDED: m6i.2xlarge (32 GB)")
        print("   Cost: ~$280-340/month")
    else:
        print("⚠️  REQUIRES: m6i.4xlarge or larger (64+ GB)")
        print("   Cost: ~$560+/month")
    
    print(f"\n💡 OPTIMIZATION OPPORTUNITIES:")
    if peak_memory > 4000:
        print("  - Consider model pruning or quantization")
        print("  - Implement model lazy loading instead of hot caching")
        print("  - Add feature caching to reduce recomputation")
    
    if len(profiler.memory_snapshots) > 10:
        model_loading_growth = 0
        feature_processing_growth = 0
        
        # Find model loading growth
        for snapshot in profiler.memory_snapshots:
            if "models loaded" in snapshot['stage'].lower():
                model_loading_growth = snapshot['memory_mb'] - baseline
            elif "features processed" in snapshot['stage'].lower():
                feature_processing_growth = snapshot['memory_mb'] - (baseline + model_loading_growth)
        
        if model_loading_growth > 0:
            print(f"  - Model loading uses {model_loading_growth:.1f} MB")
        if feature_processing_growth > 0:
            print(f"  - Feature processing uses {feature_processing_growth:.1f} MB")

async def main():
    """Run memory profiling"""
    print("🚀 Starting Calvin AI Memory Profiling...")
    print(f"⏰ Started at: {datetime.now()}")
    
    await profile_calvin_memory_usage()
    
    print(f"\n✅ Memory profiling completed at: {datetime.now()}")

if __name__ == "__main__":
    asyncio.run(main()) 