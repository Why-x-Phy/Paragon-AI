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

from src.utils.logger import log_manager

logger = log_manager.get_logger("rl_agent")

class TradingEnvironment:
    """Environment for RL agent to interact with market data"""
    
    def __init__(self, price_data, feature_data, initial_balance=10000.0, transaction_fee=0.001):
        """
        Initialize trading environment
        
        Args:
            price_data: Array of historical prices
            feature_data: Array of features for state representation
            initial_balance: Starting cash balance
            transaction_fee: Fee as percentage of trade value
        """
        self.prices = price_data
        self.features = feature_data
        self.initial_balance = initial_balance
        self.transaction_fee = transaction_fee
        self.reset()
        
    def reset(self):
        """Reset environment to initial state"""
        self.current_step = 0
        self.balance = self.initial_balance
        self.position = 0  # 0 = no position, 1 = long
        self.shares_held = 0
        self.entry_price = 0
        self.portfolio_value_history = [self.initial_balance]
        self.trades = []
        return self._get_observation()
        
    def step(self, action):
        """
        Take action in environment and return new state, reward, and done flag
        
        Args:
            action: 0 = hold, 1 = buy, 2 = sell
            
        Returns:
            Tuple of (observation, reward, done, info)
        """
        # Get current price
        current_price = self.prices[self.current_step]
        reward = 0
        
        # Execute trade based on action
        if action == 1 and self.position == 0 and self.balance > 0:  # Buy
            shares = self.balance * 0.95 / current_price
            cost = shares * current_price * (1 + self.transaction_fee)
            self.balance -= cost
            self.position = 1
            self.entry_price = current_price
            self.shares_held = shares
            self.trades.append({
                "step": self.current_step,
                "type": "buy",
                "price": current_price,
                "shares": shares,
                "cost": cost
            })
            
        elif action == 2 and self.position == 1 and self.shares_held > 0:  # Sell
            revenue = self.shares_held * current_price * (1 - self.transaction_fee)
            profit = revenue - (self.shares_held * self.entry_price)
            reward = profit / (self.shares_held * self.entry_price)  # Percentage profit as reward
            self.balance += revenue
            self.position = 0
            self.shares_held = 0
            self.trades.append({
                "step": self.current_step,
                "type": "sell",
                "price": current_price,
                "shares": self.shares_held,
                "revenue": revenue,
                "profit": profit
            })
        
        # Move to next step
        self.current_step += 1
        done = self.current_step >= len(self.prices) - 1
        
        # Calculate portfolio value
        portfolio_value = self.balance
        if self.position == 1:
            portfolio_value += self.shares_held * self.prices[min(self.current_step, len(self.prices)-1)]
        self.portfolio_value_history.append(portfolio_value)
        
        # If no explicit reward from selling, use change in portfolio value
        if reward == 0:
            # Small reward/penalty for holding position based on price movement
            reward = (portfolio_value / self.portfolio_value_history[-2] - 1) * 10
            
        info = {
            'portfolio_value': portfolio_value,
            'position': self.position,
            'balance': self.balance
        }
            
        return self._get_observation(), reward, done, info
    
    def _get_observation(self):
        """Create observation vector from current state"""
        # Ensure we don't go out of bounds
        idx = min(self.current_step, len(self.features)-1)
        
        # Create observation vector: features + position state
        obs = np.concatenate([self.features[idx], [self.position]])
        return obs

class DQNAgent:
    """Deep Q-Network (DQN) agent for trading"""
    
    def __init__(self, state_size, action_size, model_dir='models'):
        """
        Initialize DQN agent
        
        Args:
            state_size: Dimension of state space
            action_size: Dimension of action space
            model_dir: Directory to save models
        """
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=2000)
        self.gamma = 0.95  # discount rate
        self.epsilon = 1.0  # exploration rate
        self.epsilon_min = 0.01
        self.epsilon_decay = 0.995
        self.learning_rate = 0.001
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)
        
        self.model = self._build_model()
        self.target_model = self._build_model()
        self.update_target_model()
        
    def _build_model(self):
        """Build neural network model for Q-function approximation"""
        model = tf.keras.Sequential([
            tf.keras.layers.Dense(64, input_dim=self.state_size, activation='relu'),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.Dense(64, activation='relu'),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.Dense(self.action_size, activation='linear')
        ])
        model.compile(loss='mse', optimizer=tf.keras.optimizers.Adam(learning_rate=self.learning_rate))
        return model
        
    def update_target_model(self):
        """Update target model with weights from main model"""
        self.target_model.set_weights(self.model.get_weights())
        
    def remember(self, state, action, reward, next_state, done):
        """Store experience in replay memory"""
        self.memory.append((state, action, reward, next_state, done))
        
    def act(self, state, training=True):
        """Choose action based on epsilon-greedy policy"""
        if training and np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        
        state = np.array(state).reshape(1, -1)
        act_values = self.model.predict(state, verbose=0)
        return np.argmax(act_values[0])
    
    def replay(self, batch_size):
        """Train model with experiences from replay memory"""
        if len(self.memory) < batch_size:
            return
            
        # Sample random batch from memory
        minibatch = random.sample(self.memory, batch_size)
        
        # Generate training data
        states = np.zeros((batch_size, self.state_size))
        targets = np.zeros((batch_size, self.action_size))
        
        for i, (state, action, reward, next_state, done) in enumerate(minibatch):
            state = np.array(state).reshape(1, -1)
            next_state = np.array(next_state).reshape(1, -1)
            
            # Get current Q values
            target = self.model.predict(state, verbose=0)[0]
            
            if done:
                target[action] = reward
            else:
                # Use target network to estimate next Q value
                t = self.target_model.predict(next_state, verbose=0)[0]
                target[action] = reward + self.gamma * np.amax(t)
                
            states[i] = state
            targets[i] = target
        
        # Train model
        self.model.fit(states, targets, epochs=1, verbose=0, batch_size=batch_size)
        
        # Decay epsilon
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
    
    def save(self, name=None):
        """Save model to disk"""
        if name is None:
            name = f"dqn_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        model_path = os.path.join(self.model_dir, f"{name}.h5")
        self.model.save(model_path)
        
        # Save training parameters
        params = {
            'epsilon': self.epsilon,
            'gamma': self.gamma,
            'learning_rate': self.learning_rate
        }
        
        params_path = os.path.join(self.model_dir, f"{name}_params.json")
        with open(params_path, 'w') as f:
            import json
            json.dump(params, f)
            
        logger.info(f"Model saved to {model_path}")
        return model_path
    
    def load(self, path):
        """Load model from disk"""
        self.model = tf.keras.models.load_model(path)
        self.target_model = tf.keras.models.load_model(path)
        
        # Try to load params
        params_path = path.replace('.h5', '_params.json')
        if os.path.exists(params_path):
            with open(params_path, 'r') as f:
                import json
                params = json.load(f)
                self.epsilon = params.get('epsilon', self.epsilon)
                self.gamma = params.get('gamma', self.gamma)
                
        logger.info(f"Model loaded from {path}")

def train_rl_agent(
    price_data, 
    feature_data, 
    episodes=100, 
    batch_size=64, 
    initial_balance=10000.0,
    model_name=None
):
    """
    Train RL agent on historical price data
    
    Args:
        price_data: Array of historical prices
        feature_data: Array of features for state representation
        episodes: Number of training episodes
        batch_size: Batch size for training
        initial_balance: Starting cash balance
        model_name: Name for saved model
        
    Returns:
        Trained agent and final environment state
    """
    logger.info(f"Starting RL training for {episodes} episodes with batch size {batch_size}")
    
    # Prepare environment
    env = TradingEnvironment(price_data, feature_data, initial_balance)
    state_size = feature_data.shape[1] + 1  # features + position state
    action_size = 3  # hold, buy, sell
    agent = DQNAgent(state_size, action_size)
    
    # Track performance
    rewards_history = []
    portfolio_history = []
    
    # Create primary progress bar for episodes
    episode_bar = tqdm(range(episodes), desc="Training Episodes", position=0)
    
    # Training loop with progress bar
    for episode in episode_bar:
        state = env.reset()
        total_reward = 0
        done = False
        steps = 0
        
        # Create a second progress bar for steps within an episode
        # We don't know exact steps, but we can estimate based on data length
        step_bar = tqdm(total=min(1000, len(price_data)), 
                        desc=f"Episode {episode+1} Steps", 
                        position=1, 
                        leave=False)
        
        # Episode loop
        while not done:
            action = agent.act(state)
            next_state, reward, done, info = env.step(action)
            agent.remember(state, action, reward, next_state, done)
            state = next_state
            total_reward += reward
            steps += 1
            
            # Update step progress
            step_bar.update(1)
            if steps % 100 == 0:
                step_bar.set_description(f"Episode {episode+1} Steps (Reward: {total_reward:.2f})")
            
            # Train on batch of experiences
            agent.replay(batch_size)
            
        # Close step progress bar
        step_bar.close()
        
        # Update target network more frequently
        if episode % 3 == 0:
            agent.update_target_model()
            
        # Record performance
        rewards_history.append(total_reward)
        portfolio_history.append(env.portfolio_value_history[-1])
        
        # Update episode progress bar with useful information
        episode_bar.set_description(f"Training Episodes (Reward: {total_reward:.2f}, Portfolio: ${env.portfolio_value_history[-1]:.2f})")
        
        # Log progress more frequently (every 5 episodes)
        if episode % 5 == 0 or episode == episodes - 1:
            logger.info(f"Episode: {episode+1}/{episodes}, Steps: {steps}, Total Reward: {total_reward:.2f}, " +
                      f"Final Value: ${env.portfolio_value_history[-1]:.2f}, " +
                      f"Epsilon: {agent.epsilon:.4f}")
    
    # Close episode progress bar
    episode_bar.close()
    
    # Save trained model
    if model_name is None:
        model_name = f"rl_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    agent.save(model_name)
    
    # Visualize training progress
    plt.figure(figsize=(12, 6))
    plt.subplot(1, 2, 1)
    plt.plot(rewards_history)
    plt.title('Rewards per Episode')
    plt.xlabel('Episode')
    plt.ylabel('Total Reward')
    
    plt.subplot(1, 2, 2)
    plt.plot(portfolio_history)
    plt.title('Portfolio Value per Episode')
    plt.xlabel('Episode')
    plt.ylabel('Portfolio Value ($)')
    
    plt.tight_layout()
    plt.savefig(os.path.join(agent.model_dir, f"{model_name}_training.png"))
    
    return agent, env

def evaluate_agent(agent, price_data, feature_data, initial_balance=10000.0):
    """
    Evaluate trained agent on test data
    
    Args:
        agent: Trained DQN agent
        price_data: Array of test prices
        feature_data: Array of test features
        initial_balance: Starting cash balance
        
    Returns:
        Dictionary with evaluation results
    """
    logger.info(f"Evaluating agent on {len(price_data)} data points")
    
    # Run backtest with agent
    env = TradingEnvironment(price_data, feature_data, initial_balance)
    state = env.reset()
    done = False
    
    while not done:
        action = agent.act(state, training=False)
        state, reward, done, info = env.step(action)
    
    # Calculate performance metrics
    final_value = env.portfolio_value_history[-1]
    roi = (final_value - env.initial_balance) / env.initial_balance
    
    # Calculate buy and hold return
    buy_hold_return = (price_data[-1] - price_data[0]) / price_data[0]
    
    # Calculate trade statistics
    total_trades = len([t for t in env.trades if t['type'] == 'sell'])
    if total_trades > 0:
        profitable_trades = len([t for t in env.trades if t['type'] == 'sell' and t.get('profit', 0) > 0])
        win_rate = profitable_trades / total_trades
    else:
        win_rate = 0
    
    logger.info(f"Evaluation results: ROI: {roi:.2%}, Buy & Hold: {buy_hold_return:.2%}, " +
              f"Win Rate: {win_rate:.2%}, Trades: {total_trades}")
    
    # Plot portfolio value over time
    plt.figure(figsize=(10, 6))
    plt.plot(env.portfolio_value_history)
    plt.title('Portfolio Value During Evaluation')
    plt.xlabel('Step')
    plt.ylabel('Portfolio Value ($)')
    plt.grid(True)
    plt.savefig(os.path.join(agent.model_dir, "evaluation_portfolio.png"))
    
    return {
        'final_value': final_value,
        'roi': roi,
        'buy_hold_return': buy_hold_return,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'portfolio_history': env.portfolio_value_history,
        'trades': env.trades
    } 