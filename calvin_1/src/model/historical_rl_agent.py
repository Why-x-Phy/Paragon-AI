#!/usr/bin/env python
"""
Historical Reinforcement Learning agent for trading - using all previous history
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
from tqdm import tqdm
import gc

from src.utils.logger import log_manager

logger = log_manager.get_logger("historical_rl_agent")

class HistoricalTradingEnvironment:
    """Environment for RL agent with access to all historical data up to current point"""
    
    def __init__(self, price_data, feature_data, initial_balance=10000.0, transaction_fee=0.001, lookback_limit=60):
        """
        Initialize trading environment with complete history access
        
        Args:
            price_data: Array of historical prices
            feature_data: Array of features for state representation
            initial_balance: Starting cash balance
            transaction_fee: Fee as percentage of trade value
            lookback_limit: Maximum number of historical states to consider (to prevent memory issues)
        """
        # Convert inputs to numpy arrays if they aren't already
        self.prices = np.asarray(price_data, dtype=np.float32)
        
        # Pre-normalize features for faster processing - use float32 for memory efficiency
        self.feature_mean = np.mean(feature_data, axis=0).astype(np.float32)
        self.feature_std = np.std(feature_data, axis=0).astype(np.float32) + 1e-8
        self.normalized_features = ((feature_data - self.feature_mean) / self.feature_std).astype(np.float32)
        
        self.initial_balance = initial_balance
        self.transaction_fee = transaction_fee
        self.lookback_limit = lookback_limit
        
        # Add tracking for trading behavior
        self.last_action_step = 0
        self.action_count = 0
        self.last_action_type = 0
        self.cooling_off_period = 1
        self.in_cooling_off = False
        self.cooling_off_remaining = 0
        
        # Use more efficient storage for trades
        self.max_trades = 1000
        
        self.reset()
        
    def reset(self):
        """Reset environment to initial state"""
        self.current_step = 0
        self.balance = self.initial_balance
        self.position = 0  # 0 = no position, 1 = long
        self.shares_held = 0
        self.position_price = 0
        
        # Reset trade tracking variables
        self.last_action_step = 0
        self.action_count = 0
        self.last_action_type = 0
        self.in_cooling_off = False
        self.cooling_off_remaining = 0
        
        # Initialize portfolio values array with correct dimensions
        self.portfolio_values = np.zeros(len(self.prices))
        
        # CRITICAL: Set initial portfolio value to initial_balance
        self.portfolio_values[0] = self.initial_balance
        
        # Safety check - fill initial values
        for i in range(1, min(10, len(self.portfolio_values))):
            self.portfolio_values[i] = self.initial_balance
        
        self.trades = []
        
        # Ensure we have enough prices to work with
        if len(self.prices) < 2:
            logger.error(f"Not enough price data: {len(self.prices)} data points")
            raise ValueError("Insufficient price data for RL trading")
        
        # Initialize history sequence
        self.state_history = []
        
        return self._get_observation()
        
    def step(self, action):
        """
        Take action in environment with access to complete history
        
        Args:
            action: 0 = hold, 1 = buy, 2 = sell
            
        Returns:
            Tuple of (observation, reward, done, info)
        """
        # Get current price
        current_price = self.prices[self.current_step]
        reward = 0
        profit = 0  # Initialize profit
        
        # Update cooling off period if active
        if self.in_cooling_off:
            self.cooling_off_remaining -= 1
            if self.cooling_off_remaining <= 0:
                self.in_cooling_off = False
        
        # Track pre-action portfolio for reward calculation
        pre_action_portfolio = self.balance
        if self.position == 1 and self.shares_held > 0:
            pre_action_portfolio += self.shares_held * current_price
        
        # Force HOLD if in cooling-off period
        original_action = action
        if self.in_cooling_off and action != 0:
            action = 0
        
        # Execute trade based on action
        if action == 1 and self.position == 0 and self.balance > 0:  # Buy
            # Use 95% of cash maximum
            max_shares = (self.balance * 0.95) / (current_price * (1 + self.transaction_fee))
            
            # Limit position size - 20% of initial balance max
            max_position_size = self.initial_balance * 0.2 / (current_price * (1 + self.transaction_fee))
            shares = min(max_shares, max_position_size)
            
            # Calculate cost with fees
            cost = shares * current_price * (1 + self.transaction_fee)
            
            # Ensure we don't overspend
            if cost > self.balance:
                shares = self.balance / (current_price * (1 + self.transaction_fee)) * 0.99
                cost = shares * current_price * (1 + self.transaction_fee)
            
            # Don't allow tiny positions
            if shares * current_price < 1.0 or shares < 0.001:
                shares = 0
                cost = 0
            
            self.balance -= cost
            self.position = 1 if shares > 0 else 0
            self.position_price = current_price
            self.shares_held = shares
            
            if shares > 0:
                self.trades.append({
                    "step": self.current_step,
                    "type": "buy",
                    "price": current_price,
                    "shares": shares,
                    "cost": cost,
                })
                # Track this action
                self.action_count += 1
                self.last_action_type = 1
                self.last_action_step = self.current_step
                
                # Start cooling-off period
                self.in_cooling_off = True
                self.cooling_off_remaining = self.cooling_off_period
            
        elif action == 2 and self.position == 1 and self.shares_held > 0:  # Sell
            revenue = self.shares_held * current_price * (1 - self.transaction_fee)
            profit = revenue - (self.shares_held * self.position_price)
            
            self.balance += revenue
            self.position = 0
            self.shares_held = 0
            
            self.trades.append({
                "step": self.current_step,
                "type": "sell",
                "price": current_price,
                "profit": profit,
            })
            
            # Track this action
            self.action_count += 1
            self.last_action_type = 2
            self.last_action_step = self.current_step
            
            # Start cooling-off period
            self.in_cooling_off = True
            self.cooling_off_remaining = self.cooling_off_period
        
        # Calculate portfolio value - ALWAYS include cash
        portfolio_value = self.balance
        if self.position == 1 and self.shares_held > 0:
            position_value = self.shares_held * current_price
            portfolio_value += position_value
        
        # Store portfolio value for tracking
        self.portfolio_values[self.current_step] = portfolio_value
        
        # Calculate reward based on portfolio value change
        if self.current_step > 0:
            pct_change = portfolio_value / self.portfolio_values[self.current_step - 1] - 1.0
            # Clip to avoid extreme values
            pct_change = max(min(pct_change, 0.5), -0.5)
            # Scale for meaningful reward
            reward = pct_change * 10.0
            
            # Extra reward for profitable sells
            if action == 2 and profit > 0:
                # Add safety check for division by zero
                if self.shares_held > 0 and self.position_price > 0:
                    profit_pct = profit / (self.shares_held * self.position_price)
                    reward += profit_pct * 5.0
                else:
                    # Fallback if we can't calculate percentage
                    reward += 0.5
            
            # Penalty for selling at a loss
            elif action == 2 and profit < 0:
                reward -= 0.2
                
            # Encourage holding in uptrends
            if action == 0 and pct_change > 0:
                reward += 0.1
            
            # Mild portfolio-based bonuses and penalties
            if portfolio_value > self.initial_balance * 1.5:  # 50% or more profit
                reward += 2.0
            
            # Penalties for severe losses only
            if portfolio_value < self.initial_balance * 0.75:  # 25% or more loss
                reward -= 1.0
                
            if portfolio_value < self.initial_balance * 0.5:  # 50% or more loss
                reward -= 2.0
                
        else:
            reward = 0.0
        
        # Clamp reward to prevent extreme values
        reward = max(min(reward, 40.0), -15.0)
        
        # Move to next step
        self.current_step += 1
        done = self.current_step >= len(self.prices) - 1
        
        info = {
            'portfolio_value': portfolio_value,
            'position': self.position,
            'balance': self.balance,
            'shares_held': self.shares_held,
            'in_cooling_off': self.in_cooling_off,
            'cooling_off_remaining': self.cooling_off_remaining
        }
        
        # Get next observation
        next_observation = self._get_observation()
            
        return next_observation, reward, done, info
    
    def _get_observation(self):
        """
        Create observation that includes current state and 
        access to all available history up to the current point
        """
        # Get normalized features for current step
        current_features = self.normalized_features[self.current_step]
        
        # Create current observation with position state and cooling-off status
        current_obs = np.append(current_features, [self.position, int(self.in_cooling_off)])
        
        # Add current observation to state history
        self.state_history.append(current_obs)
        
        # Limit the history to lookback_limit states to avoid memory issues
        if len(self.state_history) > self.lookback_limit:
            self.state_history = self.state_history[-self.lookback_limit:]
        
        # Return the most recent state for non-historical methods
        return current_obs
    
    def get_history(self):
        """Get the current history of states as a numpy array"""
        return np.array(self.state_history)
    
    def get_history_length(self):
        """Get the current length of state history"""
        return len(self.state_history)


class HistoricalDQNAgent:
    """Deep Q-Network agent that utilizes full historical context"""
    
    def __init__(self, state_size, action_size, model_dir="models", history_limit=30):
        """
        Initialize LSTM-based DQN agent that processes historical data
        
        Args:
            state_size: Dimension of each state element
            action_size: Dimension of action space
            model_dir: Directory to save models
            history_limit: Maximum number of historical states to process
        """
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=10000)
        self.gamma = 0.95    # discount rate
        self.epsilon = 1.0   # exploration rate
        self.epsilon_min = 0.05
        self.epsilon_decay = 0.99
        self.learning_rate = 0.001
        self.model_dir = model_dir
        self.history_limit = history_limit
        self.tf_config = tf.compat.v1.ConfigProto()
        self.tf_config.gpu_options.allow_growth = True  # Prevent TF from grabbing all memory
        tf.compat.v1.keras.backend.set_session(tf.compat.v1.Session(config=self.tf_config))
        
        # Reduce memory usage
        self.prediction_batch_size = 16
        
        os.makedirs(model_dir, exist_ok=True)
        
        # Build model
        self.model = self._build_historical_lstm_model()
        self.target_model = self._build_historical_lstm_model()
        self.update_target_model()
        
    def _build_historical_lstm_model(self):
        """Build LSTM network that can handle variable-length historical data"""
        # Input shape is (None, state_size) for variable sequence length
        input_layer = tf.keras.layers.Input(shape=(None, self.state_size))
        
        # Use smaller LSTM units for faster processing
        lstm1 = tf.keras.layers.LSTM(64, return_sequences=True)(input_layer)
        dropout1 = tf.keras.layers.Dropout(0.2)(lstm1)
        
        # Use GRU for second layer (faster than LSTM)
        gru_layer = tf.keras.layers.GRU(32, return_sequences=False)(dropout1)
        dropout2 = tf.keras.layers.Dropout(0.2)(gru_layer)
        
        # Smaller dense layer
        dense1 = tf.keras.layers.Dense(32, activation='relu')(dropout2)
        
        # Output layer
        output = tf.keras.layers.Dense(self.action_size, activation='linear')(dense1)
        
        model = tf.keras.Model(inputs=input_layer, outputs=output)
        
        # Use legacy optimizer for compatibility
        try:
            optimizer = tf.keras.optimizers.legacy.Adam(learning_rate=self.learning_rate)
        except:
            optimizer = tf.keras.optimizers.Adam(learning_rate=self.learning_rate)
            
        model.compile(
            loss='mse', 
            optimizer=optimizer,
            metrics=None
        )
        return model
    
    def update_target_model(self):
        """Update target model with weights from main model"""
        self.target_model.set_weights(self.model.get_weights())
    
    def remember(self, state_history, action, reward, next_state_history, done):
        """Store experience with historical context in replay memory"""
        # Store experience as tuple of (state_history, action, reward, next_state_history, done)
        self.memory.append((state_history, action, reward, next_state_history, done))
    
    def act(self, state_history, training=True):
        """Choose action based on epsilon-greedy policy using historical context"""
        if training and np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        
        # Ensure state_history has batch dimension and time dimension
        if len(state_history.shape) == 2:  # (time_steps, features)
            state_history = np.expand_dims(state_history, axis=0)  # (1, time_steps, features)
            
        act_values = self.model.predict(state_history, verbose=0)
        return np.argmax(act_values[0])
    
    def replay(self, batch_size):
        """Train model with experiences from replay memory using historical context - optimized for speed"""
        if len(self.memory) < batch_size:
            return
            
        # Sample random batch from memory
        minibatch = random.sample(self.memory, batch_size)
        
        # Process states and next_states in batches
        # First, organize the state histories
        state_histories = []
        actions = []
        rewards = []
        next_state_histories = []
        dones = []
        
        # Extract data
        for state_history, action, reward, next_state_history, done in minibatch:
            # Handle state history shape
            if len(state_history.shape) == 2:  # (time_steps, features)
                state_history = np.expand_dims(state_history, axis=0)  # (1, time_steps, features)
            
            # Handle next state history shape
            if len(next_state_history.shape) == 2:  # (time_steps, features)
                next_state_history = np.expand_dims(next_state_history, axis=0)  # (1, time_steps, features)
                
            state_histories.append(state_history)
            actions.append(action)
            rewards.append(reward)
            next_state_histories.append(next_state_history)
            dones.append(done)
        
        # Process batches of states in a loop to avoid memory issues
        # Process 5 samples at a time for better memory management
        batch_size = 5
        for i in range(0, len(state_histories), batch_size):
            # Process a small batch
            batch_end = min(i + batch_size, len(state_histories))
            batch_range = range(i, batch_end)
            
            # Get batch data
            batch_states = [state_histories[j] for j in batch_range]
            batch_actions = [actions[j] for j in batch_range]
            batch_rewards = [rewards[j] for j in batch_range]
            batch_next_states = [next_state_histories[j] for j in batch_range]
            batch_dones = [dones[j] for j in batch_range]
            
            # Create targets for this batch
            for j in range(len(batch_states)):
                if batch_dones[j]:
                    target = batch_rewards[j]
                else:
                    # Get next Q-values
                    next_q_values = self.target_model.predict(batch_next_states[j], verbose=0)[0]
                    target = batch_rewards[j] + self.gamma * np.amax(next_q_values)
                
                # Get current Q values
                current_q = self.model.predict(batch_states[j], verbose=0)[0]
                
                # Update the Q value for the action
                current_q[batch_actions[j]] = target
                
                # Train model on this sample
                self.model.fit(batch_states[j], np.expand_dims(current_q, axis=0), epochs=1, verbose=0)
        
        # Decay epsilon
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
            # Ensure we don't go below minimum
            self.epsilon = max(self.epsilon_min, self.epsilon)
    
    def save(self, name=None):
        """Save model to disk"""
        if name is None:
            name = f"historical_dqn_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        model_path = os.path.join(self.model_dir, f"{name}.h5")
        self.model.save(model_path)
        logger.info(f"Model saved to {model_path}")
        return model_path
    
    def load(self, path):
        """Load model from disk"""
        self.model = tf.keras.models.load_model(path)
        self.target_model = tf.keras.models.load_model(path)
        logger.info(f"Model loaded from {path}")


def train_historical_rl_agent(
    price_data, 
    feature_data, 
    episodes=100, 
    batch_size=64,
    initial_balance=10000.0,
    model_name=None,
    history_limit=30,
    train_every=2,  # Only train every N steps for speed
    memory_efficient=True  # Use more memory-efficient operations
):
    """
    Train RL agent with historical context on price data
    
    Args:
        price_data: Array of historical prices
        feature_data: Array of features for state representation
        episodes: Number of training episodes
        batch_size: Batch size for training
        initial_balance: Starting cash balance
        model_name: Name for saved model
        history_limit: Maximum number of historical states to process
        train_every: How often to train the model (every N steps)
        memory_efficient: Use more memory-efficient operations
        
    Returns:
        Trained agent and final environment state
    """
    logger.info(f"Starting historical RL training for {episodes} episodes with history limit {history_limit}")
    print(f"\n{'='*80}\nStarting Historical RL training with {len(price_data)} data points\n{'='*80}")
    
    # Optimize data types for memory efficiency
    if memory_efficient:
        price_data = np.asarray(price_data, dtype=np.float32)
        feature_data = np.asarray(feature_data, dtype=np.float32)
        
    # Prepare environment
    env = HistoricalTradingEnvironment(
        price_data, 
        feature_data, 
        initial_balance=initial_balance,
        lookback_limit=history_limit
    )
    
    # Get state size (features + position + cooling-off)
    state_size = feature_data.shape[1] + 2
    action_size = 3  # hold, buy, sell
    
    # Initialize agent
    agent = HistoricalDQNAgent(
        state_size=state_size, 
        action_size=action_size, 
        history_limit=history_limit
    )
    
    # Track performance
    rewards_history = []
    portfolio_history = []
    best_portfolio_value = initial_balance
    best_agent = None
    
    # Create primary progress bar for episodes with forced tty for WSL compatibility
    episode_bar = tqdm(
        range(episodes), 
        desc="Training Episodes", 
        position=0, 
        leave=True,
        ncols=100,
        bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
    )
    
    # Maximum time allowed per episode (in seconds)
    max_episode_time = 2400  # 40 minutes (increased from 5 minutes)
    
    # Average steps per episode based on environment
    avg_steps_per_episode = min(len(price_data), 500)  # Reduced for speed
    
    # Garbage collect before training
    if memory_efficient:
        gc.collect()
    
    # Training loop
    for episode in episode_bar:
        # Track episode start time
        episode_start_time = time.time()
        
        # Reset environment
        env.reset()
        
        # Get initial state history (just the first state at this point)
        state_history = env.get_history()
        
        # Track rewards
        total_reward = 0
        done = False
        step_count = 0
        
        # Create a progress bar for steps within this episode
        step_bar = tqdm(
            total=avg_steps_per_episode,
            desc=f"Episode {episode+1} Steps",
            position=1,
            leave=False,
            ncols=100,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]'
        )
        
        # Episode loop
        while not done:
            # Check for timeout
            if time.time() - episode_start_time > max_episode_time:
                logger.warning(f"Episode {episode+1} timed out after {time.time() - episode_start_time:.1f} seconds. Breaking out.")
                break
            
            # Choose action using historical context
            action = agent.act(state_history, training=True)
            
            # Take action in environment
            next_state, reward, done, info = env.step(action)
            
            # Get updated state history
            next_state_history = env.get_history()
            
            # Store experience
            agent.remember(state_history, action, reward, next_state_history, done)
            
            # Update state
            state_history = next_state_history
            
            # Accumulate reward
            total_reward += reward
            step_count += 1
            
            # Update step progress bar
            step_bar.update(1)
            step_bar.set_postfix({
                'Reward': f'{reward:.2f}',
                'Portfolio': f'${info["portfolio_value"]:.2f}',
                'Action': ['HOLD', 'BUY', 'SELL'][action]
            })
            
            # Train agent less frequently for speed
            if len(agent.memory) > batch_size and step_count % train_every == 0:
                agent.replay(min(batch_size, len(agent.memory)))
                
                # Run garbage collection if memory efficiency is enabled
                if memory_efficient and step_count % (train_every * 5) == 0:
                    gc.collect()
            
            # Extra timeout check
            if time.time() - episode_start_time > max_episode_time:
                logger.warning(f"Episode {episode+1} processing timeout during steps. Breaking loop.")
                break
                
            # End episode early for training purposes if we've reached a good number of steps
            if step_count >= avg_steps_per_episode:
                logger.info(f"Ending episode early after {step_count} steps to optimize training time")
                break
        
        # Close step progress bar
        step_bar.close()
        
        # Update target network every episode for faster learning
        agent.update_target_model()
        
        # Record performance
        # Ensure we have a valid final portfolio value calculation, even if the episode timed out
        if env.current_step < len(env.prices):
            # Calculate final portfolio value properly
            current_price = env.prices[env.current_step-1] if env.current_step > 0 else env.prices[0]
            cash_balance = env.balance
            position_value = 0
            if env.position == 1 and env.shares_held > 0:
                position_value = env.shares_held * current_price
            
            # Set the final portfolio value explicitly
            final_portfolio = cash_balance + position_value
            # Update the portfolio values array at the current step
            if env.current_step < len(env.portfolio_values):
                env.portfolio_values[env.current_step] = final_portfolio
        else:
            final_portfolio = env.portfolio_values[min(step_count, len(env.portfolio_values)-1)]
        
        # Ensure final_portfolio is not zero (fallback to initial balance if we somehow got zero)
        if final_portfolio == 0:
            logger.warning(f"Final portfolio value was zero! Using last valid portfolio value instead.")
            # Find last non-zero portfolio value
            for i in range(min(step_count, len(env.portfolio_values)-1), -1, -1):
                if env.portfolio_values[i] > 0:
                    final_portfolio = env.portfolio_values[i]
                    break
            # If still zero, use initial balance
            if final_portfolio == 0:
                final_portfolio = env.initial_balance
                logger.warning(f"No valid portfolio value found, using initial balance: ${final_portfolio:.2f}")
        
        # Add bonus for profitability
        if final_portfolio > initial_balance:
            profit_pct = (final_portfolio / initial_balance) - 1.0
            episode_bonus = profit_pct * 100.0
            total_reward += episode_bonus
            logger.info(f"Added episode bonus: +{episode_bonus:.2f} for {profit_pct:.2%} profit")
        
        rewards_history.append(total_reward)
        portfolio_history.append(final_portfolio)
        
        # Save best model
        if final_portfolio > best_portfolio_value:
            best_portfolio_value = final_portfolio
            best_agent = agent
            if model_name:
                agent.save(f"{model_name}_best")
        
        # Update progress bar
        episode_bar.set_postfix({
            'Reward': f'{total_reward:.2f}', 
            'Portfolio': f'${final_portfolio:.2f}',
            'ROI': f'{(final_portfolio/initial_balance - 1.0)*100:.1f}%',
            'Epsilon': f'{agent.epsilon:.4f}'
        })
        
        # Calculate trading statistics
        total_buys = len([t for t in env.trades if t['type'] == 'buy'])
        total_sells = len([t for t in env.trades if t['type'] == 'sell'])
        
        if total_sells > 0:
            profitable_trades = len([t for t in env.trades if t['type'] == 'sell' and t.get('profit', 0) > 0])
            win_rate = profitable_trades / total_sells
        else:
            win_rate = 0
            
        # Log episode results
        logger.info(f"Episode {episode+1}/{episodes} completed after {step_count} steps. "
                    f"Reward: {total_reward:.2f}, Final Portfolio: ${final_portfolio:.2f}, "
                    f"Trades: {total_buys} buys, {total_sells} sells, Win Rate: {win_rate:.2%}")
    
    # Plot training results
    plt.figure(figsize=(12, 8))
    
    plt.subplot(2, 1, 1)
    plt.plot(rewards_history)
    plt.title('Total Reward per Episode')
    plt.xlabel('Episode')
    plt.ylabel('Total Reward')
    plt.grid(True)
    
    plt.subplot(2, 1, 2)
    plt.plot(portfolio_history)
    plt.axhline(y=initial_balance, color='r', linestyle='--', alpha=0.3)
    plt.title('Final Portfolio Value per Episode')
    plt.xlabel('Episode')
    plt.ylabel('Portfolio Value ($)')
    plt.grid(True)
    
    plt.tight_layout()
    plt.savefig(os.path.join(agent.model_dir, "historical_training_results.png"))
    
    # Return best agent if found, otherwise current agent
    if best_agent is not None:
        final_agent = best_agent
    else:
        final_agent = agent
        
    # Save final model
    if model_name:
        final_agent.save(model_name)
    else:
        final_agent.save()
    
    logger.info(f"Historical RL training completed. Best portfolio: ${best_portfolio_value:.2f}")
    return final_agent, env


def evaluate_historical_agent(agent, price_data, feature_data, initial_balance=10000.0, max_eval_time=1200):
    """
    Evaluate trained historical agent on test data
    
    Args:
        agent: Trained Historical DQN agent
        price_data: Array of test prices
        feature_data: Array of test features
        initial_balance: Starting cash balance
        max_eval_time: Maximum evaluation time in seconds (10 minutes)
        
    Returns:
        Dictionary with evaluation results
    """
    logger.info(f"Evaluating historical agent on {len(price_data)} data points with {max_eval_time}s timeout")
    
    # Track start time for timeout
    eval_start_time = time.time()
    
    # Run backtest with agent
    env = HistoricalTradingEnvironment(price_data, feature_data, initial_balance)
    env.reset()
    done = False
    
    # Get initial state history
    state_history = env.get_history()
    
    # Track steps
    steps = 0
    max_steps = len(price_data) * 2  # Safety cap
    
    while not done:
        # Check timeout
        if time.time() - eval_start_time > max_eval_time:
            logger.warning(f"Evaluation timed out after {max_eval_time} seconds. Stopping at step {steps}.")
            break
            
        # Check step limit
        if steps >= max_steps:
            logger.warning(f"Evaluation reached maximum steps limit ({max_steps}). Stopping to prevent infinite loop.")
            break
        
        # Choose action using historical context
        action = agent.act(state_history, training=False)
        
        # Take action
        next_state, reward, done, info = env.step(action)
        
        # Update state history
        state_history = env.get_history()
        
        steps += 1
        
        # Log progress periodically
        if steps % 1000 == 0:
            cash = env.balance
            position_value = 0
            if env.position == 1 and env.shares_held > 0:
                position_value = env.shares_held * price_data[min(env.current_step-1, len(price_data)-1)]
            logger.info(f"Step {steps}: Cash=${cash:.2f}, Position=${position_value:.2f}, Total=${cash+position_value:.2f}")
            
            # Additional timeout check
            time_elapsed = time.time() - eval_start_time
            logger.info(f"Evaluation time: {time_elapsed:.1f}s / {max_eval_time}s")
    
    # Log evaluation time
    eval_time = time.time() - eval_start_time
    logger.info(f"Evaluation completed in {eval_time:.2f} seconds after {steps} steps")
    
    # Calculate final portfolio value
    cash_balance = env.balance
    position_value = 0
    if env.position == 1 and env.shares_held > 0:
        # Make sure we get the last valid price
        if env.current_step > 0 and env.current_step < len(price_data):
            last_price = price_data[env.current_step-1]
        else:
            last_price = price_data[-1] if len(price_data) > 0 else 0
        position_value = env.shares_held * last_price
    
    # Total portfolio value
    final_value = cash_balance + position_value
    
    # Sanity check - if final value is zero or unreasonable, investigate and log
    if final_value <= 0 or final_value < initial_balance * 0.1 or final_value > initial_balance * 10:
        logger.warning(f"Potentially invalid final portfolio value: ${final_value:.2f}")
        logger.info(f"Cash: ${cash_balance:.2f}, Position value: ${position_value:.2f}")
        logger.info(f"Current step: {env.current_step}, Shares held: {env.shares_held}")
        
        # Use last valid portfolio value as backup
        backup_value = initial_balance
        for i in range(min(steps, len(env.portfolio_values)-1), -1, -1):
            if env.portfolio_values[i] > 0:
                backup_value = env.portfolio_values[i]
                logger.info(f"Using backup portfolio value from step {i}: ${backup_value:.2f}")
                break
                
        # Only use backup if final_value is invalid
        if final_value <= 0:
            final_value = backup_value
            logger.warning(f"Corrected final value to: ${final_value:.2f}")
    
    # Calculate performance metrics
    roi = (final_value - env.initial_balance) / env.initial_balance
    
    # Calculate buy and hold return
    buy_hold_return = (price_data[-1] - price_data[0]) / price_data[0] if len(price_data) > 1 else 0
    
    # Calculate trade statistics
    total_trades = len([t for t in env.trades if t['type'] == 'sell'])
    if total_trades > 0:
        profitable_trades = len([t for t in env.trades if t['type'] == 'sell' and t.get('profit', 0) > 0])
        win_rate = profitable_trades / total_trades
    else:
        win_rate = 0
    
    logger.info(f"Final evaluation: Cash=${cash_balance:.2f}, Position=${position_value:.2f}, Total=${final_value:.2f}")
    logger.info(f"Evaluation results: ROI: {roi:.2%}, Buy & Hold: {buy_hold_return:.2%}, " +
              f"Win Rate: {win_rate:.2%}, Trades: {total_trades}")
    
    # Plot portfolio value over time
    try:
        plt.figure(figsize=(10, 6))
        plt.plot(env.portfolio_values)
        plt.title('Portfolio Value During Evaluation')
        plt.xlabel('Step')
        plt.ylabel('Portfolio Value ($)')
        plt.grid(True)
        plt.savefig(os.path.join(agent.model_dir, "historical_evaluation_portfolio.png"))
    except Exception as e:
        logger.error(f"Error generating evaluation plot: {e}")
    
    return {
        'final_value': final_value,
        'roi': roi,
        'buy_hold_return': buy_hold_return,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'portfolio_history': env.portfolio_values,
        'trades': env.trades,
        'cash_balance': cash_balance,
        'position_value': position_value,
        'steps_completed': steps,
        'evaluation_time': eval_time
    } 