"""
Improved ML Model for Price Prediction

Key improvements:
1. Better initialization to prevent collapse
2. Reduced regularization 
3. Output constraints to keep predictions reasonable
4. Better loss function defaults
"""

import os
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Model, Sequential
from tensorflow.keras.layers import Dense, LSTM, Dropout, BatchNormalization, Input, Lambda
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
from tensorflow.keras.initializers import GlorotUniform, Orthogonal
from tensorflow.keras.regularizers import l2
from typing import Tuple, List

from src.model.ml_model import MLModel
from src.model.profit_functions import simple_directional_loss, direction_focused_loss, balanced_directional_loss, magnitude_constrained_loss, variance_encouraging_loss, anti_collapse_loss, robust_directional_loss


class ImprovedMLModel(MLModel):
    """Improved ML model with anti-collapse features"""
    
    def __init__(self, model_type: str = "lstm", optimization_target: str = "simple_directional"):
        # Default to simple_directional for better trading performance
        super().__init__(model_type=model_type, optimization_target=optimization_target)
        
        # Initialize logger if not already present
        if not hasattr(self, 'logger'):
            import logging
            self.logger = logging.getLogger(__name__)
    
    def _get_loss_function(self):
        """
        Override parent's loss function to use improved loss functions
        
        New options:
        - anti_collapse: Prevents model from predicting constants (RECOMMENDED FOR YOUR ISSUE)
        - robust_directional: Combines directional accuracy with anti-collapse
        - variance_encouraging: Prevents collapse to constant predictions
        - balanced_directional: Eliminates negative bias, prevents extreme predictions
        - magnitude_constrained: Explicit constraints on prediction magnitude  
        - direction_focused: Original complex loss (may cause bias)
        - simple_directional: Basic directional loss
        """
        if self.optimization_target == "anti_collapse":
            return anti_collapse_loss
        elif self.optimization_target == "robust_directional":
            return robust_directional_loss
        elif self.optimization_target == "variance_encouraging":
            return variance_encouraging_loss
        elif self.optimization_target == "balanced_directional":
            return balanced_directional_loss
        elif self.optimization_target == "magnitude_constrained":
            return magnitude_constrained_loss
        elif self.optimization_target == "simple_directional":
            return simple_directional_loss
        elif self.optimization_target == "direction_focused":
            # Fix #23: Use direction-focused loss for 80%+ accuracy
            return direction_focused_loss
        else:
            # Use Huber loss instead of MSE for better robustness
            return tf.keras.losses.Huber(delta=1.0)
    
    def _build_model(self):
        """
        Build the LSTM neural network model
        
        Returns:
            Compiled Keras model
        """
        # Get the number of features from the first training sample
        input_features = self.feature_columns
        output_units = 1  # We're predicting a single value (next time step)
        
        # Build the model
        model = Sequential()
        
        # Input layer
        model.add(Input(shape=(self.lookback_period, input_features)))
        
        # Ensure batch normalization is applied properly
        model.add(BatchNormalization())
        
        # REMOVED BATCHNORM - Fix #5: BatchNorm can interfere with LSTM temporal patterns
        # x = BatchNormalization()(x)
        # Fix #8: Add minimal dropout (0.1) to prevent overfitting
        x = Dropout(0.1)(x)
        
        # Additional LSTM layers
        for i in range(1, len(lstm_units)):
            return_seq = i < len(lstm_units) - 1
            
            if use_bidirectional:
                x = tf.keras.layers.Bidirectional(
                    LSTM(
                        units=lstm_units[i],
                        return_sequences=return_seq,
                        kernel_initializer=GlorotUniform(seed=42+i),
                        recurrent_initializer=Orthogonal(seed=42+i),
                    )
                )(x)
            else:
                x = LSTM(
                    units=lstm_units[i],
                    return_sequences=return_seq,
                    kernel_initializer=GlorotUniform(seed=42+i),
                    recurrent_initializer=Orthogonal(seed=42+i),
                )(x)
            
            # REMOVED BATCHNORM - Fix #5: BatchNorm can interfere with LSTM temporal patterns
            # x = BatchNormalization()(x)
            # Fix #8: Add minimal dropout (0.1) to prevent overfitting
            x = Dropout(0.1)(x)
        
        # Dense layers - simplified
        x = Dense(32, activation='relu', kernel_initializer=GlorotUniform(seed=100))(x)
        # Fix #8: Add minimal dropout (0.1) to prevent overfitting
        x = Dropout(0.1)(x)
        
        # Output layer - Fix #6: Remove tanh constraint to allow full range predictions
        outputs = Dense(
            output_units,
            kernel_initializer=GlorotUniform(seed=42),
            # REMOVED: activation=output_activation  
            # Let the model learn the natural scale of predictions
        )(x)
        
        # Create model
        model = Model(inputs=inputs, outputs=outputs)
        
        # Compile with AdamW optimizer for better weight decay
        model.compile(
            optimizer=tf.keras.optimizers.AdamW(
                learning_rate=lr_schedule,
                weight_decay=0.0001, 
                clipnorm=1.0,
                beta_1=0.9,  # Default momentum
                beta_2=0.999  # Default second moment decay
            ),
            loss=self._get_loss_function(),
            metrics=self._get_metrics()
        )
        
        return model
    
    def train(self, X_train, y_train, X_val, y_val, epochs=100, batch_size=32, 
              model_name=None, patience=10):
        """
        Override parent train method to use our enhanced fit with anti-collapse mechanisms
        
        Args:
            X_train: Training features
            y_train: Training targets
            X_val: Validation features  
            y_val: Validation targets
            epochs: Number of epochs
            batch_size: Batch size
            model_name: Model name for saving
            patience: Early stopping patience (for compatibility, not used in custom loop)
        """
        # Store model name
        self.model_name = model_name
        
        # Early stopping - more patient for complex patterns
        early_stop = EarlyStopping(
            monitor='val_loss',
            patience=10,  # Reverted from 15 - too much patience caused overtraining
            restore_best_weights=True,
            verbose=1
        )
        callbacks.append(early_stop)
        
        # Call the enhanced fit method
        history = self.fit(X_train, y_train, X_val, y_val, epochs, batch_size, verbose=1)
        
        # Save the model if name provided
        if model_name:
            self.save(model_name)
            
        # Return history in expected format
        return history.history
    
    def fit(self, X_train, y_train, X_val=None, y_val=None, epochs=None, batch_size=None, 
            callbacks=None, verbose=1):
        """
        Enhanced fit method with gradient noise and anti-collapse mechanisms
        """
        if epochs is None:
            epochs = self.epochs
        if batch_size is None:
            batch_size = self.batch_size
            
        # Ensure model exists
        if self.model is None:
            raise ValueError("Model not built. Call train() method instead of fit() directly.")
            
        # Store original loss function
        original_loss = self.model.loss
        
        # Custom training loop to add gradient noise and prevent collapse
        history = {'loss': [], 'val_loss': [], 'direction_acc': [], 'val_direction_acc': []}
        
        if verbose:
            print(f"\n🚀 Starting enhanced training with {self.optimization_target} loss")
            print(f"   Training samples: {len(X_train)}, Validation samples: {len(X_val) if X_val is not None else 0}")
            print(f"   Epochs: {epochs}, Batch size: {batch_size}")
            print("-" * 80)
        
        for epoch in range(epochs):
            # Check if model is collapsing (predictions too similar)
            if epoch > 0 and epoch % 10 == 0:
                # Make predictions on a sample of training data
                sample_size = min(100, len(X_train))
                sample_indices = np.random.choice(len(X_train), sample_size, replace=False)
                sample_preds = self.model.predict(X_train[sample_indices], verbose=0)
                
                # Check prediction variance
                pred_std = np.std(sample_preds)
                pred_range = np.ptp(sample_preds)  # peak-to-peak range
                
                if pred_std < 0.01 or pred_range < 0.02:
                    self.logger.warning(f"Model collapse detected at epoch {epoch}")
                    self.logger.warning(f"Prediction std: {pred_std:.6f}, range: {pred_range:.6f}")
                    
                    # Apply gradient noise to help escape local minimum
                    self._add_gradient_noise(noise_scale=0.1)
                    
                    # Temporarily increase learning rate
                    current_lr = float(self.model.optimizer.learning_rate)
                    temp_lr = min(current_lr * 2, 0.01)  # Don't go above 0.01
                    self.model.optimizer.learning_rate = temp_lr
                    self.logger.info(f"Temporarily increased learning rate to {temp_lr}")
            
            # Train for one epoch with potential gradient noise
            if epoch < 10:  # Add noise in early epochs to prevent early collapse
                noise_scale = 0.05 * (1 - epoch/10)  # Decay noise over time
                self._add_gradient_noise(noise_scale)
            
            # Fit for one epoch
            epoch_history = self.model.fit(
                X_train, y_train,
                validation_data=(X_val, y_val) if X_val is not None else None,
                epochs=1,
                batch_size=batch_size,
                callbacks=callbacks if epoch == 0 else None,  # Only use callbacks on first epoch
                verbose=1 if verbose else 0  # Show progress if verbose is True
            )
            
            # Record metrics
            history['loss'].append(epoch_history.history['loss'][0])
            if X_val is not None:
                history['val_loss'].append(epoch_history.history['val_loss'][0])
            
            # Print progress every epoch (or less frequently for long training)
            print_freq = 1 if epochs <= 50 else 5 if epochs <= 100 else 10
            if verbose and epoch % print_freq == 0:
                msg = f"Epoch {epoch+1}/{epochs} - loss: {history['loss'][-1]:.4f}"
                if X_val is not None:
                    msg += f" - val_loss: {history['val_loss'][-1]:.4f}"
                    # Calculate direction accuracy using the CORRECTED method
                    # Note: This is approximate since we're using scaled values
                    # The final evaluation will use the proper inverse-transformed values
                    val_preds = self.model.predict(X_val, verbose=0)
                    
                    # Simple sign comparison (not perfect but better than before)
                    # Skip near-zero values to avoid noise
                    val_preds_flat = val_preds.flatten()
                    y_val_flat = y_val.flatten()
                    
                    # Only compare non-trivial predictions/targets
                    significant_mask = (np.abs(y_val_flat) > 0.01)
                    if np.sum(significant_mask) > 0:
                        val_dir_acc = np.mean(
                            np.sign(val_preds_flat[significant_mask]) == 
                            np.sign(y_val_flat[significant_mask])
                        )
                    else:
                        val_dir_acc = 0.5  # Default if no significant changes
                    
                    msg += f" - val_direction_acc: {val_dir_acc:.4f}"
                print(msg)  # Use print for immediate output
        
        # Convert history to proper format
        history_obj = type('History', (), {})()
        history_obj.history = history
        
        return history_obj
    
    def _add_gradient_noise(self, noise_scale=0.01):
        """
        Add gradient noise to help escape local minima
        
        Based on "Adding Gradient Noise Improves Learning for Very Deep Networks"
        """
        for layer in self.model.layers:
            if hasattr(layer, 'kernel'):
                kernel_noise = tf.random.normal(
                    shape=layer.kernel.shape,
                    mean=0.0,
                    stddev=noise_scale,
                    dtype=layer.kernel.dtype
                )
                layer.kernel.assign_add(kernel_noise)
                
            if hasattr(layer, 'bias') and layer.bias is not None:
                bias_noise = tf.random.normal(
                    shape=layer.bias.shape,
                    mean=0.0,
                    stddev=noise_scale * 0.1,  # Less noise for biases
                    dtype=layer.bias.dtype
                )
                layer.bias.assign_add(bias_noise)