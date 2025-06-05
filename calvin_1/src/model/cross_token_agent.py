#!/usr/bin/env python
"""
Cross-Token Generalization Actor-Critic Agent

This module implements a reinforcement learning agent that can learn
trading strategies that generalize across multiple tokens.
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
from src.model.fast_rl_agent import FastTradingEnvironment
from src.model.prediction_guided_agent import PredictionGuidedEnvironment

# Set up logger
logger = log_manager.get_logger("cross_token_agent")

# Disable TensorFlow logging for cleaner output
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
tf.get_logger().setLevel('ERROR')

class MultiTokenEnvironment:
    """
    Environment that manages multiple token environments to enable
    cross-token generalization in RL training.
    """
    
    def __init__(self, env_configs, use_predictions=True):
        """
        Initialize multiple trading environments for different tokens.
        
        Args:
            env_configs: List of dictionaries, each containing the configuration
                         for a single token environment with keys:
                         - token_symbol: Symbol of the token
                         - token_address: Address of the token
                         - price_data: Price history
                         - feature_data: Feature data
                         - price_predictor: ML price prediction model (optional)
                         - feature_scaler: Feature normalizer
                         - price_scaler: Price normalizer
                         - initial_balance: Starting capital
                         - other environment params...
            use_predictions: Whether to use prediction-guided environments
        """
        self.env_configs = env_configs
        self.use_predictions = use_predictions
        self.environments = {}
        self.current_token = None
        self.token_list = []
        self.token_embedding_size = 16  # Increased size for more detailed embeddings
        
        # Token metadata storage
        self.token_metadata = {}
        self.token_addresses = {}
        self.market_data = None
        
        # Create environments for each token
        for config in env_configs:
            token_symbol = config.get('token_symbol', 'UNKNOWN')
            token_address = config.get('token_address', None)
            self.token_list.append(token_symbol)
            self.token_addresses[token_symbol] = token_address
            
            # Create appropriate environment type based on configuration
            if use_predictions and 'price_predictor' in config:
                self.environments[token_symbol] = PredictionGuidedEnvironment(
                    price_data=config['price_data'],
                    feature_data=config['feature_data'],
                    price_predictor=config['price_predictor'],
                    feature_scaler=config.get('feature_scaler'),
                    price_scaler=config.get('price_scaler'),
                    initial_balance=config.get('initial_balance', 10000.0),
                    transaction_fee=config.get('transaction_fee', 0.001),
                    risk_free_rate=config.get('risk_free_rate', 0.0),
                    sharpe_lookback=config.get('sharpe_lookback', 30),
                    sharpe_weight=config.get('sharpe_weight', 2.0),
                    position_sizing=config.get('position_sizing', 'fixed'),
                    max_position_pct=config.get('max_position_pct', 0.5),
                    resolution=config.get('resolution', '5m'),
                    reward_type=config.get('reward_type', 'combined'),
                    slippage_pct=config.get('slippage_pct', 0.0015),
                    prediction_horizon=config.get('prediction_horizon', 5),
                    sequence_length=config.get('sequence_length', 10),
                    load_predictions_from=config.get('load_predictions_from'),
                    save_predictions_to=config.get('save_predictions_to')
                )
            else:
                self.environments[token_symbol] = FastTradingEnvironment(
                    price_data=config['price_data'],
                    feature_data=config['feature_data'],
                    initial_balance=config.get('initial_balance', 10000.0),
                    transaction_fee=config.get('transaction_fee', 0.001),
                    risk_free_rate=config.get('risk_free_rate', 0.0),
                    sharpe_lookback=config.get('sharpe_lookback', 30),
                    sharpe_weight=config.get('sharpe_weight', 2.0),
                    position_sizing=config.get('position_sizing', 'fixed'),
                    max_position_pct=config.get('max_position_pct', 0.5),
                    resolution=config.get('resolution', '5m'),
                    reward_type=config.get('reward_type', 'combined'),
                    slippage_pct=config.get('slippage_pct', 0.0015)
                )
            
            # Store raw price data for embedding calculations
            self.token_metadata[token_symbol] = {
                'raw_price_data': config['price_data'],
                'resolution': config.get('resolution', '5m'),
                'current_step': 0
            }
        
        # Set the first token as current by default
        if self.token_list:
            self.current_token = self.token_list[0]
            self.set_active_token(self.current_token)
            
        # Determine the state size from the first environment
        sample_env = list(self.environments.values())[0]
        sample_state = sample_env.reset()
        self.base_state_size = len(sample_state)
        
        # Fetch token metadata and create initial embeddings
        self._fetch_token_metadata()
        self.token_embeddings = {}
        self._create_token_embeddings()
            
        logger.info(f"Initialized multi-token environment with {len(self.environments)} tokens")
    
    def _fetch_token_metadata(self):
        """
        Fetch metadata for all tokens from external sources and store it.
        This includes stable properties like token age, category, etc.
        """
        try:
            from src.data.birdeye_api import BirdEyeAPI
            
            birdeye = BirdEyeAPI()
            market_data = {'average_volume': 0, 'average_volatility': 0}
            total_volume = 0
            
            # Fetch metadata for each token
            for token_symbol, token_address in self.token_addresses.items():
                if not token_address:
                    logger.warning(f"No address for {token_symbol}, using defaults for metadata")
                    self.token_metadata[token_symbol].update({
                        'category': 'unknown',
                        'age_days': 365,  # Default 1 year
                        'has_website': False,
                        'max_supply': 0,
                        'social_score': 0,
                        'stable': False
                    })
                    continue
                    
                # Get token metadata from BirdEye
                try:
                    metadata = birdeye.get_token_metadata(token_address)
                    if 'data' in metadata:
                        token_data = metadata['data']
                        
                        # Extract data from API response
                        extensions = token_data.get('extensions', {})
                        creation_date = token_data.get('createdAt', None)
                        has_website = bool(extensions.get('website', ''))
                        
                        # Calculate age in days
                        if creation_date:
                            from datetime import datetime
                            created = datetime.fromisoformat(creation_date.replace('Z', '+00:00'))
                            now = datetime.now().astimezone()
                            age_days = (now - created).days
                        else:
                            age_days = 180  # Default to 6 months if unknown
                        
                        # Get supply info
                        decimals = token_data.get('decimals', 9)
                        max_supply = token_data.get('supply', {}).get('value', 0) / (10 ** decimals)
                        
                        # Get token category - parse from tags or description
                        description = extensions.get('description', '').lower()
                        tags = token_data.get('tags', [])
                        
                        category = 'unknown'
                        if any(tag in ['defi', 'finance', 'lending', 'swap'] for tag in tags):
                            category = 'defi'
                        elif any(tag in ['game', 'gaming', 'metaverse'] for tag in tags):
                            category = 'gaming'
                        elif any(tag in ['meme', 'dog', 'pepe', 'frog'] for tag in tags) or 'meme' in description:
                            category = 'meme'
                        elif any(tag in ['stable', 'stablecoin'] for tag in tags) or 'stable' in description:
                            category = 'stable'
                        
                        # Determine if token is a stablecoin
                        is_stable = category == 'stable' or any(s in token_symbol.lower() for s in ['usd', 'usdc', 'usdt', 'dai'])
                        
                        # Get social score
                        social_score = 0
                        if extensions.get('twitter'):
                            social_score += 20
                        if extensions.get('discord') or extensions.get('telegram'):
                            social_score += 20
                        if has_website:
                            social_score += 20
                        if extensions.get('medium') or extensions.get('blog'):
                            social_score += 10
                        if len(extensions.get('description', '')) > 100:
                            social_score += 10
                        if token_data.get('verified', False):
                            social_score += 20
                            
                        # Store metadata
                        self.token_metadata[token_symbol].update({
                            'category': category,
                            'age_days': age_days,
                            'has_website': has_website,
                            'max_supply': max_supply,
                            'social_score': social_score,
                            'stable': is_stable,
                            'verified': token_data.get('verified', False)
                        })
                        
                        # Get price and market data
                        try:
                            price_data = birdeye.get_token_price(token_address)
                            if 'data' in price_data and 'value' in price_data['data']:
                                price = float(price_data['data']['value'])
                                self.token_metadata[token_symbol]['current_price'] = price
                                
                                # Get market cap if available
                                if max_supply > 0:
                                    market_cap = price * max_supply
                                    self.token_metadata[token_symbol]['market_cap'] = market_cap
                        except:
                            logger.warning(f"Failed to get price data for {token_symbol}")
                            
                        # Get trading volume data
                        try:
                            ohlcv = birdeye.get_token_ohlcv(token_address, "1d", 5)
                            if not ohlcv.empty:
                                avg_volume = ohlcv['volume'].mean()
                                total_volume += avg_volume
                                self.token_metadata[token_symbol]['volume'] = avg_volume
                                
                                # Calculate volatility from OHLC
                                if len(ohlcv) > 1:
                                    daily_returns = ohlcv['close'].pct_change().dropna()
                                    volatility = daily_returns.std()
                                    self.token_metadata[token_symbol]['volatility'] = volatility
                                    
                                    # Add to market average
                                    market_data['average_volatility'] += volatility
                        except:
                            logger.warning(f"Failed to get OHLCV data for {token_symbol}")
                    
                except Exception as e:
                    logger.warning(f"Error fetching metadata for {token_symbol}: {e}")
                    # Set default values
                    self.token_metadata[token_symbol].update({
                        'category': 'unknown',
                        'age_days': 180,  # Default 6 months
                        'has_website': False,
                        'max_supply': 0,
                        'social_score': 0,
                        'stable': False
                    })
            
            # Calculate market averages
            num_tokens = len(self.token_addresses)
            if num_tokens > 0:
                market_data['average_volume'] = total_volume / num_tokens
                market_data['average_volatility'] /= num_tokens
                
            self.market_data = market_data
            
        except ImportError:
            logger.warning("BirdEye API not available, using default token metadata")
            # Set default values for all tokens if API not available
            for token in self.token_list:
                self.token_metadata[token].update({
                    'category': 'unknown',
                    'age_days': 180,
                    'has_website': False,
                    'max_supply': 0,
                    'social_score': 0,
                    'stable': False
                })
        except Exception as e:
            logger.error(f"Error fetching token metadata: {e}")
    
    def _create_token_embeddings(self):
        """
        Create token embeddings combining stable and dynamic properties.
        """
        for token in self.token_list:
            # Get token metadata
            metadata = self.token_metadata[token]
            
            # Calculate stable properties (normalized to 0-1 range)
            
            # 1. Category one-hot encoding
            category_vector = np.zeros(4)  # defi, gaming, meme, stable
            categories = {'defi': 0, 'gaming': 1, 'meme': 2, 'stable': 3}
            if metadata.get('category') in categories:
                category_vector[categories[metadata.get('category')]] = 1.0
            
            # 2. Age (normalized, 0 = new, 1 = old)
            age_normalized = min(metadata.get('age_days', 180) / 1095, 1.0)  # Cap at 3 years
            
            # 3. Social score (0-100 normalized to 0-1)
            social_score = metadata.get('social_score', 0) / 100
            
            # 4. Has website
            has_website = 1.0 if metadata.get('has_website', False) else 0.0
            
            # 5. Is verified
            is_verified = 1.0 if metadata.get('verified', False) else 0.0
            
            # 6. Is stablecoin
            is_stable = 1.0 if metadata.get('stable', False) else 0.0
            
            # Calculate dynamic properties based on price data
            price_data = metadata['raw_price_data']
            
            # 7. Recent price trend (normalized)
            if len(price_data) > 20:
                recent_trend = (price_data[-1] / price_data[-20]) - 1.0
                trend_normalized = np.clip(recent_trend / 0.5 + 0.5, 0, 1)  # Map [-0.5, 0.5] to [0, 1]
            else:
                trend_normalized = 0.5  # Neutral if not enough data
            
            # 8. Volatility (if computed from API, or calculate from price data)
            if 'volatility' in metadata:
                volatility = metadata['volatility']
            else:
                if len(price_data) > 20:
                    returns = np.diff(price_data[-20:]) / price_data[-21:-1]
                    volatility = np.std(returns)
                else:
                    volatility = 0.05  # Default moderate volatility
            
            # Normalize volatility (typical range is 0.01-0.2 for daily)
            volatility_normalized = np.clip(volatility / 0.2, 0, 1) 
            
            # 9. Volume relative to market
            if 'volume' in metadata and self.market_data and self.market_data['average_volume'] > 0:
                volume_ratio = metadata['volume'] / self.market_data['average_volume']
                volume_normalized = np.clip(volume_ratio, 0, 5) / 5  # Cap at 5x market average
            else:
                volume_normalized = 0.5  # Default to average
            
            # 10. Calculated market cap percentile (if available)
            if 'market_cap' in metadata:
                # Bucketing into categories (micro, small, mid, large cap)
                market_cap = metadata['market_cap']
                if market_cap < 1e6:  # < $1M
                    market_cap_normalized = 0.0
                elif market_cap < 1e7:  # $1M-$10M
                    market_cap_normalized = 0.25
                elif market_cap < 1e8:  # $10M-$100M
                    market_cap_normalized = 0.5
                elif market_cap < 1e9:  # $100M-$1B
                    market_cap_normalized = 0.75
                else:  # > $1B
                    market_cap_normalized = 1.0
            else:
                market_cap_normalized = 0.5  # Default to mid-cap
            
            # Combine all properties into a single embedding vector
            embedding = np.concatenate([
                # Stable properties (6 dimensions)
                category_vector,       # 4 dimensions (one-hot category)
                [age_normalized],      # 1 dimension (normalized age)
                [social_score],        # 1 dimension (social presence)
                [has_website],         # 1 dimension (has website)
                [is_verified],         # 1 dimension (is verified)
                [is_stable],           # 1 dimension (is stablecoin)
                
                # Dynamic properties (4 dimensions)
                [trend_normalized],    # 1 dimension (recent price trend)
                [volatility_normalized], # 1 dimension (price volatility)
                [volume_normalized],   # 1 dimension (volume vs market)
                [market_cap_normalized]  # 1 dimension (market cap category)
            ])
            
            # Ensure consistent size
            if len(embedding) < self.token_embedding_size:
                padding = np.zeros(self.token_embedding_size - len(embedding))
                embedding = np.concatenate([embedding, padding])
            elif len(embedding) > self.token_embedding_size:
                embedding = embedding[:self.token_embedding_size]
                
            self.token_embeddings[token] = embedding
            
            logger.info(f"Created embedding for {token} with stable and dynamic properties")
    
    def update_dynamic_embeddings(self, token, current_step):
        """
        Update the dynamic part of token embeddings based on recent data
        
        Args:
            token: Symbol of the token to update
            current_step: Current step in the environment
        """
        if token not in self.token_metadata:
            return
            
        metadata = self.token_metadata[token]
        metadata['current_step'] = current_step
        
        # Get recent price data
        price_data = metadata['raw_price_data']
        
        if len(price_data) <= current_step or current_step < 20:
            return  # Not enough data
            
        # Calculate recent trend
        recent_data = price_data[max(0, current_step-20):current_step+1]
        if len(recent_data) > 1:
            recent_trend = (recent_data[-1] / recent_data[0]) - 1.0
            trend_normalized = np.clip(recent_trend / 0.5 + 0.5, 0, 1)
            
            # Calculate recent volatility
            returns = np.diff(recent_data) / recent_data[:-1]
            volatility = np.std(returns)
            volatility_normalized = np.clip(volatility / 0.2, 0, 1)
            
            # Update only the dynamic parts of the embedding (last 4 dimensions)
            embedding = self.token_embeddings[token].copy()
            embedding[-4] = trend_normalized
            embedding[-3] = volatility_normalized
            
            self.token_embeddings[token] = embedding
    
    def set_active_token(self, token_symbol):
        """Switch the active token environment"""
        if token_symbol in self.environments:
            self.current_token = token_symbol
            return True
        return False
    
    def get_random_token(self):
        """Select a random token"""
        return random.choice(self.token_list)
    
    def generate_token_embedding(self, token_symbol):
        """Get the embedding vector for a token"""
        return self.token_embeddings.get(token_symbol, 
                                         np.zeros(self.token_embedding_size))
    
    def reset(self, token_symbol=None):
        """
        Reset environment for specified token or current token
        
        Args:
            token_symbol: Symbol of token to reset, or None for current token
        
        Returns:
            Combined state with token embedding
        """
        if token_symbol is not None and self.set_active_token(token_symbol):
            pass  # Active token is set
        elif self.current_token is None and self.token_list:
            self.current_token = self.token_list[0]
        
        # Reset the active environment
        base_state = self.environments[self.current_token].reset()
        
        # Reset the current step counter for dynamic embeddings
        self.token_metadata[self.current_token]['current_step'] = 0
        
        # Get token embedding
        token_embedding = self.generate_token_embedding(self.current_token)
        
        # Combine base state with token embedding
        combined_state = np.concatenate([base_state, token_embedding])
        
        return combined_state
    
    def step(self, action):
        """
        Take action in current token environment
        
        Args:
            action: Action to take in the environment
            
        Returns:
            Tuple of (augmented_state, reward, done, info)
        """
        if self.current_token is None:
            raise ValueError("No active token selected")
            
        # Take action in the current environment
        next_state, reward, done, info = self.environments[self.current_token].step(action)
        
        # Add token information to info
        info['token'] = self.current_token
        
        # Update the current step for dynamic embeddings
        current_step = self.token_metadata[self.current_token]['current_step'] + 1
        self.token_metadata[self.current_token]['current_step'] = current_step
        
        # Update dynamic part of token embedding
        self.update_dynamic_embeddings(self.current_token, current_step)
        
        # Augment state with token embedding
        token_embedding = self.generate_token_embedding(self.current_token)
        augmented_state = np.concatenate([next_state, token_embedding])
        
        return augmented_state, reward, done, info
    
    def get_state_size(self):
        """Get the size of the augmented state space"""
        return self.base_state_size + self.token_embedding_size
    
    def get_action_size(self):
        """Get the size of the action space"""
        # Assuming all environments have the same action space
        return 3  # hold, buy, sell
    
    def get_token_count(self):
        """Get the number of tokens in the environment"""
        return len(self.token_list) 

class CrossTokenActorCritic:
    """
    Actor-Critic agent designed to learn trading strategies that
    generalize across multiple tokens.
    """
    
    def __init__(self, state_size, action_size, memory_size=50000,
                 actor_learning_rate=0.0001, critic_learning_rate=0.001,
                 gamma=0.99, tau=0.001, batch_size=64):
        """
        Initialize Actor-Critic agent for cross-token generalization
        
        Args:
            state_size: Dimensionality of state (including token embedding)
            action_size: Number of possible actions
            memory_size: Size of replay buffer
            actor_learning_rate: Learning rate for actor network
            critic_learning_rate: Learning rate for critic network
            gamma: Discount factor for future rewards
            tau: Target network soft update factor
            batch_size: Training batch size
        """
        self.state_size = state_size
        self.action_size = action_size
        self.gamma = gamma  # Discount factor
        self.tau = tau  # Target network update rate
        self.batch_size = batch_size
        
        # Experience replay buffer with token identifier
        self.memory = deque(maxlen=memory_size)
        
        # Create TF2 optimizers
        self.actor_optimizer = tf.keras.optimizers.Adam(learning_rate=actor_learning_rate)
        self.critic_optimizer = tf.keras.optimizers.Adam(learning_rate=critic_learning_rate)
        
        # Create actor networks (policy function)
        self.actor = self._build_actor_network()
        self.target_actor = self._build_actor_network()
        self.target_actor.set_weights(self.actor.get_weights())
        
        # Create critic networks (value function)
        self.critic = self._build_critic_network()
        self.target_critic = self._build_critic_network()
        self.target_critic.set_weights(self.critic.get_weights())
        
        # Track tokens seen during training
        self.tokens_seen = set()
        
        logger.info(f"Initialized Cross-Token Actor-Critic agent with state size {state_size}")
    
    def _build_actor_network(self):
        """Build the actor network (policy)"""
        model = tf.keras.Sequential([
            tf.keras.layers.Input(shape=(self.state_size,)),
            tf.keras.layers.Dense(128, activation='relu'),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.Dense(64, activation='relu'),
            tf.keras.layers.Dense(self.action_size, activation='softmax')
        ])
        
        model.compile(optimizer='adam')
        return model
    
    def _build_critic_network(self):
        """Build the critic network (value function)"""
        state_input = tf.keras.layers.Input(shape=(self.state_size,))
        action_input = tf.keras.layers.Input(shape=(self.action_size,))
        
        # Process state path
        state_out = tf.keras.layers.Dense(128, activation='relu')(state_input)
        state_out = tf.keras.layers.BatchNormalization()(state_out)
        state_out = tf.keras.layers.Dense(64, activation='relu')(state_out)
        
        # Combine state and action
        concat = tf.keras.layers.Concatenate()([state_out, action_input])
        
        # Output layers
        out = tf.keras.layers.Dense(64, activation='relu')(concat)
        out = tf.keras.layers.Dense(1)(out)
        
        model = tf.keras.Model([state_input, action_input], out)
        model.compile(optimizer='adam', loss='mse')
        
        return model
    
    def remember(self, state, action, reward, next_state, done, token):
        """Store experience in replay memory with token identifier"""
        # Track which tokens we've seen
        self.tokens_seen.add(token)
        
        # Convert action to one-hot vector for critic training
        action_onehot = np.zeros(self.action_size)
        action_onehot[action] = 1
        
        # Store the experience tuple with token identifier
        self.memory.append((state, action_onehot, reward, next_state, done, token))
    
    def act(self, state, training=True, temperature=1.0):
        """
        Select an action based on the current state
        
        Args:
            state: Current state with token embedding
            training: Whether we're in training mode
            temperature: Exploration factor (higher = more exploration)
            
        Returns:
            Selected action index
        """
        # Get action probabilities from actor network
        action_probs = self.actor.predict(np.expand_dims(state, axis=0), verbose=0)[0]
        
        if training:
            # Apply temperature scaling for exploration
            action_probs = np.power(action_probs, 1/temperature)
            action_probs /= action_probs.sum()  # Renormalize
            
            # Sample from probability distribution
            action = np.random.choice(self.action_size, p=action_probs)
        else:
            # In evaluation mode, take the most probable action
            action = np.argmax(action_probs)
            
        return action
    
    def train(self):
        """Train the actor and critic networks on a batch of experiences"""
        if len(self.memory) < self.batch_size:
            return
            
        # Sample random batch of experiences
        indices = np.random.choice(len(self.memory), self.batch_size, replace=False)
        batch = [self.memory[i] for i in indices]
        
        # Unpack batch
        states = np.array([exp[0] for exp in batch])
        actions = np.array([exp[1] for exp in batch])
        rewards = np.array([exp[2] for exp in batch])
        next_states = np.array([exp[3] for exp in batch])
        dones = np.array([exp[4] for exp in batch])
        tokens = [exp[5] for exp in batch]
        
        # Get target Q values using target networks
        next_actions = self.target_actor.predict(next_states, verbose=0)
        q_future = self.target_critic.predict([next_states, next_actions], verbose=0).flatten()
        
        # Calculate target values with temporal difference
        target_q = rewards + self.gamma * q_future * (1 - dones)
        
        # Train critic
        with tf.GradientTape() as tape:
            q_values = self.critic([states, actions], training=True)
            critic_loss = tf.reduce_mean(tf.square(target_q - q_values))
            
        critic_grads = tape.gradient(critic_loss, self.critic.trainable_variables)
        self.critic_optimizer.apply_gradients(zip(critic_grads, self.critic.trainable_variables))
        
        # Train actor
        with tf.GradientTape() as tape:
            actions_pred = self.actor(states, training=True)
            actor_loss = -tf.reduce_mean(self.critic([states, actions_pred]))
            
        actor_grads = tape.gradient(actor_loss, self.actor.trainable_variables)
        self.actor_optimizer.apply_gradients(zip(actor_grads, self.actor.trainable_variables))
        
        # Soft update target networks
        self._update_target(self.actor, self.target_actor)
        self._update_target(self.critic, self.target_critic)
        
        return critic_loss.numpy(), actor_loss.numpy()
    
    def _update_target(self, source_model, target_model):
        """Soft update the target network weights"""
        for target_weight, source_weight in zip(target_model.weights, source_model.weights):
            target_weight.assign(
                self.tau * source_weight + (1 - self.tau) * target_weight
            )
    
    def save(self, actor_path, critic_path):
        """Save actor and critic models"""
        self.actor.save(actor_path)
        self.critic.save(critic_path)
        logger.info(f"Saved models to {actor_path} and {critic_path}")
    
    def load(self, actor_path, critic_path):
        """Load actor and critic models"""
        self.actor = tf.keras.models.load_model(actor_path)
        self.critic = tf.keras.models.load_model(critic_path)
        
        # Update target networks
        self.target_actor.set_weights(self.actor.get_weights())
        self.target_critic.set_weights(self.critic.get_weights())
        
        logger.info(f"Loaded models from {actor_path} and {critic_path}") 

def train_cross_token_agent(
    multi_env,
    episodes=200,
    max_steps_per_episode=10000,
    actor_lr=0.0001,
    critic_lr=0.001,
    gamma=0.99,
    tau=0.001,
    batch_size=64,
    memory_size=50000,
    token_scheduling="random",
    evaluation_interval=10,
    save_path="models/cross_token",
    temperature_start=5.0,
    temperature_end=0.1,
    temperature_decay=0.999,
):
    """
    Train an Actor-Critic agent to generalize across multiple tokens
    
    Args:
        multi_env: MultiTokenEnvironment instance
        episodes: Number of episodes to train
        max_steps_per_episode: Maximum steps per episode
        actor_lr: Learning rate for actor network
        critic_lr: Learning rate for critic network
        gamma: Discount factor for future rewards
        tau: Target network soft update rate
        batch_size: Training batch size
        memory_size: Size of replay buffer
        token_scheduling: How to schedule tokens ("random", "sequential", "curriculum")
        evaluation_interval: How often to run evaluation episodes
        save_path: Where to save model checkpoints
        temperature_start: Initial exploration temperature
        temperature_end: Final exploration temperature
        temperature_decay: Temperature decay rate
        
    Returns:
        Trained agent and performance metrics
    """
    start_time = time.time()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Create directories for model checkpoints
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    # Configure and initialize environment/agent
    state_size = multi_env.get_state_size()
    action_size = multi_env.get_action_size()
    token_count = multi_env.get_token_count()
    
    # Initialize agent
    agent = CrossTokenActorCritic(
        state_size=state_size,
        action_size=action_size,
        memory_size=memory_size,
        actor_learning_rate=actor_lr,
        critic_learning_rate=critic_lr,
        gamma=gamma,
        tau=tau,
        batch_size=batch_size
    )
    
    # Metrics tracking
    rewards_history = []
    actor_losses = []
    critic_losses = []
    portfolio_values = []
    episode_lengths = []
    best_reward = float('-inf')
    token_performances = {token: [] for token in multi_env.token_list}
    
    # Dictionary to track how many episodes per token
    token_episodes = {token: 0 for token in multi_env.token_list}
    
    # Progress tracking
    episode_bar = tqdm(total=episodes, desc="Training episodes", position=0)
    
    # Training loop
    current_temperature = temperature_start
    
    for episode in range(episodes):
        # Select token for this episode
        if token_scheduling == "random":
            token = multi_env.get_random_token()
        elif token_scheduling == "sequential":
            token_idx = episode % token_count
            token = multi_env.token_list[token_idx]
        elif token_scheduling == "curriculum":
            # TODO: Implement curriculum learning (start with easier tokens)
            token = multi_env.get_random_token()
        else:
            token = multi_env.get_random_token()
            
        # Track episodes per token
        token_episodes[token] += 1
        
        # Reset environment for this token
        state = multi_env.reset(token)
        episode_reward = 0
        done = False
        step_count = 0
        
        # Step progress tracking
        step_bar = tqdm(total=max_steps_per_episode, desc=f"Episode {episode+1} ({token})", 
                        position=1, leave=False)
        
        # Episode loop
        while not done and step_count < max_steps_per_episode:
            # Select action with current temperature for exploration
            action = agent.act(state, training=True, temperature=current_temperature)
            
            # Take action in environment
            next_state, reward, done, info = multi_env.step(action)
            
            # Store experience with token identifier
            agent.remember(state, action, reward, next_state, done, token)
            
            # Train agent
            if len(agent.memory) >= batch_size:
                c_loss, a_loss = agent.train()
                actor_losses.append(a_loss)
                critic_losses.append(c_loss)
            
            # Update state and accumulate reward
            state = next_state
            episode_reward += reward
            step_count += 1
            
            # Update progress bar every 10 steps for efficiency
            if step_count % 10 == 0:
                step_bar.update(10)
                step_bar.set_postfix({
                    'reward': f"{episode_reward:.1f}",
                    'portfolio': f"${info.get('portfolio_value', 0):.0f}",
                    'temp': f"{current_temperature:.2f}"
                })
                
        # Complete the step bar
        step_bar.update(max_steps_per_episode - step_bar.n)
        step_bar.close()
        
        # Record metrics
        rewards_history.append(episode_reward)
        episode_lengths.append(step_count)
        
        # Get final portfolio value
        final_portfolio = info.get('portfolio_value', 0)
        portfolio_values.append(final_portfolio)
        
        # Track performance by token
        token_performances[token].append((episode_reward, final_portfolio))
        
        # Update exploration temperature
        current_temperature = max(
            temperature_end, 
            current_temperature * temperature_decay
        )
        
        # Update progress display
        episode_bar.update(1)
        episode_bar.set_postfix({
            'reward': f"{episode_reward:.1f}",
            'portfolio': f"${final_portfolio:.0f}",
            'tokens': f"{len(agent.tokens_seen)}/{token_count}"
        })
        
        # Log episode results
        logger.info(f"Episode {episode+1}/{episodes} ({token}) - "
                   f"Reward: {episode_reward:.2f}, "
                   f"Portfolio: ${final_portfolio:.2f}, "
                   f"Steps: {step_count}")
        
        # Save if best performance
        if episode_reward > best_reward and episode > 10:
            best_reward = episode_reward
            agent.save(f"{save_path}_best_actor", f"{save_path}_best_critic")
            
        # Regular checkpoint saving
        if (episode + 1) % 20 == 0:
            agent.save(f"{save_path}_ep{episode+1}_actor", f"{save_path}_ep{episode+1}_critic")
            
        # Evaluate on each token periodically
        if (episode + 1) % evaluation_interval == 0:
            evaluate_all_tokens(agent, multi_env)
            
        # Force garbage collection periodically
        if (episode + 1) % 10 == 0:
            gc.collect()
    
    # Close progress bar
    episode_bar.close()
    
    # Final model save
    final_save_path = f"{save_path}_{timestamp}"
    agent.save(f"{final_save_path}_actor", f"{final_save_path}_critic")
    
    # Create performance visualization
    create_training_plots(
        save_path=f"{save_path}_{timestamp}_training.png",
        rewards_history=rewards_history,
        portfolio_values=portfolio_values,
        actor_losses=actor_losses,
        critic_losses=critic_losses,
        token_performances=token_performances,
        token_episodes=token_episodes
    )
    
    # Calculate training statistics
    training_stats = {
        'total_episodes': episodes,
        'tokens_trained': len(agent.tokens_seen),
        'average_reward': np.mean(rewards_history[-20:]),
        'final_temperature': current_temperature,
        'best_reward': best_reward,
        'training_time': time.time() - start_time,
        'token_episodes': token_episodes
    }
    
    logger.info(f"Training completed in {training_stats['training_time']:.1f} seconds")
    logger.info(f"Final average reward: {training_stats['average_reward']:.2f}")
    logger.info(f"Trained on {training_stats['tokens_trained']} tokens")
    
    return agent, training_stats

def evaluate_all_tokens(agent, multi_env, episodes_per_token=3):
    """
    Evaluate agent performance on all tokens
    
    Args:
        agent: Trained CrossTokenActorCritic agent
        multi_env: MultiTokenEnvironment instance
        episodes_per_token: Number of evaluation episodes per token
    
    Returns:
        Dictionary of token performance metrics
    """
    logger.info("Running evaluation across all tokens...")
    
    results = {}
    
    for token in multi_env.token_list:
        token_rewards = []
        token_portfolios = []
        
        for _ in range(episodes_per_token):
            # Reset environment for this token
            state = multi_env.reset(token)
            episode_reward = 0
            done = False
            
            # Run episode
            while not done:
                action = agent.act(state, training=False)
                next_state, reward, done, info = multi_env.step(action)
                episode_reward += reward
                state = next_state
                
            # Record metrics
            token_rewards.append(episode_reward)
            token_portfolios.append(info.get('portfolio_value', 0))
            
        # Calculate average metrics
        avg_reward = np.mean(token_rewards)
        avg_portfolio = np.mean(token_portfolios)
        
        # Store results
        results[token] = {
            'avg_reward': avg_reward,
            'avg_portfolio': avg_portfolio
        }
        
        logger.info(f"Token {token} evaluation: "
                   f"Avg Reward: {avg_reward:.2f}, "
                   f"Avg Portfolio: ${avg_portfolio:.2f}")
    
    return results

def create_training_plots(save_path, rewards_history, portfolio_values, 
                         actor_losses, critic_losses, token_performances,
                         token_episodes):
    """Create and save plots showing training performance"""
    plt.figure(figsize=(15, 12))
    
    # Plot episode rewards
    plt.subplot(3, 2, 1)
    plt.plot(rewards_history)
    plt.title('Episode Rewards')
    plt.ylabel('Total Reward')
    
    # Plot portfolio values
    plt.subplot(3, 2, 2)
    plt.plot(portfolio_values)
    plt.title('Final Portfolio Values')
    plt.ylabel('Portfolio Value ($)')
    
    # Plot actor and critic losses
    plt.subplot(3, 2, 3)
    plt.plot(actor_losses, label='Actor')
    plt.plot(critic_losses, label='Critic')
    plt.title('Network Losses')
    plt.xlabel('Training Step')
    plt.ylabel('Loss')
    plt.legend()
    
    # Plot token episode distribution
    plt.subplot(3, 2, 4)
    tokens = list(token_episodes.keys())
    episodes = list(token_episodes.values())
    plt.bar(tokens, episodes)
    plt.title('Episodes Per Token')
    plt.ylabel('Number of Episodes')
    plt.xticks(rotation=45)
    
    # Plot token performance comparison
    plt.subplot(3, 2, 5)
    for token, performances in token_performances.items():
        if performances:
            rewards = [p[0] for p in performances]
            plt.plot(rewards, label=token)
    plt.title('Reward by Token')
    plt.xlabel('Episode')
    plt.ylabel('Reward')
    plt.legend()
    
    # Plot token portfolio comparison
    plt.subplot(3, 2, 6)
    for token, performances in token_performances.items():
        if performances:
            portfolios = [p[1] for p in performances]
            plt.plot(portfolios, label=token)
    plt.title('Portfolio Value by Token')
    plt.xlabel('Episode')
    plt.ylabel('Portfolio Value ($)')
    plt.legend()
    
    plt.tight_layout()
    plt.savefig(save_path)
    logger.info(f"Saved training plots to {save_path}")
    
if __name__ == "__main__":
    # Example usage will go here
    pass 