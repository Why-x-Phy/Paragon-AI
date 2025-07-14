"""
Fast Improved ML Model

This version maintains anti-collapse benefits while dramatically improving training speed
by avoiding epoch-by-epoch training loops.
"""

import tensorflow as tf
from tensorflow.keras.callbacks import Callback
import numpy as np
from src.model.ml_model_improved import ImprovedMLModel
import logging

logger = logging.getLogger(__name__)


class AntiCollapseCallback(Callback):
    """
    Custom callback that monitors for model collapse during training
    and adjusts learning rate if needed.
    """
    
    def __init__(self, X_sample, check_frequency=10):
        super().__init__()
        self.X_sample = X_sample
        self.check_frequency = check_frequency
        self.collapse_count = 0
        
    def on_epoch_end(self, epoch, logs=None):
        """Check for collapse every N epochs"""
        if epoch > 0 and epoch % self.check_frequency == 0:
            # Make predictions on sample
            y_pred = self.model.predict(self.X_sample, verbose=0)
            
            # Check variance
            pred_std = np.std(y_pred)
            pred_range = np.ptp(y_pred)
            
            if pred_std < 0.01 or pred_range < 0.02:
                self.collapse_count += 1
                logger.warning(f"Potential collapse detected at epoch {epoch}: std={pred_std:.6f}, range={pred_range:.6f}")
                
                # Increase learning rate temporarily
                current_lr = float(self.model.optimizer.learning_rate)
                new_lr = min(current_lr * 1.5, 0.01)
                self.model.optimizer.learning_rate = new_lr
                logger.info(f"Increased learning rate to {new_lr} to combat collapse")
            else:
                # Reset learning rate if predictions look good
                if hasattr(self, 'original_lr'):
                    self.model.optimizer.learning_rate = self.original_lr


class FastImprovedMLModel(ImprovedMLModel):
    """
    Fast version of improved model that uses callbacks instead of custom training loops
    """
    
    def __init__(self, model_type: str = "lstm", optimization_target: str = "anti_collapse"):
        super().__init__(model_type=model_type, optimization_target=optimization_target)
        
    def train(self, X_train, y_train, X_val, y_val, epochs=100, batch_size=32, 
              model_name=None, patience=10):
        """
        Fast training using standard Keras fit with custom callbacks
        """
        # Build model if not already built
        if self.model is None:
            self.build_model(
                input_shape=(X_train.shape[1], X_train.shape[2]),
                output_shape=1
            )
        
        # Prepare callbacks
        callbacks = self._get_callbacks(patience, model_name)
        
        # Add anti-collapse callback
        sample_size = min(100, len(X_train))
        sample_indices = np.random.choice(len(X_train), sample_size, replace=False)
        X_sample = X_train[sample_indices]
        
        anti_collapse = AntiCollapseCallback(X_sample, check_frequency=10)
        callbacks.append(anti_collapse)
        
        # Use standard Keras fit (much faster!)
        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=callbacks,
            verbose=1
        )
        
        # Save model if specified
        if model_name:
            self.save(model_name)
            
        # Log collapse detection summary
        if anti_collapse.collapse_count > 0:
            logger.warning(f"Model showed signs of collapse {anti_collapse.collapse_count} times during training")
            logger.info("Consider using a different loss function or architecture")
        
        return history.history
    
    def _build_model(self):
        """
        Build model with improvements for faster convergence
        """
        # Call parent build method
        model = super()._build_model()
        
        # Additional optimizations for speed
        # Enable mixed precision for faster GPU training
        if tf.config.list_physical_devices('GPU'):
            policy = tf.keras.mixed_precision.Policy('mixed_float16')
            tf.keras.mixed_precision.set_global_policy(policy)
            logger.info("Enabled mixed precision training for faster GPU performance")
        
        return model
    
    def _get_callbacks(self, patience=10, model_name=None):
        """
        Get optimized callbacks for fast training
        """
        callbacks = []
        
        # Early stopping with restore best weights
        early_stop = tf.keras.callbacks.EarlyStopping(
            monitor='val_loss',
            patience=patience,
            restore_best_weights=True,
            verbose=1
        )
        callbacks.append(early_stop)
        
        # Reduce learning rate when stuck
        reduce_lr = tf.keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.5,
            patience=patience//2,
            min_lr=1e-6,
            verbose=1
        )
        callbacks.append(reduce_lr)
        
        # Model checkpoint (only if name provided)
        if model_name:
            checkpoint = tf.keras.callbacks.ModelCheckpoint(
                f'models/checkpoints/{model_name}_best.h5',
                monitor='val_loss',
                save_best_only=True,
                save_weights_only=True,
                verbose=0
            )
            callbacks.append(checkpoint)
        
        return callbacks


# Convenience function for drop-in replacement
def create_fast_model(optimization_target="anti_collapse"):
    """Create a fast improved model instance"""
    return FastImprovedMLModel(optimization_target=optimization_target) 