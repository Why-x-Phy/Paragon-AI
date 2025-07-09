#!/usr/bin/env python3
"""
Check Prediction Actions

Check what values are actually in the prediction_action and confidence_score fields
"""

import asyncio
import os
import sys
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

async def check_prediction_actions():
    """Check what values are in prediction_action and confidence_score fields"""
    try:
        print("🔍 Checking Prediction Actions and Confidence Scores...")
        print("=" * 60)
        
        from src.database.production_db import get_db_manager
        db_manager = await get_db_manager()
        
        async with db_manager.pg_pool.acquire() as conn:
            # Check distinct prediction_action values
            actions_query = """
                SELECT 
                    prediction_action,
                    COUNT(*) as count,
                    COUNT(CASE WHEN prediction_time >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h
                FROM model_predictions
                GROUP BY prediction_action
                ORDER BY count DESC
            """
            
            actions_result = await conn.fetch(actions_query)
            
            print("📊 Prediction Actions:")
            print(f"{'Action':<15} {'Total Count':<12} {'Last 24h':<10}")
            print("-" * 40)
            for row in actions_result:
                action = row['prediction_action'] or 'NULL'
                print(f"{action:<15} {row['count']:<12} {row['last_24h']:<10}")
            
            print()
            
            # Check confidence_score distribution
            confidence_query = """
                SELECT 
                    CASE 
                        WHEN confidence_score IS NULL THEN 'NULL'
                        WHEN confidence_score = 0 THEN 'ZERO'
                        WHEN confidence_score > 0 AND confidence_score <= 0.1 THEN '0.0-0.1'
                        WHEN confidence_score > 0.1 AND confidence_score <= 0.5 THEN '0.1-0.5'
                        WHEN confidence_score > 0.5 AND confidence_score <= 1.0 THEN '0.5-1.0'
                        ELSE 'OVER 1.0'
                    END as confidence_range,
                    COUNT(*) as count,
                    COUNT(CASE WHEN prediction_time >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h
                FROM model_predictions
                GROUP BY 
                    CASE 
                        WHEN confidence_score IS NULL THEN 'NULL'
                        WHEN confidence_score = 0 THEN 'ZERO'
                        WHEN confidence_score > 0 AND confidence_score <= 0.1 THEN '0.0-0.1'
                        WHEN confidence_score > 0.1 AND confidence_score <= 0.5 THEN '0.1-0.5'
                        WHEN confidence_score > 0.5 AND confidence_score <= 1.0 THEN '0.5-1.0'
                        ELSE 'OVER 1.0'
                    END
                ORDER BY count DESC
            """
            
            confidence_result = await conn.fetch(confidence_query)
            
            print("📈 Confidence Score Distribution:")
            print(f"{'Range':<15} {'Total Count':<12} {'Last 24h':<10}")
            print("-" * 40)
            for row in confidence_result:
                print(f"{row['confidence_range']:<15} {row['count']:<12} {row['last_24h']:<10}")
            
            print()
            
            # Test the exact adaptive strategy filters
            filtered_query = """
                SELECT COUNT(*) as filtered_count
                FROM model_predictions mp
                JOIN tokens tk ON mp.token_id = tk.token_id
                WHERE mp.prediction_time >= NOW() - INTERVAL '24 hours'
                  AND mp.prediction_action IN ('buy', 'sell')
                  AND mp.confidence_score IS NOT NULL
            """
            
            filtered_result = await conn.fetchrow(filtered_query)
            
            print("🎯 Adaptive Strategy Filters Result:")
            print(f"Records matching filters: {filtered_result['filtered_count']}")
            
            # Show some sample records that should match
            sample_query = """
                SELECT 
                    tk.symbol,
                    mp.prediction_action,
                    mp.confidence_score,
                    mp.predicted_price_change,
                    mp.prediction_time
                FROM model_predictions mp
                JOIN tokens tk ON mp.token_id = tk.token_id
                WHERE mp.prediction_time >= NOW() - INTERVAL '24 hours'
                ORDER BY mp.prediction_time DESC
                LIMIT 5
            """
            
            sample_result = await conn.fetch(sample_query)
            
            print("\n📋 Sample Recent Records:")
            print(f"{'Symbol':<10} {'Action':<10} {'Confidence':<12} {'Change':<10} {'Time':<20}")
            print("-" * 70)
            for row in sample_result:
                action = row['prediction_action'] or 'NULL'
                conf = f"{row['confidence_score']:.3f}" if row['confidence_score'] is not None else 'NULL'
                change = f"{row['predicted_price_change']:.3f}" if row['predicted_price_change'] is not None else 'NULL'
                time_str = row['prediction_time'].strftime('%H:%M:%S') if row['prediction_time'] else 'NULL'
                print(f"{row['symbol']:<10} {action:<10} {conf:<12} {change:<10} {time_str:<20}")
        
        await db_manager.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_prediction_actions()) 