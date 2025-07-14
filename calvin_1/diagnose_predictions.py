#!/usr/bin/env python3
"""
Diagnose Prediction Bias in Improved Models

This script tests predictions from improved models across different time periods
to identify bias patterns and understand why they're skewing negative.
"""

import os
import sys
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Load environment variables
from dotenv import load_dotenv
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncio
from src.inference.model_registry import get_model_registry
from src.inference.strategy_engine import SimpleStrategyEngine
from src.data.data_processor import DataProcessor
from src.database.production_db import get_db_manager


async def query_different_time_periods(symbol: str, periods: int = 20):
    """Query different time periods from the database for testing"""
    
    print(f"\n📊 Querying {periods} different time periods for {symbol}")
    print("=" * 60)
    
    db_manager = await get_db_manager()
    
    # Get current time
    now = datetime.utcnow()
    
    # Define time periods to test (historical only - we need future data for validation)
    time_periods = []
    
    # Use historical periods where we have future data available
    # Current time is around 2025-07-13 20:15, so we can test periods from several days ago
    # Expand to get a larger sample size for bias testing
    test_dates = []
    
    # Test every 12 hours going back 2 weeks for a larger sample
    for days_back in range(2, 15):  # 2 to 14 days ago
        for hours_offset in [0, 12]:  # Test at noon and midnight
            test_date = now - timedelta(days=days_back, hours=hours_offset)
            test_dates.append(test_date)
    
    # Sort by date (most recent first)
    test_dates.sort(reverse=True)
    
    for i, test_date in enumerate(test_dates):
        time_periods.append({
            'name': f'Historical {i+1}',
            'start': test_date - timedelta(hours=1),
            'end': test_date,
            'description': f'{test_date.strftime("%Y-%m-%d %H:%M")} ({i+2} days ago)'
        })
    
    # Limit to requested number of periods
    time_periods = time_periods[:periods]
    
    print(f"Testing {len(time_periods)} time periods:")
    for period in time_periods:
        print(f"  - {period['name']}: {period['description']}")
    
    return time_periods


async def check_data_availability(symbol: str, time_periods: list):
    """Check how much historical data is available for each time period"""
    
    print(f"\n📊 Checking Data Availability for {symbol}")
    print("=" * 60)
    
    db_manager = await get_db_manager()
    
    # Get token info
    token_info = await db_manager.get_token_by_symbol(symbol)
    if not token_info:
        print(f"❌ Token {symbol} not found in database")
        return
    
    token_id = token_info['token_id'] if hasattr(token_info, 'token_id') else token_info['token_id']
    
    for period in time_periods:
        end_time = period['end']
        
        # Check how much data we have going back from this point
        # Test different lookback periods
        lookback_periods = [240, 300, 360, 480]  # 10, 12.5, 15, 20 days
        
        print(f"\n📅 {period['name']}: {period['description']}")
        
        for lookback_hours in lookback_periods:
            start_time = end_time - timedelta(hours=lookback_hours)
            
            try:
                ohlcv_data = await db_manager.get_ohlcv_data(
                    token_id=token_id,
                    resolution='1H',
                    start_time=start_time,
                    end_time=end_time,
                    limit=lookback_hours + 10
                )
                
                if ohlcv_data:
                    data_count = len(ohlcv_data)
                    coverage_pct = (data_count / lookback_hours) * 100
                    print(f"  📊 {lookback_hours}h lookback: {data_count}/{lookback_hours} records ({coverage_pct:.1f}%)")
                else:
                    print(f"  ❌ {lookback_hours}h lookback: No data")
                    
            except Exception as e:
                print(f"  ❌ {lookback_hours}h lookback: Error - {e}")


async def validate_predictions_with_actual_data(symbol: str, period_results: list):
    """Validate predictions by comparing with actual future price movements"""
    
    print(f"\n🔍 Validating Predictions with Actual Price Data")
    print("=" * 60)
    
    db_manager = await get_db_manager()
    
    # Get token info
    token_info = await db_manager.get_token_by_symbol(symbol)
    if not token_info:
        print(f"❌ Token {symbol} not found in database")
        return period_results
    
    token_id = token_info['token_id'] if hasattr(token_info, 'token_id') else token_info['token_id']
    
    validated_results = []
    
    for result in period_results:
        print(f"\n📅 Validating {result['period']}: {result['description']}")
        
        try:
            # Parse simulation time
            simulation_time = datetime.fromisoformat(result['simulation_time'].replace('Z', '+00:00'))
            
            # Get actual price data for the next 1 hour after prediction (models predict next hour)
            future_start = simulation_time
            future_end = simulation_time + timedelta(hours=1)
            
            print(f"  🔍 Checking actual price movement from {future_start.strftime('%Y-%m-%d %H:%M')} to {future_end.strftime('%Y-%m-%d %H:%M')} (next hour)")
            
            # Fetch actual OHLCV data for the future period
            future_data = await db_manager.get_ohlcv_data(
                token_id=token_id,
                resolution='1H',
                start_time=future_start,
                end_time=future_end
            )
            
            if not future_data:
                print(f"  ⚠️  No future data available for validation")
                result['validation'] = {
                    'actual_change_pct': None,
                    'prediction_accurate': None,
                    'future_data_points': 0,
                    'actual_direction': None,
                    'predicted_direction': 'negative' if result['predicted_change'] < 0 else 'positive'
                }
                validated_results.append(result)
                continue
            
            # Get the price at prediction time and 1 hour later
            prediction_price = result['current_price']
            
            # Find the latest price in the future data
            latest_future_record = max(future_data, key=lambda x: x.time)
            future_price = float(latest_future_record.close)
            
            # Calculate actual percentage change
            actual_change_pct = (future_price - prediction_price) / prediction_price * 100
            
            # Determine if prediction was accurate
            predicted_direction = 'negative' if result['predicted_change'] < 0 else 'positive'
            actual_direction = 'negative' if actual_change_pct < 0 else 'positive'
            prediction_accurate = predicted_direction == actual_direction
            
            # Store validation results
            result['validation'] = {
                'actual_change_pct': actual_change_pct,
                'prediction_accurate': prediction_accurate,
                'future_data_points': len(future_data),
                'actual_direction': actual_direction,
                'predicted_direction': predicted_direction,
                'prediction_price': prediction_price,
                'future_price': future_price,
                'future_timestamp': latest_future_record.time.isoformat()
            }
            
            # Display results
            accuracy_indicator = "✅" if prediction_accurate else "❌"
            print(f"  {accuracy_indicator} Predicted: {result['predicted_change']:.3f}% ({predicted_direction})")
            print(f"     Actual: {actual_change_pct:.3f}% ({actual_direction})")
            print(f"     Accuracy: {'CORRECT' if prediction_accurate else 'WRONG'}")
            print(f"     Price: ${prediction_price:.6f} → ${future_price:.6f}")
            print(f"     Data points: {len(future_data)}")
            
            validated_results.append(result)
            
        except Exception as e:
            print(f"  ❌ Error validating prediction: {e}")
            result['validation'] = {
                'actual_change_pct': None,
                'prediction_accurate': None,
                'future_data_points': 0,
                'actual_direction': None,
                'predicted_direction': 'negative' if result['predicted_change'] < 0 else 'positive',
                'error': str(e)
            }
            validated_results.append(result)
    
    return validated_results


async def analyze_prediction_accuracy(validated_results: list):
    """Analyze the accuracy of predictions"""
    
    print(f"\n📊 Prediction Accuracy Analysis")
    print("=" * 60)
    
    if not validated_results:
        print("❌ No validated results to analyze")
        return
    
    # Filter out results with validation errors
    valid_results = [r for r in validated_results if r['validation']['prediction_accurate'] is not None]
    
    if not valid_results:
        print("❌ No valid predictions to analyze")
        return
    
    # Calculate accuracy metrics
    total_predictions = len(valid_results)
    correct_predictions = sum(1 for r in valid_results if r['validation']['prediction_accurate'])
    accuracy_rate = correct_predictions / total_predictions * 100
    
    # Analyze directional accuracy
    negative_predictions = [r for r in valid_results if r['validation']['predicted_direction'] == 'negative']
    positive_predictions = [r for r in valid_results if r['validation']['predicted_direction'] == 'positive']
    
    negative_accuracy = 0
    if negative_predictions:
        negative_correct = sum(1 for r in negative_predictions if r['validation']['prediction_accurate'])
        negative_accuracy = negative_correct / len(negative_predictions) * 100
    
    positive_accuracy = 0
    if positive_predictions:
        positive_correct = sum(1 for r in positive_predictions if r['validation']['prediction_accurate'])
        positive_accuracy = positive_correct / len(positive_predictions) * 100
    
    # Analyze actual market conditions
    actual_negative_moves = sum(1 for r in valid_results if r['validation']['actual_direction'] == 'negative')
    actual_positive_moves = sum(1 for r in valid_results if r['validation']['actual_direction'] == 'positive')
    
    # Calculate prediction vs actual correlation
    predicted_changes = [r['predicted_change'] for r in valid_results]
    actual_changes = [r['validation']['actual_change_pct'] for r in valid_results]
    
    if len(predicted_changes) > 1:
        correlation = np.corrcoef(predicted_changes, actual_changes)[0, 1]
    else:
        correlation = None
    
    # Display results
    print(f"📈 Overall Accuracy: {accuracy_rate:.1f}% ({correct_predictions}/{total_predictions})")
    print(f"📊 Directional Accuracy:")
    print(f"   Negative predictions: {negative_accuracy:.1f}% ({len(negative_predictions)} predictions)")
    print(f"   Positive predictions: {positive_accuracy:.1f}% ({len(positive_predictions)} predictions)")
    
    print(f"\n🎯 Market Conditions Analysis:")
    print(f"   Actual negative moves: {actual_negative_moves}/{total_predictions} ({actual_negative_moves/total_predictions*100:.1f}%)")
    print(f"   Actual positive moves: {actual_positive_moves}/{total_predictions} ({actual_positive_moves/total_predictions*100:.1f}%)")
    
    if correlation is not None:
        print(f"   Prediction correlation: {correlation:.3f}")
    
    # Analyze bias implications
    print(f"\n🔍 Bias Analysis:")
    
    if len(negative_predictions) > len(positive_predictions) * 2:
        print(f"  🚨 Model shows strong negative bias ({len(negative_predictions)} vs {len(positive_predictions)} predictions)")
        
        if negative_accuracy > 70:
            print(f"  ✅ But negative predictions are accurate ({negative_accuracy:.1f}%) - model is correctly bearish")
            print(f"  💡 Market may be in a downtrend, model is working correctly")
        else:
            print(f"  ❌ Negative predictions are inaccurate ({negative_accuracy:.1f}%) - model has false bearish bias")
            print(f"  💡 Model needs retraining with balanced data")
    else:
        print(f"  ✅ Model shows balanced directional predictions")
    
    # Check if model is overfitting to recent trends
    if actual_negative_moves > actual_positive_moves * 1.5:
        print(f"  📉 Market was actually bearish during test period ({actual_negative_moves/total_predictions*100:.1f}% negative moves)")
        print(f"  💡 Model may be correctly adapting to bearish market conditions")
    elif actual_positive_moves > actual_negative_moves * 1.5:
        print(f"  📈 Market was actually bullish during test period ({actual_positive_moves/total_predictions*100:.1f}% positive moves)")
        print(f"  ⚠️  Model incorrectly predicted bearish moves in bullish market")
    
    return {
        'overall_accuracy': accuracy_rate,
        'negative_accuracy': negative_accuracy,
        'positive_accuracy': positive_accuracy,
        'correlation': correlation,
        'market_bearish_ratio': actual_negative_moves / total_predictions if total_predictions > 0 else 0
    }


async def test_predictions_across_periods(symbol: str, time_periods: list):
    """Test predictions across different time periods"""
    
    print(f"\n🎯 Testing Predictions Across Time Periods")
    print("=" * 60)
    
    # Initialize components
    registry = get_model_registry()
    engine = SimpleStrategyEngine()
    
    # Find improved model
    models = registry.list_models(symbol)
    improved_models = [m for m in models if "improved" in m.model_path.lower()]
    if improved_models:
        model_metadata = improved_models[0]
    else:
        model_metadata = models[0]
    
    print(f"Using model: {model_metadata.model_path}")
    
    # Test each time period
    period_results = []
    
    for period in time_periods:
        print(f"\n📅 Testing {period['name']}: {period['description']}")
        
        try:
            # Clear cache for fresh data
            engine.clear_caches()
            
            # Use the END time of the period as simulation time to get historical data
            simulation_time = period['end']
            
            # Generate signal for this specific time period
            signal = await engine.generate_signal(symbol, simulation_time=simulation_time)
            
            if signal:
                result = {
                    'period': period['name'],
                    'description': period['description'],
                    'predicted_change': signal.predicted_change_pct,
                    'raw_prediction': signal.raw_prediction,
                    'confidence': signal.confidence,
                    'current_price': signal.current_price,
                    'predicted_price': signal.predicted_price,
                    'signal_type': signal.signal_type.value,
                    'simulation_time': simulation_time.isoformat()
                }
                
                period_results.append(result)
                
                print(f"  ✅ Prediction: {signal.predicted_change_pct:.3f}%")
                print(f"     Raw: {signal.raw_prediction:.6f}")
                print(f"     Confidence: {signal.confidence:.3f}")
                print(f"     Signal: {signal.signal_type.value.upper()}")
                print(f"     Simulation Time: {simulation_time.strftime('%Y-%m-%d %H:%M')}")
                
                # Check for bias
                if signal.predicted_change_pct < -1.0:
                    print(f"  ⚠️  NEGATIVE BIAS in this period")
                elif signal.predicted_change_pct > 1.0:
                    print(f"  ⚠️  POSITIVE BIAS in this period")
                else:
                    print(f"  ✅ Normal prediction range")
                    
            else:
                print(f"  ❌ No signal generated for this period")
                
        except Exception as e:
            print(f"  ❌ Error testing period: {e}")
            import traceback
            traceback.print_exc()
    
    return period_results


async def analyze_bias_patterns(period_results: list):
    """Analyze bias patterns across time periods"""
    
    print(f"\n📈 Bias Pattern Analysis")
    print("=" * 60)
    
    if not period_results:
        print("❌ No results to analyze")
        return
    
    # Extract predictions
    predictions = [r['predicted_change'] for r in period_results]
    raw_predictions = [r['raw_prediction'] for r in period_results]
    confidences = [r['confidence'] for r in period_results]
    
    # Calculate statistics
    avg_prediction = np.mean(predictions)
    std_prediction = np.std(predictions)
    min_prediction = min(predictions)
    max_prediction = max(predictions)
    
    avg_raw = np.mean(raw_predictions)
    std_raw = np.std(raw_predictions)
    
    avg_confidence = np.mean(confidences)
    
    print(f"📊 Prediction Statistics:")
    print(f"   Average: {avg_prediction:.3f}%")
    print(f"   Std Dev: {std_prediction:.3f}%")
    print(f"   Range: {min_prediction:.3f}% to {max_prediction:.3f}%")
    print(f"   Average Confidence: {avg_confidence:.3f}")
    
    print(f"\n🔍 Raw Prediction Statistics:")
    print(f"   Average Raw: {avg_raw:.6f}")
    print(f"   Std Dev Raw: {std_raw:.6f}")
    print(f"   Range Raw: {min(raw_predictions):.6f} to {max(raw_predictions):.6f}")
    
    # Analyze bias patterns
    print(f"\n🎯 Bias Analysis:")
    
    # Check for consistent negative bias
    negative_predictions = [p for p in predictions if p < 0]
    positive_predictions = [p for p in predictions if p > 0]
    
    print(f"   Negative predictions: {len(negative_predictions)}/{len(predictions)} ({len(negative_predictions)/len(predictions)*100:.1f}%)")
    print(f"   Positive predictions: {len(positive_predictions)}/{len(predictions)} ({len(positive_predictions)/len(predictions)*100:.1f}%)")
    
    if len(negative_predictions) > len(positive_predictions) * 2:
        print(f"  🚨 STRONG NEGATIVE BIAS: Model predicts negative changes {len(negative_predictions)/len(predictions)*100:.1f}% of the time")
    elif len(negative_predictions) > len(positive_predictions):
        print(f"  ⚠️  MODERATE NEGATIVE BIAS: Model slightly favors negative predictions")
    elif len(positive_predictions) > len(negative_predictions) * 2:
        print(f"  🚨 STRONG POSITIVE BIAS: Model predicts positive changes {len(positive_predictions)/len(predictions)*100:.1f}% of the time")
    else:
        print(f"  ✅ BALANCED: Model shows no strong directional bias")
    
    # Check for magnitude bias
    if avg_prediction < -0.5:
        print(f"  🚨 MAGNITUDE BIAS: Average prediction is {avg_prediction:.3f}% (consistently negative)")
    elif avg_prediction > 0.5:
        print(f"  🚨 MAGNITUDE BIAS: Average prediction is {avg_prediction:.3f}% (consistently positive)")
    else:
        print(f"  ✅ No significant magnitude bias (average: {avg_prediction:.3f}%)")
    
    # Check for consistency
    if std_prediction < 0.1:
        print(f"  ✅ Very consistent predictions (std dev: {std_prediction:.3f}%)")
    elif std_prediction < 0.5:
        print(f"  ⚠️  Moderate prediction variation (std dev: {std_prediction:.3f}%)")
    else:
        print(f"  🚨 High prediction variation (std dev: {std_prediction:.3f}%) - model may be unstable")
    
    # Show individual period results
    print(f"\n📋 Period-by-Period Results:")
    for result in period_results:
        bias_indicator = "🔴" if result['predicted_change'] < -0.5 else "🟢" if result['predicted_change'] > 0.5 else "🟡"
        print(f"   {bias_indicator} {result['period']}: {result['predicted_change']:.3f}% (raw: {result['raw_prediction']:.6f})")
    
    return {
        'avg_prediction': avg_prediction,
        'std_prediction': std_prediction,
        'negative_ratio': len(negative_predictions) / len(predictions),
        'has_bias': abs(avg_prediction) > 0.5 or len(negative_predictions) > len(positive_predictions) * 1.5
    }


async def diagnose_model_predictions(symbol: str = "Fartcoin", periods: int = 20):
    """Diagnose predictions for a specific symbol across different time periods"""
    
    print(f"\n🔍 Diagnosing predictions for {symbol} across {periods} time periods")
    print("=" * 80)
    
    # 0. Initialize registry with explicit models directory
    from pathlib import Path
    current_dir = Path(__file__).parent
    models_dir = current_dir / "models"
    print(f"🔍 Looking for models in: {models_dir.absolute()}")
    
    registry = get_model_registry()
    # Force re-initialization with correct path
    registry.models_dir = models_dir
    registry._initialize_registry()

    # 1. Check available models
    registry = get_model_registry()
    models = registry.list_models(symbol)
    
    if not models:
        print(f"❌ No models found for {symbol}")
        return
    
    # Find improved model
    improved_models = [m for m in models if "improved" in m.model_path.lower()]
    if improved_models:
        model_metadata = improved_models[0]
        print(f"✅ Found improved model: {model_metadata.model_path}")
    else:
        model_metadata = models[0]
        print(f"⚠️  No improved model found, using: {model_metadata.model_path}")
    
    print(f"   Version: {model_metadata.semantic_version or model_metadata.version}")
    print(f"   Sequence Length: {model_metadata.sequence_length}")
    
    # 2. Test scaler loading
    print(f"\n📊 Testing Scaler Loading...")
    data_processor = DataProcessor()
    
    # Try to load scalers
    model_version = model_metadata.semantic_version or model_metadata.version
    scalers_loaded = data_processor.load_scalers(symbol, model_version)
    
    if scalers_loaded:
        print(f"✅ Scalers loaded successfully")
        print(f"   Price scaler type: {type(data_processor.price_scaler).__name__}")
        print(f"   Feature scaler type: {type(data_processor.feature_scaler).__name__}")
    else:
        print(f"❌ Failed to load scalers - THIS IS THE PROBLEM!")
        
        # Check what scaler files exist
        scalers_dir = os.path.join(data_processor.data_dir, "scalers")
        print(f"\n   Checking scalers directory: {scalers_dir}")
        
        if os.path.exists(scalers_dir):
            scaler_files = [f for f in os.listdir(scalers_dir) if symbol in f and "improved" in f]
            if scaler_files:
                print(f"   Found {len(scaler_files)} scaler files:")
                for f in scaler_files[:5]:
                    print(f"     - {f}")
            else:
                print(f"   No scaler files found for {symbol} improved models")
    
    # 3. Query different time periods
    time_periods = await query_different_time_periods(symbol, periods)
    
    # 4. Check data availability for each time period
    await check_data_availability(symbol, time_periods)
    
    # 5. Test predictions across periods
    period_results = await test_predictions_across_periods(symbol, time_periods)
    
    # 6. Validate predictions with actual data
    validated_results = await validate_predictions_with_actual_data(symbol, period_results)
    
    # 7. Analyze prediction accuracy
    accuracy_analysis = await analyze_prediction_accuracy(validated_results)
    
    # 8. Analyze bias patterns
    bias_analysis = await analyze_bias_patterns(period_results)
    
    # 9. Provide conclusions and solutions
    print(f"\n💡 Conclusions & Solutions")
    print("=" * 60)
    
    if not scalers_loaded:
        print("🔧 PRIMARY ISSUE: Scalers not loaded")
        print(f"   Solution: Regenerate scalers for improved models")
        print(f"   Run: python regenerate_improved_scalers.py --symbol {symbol}")
    elif bias_analysis['has_bias']:
        print("🔧 MODEL BIAS DETECTED")
        print(f"   Average prediction: {bias_analysis['avg_prediction']:.3f}%")
        print(f"   Negative prediction ratio: {bias_analysis['negative_ratio']*100:.1f}%")
        
        if accuracy_analysis and accuracy_analysis['overall_accuracy'] > 70:
            print(f"   ✅ But predictions are accurate ({accuracy_analysis['overall_accuracy']:.1f}%)")
            print(f"   💡 Model is correctly predicting market direction")
            print(f"   💡 The negative bias reflects actual bearish market conditions")
        else:
            print(f"   ❌ Predictions are inaccurate ({accuracy_analysis['overall_accuracy']:.1f}% if available)")
            print(f"   💡 Model needs retraining with balanced data")
            print(f"   💡 The training data or loss function may be biased")
    else:
        print("✅ NO SIGNIFICANT ISSUES DETECTED")
        print(f"   Model shows balanced predictions across time periods")
        print(f"   Average prediction: {bias_analysis['avg_prediction']:.3f}%")
    
    print("\n" + "=" * 80)


async def test_all_improved_models():
    """Test all improved models for prediction bias across time periods"""
    
    # Get all available models
    registry = get_model_registry()
    all_models = registry.list_models()
    
    # Find unique symbols with improved models
    improved_symbols = set()
    for model in all_models:
        if "improved" in model.model_path.lower():
            improved_symbols.add(model.symbol)
    
    print(f"\n🔍 Found {len(improved_symbols)} symbols with improved models")
    
    # Test each symbol with fewer periods for efficiency
    biased_models = []
    for symbol in sorted(improved_symbols):
        print(f"\n{'='*80}")
        print(f"Testing {symbol} across time periods...")
        
        try:
            # Test with 3 periods for efficiency
            time_periods = await query_different_time_periods(symbol, 3)
            period_results = await test_predictions_across_periods(symbol, time_periods)
            bias_analysis = await analyze_bias_patterns(period_results)
            
            if bias_analysis['has_bias']:
                biased_models.append((symbol, bias_analysis['avg_prediction'], bias_analysis['negative_ratio']))
                print(f"⚠️  {symbol}: BIAS DETECTED (avg: {bias_analysis['avg_prediction']:.3f}%, neg ratio: {bias_analysis['negative_ratio']*100:.1f}%)")
            else:
                print(f"✅ {symbol}: No significant bias detected")
                
        except Exception as e:
            print(f"❌ {symbol}: Error - {e}")
    
    # Summary
    print(f"\n{'='*80}")
    print(f"SUMMARY: {len(biased_models)}/{len(improved_symbols)} models show bias")
    
    if biased_models:
        print("\nBiased Models (sorted by bias severity):")
        for symbol, avg_pred, neg_ratio in sorted(biased_models, key=lambda x: abs(x[1]), reverse=True):
            bias_type = "NEGATIVE" if avg_pred < 0 else "POSITIVE"
            print(f"  - {symbol}: {bias_type} bias ({avg_pred:.3f}% avg, {neg_ratio*100:.1f}% negative)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Diagnose prediction bias in improved models across time periods')
    parser.add_argument('--symbol', type=str, default='Fartcoin',
                        help='Symbol to diagnose (default: Fartcoin)')
    parser.add_argument('--periods', type=int, default=20,
                        help='Number of time periods to test (default: 20)')
    parser.add_argument('--test-all', action='store_true',
                        help='Test all improved models')
    
    args = parser.parse_args()
    
    if args.test_all:
        asyncio.run(test_all_improved_models())
    else:
        asyncio.run(diagnose_model_predictions(args.symbol, args.periods)) 