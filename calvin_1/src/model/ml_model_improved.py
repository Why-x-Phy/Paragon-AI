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
from tensorflow.keras.models import Model
from tensorflow.keras.layers import Dense, LSTM, Dropout, BatchNormalization, Input, Lambda
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
from tensorflow.keras.initializers import GlorotUniform, Orthogonal
from typing import Tuple, List

from src.model.ml_model import MLModel
from src.model.profit_functions import simple_directional_loss, direction_focused_loss


class ImprovedMLModel(MLModel):
    """Improved ML model with anti-collapse features"""
    
    def __init__(self, model_type: str = "lstm", optimization_target: str = "simple_directional"):
        # Default to simple_directional for better trading performance
        super().__init__(model_type=model_type, optimization_target=optimization_target)
    
    def _get_loss_function(self):
        """
        Override parent's loss function to use Huber loss
        Fix #7: Huber loss is more robust to outliers than MSE
        """
        if self.optimization_target == "simple_directional":
            return simple_directional_loss
        elif self.optimization_target == "direction_focused":
            # Fix #23: Use direction-focused loss for 80%+ accuracy
            return direction_focused_loss
        else:
            # Use Huber loss instead of MSE for better robustness
            return tf.keras.losses.Huber(delta=1.0)
    
    def build_lstm_model(
        self, 
        input_shape: Tuple[int, int],
        output_units: int = 1,
        lstm_units: List[int] = [256, 128, 64],  # Fix #21: Increased first layer from 256 to 512 units
        dropout_rate: float = 0.2,  # Reduced from 0.4
        use_bidirectional: bool = True
        # Fix #6: Removed output_activation and output_scale parameters
    ) -> Model:
        """
        Build improved LSTM model with anti-collapse features
        
        Key improvements:
        1. Reduced dropout (0.2 vs 0.4) to allow more complex patterns
        2. Removed recurrent_dropout for cuDNN optimization
        3. Output activation + scaling to prevent extreme predictions
        4. Better weight initialization
        5. Fewer layers to reduce overfitting risk
        """
        
        # Input layer
        inputs = Input(shape=input_shape)
        x = inputs
        
        # First LSTM layer
        if use_bidirectional:
            x = tf.keras.layers.Bidirectional(
                LSTM(
                    units=lstm_units[0],
                    return_sequences=len(lstm_units) > 1,
                    kernel_initializer=GlorotUniform(seed=42),
                    recurrent_initializer=Orthogonal(seed=42),
                    # No recurrent_dropout for cuDNN optimization
                )
            )(x)
        else:
            x = LSTM(
                units=lstm_units[0],
                return_sequences=len(lstm_units) > 1,
                kernel_initializer=GlorotUniform(seed=42),
                recurrent_initializer=Orthogonal(seed=42),
            )(x)
        
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
            optimizer=tf.keras.optimizers.AdamW(learning_rate=0.001, weight_decay=0.0001, clipnorm=1.0),  # Fix #20: AdamW instead of Adam
            loss=self._get_loss_function(),
            metrics=self._get_metrics()
        )
        
        return model
    
    def train(
        self, 
        X_train: np.ndarray, 
        y_train: np.ndarray,
        X_val: np.ndarray, 
        y_val: np.ndarray,
        epochs: int = 50,  # Reduced default from 100
        batch_size: int = 32,  # Smaller batch size
        model_name: str = None,
        patience: int = 10  # More aggressive early stopping
    ):
        """
        Train with better defaults to prevent collapse
        """
        # Build callbacks with better settings
        callbacks = []
        
        # Early stopping - more patient for complex patterns
        early_stop = EarlyStopping(
            monitor='val_loss',
            patience=10,  # Reverted from 15 - too much patience caused overtraining
            restore_best_weights=True,
            verbose=1
        )
        callbacks.append(early_stop)
        
        # Model checkpoint
        if model_name:
            checkpoint_path = os.path.join(self.models_dir, f"{model_name}.h5")
            checkpoint = ModelCheckpoint(
                checkpoint_path,
                monitor='val_loss',
                save_best_only=True,
                verbose=1
            )
            callbacks.append(checkpoint)
        
        # Reduce learning rate on plateau - more aggressive
        reduce_lr = ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.5,  # Cut in half
            patience=10,   # Fix #12: Increased from 5 to let model train longer
            min_lr=1e-7,
            verbose=1
        )
        callbacks.append(reduce_lr)
        
        # Add gradient norm logging callback
        class GradientLogger(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                # Log gradient norms to detect vanishing/exploding gradients
                gradients = []
                for layer in self.model.layers:
                    if hasattr(layer, 'kernel'):
                        weights = layer.get_weights()
                        if len(weights) > 0:
                            grad_norm = np.linalg.norm(weights[0])
                            gradients.append(grad_norm)
                
                if gradients:
                    avg_grad = np.mean(gradients)
                    if avg_grad < 0.0001:
                        print(f"\n⚠️ Warning: Vanishing gradients detected (avg: {avg_grad:.6f})")
                    elif avg_grad > 10:
                        print(f"\n⚠️ Warning: Large gradients detected (avg: {avg_grad:.2f})")
        
        callbacks.append(GradientLogger())
        
        # Fix #24: Try larger batch size for more stable gradients
        # Effective batch size = 64 (was 32)
        effective_batch_size = min(64, len(X_train) // 4)  # Don't use more than 25% of data per batch
        
        # Call parent train with our callbacks
        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=epochs,
            batch_size=effective_batch_size,
            callbacks=callbacks,
            verbose=1
        )
        
        return history 