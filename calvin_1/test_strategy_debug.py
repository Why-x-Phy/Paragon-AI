import asyncio
import logging
from datetime import datetime
from src.inference.strategy_engine import get_strategy_engine

# Set up logging to see debug messages
logging.basicConfig(level=logging.DEBUG)

async def test_strategy_engine():
    print("=== Testing Strategy Engine Data Loading ===")
    
    engine = get_strategy_engine()
    
    # Test with a known token and simulation time
    test_time = datetime(2025, 3, 14, 12, 0, 0)
    print(f"Testing BONK signal generation at {test_time}")
    
    signal = await engine.generate_signal('BONK', simulation_time=test_time)
    
    if signal:
        print(f"✅ Signal generated: {signal.signal_type} with confidence {signal.confidence}")
    else:
        print("❌ No signal generated")

if __name__ == "__main__":
    asyncio.run(test_strategy_engine()) 