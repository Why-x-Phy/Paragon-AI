import os
import time
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import Dict, List, Optional, Union, Any, Tuple
from datetime import datetime
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model, Model
from tensorflow.keras.layers import Dense, LSTM, GRU, Dropout, BatchNormalization, Input
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
from tensorflow.keras.utils import plot_model

from src.config.config import config
from src.utils.logger import log_manager
from src.model.profit_functions import (
    profit_loss, directional_loss, combined_profit_mse_loss, 
    cumulative_return_metric, win_rate_metric, sharpe_ratio_metric,
    backtest_trades, direction_accuracy, simple_directional_loss,
    simple_backtest_strategy
)

logger = log_manager.get_logger("ml_model")

class MLModel:
    """Machine learning model for price prediction and trading optimization"""
    
    def __init__(self, model_type: str = None, optimization_target: str = "mse"):
        self.model_type = model_type or config.model_type
        self.optimization_target = optimization_target  # "profit", "direction", "combined", "mse", or "simple_directional"
        self.model = None
        
        # Create models directory if it doesn't exist
        self.models_dir = os.path.join(os.getcwd(), "models")
        os.makedirs(self.models_dir, exist_ok=True)
        
        # Check for GPU availability
        self.has_gpu = tf.config.list_physical_devices('GPU')
        if self.has_gpu:
            logger.info(f"GPU is available: {self.has_gpu}")
            # Set memory growth to avoid OOM errors
            for gpu in self.has_gpu:
                tf.config.experimental.set_memory_growth(gpu, True)
        else:
            logger.warning("No GPU found, using CPU for training")
    
    def _get_loss_function(self):
        """Get the appropriate loss function based on optimization target"""
        if self.optimization_target == "profit":
            return profit_loss
        elif self.optimization_target == "direction":
            return directional_loss
        elif self.optimization_target == "combined":
            return combined_profit_mse_loss
        elif self.optimization_target == "simple_directional":
            return simple_directional_loss
        else:  # Default to MSE
            return 'mean_squared_error'
    
    def _get_metrics(self):
        """Get metrics for model training and evaluation"""
        metrics = ['mae']  # Always include MAE for reference
        
        # Add profit-oriented metrics - only use direction accuracy for now
        # The other metrics don't work well with normalized data during training
        if self.optimization_target in ["profit", "direction", "combined"]:
            # Create a custom direction accuracy metric
            # Disable TensorFlow direction accuracy metric - it's misleading with normalized data
            # def custom_direction_accuracy(y_true, y_pred):
            #     return direction_accuracy(y_true, y_pred)
            # 
            # # Set readable name
            # custom_direction_accuracy.__name__ = 'direction_accuracy'
            # 
            # metrics.append(custom_direction_accuracy)
            
            # Note: Direction accuracy is calculated manually in evaluate() method 
            # using actual price changes, not normalized values
            pass
            
        return metrics
    
    def build_lstm_model(
        self, 
        input_shape: Tuple[int, int],
        output_units: int = 1,
        lstm_units: List[int] = [256, 128, 64, 32],  # Deeper network with more units
        dropout_rate: float = 0.4,  # Keep substantial dropout
        use_bidirectional: bool = True  # Enable bidirectional LSTM
    ) -> Model:
        """Build an enhanced LSTM model for time series prediction and trading"""
        
        # Use both L2 and L1 regularization (ElasticNet approach)
        kernel_regularizer = tf.keras.regularizers.l1_l2(l1=0.0001, l2=0.001)
        
        # Use Functional API for more flexibility
        inputs = Input(shape=input_shape)
        x = inputs
        
        # First LSTM layer with return sequences for stacking
        if use_bidirectional:
            x = tf.keras.layers.Bidirectional(
                LSTM(
                    units=lstm_units[0],
                    return_sequences=True,
                    kernel_initializer='glorot_uniform',
                    recurrent_initializer='orthogonal',
                    kernel_regularizer=kernel_regularizer,
                    recurrent_dropout=0.2
                )
            )(x)
        else:
            x = LSTM(
                units=lstm_units[0],
                return_sequences=True,
                kernel_initializer='glorot_uniform',
                recurrent_initializer='orthogonal',
                kernel_regularizer=kernel_regularizer,
                recurrent_dropout=0.2
            )(x)
        
        x = BatchNormalization()(x)
        x = Dropout(dropout_rate)(x)
        
        # Add residual connections between LSTM layers where possible
        for i in range(1, len(lstm_units) - 1):
            # Store previous layer output for residual connection
            previous_output = x
            
            # Add LSTM layer
            if use_bidirectional:
                x = tf.keras.layers.Bidirectional(
                    LSTM(
                        units=lstm_units[i],
                        return_sequences=True,
                        kernel_initializer='glorot_uniform',
                        recurrent_initializer='orthogonal',
                        kernel_regularizer=kernel_regularizer,
                        recurrent_dropout=0.2
                    )
                )(x)
            else:
                x = LSTM(
                    units=lstm_units[i],
                    return_sequences=True,
                    kernel_initializer='glorot_uniform',
                    recurrent_initializer='orthogonal',
                    kernel_regularizer=kernel_regularizer,
                    recurrent_dropout=0.2
                )(x)
                
            x = BatchNormalization()(x)
            x = Dropout(dropout_rate)(x)
            
            # Add residual connection if shapes match
            if previous_output.shape[-1] == x.shape[-1]:
                x = tf.keras.layers.Add()([x, previous_output])
        
        # Final LSTM layer (no return sequences)
        if use_bidirectional:
            x = tf.keras.layers.Bidirectional(
                LSTM(
                    units=lstm_units[-1],
                    return_sequences=False,
                    kernel_initializer='glorot_uniform',
                    recurrent_initializer='orthogonal',
                    kernel_regularizer=kernel_regularizer,
                    recurrent_dropout=0.2
                )
            )(x)
        else:
            x = LSTM(
                units=lstm_units[-1],
                return_sequences=False,
                kernel_initializer='glorot_uniform',
                recurrent_initializer='orthogonal',
                kernel_regularizer=kernel_regularizer,
                recurrent_dropout=0.2
            )(x)
            
        x = BatchNormalization()(x)
        x = Dropout(dropout_rate)(x)
        
        # Add multiple dense layers with decreasing units for better feature extraction
        x = Dense(64, activation='relu', kernel_regularizer=kernel_regularizer)(x)
        x = BatchNormalization()(x)
        x = Dropout(0.3)(x)
        
        x = Dense(32, activation='relu', kernel_regularizer=kernel_regularizer)(x)
        x = BatchNormalization()(x)
        x = Dropout(0.2)(x)
        
        # Output layer
        outputs = Dense(units=output_units)(x)
        
        # Create model
        model = Model(inputs=inputs, outputs=outputs)
        
        # Compile with appropriate loss function and metrics
        model.compile(
            optimizer=Adam(learning_rate=0.0005, clipnorm=1.0),
            loss=self._get_loss_function(),
            metrics=self._get_metrics()
        )
        
        return model
    
    def build_gru_model(
        self, 
        input_shape: Tuple[int, int],
        output_units: int = 1,
        gru_units: List[int] = [64, 32],
        dropout_rate: float = 0.2
    ) -> Model:
        """Build a GRU model for time series prediction and trading"""
        model = Sequential()
        
        # First GRU layer with return sequences for stacking
        model.add(GRU(
            units=gru_units[0],
            return_sequences=len(gru_units) > 1,
            input_shape=input_shape
        ))
        model.add(BatchNormalization())
        model.add(Dropout(dropout_rate))
        
        # Additional GRU layers
        for i in range(1, len(gru_units)):
            model.add(GRU(
                units=gru_units[i],
                return_sequences=i < len(gru_units) - 1
            ))
            model.add(BatchNormalization())
            model.add(Dropout(dropout_rate))
        
        # Output layer
        model.add(Dense(units=output_units))
        
        # Compile the model with appropriate loss function and metrics
        model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss=self._get_loss_function(),
            metrics=self._get_metrics()
        )
        
        return model
    
    def build_transformer_model(
        self, 
        input_shape: Tuple[int, int],
        output_units: int = 1,
        d_model: int = 64,
        num_heads: int = 4,
        dropout_rate: float = 0.2
    ) -> Model:
        """Build a Transformer model for time series prediction and trading"""
        # Input layer
        inputs = Input(shape=input_shape)
        
        # Simple transformer model
        x = tf.keras.layers.LayerNormalization(epsilon=1e-6)(inputs)
        x = tf.keras.layers.MultiHeadAttention(
            key_dim=d_model // num_heads, 
            num_heads=num_heads, 
            dropout=dropout_rate
        )(x, x)
        
        # Add & Norm
        x = tf.keras.layers.Add()([x, inputs])
        x = tf.keras.layers.LayerNormalization(epsilon=1e-6)(x)
        
        # Feed Forward
        x = tf.keras.layers.Dense(d_model * 4, activation='relu')(x)
        x = tf.keras.layers.Dropout(dropout_rate)(x)
        x = tf.keras.layers.Dense(d_model)(x)
        
        # Add & Norm
        x = tf.keras.layers.Add()([x, x])
        x = tf.keras.layers.LayerNormalization(epsilon=1e-6)(x)
        
        # Global average pooling to reduce sequence dimension
        x = tf.keras.layers.GlobalAveragePooling1D()(x)
        
        # Output layer
        outputs = tf.keras.layers.Dense(output_units)(x)
        
        # Create and compile model with appropriate loss function and metrics
        model = tf.keras.Model(inputs=inputs, outputs=outputs)
        model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss=self._get_loss_function(),
            metrics=self._get_metrics()
        )
        
        return model
    
    def build_model(self, input_shape: Tuple[int, int], use_bidirectional: bool = True) -> None:
        """Build the appropriate model based on model_type"""
        logger.info(f"Building {self.model_type} model with input shape {input_shape}, optimization target: {self.optimization_target}")
        
        if self.model_type == 'lstm':
            self.model = self.build_lstm_model(input_shape, use_bidirectional=use_bidirectional)
        elif self.model_type == 'gru':
            self.model = self.build_gru_model(input_shape)
        elif self.model_type == 'transformer':
            self.model = self.build_transformer_model(input_shape)
        else:
            logger.error(f"Unsupported model type: {self.model_type}")
            raise ValueError(f"Unsupported model type: {self.model_type}")
        
        logger.info(f"Model built successfully: {self.model.summary()}")
    
    def train(
        self, 
        X_train: np.ndarray, 
        y_train: np.ndarray,
        X_val: np.ndarray, 
        y_val: np.ndarray,
        epochs: int = 100,
        batch_size: int = 32,
        model_name: str = None
    ) -> Dict:
        """
        Train the model
        
        Args:
            X_train: Training features
            y_train: Training targets
            X_val: Validation features
            y_val: Validation targets
            epochs: Number of training epochs
            batch_size: Batch size for training
            model_name: Name for the saved model
            
        Returns:
            Training history
        """
        if self.model is None:
            raise ValueError("No model has been built yet. Call build_model() first.")
        
        # Set up model checkpoint callback
        if model_name is None:
            model_name = f"{self.model_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
        checkpoint_path = os.path.join(self.models_dir, f"{model_name}.h5")
        checkpoint = ModelCheckpoint(
            checkpoint_path,
            monitor='val_loss',
            verbose=1,
            save_best_only=True,
            mode='min'
        )
        
        # Set up early stopping callback
        early_stopping = EarlyStopping(
            monitor='val_loss',
            patience=20,
            verbose=1,
            restore_best_weights=True
        )
        
        # Set up learning rate reduction callback
        reduce_lr = ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.5,
            patience=5,
            min_lr=1e-6,
            verbose=1
        )
        
        # Print info about model training
        total_params = self.model.count_params()
        print(f"\n{'-'*50}")
        print(f"TRAINING MODEL: {model_name}")
        print(f"Model Type: {self.model_type}")
        print(f"Optimization Target: {self.optimization_target}")
        print(f"Total Parameters: {total_params:,}")
        print(f"Training Samples: {len(X_train):,}")
        print(f"Validation Samples: {len(X_val):,}")
        print(f"Epochs: {epochs}")
        print(f"Batch Size: {batch_size}")
        print(f"Saving to: {checkpoint_path}")
        print(f"{'-'*50}\n")
        
        # Train the model
        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=[checkpoint, early_stopping, reduce_lr],
            verbose=1
        )
        
        # Load the best model from checkpoints
        from src.model.profit_functions import (
            profit_loss, directional_loss, combined_profit_mse_loss, 
            direction_accuracy, simple_directional_loss, direction_focused_loss,
            balanced_directional_loss, magnitude_constrained_loss, 
            variance_encouraging_loss, anti_collapse_loss, robust_directional_loss
        )
        
        self.model = load_model(
            checkpoint_path,
            custom_objects={
                'profit_loss': profit_loss,
                'directional_loss': directional_loss,
                'combined_profit_mse_loss': combined_profit_mse_loss,
                'direction_accuracy': direction_accuracy,
                'custom_direction_accuracy': direction_accuracy,  # Alias for compatibility
                'simple_directional_loss': simple_directional_loss,
                'direction_focused_loss': direction_focused_loss,
                'balanced_directional_loss': balanced_directional_loss,
                'magnitude_constrained_loss': magnitude_constrained_loss,
                'variance_encouraging_loss': variance_encouraging_loss,
                'anti_collapse_loss': anti_collapse_loss,
                'robust_directional_loss': robust_directional_loss
            }
        )
        
        # Print training results summary
        val_loss = min(history.history['val_loss'])
        last_lr = history.history['lr'][-1]
        
        # Calculate final directional accuracy on validation set
        y_pred_val = self.model.predict(X_val)
        dir_acc = 0
        total_comparisons = 0
        
        # Calculate direction accuracy for percentage change predictions
        for i in range(len(y_val)):
            # y_val[i] and y_pred_val[i] are already percentage changes
            actual_change = y_val[i]        # This IS the percentage change
            predicted_change = y_pred_val[i] # This IS the percentage change
            
            # Skip if actual change is essentially zero (no clear direction)
            if abs(actual_change) < 1e-6:
                continue
                
            # Check if signs of percentage changes match (both up or both down)
            if np.sign(actual_change) == np.sign(predicted_change):
                dir_acc += 1
            total_comparisons += 1
            
        # Calculate direction accuracy
        dir_acc = dir_acc / total_comparisons if total_comparisons > 0 else 0
        
        print(f"\n{'-'*50}")
        print(f"TRAINING COMPLETED: {model_name}")
        print(f"Best Validation Loss: {val_loss:.6f}")
        print(f"Final Learning Rate: {last_lr:.6e}")
        print(f"Final Direction Accuracy: {dir_acc*100:.2f}%")
        print(f"Model saved to: {checkpoint_path}")
        print(f"{'-'*50}\n")
        
        return history.history
    
    def evaluate(
        self, 
        X_test: np.ndarray, 
        y_test: np.ndarray, 
        include_backtest: bool = True,
        resolution: str = None,
        ohlcv_data: pd.DataFrame = None,
        auto_visualize: bool = True
    ) -> Dict:
        """
        Evaluate model performance on test data
        
        Args:
            X_test: Test input features
            y_test: Test target values
            include_backtest: Whether to include backtest results
            resolution: Time resolution of the data (e.g., "1m", "5m", "1h", "1d")
            ohlcv_data: Optional OHLCV DataFrame for candlestick visualization
            auto_visualize: Whether to automatically generate visualization
            
        Returns:
            Dictionary of evaluation metrics
        """
        if self.model is None:
            raise ValueError("No model has been built or loaded yet")
            
        # Get model predictions
        y_pred = self.model.predict(X_test)
        
        # Calculate standard regression metrics
        mse = mean_squared_error(y_test, y_pred)
        rmse = np.sqrt(mse)
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        
        # Calculate directional accuracy manually - TRULY CORRECT VERSION
        # Since our model predicts percentage changes (not absolute prices),
        # we should compare the signs of the percentage changes directly
        correct_direction = 0
        total_comparisons = 0
        
        for i in range(len(y_test)):
            # y_test[i] and y_pred[i] are already percentage changes
            actual_change = y_test[i]    # This IS the percentage change
            predicted_change = y_pred[i] # This IS the percentage change
            
            # Skip if actual change is essentially zero (no clear direction)
            if abs(actual_change) < 1e-6:
                continue
                
            # Check if signs of percentage changes match (both up or both down)
            if np.sign(actual_change) == np.sign(predicted_change):
                correct_direction += 1
            total_comparisons += 1
            
        # Calculate direction accuracy
        dir_acc = correct_direction / total_comparisons if total_comparisons > 0 else 0
        
        # Package metrics into dictionary
        metrics = {
            'mse': mse,
            'rmse': rmse,
            'mae': mae,
            'r2': r2,
            'direction_accuracy': dir_acc
        }
        
        # Run backtest if requested
        if include_backtest:
            # Get resolution from config if not provided
            if resolution is None:
                resolution = config.resolution if hasattr(config, 'resolution') else "1d"
                
            backtest_metrics = self.run_simple_backtest(y_test, y_pred, resolution=resolution)
            metrics.update(backtest_metrics)
            
            # Generate candlestick chart if OHLCV data is provided and auto_visualize is enabled
            if auto_visualize and ohlcv_data is not None:
                # Generate a filename based on model type and timestamp
                model_name = getattr(self, 'symbol', self.model_type)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                chart_filename = f"{model_name}_backtest_{timestamp}.png"
                
                # Generate candlestick chart with buy/sell signals
                chart_path = self.plot_candlestick_backtest(
                    ohlcv_data=ohlcv_data,
                    y_true=y_test,
                    y_pred=y_pred,
                    filename=chart_filename,
                    title=f"{model_name} Backtest Results ({resolution})"
                )
                
                if chart_path:
                    logger.info(f"Candlestick backtest chart generated: {chart_path}")
                    metrics['candlestick_chart'] = chart_path
        
        # Print a nicely formatted evaluation summary
        self._print_evaluation_summary(metrics)
            
        return metrics
        
    def _print_evaluation_summary(self, metrics: Dict) -> None:
        """Print nicely formatted evaluation summary"""
        print("\n" + "="*50)
        print("MODEL EVALUATION SUMMARY")
        print("="*50)
        
        # Convert numpy values to scalars for formatting
        mse = float(metrics['mse']) if isinstance(metrics['mse'], np.ndarray) else metrics['mse']
        rmse = float(metrics['rmse']) if isinstance(metrics['rmse'], np.ndarray) else metrics['rmse']
        mae = float(metrics['mae']) if isinstance(metrics['mae'], np.ndarray) else metrics['mae']
        r2 = float(metrics['r2']) if isinstance(metrics['r2'], np.ndarray) else metrics['r2']
        dir_acc = float(metrics['direction_accuracy']) if isinstance(metrics['direction_accuracy'], np.ndarray) else metrics['direction_accuracy']
        
        # Format standard metrics
        print(f"MSE:                 {mse:.6f}")
        print(f"RMSE:                {rmse:.6f}")
        print(f"MAE:                 {mae:.6f}")
        print(f"R² Score:            {r2:.6f}")
        print(f"Direction Accuracy:  {dir_acc*100:.2f}%")
        
        # Print backtest metrics if available
        if 'total_return' in metrics:
            print("\n" + "-"*50)
            print("BACKTEST RESULTS")
            print("-"*50)
            
            # Handle both naming conventions for total trades
            total_trades = metrics.get('total_trades', metrics.get('number_of_trades', 0))
            
            # Convert all backtest metrics to scalars and handle NaN/Inf values
            def safe_float(value):
                try:
                    if isinstance(value, np.ndarray):
                        value = value.item()
                    float_val = float(value)
                    if np.isnan(float_val) or np.isinf(float_val):
                        return 0.0
                    return float_val
                except (ValueError, TypeError):
                    return 0.0
            
            # Convert all metrics using safe_float
            total_return = safe_float(metrics['total_return'])
            annualized_return = safe_float(metrics.get('annualized_return', 0))
            avg_daily_return = safe_float(metrics.get('avg_daily_return', 0))
            periods_per_day = safe_float(metrics.get('periods_per_day', 1))
            max_drawdown = safe_float(metrics.get('max_drawdown', 0))
            win_rate = safe_float(metrics.get('win_rate', 0))
            profit_factor = safe_float(metrics.get('profit_factor', 0))
            sharpe_ratio = safe_float(metrics.get('sharpe_ratio', 0))
            resolution = metrics.get('resolution', '1d')
            
            # Get initial and final values - assume 10000 initial if not provided
            initial_value = safe_float(metrics.get('initial_value', 10000.0))
            final_value = safe_float(metrics.get('final_value', initial_value * (1 + total_return)))
            
            print(f"Resolution:          {resolution} ({periods_per_day:.2f} periods/day)")
            print(f"Initial Portfolio:   ${initial_value:.2f}")
            print(f"Final Portfolio:     ${final_value:.2f}")
            print(f"Total Return:        {total_return*100:.2f}%")
            print(f"Avg Daily Return:    {avg_daily_return*100:.4f}%")
            print(f"Annualized Return:   {annualized_return*100:.2f}%  (calculated as (1+r_daily)^365-1)")
            print(f"Max Drawdown:        {max_drawdown*100:.2f}%")
            print(f"Win Rate:            {win_rate*100:.2f}%")
            print(f"Profit Factor:       {profit_factor:.2f}")
            print(f"Sharpe Ratio:        {sharpe_ratio:.2f}")
            print(f"Total Trades:        {total_trades}")
            
            # Print exit reason statistics if available
            if 'take_profit_count' in metrics:
                take_profit_count = int(metrics.get('take_profit_count', 0))
                stop_loss_count = int(metrics.get('stop_loss_count', 0))
                prediction_count = int(metrics.get('prediction_exit_count', 0))
                
                # Only print if we have trades
                if take_profit_count + stop_loss_count + prediction_count > 0:
                    print("\nExit Reasons:")
                    
                    if take_profit_count > 0:
                        tp_win_rate = safe_float(metrics.get('take_profit_win_rate', 0))
                        print(f"  Take Profit:        {take_profit_count} trades ({tp_win_rate*100:.1f}% win rate)")
                        
                    if stop_loss_count > 0:
                        sl_win_rate = safe_float(metrics.get('stop_loss_win_rate', 0))
                        print(f"  Stop Loss:          {stop_loss_count} trades ({sl_win_rate*100:.1f}% win rate)")
                        
                    if prediction_count > 0:
                        pred_win_rate = safe_float(metrics.get('prediction_win_rate', 0))
                        print(f"  Prediction Signal:  {prediction_count} trades ({pred_win_rate*100:.1f}% win rate)")
            
            print(f"\nNote: Prices in the model are normalized values, not actual dollar prices.")
        
        print("="*50 + "\n")
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions with the trained model"""
        if self.model is None:
            logger.error("Model not initialized. Call build_model() and train() first.")
            raise ValueError("Model not initialized")
        
        return self.model.predict(X)
    
    def get_trade_signals(self, X: np.ndarray, last_prices: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Generate trading signals from model predictions
        
        Args:
            X: Input features
            last_prices: Last known prices for each sequence
            
        Returns:
            Tuple of (predictions, signals, confidences)
            where signals are -1 (sell), 0 (hold), 1 (buy)
        """
        if len(X) != len(last_prices):
            raise ValueError("X and last_prices must have the same length")
        
        # Get predictions
        predictions = self.predict(X)
        
        # Calculate predicted returns
        pred_returns = (predictions - last_prices) / last_prices
        
        # Generate signals (-1: sell, 0: hold, 1: buy)
        # Using a threshold of 0.5% to filter out noise
        threshold = 0.005
        signals = np.zeros_like(pred_returns)
        signals[pred_returns > threshold] = 1
        signals[pred_returns < -threshold] = -1
        
        # Calculate confidence as normalized absolute return
        # Higher predicted return = higher confidence
        confidences = np.abs(pred_returns)
        
        return predictions, signals, confidences
    
    def save(self, model_name: str = None) -> str:
        """Save the model to disk"""
        if self.model is None:
            logger.error("Model not initialized. Nothing to save.")
            raise ValueError("Model not initialized")
        
        if not model_name:
            model_name = f"{self.model_type}_{self.optimization_target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        model_path = os.path.join(self.models_dir, f"{model_name}.h5")
        self.model.save(model_path)
        
        # Save model configuration
        config_path = os.path.join(self.models_dir, f"{model_name}_config.json")
        model_config = {
            'model_type': self.model_type,
            'optimization_target': self.optimization_target,
            'input_shape': self.model.input_shape[1:],
            'saved_at': datetime.now().isoformat()
        }
        with open(config_path, 'w') as f:
            json.dump(model_config, f)
        
        logger.info(f"Model saved to {model_path}")
        return model_path
    
    def load(self, model_path: str) -> None:
        """Load a saved model from disk"""
        if not os.path.exists(model_path):
            logger.error(f"Model file not found: {model_path}")
            raise FileNotFoundError(f"Model file not found: {model_path}")
        
        # Temporarily set optimization_target to MSE to prevent errors in custom loss functions
        original_target = self.optimization_target
        self.optimization_target = "mse"
        
        # Create custom_objects dictionary with our custom functions
        from src.model.profit_functions import (
            profit_loss, directional_loss, combined_profit_mse_loss, 
            cumulative_return_metric, win_rate_metric, sharpe_ratio_metric,
            direction_accuracy, simple_directional_loss, direction_focused_loss,
            balanced_directional_loss, magnitude_constrained_loss, 
            variance_encouraging_loss, anti_collapse_loss, robust_directional_loss
        )
        
        custom_objects = {
            'profit_loss': profit_loss,
            'directional_loss': directional_loss,
            'combined_profit_mse_loss': combined_profit_mse_loss,
            'cumulative_return_metric': cumulative_return_metric,
            'win_rate_metric': win_rate_metric,
            'sharpe_ratio_metric': sharpe_ratio_metric,
            'direction_accuracy': direction_accuracy,
            'simple_directional_loss': simple_directional_loss,
            'direction_focused_loss': direction_focused_loss,
            'balanced_directional_loss': balanced_directional_loss,
            'magnitude_constrained_loss': magnitude_constrained_loss,
            'variance_encouraging_loss': variance_encouraging_loss,
            'anti_collapse_loss': anti_collapse_loss,
            'robust_directional_loss': robust_directional_loss
        }
        
        # Load the model with custom objects
        with tf.keras.utils.custom_object_scope(custom_objects):
            self.model = load_model(model_path)
        
        # Try to load model configuration
        config_path = model_path.replace('.h5', '_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                model_config = json.load(f)
                self.model_type = model_config.get('model_type', 'unknown')
                self.optimization_target = model_config.get('optimization_target', original_target)
        else:
            self.optimization_target = original_target
        
        logger.info(f"Model loaded from {model_path} with optimization_target: {self.optimization_target}")
    
    def plot_training_history(self, history: Dict, filename: str = None) -> None:
        """Plot training history"""
        plt.figure(figsize=(15, 12))
        
        # Plot loss
        plt.subplot(3, 2, 1)
        plt.plot(history['loss'], label='Training Loss')
        plt.plot(history['val_loss'], label='Validation Loss')
        plt.title('Loss')
        plt.xlabel('Epochs')
        plt.ylabel('Loss')
        plt.legend()
        plt.grid(True)
        
        # Plot MAE
        plt.subplot(3, 2, 2)
        plt.plot(history['mae'], label='Training MAE')
        plt.plot(history['val_mae'], label='Validation MAE')
        plt.title('Mean Absolute Error')
        plt.xlabel('Epochs')
        plt.ylabel('MAE')
        plt.legend()
        plt.grid(True)
        
        # Plot profit metrics if available
        if 'cumulative_return_metric' in history:
            plt.subplot(3, 2, 3)
            plt.plot(history['cumulative_return_metric'], label='Training Return')
            plt.plot(history['val_cumulative_return_metric'], label='Validation Return')
            plt.title('Cumulative Return')
            plt.xlabel('Epochs')
            plt.ylabel('Return')
            plt.legend()
            plt.grid(True)
            
            plt.subplot(3, 2, 4)
            plt.plot(history['win_rate_metric'], label='Training Win Rate')
            plt.plot(history['val_win_rate_metric'], label='Validation Win Rate')
            plt.title('Win Rate')
            plt.xlabel('Epochs')
            plt.ylabel('Win Rate')
            plt.legend()
            plt.grid(True)
            
            plt.subplot(3, 2, 5)
            plt.plot(history['sharpe_ratio_metric'], label='Training Sharpe')
            plt.plot(history['val_sharpe_ratio_metric'], label='Validation Sharpe')
            plt.title('Sharpe Ratio')
            plt.xlabel('Epochs')
            plt.ylabel('Sharpe Ratio')
            plt.legend()
            plt.grid(True)
        
        plt.tight_layout()
        
        if filename:
            # Save to plots/training directory
            plots_dir = os.path.join(os.path.dirname(self.models_dir), 'plots', 'training')
            os.makedirs(plots_dir, exist_ok=True)
            file_path = os.path.join(plots_dir, filename)
            plt.savefig(file_path)
            logger.info(f"Training history plot saved to {file_path}")
        else:
            plt.show()
    
    def plot_predictions(
        self, 
        y_true: np.ndarray, 
        y_pred: np.ndarray, 
        include_trades: bool = True,
        filename: str = None
    ) -> None:
        """
        Plot predictions vs actual values, with optional trade markers
        
        Args:
            y_true: True price values
            y_pred: Predicted price values
            include_trades: Whether to include trade markers
            filename: Optional filename to save the plot
        """
        plt.figure(figsize=(15, 8))
        
        # Plot prices
        plt.subplot(2, 1, 1)
        plt.plot(y_true, label='Actual')
        plt.plot(y_pred, label='Predicted')
        
        # Add trade markers if requested
        if include_trades:
            # Generate trade signals
            signals = np.zeros(len(y_true))
            for i in range(1, len(y_true)):
                pred_return = (y_pred[i] - y_true[i-1]) / y_true[i-1]
                if pred_return > 0.005:  # Buy threshold
                    signals[i] = 1
                elif pred_return < -0.005:  # Sell threshold
                    signals[i] = -1
            
            # Plot buy signals (1)
            buy_indices = np.where(signals == 1)[0]
            if len(buy_indices) > 0:
                plt.scatter(buy_indices, y_true[buy_indices], marker='^', color='green', s=100, label='Buy')
            
            # Plot sell signals (-1)
            sell_indices = np.where(signals == -1)[0]
            if len(sell_indices) > 0:
                plt.scatter(sell_indices, y_true[sell_indices], marker='v', color='red', s=100, label='Sell')
        
        plt.title('Price Prediction vs Actual')
        plt.xlabel('Time Step')
        plt.ylabel('Price')
        plt.legend()
        plt.grid(True)
        
        # Plot returns (percentage change)
        plt.subplot(2, 1, 2)
        actual_returns = np.zeros(len(y_true))
        pred_returns = np.zeros(len(y_true))
        
        for i in range(1, len(y_true)):
            actual_returns[i] = (y_true[i] - y_true[i-1]) / y_true[i-1] * 100
            pred_returns[i] = (y_pred[i] - y_true[i-1]) / y_true[i-1] * 100
        
        plt.plot(actual_returns, label='Actual Returns %')
        plt.plot(pred_returns, label='Predicted Returns %')
        plt.title('Price Returns (Percentage Change)')
        plt.xlabel('Time Step')
        plt.ylabel('Return %')
        plt.legend()
        plt.grid(True)
        
        plt.tight_layout()
        
        if filename:
            # Save to plots/training directory
            plots_dir = os.path.join(os.path.dirname(self.models_dir), 'plots', 'training')
            os.makedirs(plots_dir, exist_ok=True)
            file_path = os.path.join(plots_dir, filename)
            plt.savefig(file_path)
            logger.info(f"Predictions plot saved to {file_path}")
        else:
            plt.show()
    
    def plot_backtest_results(
        self, 
        y_true: np.ndarray, 
        y_pred: np.ndarray,
        transaction_cost_pct: float = 0.001,
        filename: str = None
    ) -> None:
        """
        Plot backtest results
        
        Args:
            y_true: True price values
            y_pred: Predicted price values
            transaction_cost_pct: Trading fee percentage
            filename: Optional filename to save the plot
        """
        backtest_results = backtest_trades(y_true, y_pred, transaction_cost_pct)
        
        plt.figure(figsize=(15, 10))
        
        # Plot prices with trades
        plt.subplot(3, 1, 1)
        plt.plot(y_true, label='Actual Price')
        
        # Plot buy trades
        buy_trades = [t for t in backtest_results['trades'] if t['action'] == 'buy']
        if buy_trades:
            buy_timestamps = [t['timestamp'] for t in buy_trades]
            buy_prices = [t['price'] for t in buy_trades]
            plt.scatter(buy_timestamps, buy_prices, marker='^', color='green', s=100, label='Buy')
        
        # Plot sell trades
        sell_trades = [t for t in backtest_results['trades'] if t['action'] == 'sell']
        if sell_trades:
            sell_timestamps = [t['timestamp'] for t in sell_trades]
            sell_prices = [t['price'] for t in sell_trades]
            plt.scatter(sell_timestamps, sell_prices, marker='v', color='red', s=100, label='Sell')
        
        plt.title('Price Chart with Trades')
        plt.xlabel('Time Step')
        plt.ylabel('Price')
        plt.legend()
        plt.grid(True)
        
        # Plot portfolio value
        plt.subplot(3, 1, 2)
        plt.plot(backtest_results['portfolio_value'], label='Portfolio Value')
        
        # Add buy-and-hold line for comparison
        buy_hold_values = [y_true[0]]
        for i in range(1, len(y_true)):
            buy_hold_values.append(buy_hold_values[0] * (y_true[i] / y_true[0]))
        plt.plot(buy_hold_values, label='Buy & Hold', linestyle='--')
        
        plt.title('Portfolio Value vs Buy & Hold')
        plt.xlabel('Time Step')
        plt.ylabel('Value ($)')
        plt.legend()
        plt.grid(True)
        
        # Plot trade profits
        plt.subplot(3, 1, 3)
        trade_profits = [t.get('profit', 0) for t in backtest_results['trades'] if 'profit' in t]
        if trade_profits:
            plt.bar(range(len(trade_profits)), trade_profits)
            plt.axhline(y=0, color='r', linestyle='-')
            plt.title('Trade Profits/Losses')
            plt.xlabel('Trade Number')
            plt.ylabel('Profit/Loss ($)')
            plt.grid(True)
        
        # Add text with backtest summary
        plt.figtext(
            0.5, 0.01, 
            f"Total Return: {backtest_results['total_return']:.2%} | "
            f"Buy & Hold: {backtest_results['buy_hold_return']:.2%} | "
            f"Win Rate: {backtest_results['win_rate']:.2%} | "
            f"Trades: {backtest_results['total_trades']}",
            ha='center', fontsize=12, bbox=dict(facecolor='white', alpha=0.8)
        )
        
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        
        if filename:
            # Save to plots/backtests directory
            plots_dir = os.path.join(os.path.dirname(self.models_dir), 'plots', 'backtests')
            os.makedirs(plots_dir, exist_ok=True)
            file_path = os.path.join(plots_dir, filename)
            plt.savefig(file_path)
            logger.info(f"Backtest results plot saved to {file_path}")
        else:
            plt.show()
    
    def check_model_performance(
        self, 
        performance_threshold: float = None,
        metric: str = 'total_return'
    ) -> bool:
        """
        Check if model performance is above threshold
        
        Args:
            performance_threshold: Threshold value to consider the model good enough
            metric: Metric to check ('total_return', 'win_rate', 'r2', etc.)
            
        Returns:
            True if model performance is above threshold, False otherwise
        """
        threshold = performance_threshold or config.retraining_threshold
        
        # Get latest evaluation metrics
        metrics_path = os.path.join(self.models_dir, 'latest_metrics.json')
        if os.path.exists(metrics_path):
            with open(metrics_path, 'r') as f:
                metrics = json.load(f)
                
            value = metrics.get(metric, 0)
            logger.info(f"Current model {metric}: {value}, threshold: {threshold}")
            
            return value >= threshold
        
        logger.warning("No evaluation metrics found, cannot check model performance")
        return False
        
    def save_evaluation_metrics(self, metrics: Dict, model_name: str = 'latest') -> None:
        """Save evaluation metrics to disk"""
        metrics_path = os.path.join(self.models_dir, f'{model_name}_metrics.json')
        with open(metrics_path, 'w') as f:
            json.dump(metrics, f)
        
        # Also save as latest metrics
        latest_path = os.path.join(self.models_dir, 'latest_metrics.json')
        with open(latest_path, 'w') as f:
            json.dump(metrics, f)
        
        logger.info(f"Evaluation metrics saved to {metrics_path}")
    
    def get_latest_model_path(self) -> Optional[str]:
        """Get the path to the latest model file"""
        model_files = [f for f in os.listdir(self.models_dir) if f.endswith('.h5')]
        
        if not model_files:
            return None
        
        # Sort by creation time (newest first)
        model_files.sort(key=lambda x: os.path.getctime(os.path.join(self.models_dir, x)), reverse=True)
        
        latest_model = model_files[0]
        return os.path.join(self.models_dir, latest_model)
    
    def run_simple_backtest(
        self, 
        y_true: np.ndarray, 
        y_pred: np.ndarray,
        verbosity: int = 0,
        resolution: str = None
    ) -> Dict:
        """
        Run a simple backtesting strategy focused on directional accuracy
        
        Args:
            y_true: True price values
            y_pred: Predicted price values
            verbosity: Level of output detail (0=minimal, 1=medium, 2=full)
            resolution: Time resolution of the data (e.g., "1m", "5m", "1h", "1d")
            
        Returns:
            Dictionary with backtest results
        """
        logger.info("Running simple backtest strategy")
        
        # Convert to numpy arrays if they're tensors
        if isinstance(y_true, tf.Tensor):
            y_true = y_true.numpy()
        if isinstance(y_pred, tf.Tensor):
            y_pred = y_pred.numpy()
            
        # Ensure arrays are float64 for maximum precision
        y_true = np.array(y_true, dtype=np.float64).flatten()
        y_pred = np.array(y_pred, dtype=np.float64).flatten()
        
        # Ensure no zeros or NaN values that could cause division errors
        epsilon = np.finfo(np.float64).eps
        y_true = np.maximum(y_true, epsilon)
        
        # Replace any NaN or inf values
        y_true = np.nan_to_num(y_true, nan=epsilon, posinf=1e9, neginf=epsilon)
        y_pred = np.nan_to_num(y_pred, nan=epsilon, posinf=1e9, neginf=epsilon)
        
        # Ensure arrays have the same length
        if len(y_true) != len(y_pred):
            logger.warning(f"Length mismatch: y_true ({len(y_true)}) vs y_pred ({len(y_pred)})")
            # Truncate to the shorter length
            min_len = min(len(y_true), len(y_pred))
            y_true = y_true[:min_len]
            y_pred = y_pred[:min_len]
            
        # Run the backtest
        try:
            from src.model.profit_functions import simple_backtest_strategy
            
            # Get resolution from config if not provided
            if resolution is None:
                resolution = config.resolution if hasattr(config, 'resolution') else "1d"
            
            # Log the resolution being used - preserve original case exactly as passed
            logger.info(f"Using resolution: {resolution} (original case preserved)")
            
            # Run backtest with appropriate parameters - pass the resolution exactly as given
            results = simple_backtest_strategy(
                y_true, 
                y_pred, 
                include_detailed_trades=verbosity > 1, 
                verbosity=verbosity,
                resolution=resolution
            )
            
            # Ensure all results are Python scalars for correct logging/display
            # Convert any numpy types to Python types
            def safe_float(value):
                try:
                    if isinstance(value, np.ndarray):
                        value = value.item()
                    float_val = float(value)
                    if np.isnan(float_val) or np.isinf(float_val):
                        return 0.0
                    return float_val
                except (ValueError, TypeError):
                    return 0.0
                    
            total_return = safe_float(results['total_return'])
            buy_hold_return = safe_float(results['buy_hold_return'])
            win_rate = safe_float(results['win_rate'])
            final_value = safe_float(results['final_value'])
            annualized_return = safe_float(results['annualized_return'])
            avg_daily_return = safe_float(results.get('avg_daily_return', 0.0))
            periods_per_day = safe_float(results.get('periods_per_day', 1.0))
            
            # Make sure trades count is an integer
            num_trades = int(results.get('number_of_trades', 0))
            
            # Print summary with scalar values (based on verbosity)
            if verbosity >= 0:
                logger.info(f"Simple backtest results:")
                logger.info(f"Resolution: {resolution} ({periods_per_day} periods per day)")
                logger.info(f"Initial portfolio: $10,000.00")
                logger.info(f"Final portfolio: ${final_value:.2f}")
                logger.info(f"Total return: {total_return:.2%}")
                logger.info(f"Avg daily return: {avg_daily_return:.4%}")
                logger.info(f"Annualized return: {annualized_return:.2%}")
                logger.info(f"Buy & hold return: {buy_hold_return:.2%}")
                logger.info(f"Win rate: {win_rate:.2%}")
                logger.info(f"Number of trades: {num_trades}")
            
            # Add total_trades for compatibility with evaluation summary
            if 'total_trades' not in results:
                results['total_trades'] = results.get('number_of_trades', 0)
                
            return results
            
        except Exception as e:
            logger.error(f"Error in backtest: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Return dummy results to prevent crashes
            return {
                'initial_value': 10000.0,
                'final_value': 10000.0,
                'total_return': 0.0,
                'buy_hold_return': 0.0,
                'win_rate': 0.0,
                'number_of_trades': 0,
                'total_trades': 0,
                'max_drawdown': 0.0,
                'annualized_return': 0.0,
                'avg_daily_return': 0.0,
                'periods_per_day': 1.0,
                'sharpe_ratio': 0.0,
                'profit_factor': 0.0,
                'resolution': resolution or "1d"
            }
    
    def plot_simple_backtest(
        self, 
        y_true: np.ndarray, 
        y_pred: np.ndarray,
        filename: str = None,
        resolution: str = None
    ) -> None:
        """
        Run simple backtest and plot detailed trading results with entry/exit points
        
        Args:
            y_true: Array of actual prices
            y_pred: Array of predicted prices 
            filename: Optional filename to save plot
            resolution: Time resolution of the data (e.g., "1m", "5m", "1h", "1d")
        """
        # Get resolution from config if not provided
        if resolution is None:
            resolution = config.resolution if hasattr(config, 'resolution') else "1d"
            
        # Run the backtest
        backtest_results = self.run_simple_backtest(y_true, y_pred, resolution=resolution)
        
        # Extract results
        trades = backtest_results.get('trades', [])
        portfolio_values = backtest_results.get('portfolio_values', [])
        
        # Ensure all values are Python scalars
        total_return = float(backtest_results['total_return'])
        buy_hold_return = float(backtest_results['buy_hold_return'])
        win_rate = float(backtest_results['win_rate']) 
        max_drawdown = float(backtest_results.get('max_drawdown', 0.0))
        annualized_return = float(backtest_results.get('annualized_return', 0.0))
        
        # Create figure with 3 subplots: prices & trades, portfolio value, predictions
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 16), sharex=True)
        
        # Ensure arrays are flattened and proper type
        y_true_flat = np.array(y_true, dtype=np.float64).flatten()
        y_pred_flat = np.array(y_pred, dtype=np.float64).flatten()
        
        # Plot 1: Prices with buy/sell points and trailing stops
        ax1.plot(range(len(y_true_flat)), y_true_flat, label='Actual Price', color='blue', alpha=0.7)
        
        # Skip the rest if there are no trades
        if len(trades) == 0:
            ax1.set_title('Price Chart (No Trades)')
            ax1.set_ylabel('Price')
            ax1.legend()
            ax1.grid(True)
            
            # Plot 2: Portfolio Value
            ax2.plot(range(len(portfolio_values)), portfolio_values, label='Portfolio Value', color='purple')
            ax2.axhline(y=10000, color='gray', linestyle='--', alpha=0.7, label='Initial Value')
            ax2.set_title('Portfolio Value (No Trades)')
            ax2.set_ylabel('Value ($)')
            ax2.legend()
            ax2.grid(True)
            
            # Plot 3: Actual vs Predicted Prices
            ax3.plot(range(len(y_true_flat)), y_true_flat, label='Actual Price', color='blue')
            ax3.plot(range(len(y_pred_flat)), y_pred_flat, label='Predicted Price', color='orange', alpha=0.7)
            ax3.set_title('Actual vs Predicted Prices')
            ax3.set_xlabel('Time Step')
            ax3.set_ylabel('Price')
            ax3.legend()
            ax3.grid(True)
            
            plt.tight_layout()
            
            # Save or show
            if filename:
                plt.savefig(filename)
                logger.info(f"Simple backtest plot saved to {filename}")
            else:
                plt.show()
                
            return
        
        # Extract buy/sell indices from valid trades
        buy_indices = []
        sell_indices = []
        
        for trade in trades:
            try:
                if trade['action'] == 'buy':
                    buy_indices.append(int(trade['timestamp']))
                elif trade['action'] == 'sell':
                    sell_indices.append(int(trade['timestamp']))
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"Skipping invalid trade: {e}")
                continue
        
        # Add buy/sell markers
        if buy_indices and sell_indices:
            buy_prices = [y_true_flat[i] if 0 <= i < len(y_true_flat) else 0 for i in buy_indices]
            sell_prices = [y_true_flat[i] if 0 <= i < len(y_true_flat) else 0 for i in sell_indices]
            
            ax1.scatter(buy_indices, buy_prices, marker='^', color='green', s=100, label='Buy')
            ax1.scatter(sell_indices, sell_prices, marker='v', color='red', s=100, label='Sell')
        
            # Plot trailing stops if we can calculate them
            trailing_stops = []
            trailing_stop_indices = []
            
            # Reconstruct trailing stops
            in_position = False
            entry_idx = 0
            highest_price = 0
            trailing_stop_pct = 0.03  # Same as in the strategy
            
            for i, price in enumerate(y_true_flat):
                # Check if this is an entry point
                if i in buy_indices:
                    in_position = True
                    entry_idx = i
                    highest_price = price
                
                # Update trailing stop if in position
                if in_position:
                    highest_price = max(highest_price, price)
                    trailing_stop = highest_price * (1 - trailing_stop_pct)
                    trailing_stops.append(trailing_stop)
                    trailing_stop_indices.append(i)
                
                # Check if this is an exit point
                if i in sell_indices:
                    in_position = False
            
            # Plot trailing stops as a dashed line
            if trailing_stop_indices:
                ax1.plot(trailing_stop_indices, trailing_stops, 'r--', alpha=0.5, label='Trailing Stop')
        
        ax1.set_title('Price Chart with Entry/Exit Points')
        ax1.set_ylabel('Price')
        ax1.legend()
        ax1.grid(True)
        
        # Plot 2: Portfolio Value
        ax2.plot(range(len(portfolio_values)), portfolio_values, label='Portfolio Value', color='purple')
        
        # Add horizontal line for initial value
        ax2.axhline(y=10000, color='gray', linestyle='--', alpha=0.7, label='Initial Value')
        
        # Add buy & hold performance for comparison
        buy_hold_values = [10000]
        for i in range(1, len(y_true_flat)):
            if y_true_flat[0] > 0:  # Prevent division by zero
                buy_hold_values.append(10000 * (y_true_flat[i] / y_true_flat[0]))
            else:
                buy_hold_values.append(10000)  # Just stay at initial value if first price is zero
        
        ax2.plot(range(len(buy_hold_values)), buy_hold_values, label='Buy & Hold', color='green', alpha=0.5)
        
        ax2.set_title('Portfolio Value vs Buy & Hold')
        ax2.set_ylabel('Value ($)')
        ax2.legend()
        ax2.grid(True)
        
        # Plot 3: Actual vs Predicted Prices
        ax3.plot(range(len(y_true_flat)), y_true_flat, label='Actual Price', color='blue')
        ax3.plot(range(len(y_pred_flat)), y_pred_flat, label='Predicted Price', color='orange', alpha=0.7)
        
        # Highlight areas where prediction direction was wrong
        for i in range(1, min(len(y_true_flat), len(y_pred_flat))):
            if i >= len(y_true_flat) or i-1 >= len(y_true_flat):
                continue
                
            true_direction = np.sign(y_true_flat[i] - y_true_flat[i-1])
            pred_direction = np.sign(y_pred_flat[i] - y_true_flat[i-1])
            
            if true_direction != pred_direction:
                ax3.axvspan(i-0.5, i+0.5, alpha=0.2, color='red')
        
        ax3.set_title('Actual vs Predicted Prices (Red areas show wrong direction predictions)')
        ax3.set_xlabel('Time Step')
        ax3.set_ylabel('Price')
        ax3.legend()
        ax3.grid(True)
        
        # Add performance metrics as text
        metrics_text = (
            f"Resolution: {resolution}\n"
            f"Total Return: {total_return:.2%}\n"
            f"Annualized Return: {annualized_return:.2%}\n"
            f"Buy & Hold Return: {buy_hold_return:.2%}\n"
            f"Number of Trades: {backtest_results.get('number_of_trades', 0)}\n"
            f"Win Rate: {win_rate:.2%}\n"
            f"Max Drawdown: {max_drawdown:.2%}"
        )
        
        # Add text box with metrics to the top right of the top plot
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        ax1.text(0.02, 0.98, metrics_text, transform=ax1.transAxes, fontsize=10,
                verticalalignment='top', bbox=props)
        
        plt.tight_layout()
        
        # Save or show
        if filename:
            # Save to plots/backtests directory
            plots_dir = os.path.join(os.path.dirname(self.models_dir), 'plots', 'backtests')
            os.makedirs(plots_dir, exist_ok=True)
            file_path = os.path.join(plots_dir, filename)
            plt.savefig(file_path)
            logger.info(f"Simple backtest plot saved to {file_path}")
        else:
            plt.show()

    def plot_price_comparison(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        filename: str = None
    ) -> None:
        """
        Create a simple plot showing predicted closing prices vs actual closing prices
        
        Args:
            y_true: Array of actual closing prices
            y_pred: Array of predicted closing prices
            filename: Optional filename to save the plot
        """
        plt.figure(figsize=(12, 8))
        
        # Ensure arrays are flattened and proper type
        y_true = np.array(y_true, dtype=np.float64).flatten()
        y_pred = np.array(y_pred, dtype=np.float64).flatten()
        
        # Ensure arrays have the same length
        if len(y_true) != len(y_pred):
            logger.warning(f"Length mismatch: y_true ({len(y_true)}) vs y_pred ({len(y_pred)})")
            # Truncate to the shorter length
            min_len = min(len(y_true), len(y_pred))
            y_true = y_true[:min_len]
            y_pred = y_pred[:min_len]
        
        # Plot actual and predicted prices
        plt.plot(y_true, label='Actual Closing Price', color='blue', linewidth=2)
        plt.plot(y_pred, label='Predicted Closing Price', color='red', linewidth=2, alpha=0.7)
        
        # Calculate directional accuracy
        correct_dir = 0
        total_dir = 0
        
        for i in range(len(y_true)):
            # y_true[i] and y_pred[i] are already percentage changes
            actual_dir = y_true[i]  # This IS the percentage change
            pred_dir = y_pred[i]    # This IS the percentage change
            
            # Only count non-zero changes
            if np.abs(actual_dir) > 1e-6:
                total_dir += 1
                if np.sign(actual_dir) == np.sign(pred_dir):
                    correct_dir += 1
        
        dir_accuracy = (correct_dir / total_dir) * 100 if total_dir > 0 else 0
        
        # Calculate MSE
        mse = np.mean((y_true - y_pred) ** 2)
        
        # Add metrics in a text box
        metrics_text = (
            f"MSE: {mse:.6f}\n"
            f"Direction Accuracy: {dir_accuracy:.2f}%"
        )
        
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        plt.text(0.02, 0.98, metrics_text, transform=plt.gca().transAxes, fontsize=10,
                verticalalignment='top', bbox=props)
        
        plt.title('Actual vs Predicted Closing Prices')
        plt.xlabel('Time Step')
        plt.ylabel('Price')
        plt.legend()
        plt.grid(True)
        
        # Save or show the plot
        if filename:
            # Save to plots/comparisons directory
            plots_dir = os.path.join(os.path.dirname(self.models_dir), 'plots', 'comparisons')
            os.makedirs(plots_dir, exist_ok=True)
            file_path = os.path.join(plots_dir, filename)
            plt.savefig(file_path)
            logger.info(f"Price comparison plot saved to {file_path}")
        else:
            plt.show()

    def plot_candlestick_backtest(
        self, 
        ohlcv_data: pd.DataFrame,
        y_true: np.ndarray = None, 
        y_pred: np.ndarray = None,
        transaction_cost_pct: float = 0.001,
        filename: str = None,
        title: str = None
    ) -> str:
        """
        Plot backtest results on candlestick chart with buy/sell signals
        
        Args:
            ohlcv_data: DataFrame with OHLCV data
            y_true: Optional array of actual prices (if not provided, will use ohlcv_data['close'])
            y_pred: Optional array of predicted prices
            transaction_cost_pct: Trading fee percentage
            filename: Optional filename to save the plot
            title: Optional title for the plot
            
        Returns:
            Path to saved plot or None
        """
        from src.model.profit_functions import backtest_trades, plot_backtest_with_signals
        
        # If no price data provided, use the close prices from OHLCV data
        if y_true is None:
            y_true = ohlcv_data['close'].values
            
        # If we have predictions, run backtest to get trade signals
        if y_pred is not None:
            backtest_results = backtest_trades(y_true, y_pred, transaction_cost_pct)
            trades = backtest_results['trades']
            
            # Set default title if none provided
            if title is None:
                title = f"Backtest Results (Return: {backtest_results['total_return']:.2%}, B&H: {backtest_results['buy_hold_return']:.2%})"
                
            # Set default filename if none provided
            if filename is None:
                symbol = self.symbol if hasattr(self, 'symbol') else "backtest"
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{symbol}_backtest_{timestamp}.png"
                
            # Plot with signals - save to plots/backtests directory
            plots_dir = os.path.join(os.path.dirname(self.models_dir), 'plots', 'backtests')
            os.makedirs(plots_dir, exist_ok=True)
            return plot_backtest_with_signals(
                ohlcv_data=ohlcv_data,
                trades=trades,
                filename=filename,
                title=title,
                output_dir=plots_dir
            )
        else:
            logger.warning("No predictions provided for backtest visualization")
            return None

# Add PricePredictor as a wrapper around MLModel
class PricePredictor(MLModel):
    """
    Price prediction model wrapper class.
    This class inherits from MLModel but is used specifically for price predictions
    in the cross-token training process.
    """
    
    def __init__(self, model_type: str = "lstm", optimization_target: str = "mse"):
        super().__init__(model_type=model_type, optimization_target=optimization_target)
        
    def predict_next_price(self, X: np.ndarray) -> np.ndarray:
        """
        Predict the next price given the current state.
        
        Args:
            X: Input features of shape (batch_size, sequence_length, features)
            
        Returns:
            Predicted next price
        """
        return self.predict(X)
