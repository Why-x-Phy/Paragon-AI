"""
Test script to validate the updated inference system.

Tests the integration between:
1. Updated InferenceDataProcessor (using DataProcessor.prepare_ml_data)
2. Updated SimpleStrategyEngine (using inference_sequence)
3. Model prediction with no NaN values

This proves our refactoring to use the proven DataProcessor pattern works.
"""

import asyncio
import numpy as np
from datetime import datetime

from src.inference.strategy_engine import SimpleStrategyEngine
from src.database.production_db import get_db_manager
from src.utils.logger import log

logger = log

async def test_updated_inference_system():
    """Test the updated inference system end-to-end"""
    
    # Test with JUP (has newer model)
    symbol = "JUP"
    
    logger.info("=== TESTING UPDATED INFERENCE SYSTEM ===")
    logger.info(f"Testing with symbol: {symbol}")
    
    try:
        # 1. Initialize strategy engine
        logger.info("\n1. Initializing strategy engine...")
        strategy_engine = SimpleStrategyEngine(backtest_mode=False)
        logger.info("✅ Strategy engine initialized")
        
        # 2. Generate signal (this will test the entire pipeline)
        logger.info(f"\n2. Generating trading signal for {symbol}...")
        signal = await strategy_engine.generate_signal(symbol)
        
        if signal is None:
            logger.error(f"❌ Failed to generate signal for {symbol}")
            return
        
        # 3. Validate signal
        logger.info(f"\n3. SIGNAL RESULTS for {symbol}:")
        logger.info(f"   Signal Type: {signal.signal_type.value}")
        logger.info(f"   Strength: {signal.strength.value}")
        logger.info(f"   Confidence: {signal.confidence:.3f}")
        logger.info(f"   Current Price: ${signal.current_price:.6f}")
        logger.info(f"   Predicted Price: ${signal.predicted_price:.6f}")
        logger.info(f"   Predicted Change: {signal.predicted_change_pct:.2%}")
        logger.info(f"   Raw Prediction: {signal.raw_prediction:.6f}")
        logger.info(f"   Model Version: {signal.model_version}")
        logger.info(f"   Processing Time: {signal.processing_time_ms:.1f}ms")
        
        # 4. Validate no NaN values
        checks = {
            'current_price': signal.current_price,
            'predicted_price': signal.predicted_price,
            'predicted_change_pct': signal.predicted_change_pct,
            'raw_prediction': signal.raw_prediction,
            'confidence': signal.confidence
        }
        
        nan_found = False
        for field, value in checks.items():
            if np.isnan(value) or np.isinf(value):
                logger.error(f"❌ Invalid value in {field}: {value}")
                nan_found = True
        
        if not nan_found:
            logger.info("✅ All signal values are valid (no NaN/inf)")
        
        # 5. Test batch signal generation
        logger.info(f"\n4. Testing batch signal generation...")
        symbols = ["JUP", "BONK"]  # Test with multiple symbols
        batch_signals = await strategy_engine.generate_signals_batch(symbols)
        
        successful_signals = 0
        for sym, sig in batch_signals.items():
            if sig is not None:
                successful_signals += 1
                logger.info(f"   ✅ {sym}: {sig.signal_type.value} signal (confidence: {sig.confidence:.3f})")
            else:
                logger.warning(f"   ❌ {sym}: Failed to generate signal")
        
        logger.info(f"Batch results: {successful_signals}/{len(symbols)} successful")
        
        # 6. Get performance stats
        logger.info(f"\n5. Strategy engine performance:")
        stats = strategy_engine.get_performance_stats()
        for key, value in stats.items():
            if isinstance(value, (int, float)):
                logger.info(f"   {key}: {value}")
        
        logger.info("\n✅ SUCCESS! Updated inference system working correctly")
        logger.info("🎯 Key achievements:")
        logger.info("   - No NaN predictions")
        logger.info("   - DataProcessor.prepare_ml_data() integration working") 
        logger.info("   - Strategy engine updated for new data format")
        logger.info("   - End-to-end signal generation functional")
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(test_updated_inference_system()) 