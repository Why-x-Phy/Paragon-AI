#!/usr/bin/env python3
"""
K-Fold Cross-Validation for Time Series LSTM Models

This implementation uses TimeSeriesSplit to respect temporal ordering,
which is crucial for financial time series data.
"""

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from typing import Tuple, Dict, List
import tensorflow as tf
import logging
from datetime import datetime
import json
import os

from src.model.ml_model_improved import ImprovedMLModel
from src.utils.logger import log_manager

logger = log_manager.get_logger("kfold_trainer")

class KFoldTimeSeriesTrainer:
    """
    K-Fold cross-validation trainer for time series models
    
    Uses expanding window approach where:
    - Fold 1: Train on 20%, test on next 20%
    - Fold 2: Train on 40%, test on next 20%
    - Fold 3: Train on 60%, test on next 20%
    - etc.
    """
    
    def __init__(self, n_splits: int = 5, optimization_target: str = "anti_collapse"):
        """
        Initialize K-Fold trainer
        
        Args:
            n_splits: Number of folds (typically 5 or 10)
            optimization_target: Loss function to use
        """
        self.n_splits = n_splits
        self.optimization_target = optimization_target
        self.fold_results = []
        
    def train_kfold(self, X: np.ndarray, y: np.ndarray, 
                    symbol: str, epochs: int = 30, 
                    batch_size: int = 32) -> Dict:
        """
        Train model using k-fold cross-validation
        
        Args:
            X: Feature array (samples, lookback, features)
            y: Target array (samples,)
            symbol: Token symbol for model naming
            epochs: Training epochs per fold
            batch_size: Batch size
            
        Returns:
            Dictionary with results and best model
        """
        logger.info(f"🔄 Starting {self.n_splits}-fold cross-validation for {symbol}")
        logger.info(f"   Data shape: {X.shape}, Target shape: {y.shape}")
        
        # Use TimeSeriesSplit for temporal data
        tscv = TimeSeriesSplit(n_splits=self.n_splits)
        
        fold_metrics = {
            'loss': [],
            'val_loss': [],
            'direction_accuracy': [],
            'val_direction_accuracy': [],
            'r2_score': [],
            'mae': [],
            'predictions_std': [],
            'predictions_collapsed': []
        }
        
        best_val_loss = float('inf')
        best_model = None
        best_fold = -1
        
        # Track time
        start_time = datetime.now()
        
        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            logger.info(f"\n{'='*60}")
            logger.info(f"📁 FOLD {fold + 1}/{self.n_splits}")
            logger.info(f"   Train samples: {len(train_idx)} ({len(train_idx)/len(X)*100:.1f}%)")
            logger.info(f"   Val samples: {len(val_idx)} ({len(val_idx)/len(X)*100:.1f}%)")
            
            # Split data
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]
            
            # Analyze data distribution for this fold
            train_pos_pct = np.sum(y_train > 0) / len(y_train) * 100
            val_pos_pct = np.sum(y_val > 0) / len(y_val) * 100
            logger.info(f"   Train distribution: {train_pos_pct:.1f}% positive")
            logger.info(f"   Val distribution: {val_pos_pct:.1f}% positive")
            
            # Create new model for each fold
            model = ImprovedMLModel(optimization_target=self.optimization_target)
            
            # Build model
            model.build_model(
                input_shape=(X.shape[1], X.shape[2])
            )
            
            # Train model
            history = model.train(
                X_train, y_train,
                X_val, y_val,
                epochs=epochs,
                batch_size=batch_size,
                model_name=None  # Don't save intermediate models
            )
            
            # Evaluate fold
            fold_results = self._evaluate_fold(model, X_val, y_val, fold)
            
            # Store metrics
            for metric, value in fold_results.items():
                if metric in fold_metrics:
                    fold_metrics[metric].append(value)
            
            # Track best model
            if fold_results['val_loss'] < best_val_loss:
                best_val_loss = fold_results['val_loss']
                best_model = model
                best_fold = fold + 1
                
            logger.info(f"\n📊 Fold {fold + 1} Results:")
            logger.info(f"   Val Loss: {fold_results['val_loss']:.6f}")
            logger.info(f"   Direction Accuracy: {fold_results['val_direction_accuracy']:.2%}")
            logger.info(f"   R² Score: {fold_results['r2_score']:.4f}")
            logger.info(f"   Prediction Std: {fold_results['predictions_std']:.6f}")
            logger.info(f"   Collapsed: {'YES' if fold_results['predictions_collapsed'] else 'NO'}")
        
        # Save best model FIRST (before summary calculations that might crash)
        model_name = None
        if best_model:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_name = f"{symbol}_lstm_kfold_best_{timestamp}"
            try:
                best_model.save(model_name)
                logger.info(f"\n💾 Saved best model from fold {best_fold}: {model_name}")
            except Exception as e:
                logger.error(f"Failed to save best model: {e}")
                model_name = None
        
        # Calculate summary statistics (safe to crash after model is saved)
        summary = self._calculate_summary(fold_metrics)
        
        # Total time
        total_time = (datetime.now() - start_time).total_seconds() / 60
        summary['training_time_minutes'] = total_time
        summary['best_fold'] = best_fold
        summary['model_name'] = model_name
        
        # Print summary
        self._print_summary(summary, symbol)
        
        # Save detailed results
        self._save_results(summary, symbol)
        
        return summary
    
    def _evaluate_fold(self, model, X_val: np.ndarray, y_val: np.ndarray, fold: int) -> Dict:
        """Evaluate model performance on validation set"""
        # Make predictions
        y_pred = model.predict(X_val)
        
        # Calculate metrics
        val_loss = np.mean((y_pred - y_val) ** 2)
        direction_accuracy = np.mean(np.sign(y_pred) == np.sign(y_val))
        
        # R² score
        ss_res = np.sum((y_val - y_pred) ** 2)
        ss_tot = np.sum((y_val - np.mean(y_val)) ** 2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else -999
        
        # MAE
        mae = np.mean(np.abs(y_pred - y_val))
        
        # Check for collapse
        pred_std = np.std(y_pred)
        pred_range = np.ptp(y_pred)
        collapsed = pred_std < 0.001 or pred_range < 0.002
        
        return {
            'fold': fold + 1,
            'val_loss': float(val_loss),
            'val_direction_accuracy': float(direction_accuracy),
            'r2_score': float(r2),
            'mae': float(mae),
            'predictions_std': float(pred_std),
            'predictions_range': float(pred_range),
            'predictions_collapsed': collapsed
        }
    
    def _calculate_summary(self, fold_metrics: Dict) -> Dict:
        """Calculate summary statistics across all folds"""
        summary = {}
        
        for metric, values in fold_metrics.items():
            # Skip empty arrays to prevent crashes
            if not values or len(values) == 0:
                logger.warning(f"Empty values for metric {metric}, skipping")
                continue
                
            if metric == 'predictions_collapsed':
                summary[f'{metric}_count'] = sum(values)
                summary[f'{metric}_rate'] = sum(values) / len(values) if len(values) > 0 else 0
            else:
                # Safe calculation with error handling
                try:
                    summary[f'{metric}_mean'] = float(np.mean(values))
                    summary[f'{metric}_std'] = float(np.std(values)) if len(values) > 1 else 0.0
                    summary[f'{metric}_min'] = float(np.min(values))
                    summary[f'{metric}_max'] = float(np.max(values))
                except Exception as e:
                    logger.warning(f"Error calculating stats for {metric}: {e}")
                    summary[f'{metric}_mean'] = 0.0
                    summary[f'{metric}_std'] = 0.0
                    summary[f'{metric}_min'] = 0.0
                    summary[f'{metric}_max'] = 0.0
        
        return summary
    
    def _print_summary(self, summary: Dict, symbol: str):
        """Print formatted summary of k-fold results"""
        print(f"\n{'='*70}")
        print(f"🎯 K-FOLD CROSS-VALIDATION SUMMARY - {symbol}")
        print(f"{'='*70}")
        
        print(f"\n📊 Performance Metrics (mean ± std):")
        print(f"   Direction Accuracy: {summary['val_direction_accuracy_mean']:.2%} ± {summary['val_direction_accuracy_std']:.2%}")
        print(f"   R² Score: {summary['r2_score_mean']:.4f} ± {summary['r2_score_std']:.4f}")
        print(f"   Val Loss: {summary['val_loss_mean']:.6f} ± {summary['val_loss_std']:.6f}")
        print(f"   MAE: {summary['mae_mean']:.6f} ± {summary['mae_std']:.6f}")
        
        print(f"\n🔍 Stability Metrics:")
        print(f"   Prediction Std Dev: {summary['predictions_std_mean']:.6f} ± {summary['predictions_std_std']:.6f}")
        print(f"   Collapse Rate: {summary['predictions_collapsed_rate']:.0%} ({summary['predictions_collapsed_count']}/{self.n_splits} folds)")
        
        print(f"\n⏱️  Training Time: {summary['training_time_minutes']:.1f} minutes")
        print(f"🏆 Best Fold: {summary['best_fold']}")
        
        print(f"\n💡 Interpretation:")
        if summary['val_direction_accuracy_mean'] > 0.55:
            print("   ✅ Model shows consistent predictive power")
        elif summary['val_direction_accuracy_mean'] > 0.52:
            print("   ⚠️  Model has marginal predictive power")
        else:
            print("   ❌ Model performs at random chance level")
            
        if summary['predictions_collapsed_rate'] > 0.2:
            print("   ⚠️  High collapse rate - consider different loss function")
        
    def _save_results(self, summary: Dict, symbol: str):
        """Save detailed results to JSON file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"models/results/kfold_{symbol}_{timestamp}.json"
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Convert numpy types to Python types for JSON serialization
        def convert_numpy_types(obj):
            if hasattr(obj, 'item'):  # numpy scalar
                return obj.item()
            elif isinstance(obj, dict):
                return {k: convert_numpy_types(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy_types(item) for item in obj]
            else:
                return obj
        
        json_safe_summary = convert_numpy_types(summary)
        
        with open(filename, 'w') as f:
            json.dump(json_safe_summary, f, indent=2)
        
        logger.info(f"\n💾 Detailed results saved to: {filename}")


def train_with_kfold(symbol: str, token_address: str, 
                     days: int = 30, n_splits: int = 5,
                     optimization_target: str = "anti_collapse") -> Dict:
    """
    Convenience function to train a model with k-fold validation
    
    Args:
        symbol: Token symbol
        token_address: Token contract address
        days: Days of historical data
        n_splits: Number of folds
        optimization_target: Loss function
        
    Returns:
        K-fold results summary
    """
    from src.data.data_processor import DataProcessor
    
    # Initialize data processor
    processor = DataProcessor()
    
    # Fetch and prepare data
    logger.info(f"Fetching {days} days of data for {symbol}...")
    
    # First, get processed DataFrame using data processor
    df = processor.process_pipeline(
        token_address=token_address,
        symbol=symbol,
        resolution='1H',
        days=days,
        save_data=False,
        include_sentiment=True
    )
    
    if df.empty:
        raise ValueError(f"Failed to fetch data for {symbol}")
    
    # Now prepare ML data from the DataFrame
    X_train, X_val, y_train, y_val, feature_columns = processor.prepare_ml_data(
        df=df,
        target_col='close',
        sequence_length=24,
        prediction_horizon=1,
        test_size=0.2,
        include_feature_names=True
    )
    
    # Combine train and validation for k-fold
    # (k-fold will create its own train/val splits)
    X_all = np.concatenate([X_train, X_val], axis=0)
    y_all = np.concatenate([y_train, y_val], axis=0)
    
    # Initialize k-fold trainer
    trainer = KFoldTimeSeriesTrainer(n_splits=n_splits, optimization_target=optimization_target)
    
    # Run k-fold training
    results = trainer.train_kfold(X_all, y_all, symbol=symbol)
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Train model with k-fold cross-validation')
    parser.add_argument('token_address', type=str, help='Token contract address')
    parser.add_argument('symbol', type=str, help='Token symbol (e.g., FARTCOIN)')
    parser.add_argument('--days', type=int, default=30, help='Days of historical data')
    parser.add_argument('--n-splits', type=int, default=5, help='Number of folds')
    parser.add_argument('--optimization-target', type=str, default='anti_collapse',
                        choices=['anti_collapse', 'robust_directional', 'variance_encouraging'],
                        help='Loss function to use')
    
    args = parser.parse_args()
    
    results = train_with_kfold(
        symbol=args.symbol,
        token_address=args.token_address,
        days=args.days,
        n_splits=args.n_splits,
        optimization_target=args.optimization_target
    ) 