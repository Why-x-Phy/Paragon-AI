#!/usr/bin/env python3
"""
Reset Adaptive Strategy Thresholds

This script resets tokens with unreasonably high thresholds back to defaults.
Useful for fixing tokens that got stuck with 3%+ thresholds due to 0% win rates.

Usage:
    python reset_adaptive_thresholds.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.inference.adaptive_strategy import get_adaptive_strategy_engine
from src.database.production_db import get_db_manager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Main function to reset high thresholds"""
    try:
        logger.info("🔄 Starting adaptive strategy threshold reset...")
        
        # Initialize components
        db_manager = await get_db_manager()
        adaptive_engine = await get_adaptive_strategy_engine(db_manager=db_manager)
        
        # Show current parameters before reset
        logger.info("\n📊 Current adaptive strategy parameters:")
        for symbol, params in adaptive_engine.strategy_parameters.items():
            logger.info(f"  {symbol}: buy={params.buy_threshold:.1%}, sell={params.sell_threshold:.1%}, "
                       f"signals={params.total_signals}, win_rate={params.win_rate:.1%}")
        
        # Reset high thresholds
        reset_count = await adaptive_engine.reset_high_threshold_tokens(
            max_buy_threshold=0.025,   # 2.5%
            max_sell_threshold=0.025   # 2.5%
        )
        
        if reset_count > 0:
            logger.info(f"\n✅ Reset {reset_count} tokens with high thresholds")
            
            # Show parameters after reset
            logger.info("\n📊 Updated adaptive strategy parameters:")
            for symbol, params in adaptive_engine.strategy_parameters.items():
                logger.info(f"  {symbol}: buy={params.buy_threshold:.1%}, sell={params.sell_threshold:.1%}, "
                           f"signals={params.total_signals}, win_rate={params.win_rate:.1%}")
        else:
            logger.info("✅ No tokens needed threshold reset")
        
        # Clean up
        await adaptive_engine.close()
        
        logger.info("🎉 Threshold reset completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Failed to reset thresholds: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 