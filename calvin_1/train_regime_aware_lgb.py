#!/usr/bin/env python3
"""
Regime-Aware LightGBM Training System

The best production stack for crypto trading:
1. Regime Classifier - Detects high/low volatility regimes
2. High-Vol Regressor - Specialized for volatile markets
3. Low-Vol Regressor - Specialized for calm markets
4. Optional Direction Classifier - Final up/down decision

"""

import os
import sys
import argparse
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, mean_squared_error, classification_report
import joblib
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import warnings
warnings.filterwarnings('ignore')

# Add src to path
sys.path.append('src')

from src.data.data_processor import DataProcessor
from src.config.config import config

class RegimeAwareLGBTrainer:
    
    def __init__(self, symbol: str, token_address: str):
        self.symbol = symbol
        self.token_address = token_address
        self.data_processor = DataProcessor()
        
        # Model storage
        self.regime_classifier = None
        self.high_vol_regressor = None
        self.low_vol_regressor = None
        self.direction_classifier = None
        
        # Scalers
        self.feature_scaler = StandardScaler()
        self.regime_scaler = StandardScaler()
        
        # Feature names storage
        self.feature_names = None
        self.regime_feature_names = None
        
        # Hyperparameters
        self.regime_clf_params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.9,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'random_state': 42
        }
        
        self.regressor_params = {
            'objective': 'regression_l2',
            'metric': 'rmse',
            'boosting_type': 'gbdt',
            'num_leaves': 63,
            'learning_rate': 0.03,
            'feature_fraction': 0.9,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'random_state': 42
        }
        
        self.direction_clf_params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.9,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'random_state': 42
        }
        
        # Create plots directory
        os.makedirs('plots', exist_ok=True)
        
        print(f"🚀 Initializing Regime-Aware LGB Trainer for {symbol}")
        
    def load_and_prepare_data(self, days: int = 90):
        """Load data and prepare features"""
        print(f"\n📊 Loading {days} days of data...")
        
        df = self.data_processor.process_pipeline(
            self.token_address,
            self.symbol,
            resolution='1H',
            days=days,
            save_data=False
        )
        
        if df is None or df.empty:
            raise ValueError("Failed to load data")
        
        print(f"✅ Loaded {len(df)} hours of data")
        return df
    
    def plot_feature_importance(self, model, feature_names, model_name: str, top_n: int = 20):
        """Plot feature importance for a model"""
        try:
            # Get feature importance
            importance = model.feature_importance(importance_type='gain')
            
            if len(importance) != len(feature_names):
                print(f"⚠️ Warning: Feature count mismatch for {model_name}: {len(importance)} vs {len(feature_names)}")
                # Truncate to match
                min_len = min(len(importance), len(feature_names))
                importance = importance[:min_len]
                feature_names = feature_names[:min_len]
            
            # Create DataFrame and sort
            importance_df = pd.DataFrame({
                'feature': feature_names,
                'importance': importance
            }).sort_values('importance', ascending=False)
            
            # Plot top features
            plt.figure(figsize=(12, 8))
            top_features = importance_df.head(top_n)
            
            sns.barplot(data=top_features, x='importance', y='feature', palette='viridis')
            plt.title(f'{model_name} - Top {top_n} Feature Importance (by Gain)', fontsize=14, fontweight='bold')
            plt.xlabel('Feature Importance (Gain)', fontsize=12)
            plt.ylabel('Features', fontsize=12)
            plt.tight_layout()
            
            # Save plot
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            plot_path = f"plots/{self.symbol}_{model_name.lower().replace(' ', '_')}_{timestamp}.png"
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            plt.close()
            
            print(f"📊 {model_name} feature importance saved to: {plot_path}")
            
            # Print top 10 features
            print(f"\n🎯 Top 10 Features for {model_name}:")
            for i, (_, row) in enumerate(top_features.head(10).iterrows()):
                print(f"   {i+1:2d}. {row['feature'][:40]:<40} {row['importance']:>8.1f}")
            
            return importance_df
            
        except Exception as e:
            print(f"❌ Error plotting feature importance for {model_name}: {e}")
            return None

    def create_regime_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create features specifically for regime detection"""
        print("\n🔧 Creating regime detection features...")
        
        regime_features = pd.DataFrame(index=df.index)
        
        # Volatility features (key for regime detection)
        regime_features['volatility_24h'] = df['close'].pct_change().rolling(24).std()
        regime_features['volatility_72h'] = df['close'].pct_change().rolling(72).std()
        regime_features['volatility_168h'] = df['close'].pct_change().rolling(168).std()
        
        # Volatility ratios (with better epsilon for stability)
        epsilon = 1e-6
        regime_features['vol_ratio_24_72'] = regime_features['volatility_24h'] / (regime_features['volatility_72h'] + epsilon)
        regime_features['vol_ratio_24_168'] = regime_features['volatility_24h'] / (regime_features['volatility_168h'] + epsilon)
        
        # ATR-based volatility
        if 'ATRr_14' in df.columns:
            regime_features['atr_14'] = df['ATRr_14']
            regime_features['atr_change'] = df['ATRr_14'].pct_change(24)
        
        # Volume features (high volume often = high volatility)
        volume_std = df['volume'].rolling(168).std()
        volume_mean = df['volume'].rolling(168).mean()
        regime_features['volume_24h_zscore'] = np.where(
            volume_std > epsilon,
            (df['volume'] - volume_mean) / volume_std,
            0
        )
        regime_features['volume_spike'] = (df['volume'] > df['volume'].rolling(168).quantile(0.9)).astype(int)
        
        # Price momentum (trending markets often volatile)
        regime_features['momentum_24h'] = df['close'].pct_change(24)
        regime_features['momentum_abs'] = regime_features['momentum_24h'].abs()
        
        # Range expansion
        regime_features['range_24h'] = (df['high'].rolling(24).max() - df['low'].rolling(24).min()) / (df['close'] + epsilon)
        range_mean = regime_features['range_24h'].rolling(168).mean()
        regime_features['range_expansion'] = np.where(
            range_mean > epsilon,
            regime_features['range_24h'] / range_mean,
            1.0
        )
        
        # Realized volatility variations
        if 'parkinson_volatility' in df.columns:
            regime_features['parkinson_vol'] = df['parkinson_volatility']
        if 'garman_klass_volatility' in df.columns:
            regime_features['gk_vol'] = df['garman_klass_volatility']
        
        # Market microstructure
        high_low_range = df['high'] - df['low']
        regime_features['price_efficiency'] = np.where(
            high_low_range > epsilon,
            (df['close'] - df['open']).abs() / high_low_range,
            0.5
        )
        
        # Fill NaN values
        regime_features = regime_features.fillna(method='ffill').fillna(0)
        
        # Clip extreme values to prevent infinity
        regime_features = regime_features.clip(lower=-1e6, upper=1e6)
        
        # Replace any remaining inf values
        regime_features = regime_features.replace([np.inf, -np.inf], 0)
        
        # Store regime feature names
        self.regime_feature_names = regime_features.columns.tolist()
        
        print(f"✅ Created {len(regime_features.columns)} regime features")
        return regime_features
    
    def create_regime_labels(self, df: pd.DataFrame, vol_threshold: float = 0.75) -> np.ndarray:
        """Create regime labels based on volatility quantiles"""
        print(f"\n🏷️  Creating regime labels (threshold: {vol_threshold:.0%} quantile)...")
        
        # Calculate rolling volatility
        volatility = df['close'].pct_change().rolling(24).std()
        
        # High volatility regime = above threshold quantile
        threshold = volatility.quantile(vol_threshold)
        regime_labels = (volatility > threshold).astype(int)
        
        # Print regime distribution
        high_vol_pct = regime_labels.mean() * 100
        print(f"📊 Regime Distribution:")
        print(f"   High Volatility: {high_vol_pct:.1f}%")
        print(f"   Low Volatility: {100-high_vol_pct:.1f}%")
        print(f"   Threshold: {threshold:.4f}")
        
        return regime_labels.values
    
    def prepare_features_and_targets(self, df: pd.DataFrame):
        """Prepare features and targets for all models"""
        print("\n📊 Preparing features and targets...")
        
        # Create targets
        # Regression target: next hour return
        df['target_return'] = df['close'].pct_change().shift(-1)
        
        # Classification target: up/down
        df['target_direction'] = (df['target_return'] > 0).astype(int)
        
        # Get feature columns (exclude targets and non-features)
        exclude_cols = [
            'target_return', 'target_direction', 'timestamp', 'date', 'time',
            'symbol', 'token_address', 'resolution', 'source',  # Common metadata
            'lunarcrush', 'lunarcrush_id', 'coingecko_id',  # ID columns
            'name', 'slug', 'category', 'description',  # Text columns
            'data_source'  # Added this column to excluded features
        ]
        
        # Get numeric columns only
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        feature_cols = [col for col in numeric_cols if col not in exclude_cols]
        
        # Store feature names
        self.feature_names = feature_cols
        
        # Remove rows with NaN targets
        mask = ~df['target_return'].isna()
        
        # Ensure all features are numeric
        X = df[feature_cols][mask].values.astype(np.float32)
        y_reg = df['target_return'][mask].values
        y_clf = df['target_direction'][mask].values
        
        # Check for any remaining non-numeric values
        if np.any(np.isnan(X)):
            print("⚠️  Warning: NaN values found in features, filling with 0")
            X = np.nan_to_num(X, nan=0.0)
        
        print(f"✅ Features shape: {X.shape}")
        print(f"✅ Feature columns: {len(feature_cols)}")
        print(f"✅ Positive returns: {(y_reg > 0).mean():.1%}")
        
        return X, y_reg, y_clf, feature_cols
    
    def train_regime_classifier(self, X_regime: np.ndarray, y_regime: np.ndarray):
        """Train the regime detection classifier"""
        print("\n🎯 Training Regime Classifier...")
        
        # Time series split
        tscv = TimeSeriesSplit(n_splits=5)
        cv_scores = []
        
        for fold, (train_idx, val_idx) in enumerate(tscv.split(X_regime)):
            X_train, X_val = X_regime[train_idx], X_regime[val_idx]
            y_train, y_val = y_regime[train_idx], y_regime[val_idx]
            
            # Scale features
            X_train_scaled = self.regime_scaler.fit_transform(X_train)
            X_val_scaled = self.regime_scaler.transform(X_val)
            
            # Train model
            train_data = lgb.Dataset(X_train_scaled, label=y_train)
            val_data = lgb.Dataset(X_val_scaled, label=y_val, reference=train_data)
            
            model = lgb.train(
                self.regime_clf_params,
                train_data,
                valid_sets=[val_data],
                num_boost_round=1000,
                callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
            )
            
            # Evaluate
            val_pred = (model.predict(X_val_scaled) > 0.5).astype(int)
            accuracy = accuracy_score(y_val, val_pred)
            cv_scores.append(accuracy)
            
            print(f"   Fold {fold+1}: Accuracy = {accuracy:.3f}")
        
        print(f"✅ CV Accuracy: {np.mean(cv_scores):.3f} (+/- {np.std(cv_scores):.3f})")
        
        # Train final model on all data
        X_scaled = self.regime_scaler.fit_transform(X_regime)
        train_data = lgb.Dataset(X_scaled, label=y_regime)
        
        self.regime_classifier = lgb.train(
            self.regime_clf_params,
            train_data,
            num_boost_round=1000
        )
        
        # Plot feature importance
        if self.regime_feature_names:
            self.plot_feature_importance(
                self.regime_classifier, 
                self.regime_feature_names, 
                "Regime Classifier"
            )
        
        return np.mean(cv_scores)
    
    def train_regime_regressors(self, X: np.ndarray, y: np.ndarray, regimes: np.ndarray):
        """Train separate regressors for high and low volatility regimes"""
        print("\n🎯 Training Regime-Specific Regressors...")
        
        # Split data by regime
        high_vol_mask = regimes == 1
        low_vol_mask = regimes == 0
        
        X_high = X[high_vol_mask]
        y_high = y[high_vol_mask]
        X_low = X[low_vol_mask]
        y_low = y[low_vol_mask]
        
        print(f"   High-Vol samples: {len(X_high)}")
        print(f"   Low-Vol samples: {len(X_low)}")
        
        # Scale features
        X_scaled = self.feature_scaler.fit_transform(X)
        X_high_scaled = X_scaled[high_vol_mask]
        X_low_scaled = X_scaled[low_vol_mask]
        
        # Train high volatility regressor
        print("\n   Training High-Volatility Regressor...")
        train_data_high = lgb.Dataset(X_high_scaled, label=y_high)
        
        self.high_vol_regressor = lgb.train(
            self.regressor_params,
            train_data_high,
            num_boost_round=1000
        )
        
        # Evaluate
        pred_high = self.high_vol_regressor.predict(X_high_scaled)
        rmse_high = np.sqrt(mean_squared_error(y_high, pred_high))
        print(f"   ✅ High-Vol RMSE: {rmse_high:.4f}")
        
        # Plot feature importance for high-vol regressor
        if self.feature_names:
            self.plot_feature_importance(
                self.high_vol_regressor, 
                self.feature_names, 
                "High Volatility Regressor"
            )
        
        # Train low volatility regressor
        print("\n   Training Low-Volatility Regressor...")
        train_data_low = lgb.Dataset(X_low_scaled, label=y_low)
        
        self.low_vol_regressor = lgb.train(
            self.regressor_params,
            train_data_low,
            num_boost_round=1000
        )
        
        # Evaluate
        pred_low = self.low_vol_regressor.predict(X_low_scaled)
        rmse_low = np.sqrt(mean_squared_error(y_low, pred_low))
        print(f"   ✅ Low-Vol RMSE: {rmse_low:.4f}")
        
        # Plot feature importance for low-vol regressor
        if self.feature_names:
            self.plot_feature_importance(
                self.low_vol_regressor, 
                self.feature_names, 
                "Low Volatility Regressor"
            )
        
        return rmse_high, rmse_low
    
    def train_direction_classifier(self, X: np.ndarray, y_clf: np.ndarray, 
                                 regimes: np.ndarray, use_regressor_output: bool = True):
        """Train optional direction classifier on regressor outputs"""
        print("\n🎯 Training Direction Classifier...")
        
        if use_regressor_output:
            # Get predictions from regime-specific regressors
            X_scaled = self.feature_scaler.transform(X)
            predictions = np.zeros(len(X))
            
            # High vol predictions
            high_mask = regimes == 1
            if high_mask.any():
                predictions[high_mask] = self.high_vol_regressor.predict(X_scaled[high_mask])
            
            # Low vol predictions
            low_mask = regimes == 0
            if low_mask.any():
                predictions[low_mask] = self.low_vol_regressor.predict(X_scaled[low_mask])
            
            # Use predictions as features
            X_direction = np.column_stack([predictions, X_scaled])
            direction_feature_names = ['regressor_prediction'] + self.feature_names
            print(f"   Using regressor outputs + original features: {X_direction.shape}")
        else:
            X_direction = self.feature_scaler.transform(X)
            direction_feature_names = self.feature_names
        
        # Time series split
        tscv = TimeSeriesSplit(n_splits=5)
        cv_scores = []
        
        for fold, (train_idx, val_idx) in enumerate(tscv.split(X_direction)):
            X_train, X_val = X_direction[train_idx], X_direction[val_idx]
            y_train, y_val = y_clf[train_idx], y_clf[val_idx]
            
            # Train
            train_data = lgb.Dataset(X_train, label=y_train)
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
            
            model = lgb.train(
                self.direction_clf_params,
                train_data,
                valid_sets=[val_data],
                num_boost_round=1000,
                callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
            )
            
            # Evaluate
            val_pred = (model.predict(X_val) > 0.5).astype(int)
            accuracy = accuracy_score(y_val, val_pred)
            cv_scores.append(accuracy)
            
            print(f"   Fold {fold+1}: Accuracy = {accuracy:.3f}")
        
        print(f"✅ CV Accuracy: {np.mean(cv_scores):.3f} (+/- {np.std(cv_scores):.3f})")
        
        # Train final model with validation set and early stopping
        # Use 80/20 split for final training
        split_idx = int(0.8 * len(X_direction))
        X_train_final = X_direction[:split_idx]
        X_val_final = X_direction[split_idx:]
        y_train_final = y_clf[:split_idx]
        y_val_final = y_clf[split_idx:]
        
        train_data = lgb.Dataset(X_train_final, label=y_train_final)
        val_data = lgb.Dataset(X_val_final, label=y_val_final, reference=train_data)
        
        self.direction_classifier = lgb.train(
            self.direction_clf_params,
            train_data,
            valid_sets=[val_data],
            num_boost_round=1000,
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)]  # Early stopping + less verbose logging
        )
        
        # Evaluate final model on validation set
        final_val_pred = (self.direction_classifier.predict(X_val_final) > 0.5).astype(int)
        final_accuracy = accuracy_score(y_val_final, final_val_pred)
        print(f"✅ Final Model Validation Accuracy: {final_accuracy:.3f}")
        print(f"✅ Final Model Stopped at: {self.direction_classifier.best_iteration} rounds")
        
        # Plot feature importance for direction classifier
        if direction_feature_names:
            self.plot_feature_importance(
                self.direction_classifier, 
                direction_feature_names, 
                "Direction Classifier"
            )
        
        return np.mean(cv_scores)
    
    def save_models(self):
        """Save all trained models and scalers"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = f"{self.symbol}_regime_aware_{timestamp}"
        
        # Create models directory
        os.makedirs('models', exist_ok=True)
        
        # Save models and metadata
        model_data = {
            'regime_classifier': self.regime_classifier,
            'high_vol_regressor': self.high_vol_regressor,
            'low_vol_regressor': self.low_vol_regressor,
            'direction_classifier': self.direction_classifier,
            'feature_scaler': self.feature_scaler,
            'regime_scaler': self.regime_scaler,
            'symbol': self.symbol,
            'timestamp': timestamp,
            'params': {
                'regime_clf': self.regime_clf_params,
                'regressor': self.regressor_params,
                'direction_clf': self.direction_clf_params
            }
        }
        
        model_path = f"models/{base_name}.pkl"
        joblib.dump(model_data, model_path)
        
        print(f"\n💾 Models saved to: {model_path}")
        return model_path
    
    def train_full_stack(self, days: int = 90, vol_threshold: float = 0.75):
        """Train the complete regime-aware model stack"""
        print("\n" + "="*60)
        print("🚀 TRAINING REGIME-AWARE LIGHTGBM STACK")
        print("="*60)
        
        # Load and prepare data
        df = self.load_and_prepare_data(days)
        
        # Prepare features and targets
        X, y_reg, y_clf, feature_names = self.prepare_features_and_targets(df)
        
        # Create regime features and labels
        regime_features_df = self.create_regime_features(df)
        regime_labels = self.create_regime_labels(df, vol_threshold)
        
        # Align with targets
        mask = ~df['target_return'].isna()
        X_regime = regime_features_df[mask].values
        regime_labels = regime_labels[mask]
        
        # 1. Train regime classifier
        regime_accuracy = self.train_regime_classifier(X_regime, regime_labels)
        
        # 2. Train regime-specific regressors
        rmse_high, rmse_low = self.train_regime_regressors(X, y_reg, regime_labels)
        
        # 3. Train direction classifier
        direction_accuracy = self.train_direction_classifier(X, y_clf, regime_labels)
        
        # Save models
        model_path = self.save_models()
        
        # Print summary
        print("\n" + "="*60)
        print("📊 TRAINING SUMMARY")
        print("="*60)
        print(f"✅ Regime Classifier Accuracy: {regime_accuracy:.3f}")
        print(f"✅ High-Vol Regressor RMSE: {rmse_high:.4f}")
        print(f"✅ Low-Vol Regressor RMSE: {rmse_low:.4f}")
        print(f"✅ Direction Classifier Accuracy: {direction_accuracy:.3f}")
        print(f"✅ Models saved to: {model_path}")
        print("="*60)
        
        return {
            'regime_accuracy': regime_accuracy,
            'rmse_high': rmse_high,
            'rmse_low': rmse_low,
            'direction_accuracy': direction_accuracy,
            'model_path': model_path
        }


def main():
    parser = argparse.ArgumentParser(description='Train Regime-Aware LightGBM Stack')
    parser.add_argument('--symbol', required=True, help='Token symbol')
    parser.add_argument('--token-address', required=True, help='Token address')
    parser.add_argument('--days', type=int, default=90, help='Days of training data')
    parser.add_argument('--vol-threshold', type=float, default=0.75, help='Volatility quantile threshold')
    
    args = parser.parse_args()
    
    # Train the model stack
    trainer = RegimeAwareLGBTrainer(args.symbol, args.token_address)
    results = trainer.train_full_stack(args.days, args.vol_threshold)
    
    print("\n✅ Training complete!")


if __name__ == "__main__":
    main() 