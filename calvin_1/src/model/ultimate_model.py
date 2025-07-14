"""
Ultimate LSTM Model Architecture

This model is designed for maximum performance on crypto price prediction,
incorporating every technique that can improve accuracy, regardless of training time.
"""

import tensorflow as tf
from tensorflow.keras import layers, Model
import numpy as np
from typing import Tuple, List, Dict
import logging

logger = logging.getLogger(__name__)


class UltimateModel:
    """
    The best possible model architecture for crypto price prediction.
    
    Key innovations:
    1. Multi-scale temporal attention (1h, 4h, 24h patterns)
    2. Bidirectional LSTMs with residual connections
    3. Feature-wise attention mechanism
    4. Mixture of Experts (MoE) for different market regimes
    5. Uncertainty quantification
    6. Advanced regularization
    """
    
    def __init__(self, optimization_target: str = "ultimate_loss"):
        self.optimization_target = optimization_target
        self.model = None
        self.models_ensemble = []  # For ensemble approach
        
    def build_model(self, input_shape: Tuple[int, int], output_shape: int = 1) -> Model:
        """
        Build the ultimate model architecture
        
        Args:
            input_shape: (lookback_period, n_features)
            output_shape: Number of outputs (typically 1)
        """
        lookback, n_features = input_shape
        
        # Input layer
        inputs = layers.Input(shape=input_shape, name='main_input')
        
        # 1. Multi-Scale Feature Extraction
        # Extract features at different time scales
        multi_scale_features = self._build_multi_scale_block(inputs, n_features)
        
        # 2. Feature Attention
        # Learn which features are most important
        attended_features = self._build_feature_attention(multi_scale_features, n_features)
        
        # 3. Bidirectional LSTM Stack with Residual Connections
        lstm_output = self._build_lstm_stack(attended_features)
        
        # 4. Temporal Attention
        # Focus on most important time steps
        temporal_output = self._build_temporal_attention(lstm_output)
        
        # 5. Mixture of Experts
        # Different "experts" for different market conditions
        moe_output = self._build_mixture_of_experts(temporal_output)
        
        # 6. Uncertainty Estimation
        # Predict both mean and uncertainty
        mean_output = layers.Dense(
            output_shape, 
            activation=None,
            kernel_initializer=tf.keras.initializers.RandomNormal(mean=0.0, stddev=0.05),
            name='mean_prediction'
        )(moe_output)
        
        # Predict log variance for numerical stability
        log_var_output = layers.Dense(
            output_shape,
            activation=None,
            kernel_initializer=tf.keras.initializers.RandomNormal(mean=0.0, stddev=0.02),
            name='log_variance'
        )(moe_output)
        
        # Combine outputs
        outputs = layers.Concatenate(name='combined_output')([mean_output, log_var_output])
        
        # Build model
        self.model = Model(inputs=inputs, outputs=outputs, name='UltimateModel')
        
        # Compile with custom loss
        self._compile_model()
        
        return self.model
    
    def _build_multi_scale_block(self, inputs, n_features):
        """Extract features at multiple time scales"""
        
        # 1-hour scale (original)
        scale_1h = inputs
        
        # 4-hour scale (average every 4 time steps)
        scale_4h = layers.AveragePooling1D(
            pool_size=4, strides=1, padding='same'
        )(inputs)
        
        # Daily scale (average every 24 time steps)
        scale_24h = layers.AveragePooling1D(
            pool_size=24, strides=1, padding='same'
        )(inputs)
        
        # Concatenate multi-scale features
        multi_scale = layers.Concatenate(axis=-1)([scale_1h, scale_4h, scale_24h])
        
        # Project back to original feature dimension
        multi_scale = layers.Dense(n_features, activation='relu')(multi_scale)
        
        return multi_scale
    
    def _build_feature_attention(self, inputs, n_features):
        """Attention mechanism over features"""
        
        # Calculate attention scores for each feature
        attention_scores = layers.Dense(n_features, activation='sigmoid')(inputs)
        
        # Apply attention
        attended = layers.Multiply()([inputs, attention_scores])
        
        # Add residual connection
        attended = layers.Add()([inputs, attended])
        
        return attended
    
    def _build_lstm_stack(self, inputs):
        """Bidirectional LSTM stack with residual connections"""
        
        x = inputs
        
        # Stack of Bidirectional LSTMs with increasing complexity
        lstm_units = [128, 256, 128]
        
        for i, units in enumerate(lstm_units):
            # Bidirectional LSTM
            lstm_out = layers.Bidirectional(
                layers.LSTM(
                    units,
                    return_sequences=True,
                    kernel_regularizer=tf.keras.regularizers.l2(1e-4),
                    recurrent_regularizer=tf.keras.regularizers.l2(1e-4),
                    dropout=0.1,
                    recurrent_dropout=0.1
                ),
                merge_mode='concat'
            )(x)
            
            # Layer normalization
            lstm_out = layers.LayerNormalization()(lstm_out)
            
            # Residual connection (if dimensions match)
            if i > 0:
                # Project to match dimensions
                if x.shape[-1] != lstm_out.shape[-1]:
                    x = layers.Dense(lstm_out.shape[-1])(x)
                lstm_out = layers.Add()([x, lstm_out])
            
            x = lstm_out
            
            # Dropout for regularization
            x = layers.Dropout(0.2)(x)
        
        return x
    
    def _build_temporal_attention(self, lstm_output):
        """Self-attention over time steps"""
        
        # Multi-head attention
        attention_output = layers.MultiHeadAttention(
            num_heads=8,
            key_dim=64,
            dropout=0.1
        )(lstm_output, lstm_output)
        
        # Add & Norm
        attention_output = layers.Add()([lstm_output, attention_output])
        attention_output = layers.LayerNormalization()(attention_output)
        
        # Global average pooling to get fixed size output
        output = layers.GlobalAveragePooling1D()(attention_output)
        
        return output
    
    def _build_mixture_of_experts(self, inputs):
        """Mixture of Experts for different market regimes"""
        
        # Define expert networks
        n_experts = 4  # Bull, Bear, Sideways, Volatile
        expert_outputs = []
        
        for i in range(n_experts):
            expert = layers.Dense(64, activation='relu', name=f'expert_{i}')(inputs)
            expert = layers.Dropout(0.3)(expert)
            expert = layers.Dense(32, activation='relu')(expert)
            expert_outputs.append(expert)
        
        # Gating network to select experts
        gate = layers.Dense(n_experts, activation='softmax', name='gate')(inputs)
        
        # Weighted combination of experts
        expert_stack = layers.Stack(axis=1)(expert_outputs)
        gate_expanded = layers.RepeatVector(32)(gate)  # 32 is expert output dim
        gate_expanded = layers.Permute((2, 1))(gate_expanded)
        
        # Weighted sum
        weighted_experts = layers.Multiply()([expert_stack, gate_expanded])
        output = layers.Lambda(lambda x: tf.reduce_sum(x, axis=1))(weighted_experts)
        
        return output
    
    def _compile_model(self):
        """Compile with sophisticated loss and optimization"""
        
        # Use sophisticated optimizer
        optimizer = tf.keras.optimizers.AdamW(
            learning_rate=self._get_learning_rate_schedule(),
            weight_decay=1e-5,
            beta_1=0.9,
            beta_2=0.999,
            clipnorm=1.0
        )
        
        # Custom ultimate loss
        self.model.compile(
            optimizer=optimizer,
            loss=self._ultimate_loss,
            metrics=[
                self._direction_accuracy,
                self._large_move_accuracy,
                self._prediction_sharpness
            ]
        )
    
    def _get_learning_rate_schedule(self):
        """Sophisticated learning rate schedule"""
        
        # Warmup + Cosine decay
        initial_learning_rate = 1e-5
        target_learning_rate = 1e-3
        warmup_steps = 500
        decay_steps = 10000
        
        def schedule(step):
            if step < warmup_steps:
                # Linear warmup
                return initial_learning_rate + (target_learning_rate - initial_learning_rate) * (step / warmup_steps)
            else:
                # Cosine decay
                progress = (step - warmup_steps) / decay_steps
                return target_learning_rate * 0.5 * (1 + tf.cos(np.pi * progress))
        
        return tf.keras.optimizers.schedules.LearningRateSchedule(schedule)
    
    def _ultimate_loss(self, y_true, y_pred):
        """
        The ultimate loss function combining multiple objectives:
        1. Prediction accuracy (MSE)
        2. Direction accuracy
        3. Large move capture
        4. Uncertainty calibration
        5. Prediction diversity
        """
        
        # Split predictions into mean and log variance
        y_pred_mean = y_pred[:, 0]
        y_pred_log_var = y_pred[:, 1]
        
        # 1. Negative Log Likelihood with uncertainty
        # This encourages the model to be uncertain when it should be
        variance = tf.exp(y_pred_log_var) + 1e-6
        nll_loss = 0.5 * tf.reduce_mean(
            y_pred_log_var + tf.square(y_true - y_pred_mean) / variance
        )
        
        # 2. Direction loss (most important for trading)
        direction_loss = 1.0 - self._direction_accuracy(y_true, y_pred_mean)
        
        # 3. Large move capture loss
        large_move_threshold = 0.03
        is_large_move = tf.abs(y_true) > large_move_threshold
        large_move_mask = tf.cast(is_large_move, tf.float32)
        
        # Extra penalty for missing large moves
        large_move_error = tf.where(
            is_large_move,
            tf.square(y_true - y_pred_mean) * 5.0,  # 5x penalty
            tf.square(y_true - y_pred_mean)
        )
        large_move_loss = tf.reduce_mean(large_move_error)
        
        # 4. Diversity loss (prevent collapse)
        pred_std = tf.math.reduce_std(y_pred_mean)
        diversity_loss = tf.maximum(0.0, 0.02 - pred_std) * 10.0
        
        # 5. Confidence calibration
        # When prediction is wrong, uncertainty should be high
        prediction_error = tf.abs(y_true - y_pred_mean)
        expected_std = tf.sqrt(variance)
        
        # Uncertainty should correlate with error
        calibration_loss = tf.reduce_mean(
            tf.square(prediction_error - expected_std)
        )
        
        # Combine all losses with careful weighting
        total_loss = (
            0.1 * nll_loss +           # Base prediction
            0.4 * direction_loss +     # Most important
            0.2 * large_move_loss +    # Capture big moves
            0.2 * diversity_loss +     # Prevent collapse
            0.1 * calibration_loss     # Calibrated uncertainty
        )
        
        return total_loss
    
    def _direction_accuracy(self, y_true, y_pred):
        """Calculate direction accuracy metric"""
        if len(y_pred.shape) > 1 and y_pred.shape[1] > 1:
            y_pred = y_pred[:, 0]  # Use mean prediction
        
        return tf.reduce_mean(
            tf.cast(tf.sign(y_true) == tf.sign(y_pred), tf.float32)
        )
    
    def _large_move_accuracy(self, y_true, y_pred):
        """Accuracy on large moves only"""
        if len(y_pred.shape) > 1 and y_pred.shape[1] > 1:
            y_pred = y_pred[:, 0]
            
        large_moves = tf.abs(y_true) > 0.03
        if tf.reduce_sum(tf.cast(large_moves, tf.float32)) > 0:
            correct = tf.logical_and(
                large_moves,
                tf.sign(y_true) == tf.sign(y_pred)
            )
            return tf.reduce_sum(tf.cast(correct, tf.float32)) / tf.reduce_sum(tf.cast(large_moves, tf.float32))
        return tf.constant(0.0)
    
    def _prediction_sharpness(self, y_true, y_pred):
        """How confident/sharp are predictions"""
        if len(y_pred.shape) > 1 and y_pred.shape[1] > 1:
            y_pred = y_pred[:, 0]
        return tf.math.reduce_std(y_pred)
    
    def train_with_advanced_techniques(self, X_train, y_train, X_val, y_val, 
                                     epochs=200, batch_size=32):
        """
        Train with every advanced technique for best results
        """
        
        # 1. Data Augmentation
        X_train_aug, y_train_aug = self._augment_data(X_train, y_train)
        
        # 2. Multiple training runs with different initializations
        best_val_loss = float('inf')
        best_model_weights = None
        
        for run in range(3):  # Train 3 times, keep best
            logger.info(f"\n🎲 Training run {run + 1}/3 with different initialization")
            
            # Rebuild model with new random seed
            tf.random.set_seed(42 + run)
            self.build_model(
                input_shape=(X_train.shape[1], X_train.shape[2]),
                output_shape=1
            )
            
            # Advanced callbacks
            callbacks = self._get_advanced_callbacks()
            
            # Train
            history = self.model.fit(
                X_train_aug, y_train_aug,
                validation_data=(X_val, y_val),
                epochs=epochs,
                batch_size=batch_size,
                callbacks=callbacks,
                verbose=1
            )
            
            # Track best model
            val_loss = min(history.history['val_loss'])
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_model_weights = self.model.get_weights()
                logger.info(f"New best model! Val loss: {val_loss:.6f}")
        
        # Load best weights
        self.model.set_weights(best_model_weights)
        
        # 3. Fine-tune on recent data with lower learning rate
        logger.info("\n🎯 Fine-tuning on recent data...")
        self._fine_tune_recent(X_train, y_train, X_val, y_val)
        
        return history
    
    def _augment_data(self, X, y):
        """Augment training data for better generalization"""
        
        augmented_X = []
        augmented_y = []
        
        # Original data
        augmented_X.append(X)
        augmented_y.append(y)
        
        # 1. Add Gaussian noise to features
        noise = np.random.normal(0, 0.01, X.shape)
        augmented_X.append(X + noise)
        augmented_y.append(y)
        
        # 2. Time shift augmentation (shift features by 1-2 time steps)
        for shift in [1, 2]:
            shifted_X = np.roll(X, shift, axis=1)
            augmented_X.append(shifted_X)
            augmented_y.append(y)
        
        # Combine all augmented data
        X_aug = np.concatenate(augmented_X, axis=0)
        y_aug = np.concatenate(augmented_y, axis=0)
        
        # Shuffle
        indices = np.random.permutation(len(X_aug))
        return X_aug[indices], y_aug[indices]
    
    def _get_advanced_callbacks(self):
        """Get advanced training callbacks"""
        
        callbacks = []
        
        # 1. Reduce LR on plateau with patience
        reduce_lr = tf.keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.5,
            patience=10,
            min_lr=1e-7,
            verbose=1
        )
        callbacks.append(reduce_lr)
        
        # 2. Early stopping with high patience
        early_stop = tf.keras.callbacks.EarlyStopping(
            monitor='val_loss',
            patience=50,  # Very patient
            restore_best_weights=True,
            verbose=1
        )
        callbacks.append(early_stop)
        
        # 3. Custom callback for monitoring
        class PerformanceMonitor(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if epoch % 10 == 0:
                    dir_acc = logs.get('direction_accuracy', 0)
                    val_dir_acc = logs.get('val_direction_accuracy', 0)
                    print(f"\n📊 Epoch {epoch}: Train Dir Acc: {dir_acc:.3f}, Val Dir Acc: {val_dir_acc:.3f}")
        
        callbacks.append(PerformanceMonitor())
        
        return callbacks
    
    def _fine_tune_recent(self, X_train, y_train, X_val, y_val):
        """Fine-tune on recent data with careful learning rate"""
        
        # Use only last 30% of training data (most recent)
        recent_idx = int(len(X_train) * 0.7)
        X_recent = X_train[recent_idx:]
        y_recent = y_train[recent_idx:]
        
        # Very low learning rate
        self.model.optimizer.learning_rate = 1e-5
        
        # Short fine-tuning
        self.model.fit(
            X_recent, y_recent,
            validation_data=(X_val, y_val),
            epochs=10,
            batch_size=16,
            verbose=1
        )
    
    def predict_with_uncertainty(self, X):
        """Make predictions with uncertainty estimates"""
        
        predictions = self.model.predict(X)
        
        means = predictions[:, 0]
        log_vars = predictions[:, 1]
        stds = np.sqrt(np.exp(log_vars))
        
        return {
            'predictions': means,
            'uncertainty': stds,
            'lower_bound': means - 2 * stds,
            'upper_bound': means + 2 * stds
        } 