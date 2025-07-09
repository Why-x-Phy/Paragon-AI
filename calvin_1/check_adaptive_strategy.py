#!/usr/bin/env python3
"""
Check Adaptive Strategy Status

Quick script to check the current status of the adaptive strategy engine
and see if it's working properly.
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

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

async def check_adaptive_strategy():
    """Check adaptive strategy status"""
    try:
        print("🔍 Checking Adaptive Strategy Status...")
        print("=" * 50)
        
        # Import adaptive strategy
        from src.inference.adaptive_strategy import get_adaptive_strategy_engine
        
        # Get the engine
        try:
            adaptive_engine = await get_adaptive_strategy_engine()
            print("✅ Adaptive Strategy Engine found")
        except Exception as e:
            print(f"❌ Failed to get adaptive strategy engine: {e}")
            return
        
        # Check if monitoring is running
        print(f"🔄 Monitoring Status: {'Running' if adaptive_engine.is_running else 'Stopped'}")
        print(f"📊 Adaptation Method: {adaptive_engine.config.adaptation_method.value}")
        print(f"⏱️  Adaptation Frequency: {adaptive_engine.config.adaptation_frequency_minutes} minutes")
        print(f"🎯 Min Signals Required: {adaptive_engine.config.min_signals_for_adaptation}")
        print(f"📈 Low Volatility Threshold: {adaptive_engine.config.low_volatility_threshold:.1%}")
        print(f"📉 High Volatility Threshold: {adaptive_engine.config.high_volatility_threshold:.1%}")
        
        print("\n📋 Current Strategy Parameters:")
        print("-" * 30)
        
        # Check parameters for each token
        if adaptive_engine.strategy_parameters:
            for symbol, params in adaptive_engine.strategy_parameters.items():
                print(f"{symbol}:")
                print(f"  Buy Threshold:  {params.buy_threshold:.2%}")
                print(f"  Sell Threshold: {params.sell_threshold:.2%}")
                print(f"  Total Signals:  {params.total_signals}")
                print(f"  Win Rate:       {params.win_rate:.1%}")
                print(f"  Last Updated:   {params.last_updated.strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Check market conditions
                if symbol in adaptive_engine.market_conditions:
                    conditions = adaptive_engine.market_conditions[symbol]
                    print(f"  Market Regime:  {conditions.regime.value}")
                    print(f"  24h Volatility: {conditions.volatility_24h:.2%}")
                    print(f"  24h Momentum:   {conditions.momentum_24h:.1f}%")
                print()
        else:
            print("❌ No strategy parameters found")
        
        # Check adaptation stats
        print("📊 Adaptation Statistics:")
        print("-" * 25)
        stats = await adaptive_engine.get_adaptation_stats()
        if stats:
            print(f"Total Adaptations: {stats.get('total_adaptations', 0)}")
            print(f"Signals Analyzed:  {stats.get('total_signals_analyzed', 0)}")
            print(f"Active Tokens:     {len(stats.get('active_tokens', []))}")
            print(f"Uptime Hours:      {stats.get('uptime_hours', 0):.1f}")
            
            # Show regime distribution
            regime_dist = stats.get('regime_distribution', {})
            if regime_dist:
                print("\nMarket Regime Distribution:")
                for regime, count in regime_dist.items():
                    print(f"  {regime}: {count} tokens")
        else:
            print("❌ No adaptation statistics available")
        
        print("\n" + "=" * 50)
        print("✅ Adaptive Strategy Status Check Complete")
        
    except Exception as e:
        print(f"❌ Error checking adaptive strategy: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_adaptive_strategy()) 