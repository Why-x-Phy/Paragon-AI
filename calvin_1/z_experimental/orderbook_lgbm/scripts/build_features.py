#!/usr/bin/env python3
"""
Build features and target for Orderbook LGBM model

Loads raw orderbook and candle data from database, creates features and target,
and saves to cache files for training.
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ..config import get_config, validate_config
from ..data_loader import get_data_loader
from ..features import get_feature_engineer, make_features, validate_features
from ..utils import setup_logging, save_json

def main():
    parser = argparse.ArgumentParser(description='Build features for Orderbook LGBM model')

    # Data parameters
    parser.add_argument('--symbol', type=str, default='SOL',
                       help='Token symbol to build features for')
    parser.add_argument('--timeframe', type=str, default='1m',
                       help='Candle timeframe (1m, 5m, 1h, etc.)')
    parser.add_argument('--start', type=str, required=True,
                       help='Start timestamp (ISO format: 2024-01-01)')
    parser.add_argument('--end', type=str, required=True,
                       help='End timestamp (ISO format: 2024-12-01)')

    # Target parameters
    parser.add_argument('--target-type', type=str, default='regression', choices=['regression', 'classification'],
                       help='Target type: regression for raw returns, classification for direction')
    parser.add_argument('--horizon', type=int, default=1,
                       help='Prediction horizon in bars (e.g., 3 = 3 bars ahead)')
    parser.add_argument('--neutral-mode', type=str, default='vol', choices=['vol', 'percentile', 'fixed'],
                       help='Neutral band type for classification labels')
    parser.add_argument('--neutral-value', type=float, default=0.15,
                       help='Neutral band parameter: vol=multiplier of rolling std; percentile=quantile 0-1; fixed=bps')

    # Feature parameters
    parser.add_argument('--levels', type=int, default=1,
                       help='Orderbook levels to use (1 or 5)')
    parser.add_argument('--include-momentum', action='store_true', default=True,
                       help='Include momentum features (multiple lag returns, rolling stats)')
    parser.add_argument('--include-spread-momentum', action='store_true', default=True,
                       help='Include spread momentum features')
    parser.add_argument('--include-microstructure-momentum', action='store_true', default=True,
                       help='Include microstructure momentum features')
    parser.add_argument('--include-time-features', action='store_true', default=True,
                       help='Include time-based features (hour of day, etc.)')
    parser.add_argument('--include-advanced-features', action='store_true', default=True,
                       help='Include advanced features (pressure indicators, etc.)')
    parser.add_argument('--drop-price-level', action='store_true', default=True,
                       help='Drop raw price-level features (e.g., mid_price, rolling means)')

    # Output parameters
    parser.add_argument('--features-path', type=str,
                       help='Path to save features (default: data_cache/features.parquet)')
    parser.add_argument('--target-path', type=str,
                       help='Path to save target (default: data_cache/target.parquet)')
    parser.add_argument('--overwrite', action='store_true',
                       help='Overwrite existing cache files')

    # Logging
    parser.add_argument('--log-level', type=str, default='INFO',
                       help='Logging level (DEBUG, INFO, WARNING, ERROR)')

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    config = get_config()

    # Validate configuration
    if not validate_config():
        sys.exit(1)

    print("🚀 Building features for Orderbook LGBM model")
    print(f"📊 Symbol: {args.symbol}")
    print(f"⏰ Timeframe: {args.timeframe}")
    print(f"📅 Period: {args.start} to {args.end}")
    print(f"📈 Orderbook levels: {args.levels}")
    print(f"🎯 Target type: {args.target_type}")
    print(f"🧠 Features: momentum={args.include_momentum}, spread_momentum={args.include_spread_momentum}, microstructure={args.include_microstructure_momentum}, time={args.include_time_features}, advanced={args.include_advanced_features}")

    # Set output paths
    features_path = Path(args.features_path) if args.features_path else config.data_cache_dir / 'features.parquet'
    target_path = Path(args.target_path) if args.target_path else config.data_cache_dir / 'target.parquet'

    # Check if files exist
    if not args.overwrite and features_path.exists() and target_path.exists():
        print(f"✅ Cache files already exist: {features_path}, {target_path}")
        print("💡 Use --overwrite to rebuild")
        return

    try:
        # Load raw data
        print("📡 Loading data from database...")
        loader = get_data_loader()

        candles_df, orderbook_df = loader.load_combined_data(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start_ts=args.start,
            end_ts=args.end
        )

        if candles_df.empty:
            print(f"❌ No candle data found for {args.symbol} {args.timeframe}")
            sys.exit(1)

        if orderbook_df.empty:
            print(f"❌ No orderbook data found for {args.symbol}")
            sys.exit(1)

        print(f"📊 Loaded {len(candles_df)} candles and {len(orderbook_df)} orderbook snapshots")

        # Build features
        print("🔧 Building features and target...")
        feature_params = {
            'levels': args.levels,
            'include_momentum': args.include_momentum,
            'include_spread_momentum': args.include_spread_momentum,
            'include_microstructure_momentum': args.include_microstructure_momentum,
            'include_time_features': args.include_time_features,
            'include_advanced_features': args.include_advanced_features,
            'horizon': args.horizon,
            'neutral_mode': args.neutral_mode,
            'neutral_value': args.neutral_value,
            'drop_price_level': args.drop_price_level
        }

        X, y = make_features(candles_df, orderbook_df, feature_params, args.target_type)

        if X.empty or y.empty:
            print("❌ No valid features/target generated")
            sys.exit(1)

        # Validate features
        validation = validate_features(X, y)
        if not validation['valid']:
            print("❌ Feature validation failed:")
            for error in validation['errors']:
                print(f"  - {error}")
            sys.exit(1)

        if validation['warnings']:
            print("⚠️  Feature validation warnings:")
            for warning in validation['warnings']:
                print(f"  - {warning}")

        print("✅ Features built successfully!")
        print(f"📏 Dataset: {len(X)} samples, {X.shape[1]} features")
        print(".4f")
        print(".4f")
        print(".4f")

        # Save to cache
        print("💾 Saving to cache...")
        X.to_parquet(features_path)
        y.to_frame('target').to_parquet(target_path)

        print(f"✅ Features saved to: {features_path}")
        print(f"✅ Target saved to: {target_path}")

        # Save metadata
        metadata = {
            'symbol': args.symbol,
            'timeframe': args.timeframe,
            'start_ts': args.start,
            'end_ts': args.end,
            'target_type': args.target_type,
            'levels': args.levels,
            'feature_config': {
                'include_momentum': args.include_momentum,
                'include_spread_momentum': args.include_spread_momentum,
                'include_microstructure_momentum': args.include_microstructure_momentum,
                'include_time_features': args.include_time_features,
                'include_advanced_features': args.include_advanced_features
            },
            'n_samples': len(X),
            'n_features': X.shape[1],
            'feature_names': list(X.columns),
            'target_stats': {
                'mean': float(y.mean()),
                'std': float(y.std()),
                'min': float(y.min()),
                'max': float(y.max())
            },
            'validation': validation
        }

        metadata_path = config.data_cache_dir / 'features_metadata.json'
        save_json(metadata, metadata_path)
        print(f"✅ Metadata saved to: {metadata_path}")

        print("\n🎉 Feature building complete!")
        print(f"🚀 Ready for training: python -m orderbook_lgbm.scripts.train_lgbm --features-path {features_path} --target-path {target_path}")

    except Exception as e:
        print(f"❌ Error building features: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
