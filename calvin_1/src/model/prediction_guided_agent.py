#!/usr/bin/env python
"""
Prediction-Guided RL Trading Agent

This module implements a reinforcement learning agent that combines
price predictions from an ML model with RL-based decision making.
"""

import os
import time
import random
import numpy as np
import pandas as pd
import tensorflow as tf
from collections import deque
from datetime import datetime
import matplotlib.pyplot as plt
from tqdm.auto import tqdm
import sys
import json
import gc

from src.utils.logger import log_manager
from src.model.fast_rl_agent import FastTradingEnvironment, FastDQNAgent

# Set up logger
logger = log_manager.get_logger("prediction_guided_agent")

# Disable TensorFlow logging for predictions to keep terminal clean
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # 0=all, 1=info, 2=warning, 3=error
# Disable eager execution warnings
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)
# Suppress step logs during prediction
tf.get_logger().setLevel('ERROR')

class PredictionGuidedEnvironment(FastTradingEnvironment):
    """Trading environment that incorporates price predictions from an ML model"""
    
    def __init__(self, price_data, feature_data, price_predictor, 
                 initial_balance=10000.0, transaction_fee=0.001,
                 risk_free_rate=0.0, sharpe_lookback=30, sharpe_weight=2.0,
                 position_sizing="fixed", max_position_pct=0.5, resolution="5m", 
                 reward_type="combined", slippage_pct=0.0015,
                 prediction_horizon=5, sequence_length=10, 
                 feature_scaler=None, price_scaler=None,
                 load_predictions_from=None, save_predictions_to=None):
        """
        Initialize enhanced trading environment with price prediction guidance
        
        Args:
            price_data: Array of historical prices
            feature_data: Array of features for state representation
            price_predictor: Trained ML model for price prediction
            initial_balance: Starting cash balance
            transaction_fee: Fee as percentage of trade value
            risk_free_rate: Annual risk-free rate for Sharpe calculation
            sharpe_lookback: Number of steps to use for Sharpe calculation
            sharpe_weight: Weight of Sharpe reward component
            position_sizing: Strategy for position sizing
            max_position_pct: Maximum position size as percentage of portfolio
            resolution: Time resolution of the data
            reward_type: Type of reward function to use
            slippage_pct: Percentage of slippage to apply to trades
            prediction_horizon: Number of steps into the future for predictions
            sequence_length: Length of sequence for prediction input
            feature_scaler: Scaler used to normalize features
            price_scaler: Scaler used to normalize prices
            load_predictions_from: Path to CSV file to load predictions from
            save_predictions_to: Path to CSV file to save predictions to
        """
        # Initialize prediction-related attributes first
        self.predictor = price_predictor
        self.prediction_horizon = prediction_horizon
        self.sequence_length = sequence_length
        self.feature_scaler = feature_scaler
        self.price_scaler = price_scaler
        self.prediction_errors = []
        self.max_error_history = 50
        self.prediction_confidence = 0.5  # Initial confidence
        self.cached_predictions = None
        self.save_predictions_to = save_predictions_to
        
        # Store raw price data for feature engineering
        self.raw_price_data = np.array(price_data)

        # Initialize parent class
        super().__init__(
            price_data=price_data, 
            feature_data=feature_data,
            initial_balance=initial_balance,
            transaction_fee=transaction_fee,
            risk_free_rate=risk_free_rate,
            sharpe_lookback=sharpe_lookback,
            sharpe_weight=sharpe_weight,
            position_sizing=position_sizing,
            max_position_pct=max_position_pct,
            resolution=resolution,
            reward_type=reward_type,
            slippage_pct=slippage_pct
        )
        
        # Try to load predictions if a file is specified
        if load_predictions_from and os.path.exists(load_predictions_from):
            try:
                logger.info(f"Loading cached predictions from {load_predictions_from}")
                self.cached_predictions = self._load_predictions(load_predictions_from)
                logger.info(f"Loaded {len(self.cached_predictions)} predictions")
            except Exception as e:
                logger.error(f"Failed to load predictions: {e}")
                self.cached_predictions = None
        
        # Precompute predictions if not loaded from file
        if self.cached_predictions is None:
            try:
                # Temporarily disable progress bar output for cleaner terminal
                original_stdout = sys.stdout
                sys.stdout = open(os.devnull, 'w')
                
                # Calculate predictions
                self.cached_predictions = self._precompute_predictions()
                
                # Restore stdout
                sys.stdout.close()
                sys.stdout = original_stdout
                
                # Save predictions if requested
                if self.save_predictions_to:
                    self._save_predictions(self.save_predictions_to)
            except Exception as e:
                logger.error(f"Error during prediction precomputation: {e}")
                self.cached_predictions = None
            
        logger.info(f"Initialized prediction-guided environment with prediction horizon {prediction_horizon}")
    
    def _prepare_prediction_input(self, step):
        """Prepare input for the price prediction model"""
        # Ensure we have enough data for sequence
        if step < self.sequence_length:
            return None
            
        # Extract sequence of features before current step
        try:
            # Handle case where sequence_length is greater than available normalized features
            if self.sequence_length > len(self.normalized_features):
                logger.warning(f"Sequence length {self.sequence_length} is greater than available normalized features {len(self.normalized_features)}. Using all available features.")
                feature_sequence = self.normalized_features[0:step]
            else:
                feature_sequence = self.normalized_features[step-self.sequence_length:step]
                
            # Add price data to features if we have a shape mismatch
            if self.predictor.model and hasattr(self.predictor.model, 'input_shape'):
                expected_shape = self.predictor.model.input_shape
                if len(expected_shape) > 2 and expected_shape[2] is not None:
                    expected_features = expected_shape[2]
                    if feature_sequence.shape[1] < expected_features:
                        # We need to add 5 more features (OHLCV)
                        missing_features = expected_features - feature_sequence.shape[1]
                        if missing_features == 5 and step >= self.sequence_length:
                            # Extract price data for the same sequence
                            price_slice = self.raw_price_data[step-self.sequence_length:step]
                            
                            # If price data is 1D, reshape it to be 2D with a single column
                            if len(price_slice.shape) == 1:
                                price_slice = price_slice.reshape(-1, 1)
                                
                                # Duplicate into OHLCV format (5 columns)
                                # This is just a workaround if we only have close prices
                                price_features = np.repeat(price_slice, 5, axis=1)
                            else:
                                # Use first 5 columns or pad as needed
                                price_cols = min(price_slice.shape[1], 5)
                                if price_cols < 5:
                                    # Pad with repeat of last column
                                    padding = np.repeat(price_slice[:, -1:], 5-price_cols, axis=1)
                                    price_features = np.hstack((price_slice, padding))
                                else:
                                    price_features = price_slice[:, :5]
                            
                            # Scale price features if scaler is available
                            if self.price_scaler is not None:
                                try:
                                    # Check if price_scaler is fitted
                                    if not hasattr(self.price_scaler, 'n_samples_seen_') or self.price_scaler.n_samples_seen_ is None:
                                        # Fit the scaler on the price data
                                        # Only log this once
                                        if not hasattr(self, '_scaler_fit_logged'):
                                            logger.warning("Price scaler not fitted. Fitting on available price data.")
                                            self._scaler_fit_logged = True
                                        self.price_scaler.fit(self.raw_price_data.reshape(-1, 1))
                                    
                                    # Scale each column separately
                                    for i in range(price_features.shape[1]):
                                        price_features[:, i] = self.price_scaler.transform(
                                            price_features[:, i].reshape(-1, 1)
                                        ).flatten()
                                except Exception as e:
                                    logger.warning(f"Error scaling price features: {e}. Using unscaled values.")
                            
                            # Concatenate original features with price features
                            # Ensure both arrays have the same sequence length
                            min_len = min(feature_sequence.shape[0], price_features.shape[0])
                            feature_sequence = np.hstack((
                                feature_sequence[-min_len:],
                                price_features[-min_len:]
                            ))
            
            # Reshape for model input (batch_size, sequence_length, features)
            sequence = np.expand_dims(feature_sequence, axis=0)
            
            # Check if sequence has expected dimensions for the model
            if self.predictor.model and hasattr(self.predictor.model, 'input_shape'):
                expected_shape = self.predictor.model.input_shape
                if len(expected_shape) > 1 and expected_shape[1] is not None:
                    # Handle sequence length mismatch
                    expected_seq_len = expected_shape[1]
                    if sequence.shape[1] != expected_seq_len:
                        # Only log this warning once to avoid terminal spam
                        if not hasattr(self, '_seq_mismatch_logged'):
                            logger.warning(f"Sequence length mismatch: got {sequence.shape[1]}, model expects {expected_seq_len}. Padding or truncating.")
                            self._seq_mismatch_logged = True
                        
                        # Pad or truncate sequence to match model's expected length
                        if sequence.shape[1] < expected_seq_len:
                            # Pad with zeros
                            padding = np.zeros((1, expected_seq_len - sequence.shape[1], sequence.shape[2]))
                            sequence = np.concatenate([padding, sequence], axis=1)
                        else:
                            # Truncate
                            sequence = sequence[:, -expected_seq_len:, :]
                    
                    # Handle feature dimension mismatch
                    expected_features = expected_shape[2]
                    if sequence.shape[2] != expected_features:
                        # Only log this warning once to avoid terminal spam
                        if not hasattr(self, '_feature_mismatch_logged'):
                            logger.warning(f"Feature dimension mismatch: got {sequence.shape[2]}, model expects {expected_features}. Adjusting dimensions.")
                            self._feature_mismatch_logged = True
                            
                        if sequence.shape[2] < expected_features:
                            # Pad with zeros to match expected feature count
                            padding = np.zeros((sequence.shape[0], sequence.shape[1], expected_features - sequence.shape[2]))
                            sequence = np.concatenate([sequence, padding], axis=2)
                        else:
                            # Truncate features (not ideal, but allows the model to run)
                            sequence = sequence[:, :, :expected_features]
            
            return sequence
        except Exception as e:
            logger.warning(f"Error preparing prediction input at step {step}: {e}")
            return None
    
    def _precompute_predictions(self):
        """Pre-compute price predictions for the entire dataset"""
        try:
            logger.info("Pre-computing price predictions for efficiency...")
            predictions = []
            
            # Create progress bar
            with tqdm(total=len(self.prices) - self.prediction_horizon, desc="Precomputing predictions") as pbar:
                for step in range(len(self.prices) - self.prediction_horizon):
                    # Get feature sequence for prediction
                    sequence = self._prepare_prediction_input(step)
                    
                    if sequence is not None:
                        # Get prediction
                        try:
                            # Suppress TensorFlow output during prediction
                            tf_verbosity = tf.get_logger().getEffectiveLevel()
                            tf.get_logger().setLevel('ERROR')
                            
                            # Make prediction
                            pred = self.predictor.predict(sequence)[0]
                            
                            # Restore TensorFlow logging level
                            tf.get_logger().setLevel(tf_verbosity)
                            
                            # Inverse transform if a price scaler is provided
                            if self.price_scaler is not None:
                                pred = self.price_scaler.inverse_transform(pred.reshape(-1, 1)).flatten()
                                
                            predictions.append(pred)
                        except Exception as e:
                            # Only log a limited number of prediction errors
                            if len(predictions) % 100 == 0 or len(predictions) < 10:
                                logger.warning(f"Error making prediction at step {step}: {e}")
                            predictions.append(None)
                    else:
                        # If not enough data, use None as placeholder
                        predictions.append(None)
                        
                    pbar.update(1)
            
            logger.info(f"Pre-computed {len(predictions)} price predictions")
            return predictions
            
        except Exception as e:
            logger.warning(f"Could not pre-compute predictions: {e}. Will calculate on-the-fly.")
            return None
    
    def _save_predictions(self, filepath):
        """Save predictions to CSV file for reuse"""
        if self.cached_predictions is None:
            logger.warning("No predictions to save")
            return
            
        try:
            logger.info(f"Saving predictions to {filepath}")
            # Convert predictions to DataFrame
            pred_data = []
            for i, pred in enumerate(self.cached_predictions):
                if pred is not None:
                    # For multi-step predictions, save all steps
                    for j, p in enumerate(pred):
                        pred_data.append({
                            'step': i,
                            'horizon': j+1,
                            'prediction': p
                        })
                        
            df = pd.DataFrame(pred_data)
            df.to_csv(filepath, index=False)
            logger.info(f"Saved {len(pred_data)} predictions to {filepath}")
        except Exception as e:
            logger.error(f"Error saving predictions: {e}")
    
    def _load_predictions(self, filepath):
        """Load predictions from CSV file"""
        try:
            df = pd.read_csv(filepath)
            
            # Convert back to list format
            predictions = [None] * (df['step'].max() + 1)
            
            # Group by step
            for step, group in df.groupby('step'):
                # Sort by horizon
                group = group.sort_values('horizon')
                # Create prediction array
                pred = group['prediction'].values
                predictions[step] = pred
                
            return predictions
        except Exception as e:
            logger.error(f"Error loading predictions: {e}")
            return None
    
    def _get_price_prediction(self, step):
        """Get price prediction for the current step"""
        # Use cached prediction if available
        if self.cached_predictions is not None and step < len(self.cached_predictions):
            return self.cached_predictions[step]
            
        # Otherwise compute on-the-fly
        sequence = self._prepare_prediction_input(step)
        if sequence is None:
            return None
            
        # Get raw prediction
        try:
            # Temporarily suppress TensorFlow output
            tf_verbosity = tf.get_logger().getEffectiveLevel()
            tf.get_logger().setLevel('ERROR')
            
            # Make prediction
            pred = self.predictor.predict(sequence)[0]
            
            # Restore TensorFlow logging level
            tf.get_logger().setLevel(tf_verbosity)
            
            # Inverse transform if needed
            if self.price_scaler is not None:
                pred = self.price_scaler.inverse_transform(pred.reshape(-1, 1)).flatten()
                
            return pred
        except Exception as e:
            logger.warning(f"Error making prediction at step {step}: {e}")
            return None
    
    def _update_prediction_tracking(self, step):
        """Track prediction accuracy for adaptive confidence"""
        # Only update if we've made predictions in the past
        if step >= self.prediction_horizon and step - self.prediction_horizon >= 0:
            # Get previous prediction
            past_prediction = self._get_price_prediction(step - self.prediction_horizon)
            
            if past_prediction is not None:
                # Compare with actual price
                actual_price = self.prices[step]
                predicted_price = past_prediction[0]  # First prediction step
                
                # Calculate error as percentage of price
                if actual_price > 0:
                    error = abs(predicted_price - actual_price) / actual_price
                    
                    # Add to error history
                    self.prediction_errors.append(error)
                    
                    # Keep history within limits
                    if len(self.prediction_errors) > self.max_error_history:
                        self.prediction_errors.pop(0)
                        
                    # Update confidence based on recent errors
                    self.prediction_confidence = self._calculate_prediction_confidence()
    
    def _calculate_prediction_confidence(self):
        """Calculate confidence in predictions based on recent accuracy"""
        if len(self.prediction_errors) < 5:
            return 0.5  # Default medium confidence with insufficient data
            
        # Calculate normalized mean absolute error
        mean_error = np.mean(self.prediction_errors)
        
        # Convert error to confidence (higher error = lower confidence)
        # Clip between 0.1 and 0.9
        confidence = np.clip(1.0 - mean_error, 0.1, 0.9)
        
        return confidence
    
    def _get_observation(self):
        """Create enhanced observation with prediction data"""
        # Get base observation from parent class
        base_obs = super()._get_observation()
        
        # Add prediction information
        prediction = self._get_price_prediction(self.current_step)
        
        if prediction is None:
            # If no prediction available, add zeros
            prediction_features = np.zeros(self.prediction_horizon)
        else:
            try:
                # Calculate predicted returns relative to current price
                current_price = self.prices[self.current_step]
                
                # Ensure prediction is at least as long as prediction_horizon
                if len(prediction) < self.prediction_horizon:
                    # Pad with last value
                    padding = np.full(self.prediction_horizon - len(prediction), prediction[-1])
                    prediction = np.concatenate([prediction, padding])
                    
                prediction_features = np.array([
                    (pred_price - current_price) / current_price 
                    for pred_price in prediction[:self.prediction_horizon]
                ])
                
                # Clip to reasonable range
                prediction_features = np.clip(prediction_features, -0.1, 0.1)
            except Exception as e:
                logger.warning(f"Error calculating prediction features: {e}")
                prediction_features = np.zeros(self.prediction_horizon)
        
        # Create enhanced observation
        enhanced_obs = np.concatenate([
            base_obs,
            prediction_features,
            [self.prediction_confidence]  # Add confidence as feature
        ])
        
        # Update prediction tracking
        self._update_prediction_tracking(self.current_step)
        
        return enhanced_obs
        
    def step(self, action):
        """Enhanced step function that incorporates prediction confidence"""
        # Run standard step
        try:
            obs, reward, done, info = super().step(action)
            
            # Get latest prediction
            prediction = self._get_price_prediction(self.current_step)
            
            # Add prediction info to info dict
            info['prediction'] = prediction
            info['prediction_confidence'] = self.prediction_confidence
            
            # Ensure portfolio_value is always in info
            if 'portfolio_value' not in info:
                portfolio_value = self.balance
                if self.position == 1 and self.shares_held > 0:
                    portfolio_value += self.shares_held * self.prices[min(self.current_step, len(self.prices)-1)]
                info['portfolio_value'] = portfolio_value
            
            return obs, reward, done, info
        except Exception as e:
            logger.error(f"Error in step method: {e}")
            # Create a minimal valid return
            return np.zeros_like(self._get_observation()), 0.0, True, {
                'portfolio_value': self.initial_balance,
                'prediction': None,
                'prediction_confidence': 0.0,
                'error': str(e)
            }
        
    def reset(self):
        """Reset the environment and prediction tracking"""
        # Reset parent environment
        observation = super().reset()
        
        # Reset prediction tracking
        self.prediction_errors = []
        self.prediction_confidence = 0.5
        
        return observation 

class PredictionGuidedAgent(FastDQNAgent):
    """
    DQN agent enhanced with prediction guidance from ML model
    """
    def __init__(self, state_size, action_size, initial_balance=10000,
                 memory_size=20000, gamma=0.95, epsilon=1.0, 
                 epsilon_min=0.01, epsilon_decay=0.995, learning_rate=0.001,
                 batch_size=32, network_type="simple"):
                 
        # Call parent constructor with only the parameters it expects
        super().__init__(
            state_size=state_size, 
            action_size=action_size,
            network_type=network_type
        )
        
        # Set the remaining parameters directly
        self.initial_balance = initial_balance
        self.memory_size = memory_size
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        
        # Enhanced replay with better performance
        self.memory = deque(maxlen=memory_size)
        
        # Track which states we've seen for duplicate prevention
        self.state_hashes = set()
    
    def remember(self, state, action, reward, next_state, done):
        """Store experience in memory with duplicate prevention for similar states"""
        # Store experience tuple in memory
        self.memory.append((state, action, reward, next_state, done))
    
    def optimize_memory(self, max_size=None):
        """
        Optimize memory usage by removing low-value experiences when memory gets too large
        This helps prevent memory issues during long training runs
        """
        if max_size is None or len(self.memory) <= max_size:
            return
            
        logger.debug(f"Optimizing agent memory from {len(self.memory)} to {max_size} entries")
        
        # Strategy: Keep more recent experiences and high-reward experiences
        # Sort experiences by importance: recent + high absolute reward are most valuable
        memory_list = list(self.memory)
        
        # Create scores based on recency and reward magnitude
        rewards = np.array([abs(exp[2]) for exp in memory_list])  # absolute reward values
        max_reward = np.max(rewards) if len(rewards) > 0 and np.max(rewards) > 0 else 1.0
        
        # Calculate importance scores: 50% recency, 50% reward magnitude
        scores = []
        for i, (_, _, reward, _, _) in enumerate(memory_list):
            recency_score = i / len(memory_list)  # 0 to 1, higher for more recent
            reward_score = abs(reward) / max_reward if max_reward > 0 else 0
            score = 0.5 * recency_score + 0.5 * reward_score
            scores.append(score)
        
        # Sort by importance score and keep the most valuable experiences
        sorted_indices = np.argsort(scores)
        keep_indices = sorted_indices[-max_size:]  # Keep highest scores
        
        # Create new memory with only the most valuable experiences
        new_memory = deque(maxlen=max_size)
        for idx in keep_indices:
            new_memory.append(memory_list[idx])
        
        # Replace memory with optimized version
        self.memory = new_memory
        logger.debug(f"Memory optimized to {len(self.memory)} entries")
        
    def replay(self, batch_size):
        """Train the neural network on batches of experiences"""
        if len(self.memory) < batch_size:
            return
            
        # Sample random mini-batch
        minibatch = random.sample(self.memory, batch_size)
        
        # Extract state arrays for efficient batch processing
        state_arrays = np.array([exp[0] for exp in minibatch])
        next_state_arrays = np.array([exp[3] for exp in minibatch])
        
        # Use vectorized predictions for efficiency
        targets = self.model.predict(state_arrays, verbose=0)
        next_state_values = np.amax(self.model.predict(next_state_arrays, verbose=0), axis=1)
        
        # Update targets with reward and discounted next state value
        for i, (_, action, reward, _, done) in enumerate(minibatch):
            if done:
                targets[i, action] = reward
            else:
                targets[i, action] = reward + self.gamma * next_state_values[i]
        
        # Train model with updated targets
        self.model.fit(state_arrays, targets, epochs=1, verbose=0, batch_size=batch_size)
        
        # Update exploration rate
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

def train_prediction_guided_agent(
    price_data, 
    feature_data, 
    price_predictor,  # ML price prediction model
    feature_scaler,   # Scaler from DataProcessor
    price_scaler,     # Scaler from DataProcessor
    sequence_length=10,
    prediction_horizon=5,
    episodes=100, 
    batch_size=256,
    initial_balance=10000.0,
    model_name=None,
    network_type="deep",  # Use deeper network for more complex state
    risk_free_rate=0.0,
    sharpe_lookback=30,
    sharpe_weight=2.0,
    position_sizing="fixed",
    max_position_pct=0.2,
    resolution="5m",
    reward_type="combined",
    slippage_pct=0.0015,
    memory_buffer_size=10000,
    load_predictions_from=None,
    save_predictions_to=None,
    token_symbol="UNKNOWN",
    days_of_data=0
):
    """
    Train an RL agent enhanced with price predictions
    
    Args:
        price_data: Historical price data
        feature_data: Feature data for state representation
        price_predictor: Trained ML model for price prediction
        feature_scaler: Scaler used to normalize features
        price_scaler: Scaler used to normalize prices
        sequence_length: Length of sequence for prediction input
        prediction_horizon: Number of steps into future to predict
        episodes: Number of episodes to train for
        batch_size: Training batch size
        initial_balance: Starting balance for trading
        model_name: Name for saving the model
        network_type: Type of neural network to use
        risk_free_rate: Annual risk-free rate for Sharpe ratio
        sharpe_lookback: Lookback period for Sharpe calculation
        sharpe_weight: Weight of Sharpe ratio in reward
        position_sizing: Strategy for position sizing
        max_position_pct: Maximum position size
        resolution: Time resolution of the data
        reward_type: Type of reward function
        slippage_pct: Trading slippage percentage
        memory_buffer_size: Size of replay memory buffer
        load_predictions_from: Path to CSV file to load predictions from
        save_predictions_to: Path to CSV file to save predictions to
        token_symbol: Symbol of the token being trained on (for filename)
        days_of_data: Number of days of data used (for filename)
        
    Returns:
        Trained agent and environment
    """
    start_time = time.time()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Configure TensorFlow for better performance
    tf.get_logger().setLevel('ERROR')
    physical_devices = tf.config.list_physical_devices('GPU')
    if physical_devices:
        for device in physical_devices:
            try:
                tf.config.experimental.set_memory_growth(device, True)
                logger.info(f"Configured GPU {device} for memory growth")
            except Exception as e:
                logger.warning(f"Could not configure GPU: {e}")
    
    # Use mixed precision training if on GPU for better performance
    if physical_devices:
        mixed_precision = tf.keras.mixed_precision.Policy('mixed_float16')
        tf.keras.mixed_precision.set_global_policy(mixed_precision)
        logger.info("Using mixed precision training for better performance")
    
    # Progress tracking setup
    episode_bar = tqdm(total=episodes, desc=f"Training episodes", position=0)
    step_bar = tqdm(total=100, desc="Current episode", position=1, leave=False)
    
    # Performance tracking variables
    total_reward_history = []
    episode_profits = []
    episode_sharpe_ratios = []
    best_profit = float('-inf')
    
    # Generate default prediction filename if not provided
    if save_predictions_to is None and token_symbol != "UNKNOWN":
        # Create models/predictions directory if it doesn't exist
        pred_dir = os.path.join("models", "predictions")
        os.makedirs(pred_dir, exist_ok=True)
        
        # Create filename with token, days, and timestamp
        save_predictions_to = os.path.join(
            pred_dir, 
            f"{token_symbol}_{days_of_data}d_{resolution}_{prediction_horizon}h_{timestamp}.csv"
        )
        logger.info(f"Auto-generating prediction save path: {save_predictions_to}")
    
    # Create prediction save path if specified but doesn't exist
    if save_predictions_to:
        os.makedirs(os.path.dirname(os.path.abspath(save_predictions_to)), exist_ok=True)
    
    # Initialize environment with prediction guidance
    env = PredictionGuidedEnvironment(
        price_data=price_data,
        feature_data=feature_data,
        price_predictor=price_predictor,
        initial_balance=initial_balance,
        transaction_fee=0.001,
        risk_free_rate=risk_free_rate,
        sharpe_lookback=sharpe_lookback,
        sharpe_weight=sharpe_weight,
        position_sizing=position_sizing,
        max_position_pct=max_position_pct,
        resolution=resolution,
        reward_type=reward_type,
        slippage_pct=slippage_pct,
        prediction_horizon=prediction_horizon,
        sequence_length=sequence_length,
        feature_scaler=feature_scaler,
        price_scaler=price_scaler,
        load_predictions_from=load_predictions_from,
        save_predictions_to=save_predictions_to
    )
    
    # Get initial observation to determine state size
    initial_state = env.reset()
    state_size = len(initial_state)
    action_size = 3  # hold, buy, sell
    
    # Log enhanced state information
    base_state_size = len(price_data[0]) if hasattr(price_data[0], '__len__') else 1
    logger.info(f"Using prediction-guided agent with state size {state_size}")
    logger.info(f"  - Added {prediction_horizon} prediction features and 1 confidence feature")
    
    # Create model name if not provided
    if model_name is None:
        model_name = f"prediction_guided_{token_symbol}_{days_of_data}d_{resolution}_{network_type}_{timestamp}"
        
    # Initialize agent with the enhanced state size
    agent = PredictionGuidedAgent(
        state_size=state_size, 
        action_size=action_size, 
        initial_balance=initial_balance,
        memory_size=memory_buffer_size,
        gamma=0.95,
        epsilon=1.0,
        epsilon_min=0.01,
        epsilon_decay=0.995,
        learning_rate=0.001,
        batch_size=batch_size,
        network_type=network_type
    )
    
    logger.info(f"Starting training for {episodes} episodes")
    logger.info(f"Network type: {network_type}, Batch size: {batch_size}")
    
    # Estimate steps per episode for progress tracking
    est_steps = len(price_data) - sequence_length - prediction_horizon
    
    # Create a directory for model checkpoints if it doesn't exist
    checkpoint_dir = os.path.join("models", "checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)
    
    # Training loop with improved batching and memory management
    for episode in range(episodes):
        # Reset environment at start of episode
        state = env.reset()
        total_reward = 0
        done = False
        
        # Reset step progress bar
        step_bar.reset(total=est_steps)
        step_bar.set_description(f"Episode {episode+1}/{episodes}")
        
        # Track episode performance
        episode_start_time = time.time()
        step_count = 0
        last_batch_at = 0
        batch_interval = 10  # Train every 10 steps
        
        # Store experiences for batch training
        episode_states = []
        episode_actions = []
        episode_rewards = []
        episode_next_states = []
        episode_dones = []
        
        # Episode loop with batched training
        while not done:
            # Choose action using epsilon-greedy policy
            action = agent.act(state)
            
            # Apply selected action in environment
            next_state, reward, done, info = env.step(action)
            
            # Store experience in replay buffer
            agent.remember(state, action, reward, next_state, done)
            
            # Also store in episodic batch
            episode_states.append(state)
            episode_actions.append(action)
            episode_rewards.append(reward)
            episode_next_states.append(next_state)
            episode_dones.append(done)
            
            # Update state and accumulate reward
            state = next_state
            total_reward += reward
            step_count += 1
            
            # Update progress bar every 10 steps
            if step_count % 10 == 0:
                step_bar.update(10)
                step_bar.set_postfix({
                    'reward': f"{total_reward:.1f}", 
                    'epsilon': f"{agent.epsilon:.2f}",
                    'balance': f"${info.get('portfolio_value', 0):.0f}"
                })
            
            # Train in mini-batches for better performance
            if len(agent.memory) > batch_size and step_count - last_batch_at >= batch_interval:
                agent.replay(batch_size)
                last_batch_at = step_count
                
            # Periodically optimize memory
            if step_count % 500 == 0:
                agent.optimize_memory(max_size=memory_buffer_size)
                # Force garbage collection
                gc.collect()
        
        # Complete step bar
        step_bar.update(est_steps - step_bar.n)
        
        # Final batch training at end of episode
        if len(agent.memory) > batch_size:
            for _ in range(3):  # Train multiple times at episode end
                agent.replay(batch_size)
        
        # Track episode metrics
        episode_profit = info.get('profit', 0)
        episode_sharpe = info.get('sharpe_ratio', 0)
        
        total_reward_history.append(total_reward)
        episode_profits.append(episode_profit)
        episode_sharpe_ratios.append(episode_sharpe)
        
        # Update progress display
        episode_time = time.time() - episode_start_time
        steps_per_sec = step_count / episode_time if episode_time > 0 else 0
        
        episode_bar.update(1)
        episode_bar.set_postfix({
            'reward': f"{total_reward:.1f}",
            'profit': f"${episode_profit:.0f}",
            'steps/s': f"{steps_per_sec:.1f}"
        })
        
        # Save checkpoints based on performance
        if episode_profit > best_profit and episode > 5:
            best_profit = episode_profit
            # Save high performance model
            best_model_path = os.path.join(checkpoint_dir, f"{model_name}_best")
            agent.save(best_model_path)
            logger.info(f"New best profit ${episode_profit:.2f} - saved model to {best_model_path}")
        
        # Regular checkpoint saving
        if episode > 0 and episode % 10 == 0:
            checkpoint_path = os.path.join(checkpoint_dir, f"{model_name}_ep{episode}")
            agent.save(checkpoint_path)
            logger.info(f"Saved checkpoint at episode {episode} to {checkpoint_path}")
        
        # Log episode results
        logger.info(f"Episode {episode+1}/{episodes} - " 
                   f"Reward: {total_reward:.2f}, "
                   f"Profit: ${episode_profit:.2f}, "
                   f"Sharpe: {episode_sharpe:.2f}, "
                   f"Time: {episode_time:.1f}s")
        
        # Memory cleanup between episodes
        if episode % 5 == 0:
            tf.keras.backend.clear_session()
            gc.collect()
    
    # Close progress bars
    step_bar.close()
    episode_bar.close()
    
    # Save final model
    agent.save(model_name)
    logger.info(f"Training completed in {time.time() - start_time:.1f} seconds")
    logger.info(f"Final model saved as: {model_name}")
    
    # Create and save training performance plot
    plt.figure(figsize=(12, 8))
    
    plt.subplot(3, 1, 1)
    plt.plot(total_reward_history)
    plt.title('Episode Rewards During Training')
    plt.ylabel('Total Reward')
    
    plt.subplot(3, 1, 2)
    plt.plot(episode_profits)
    plt.title('Episode Profits During Training')
    plt.ylabel('Profit ($)')
    
    plt.subplot(3, 1, 3)
    plt.plot(episode_sharpe_ratios)
    plt.title('Episode Sharpe Ratios During Training')
    plt.ylabel('Sharpe Ratio')
    plt.xlabel('Episode')
    
    plt.tight_layout()
    plt.savefig(f"models/{model_name}_training_history.png")
    
    return agent, env

def evaluate_prediction_guided_agent(
    agent,
    price_data,
    feature_data,
    price_predictor,
    feature_scaler=None,
    price_scaler=None,
    initial_balance=10000.0,
    max_eval_time=300,  # Max time in seconds for evaluation
    risk_free_rate=0.0,
    sharpe_lookback=30,
    sharpe_weight=2.0,
    position_sizing="fixed",
    max_position_pct=0.2,
    resolution="5m",
    reward_type="combined",
    slippage_pct=0.0015,
    sequence_length=10,
    prediction_horizon=5,
    verbose=True,
    load_predictions_from=None,
    save_predictions_to=None,
    token_symbol="UNKNOWN",
    days_of_data=0
):
    """
    Evaluate a trained prediction-guided agent on new data
    
    Args:
        agent: Trained FastDQNAgent
        price_data: Price data to evaluate on
        feature_data: Feature data for state representation
        price_predictor: Trained ML model for price prediction
        feature_scaler: Scaler used to normalize features
        price_scaler: Scaler used to normalize prices
        initial_balance: Starting balance for evaluation
        max_eval_time: Maximum evaluation time in seconds
        risk_free_rate: Annual risk-free rate for Sharpe ratio
        sharpe_lookback: Lookback period for Sharpe calculation
        sharpe_weight: Weight of Sharpe ratio in reward
        position_sizing: Strategy for position sizing
        max_position_pct: Maximum position size
        resolution: Time resolution of the data
        reward_type: Type of reward function
        slippage_pct: Trading slippage percentage
        sequence_length: Length of sequence for prediction input
        prediction_horizon: Number of steps into future to predict
        verbose: Whether to print detailed results
        load_predictions_from: Path to CSV file to load predictions from
        save_predictions_to: Path to CSV file to save predictions to
        token_symbol: Symbol of the token being evaluated (for filename)
        days_of_data: Number of days of data used (for filename)
        
    Returns:
        Dictionary with evaluation results
    """
    start_time = time.time()
    logger.info(f"Evaluating prediction-guided agent on {len(price_data)} data points")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Generate default prediction filename if not provided
    if save_predictions_to is None and token_symbol != "UNKNOWN":
        # Create models/predictions directory if it doesn't exist
        pred_dir = os.path.join("models", "predictions")
        os.makedirs(pred_dir, exist_ok=True)
        
        # Create filename with token, days, and timestamp
        save_predictions_to = os.path.join(
            pred_dir, 
            f"{token_symbol}_{days_of_data}d_{resolution}_{prediction_horizon}h_eval_{timestamp}.csv"
        )
        logger.info(f"Auto-generating prediction save path: {save_predictions_to}")
    
    # Create prediction save path if specified but doesn't exist
    if save_predictions_to:
        os.makedirs(os.path.dirname(os.path.abspath(save_predictions_to)), exist_ok=True)
    
    # Initialize environment with evaluation data
    env = PredictionGuidedEnvironment(
        price_data=price_data,
        feature_data=feature_data,
        price_predictor=price_predictor,
        initial_balance=initial_balance,
        transaction_fee=0.001,
        risk_free_rate=risk_free_rate,
        sharpe_lookback=sharpe_lookback,
        sharpe_weight=sharpe_weight,
        position_sizing=position_sizing,
        max_position_pct=max_position_pct,
        resolution=resolution,
        reward_type=reward_type,
        slippage_pct=slippage_pct,
        prediction_horizon=prediction_horizon,
        sequence_length=sequence_length,
        feature_scaler=feature_scaler,
        price_scaler=price_scaler,
        load_predictions_from=load_predictions_from,
        save_predictions_to=save_predictions_to
    )
    
    # Run through environment once
    state = env.reset()
    done = False
    rewards = []
    actions_taken = []
    portfolio_values = []
    prediction_history = []
    confidence_history = []
    
    # Run evaluation with timeout protection
    logger.info("Running evaluation episode...")
    
    with tqdm(total=len(price_data), desc="Evaluating") as pbar:
        while not done:
            # Check if we've exceeded the time limit
            if time.time() - start_time > max_eval_time:
                logger.warning(f"Evaluation time limit of {max_eval_time}s exceeded. Terminating early.")
                break
                
            # Get action from agent (no exploration)
            action = agent.act(state, training=False)
            
            # Take action in environment
            next_state, reward, done, info = env.step(action)
            
            # Track metrics
            rewards.append(reward)
            actions_taken.append(action)
            portfolio_values.append(info.get('portfolio_value', 0))
            
            # Track prediction information
            if 'prediction' in info and info['prediction'] is not None:
                prediction_history.append(info['prediction'][0])  # First prediction step
            else:
                prediction_history.append(None)
                
            confidence_history.append(info.get('prediction_confidence', 0))
            
            # Move to next state
            state = next_state
            pbar.update(1)
    
    # Collect evaluation metrics
    final_value = env.portfolio_values[-1]
    roi = (final_value / initial_balance - 1) * 100
    buy_hold_value = initial_balance * price_data[-1] / price_data[0]
    buy_hold_roi = (buy_hold_value / initial_balance - 1) * 100
    
    # Calculate trade statistics
    total_trades = len(env.trades)
    if total_trades > 0:
        profitable_trades = sum(1 for trade in env.trades if trade.get('type') == 'sell' and trade.get('profit', 0) > 0)
        win_rate = profitable_trades / total_trades if total_trades > 0 else 0
    else:
        profitable_trades = 0
        win_rate = 0
    
    # Calculate Sharpe ratio
    if len(env.daily_returns) > 30:
        returns_mean = np.mean(env.daily_returns)
        returns_std = np.std(env.daily_returns)
        if returns_std > 0:
            sharpe = (returns_mean - risk_free_rate / 252) / returns_std * np.sqrt(252)
        else:
            sharpe = 0
    else:
        sharpe = 0
        
    # Analyze prediction accuracy
    if len(env.prediction_errors) > 0:
        avg_prediction_error = np.mean(env.prediction_errors)
    else:
        avg_prediction_error = 0
        
    # Analyze prediction contribution
    prediction_correlation = 0
    if len(prediction_history) > 30 and len(portfolio_values) > 30:
        valid_predictions = [p for p in prediction_history if p is not None]
        if len(valid_predictions) > 30:
            try:
                # Calculate correlation between predictions and portfolio performance
                portfolio_returns = np.diff(portfolio_values)
                prediction_values = valid_predictions[:len(portfolio_returns)]
                if len(prediction_values) > 30:
                    prediction_correlation = np.corrcoef(portfolio_returns[-30:], prediction_values[-30:])[0, 1]
            except:
                prediction_correlation = 0
    
    # Format results
    results = {
        'final_value': final_value,
        'roi': roi,
        'buy_hold_return': buy_hold_roi,
        'outperformance': roi - buy_hold_roi,
        'sharpe_ratio': sharpe,
        'total_trades': total_trades,
        'profitable_trades': profitable_trades,
        'win_rate': win_rate,
        'avg_prediction_error': avg_prediction_error,
        'prediction_correlation': prediction_correlation,
        'evaluation_time': time.time() - start_time
    }
    
    # Print results if verbose
    if verbose:
        logger.info("Evaluation Results:")
        logger.info(f"Final Portfolio Value: ${results['final_value']:.2f}")
        logger.info(f"Return on Investment: {results['roi']:.2f}%")
        logger.info(f"Buy & Hold Return: {results['buy_hold_return']:.2f}%")
        logger.info(f"Outperformance vs Buy & Hold: {results['outperformance']:.2f}%")
        logger.info(f"Sharpe Ratio: {results['sharpe_ratio']:.4f}")
        logger.info(f"Total Trades: {results['total_trades']}")
        logger.info(f"Win Rate: {results['win_rate']:.2%}")
        logger.info(f"Average Prediction Error: {results['avg_prediction_error']:.4f}")
        logger.info(f"Prediction-Performance Correlation: {results['prediction_correlation']:.4f}")
    
    # Create plots
    plt.figure(figsize=(15, 12))
    
    # Plot portfolio value
    plt.subplot(4, 1, 1)
    plt.plot(portfolio_values)
    plt.title('Portfolio Value During Evaluation')
    plt.ylabel('Portfolio Value ($)')
    
    # Plot price data
    plt.subplot(4, 1, 2)
    plt.plot(price_data)
    plt.title('Price Data')
    plt.ylabel('Price')
    
    # Plot actions taken
    plt.subplot(4, 1, 3)
    action_labels = {0: 'Hold', 1: 'Buy', 2: 'Sell'}
    action_values = [action_labels[a] for a in actions_taken]
    action_colors = ['yellow' if a == 0 else 'green' if a == 1 else 'red' for a in actions_taken]
    
    # Plot actions as colored regions
    for i, action in enumerate(actions_taken):
        if action != 0:  # Skip hold actions for clarity
            plt.axvline(x=i, color=action_colors[i], alpha=0.5)
    
    plt.title('Agent Actions')
    plt.ylabel('Action')
    
    # Plot prediction confidence
    plt.subplot(4, 1, 4)
    plt.plot(confidence_history)
    plt.title('Prediction Confidence')
    plt.ylabel('Confidence')
    plt.xlabel('Time Step')
    
    plt.tight_layout()
    
    # Save plot
    plt.savefig(f"models/prediction_guided_eval_{timestamp}.png")
    
    return results, env 