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
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
from tensorflow.keras.initializers import GlorotUniform, Orthogonal
from typing import Tuple, List

from src.model.ml_model import MLModel
from src.model.profit_functions import simple_directional_loss


class ImprovedMLModel(MLModel):
    """Improved ML model with anti-collapse features"""
    
    def __init__(self, model_type: str = "lstm", optimization_target: str = "simple_directional"):
        # Default to simple_directional for better trading performance
        super().__init__(model_type=model_type, optimization_target=optimization_target)
    
    def build_lstm_model(
        self, 
        input_shape: Tuple[int, int],
        output_units: int = 1,
        lstm_units: List[int] = [128, 64, 32],  # Reduced from [256, 128, 64, 32]
        dropout_rate: float = 0.2,  # Reduced from 0.4
        use_bidirectional: bool = True,
        output_activation: str = 'tanh',  # Constrain outputs to [-1, 1]
        output_scale: float = 0.1  # Scale outputs to reasonable percentage range
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
        
        x = BatchNormalization()(x)
        x = Dropout(dropout_rate)(x)
        
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
            
            x = BatchNormalization()(x)
            x = Dropout(dropout_rate)(x)
        
        # Dense layers - simplified
        x = Dense(32, activation='relu', kernel_initializer=GlorotUniform(seed=100))(x)
        x = Dropout(dropout_rate)(x)
        
        # Output layer with activation
        if output_activation == 'tanh':
            # Tanh output: [-1, 1] range
            raw_output = Dense(output_units, activation='tanh', 
                             kernel_initializer=GlorotUniform(seed=200))(x)
            # Scale to percentage range (e.g., -10% to +10%)
            outputs = Lambda(lambda x: x * output_scale, name='scaled_output')(raw_output)
        elif output_activation == 'sigmoid':
            # Sigmoid output: [0, 1] range  
            raw_output = Dense(output_units, activation='sigmoid',
                             kernel_initializer=GlorotUniform(seed=200))(x)
            # Scale and shift to percentage range (e.g., -5% to +5%)
            outputs = Lambda(lambda x: (x - 0.5) * output_scale * 2, name='scaled_output')(raw_output)
        else:
            # Linear output (original behavior)
            outputs = Dense(output_units, kernel_initializer=GlorotUniform(seed=200))(x)
        
        # Create model
        model = Model(inputs=inputs, outputs=outputs)
        
        # Compile with lower learning rate for stability
        model.compile(
            optimizer=Adam(learning_rate=0.0001, clipnorm=1.0),  # Reduced from 0.0005
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
        
        # Early stopping - stop if no improvement
        early_stopping = EarlyStopping(
            monitor='val_loss',
            patience=patience,
            restore_best_weights=True,
            verbose=1
        )
        callbacks.append(early_stopping)
        
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
            patience=5,   # Reduced from 10
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
        
        # Call parent train with our callbacks
        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=callbacks,
            verbose=1
        )
        
        return history 