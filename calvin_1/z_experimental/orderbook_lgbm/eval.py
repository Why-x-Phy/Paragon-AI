"""
Model evaluation for Orderbook LGBM predictions

Computes comprehensive metrics and saves predictions for analysis.
"""

import lightgbm as lgb
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import json
import logging
from datetime import datetime

from .config import get_config

logger = logging.getLogger(__name__)

class ModelEvaluator:
    """Evaluates trained LightGBM model performance"""

    def __init__(self, model_path: Optional[Path] = None):
        self.config = get_config()
        self.model = None
        self.model_path = model_path or self.config.models_dir / 'lgbm_model.txt'

        # Load model if path exists
        if self.model_path.exists():
            self.load_model(self.model_path)

    def load_model(self, model_path: Path) -> lgb.Booster:
        """
        Load trained LightGBM model

        Args:
            model_path: Path to model file

        Returns:
            Loaded model
        """
        self.model = lgb.Booster(model_file=str(model_path))
        self.model_path = model_path
        logger.info(f"Loaded model from {model_path}")
        return self.model

    def evaluate_model(self,
                      X: pd.DataFrame,
                      y: pd.Series,
                      save_predictions: bool = True,
                      predictions_path: Optional[Path] = None,
                      target_type: str = 'regression',
                      threshold: Optional[float] = None) -> Dict[str, Any]:
        """
        Evaluate model on test data

        Args:
            X: Test features
            y: Test target
            save_predictions: Whether to save predictions to CSV
            predictions_path: Path to save predictions CSV

        Returns:
            Dictionary with evaluation metrics and predictions
        """
        if self.model is None:
            raise ValueError("No model loaded. Call load_model() first.")

        # Make predictions
        raw_pred = self.model.predict(X.values, num_iteration=self.model.best_iteration)

        # Handle classification predictions
        if target_type == 'classification':
            # For multiclass, raw_pred is (n_samples, n_classes) probabilities
            # Convert to class predictions
            if len(raw_pred.shape) > 1:
                y_pred = raw_pred.argmax(axis=1)
            else:
                y_pred = raw_pred

            # Remap back to original labels (-1, 0, 1)
            reverse_mapping = {0: -1, 1: 0, 2: 1}
            y_pred = pd.Series(y_pred).map(reverse_mapping).values
        elif target_type == 'binary':
            # raw_pred are probabilities of class 1
            thr = 0.5 if threshold is None else float(threshold)
            y_pred = (raw_pred >= thr).astype(int)
        else:
            # Regression predictions are already 1D
            y_pred = raw_pred

        # Calculate metrics
        metrics = self.calculate_metrics(y.values, y_pred, target_type)

        # Create predictions DataFrame
        predictions_df = pd.DataFrame({
            'timestamp': X.index,
            'y_true': y.values,
            'y_pred': y_pred,
            'error': y.values - y_pred,
            'abs_error': np.abs(y.values - y_pred)
        })

        # Add directional predictions
        predictions_df['direction_true'] = np.sign(predictions_df['y_true'])
        predictions_df['direction_pred'] = np.sign(predictions_df['y_pred'])
        predictions_df['direction_correct'] = (predictions_df['direction_true'] == predictions_df['direction_pred']).astype(int)

        # Add additional analysis columns
        predictions_df['y_true_pct'] = predictions_df['y_true'] * 100  # Convert to percentage
        predictions_df['y_pred_pct'] = predictions_df['y_pred'] * 100
        predictions_df['large_move_true'] = (predictions_df['y_true'].abs() > 0.01).astype(int)  # >1% moves
        predictions_df['large_move_pred'] = (predictions_df['y_pred'].abs() > 0.01).astype(int)

        # Save predictions if requested
        if save_predictions:
            predictions_path = predictions_path or self.config.data_cache_dir / 'predictions.csv'
            predictions_path.parent.mkdir(exist_ok=True)
            predictions_df.to_csv(predictions_path, index=False)
            logger.info(f"Predictions saved to {predictions_path}")

        # Add predictions summary to metrics
        metrics['predictions'] = {
            'n_samples': len(predictions_df),
            'large_moves_true': int(predictions_df['large_move_true'].sum()),
            'large_moves_pred': int(predictions_df['large_move_pred'].sum()),
            'avg_true_move_pct': float(predictions_df['y_true_pct'].abs().mean()),
            'avg_pred_move_pct': float(predictions_df['y_pred_pct'].abs().mean())
        }

        # Print summary
        self._print_evaluation_summary(metrics, predictions_df)

        return {
            'metrics': metrics,
            'predictions': predictions_df,
            'predictions_path': str(predictions_path) if save_predictions else None
        }

    def calculate_metrics(self, y_true: np.ndarray, y_pred: np.ndarray, target_type: str = 'regression') -> Dict[str, float]:
        """
        Calculate comprehensive evaluation metrics

        Args:
            y_true: True target values
            y_pred: Predicted values
            target_type: 'regression' or 'classification'

        Returns:
            Dictionary of metrics
        """
        if target_type == 'classification':
            # Classification metrics
            from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix

            accuracy = accuracy_score(y_true, y_pred)

            # Calculate per-class metrics (weighted average)
            precision = precision_score(y_true, y_pred, average='weighted', zero_division=0)
            recall = recall_score(y_true, y_pred, average='weighted', zero_division=0)
            f1 = f1_score(y_true, y_pred, average='weighted', zero_division=0)

            # Confusion matrix elements
            cm = confusion_matrix(y_true, y_pred)
            if cm.shape == (3, 3):  # 3-class classification
                tn_down = cm[0, 0]  # True negative for down (-1)
                fp_down = cm[1, 0] + cm[2, 0]  # False positive for down
                fn_down = cm[0, 1] + cm[0, 2]  # False negative for down
                tp_down = cm[0, 0]  # True positive for down

                tn_up = cm[2, 2]  # True negative for up (1)
                fp_up = cm[0, 2] + cm[1, 2]  # False positive for up
                fn_up = cm[2, 0] + cm[2, 1]  # False negative for up
                tp_up = cm[2, 2]  # True positive for up

                up_accuracy = tp_up / (tp_up + fn_up) if (tp_up + fn_up) > 0 else 0
                down_accuracy = tp_down / (tp_down + fn_down) if (tp_down + fn_down) > 0 else 0
            else:
                up_accuracy = down_accuracy = 0

            return {
                'accuracy': float(accuracy),
                'up_accuracy': float(up_accuracy),
                'down_accuracy': float(down_accuracy),
                'precision': float(precision),
                'recall': float(recall),
                'f1': float(f1),
                'target_type': target_type
            }

        else:
            # Regression metrics
            mse = np.mean((y_true - y_pred) ** 2)
            rmse = np.sqrt(mse)
            mae = np.mean(np.abs(y_true - y_pred))

            # R-squared
            ss_res = np.sum((y_true - y_pred) ** 2)
            ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
            r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

            # Directional accuracy (sign prediction)
            true_direction = np.sign(y_true)
            pred_direction = np.sign(y_pred)
            directional_accuracy = np.mean(true_direction == pred_direction)

            # Additional metrics
            mape = np.mean(np.abs((y_true - y_pred) / (y_true + 1e-9)))  # Avoid division by zero

            # Quantile-based metrics
            errors = y_true - y_pred
            q75_error = np.percentile(np.abs(errors), 75)
            q95_error = np.percentile(np.abs(errors), 95)

            # Sharpe-like ratio for predictions
            pred_std = np.std(y_pred)
            pred_sharpness = np.mean(np.abs(y_pred)) / (pred_std + 1e-9)

            return {
                'mse': float(mse),
                'rmse': float(rmse),
                'mae': float(mae),
                'r2': float(r2),
                'directional_accuracy': float(directional_accuracy),
                'mape': float(mape),
                'q75_abs_error': float(q75_error),
                'q95_abs_error': float(q95_error),
                'prediction_sharpness': float(pred_sharpness),
                'mean_prediction': float(np.mean(y_pred)),
            'std_prediction': float(np.std(y_pred)),
            'mean_true': float(np.mean(y_true)),
            'std_true': float(np.std(y_true))
        }

    def _print_evaluation_summary(self, metrics: Dict[str, Any], predictions_df: pd.DataFrame):
        """
        Print formatted evaluation summary
        """
        print("\n" + "="*60)
        print("MODEL EVALUATION SUMMARY")
        print("="*60)

        target_type = metrics.get('target_type', 'regression')

        if target_type == 'classification':
            print("\nClassification Metrics:")
            print(f"  Accuracy: {metrics['accuracy']:.4f}")
            print(f"  Up Accuracy: {metrics['up_accuracy']:.4f}")
            print(f"  Down Accuracy: {metrics['down_accuracy']:.4f}")
            print(f"  Precision: {metrics['precision']:.4f}")
            print(f"  Recall: {metrics['recall']:.4f}")
            print(f"  F1 Score: {metrics['f1']:.4f}")
        else:
            print("\nRegression Metrics:")
            print(f"  RMSE: {metrics['rmse']:.6f}")
            print(f"  MAE: {metrics['mae']:.6f}")
            print(f"  R²: {metrics['r2']:.4f}")
            print(f"  MAPE: {metrics['mape']:.4f}")
            print(f"  Q95 Error: {metrics['q95_abs_error']:.6f}")

            print("\nDirectional Metrics:")
            print(f"  Directional Accuracy: {metrics['directional_accuracy']:.4f}")
            print(f"  Prediction Sharpness: {metrics['prediction_sharpness']:.4f}")

            print("\nPrediction Characteristics:")
            print(f"  Mean Prediction: {metrics['mean_prediction']:.6f}")
            print(f"  Std Prediction: {metrics['std_prediction']:.6f}")
            print(f"  Mean True: {metrics['mean_true']:.6f}")
            print(f"  Std True: {metrics['std_true']:.6f}")

        print("\nData Summary:")
        print(f"  Samples: {len(predictions_df)}")
        if target_type == 'regression':
            large_moves_true = (predictions_df['y_true'].abs() > 0.01).sum()
            large_moves_pred = (predictions_df['y_pred'].abs() > 0.01).sum()
            print(f"  Large moves (>1%): {large_moves_true} true, {large_moves_pred} predicted")
            print(f"  Avg True Move: {predictions_df['y_true'].abs().mean():.6f}")
            print(f"  Avg Pred Move: {predictions_df['y_pred'].abs().mean():.6f}")

        # Directional breakdown
        direction_crosstab = pd.crosstab(
            predictions_df['direction_true'],
            predictions_df['direction_pred'],
            rownames=['True'],
            colnames=['Predicted']
        )
        print("\nDirection Confusion Matrix:")
        print(direction_crosstab)

        print("="*60)

    def create_predictions_analysis(self,
                                  predictions_df: pd.DataFrame,
                                  output_dir: Optional[Path] = None) -> Dict[str, Path]:
        """
        Create detailed predictions analysis files

        Args:
            predictions_df: Predictions DataFrame
            output_dir: Output directory for analysis files

        Returns:
            Dictionary mapping analysis type to file path
        """
        output_dir = output_dir or self.config.data_cache_dir
        output_dir.mkdir(exist_ok=True)

        analysis_files = {}

        # Hourly performance analysis
        hourly_perf = self._create_hourly_performance(predictions_df)
        hourly_path = output_dir / 'hourly_performance.csv'
        hourly_perf.to_csv(hourly_path)
        analysis_files['hourly_performance'] = hourly_path

        # Error distribution analysis
        error_analysis = self._create_error_analysis(predictions_df)
        error_path = output_dir / 'error_analysis.json'
        with open(error_path, 'w') as f:
            json.dump(error_analysis, f, indent=2, default=str)
        analysis_files['error_analysis'] = error_path

        # Feature importance (if available)
        meta_path = self.config.models_dir / 'meta.json'
        if meta_path.exists():
            with open(meta_path, 'r') as f:
                meta = json.load(f)

            if 'feature_importance' in meta:
                importance_df = pd.DataFrame({
                    'feature': list(meta['feature_importance'].keys()),
                    'importance': list(meta['feature_importance'].values())
                }).sort_values('importance', ascending=False)

                importance_path = output_dir / 'feature_importance_detailed.csv'
                importance_df.to_csv(importance_path, index=False)
                analysis_files['feature_importance'] = importance_path

        logger.info(f"Created {len(analysis_files)} analysis files in {output_dir}")
        return analysis_files

    def _create_hourly_performance(self, predictions_df: pd.DataFrame) -> pd.DataFrame:
        """
        Create hourly performance breakdown
        """
        # Add hour column
        df = predictions_df.copy()
        df['hour'] = df['timestamp'].dt.hour

        # Group by hour
        hourly = df.groupby('hour').agg({
            'y_true': ['count', 'mean', 'std'],
            'y_pred': ['mean', 'std'],
            'direction_correct': 'mean',
            'abs_error': 'mean'
        }).round(6)

        # Flatten column names
        hourly.columns = ['_'.join(col).strip() for col in hourly.columns.values]
        hourly = hourly.rename(columns={
            'y_true_count': 'n_predictions',
            'y_true_mean': 'avg_true_return',
            'y_true_std': 'std_true_return',
            'y_pred_mean': 'avg_pred_return',
            'y_pred_std': 'std_pred_return',
            'direction_correct_mean': 'directional_accuracy',
            'abs_error_mean': 'mae'
        })

        return hourly

    def _create_error_analysis(self, predictions_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Create detailed error analysis
        """
        errors = predictions_df['error']

        return {
            'error_distribution': {
                'mean': float(errors.mean()),
                'std': float(errors.std()),
                'skew': float(errors.skew()),
                'kurtosis': float(errors.kurtosis()),
                'min': float(errors.min()),
                'max': float(errors.max()),
                'percentiles': {
                    '1': float(np.percentile(errors, 1)),
                    '5': float(np.percentile(errors, 5)),
                    '25': float(np.percentile(errors, 25)),
                    '50': float(np.percentile(errors, 50)),
                    '75': float(np.percentile(errors, 75)),
                    '95': float(np.percentile(errors, 95)),
                    '99': float(np.percentile(errors, 99))
                }
            },
            'directional_analysis': {
                'overall_accuracy': float(predictions_df['direction_correct'].mean()),
                'by_magnitude': self._analyze_by_magnitude(predictions_df)
            }
        }

    def _analyze_by_magnitude(self, predictions_df: pd.DataFrame) -> Dict[str, float]:
        """
        Analyze directional accuracy by true move magnitude
        """
        df = predictions_df.copy()
        df['magnitude_bin'] = pd.cut(df['y_true'].abs(),
                                   bins=[0, 0.001, 0.005, 0.01, 0.02, np.inf],
                                   labels=['<0.1%', '0.1-0.5%', '0.5-1%', '1-2%', '>2%'])

        return df.groupby('magnitude_bin')['direction_correct'].mean().to_dict()

def evaluate_saved_model(X: pd.DataFrame,
                        y: pd.Series,
                        model_path: Optional[Path] = None,
                        save_predictions: bool = True,
                        target_type: str = 'regression') -> Dict[str, Any]:
    """
    Convenience function to evaluate a saved model

    Args:
        X: Test features
        y: Test target
        model_path: Path to saved model
        save_predictions: Whether to save predictions
        target_type: Target type ('regression' or 'classification')

    Returns:
        Evaluation results
    """
    evaluator = ModelEvaluator(model_path)
    return evaluator.evaluate_model(X, y, save_predictions, target_type=target_type)

def get_evaluator(model_path: Optional[Path] = None) -> ModelEvaluator:
    """Get ModelEvaluator instance"""
    return ModelEvaluator(model_path)
