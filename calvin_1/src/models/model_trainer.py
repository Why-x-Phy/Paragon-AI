import os
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Union, Any, Tuple
from datetime import datetime

from src.model.ml_model import MLModel
from src.config.config import config
from src.utils.logger import log_manager

logger = log_manager.get_logger("model_trainer")

class ModelTrainer:
    """Train and manage machine learning models for price prediction and trading"""
    
    def __init__(self, model_type: str = None, optimization_target: str = "profit"):
        self.model_type = model_type or config.model_type
        self.optimization_target = optimization_target
        self.ml_model = MLModel(self.model_type, self.optimization_target)
        
        # Create directories if they don't exist
        self.models_dir = os.path.join(os.getcwd(), "models")
        os.makedirs(self.models_dir, exist_ok=True)
    
    def train_model(
        self, 
        X_train: np.ndarray, 
        y_train: np.ndarray,
        X_val: np.ndarray, 
        y_val: np.ndarray,
        model_params: Dict = None
    ) -> Any:
        """
        Train a model with the given data
        
        Args:
            X_train: Training features
            y_train: Training targets
            X_val: Validation features
            y_val: Validation targets
            model_params: Optional parameters for model configuration
            
        Returns:
            Trained model
        """
        logger.info(f"Training {self.model_type} model with optimization target: {self.optimization_target}")
        
        # Build the model
        input_shape = X_train.shape[1:]
        self.ml_model.build_model(input_shape)
        
        # Configure training parameters
        epochs = model_params.get('epochs', 100) if model_params else 100
        batch_size = model_params.get('batch_size', 32) if model_params else 32
        patience = model_params.get('patience', 20) if model_params else 20
        
        # Train the model
        history = self.ml_model.train(
            X_train, y_train,
            X_val, y_val,
            epochs=epochs,
            batch_size=batch_size,
            patience=patience
        )
        
        # Save training history plot
        self.ml_model.plot_training_history(
            history, 
            filename=f"{self.model_type}_{self.optimization_target}_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        
        # Evaluate on validation data
        self.evaluate_model(X_val, y_val)
        
        return self.ml_model.model
    
    def evaluate_model(
        self, 
        X_test: np.ndarray, 
        y_test: np.ndarray,
        include_backtest: bool = True
    ) -> Dict:
        """
        Evaluate the model on test data
        
        Args:
            X_test: Test features
            y_test: Test targets
            include_backtest: Whether to run backtest with the model
            
        Returns:
            Dict with evaluation metrics
        """
        logger.info(f"Evaluating {self.model_type} model")
        
        # Evaluate the model
        metrics = self.ml_model.evaluate(X_test, y_test, include_backtest)
        
        # Save evaluation metrics
        self.ml_model.save_evaluation_metrics(
            metrics, 
            model_name=f"{self.model_type}_{self.optimization_target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        
        # Create a prediction graph
        y_pred = self.ml_model.predict(X_test)
        
        # Plot predictions
        self.ml_model.plot_predictions(
            y_test, y_pred, 
            include_trades=True,
            filename=f"{self.model_type}_{self.optimization_target}_predictions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        
        # Plot backtest results if requested
        if include_backtest:
            self.ml_model.plot_backtest_results(
                y_test, y_pred,
                filename=f"{self.model_type}_{self.optimization_target}_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            )
        
        return metrics
    
    def save_model(self, model, model_name: str = None) -> str:
        """
        Save the model to disk
        
        Args:
            model: Model to save
            model_name: Name for the saved model file
            
        Returns:
            Path to the saved model
        """
        if not model_name:
            model_name = f"{self.model_type}_{self.optimization_target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Save the model
        model_path = self.ml_model.save(model_name)
        logger.info(f"Model saved to {model_path}")
        
        return model_path
    
    def load_model(self, model_path: str) -> Any:
        """
        Load a model from disk
        
        Args:
            model_path: Path to the model file
            
        Returns:
            Loaded model
        """
        self.ml_model.load(model_path)
        logger.info(f"Model loaded from {model_path}")
        
        return self.ml_model.model
    
    def load_latest_model(self, symbol: str = None) -> Any:
        """
        Load the latest model for a given symbol
        
        Args:
            symbol: Symbol to load model for
            
        Returns:
            Loaded model
        """
        # Look for models matching the symbol
        model_files = [f for f in os.listdir(self.models_dir) if f.endswith('.h5')]
        
        if symbol:
            model_files = [f for f in model_files if symbol.lower() in f.lower()]
        
        if not model_files:
            logger.warning(f"No models found for symbol: {symbol}")
            return None
        
        # Get the most recent model
        latest_model = max(model_files, key=lambda f: os.path.getctime(os.path.join(self.models_dir, f)))
        model_path = os.path.join(self.models_dir, latest_model)
        
        logger.info(f"Loading latest model: {model_path}")
        return self.load_model(model_path)
    
    def check_if_retraining_needed(
        self, 
        X_recent: np.ndarray, 
        y_recent: np.ndarray,
        retraining_threshold: float = None
    ) -> bool:
        """
        Check if model needs retraining based on recent performance
        
        Args:
            X_recent: Recent feature data
            y_recent: Recent target data
            retraining_threshold: Performance threshold for retraining
            
        Returns:
            True if retraining is needed, False otherwise
        """
        if self.ml_model.model is None:
            logger.warning("No model loaded, retraining is needed")
            return True
        
        # Evaluate on recent data
        metrics = self.ml_model.evaluate(X_recent, y_recent)
        
        # Check performance against threshold
        threshold = retraining_threshold or config.retraining_threshold
        
        # If using profit optimization, check profit metrics
        if self.optimization_target in ["profit", "combined"]:
            performance_metric = metrics.get('total_return', 0)
            logger.info(f"Current model return: {performance_metric:.2%}, threshold: {threshold:.2%}")
            return performance_metric < threshold
        else:
            # Otherwise check standard accuracy metrics
            r2 = metrics.get('r2', 0)
            logger.info(f"Current model R²: {r2:.4f}, threshold: {threshold:.4f}")
            return r2 < threshold
    
    def get_prediction_with_confidence(
        self, 
        X: np.ndarray, 
        last_price: float
    ) -> Tuple[float, float, int]:
        """
        Get prediction with confidence and trading signal
        
        Args:
            X: Input features
            last_price: Last known price
            
        Returns:
            Tuple of (predicted_price, confidence, signal)
            where signal is -1 (sell), 0 (hold), 1 (buy)
        """
        if self.ml_model.model is None:
            logger.error("No model loaded, cannot make predictions")
            raise ValueError("No model loaded")
        
        # Get prediction
        pred = self.ml_model.predict(np.expand_dims(X, axis=0))[0]
        
        # Calculate predicted return
        pred_return = (pred - last_price) / last_price
        
        # Generate signal
        threshold = 0.005  # 0.5% threshold for action
        if pred_return > threshold:
            signal = 1  # Buy
        elif pred_return < -threshold:
            signal = -1  # Sell
        else:
            signal = 0  # Hold
        
        # Calculate confidence as normalized absolute return
        confidence = min(abs(pred_return) * 20, 1.0)  # Scale to 0-1
        
        return float(pred), float(confidence), int(signal) 