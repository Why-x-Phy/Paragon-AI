#!/usr/bin/env python3
"""
Multi-Token ATCGAN RL Agent for trading portfolio of assets
"""

import os
import numpy as np
import pandas as pd
import random
import tensorflow as tf
from tensorflow.keras.models import Model, load_model
from tensorflow.keras.layers import Input, Dense, Flatten, Concatenate, Dropout
from tensorflow.keras.optimizers import Adam
from collections import deque
import logging
from datetime import datetime

from src.model.atcgan_rl_agent import ATCGAN
from src.model.multi_token_environment import MultiTokenTradingEnvironment

logger = logging.getLogger(__name__)

class MultiTokenATCGANAgent:
    """
    ATCGAN-based RL agent that can trade multiple tokens simultaneously
    """
    
    def __init__(self, 
                 num_tokens,
                 state_size,
                 sequence_length=40,
                 feature_dim=5,  # OHLCV features
                 memory_limit=10000,
                 gamma=0.95,
                 epsilon=1.0,
                 epsilon_min=0.05,
                 epsilon_decay=0.995,
                 learning_rate=0.001,
                 dropout_rate=0.1,
                 model_dir="models"):
        """
        Initialize the Multi-Token ATCGAN Agent
        
        Args:
            num_tokens: Number of tokens the agent can trade
            state_size: Size of the state vector for portfolio features
            sequence_length: Length of historical sequences for ATCGAN
            feature_dim: Number of features per time step
            memory_limit: Maximum size of replay memory
            gamma: Discount factor
            epsilon: Initial exploration rate
            epsilon_min: Minimum exploration rate
            epsilon_decay: Exploration rate decay factor
            learning_rate: Learning rate for optimizers
            dropout_rate: Dropout rate for regularization
            model_dir: Directory to save models
        """
        self.num_tokens = num_tokens
        self.state_size = state_size
        self.sequence_length = sequence_length
        self.feature_dim = feature_dim
        self.action_size = 3  # buy, sell, hold
        
        # RL parameters
        self.memory = deque(maxlen=memory_limit)
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.learning_rate = learning_rate
        self.dropout_rate = dropout_rate
        
        # Model storage
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)
        
        # Create token-specific feature extractors
        self.feature_extractors = {}
        for i in range(num_tokens):
            self.feature_extractors[i] = ATCGAN(
                sequence_length=sequence_length,
                feature_dim=feature_dim,
                output_dim=min(feature_dim * 2, 16),  # Compressed representation
                gen_filters=64,
                disc_filters=32,
                dropout_rate=dropout_rate,
                learning_rate=learning_rate
            )
        
        # Create main model and target model
        self.models = {}
        self.target_models = {}
        
        for i in range(num_tokens):
            self.models[i] = self._build_model(i)
            self.target_models[i] = self._build_model(i)
            # Initialize target model with same weights
            self.target_models[i].set_weights(self.models[i].get_weights())
    
    def _build_model(self, token_idx):
        """
        Build Q-Network for a specific token
        
        Args:
            token_idx: Index of the token
            
        Returns:
            Compiled Q-Network model
        """
        # Input for sequence of historical prices
        sequence_input = Input(shape=(self.sequence_length, self.feature_dim))
        
        # Input for current state (portfolio features)
        state_input = Input(shape=(self.state_size,))
        
        # Extract features using token-specific ATCGAN
        features, attention_weights = self.feature_extractors[token_idx].generator(sequence_input)
        
        # Flatten features
        flat_features = Flatten()(features)
        
        # Combine with state features
        combined = Concatenate()([flat_features, state_input])
        
        # Dense layers
        x = Dense(128, activation='relu')(combined)
        x = Dropout(self.dropout_rate)(x)
        x = Dense(64, activation='relu')(x)
        x = Dropout(self.dropout_rate)(x)
        
        # Output Q-values for each action
        q_values = Dense(self.action_size, activation='linear')(x)
        
        # Create model
        model = Model(inputs=[sequence_input, state_input], outputs=q_values)
        model.compile(
            loss='mse',
            optimizer=Adam(learning_rate=self.learning_rate)
        )
        
        return model
    
    def remember(self, token_idx, state, sequence, action, reward, next_state, next_sequence, done):
        """
        Store experience in memory
        
        Args:
            token_idx: Token index for this experience
            state: Current state
            sequence: Current price sequence
            action: Action taken
            reward: Reward received
            next_state: Next state
            next_sequence: Next price sequence
            done: Whether episode is done
        """
        self.memory.append((token_idx, state, sequence, action, reward, next_state, next_sequence, done))
    
    def act(self, token_idx, state, sequence, evaluate=False):
        """
        Choose action for given token based on epsilon-greedy policy
        
        Args:
            token_idx: Token index to choose action for
            state: Current state
            sequence: Current price sequence
            evaluate: Whether to use exploration or not (for evaluation)
            
        Returns:
            Selected action
        """
        if evaluate or np.random.rand() > self.epsilon:
            # Use model to predict best action
            q_values = self.models[token_idx].predict(
                [np.array([sequence]), np.array([state])],
                verbose=0
            )[0]
            return np.argmax(q_values)
        else:
            # Explore randomly
            return random.randrange(self.action_size)
    
    def replay(self, batch_size):
        """
        Train on batch from replay memory
        
        Args:
            batch_size: Size of batch to train on
        """
        if len(self.memory) < batch_size:
            return
        
        # Organize experiences by token
        token_experiences = {i: [] for i in range(self.num_tokens)}
        
        # Sample random batch
        minibatch = random.sample(self.memory, batch_size)
        
        # Group by token
        for experience in minibatch:
            token_idx = experience[0]
            token_experiences[token_idx].append(experience)
        
        # Train each token model with its own experiences
        for token_idx, experiences in token_experiences.items():
            if not experiences:
                continue  # Skip if no experiences for this token
                
            states = []
            sequences = []
            targets = []
            
            for token_idx, state, sequence, action, reward, next_state, next_sequence, done in experiences:
                target = self.models[token_idx].predict(
                    [np.array([sequence]), np.array([state])],
                    verbose=0
                )[0]
                
                if done:
                    target[action] = reward
                else:
                    t = self.target_models[token_idx].predict(
                        [np.array([next_sequence]), np.array([next_state])],
                        verbose=0
                    )[0]
                    target[action] = reward + self.gamma * np.amax(t)
                
                states.append(state)
                sequences.append(sequence)
                targets.append(target)
            
            # Convert to numpy arrays
            states = np.array(states)
            sequences = np.array(sequences)
            targets = np.array(targets)
            
            # Train the model
            self.models[token_idx].fit(
                [sequences, states],
                targets,
                epochs=1,
                verbose=0
            )
        
        # Decay epsilon
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
            
    def update_target_models(self):
        """Update all target models with weights from main models"""
        for token_idx in range(self.num_tokens):
            self.target_models[token_idx].set_weights(self.models[token_idx].get_weights())
    
    def pretrain_feature_extractors(self, token_sequences, targets, epochs=50, batch_size=32, verbose=0):
        """
        Pretrain ATCGAN feature extractors for all tokens
        
        Args:
            token_sequences: Dictionary of token_idx -> sequences
            targets: Dictionary of token_idx -> targets
            epochs: Number of training epochs
            batch_size: Batch size
            verbose: Verbosity level
        """
        logger.info(f"Pretraining ATCGAN feature extractors for {epochs} epochs...")
        
        for token_idx, sequences in token_sequences.items():
            logger.info(f"Pretraining feature extractor for token {token_idx}...")
            self.feature_extractors[token_idx].train(
                sequences,
                targets[token_idx],
                epochs=epochs,
                batch_size=batch_size,
                verbose=verbose
            )
        
        logger.info("Feature extractor pretraining complete")
    
    def save(self, name=None):
        """
        Save models to disk
        
        Args:
            name: Name prefix for saved models
            
        Returns:
            Dictionary of paths to saved models
        """
        if name is None:
            name = f"multi_token_atcgan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        models_paths = {}
        
        # Save Q-Networks
        for token_idx in range(self.num_tokens):
            q_path = os.path.join(self.model_dir, f"{name}_token{token_idx}_q_network.h5")
            self.models[token_idx].save(q_path)
            models_paths[f"q_network_{token_idx}"] = q_path
            
            # Save feature extractors
            gen_path = os.path.join(self.model_dir, f"{name}_token{token_idx}_generator.h5")
            self.feature_extractors[token_idx].generator.save(gen_path)
            models_paths[f"generator_{token_idx}"] = gen_path
        
        logger.info(f"Models saved with prefix: {name}")
        return models_paths
    
    def load(self, model_paths):
        """
        Load models from disk
        
        Args:
            model_paths: Dictionary of model paths
        """
        for token_idx in range(self.num_tokens):
            q_path = model_paths.get(f"q_network_{token_idx}")
            if q_path and os.path.exists(q_path):
                self.models[token_idx] = load_model(q_path)
                self.target_models[token_idx].set_weights(self.models[token_idx].get_weights())
            
            gen_path = model_paths.get(f"generator_{token_idx}")
            if gen_path and os.path.exists(gen_path):
                self.feature_extractors[token_idx].generator = load_model(gen_path)
        
        logger.info("Models loaded successfully")

# Training function for multi-token agent
def train_multi_token_agent(price_data_dict, token_symbols, initial_balance=10000,
                           sequence_length=40, lookback_window=30,
                           training_days=60, testing_days=30,
                           model_dir="models", episodes=100, batch_size=32,
                           pretrain_epochs=50, epsilon_decay=0.995, epsilon_min=0.05,
                           model_name=None, save_interval=10):
    """
    Train a multi-token ATCGAN-RL agent
    
    Args:
        price_data_dict: Dictionary of token symbol -> price data DataFrame
        token_symbols: List of token symbols
        initial_balance: Initial balance for the agent
        sequence_length: Historical sequence length for ATCGAN
        lookback_window: Lookback window for trading environment
        training_days: Number of days to use for training
        testing_days: Number of days to use for testing
        model_dir: Directory to save models
        episodes: Number of training episodes
        batch_size: Size of batches for training
        pretrain_epochs: Number of epochs for pretraining feature extractors
        epsilon_decay: Decay rate for exploration
        epsilon_min: Minimum exploration rate
        model_name: Custom name for the model
        save_interval: Interval for saving model checkpoints
        
    Returns:
        Trained agent and training history
    """
    logger.info(f"Starting multi-token ATCGAN-RL agent training for {len(token_symbols)} tokens")
    
    if model_name is None:
        model_name = f"multi_token_atcgan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Ensure all data is sorted by timestamp
    for symbol, df in price_data_dict.items():
        if 'timestamp' in df.columns:
            price_data_dict[symbol] = df.sort_values('timestamp')
    
    # Split data into training and testing sets
    train_data_dict = {}
    test_data_dict = {}
    
    for symbol, df in price_data_dict.items():
        train_data = df.iloc[:training_days].copy()
        test_data = df.iloc[training_days:training_days+testing_days].copy()
        
        train_data_dict[symbol] = train_data
        test_data_dict[symbol] = test_data
    
    # Prepare features and scale data
    train_scaled_dict = {}
    test_scaled_dict = {}
    feature_columns = ['open', 'high', 'low', 'close', 'volume']
    scalers = {}
    
    for symbol, train_data in train_data_dict.items():
        # Create scaler based on training data
        from sklearn.preprocessing import MinMaxScaler
        scaler = MinMaxScaler()
        train_scaled_dict[symbol] = pd.DataFrame(
            scaler.fit_transform(train_data[feature_columns]),
            columns=feature_columns
        )
        
        # Apply same scaling to test data
        test_data = test_data_dict[symbol]
        test_scaled_dict[symbol] = pd.DataFrame(
            scaler.transform(test_data[feature_columns]),
            columns=feature_columns
        )
        
        # Save scaler for later use
        scalers[symbol] = scaler
    
    # Prepare sequences for pretraining
    X_pretrain_dict = {}
    y_pretrain_dict = {}
    
    for symbol, train_scaled in train_scaled_dict.items():
        X_pretrain, y_pretrain = [], []
        
        for i in range(len(train_scaled) - sequence_length):
            X_pretrain.append(train_scaled.iloc[i:i+sequence_length][feature_columns].values)
            y_pretrain.append(train_scaled.iloc[i+sequence_length][['close']].values)
        
        X_pretrain_dict[symbol] = np.array(X_pretrain)
        y_pretrain_dict[symbol] = np.array(y_pretrain)
    
    # Create trading environments
    env = MultiTokenTradingEnvironment(
        price_data_dict=train_data_dict,
        initial_balance=initial_balance,
        lookback_window=lookback_window,
        transaction_fee=0.001
    )
    
    # Initialize agent
    num_tokens = len(token_symbols)
    token_to_idx = {symbol: i for i, symbol in enumerate(token_symbols)}
    state_size = env._get_state().shape[0]  # Get state size from environment
    
    agent = MultiTokenATCGANAgent(
        num_tokens=num_tokens,
        state_size=state_size,
        sequence_length=sequence_length,
        feature_dim=len(feature_columns),
        memory_limit=20000,
        gamma=0.95,
        epsilon=1.0,
        epsilon_min=epsilon_min,
        epsilon_decay=epsilon_decay,
        model_dir=model_dir
    )
    
    # Convert pretraining data to token index format
    X_pretrain_by_idx = {token_to_idx[symbol]: data for symbol, data in X_pretrain_dict.items()}
    y_pretrain_by_idx = {token_to_idx[symbol]: data for symbol, data in y_pretrain_dict.items()}
    
    # Pretrain feature extractors
    agent.pretrain_feature_extractors(X_pretrain_by_idx, y_pretrain_by_idx, epochs=pretrain_epochs, batch_size=batch_size)
    
    # Training history
    history = {
        'episode_rewards': [],
        'portfolio_values': [],
        'trades_per_token': {},
        'buy_count_per_token': {},
        'sell_count_per_token': {}
    }
    
    # Initialize trade counters for each token
    for symbol in token_symbols:
        history['trades_per_token'][symbol] = []
        history['buy_count_per_token'][symbol] = []
        history['sell_count_per_token'][symbol] = []
    
    # Training loop
    from tqdm import tqdm
    
    # Main episode loop
    episode_pbar = tqdm(range(episodes), desc="Training Episodes", ncols=100)
    
    for episode in episode_pbar:
        # Reset environment
        state = env.reset()
        
        # Initialize token-specific sequences
        token_sequences = {}
        for symbol, idx in token_to_idx.items():
            # Initialize with zeros
            token_sequences[idx] = np.zeros((sequence_length, len(feature_columns)))
            
            # Get current price data for initial sequence
            current_data = train_scaled_dict[symbol].iloc[:sequence_length]
            if len(current_data) == sequence_length:
                token_sequences[idx] = current_data[feature_columns].values
        
        # Track episode metrics
        total_reward = 0
        done = False
        token_trade_counts = {symbol: 0 for symbol in token_symbols}
        token_buy_counts = {symbol: 0 for symbol in token_symbols}
        token_sell_counts = {symbol: 0 for symbol in token_symbols}
        
        # Store portfolio values
        portfolio_values = [env.portfolio_value()]
        
        # Max steps per episode
        max_steps = min(len(next(iter(train_data_dict.values()))), 500)
        step_count = 0
        
        while not done and step_count < max_steps:
            # Take actions for each token in order
            for idx, symbol in enumerate(token_symbols):
                # Choose action for this token
                action = agent.act(
                    token_idx=token_to_idx[symbol],
                    state=state,
                    sequence=token_sequences[token_to_idx[symbol]]
                )
                
                # Execute action
                next_state, reward, done, info = env.step(token_to_idx[symbol], action)
                
                # Update sequence for this token
                if env.current_step < len(train_scaled_dict[symbol]):
                    # Shift sequence and add new data point
                    token_sequences[token_to_idx[symbol]] = np.roll(
                        token_sequences[token_to_idx[symbol]],
                        -1,
                        axis=0
                    )
                    token_sequences[token_to_idx[symbol]][-1] = train_scaled_dict[symbol].iloc[env.current_step][feature_columns].values
                
                # Store experience
                agent.remember(
                    token_to_idx[symbol],
                    state,
                    token_sequences[token_to_idx[symbol]],
                    action,
                    reward,
                    next_state,
                    token_sequences[token_to_idx[symbol]],  # Next sequence is the same since we already updated it
                    done
                )
                
                # Track token-specific actions
                if info['action'] == 'buy':
                    token_buy_counts[symbol] += 1
                    token_trade_counts[symbol] += 1
                elif info['action'] == 'sell':
                    token_sell_counts[symbol] += 1
                    token_trade_counts[symbol] += 1
                
                # Update state
                state = next_state
                total_reward += reward
                
                # Break if done
                if done:
                    break
            
            # Train after each step through all tokens
            agent.replay(min(batch_size, len(agent.memory)))
            
            # Update target model occasionally
            if len(agent.memory) >= batch_size * 5 and step_count % 10 == 0:
                agent.update_target_models()
            
            # Store portfolio value
            portfolio_values.append(env.portfolio_value())
            
            # Increment step counter
            step_count += 1
            
            # Break if environment signals done
            if done:
                break
        
        # Record history
        history['episode_rewards'].append(total_reward)
        history['portfolio_values'].append(portfolio_values[-1])
        
        for symbol in token_symbols:
            history['trades_per_token'][symbol].append(token_trade_counts[symbol])
            history['buy_count_per_token'][symbol].append(token_buy_counts[symbol])
            history['sell_count_per_token'][symbol].append(token_sell_counts[symbol])
        
        # Calculate ROI
        roi = ((portfolio_values[-1] - initial_balance) / initial_balance) * 100
        
        # Update progress bar
        total_trades = sum(token_trade_counts.values())
        episode_pbar.set_description(
            f"Episode {episode+1}/{episodes} - ROI: {roi:.1f}%, Trades: {total_trades}"
        )
        
        # Save model periodically
        if episode % save_interval == 0:
            agent.save(f"{model_name}_ep{episode}")
        
        # Log episode results
        position_summary = ", ".join([
            f"{symbol}: {env.positions[symbol]:.2f}" for symbol in token_symbols
            if env.positions[symbol] > 0
        ])
        
        position_summary = position_summary if position_summary else "No positions"
        
        logger.info(f"Episode {episode+1}/{episodes} - "
                   f"Reward: {total_reward:.2f}, "
                   f"Portfolio: ${portfolio_values[-1]:.2f}, "
                   f"ROI: {roi:.2f}%, "
                   f"Trades: {total_trades}, "
                   f"Positions: {position_summary}")
    
    # Save final model
    agent.save(model_name)
    
    # Evaluate on test data
    test_env = MultiTokenTradingEnvironment(
        price_data_dict=test_data_dict,
        initial_balance=initial_balance,
        lookback_window=lookback_window,
        transaction_fee=0.001
    )
    
    # Test evaluation
    test_state = test_env.reset()
    test_portfolio_values = [initial_balance]
    test_rewards = 0
    test_trades = {symbol: 0 for symbol in token_symbols}
    test_buys = {symbol: 0 for symbol in token_symbols}
    test_sells = {symbol: 0 for symbol in token_symbols}
    done = False
    
    # Initialize token sequences for testing
    test_token_sequences = {}
    for symbol, idx in token_to_idx.items():
        test_token_sequences[idx] = np.zeros((sequence_length, len(feature_columns)))
        current_data = test_scaled_dict[symbol].iloc[:sequence_length]
        if len(current_data) == sequence_length:
            test_token_sequences[idx] = current_data[feature_columns].values
    
    # Evaluation loop
    while not done:
        for idx, symbol in enumerate(token_symbols):
            # Choose action (no exploration)
            action = agent.act(
                token_idx=token_to_idx[symbol],
                state=test_state,
                sequence=test_token_sequences[token_to_idx[symbol]],
                evaluate=True
            )
            
            # Execute action
            next_state, reward, done, info = test_env.step(token_to_idx[symbol], action)
            
            # Update sequence
            if test_env.current_step < len(test_scaled_dict[symbol]):
                test_token_sequences[token_to_idx[symbol]] = np.roll(
                    test_token_sequences[token_to_idx[symbol]],
                    -1,
                    axis=0
                )
                test_token_sequences[token_to_idx[symbol]][-1] = test_scaled_dict[symbol].iloc[test_env.current_step][feature_columns].values
            
            # Track metrics
            test_rewards += reward
            
            # Count trades
            if info['action'] == 'buy':
                test_trades[symbol] += 1
                test_buys[symbol] += 1
            elif info['action'] == 'sell':
                test_trades[symbol] += 1
                test_sells[symbol] += 1
            
            # Update state
            test_state = next_state
            
            if done:
                break
        
        # Store portfolio value
        test_portfolio_values.append(test_env.portfolio_value())
        
        if done:
            break
    
    # Calculate test performance
    test_portfolio = test_env.portfolio_value()
    test_roi = ((test_portfolio - initial_balance) / initial_balance) * 100
    
    # Log test results
    logger.info("\nTest Results:")
    logger.info(f"Initial Portfolio: ${initial_balance:.2f}")
    logger.info(f"Final Portfolio: ${test_portfolio:.2f}")
    logger.info(f"ROI: {test_roi:.2f}%")
    
    for symbol in token_symbols:
        logger.info(f"{symbol} - Trades: {test_trades[symbol]} (Buys: {test_buys[symbol]}, Sells: {test_sells[symbol]})")
    
    # Calculate buy & hold performance
    buy_hold_roi = {}
    for symbol in token_symbols:
        first_price = test_data_dict[symbol].iloc[0]['close']
        last_price = test_data_dict[symbol].iloc[-1]['close']
        buy_hold_roi[symbol] = (last_price - first_price) / first_price * 100
        logger.info(f"{symbol} Buy & Hold ROI: {buy_hold_roi[symbol]:.2f}%")
    
    # Calculate portfolio buy & hold (equal weight)
    avg_buy_hold = sum(buy_hold_roi.values()) / len(buy_hold_roi)
    logger.info(f"Average Buy & Hold ROI: {avg_buy_hold:.2f}%")
    
    # Add test metrics to history
    history['test_portfolio'] = test_portfolio
    history['test_roi'] = test_roi
    history['test_rewards'] = test_rewards
    history['test_trades'] = test_trades
    history['test_buys'] = test_buys
    history['test_sells'] = test_sells
    history['buy_hold_roi'] = buy_hold_roi
    history['avg_buy_hold_roi'] = avg_buy_hold
    
    # Print summary
    print("\n" + "="*80)
    print(f"MULTI-TOKEN ATCGAN-RL AGENT EVALUATION")
    print("="*80)
    print(f"Tokens: {', '.join(token_symbols)}")
    print(f"Training Episodes: {episodes}")
    print(f"Initial Balance: ${initial_balance:.2f}")
    
    # Training results
    print("\n" + "-"*30 + " TRAINING RESULTS " + "-"*30)
    
    # Calculate averages for last 10 episodes
    num_avg_episodes = min(10, len(history['portfolio_values']))
    avg_portfolio = sum(history['portfolio_values'][-num_avg_episodes:]) / num_avg_episodes
    avg_roi = ((avg_portfolio - initial_balance) / initial_balance) * 100
    
    print(f"Average Portfolio (last {num_avg_episodes} episodes): ${avg_portfolio:.2f}")
    print(f"Average ROI: {avg_roi:.2f}%")
    
    # Token-specific metrics
    for symbol in token_symbols:
        avg_trades = sum(history['trades_per_token'][symbol][-num_avg_episodes:]) / num_avg_episodes
        avg_buys = sum(history['buy_count_per_token'][symbol][-num_avg_episodes:]) / num_avg_episodes
        avg_sells = sum(history['sell_count_per_token'][symbol][-num_avg_episodes:]) / num_avg_episodes
        
        print(f"{symbol} - Avg Trades: {avg_trades:.1f} (Buys: {avg_buys:.1f}, Sells: {avg_sells:.1f})")
    
    # Test results
    print("\n" + "-"*30 + " TESTING RESULTS " + "-"*32)
    print(f"Final Portfolio: ${test_portfolio:.2f}")
    print(f"Return on Investment: {test_roi:.2f}%")
    
    # Token-specific test metrics
    for symbol in token_symbols:
        print(f"{symbol} - Trades: {test_trades[symbol]} (Buys: {test_buys[symbol]}, Sells: {test_sells[symbol]})")
        print(f"{symbol} - Buy & Hold ROI: {buy_hold_roi[symbol]:.2f}%")
    
    # Performance comparison
    print(f"\nAgent vs Avg Buy & Hold: {test_roi - avg_buy_hold:+.2f}%")
    
    # Final positions
    print("\nFinal Positions:")
    for symbol in token_symbols:
        if test_env.positions[symbol] > 0:
            symbol_value = test_env.positions[symbol] * test_data_dict[symbol].iloc[-1]['close']
            allocation = symbol_value / test_portfolio * 100
            print(f"{symbol}: {test_env.positions[symbol]:.4f} (${symbol_value:.2f}, {allocation:.1f}%)")
    
    cash_allocation = test_env.balance / test_portfolio * 100
    print(f"Cash: ${test_env.balance:.2f} ({cash_allocation:.1f}%)")
    
    print("="*80)
    
    return agent, history 