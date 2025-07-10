#!/usr/bin/env python3
"""
Check Prediction Details

Detailed analysis of model predictions to understand why no buy signals are generated.
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

async def check_prediction_details():
    """Check detailed prediction information"""
    try:
        print("🔍 Checking Detailed Prediction Information...")
        print("=" * 80)
        
        from src.database.production_db import get_db_manager
        db_manager = await get_db_manager()
        
        async with db_manager.pg_pool.acquire() as conn:
            # First, show the distribution of predicted price changes
            distribution_query = """
                SELECT 
                    CASE 
                        WHEN predicted_price_change >= 0.01 THEN 'BUY (>= 1%)'
                        WHEN predicted_price_change <= -0.015 THEN 'SELL (<= -1.5%)'
                        WHEN predicted_price_change > 0 THEN 'POSITIVE (< 1%)'
                        WHEN predicted_price_change < 0 THEN 'NEGATIVE (> -1.5%)'
                        ELSE 'ZERO'
                    END as signal_category,
                    COUNT(*) as count,
                    AVG(predicted_price_change) as avg_change,
                    MAX(predicted_price_change) as max_change,
                    MIN(predicted_price_change) as min_change,
                    AVG(confidence_score) as avg_confidence
                FROM model_predictions
                WHERE prediction_time >= NOW() - INTERVAL '24 hours'
                GROUP BY signal_category
                ORDER BY 
                    CASE signal_category
                        WHEN 'BUY (>= 1%)' THEN 1
                        WHEN 'SELL (<= -1.5%)' THEN 2
                        WHEN 'POSITIVE (< 1%)' THEN 3
                        WHEN 'NEGATIVE (> -1.5%)' THEN 4
                        ELSE 5
                    END
            """
            
            dist_results = await conn.fetch(distribution_query)
            
            print("📊 Predicted Price Change Distribution (Last 24h):")
            print(f"{'Category':<20} {'Count':<8} {'Avg %':<10} {'Max %':<10} {'Min %':<10} {'Avg Conf':<10}")
            print("-" * 80)
            
            for row in dist_results:
                print(f"{row['signal_category']:<20} {row['count']:<8} "
                      f"{row['avg_change']*100:<10.3f} {row['max_change']*100:<10.3f} "
                      f"{row['min_change']*100:<10.3f} {row['avg_confidence']:<10.3f}")
            
            print("\n" + "="*80 + "\n")
            
            # Show recent predictions with actual values
            recent_query = """
                SELECT 
                    tk.symbol,
                    mp.prediction_time,
                    mp.prediction_action,
                    mp.predicted_price_change * 100 as predicted_change_pct,
                    mp.confidence_score,
                    mp.model_version
                FROM model_predictions mp
                JOIN tokens tk ON mp.token_id = tk.token_id
                WHERE mp.prediction_time >= NOW() - INTERVAL '2 hours'
                ORDER BY mp.prediction_time DESC
                LIMIT 20
            """
            
            recent_results = await conn.fetch(recent_query)
            
            print("📈 Recent Individual Predictions (Last 2 hours):")
            print(f"{'Time':<20} {'Symbol':<10} {'Action':<8} {'Pred %':<10} {'Conf':<8} {'Model':<20}")
            print("-" * 80)
            
            for row in recent_results:
                time_str = row['prediction_time'].strftime('%H:%M:%S')
                print(f"{time_str:<20} {row['symbol']:<10} {row['prediction_action']:<8} "
                      f"{row['predicted_change_pct']:<10.3f} {row['confidence_score']:<8.3f} "
                      f"{row['model_version'][:20]:<20}")
            
            print("\n" + "="*80 + "\n")
            
            # Show tokens with the highest predicted changes
            high_change_query = """
                SELECT 
                    tk.symbol,
                    COUNT(*) as predictions,
                    MAX(mp.predicted_price_change * 100) as max_positive_pct,
                    MIN(mp.predicted_price_change * 100) as max_negative_pct,
                    AVG(ABS(mp.predicted_price_change) * 100) as avg_magnitude_pct,
                    COUNT(CASE WHEN mp.predicted_price_change >= 0.01 THEN 1 END) as buy_signals,
                    COUNT(CASE WHEN mp.predicted_price_change <= -0.015 THEN 1 END) as sell_signals
                FROM model_predictions mp
                JOIN tokens tk ON mp.token_id = tk.token_id
                WHERE mp.prediction_time >= NOW() - INTERVAL '24 hours'
                GROUP BY tk.symbol
                HAVING AVG(ABS(mp.predicted_price_change)) > 0
                ORDER BY avg_magnitude_pct DESC
                LIMIT 10
            """
            
            high_change_results = await conn.fetch(high_change_query)
            
            print("🚀 Tokens with Highest Average Predicted Changes (Last 24h):")
            print(f"{'Symbol':<10} {'Predictions':<12} {'Max +%':<10} {'Max -%':<10} {'Avg |%|':<10} {'Buy Sig':<10} {'Sell Sig':<10}")
            print("-" * 80)
            
            for row in high_change_results:
                print(f"{row['symbol']:<10} {row['predictions']:<12} "
                      f"{row['max_positive_pct']:<10.3f} {row['max_negative_pct']:<10.3f} "
                      f"{row['avg_magnitude_pct']:<10.3f} {row['buy_signals']:<10} {row['sell_signals']:<10}")
            
            print("\n" + "="*80 + "\n")
            
            # Summary statistics
            summary_query = """
                SELECT 
                    COUNT(*) as total_predictions,
                    COUNT(CASE WHEN predicted_price_change >= 0.01 THEN 1 END) as potential_buys,
                    COUNT(CASE WHEN predicted_price_change <= -0.015 THEN 1 END) as potential_sells,
                    COUNT(CASE WHEN prediction_action = 'buy' THEN 1 END) as buy_actions,
                    COUNT(CASE WHEN prediction_action = 'sell' THEN 1 END) as sell_actions,
                    COUNT(CASE WHEN prediction_action = 'hold' THEN 1 END) as hold_actions,
                    AVG(ABS(predicted_price_change) * 100) as avg_magnitude_pct,
                    MAX(predicted_price_change * 100) as max_positive_pct,
                    MIN(predicted_price_change * 100) as max_negative_pct,
                    AVG(confidence_score) as avg_confidence
                FROM model_predictions
                WHERE prediction_time >= NOW() - INTERVAL '24 hours'
            """
            
            summary_result = await conn.fetchrow(summary_query)
            
            print("📋 Summary Statistics (Last 24h):")
            print(f"  Total Predictions: {summary_result['total_predictions']}")
            print(f"  Predictions >= 1% (Buy Threshold): {summary_result['potential_buys']}")
            print(f"  Predictions <= -1.5% (Sell Threshold): {summary_result['potential_sells']}")
            print(f"  Average Magnitude: {summary_result['avg_magnitude_pct']:.3f}%")
            print(f"  Max Positive Change: {summary_result['max_positive_pct']:.3f}%")
            print(f"  Max Negative Change: {summary_result['max_negative_pct']:.3f}%")
            print(f"  Average Confidence: {summary_result['avg_confidence']:.3f}")
            print()
            print(f"  Action Distribution:")
            print(f"    Buy Actions: {summary_result['buy_actions']}")
            print(f"    Sell Actions: {summary_result['sell_actions']}")
            print(f"    Hold Actions: {summary_result['hold_actions']}")
            
            print("\n" + "="*80 + "\n")
            print("💡 Analysis:")
            print(f"  - Buy threshold is 1.0%, but only {summary_result['potential_buys']} predictions meet this")
            print(f"  - Sell threshold is 1.5%, but only {summary_result['potential_sells']} predictions meet this")
            print(f"  - The models are predicting very small changes (avg {summary_result['avg_magnitude_pct']:.3f}%)")
            print(f"  - This explains why no buy signals are being generated in production!")
            
        await db_manager.close()
        
    except Exception as e:
        print(f"❌ Error checking predictions: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_prediction_details()) 