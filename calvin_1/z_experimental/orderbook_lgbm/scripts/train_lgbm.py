#!/usr/bin/env python3
"""
Train LightGBM model for Orderbook-based price prediction

Loads features and target, trains model with time-based split, and saves artifacts.
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ..config import get_config, validate_config
from ..trainer import get_trainer, create_time_based_split
from ..utils import setup_logging, save_json, load_json

def main():
    parser = argparse.ArgumentParser(description='Train LightGBM model for orderbook prediction')

    # Data paths
    parser.add_argument('--features-path', type=str, required=True,
                       help='Path to features parquet file')
    parser.add_argument('--target-path', type=str, required=True,
                       help='Path to target parquet file')
    parser.add_argument('--target-type', type=str, default='regression', choices=['regression', 'classification', 'binary'],
                       help='Target type used during feature building')
    parser.add_argument('--directional-only', action='store_true',
                       help='Train binary model on movers only (-1 vs +1), filter neutrals (0)')

    # Training parameters
    parser.add_argument('--train-ratio', type=float, default=0.8,
                       help='Ratio of data for training (0-1)')
    parser.add_argument('--seed', type=int, default=42,
                       help='Random seed for reproducibility')

    # LightGBM parameters
    parser.add_argument('--learning-rate', type=float, default=0.05,
                       help='Learning rate')
    parser.add_argument('--num-leaves', type=int, default=64,
                       help='Number of leaves in each tree')
    parser.add_argument('--feature-fraction', type=float, default=0.9,
                       help='Feature fraction for bagging')
    parser.add_argument('--bagging-fraction', type=float, default=0.8,
                       help='Bagging fraction')
    parser.add_argument('--bagging-freq', type=int, default=1,
                       help='Bagging frequency')
    parser.add_argument('--min-data-in-leaf', type=int, default=50,
                       help='Minimum data in leaf')
    parser.add_argument('--n-estimators', type=int, default=2000,
                       help='Number of boosting iterations')
    parser.add_argument('--early-stopping-rounds', type=int, default=100,
                       help='Early stopping rounds')

    # Output paths
    parser.add_argument('--model-path', type=str,
                       help='Path to save model (default: models/lgbm_model.txt)')
    parser.add_argument('--meta-path', type=str,
                       help='Path to save metadata (default: models/meta.json)')

    # Feature selection
    parser.add_argument('--feature-selection', action='store_true',
                       help='Perform automatic feature selection before training')

    # Logging
    parser.add_argument('--log-level', type=str, default='INFO',
                       help='Logging level (DEBUG, INFO, WARNING, ERROR)')
    parser.add_argument('--verbose', action='store_true',
                       help='Verbose training output')

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    config = get_config()

    # Validate configuration
    if not validate_config():
        sys.exit(1)

    print("🚀 Training LightGBM model for Orderbook prediction")
    print(f"📂 Features: {args.features_path}")
    print(f"🎯 Target: {args.target_path} (type: {args.target_type})")
    print(f"📊 Train ratio: {args.train_ratio}")
    print(f"🌱 Seed: {args.seed}")

    # Load data
    try:
        print("📡 Loading features and target...")
        features_path = Path(args.features_path)
        target_path = Path(args.target_path)

        if not features_path.exists():
            print(f"❌ Features file not found: {features_path}")
            sys.exit(1)

        if not target_path.exists():
            print(f"❌ Target file not found: {target_path}")
            sys.exit(1)

        import pandas as pd
        X = pd.read_parquet(features_path)
        y = pd.read_parquet(target_path)['target']

        print(f"📊 Loaded {len(X)} samples with {X.shape[1]} features")

        # Load metadata if available
        metadata_path = config.data_cache_dir / 'features_metadata.json'
        metadata = None
        if metadata_path.exists():
            metadata = load_json(metadata_path)
            target_type_from_meta = metadata.get('target_type', 'regression')
            # Override command line arg if metadata specifies different target type
            if target_type_from_meta != args.target_type:
                print(f"⚠️  Overriding target type from metadata: {args.target_type} -> {target_type_from_meta}")
                args.target_type = target_type_from_meta
            print(f"📋 Loaded metadata: {metadata.get('symbol', 'unknown')} {metadata.get('timeframe', 'unknown')}, target={args.target_type}")

    except Exception as e:
        print(f"❌ Error loading data: {e}")
        sys.exit(1)

    try:
        # Create time-based split
        print("✂️  Creating time-based train/validation split...")
        X_train, y_train, X_valid, y_valid = create_time_based_split(X, y, args.train_ratio)

        print(f"📈 Train set: {len(X_train)} samples ({X_train.index[0]} to {X_train.index[-1]})")
        print(f"📉 Valid set: {len(X_valid)} samples ({X_valid.index[0]} to {X_valid.index[-1]})")

        # Override target type for directional-only
        if args.directional_only:
            args.target_type = 'binary'

        # Prepare model parameters
        model_params = {
            'learning_rate': args.learning_rate,
            'num_leaves': args.num_leaves,
            'feature_fraction': args.feature_fraction,
            'bagging_fraction': args.bagging_fraction,
            'bagging_freq': args.bagging_freq,
            'min_data_in_leaf': args.min_data_in_leaf,
            'n_estimators': args.n_estimators,
            'early_stopping_rounds': args.early_stopping_rounds,
            'random_state': args.seed,
            'verbosity': 1 if args.verbose else -1
        }

        print("🤖 Training LightGBM model...")
        print(f"⚙️  Parameters: learning_rate={args.learning_rate}, num_leaves={args.num_leaves}, n_estimators={args.n_estimators}")

        # Train model
        trainer = get_trainer()
        model, eval_metrics = trainer.train_lgbm(
            X_train, y_train, X_valid, y_valid, model_params, args.feature_selection, args.target_type
        )

        # Display results
        print("\n📊 Training Results:")
        print("=" * 50)

        target_type = eval_metrics.get('target_type', 'regression')

        if target_type == 'classification':
            print("Train Metrics:")
            print(f"  Accuracy: {eval_metrics['train']['accuracy']:.4f}")
            print(f"  Up Accuracy: {eval_metrics['train']['up_accuracy']:.4f}")
            print(f"  Down Accuracy: {eval_metrics['train']['down_accuracy']:.4f}")
            print(f"  F1 Score: {eval_metrics['train']['f1']:.4f}")

            print("Validation Metrics:")
            print(f"  Accuracy: {eval_metrics['valid']['accuracy']:.4f}")
            print(f"  Up Accuracy: {eval_metrics['valid']['up_accuracy']:.4f}")
            print(f"  Down Accuracy: {eval_metrics['valid']['down_accuracy']:.4f}")
            print(f"  F1 Score: {eval_metrics['valid']['f1']:.4f}")

            print(f"🏆 Best iteration: {eval_metrics['best_iteration']}")
            print(f"📈 Final accuracy: {eval_metrics['valid']['accuracy']:.4f}")
        elif target_type == 'binary':
            print("Train Metrics:")
            print(f"  Accuracy: {eval_metrics['train']['accuracy']:.4f}")
            print(f"  Precision: {eval_metrics['train']['precision']:.4f}")
            print(f"  Recall: {eval_metrics['train']['recall']:.4f}")
            print(f"  F1: {eval_metrics['train']['f1']:.4f}")

            print("Validation Metrics:")
            print(f"  Accuracy: {eval_metrics['valid']['accuracy']:.4f}")
            print(f"  Precision: {eval_metrics['valid']['precision']:.4f}")
            print(f"  Recall: {eval_metrics['valid']['recall']:.4f}")
            print(f"  F1: {eval_metrics['valid']['f1']:.4f}")

            print(f"🏆 Best iteration: {eval_metrics['best_iteration']}")
            print(f"📈 Final accuracy: {eval_metrics['valid']['accuracy']:.4f}")
        else:
            print("Train Metrics:")
            print(f"  RMSE: {eval_metrics['train']['rmse']:.4f}")
            print(f"  MAE: {eval_metrics['train']['mae']:.4f}")
            print(f"  R²: {eval_metrics['train']['r2']:.4f}")
            print(f"  Directional Acc: {eval_metrics['train']['directional_accuracy']:.4f}")

            print("Validation Metrics:")
            print(f"  RMSE: {eval_metrics['valid']['rmse']:.4f}")
            print(f"  MAE: {eval_metrics['valid']['mae']:.4f}")
            print(f"  R²: {eval_metrics['valid']['r2']:.4f}")
            print(f"  Directional Acc: {eval_metrics['valid']['directional_accuracy']:.4f}")

            print(f"🏆 Best iteration: {eval_metrics['best_iteration']}")
            print(f"📈 Final R² score: {eval_metrics['valid']['r2']:.4f}")

        # Save model and artifacts
        print("\n💾 Saving model and artifacts...")

        model_path = Path(args.model_path) if args.model_path else None
        meta_path = Path(args.meta_path) if args.meta_path else None

        saved_model_path, saved_meta_path = trainer.save_model(model_path, meta_path)
        feature_importance_path = trainer.save_feature_importance_csv()

        print(f"✅ Model saved to: {saved_model_path}")
        print(f"✅ Metadata saved to: {saved_meta_path}")
        print(f"✅ Feature importance saved to: {feature_importance_path}")

        # Save training summary
        training_summary = {
            'timestamp': pd.Timestamp.now().isoformat(),
            'data_info': {
                'features_path': str(features_path),
                'target_path': str(target_path),
                'n_samples': len(X),
                'n_features': X.shape[1],
                'train_samples': len(X_train),
                'valid_samples': len(X_valid),
                'train_period': [X_train.index[0].isoformat(), X_train.index[-1].isoformat()],
                'valid_period': [X_valid.index[0].isoformat(), X_valid.index[-1].isoformat()]
            },
            'model_params': model_params,
            'eval_metrics': eval_metrics,
            'feature_importance_top10': dict(
                sorted(eval_metrics['feature_importance'].items(),
                      key=lambda x: x[1], reverse=True)[:10]
            )
        }

        summary_path = config.data_cache_dir / 'training_summary.json'
        save_json(training_summary, summary_path)
        print(f"✅ Training summary saved to: {summary_path}")

        print("\n🎉 Training complete!")
        print(f"🚀 Ready for evaluation: python -m orderbook_lgbm.scripts.evaluate --features-path {args.features_path} --target-path {args.target_path} --model-path {saved_model_path}")

        # Show top features
        if eval_metrics['feature_importance']:
            print("\n🔍 Top 5 Features by Importance:")
            sorted_features = sorted(eval_metrics['feature_importance'].items(),
                                   key=lambda x: x[1], reverse=True)
            for i, (feature, importance) in enumerate(sorted_features[:5]):
                print(f"{feature}: {importance:.4f}")

    except Exception as e:
        print(f"❌ Error during training: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
