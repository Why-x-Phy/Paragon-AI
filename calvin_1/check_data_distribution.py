#!/usr/bin/env python3
"""
Check Data Distribution - Analyze FARTCOIN price movements over past 30 days
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from src.data.data_processor import DataProcessor

def analyze_data_distribution():
    """Analyze the actual distribution of price changes in training data"""
    
    print("🔍 Analyzing FARTCOIN data distribution (past 30 days)")
    print("=" * 60)
    
    # Initialize processor
    processor = DataProcessor()
    
    # Get FARTCOIN data
    token_address = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
    symbol = "FARTCOIN"
    
    try:
        # Fetch raw price data
        print("📊 Fetching raw price data...")
        df = processor.process_pipeline(
            token_address=token_address,
            symbol=symbol,
            resolution='1H',
            days=30,
            include_sentiment=True
        )
        
        if df.empty:
            print("❌ No data found!")
            return
        
        print(f"✅ Got {len(df)} hourly data points")
        print(f"📅 Date range: {df.index[0]} to {df.index[-1]}")
        
        # Calculate percentage changes
        df['pct_change'] = df['close'].pct_change()
        df['pct_change_next'] = df['close'].pct_change().shift(-1)  # Next hour change (what we predict)
        
        # Remove NaN values
        valid_changes = df['pct_change_next'].dropna()
        
        print(f"\n📈 Raw Price Movement Analysis:")
        print(f"   Total price changes: {len(valid_changes)}")
        print(f"   Positive changes: {(valid_changes > 0).sum()} ({(valid_changes > 0).mean()*100:.1f}%)")
        print(f"   Negative changes: {(valid_changes < 0).sum()} ({(valid_changes < 0).mean()*100:.1f}%)")
        print(f"   Zero changes: {(valid_changes == 0).sum()} ({(valid_changes == 0).mean()*100:.1f}%)")
        
        print(f"\n📊 Price Change Statistics:")
        print(f"   Mean: {valid_changes.mean()*100:.3f}%")
        print(f"   Std: {valid_changes.std()*100:.3f}%")
        print(f"   Min: {valid_changes.min()*100:.3f}%")
        print(f"   Max: {valid_changes.max()*100:.3f}%")
        print(f"   Median: {valid_changes.median()*100:.3f}%")
        
        # Check for extreme movements
        large_moves = valid_changes[abs(valid_changes) > 0.1]  # >10% moves
        print(f"\n🚀 Large Movements (>10%):")
        print(f"   Count: {len(large_moves)}")
        if len(large_moves) > 0:
            print(f"   Largest gain: {large_moves.max()*100:.1f}%")
            print(f"   Largest loss: {large_moves.min()*100:.1f}%")
        
        # Analyze actual training targets
        print(f"\n🎯 Training Target Analysis:")
        try:
            # Prepare ML data to see what the model actually sees
            X_train, X_val, y_train, y_val, feature_columns = processor.prepare_ml_data(
                df=df,
                sequence_length=24,
                test_size=0.2
            )
            
            # Combine all targets
            all_targets = np.concatenate([y_train, y_val])
            
            print(f"   Total training targets: {len(all_targets)}")
            print(f"   Positive targets: {(all_targets > 0).sum()} ({(all_targets > 0).mean()*100:.1f}%)")
            print(f"   Negative targets: {(all_targets < 0).sum()} ({(all_targets < 0).mean()*100:.1f}%)")
            print(f"   Zero targets: {(all_targets == 0).sum()} ({(all_targets == 0).mean()*100:.1f}%)")
            
            print(f"\n📊 Scaled Target Statistics:")
            print(f"   Mean: {all_targets.mean():.6f}")
            print(f"   Std: {all_targets.std():.6f}")
            print(f"   Min: {all_targets.min():.6f}")
            print(f"   Max: {all_targets.max():.6f}")
            print(f"   Range: [{all_targets.min():.3f}, {all_targets.max():.3f}]")
            
            # Check if scaling is working properly
            print(f"\n🔧 Scaler Analysis:")
            print(f"   Scaler type: {type(processor.price_scaler).__name__}")
            if hasattr(processor.price_scaler, 'feature_range'):
                print(f"   Feature range: {processor.price_scaler.feature_range}")
            
            # Show some actual vs scaled examples
            print(f"\n📋 Sample Transformations:")
            raw_sample = valid_changes.iloc[:10].values
            scaled_sample = processor.price_scaler.transform(raw_sample.reshape(-1, 1)).flatten()
            
            for i in range(min(10, len(raw_sample))):
                print(f"   Raw: {raw_sample[i]*100:+6.2f}% → Scaled: {scaled_sample[i]:+7.4f}")
            
        except Exception as e:
            print(f"❌ Error analyzing training targets: {e}")
        
        # Price trend analysis
        print(f"\n📈 Price Trend Analysis:")
        start_price = df['close'].iloc[0]
        end_price = df['close'].iloc[-1]
        total_return = (end_price - start_price) / start_price
        print(f"   Start price: ${start_price:.6f}")
        print(f"   End price: ${end_price:.6f}")
        print(f"   Total return: {total_return*100:+.2f}%")
        
        # Daily returns
        daily_returns = df['close'].resample('1D').last().pct_change().dropna()
        print(f"   Daily positive days: {(daily_returns > 0).sum()}/{len(daily_returns)} ({(daily_returns > 0).mean()*100:.1f}%)")
        
        # Create a simple plot
        plt.figure(figsize=(12, 8))
        
        plt.subplot(2, 2, 1)
        plt.plot(df.index, df['close'])
        plt.title('FARTCOIN Price (30 days)')
        plt.ylabel('Price ($)')
        
        plt.subplot(2, 2, 2)
        plt.hist(valid_changes * 100, bins=50, alpha=0.7, edgecolor='black')
        plt.title('Distribution of Hourly Returns')
        plt.xlabel('Return (%)')
        plt.ylabel('Frequency')
        plt.axvline(0, color='red', linestyle='--', alpha=0.7)
        
        if 'all_targets' in locals():
            plt.subplot(2, 2, 3)
            plt.hist(all_targets, bins=50, alpha=0.7, edgecolor='black')
            plt.title('Distribution of Scaled Training Targets')
            plt.xlabel('Scaled Value')
            plt.ylabel('Frequency')
            plt.axvline(0, color='red', linestyle='--', alpha=0.7)
        
        plt.subplot(2, 2, 4)
        plt.plot(df.index[1:], valid_changes.cumsum() * 100)
        plt.title('Cumulative Returns')
        plt.ylabel('Cumulative Return (%)')
        plt.axhline(0, color='red', linestyle='--', alpha=0.7)
        
        plt.tight_layout()
        plt.savefig('fartcoin_data_analysis.png', dpi=150, bbox_inches='tight')
        print(f"\n💾 Saved analysis plot to: fartcoin_data_analysis.png")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_data_distribution() 