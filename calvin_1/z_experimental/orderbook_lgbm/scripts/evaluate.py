#!/usr/bin/env python3
"""
Evaluate trained LightGBM model for Orderbook prediction

Loads model and test data, computes metrics, and saves predictions.
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ..config import get_config, validate_config
from ..eval import get_evaluator
from ..utils import setup_logging

def main():
    parser = argparse.ArgumentParser(description='Evaluate LightGBM model for orderbook prediction')

    # Required arguments
    parser.add_argument('--features-path', type=str, required=True,
                       help='Path to test features parquet file')
    parser.add_argument('--target-path', type=str, required=True,
                       help='Path to test target parquet file')
    parser.add_argument('--model-path', type=str, required=True,
                       help='Path to trained model file')

    # Optional arguments
    parser.add_argument('--predictions-path', type=str,
                       help='Path to save predictions CSV (default: data_cache/predictions.csv)')
    parser.add_argument('--no-save-predictions', action='store_true',
                       help='Skip saving predictions to CSV')
    parser.add_argument('--analysis-dir', type=str,
                       help='Directory to save analysis files (default: data_cache/)')

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

    print("🚀 Evaluating LightGBM model for Orderbook prediction")
    print(f"🤖 Model: {args.model_path}")
    print(f"📂 Features: {args.features_path}")
    print(f"🎯 Target: {args.target_path}")

    # Validate input files
    model_path = Path(args.model_path)
    features_path = Path(args.features_path)
    target_path = Path(args.target_path)

    if not model_path.exists():
        print(f"❌ Model file not found: {model_path}")
        sys.exit(1)

    if not features_path.exists():
        print(f"❌ Features file not found: {features_path}")
        sys.exit(1)

    if not target_path.exists():
        print(f"❌ Target file not found: {target_path}")
        sys.exit(1)

    try:
        # Load test data
        print("📡 Loading test data...")
        import pandas as pd

        X_test = pd.read_parquet(features_path)
        y_test = pd.read_parquet(target_path)['target']

        print(f"📊 Loaded {len(X_test)} test samples with {X_test.shape[1]} features")

        # Load and evaluate model
        print("🔍 Evaluating model...")
        evaluator = get_evaluator()
        evaluator.load_model(model_path)

        # Determine target type from model metadata (no forcing)
        target_type = 'regression'  # default
        meta_path = model_path.parent / 'meta.json'
        if meta_path.exists():
            import json
            try:
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                    if 'target_type' in meta:
                        target_type = meta['target_type']
                    elif meta.get('objective') == 'multiclass':
                        target_type = 'classification'
                    elif meta.get('objective') == 'binary':
                        target_type = 'binary'
                    print(f"📋 Detected target type from metadata: {target_type}")
            except Exception as e:
                print(f"⚠️  Could not read metadata: {e}")

        # Load optimal threshold for binary if present
        optimal_threshold = None
        if target_type == 'binary' and meta_path.exists():
            try:
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                    optimal_threshold = meta.get('optimal_threshold')
            except Exception:
                pass

        evaluation_results = evaluator.evaluate_model(
            X_test,
            y_test,
            save_predictions=not args.no_save_predictions,
            predictions_path=Path(args.predictions_path) if args.predictions_path else None,
            target_type=target_type,
            threshold=optimal_threshold
        )

        # The evaluate_model method already prints the summary
        # Now save additional analysis if requested
        if args.analysis_dir:
            analysis_dir = Path(args.analysis_dir)
        else:
            analysis_dir = config.data_cache_dir

        analysis_dir.mkdir(exist_ok=True)

        print(f"\n📊 Generating detailed analysis in {analysis_dir}...")
        analysis_files = evaluator.create_predictions_analysis(
            evaluation_results['predictions'],
            analysis_dir
        )

        print("📁 Analysis files created:")
        for analysis_type, file_path in analysis_files.items():
            print(f"  • {analysis_type}: {file_path}")

        # Save evaluation summary
        eval_summary = {
            'model_path': str(model_path),
            'features_path': str(features_path),
            'target_path': str(target_path),
            'test_samples': len(X_test),
            'predictions_path': evaluation_results.get('predictions_path'),
            'metrics': evaluation_results['metrics'],
            'analysis_files': {k: str(v) for k, v in analysis_files.items()}
        }

        from ..utils import save_json
        summary_path = analysis_dir / 'evaluation_summary.json'
        save_json(eval_summary, summary_path)
        print(f"✅ Evaluation summary saved to: {summary_path}")

        print("\n🎉 Evaluation complete!")

        # Quick interpretation guide
        metrics = evaluation_results['metrics']
        if 'r2' in metrics:
            r2 = metrics['r2']
            directional_acc = metrics.get('directional_accuracy', metrics.get('accuracy', 0))
        else:
            r2 = 0
            directional_acc = metrics.get('accuracy', 0)

        print("\n💡 Quick Interpretation:")
        if r2 > 0.1:
            print("📈 Model shows predictive power (R² > 0.1)")
        elif r2 > 0:
            print("🤔 Model shows weak predictive power (R² > 0)")
        else:
            print("📉 Model performs worse than baseline (R² < 0)")

        if directional_acc > 0.55:
            print("🎯 Good directional accuracy (>55%)")
        elif directional_acc > 0.5:
            print("🤷 Moderate directional accuracy (50-55%)")
        else:
            print("❌ Poor directional accuracy (<50%)")

    except Exception as e:
        print(f"❌ Error during evaluation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
