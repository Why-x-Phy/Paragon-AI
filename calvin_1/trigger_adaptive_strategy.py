#!/usr/bin/env python3
"""
Trigger Adaptive Strategy

Manually trigger the adaptive strategy to test it without waiting for the scheduled run.
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

async def trigger_adaptive_strategy():
    """Manually trigger adaptive strategy for testing"""
    # Initialize shared database manager first
    from src.database.production_db import get_db_manager
    shared_db_manager = None
    
    try:
        print("🚀 Manually Triggering Adaptive Strategy...")
        print("=" * 50)
        
        # Create a shared database manager that will be used by all components
        print("📊 Initializing shared database manager...")
        shared_db_manager = await get_db_manager()
        
        # Import adaptive strategy
        from src.inference.adaptive_strategy import AdaptiveStrategyEngine
        
        # Create adaptive strategy with the shared database manager
        print("📊 Initializing adaptive strategy engine with shared DB...")
        adaptive_engine = AdaptiveStrategyEngine(db_manager=shared_db_manager)
        await adaptive_engine.initialize()
        
        print("✅ Adaptive strategy initialized")
        print()
        
        # Manually trigger the database update
        print("🔄 Updating performance from verified trades...")
        
        # Check what's in the database first
        print("  📊 Checking database before update...")
        
        # Use the shared database manager for our checks
        print("    🔍 Checking model predictions in database...")
        try:
            async with shared_db_manager.pg_pool.acquire() as conn:
                # First check if we have any predictions at all
                total_check = await conn.fetchrow("""
                    SELECT COUNT(*) as total_predictions,
                           COUNT(CASE WHEN prediction_time >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h
                    FROM model_predictions
                """)
                print(f"      Total predictions: {total_check['total_predictions']}, Last 24h: {total_check['last_24h']}")
                
                # Check predictions with buy/sell actions
                action_check = await conn.fetchrow("""
                    SELECT COUNT(*) as total_actionable,
                           COUNT(DISTINCT mp.token_id) as unique_tokens
                    FROM model_predictions mp
                    JOIN tokens tk ON mp.token_id = tk.token_id
                    WHERE mp.prediction_action IN ('buy', 'sell')
                      AND mp.prediction_time >= NOW() - INTERVAL '24 hours'
                """)
                print(f"      Actionable predictions (buy/sell): {action_check['total_actionable']}, Unique tokens: {action_check['unique_tokens']}")
                
                # Check if we have any 'hold' predictions (which might be our issue)
                hold_check = await conn.fetchrow("""
                    SELECT COUNT(*) as hold_predictions
                    FROM model_predictions
                    WHERE prediction_action = 'hold'
                      AND prediction_time >= NOW() - INTERVAL '24 hours'
                """)
                print(f"      Hold predictions: {hold_check['hold_predictions']}")
                
        except Exception as e:
            print(f"      ❌ Database check failed: {e}")
        
        # Now update performance from verified trades
        try:
            await adaptive_engine.update_performance_from_verified_trades()
            print("✅ Performance update complete")
        except Exception as e:
            print(f"❌ Performance update failed: {e}")
            import traceback
            traceback.print_exc()
        
        print()
        
        # Try to adapt parameters for all tokens
        test_symbols = list(adaptive_engine.strategy_parameters.keys())
        
        print(f"🎯 Testing adaptation for {len(test_symbols)} symbols...")
        
        adaptations_succeeded = 0
        adaptations_failed = 0
        
        for symbol in test_symbols:
            print(f"  🔧 Adapting {symbol}...")
            try:
                adapted = await adaptive_engine.adapt_strategy_parameters(symbol)
                if adapted:
                    print(f"    ✅ {symbol} adapted successfully")
                    adaptations_succeeded += 1
                else:
                    print(f"    ⏭️  {symbol} no adaptation needed")
            except Exception as e:
                print(f"    ❌ {symbol} adaptation failed: {e}")
                adaptations_failed += 1
        
        print()
        print(f"📊 Adaptation Summary: {adaptations_succeeded} succeeded, {adaptations_failed} failed")
        print()
        
        # Show updated parameters
        print("📋 Updated Strategy Parameters:")
        print("-" * 40)
        
        for symbol in test_symbols:
            if symbol.upper() in adaptive_engine.strategy_parameters:
                params = adaptive_engine.strategy_parameters[symbol.upper()]
                print(f"{symbol}:")
                print(f"  Buy: {params.buy_threshold:.3%} | Sell: {params.sell_threshold:.3%}")
                print(f"  Signals: {params.total_signals} | Win Rate: {params.win_rate:.1%}")
                
                # Check market conditions
                if symbol.upper() in adaptive_engine.market_conditions:
                    conditions = adaptive_engine.market_conditions[symbol.upper()]
                    print(f"  Volatility: {conditions.volatility_24h:.3%} | Regime: {conditions.regime.value}")
                print()
        
        # Get adaptation stats
        stats = await adaptive_engine.get_adaptation_stats()
        print("📊 Adaptation Statistics:")
        print(f"  Total Adaptations: {stats.get('total_adaptations', 0)}")
        print(f"  Signals Analyzed: {stats.get('total_signals_analyzed', 0)}")
        print(f"  Active Tokens: {len(stats.get('active_tokens', []))}")
        
        # Close adaptive engine first (it doesn't own the db_manager)
        await adaptive_engine.close()
        
    except Exception as e:
        print(f"❌ Error triggering adaptive strategy: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up the shared database manager last
        if shared_db_manager:
            try:
                await shared_db_manager.close()
                print("\n✅ Database connections closed properly")
            except Exception as e:
                print(f"\n❌ Error closing database: {e}")

if __name__ == "__main__":
    asyncio.run(trigger_adaptive_strategy()) 