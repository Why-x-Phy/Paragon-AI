"""
LightGBM model trainer for Orderbook features

Trains regression model to predict next candle percent change using orderbook features.
"""

import lightgbm as lgb
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple, Optional, List
from pathlib import Path
import json
import pickle
import logging
from datetime import datetime

from .config import get_config

logger = logging.getLogger(__name__)

class LGBMTrainer:
    """Trains LightGBM model for orderbook-based price prediction"""

    def __init__(self):
        self.config = get_config()
        self.model = None
        self.feature_names = None
        self.feature_importances = None

    def train_lgbm(self,
                  X_train: pd.DataFrame,
                  y_train: pd.Series,
                  X_valid: pd.DataFrame,
                  y_valid: pd.Series,
                  params: Optional[Dict[str, Any]] = None,
                  feature_selection: bool = False,
                  target_type: str = 'regression') -> Tuple[lgb.Booster, Dict[str, Any]]:
        # Store target type for metadata
        self._last_target_type = target_type

        """
        Train LightGBM model with early stopping

        Args:
            X_train: Training features
            y_train: Training target
            X_valid: Validation features
            y_valid: Validation target
            params: LightGBM parameters

        Returns:
            Tuple of (trained_model, eval_metrics)
        """
        # Default parameters based on target type
        if target_type == 'classification':
            default_params = {
                'objective': 'multiclass',  # Multi-class classification for -1, 0, 1
                'metric': 'multi_logloss',
                'num_class': 3,  # -1, 0, 1 classes
                'learning_rate': 0.05,
                'num_leaves': 32,  # Smaller trees for classification
                'feature_fraction': 0.8,
                'bagging_fraction': 0.8,
                'bagging_freq': 1,
                'min_data_in_leaf': 100,  # Larger minimum for classification
                'n_estimators': 1000,
                'early_stopping_rounds': 50,
                'lambda_l1': 0.0,
                'lambda_l2': 1.0,
                'min_gain_to_split': 0.0,
                'max_depth': -1,
                'random_state': self.config.model.random_state,
                'verbosity': -1
            }
        elif target_type == 'binary':
            default_params = {
                'objective': 'binary',
                'metric': 'binary_logloss',
                'learning_rate': 0.03,
                'num_leaves': 48,
                'feature_fraction': 0.8,
                'bagging_fraction': 0.8,
                'bagging_freq': 1,
                'min_data_in_leaf': 200,
                'n_estimators': 2500,
                'early_stopping_rounds': 200,
                'lambda_l1': 0.0,
                'lambda_l2': 1.0,
                'min_gain_to_split': 0.0,
                'max_depth': -1,
                'random_state': self.config.model.random_state,
                'verbosity': -1
            }
        else:  # regression
            default_params = {
                'objective': self.config.model.objective,
                'metric': self.config.model.metric,
                'learning_rate': self.config.model.learning_rate,
                'num_leaves': self.config.model.num_leaves,
                'feature_fraction': self.config.model.feature_fraction,
                'bagging_fraction': self.config.model.bagging_fraction,
                'bagging_freq': self.config.model.bagging_freq,
                'min_data_in_leaf': self.config.model.min_data_in_leaf,
                'n_estimators': self.config.model.n_estimators,
                'early_stopping_rounds': self.config.model.early_stopping_rounds,
                'lambda_l1': 0.0,
                'lambda_l2': 1.0,
                'min_gain_to_split': 0.0,
                'max_depth': -1,
                'random_state': self.config.model.random_state,
                'verbosity': -1
            }

        # Override with provided params
        if params:
            default_params.update(params)

        logger.info(f"Training LGBM with params: {default_params}")

        # Handle label encoding / filtering
        if target_type == 'classification':
            # Remap labels from (-1, 0, 1) to (0, 1, 2) for LightGBM
            label_mapping = {-1: 0, 0: 1, 1: 2}
            y_train_encoded = y_train.map(label_mapping)
            y_valid_encoded = y_valid.map(label_mapping)

            # Store original labels for metrics calculation
            y_train_orig = y_train.copy()
            y_valid_orig = y_valid.copy()
        elif target_type == 'binary':
            # Filter out neutrals (0). Map {-1, +1} -> {0, 1}
            train_mask = y_train != 0
            valid_mask = y_valid != 0
            X_train = X_train[train_mask]
            y_train = y_train[train_mask]
            X_valid = X_valid[valid_mask]
            y_valid = y_valid[valid_mask]

            y_train_encoded = (y_train == 1).astype(int)
            y_valid_encoded = (y_valid == 1).astype(int)

            y_train_orig = y_train.copy()
            y_valid_orig = y_valid.copy()
        else:
            y_train_encoded = y_train
            y_valid_encoded = y_valid
            y_train_orig = y_train
            y_valid_orig = y_valid

        # Feature selection (keep only top N features by importance)
        if feature_selection and len(X_train.columns) > 20:
            logger.info("Performing feature selection...")
            # Quick feature importance estimation
            quick_params = default_params.copy()
            quick_params.update({'n_estimators': 100, 'early_stopping_rounds': None})

            quick_model = lgb.train(
                quick_params,
                lgb.Dataset(X_train, label=y_train_encoded),
                num_boost_round=100,
                valid_sets=[lgb.Dataset(X_valid, label=y_valid_encoded)],
                callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)]
            )

            # Select top features
            importances = quick_model.feature_importance(importance_type='gain')
            feature_importance_df = pd.DataFrame({
                'feature': X_train.columns,
                'importance': importances
            }).sort_values('importance', ascending=False)

            # Keep top 75% of features or minimum 15 features
            n_keep = max(15, int(len(feature_importance_df) * 0.75))
            top_features = feature_importance_df.head(n_keep)['feature'].tolist()

            logger.info(f"Selected {len(top_features)}/{len(X_train.columns)} features")
            X_train = X_train[top_features]
            X_valid = X_valid[top_features]

        # Create sample weights
        if target_type == 'classification':
            label_mapping = {-1: 0, 0: 1, 1: 2}
            encoded_train = y_train.map(label_mapping)
            class_counts = encoded_train.value_counts().to_dict()
            total = sum(class_counts.values()) if class_counts else 1
            n_classes = len(class_counts) if class_counts else 1
            # Soften weights: sqrt of inverse frequency to avoid overcompensation
            class_weight = {cls: (total / (n_classes * cnt)) ** 0.5 for cls, cnt in class_counts.items()} if class_counts else {0: 1.0}
            w_train = encoded_train.map(class_weight).astype(float)

            encoded_valid = y_valid.map(label_mapping)
            w_valid = encoded_valid.map(class_weight).astype(float)
        elif target_type == 'binary':
            # Balance positive vs negative movers
            pos = y_train_encoded.sum()
            neg = len(y_train_encoded) - pos
            if pos > 0 and neg > 0:
                w_pos = (neg / pos) ** 0.5
                w_neg = 1.0
                w_train = y_train_encoded.apply(lambda v: w_pos if v == 1 else w_neg).astype(float)
                w_valid = y_valid_encoded.apply(lambda v: w_pos if v == 1 else w_neg).astype(float)
            else:
                w_train = pd.Series(1.0, index=y_train_encoded.index)
                w_valid = pd.Series(1.0, index=y_valid_encoded.index)
        else:
            w_train = y_train_encoded.abs().clip(upper=0.015) / 0.015
            w_train = w_train.fillna(0.0)
            w_valid = y_valid_encoded.abs().clip(upper=0.015) / 0.015
            w_valid = w_valid.fillna(0.0)

        # Create datasets
        train_data = lgb.Dataset(X_train, label=y_train_encoded, weight=w_train, feature_name=list(X_train.columns))
        valid_data = lgb.Dataset(X_valid, label=y_valid_encoded, weight=w_valid, feature_name=list(X_train.columns))

        # Remove early_stopping_rounds from params (used separately)
        train_params = default_params.copy()
        early_stopping_rounds = train_params.pop('early_stopping_rounds')

        # Train model
        self.model = lgb.train(
            train_params,
            train_data,
            valid_sets=[train_data, valid_data],
            valid_names=['train', 'valid'],
            num_boost_round=train_params.get('n_estimators', 2000),
            callbacks=[
                lgb.early_stopping(stopping_rounds=early_stopping_rounds),
                lgb.log_evaluation(period=50)
            ]
        )

        # Store feature information
        self.feature_names = list(X_train.columns)
        self.feature_importances = dict(zip(
            self.feature_names,
            self.model.feature_importance(importance_type='gain').tolist()
        ))

        # Get evaluation metrics (use original labels for classification)
        eval_metrics = self._get_eval_metrics(X_train, y_train_orig, X_valid, y_valid_orig, target_type)

        logger.info(f"Training completed. Best iteration: {self.model.best_iteration}")

        return self.model, eval_metrics

    def _get_eval_metrics(self,
                         X_train: pd.DataFrame,
                         y_train: pd.Series,
                         X_valid: pd.DataFrame,
                         y_valid: pd.Series,
                         target_type: str = 'regression') -> Dict[str, Any]:
        """
        Calculate training and validation metrics
        """
        # Predictions
        if target_type == 'classification':
            # For classification, get class predictions (not probabilities)
            train_pred_raw = self.model.predict(X_train, num_iteration=self.model.best_iteration)
            valid_pred_raw = self.model.predict(X_valid, num_iteration=self.model.best_iteration)

            # Convert probabilities to class predictions
            train_pred = train_pred_raw.argmax(axis=1) if len(train_pred_raw.shape) > 1 else train_pred_raw
            valid_pred = valid_pred_raw.argmax(axis=1) if len(valid_pred_raw.shape) > 1 else valid_pred_raw

            # Remap back to original labels (-1, 0, 1)
            reverse_mapping = {0: -1, 1: 0, 2: 1}
            train_pred = pd.Series(train_pred).map(reverse_mapping)
            valid_pred = pd.Series(valid_pred).map(reverse_mapping)
        elif target_type == 'binary':
            train_prob = np.array(self.model.predict(X_train, num_iteration=self.model.best_iteration))
            valid_prob = np.array(self.model.predict(X_valid, num_iteration=self.model.best_iteration))

            # Find optimal threshold on validation to maximize F1 (or balanced acc)
            thresholds = np.linspace(0.3, 0.7, 41)
            best_thr = 0.5
            best_f1 = -1.0
            yv = y_valid.astype(int).values
            for thr in thresholds:
                preds = (valid_prob >= thr).astype(int)
                tp = np.sum((yv == 1) & (preds == 1))
                fp = np.sum((yv == 0) & (preds == 1))
                fn = np.sum((yv == 1) & (preds == 0))
                precision = tp / (tp + fp) if (tp + fp) > 0 else 0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
                if f1 > best_f1:
                    best_f1 = f1
                    best_thr = thr

            # Store for metadata
            self._optimal_threshold = best_thr

            train_pred = (train_prob >= best_thr).astype(int)
            valid_pred = (valid_prob >= best_thr).astype(int)
        else:
            # Regression predictions
            train_pred = self.model.predict(X_train, num_iteration=self.model.best_iteration)
            valid_pred = self.model.predict(X_valid, num_iteration=self.model.best_iteration)

        # Metrics
        metrics = {
            'train': self._calculate_metrics(y_train, train_pred, target_type),
            'valid': self._calculate_metrics(y_valid, valid_pred, target_type),
            'feature_importance': self.feature_importances,
            'best_iteration': self.model.best_iteration,
            'num_features': len(self.feature_names),
            'target_type': target_type,
            'training_params': {
                'n_train_samples': len(X_train),
                'n_valid_samples': len(X_valid),
                'feature_names': self.feature_names
            }
        }

        if target_type == 'binary':
            metrics['optimal_threshold'] = float(getattr(self, '_optimal_threshold', 0.5))

        return metrics

    def _calculate_metrics(self, y_true: pd.Series, y_pred: np.ndarray, target_type: str = 'regression') -> Dict[str, float]:
        """
        Calculate metrics for regression or classification
        """
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)

        if target_type == 'classification':
            # Classification metrics
            accuracy = np.mean(y_true == y_pred)

            # Per-class metrics for up/down moves (ignoring neutral)
            up_mask = y_true == 1
            down_mask = y_true == -1

            up_accuracy = np.mean(y_pred[up_mask] == 1) if np.sum(up_mask) > 0 else 0
            down_accuracy = np.mean(y_pred[down_mask] == -1) if np.sum(down_mask) > 0 else 0

            # Confusion matrix elements (focusing on directional predictions)
            true_positives = np.sum((y_true == 1) & (y_pred == 1))
            true_negatives = np.sum((y_true == -1) & (y_pred == -1))
            false_positives = np.sum((y_true == -1) & (y_pred == 1))
            false_negatives = np.sum((y_true == 1) & (y_pred == -1))

            precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
            recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

            return {
                'accuracy': float(accuracy),
                'up_accuracy': float(up_accuracy),
                'down_accuracy': float(down_accuracy),
                'precision': float(precision),
                'recall': float(recall),
                'f1': float(f1),
                'true_positives': int(true_positives),
                'true_negatives': int(true_negatives),
                'false_positives': int(false_positives),
                'false_negatives': int(false_negatives)
            }
        elif target_type == 'binary':
            # Binary classification metrics
            y_true = y_true.astype(int)
            y_pred = y_pred.astype(int)
            accuracy = np.mean(y_true == y_pred)
            # Precision/recall/F1 for positive class
            tp = np.sum((y_true == 1) & (y_pred == 1))
            fp = np.sum((y_true == 0) & (y_pred == 1))
            fn = np.sum((y_true == 1) & (y_pred == 0))
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (fn + tp) if (fn + tp) > 0 else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            return {
                'accuracy': float(accuracy),
                'precision': float(precision),
                'recall': float(recall),
                'f1': float(f1)
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

            return {
                'mse': float(mse),
                'rmse': float(rmse),
                'mae': float(mae),
                'r2': float(r2),
                'directional_accuracy': float(directional_accuracy),
                'mape': float(mape)
            }

    def save_model(self,
                  model_path: Optional[Path] = None,
                  meta_path: Optional[Path] = None) -> Tuple[Path, Path]:
        """
        Save trained model and metadata

        Args:
            model_path: Path to save model (default: models/lgbm_model.txt)
            meta_path: Path to save metadata (default: models/meta.json)

        Returns:
            Tuple of (model_path, meta_path)
        """
        if self.model is None:
            raise ValueError("No trained model to save")

        # Default paths
        model_path = model_path or self.config.models_dir / 'lgbm_model.txt'
        meta_path = meta_path or self.config.models_dir / 'meta.json'

        # Save model
        model_path.parent.mkdir(exist_ok=True)
        self.model.save_model(str(model_path))
        logger.info(f"Model saved to {model_path}")

        # Save metadata
        # Determine objective and target based on last training
        objective = 'multiclass' if getattr(self, '_last_target_type', 'regression') == 'classification' else 'regression'
        target_name = 'direction' if getattr(self, '_last_target_type', 'regression') == 'classification' else 'next_candle_pct_change'

        metadata = {
            'timestamp': datetime.now().isoformat(),
            'model_type': 'lightgbm',
            'objective': objective,
            'target': target_name,
            'target_type': getattr(self, '_last_target_type', 'regression'),
            'feature_names': self.feature_names,
            'feature_importance': self.feature_importances,
            'best_iteration': self.model.best_iteration if hasattr(self.model, 'best_iteration') else None,
            'config': {
                'learning_rate': self.config.model.learning_rate,
                'num_leaves': self.config.model.num_leaves,
                'num_features': len(self.feature_names) if self.feature_names else 0
            }
        }

        # Persist optimal threshold for binary models
        if getattr(self, '_last_target_type', 'regression') == 'binary':
            metadata['optimal_threshold'] = float(getattr(self, '_optimal_threshold', 0.5))

        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2, default=str)

        logger.info(f"Metadata saved to {meta_path}")
        return model_path, meta_path

    def save_feature_importance_csv(self, csv_path: Optional[Path] = None) -> Path:
        """
        Save feature importance to CSV

        Args:
            csv_path: Path to save CSV (default: models/feature_importance.csv)

        Returns:
            Path to saved CSV
        """
        if self.feature_importances is None:
            raise ValueError("No feature importance data available")

        csv_path = csv_path or self.config.models_dir / 'feature_importance.csv'

        # Create DataFrame
        importance_df = pd.DataFrame({
            'feature': list(self.feature_importances.keys()),
            'importance': list(self.feature_importances.values())
        }).sort_values('importance', ascending=False)

        # Save to CSV
        csv_path.parent.mkdir(exist_ok=True)
        importance_df.to_csv(csv_path, index=False)

        logger.info(f"Feature importance saved to {csv_path}")
        return csv_path

def create_time_based_split(X: pd.DataFrame,
                           y: pd.Series,
                           train_ratio: float = 0.8) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """
    Create time-based train/validation split

    Args:
        X: Features DataFrame (datetime index)
        y: Target Series (datetime index)
        train_ratio: Ratio of data for training (0-1)

    Returns:
        Tuple of (X_train, y_train, X_valid, y_valid)
    """
    if not isinstance(X.index, pd.DatetimeIndex) or not isinstance(y.index, pd.DatetimeIndex):
        raise ValueError("X and y must have DatetimeIndex")

    # Sort by time (should already be sorted, but ensure)
    X = X.sort_index()
    y = y.sort_index()

    # Find split point
    split_idx = int(len(X) * train_ratio)

    # Split
    X_train = X.iloc[:split_idx]
    y_train = y.iloc[:split_idx]
    X_valid = X.iloc[split_idx:]
    y_valid = y.iloc[split_idx:]

    logger.info(f"Time-based split: {len(X_train)} train, {len(X_valid)} valid samples")
    logger.info(f"Train period: {X_train.index[0]} to {X_train.index[-1]}")
    logger.info(f"Valid period: {X_valid.index[0]} to {X_valid.index[-1]}")

    return X_train, y_train, X_valid, y_valid

def train_model_with_split(X: pd.DataFrame,
                          y: pd.Series,
                          train_ratio: float = 0.8,
                          model_params: Optional[Dict[str, Any]] = None,
                          feature_selection: bool = False,
                          target_type: str = 'regression') -> Tuple[lgb.Booster, Dict[str, Any]]:
    """
    Convenience function to train model with automatic time-based split

    Args:
        X: Features DataFrame
        y: Target Series
        train_ratio: Training data ratio
        model_params: LightGBM parameters
        feature_selection: Whether to perform feature selection
        target_type: 'regression' or 'classification'

    Returns:
        Tuple of (trained_model, eval_metrics)
    """
    # Create split
    X_train, y_train, X_valid, y_valid = create_time_based_split(X, y, train_ratio)

    # Train model
    trainer = LGBMTrainer()
    model, metrics = trainer.train_lgbm(X_train, y_train, X_valid, y_valid, model_params, feature_selection, target_type)

    # Save model and artifacts
    trainer.save_model()
    trainer.save_feature_importance_csv()

    return model, metrics

# Utility functions for cross-validation

def time_series_split(X: pd.DataFrame,
                     y: pd.Series,
                     n_splits: int = 5,
                     test_size: float = 0.2) -> List[Tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]]:
    """
    Create multiple time-based train/test splits for cross-validation

    Args:
        X: Features DataFrame
        y: Target Series
        n_splits: Number of splits
        test_size: Size of test set (0-1)

    Returns:
        List of (X_train, y_train, X_test, y_test) tuples
    """
    if not isinstance(X.index, pd.DatetimeIndex):
        raise ValueError("X must have DatetimeIndex for time series split")

    splits = []
    n_samples = len(X)

    for i in range(n_splits):
        # Rolling window split
        split_point = n_samples - int(n_samples * test_size * (n_splits - i) / n_splits)

        X_train = X.iloc[:split_point]
        y_train = y.iloc[:split_point]
        X_test = X.iloc[split_point:]
        y_test = y.iloc[split_point:]

        splits.append((X_train, y_train, X_test, y_test))

    return splits

def get_trainer() -> LGBMTrainer:
    """Get LGBMTrainer instance"""
    return LGBMTrainer()
