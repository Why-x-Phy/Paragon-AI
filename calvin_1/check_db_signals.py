#!/usr/bin/env python3
"""
Check Database Signals

Quick script to check what signals are actually in the database
without interfering with the running vault system.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
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

async def check_database_signals():
    """Check what signals are in the database"""
    try:
        print("🔍 Checking Database Signals...")
        print("=" * 50)
        
        from src.database.production_db import get_db_manager
        db_manager = await get_db_manager()
        
        # Check model_predictions table
        query = """
            SELECT 
                COUNT(*) as total_predictions,
                COUNT(CASE WHEN prediction_time >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h,
                COUNT(CASE WHEN prediction_time >= NOW() - INTERVAL '1 hour' THEN 1 END) as last_1h,
                MIN(prediction_time) as earliest,
                MAX(prediction_time) as latest
            FROM model_predictions
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            result = await conn.fetchrow(query)
            
            print(f"📊 Model Predictions Summary:")
            print(f"  Total Predictions: {result['total_predictions']}")
            print(f"  Last 24 hours: {result['last_24h']}")
            print(f"  Last 1 hour: {result['last_1h']}")
            print(f"  Earliest: {result['earliest']}")
            print(f"  Latest: {result['latest']}")
            print()
            
            # Check recent signals by symbol
            recent_query = """
                SELECT 
                    tk.symbol,
                    COUNT(*) as signal_count,
                    AVG(mp.confidence_score) as avg_confidence,
                    AVG(ABS(mp.predicted_price_change)) as avg_magnitude,
                    MAX(mp.prediction_time) as latest_signal
                FROM model_predictions mp
                JOIN tokens tk ON mp.token_id = tk.token_id
                WHERE mp.prediction_time >= NOW() - INTERVAL '24 hours'
                GROUP BY tk.symbol
                ORDER BY signal_count DESC
                LIMIT 10
            """
            
            recent_results = await conn.fetch(recent_query)
            
            print(f"📈 Recent Signals by Symbol (Last 24h):")
            print(f"{'Symbol':<10} {'Count':<6} {'Avg Conf':<10} {'Avg Mag':<10} {'Latest':<20}")
            print("-" * 70)
            
            for row in recent_results:
                latest_time = row['latest_signal'].strftime('%H:%M:%S') if row['latest_signal'] else 'N/A'
                print(f"{row['symbol']:<10} {row['signal_count']:<6} {row['avg_confidence']:<10.2f} {row['avg_magnitude']:<10.3f} {latest_time:<20}")
            
            print()
            
            # Check trades table
            trades_query = """
                SELECT 
                    COUNT(*) as total_trades,
                    COUNT(CASE WHEN confirmed_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h_trades
                FROM trades
            """
            
            trades_result = await conn.fetchrow(trades_query)
            print(f"💰 Trades Summary:")
            print(f"  Total Trades: {trades_result['total_trades']}")
            print(f"  Last 24 hours: {trades_result['last_24h_trades']}")
            print()
            
            # Check if adaptive strategy should be getting data
            combined_query = """
                SELECT 
                    tk.symbol,
                    COUNT(*) as predictions,
                    COUNT(t.trade_id) as actual_trades,
                    AVG(ABS(mp.predicted_price_change)) as avg_predicted_change
                FROM model_predictions mp
                JOIN tokens tk ON mp.token_id = tk.token_id
                LEFT JOIN trades t ON (
                    t.token_id = mp.token_id 
                    AND t.cycle_timestamp BETWEEN mp.prediction_time - INTERVAL '10 minutes' 
                                                AND mp.prediction_time + INTERVAL '10 minutes'
                )
                WHERE mp.prediction_time >= NOW() - INTERVAL '24 hours'
                  AND mp.prediction_action IN ('buy', 'sell')
                GROUP BY tk.symbol
                ORDER BY predictions DESC
                LIMIT 5
            """
            
            combined_results = await conn.fetch(combined_query)
            
            print(f"🔗 Predictions vs Trades (Top 5 symbols):")
            print(f"{'Symbol':<10} {'Predictions':<12} {'Trades':<8} {'Avg Change':<12}")
            print("-" * 50)
            
            for row in combined_results:
                print(f"{row['symbol']:<10} {row['predictions']:<12} {row['actual_trades']:<8} {row['avg_predicted_change']:<12.3f}")
            
        await db_manager.close()
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_database_signals()) 