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
import threading
import queue
from typing import Dict, List, Optional

from src.utils.logger import log_manager

# Enable mixed precision for faster GPU training
try:
    policy = tf.keras.mixed_precision.Policy('mixed_float16')
    tf.keras.mixed_precision.set_global_policy(policy)
    USING_MIXED_PRECISION = True
except:
    USING_MIXED_PRECISION = False

logger = log_manager.get_logger("fast_rl_agent")
logger.info(f"Using mixed precision: {USING_MIXED_PRECISION}")

# Optimize TensorFlow operations
tf.config.optimizer.set_jit(True)  # Enable XLA optimization

class RewardCalculator:
    def __init__(
        self,
        alpha: float = 2.0,
        beta: float = 0.3,
        gamma: float = 0.05,
        delta: float = 0.05,
        cost_rate: float = 0.002,
        vol_window: int = 24,
        warmup_steps: int = 24,
    ):
        # Hyperparameters
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.delta = delta
        self.cost_rate = cost_rate
        self.vol_window = vol_window
        self.warmup_steps = warmup_steps

        # Stateful history
        self.returns: List[float] = []
        self.portfolio_values: List[float] = []
        self.step = 0

    def compute_reward(
        self,
        prev_value: float,
        curr_value: float,
        action: int,           # -1, 0, +1
    ) -> float:
        """
        Compute composite reward at each time step.
        - prev_value: portfolio value at t-1
        - curr_value: portfolio value at t
        - action: discrete action taken (-1 sell, 0 hold, +1 buy)
        """

        self.step += 1
        # 1) Profit term (log-return)
        if prev_value <= 0:
            profit = 0.0
        else:
            profit = np.log(curr_value / prev_value)

        # Record history
        self.returns.append(profit)
        self.portfolio_values.append(curr_value)

        # 2) Transaction cost: fixed 5% trade size per action (except hold)
        trade_size = 0.05
        cost_penalty = (
            self.beta * self.cost_rate * trade_size
            if action != 0
            else 0.0
        )

        # 3) Volatility penalty (only after warmup)
        if self.step > self.warmup_steps and len(self.returns) >= self.vol_window:
            vol = np.std(self.returns[-self.vol_window :])
            vol_penalty = self.gamma * vol * trade_size
        else:
            vol_penalty = 0.0

        # 4) Drawdown penalty (only after warmup)
        if self.step > self.warmup_steps:
            peak = max(self.portfolio_values[:-1]) if len(self.portfolio_values) > 1 else curr_value
            drawdown = max(0.0, (peak - curr_value) / peak) if peak > 0 else 0.0
            dd_penalty = self.delta * drawdown * trade_size
        else:
            dd_penalty = 0.0

        # 5) (Optional) Benchmark penalty: underperforming a HODL return
        # e.g.: hodl_return = ln(price_t / price_{t-1})
        # bench_penalty = theta * max(0, hodl_return - profit)

        # Composite reward
        reward = (
            self.alpha * profit
            - cost_penalty
            - vol_penalty
            - dd_penalty
        )

        # (Optional) clip reward for stability
        reward = float(np.clip(reward, -1.0, 1.0))

        return reward

    def reset(self):
        """Call at the start of each episode."""
        self.returns.clear()
        self.portfolio_values.clear()
        self.step = 0

class FastTradingEnvironment:
    """Optimized environment for RL agent to interact with market data"""
    
    def __init__(self, price_data, feature_data, initial_balance=10000.0, transaction_fee=0.001, 
                risk_free_rate=0.0, sharpe_lookback=30, sharpe_weight=2.0,
                position_sizing="fixed", max_position_pct=0.2, resolution="1m", 
                reward_type="profit_focused", slippage_pct=0.0015):
        """
        Initialize trading environment with vectorized operations
        
        Args:
            price_data: Array of historical prices
            feature_data: Array of features for state representation
            initial_balance: Starting cash balance
            transaction_fee: Fee as percentage of trade value
            risk_free_rate: Annual risk-free rate for Sharpe calculation
            sharpe_lookback: Number of steps to use for Sharpe calculation
            sharpe_weight: Weight of Sharpe reward component
            position_sizing: Strategy for position sizing ('fixed', 'kelly', or 'random')
            max_position_pct: Maximum position size as percentage of portfolio (for fixed sizing)
            resolution: Time resolution of the data (e.g., "1m", "5m", "15m", "1h", "4h", "1d")
            reward_type: Type of reward function to use ('combined', 'sharpe_only')
            slippage_pct: Percentage of slippage to apply to trades (0.0015 = 15 basis points)
        """
        self.prices = price_data
        
        # Ensure feature_data is a proper array, not a scalar
        if not isinstance(feature_data, np.ndarray):
            raise ValueError(f"feature_data must be a numpy array, got {type(feature_data)}")
        
        # Check dimensions
        if feature_data.ndim != 2:
            raise ValueError(f"feature_data must be a 2D array, but has {feature_data.ndim} dimensions")
        
        # Ensure we have at least one feature
        if feature_data.shape[1] == 0:
            raise ValueError("feature_data must have at least one feature (second dimension > 0)")
            
        # Ensure data types are numeric
        try:
            # Try to convert to float if not already
            if feature_data.dtype.kind not in 'fc':  # 'f' for float, 'c' for complex
                logger.warning(f"Converting feature data from {feature_data.dtype} to float64")
                feature_data = feature_data.astype(np.float64)
        except Exception as e:
            logger.error(f"Error converting feature data to numeric: {e}")
            raise ValueError(f"feature_data must contain numeric values that can be converted to float")
        
        self.features = feature_data
        
        # Pre-normalize features for faster processing
        try:
            # Sanitize data before calculating statistics
            # Check for and replace any NaN or infinite values
            cleaned_data = np.copy(feature_data)
            if np.isnan(cleaned_data).any() or np.isinf(cleaned_data).any():
                logger.warning(f"Found NaN or Inf values in feature_data. Replacing with zeros.")
                cleaned_data = np.nan_to_num(cleaned_data, nan=0.0, posinf=0.0, neginf=0.0)
            
            # Calculate mean across all samples for each feature
            self.feature_mean = np.mean(cleaned_data, axis=0)
            
            # Calculate standard deviation safely, handling zero-variance features
            raw_std = np.std(cleaned_data, axis=0)
            
            # Ensure no zeros in std to avoid division by zero (use small constant)
            self.feature_std = np.where(raw_std > 1e-8, raw_std, 1.0)
            
            # Normalize features
            self.normalized_features = (cleaned_data - self.feature_mean) / self.feature_std
        except Exception as e:
            logger.error(f"Error normalizing features: {e}")
            logger.error(f"feature_data shape: {feature_data.shape}")
            logger.error(f"feature_data type: {type(feature_data)}")
            logger.error(f"feature_data dtype: {feature_data.dtype}")
            if len(feature_data) > 0:
                logger.error(f"feature_data first few values: {feature_data[:5]}")
            raise
        
        self.initial_balance = initial_balance
        self.transaction_fee = transaction_fee
        self.slippage_pct = slippage_pct  # Store slippage percentage
        
        # Position sizing parameters
        self.position_sizing = position_sizing
        self.max_position_pct = max_position_pct
        
        # Sharpe ratio parameters
        self.risk_free_rate = risk_free_rate  # Annual risk-free rate
        self.sharpe_lookback = min(sharpe_lookback, len(price_data))  # Period for Sharpe calculation
        self.sharpe_weight = sharpe_weight  # Weight of Sharpe in reward function
        
        # Reward function type ('combined' = original complex reward, 'sharpe_only' = only Sharpe ratio)
        self.reward_type = reward_type
        logger.info(f"Using {self.reward_type} reward function")
        
        # Initialize the new reward calculator for profit_focused type
        if self.reward_type == "profit_focused":
            self.reward_calculator = RewardCalculator(
                alpha=1.0,      # Weight for profit term
                beta=1.0,       # Weight for transaction cost
                gamma=0.1,      # Weight for volatility penalty  
                delta=0.1,      # Weight for drawdown penalty
                cost_rate=self.transaction_fee,  # Use environment's transaction fee
                vol_window=50,  # 50-step volatility window
                warmup_steps=50  # 50-step warmup period
            )
        
        # Returns tracking for proper Sharpe ratio calculation
        self.minute_returns = []
        self.daily_returns = []
        self.current_day_returns = []
        
        # Calculate periods per day based on resolution
        minutes_per_period = self._get_minutes_from_resolution(resolution)
        self.PERIODS_PER_DAY = int(24 * 60 / minutes_per_period)  # Periods in 24 hours for crypto (24/7 market)
        logger.info(f"Using resolution {resolution} with {self.PERIODS_PER_DAY} periods per day")
        
        # Add tracking for trading behavior
        self.last_action_step = 0       # Track when the last action was taken
        self.action_count = 0           # Count actions taken
        self.last_action_type = 0       # Track last action type (0=hold, 1=buy, 2=sell)
        
        # Add tracking for position high-water mark (for drawdown penalties)
        self.position_high_water_mark = 0.0    # Highest value since position was opened
        self.position_high_step = 0            # Step when high was reached
        self.lookback_for_recent_high = 24     # Look back 24 steps for "recent" high
        
        # Add tracking for performance metrics
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        self.longest_win_streak = 0
        self.longest_lose_streak = 0
        self.current_win_streak = 0
        self.current_lose_streak = 0
        self.trade_durations = []
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        
        # Sequence management for LSTM networks
        self.sequence_length = 10  # Default sequence length for LSTMs
        self.observation_buffer = deque(maxlen=self.sequence_length)
        
        self.reset()
        
    def _get_minutes_from_resolution(self, resolution):
        """Convert resolution string to minutes per period"""
        resolution = str(resolution).lower()  # Convert to lowercase for case-insensitive matching
        if resolution.endswith('m'):
            return int(resolution[:-1])
        elif resolution.endswith('h'):
            return int(resolution[:-1]) * 60
        elif resolution.endswith('d'):
            return int(resolution[:-1]) * 24 * 60
        else:
            logger.warning(f"Unknown resolution format {resolution}, defaulting to 5m")
            return 5  # Default to 5 minutes if resolution format is unknown
        
    def reset(self):
        """Reset environment to initial state"""
        self.current_step = 0
        self.balance = self.initial_balance
        self.position = 0  # 0 = no position, 1 = long
        self.shares_held = 0
        self.position_price = 0
        self.position_entry_step = 0  # When current position was entered
        
        # Track maximum portfolio value for drawdown calculation
        self.max_portfolio_value = self.initial_balance
        
        # Track rejected buys due to DCA prevention
        self.dca_prevented_count = 0
        self.partial_sell_count = 0  # Keep to maintain backwards compatibility
        
        # Reset trade tracking variables
        self.last_action_step = 0
        self.action_count = 0
        self.last_action_type = 0
        
        # Reset position high-water mark tracking
        self.position_high_water_mark = 0.0
        self.position_high_step = 0
        
        # Initialize portfolio values array with correct dimensions
        self.portfolio_values = np.zeros(len(self.prices))
        
        # CRITICAL: Set initial portfolio value to initial_balance
        self.portfolio_values[0] = self.initial_balance  
        
        # Safety check - make sure we don't have uninitialized values
        # Fill all initially with the same value
        for i in range(1, min(10, len(self.portfolio_values))):
            self.portfolio_values[i] = self.initial_balance
            
        # Reset reward calculator if using profit_focused
        if self.reward_type == "profit_focused" and hasattr(self, 'reward_calculator'):
            self.reward_calculator.reset()
            
        # Initialize sequence buffer with initial observation
        self.observation_buffer.clear()
        initial_obs = self._get_single_observation()
        # Fill buffer with initial observation (padding for start of episode)
        for _ in range(self.sequence_length):
            self.observation_buffer.append(initial_obs.copy())
        
        # Reset daily returns for Sharpe calculation
        self.minute_returns = []
        self.daily_returns = []
        self.current_day_returns = []
        
        # Initialize with small positive returns to avoid early instability 
        # and prevent zero Sharpe ratios due to insufficient data
        for _ in range(5):
            self.daily_returns.append(0.0001)
        
        self.trades = []
        
        # Pre-calculate possible states
        self._calculate_possible_states()
        
        # Ensure we have enough prices to work with
        if len(self.prices) < 2:
            logger.error(f"Not enough price data: {len(self.prices)} data points")
            raise ValueError("Insufficient price data for RL trading")
        
        # Reset performance metrics
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        self.longest_win_streak = 0
        self.longest_lose_streak = 0
        self.current_win_streak = 0
        self.current_lose_streak = 0
        self.trade_durations = []
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        
        return self._get_observation()
        
    def _calculate_possible_states(self):
        """Pre-calculate state information for faster access"""
        # Calculate returns for reward calculation
        self.price_returns = np.zeros_like(self.prices)
        self.price_returns[1:] = (self.prices[1:] - self.prices[:-1]) / self.prices[:-1]
        
    def _calculate_sharpe_ratio(self):
        """Calculate the Sharpe ratio based on portfolio returns"""
        # Need sufficient daily returns for meaningful calculation
        if len(self.daily_returns) < 5:  # Require at least 5 days of returns
            return 0.0  # Not enough data for calculation
            
        # Use only the lookback period of daily returns
        recent_daily_returns = self.daily_returns[-self.sharpe_lookback:]
        
        # Safety check: filter out any extreme values or NaNs
        filtered_returns = [r for r in recent_daily_returns if np.isfinite(r) and abs(r) < 0.5]  # Less strict filtering
        
        # If we don't have enough valid returns after filtering, return a neutral value
        if len(filtered_returns) < 5:  # Require at least 5 valid returns
            return 0.0
            
        # Calculate mean and standard deviation of daily returns
        mean_return = np.mean(filtered_returns)
        std_return = np.std(filtered_returns)
        
        # Avoid division by zero or extremely small values
        if std_return < 0.0001:
            if mean_return > 0:
                return 1.0  # If mean is positive but volatility is tiny, return modest positive Sharpe
            elif mean_return < 0:
                return -1.0  # If mean is negative but volatility is tiny, return modest negative Sharpe
            else:
                return 0.0  # Neutral case
        
        # Convert risk-free rate to per-period rate based on periods per day
        # We're dealing with daily returns (already aggregated from minute/hour data)
        daily_rf_rate = self.risk_free_rate / 365.0  # Daily equivalent for crypto trading (365 days)
        
        # Calculate Sharpe ratio: (mean_return - risk_free_rate) / std_deviation
        sharpe = (mean_return - daily_rf_rate) / std_return
        
        # Annualize the Sharpe ratio properly based on actual periods per year
        # Since we've already aggregated to daily returns regardless of original resolution,
        # the annualization factor is based on days per year
        periods_per_year = 365  # We're using daily returns
        annual_sharpe = sharpe * np.sqrt(periods_per_year)
        
        # Add debug logging to help track Sharpe calculation
        if np.random.random() < 0.01:  # Only log occasionally to avoid spam
            logger.debug(f"Sharpe calculation - Mean return: {mean_return:.6f}, Std: {std_return:.6f}, " +
                       f"Daily RF rate: {daily_rf_rate:.6f}, Periods/day: {self.PERIODS_PER_DAY}, " +
                       f"Result: {annual_sharpe:.4f}")
        
        # Cap extreme values
        annual_sharpe = max(min(annual_sharpe, 5.0), -5.0)
        
        return annual_sharpe
        
    def step(self, action):
        """
        Take action in environment with vectorized operations
        
        Args:
            action: 0 = hold
                   1 = buy with fixed position size
                   2 = sell all (liquidate entire position)
            
        Returns:
            Tuple of (observation, reward, done, info)
        """
        # Get current price and price return
        current_price = self.prices[self.current_step]
        reward = 0
        profit = 0  # Initialize profit to avoid undefined variable errors
        position_size_pct = 0  # Track which position size was used
        
        # No cooling off period needed at hourly resolution
        
        # Track pre-action portfolio for reward calculation
        pre_action_portfolio = self.balance
        if self.position == 1 and self.shares_held > 0:
            pre_action_portfolio += self.shares_held * current_price
        
        # Store original action for reward calculation
        original_action = action
        action_executed = True  # Track whether the action was executed as intended
        
        # Check for stop-loss condition before executing trade
        stop_loss_triggered = False
        stop_loss_penalty = 0
        
        if self.position == 1 and self.shares_held > 0:
            # Calculate current loss percentage
            loss_pct = (self.position_price - current_price) / self.position_price
            
            # Apply stop-loss at 7% loss
            if loss_pct > 0.20:
                # Force sell and log it
                stop_loss_triggered = True
                action = 2  # Force SELL FULL POSITION action
                stop_loss_penalty = 0.5  # Reduced fixed penalty for hitting stop loss
                logger.debug(f"Stop-loss triggered: {loss_pct:.2%} loss, forced sell at {current_price:.4f}")
        
        # Execute trade based on action - optimized logic
        if action == 1 and self.balance > 0:  # Buy action
            # Prevent DCA - reject buy action if position is already open
            if (self.position == 1 and self.shares_held > 0):
                # Store original action for penalty calculation
                original_action = action
                
                # Force action to HOLD instead of buy
                action = 0
                action_executed = False  # Mark that the original action was not executed
                # Track rejected buy attempt
                self.dca_prevented_count += 1
                # Apply penalty for attempting DCA
                dca_attempt_penalty = 0.5  # Significant penalty to discourage this behavior
                reward -= dca_attempt_penalty
                # Log the rejection reason
                logger.debug(f"DCA prevention: Rejecting buy action (position already open with {self.shares_held:.4f} shares), penalty: -{dca_attempt_penalty}")
            else:
                # Use fixed position size (5%)
                position_fraction = 0.05
                position_size_pct = 5
                
                # Apply slippage to buy price (buy at slightly higher price)
                execution_price = current_price * (1 + self.slippage_pct)
                    
                # Calculate position size based on current portfolio value
                current_portfolio = self.balance
                if self.position == 1 and self.shares_held > 0:
                    current_portfolio += self.shares_held * current_price
                    
                # Calculate new position size in shares
                new_position_value = current_portfolio * position_fraction
                shares_to_buy = new_position_value / (execution_price * (1 + self.transaction_fee))
                
                # Calculate actual cost with fees and slippage
                cost = shares_to_buy * execution_price * (1 + self.transaction_fee)
                
                # Double-check we're not spending more than we have
                if cost > self.balance:
                    shares_to_buy = self.balance / (execution_price * (1 + self.transaction_fee)) * 0.99
                    cost = shares_to_buy * execution_price * (1 + self.transaction_fee)
                
                # Sanity check - don't allow absurdly small positions
                if shares_to_buy * execution_price < 1.0 or shares_to_buy < 0.001:
                    shares_to_buy = 0
                    cost = 0
                
                self.balance -= cost
                self.position = 1 if shares_to_buy > 0 else 0
                
                # For new positions, set the position price
                if self.shares_held == 0:
                    self.position_price = execution_price  # Set entry price for new position
                    # Initialize high-water mark for new position
                    self.position_high_water_mark = execution_price
                    self.position_high_step = self.current_step
                else:
                    # Calculate weighted average price for additional purchases
                    total_shares = self.shares_held + shares_to_buy
                    self.position_price = ((self.position_price * self.shares_held) + 
                                          (execution_price * shares_to_buy)) / total_shares
                
                # Update shares held
                self.shares_held += shares_to_buy
                
                if shares_to_buy > 0:
                    # Track when this position was entered for holding duration calculation
                    if self.shares_held == shares_to_buy:  # New position
                        self.position_entry_step = self.current_step
                    
                    self.trades.append({
                        "step": self.current_step,
                        "type": "buy",
                        "price": execution_price,  # Record actual execution price
                        "market_price": current_price,  # Also record market price for reference
                        "slippage": execution_price - current_price,  # Record slippage amount
                        "shares": shares_to_buy,
                        "cost": cost,
                        "position_size_pct": position_size_pct,  # Record which position size was used
                    })
                    # Track this action for trading frequency tracking
                    self.action_count += 1
                    self.last_action_type = action
                    self.last_action_step = self.current_step
            
        elif action == 2 and self.position == 1 and self.shares_held > 0:  # Sell action
            # Calculate shares to sell - always 100%
            shares_to_sell = self.shares_held
            
            # Apply slippage to sell price (sell at slightly lower price)
            execution_price = current_price * (1 - self.slippage_pct)
            
            # Calculate revenue and profit
            revenue = shares_to_sell * execution_price * (1 - self.transaction_fee)
            profit = revenue - (shares_to_sell * self.position_price)
            
            # Update balance and position
            self.balance += revenue
            self.shares_held = 0
            
            # Reset position flags
            self.position = 0
            self.position_price = 0
            self.position_entry_step = 0
            
            # Reset high-water mark when position is closed
            self.position_high_water_mark = 0.0
            self.position_high_step = 0
            
            # Add to trades log
            self.trades.append({
                "step": self.current_step,
                "type": "sell",
                "price": execution_price,  # Record actual execution price
                "market_price": current_price,  # Also record market price for reference
                "slippage": current_price - execution_price,  # Record slippage amount
                "shares": shares_to_sell,
                "shares_remaining": 0,
                "sell_percent": 100.0,  # Always 100% now
                "profit": profit,
                "partial_sell": False  # Always full sell now
            })
            
            # Track this action for trading frequency tracking
            self.action_count += 1
            self.last_action_type = action
            self.last_action_step = self.current_step
            
            # Track profit/loss for metrics
            if profit > 0:
                self.gross_profit += profit
                self.current_win_streak += 1
                self.current_lose_streak = 0
                self.longest_win_streak = max(self.longest_win_streak, self.current_win_streak)
            else:
                self.gross_loss += abs(profit)
                self.current_lose_streak += 1
                self.current_win_streak = 0
                self.longest_lose_streak = max(self.longest_lose_streak, self.current_lose_streak)
            
            # Track position duration
            if hasattr(self, 'position_entry_step') and self.position_entry_step > 0:
                duration = self.current_step - self.position_entry_step
                self.trade_durations.append(duration)
        
        # CRITICAL: Calculate portfolio value - ALWAYS include cash balance
        portfolio_value = self.balance  # Cash is ALWAYS included in portfolio
        if self.position == 1 and self.shares_held > 0:
            position_value = self.shares_held * current_price
            portfolio_value += position_value
            
            # Update high-water mark for open positions
            if current_price > self.position_high_water_mark:
                self.position_high_water_mark = current_price
                self.position_high_step = self.current_step
            
        # Store portfolio value for this step
        self.portfolio_values[self.current_step] = portfolio_value
        
        # Update maximum portfolio value and calculate drawdown
        self.max_portfolio_value = max(self.max_portfolio_value, portfolio_value)
        self.current_drawdown = (self.max_portfolio_value - portfolio_value) / self.max_portfolio_value if self.max_portfolio_value > 0 else 0
        self.max_drawdown = max(self.max_drawdown, self.current_drawdown)
        
        # Calculate portfolio return for this step (for Sharpe ratio)
        if self.current_step > 0 and self.portfolio_values[self.current_step-1] > 0:
            # Calculate return and ensure it's valid
            prev_value = self.portfolio_values[self.current_step-1]
            minute_return = (portfolio_value / prev_value) - 1.0
            
            # Safety check: filter out extreme or invalid values
            if np.isfinite(minute_return) and abs(minute_return) < 0.5:
                self.minute_returns.append(minute_return)
                self.current_day_returns.append(minute_return)
            else:
                # Use a small non-zero value instead of extreme values
                safe_value = 0.0001 * (1 if minute_return >= 0 else -1)  # Preserve sign
                self.minute_returns.append(safe_value)
                self.current_day_returns.append(safe_value)
            
            # Every PERIODS_PER_DAY steps, aggregate into a daily return
            # This approximates daily returns from 5-minute returns
            if len(self.current_day_returns) >= self.PERIODS_PER_DAY:
                # Calculate compound daily return
                daily_return = np.prod(np.array(self.current_day_returns) + 1.0) - 1.0
                
                # Add to daily returns list
                self.daily_returns.append(daily_return)
                
                # Reset current day returns
                self.current_day_returns = []
                
                # Log daily return for debugging
                logger.debug(f"Aggregated daily return: {daily_return:.4f}")
        
        # Calculate reward based on the selected reward type
        if self.reward_type == "sharpe_only":
            # Sharpe-ratio-only reward function
            if len(self.daily_returns) >= 5:  # Need enough data for Sharpe
                # Calculate Sharpe ratio and scale to reward
                sharpe = self._calculate_sharpe_ratio()
                # Scale to make a reasonable reward range (-1 to +1)
                reward = np.clip(sharpe * 0.5, -1.0, 1.0)
                
                # Small action penalty to discourage excessive trading
                if action != 0:  # Any non-hold action
                    reward -= 0.05  # Small fixed cost for any trade
                
                # Logging for significant Sharpe values
                if abs(sharpe) > 1.0:
                    logger.debug(f"Sharpe-only reward: {reward:.4f} from Sharpe ratio: {sharpe:.4f}")
            else:
                # Not enough data yet, use simple immediate return
                if self.current_step > 0 and self.portfolio_values[self.current_step-1] > 0:
                    step_return = (portfolio_value / self.portfolio_values[self.current_step-1]) - 1.0
                    reward = np.clip(step_return * 50.0, -1.0, 1.0)
                
                # Small action penalty
                if action != 0:  # Any non-hold action
                    reward -= 0.05  # Small fixed cost for any trade
        elif self.reward_type == "profit_focused":
            # NEW: Use RewardCalculator for sophisticated reward computation
            if hasattr(self, 'reward_calculator'):
                # Get previous portfolio value
                prev_value = self.portfolio_values[self.current_step-1] if self.current_step > 0 else self.initial_balance
                curr_value = portfolio_value
                
                # Convert our action space (0=hold, 1=buy, 2=sell) to RewardCalculator's (-1, 0, +1)
                if action == 0:  # Hold
                    calc_action = 0
                elif action == 1:  # Buy 
                    calc_action = 1
                elif action == 2:  # Sell
                    calc_action = -1
                else:
                    calc_action = 0  # Default to hold for any other action
                
                # Get reward from RewardCalculator
                reward = self.reward_calculator.compute_reward(prev_value, curr_value, calc_action)
                
                # Log significant rewards occasionally for debugging
                if abs(reward) > 0.1 and np.random.random() < 0.05:  # 5% logging chance
                    logger.debug(f"RewardCalculator: prev={prev_value:.2f}, curr={curr_value:.2f}, action={calc_action}, reward={reward:.4f}")
            else:
                # Fallback if RewardCalculator not initialized
                reward = 0.0
                logger.warning("RewardCalculator not initialized, using zero reward")
        elif self.reward_type == "simplified_profit_sharpe":
            # Simplified reward focusing on profit and Sharpe ratio
            reward = 0.0
            profit_component = 0.0
            sharpe_component = 0.0
            transaction_penalty = 0.0
            position_sizing_bonus = 0.0
            volatility_alignment = 0.0

            # 1. Step-wise profit component
            if self.current_step > 0 and self.portfolio_values[self.current_step-1] > 0:
                step_return = (portfolio_value / self.portfolio_values[self.current_step-1]) - 1.0
                # Scale: 1% step return = +0.7 reward component
                profit_component = np.clip(step_return * 70.0, -0.7, 0.7)
            
            # 2. Daily Sharpe ratio component
            if len(self.daily_returns) >= 5: # Need enough data for Sharpe
                sharpe = self._calculate_sharpe_ratio() # Sharpe is capped +/- 5.0
                # Scale: Sharpe of 5.0 = +0.7 reward component
                sharpe_component = np.clip(sharpe * 0.14, -0.7, 0.7)
            
            # 3. Transaction cost penalty (based on action)
            if action in [1, 2, 3, 4]:  # Buy actions
                transaction_penalty = 0.02  # Small cost for buying
            elif action in [5, 6, 7]:  # Sell actions
                transaction_penalty = 0.01  # Very small cost for selling
            else:  # Hold
                transaction_penalty = 0.0
                
            # 4. Appropriate position sizing reward for buy actions
            if 1 <= action <= 4 and self.position == 0:  # New position
                # Get the position size that was attempted for this action
                position_sizes = {1: 0.01, 2: 0.025, 3: 0.05, 4: 0.1}
                position_size = position_sizes.get(action, 0.05)  # Default to 5%
                
                # Calculate recent volatility (last 10 periods)
                if self.current_step >= 10:
                    recent_prices = self.prices[self.current_step-10:self.current_step]
                    price_changes = np.diff(recent_prices) / recent_prices[:-1]
                    recent_volatility = np.std(price_changes) if len(price_changes) > 0 else 0.01
                    
                    # Appropriate size: higher volatility = smaller position
                    # Low volatility (1% daily) = up to 10% position OK
                    # High volatility (5% daily) = 2% position max
                    target_position_size = max(0.02, min(0.1, 0.03 / max(recent_volatility, 0.005)))
                    
                    # Bonus for being close to the target size
                    size_difference = abs(position_size - target_position_size)
                    if size_difference < 0.02:  # Within 2% of target
                        position_sizing_bonus = 0.05  # Small bonus for good sizing
                    else:
                        position_sizing_bonus = 0.0
            
            # Add risk-adjustment factor for profit component based on position size
            if 1 <= action <= 4 and profit_component > 0:
                position_sizes = {1: 0.01, 2: 0.025, 3: 0.05, 4: 0.1}
                position_size = position_sizes.get(action, 0.05)
                
                # More reward for profit with smaller positions (reward risk management)
                risk_adjustment = (0.1 / max(position_size, 0.005)) ** 0.5  # Square root dampens the effect
                profit_component = profit_component * min(risk_adjustment, 2.0)  # Cap the multiplier at 2x
            
            # Combine all components for final reward
            reward = profit_component + sharpe_component + position_sizing_bonus - transaction_penalty
            
            if abs(reward) > 0.01 and np.random.random() < 0.01: # Occasional logging
                 logger.debug(f"Reward: Total={reward:.3f} (Profit={profit_component:.3f}, Sharpe={sharpe_component:.3f}, " +
                             f"Sizing={position_sizing_bonus:.3f}, Penalty={transaction_penalty:.3f})")

        else:
            # Original complex reward system
            reward = 0.0  # Start with zero reward
            
            if self.current_step > 0:
                # Calculate step-to-step return (immediate performance)
                if self.current_step > 0 and self.portfolio_values[self.current_step-1] > 0:
                    step_return = (portfolio_value / self.portfolio_values[self.current_step-1]) - 1.0
                    
                    # Amplify immediate returns to encourage profit seeking
                    # 0.01 (1%) change gives reward of 2.5 (was 0.5)
                    normalized_step_reward = np.clip(step_return * 250.0, -5.0, 5.0)
                    
                    # Basic reward is based on immediate portfolio change
                    reward += normalized_step_reward
                    
                    # Log significant step returns
                    if abs(step_return) > 0.005:  # 0.5% change
                        logger.debug(f"Significant step return: {step_return:.2%}, reward component: {normalized_step_reward:.4f}")
                
                # ACTION-SPECIFIC REWARDS AND PENALTIES
                if 1 <= action <= 4 and action_executed:  # Buy actions that were actually executed
                    # Get position size from executed action
                    position_sizes = {1: 0.01, 2: 0.025, 3: 0.05, 4: 0.1}
                    position_size = position_sizes.get(action, 0.05)
                    
                    # Reward for making a move in certain market conditions (much smaller now)
                    if self.current_step > 10:  # Need recent price history
                        # Analyze recent price momentum
                        recent_prices = self.prices[max(0, self.current_step-10):self.current_step+1]
                        
                        # Calculate trend (simple slope)
                        if len(recent_prices) >= 5:
                            # Linear regression slope for trend
                            x = np.arange(len(recent_prices))
                            slope = np.polyfit(x, recent_prices, 1)[0]
                            price_trend = slope / recent_prices[0]  # Normalize by starting price
                            
                            # Reward buying in uptrends (much smaller reward)
                            if price_trend > 0.001:  # 0.1% uptrend
                                trend_reward = min(price_trend * 100.0, 0.2)  # Reduced from 2.0 to 0.2
                                reward += trend_reward
                                
                                # Log significant trend rewards
                                if trend_reward > 0.1:
                                    logger.debug(f"Uptrend buy reward: +{trend_reward:.2f} for {price_trend:.3%} trend")
                            
                            # Penalty for buying in strong downtrends 
                            elif price_trend < -0.002:  # -0.2% downtrend
                                trend_penalty = min(abs(price_trend) * 200.0, 0.5)  # Increased penalty
                                reward -= trend_penalty
                                
                                # Log trend penalties
                                if trend_penalty > 0.2:
                                    logger.debug(f"Downtrend buy penalty: -{trend_penalty:.2f} for {price_trend:.3%} trend")
                    
                    # Position size appropriateness reward
                    if self.current_step >= 20:
                        recent_prices = self.prices[self.current_step-20:self.current_step]
                        price_returns = np.diff(recent_prices) / recent_prices[:-1]
                        recent_volatility = np.std(price_returns) if len(price_returns) > 0 else 0.01
                        
                        # Appropriate size would be inversely proportional to volatility
                        appropriate_size = min(0.1, 0.03 / max(recent_volatility, 0.005))  # Cap at 10%
                        
                        # Reward for being close to appropriate size
                        volatility_alignment = 1 - abs(position_size - appropriate_size) / max(position_size, appropriate_size, 0.001)
                        reward += volatility_alignment * 0.1  # Small bonus for good sizing
                
                elif 5 <= action <= 7:  # Sell actions
                    # Get sell percentage from action
                    sell_percentages = {5: 0.33, 6: 0.66, 7: 1.0}
                    sell_percent = sell_percentages.get(action, 1.0)
                    
                    # Initialize profit_pct to avoid undefined variable issues
                    profit_pct = 0.0
                    
                    # Calculate trade profit or loss for the portion sold
                    if profit != 0:
                        # Use position cost as denominator (with safety check)
                        position_cost = self.shares_held * self.position_price if self.position_price > 0 else 1
                        
                        if position_cost > 0.001:  # Valid position
                            # Trade profit percentage
                            profit_pct = profit / position_cost
                            
                            # Massively increase reward for profitable trades
                            # A 2% profit now gives 2.0 reward (was 0.5), -2% gives -1.0 (asymmetric)
                            if profit_pct > 0:
                                trade_reward = np.clip(profit_pct * 100.0, 0, 5.0)  # Much higher reward for profits
                            else:
                                trade_reward = np.clip(profit_pct * 50.0, -2.0, 0)  # Less punishment for losses
                                
                            reward += trade_reward
                            
                            # Bonus for good timing (when selling partial positions at profit)
                            if profit > 0 and sell_percent < 1.0:
                                reward += 0.05  # Small bonus for well-timed partial profit taking
                            
                            # Log trade outcomes
                            logger.debug(f"Trade completed: {profit_pct:.2%} {'profit' if profit_pct > 0 else 'loss'}, " + 
                                          f"reward component: {trade_reward:.4f}")
                    
                    # Additional context-based selling rewards
                    if self.current_step > 10:
                        recent_prices = self.prices[max(0, self.current_step-10):self.current_step+1]
                        
                        if len(recent_prices) >= 5:
                            # Calculate recent trend
                            x = np.arange(len(recent_prices))
                            slope = np.polyfit(x, recent_prices, 1)[0]
                            price_trend = slope / recent_prices[0]
                            
                            # Small penalty for selling in strong uptrends (unless at good profit)
                            if price_trend > 0.002 and profit_pct < 0.01:  # Uptrend and small profit
                                trend_sell_penalty = min(price_trend * 50.0, 0.2)
                                reward -= trend_sell_penalty
                                
                                # Log uptrend sell penalties
                                if trend_sell_penalty > 0.1:
                                    logger.debug(f"Uptrend small-profit sell penalty: -{trend_sell_penalty:.2f}")
                
                elif action == 0:  # Hold action
                    # HOLDING REWARDS
                    position_hold_steps = 0
                    
                    if self.position == 1 and self.shares_held > 0:
                        # Calculate holding duration
                        if hasattr(self, 'position_entry_step') and self.position_entry_step > 0:
                            position_hold_steps = self.current_step - self.position_entry_step
                            
                        # Reward for holding profitable positions, but penalize drawdowns from recent highs
                        if current_price > self.position_price:
                            unrealized_gain_pct = (current_price / self.position_price) - 1.0
                            
                            # Check for drawdown from recent high
                            drawdown_from_high_penalty = 0.0
                            recent_high_threshold = self.current_step - self.position_high_step
                            
                            # Only apply drawdown penalty if we have a meaningful high and it's recent
                            if (self.position_high_water_mark > self.position_price and  # High is above entry
                                recent_high_threshold <= self.lookback_for_recent_high and  # High was recent
                                current_price < self.position_high_water_mark):  # Currently below high
                                
                                # Calculate drawdown from recent high
                                drawdown_from_high = (self.position_high_water_mark - current_price) / self.position_high_water_mark
                                
                                # Apply graduated penalty based on drawdown magnitude
                                if drawdown_from_high > 0.01:  # Only penalize if >1% drawdown from high
                                    # Escalating penalty: 
                                    # 2% drawdown = -0.1 penalty, 5% = -0.5, 10% = -1.5, 15%+ = -2.5
                                    if drawdown_from_high <= 0.05:  # 0-5% drawdown
                                        drawdown_from_high_penalty = drawdown_from_high * 10.0  # Moderate penalty
                                    elif drawdown_from_high <= 0.10:  # 5-10% drawdown
                                        drawdown_from_high_penalty = 0.5 + (drawdown_from_high - 0.05) * 20.0  # Escalating
                                    else:  # >10% drawdown
                                        drawdown_from_high_penalty = 1.5 + (drawdown_from_high - 0.10) * 10.0  # Heavy penalty
                                    
                                    # Cap maximum penalty
                                    drawdown_from_high_penalty = min(drawdown_from_high_penalty, 2.5)
                                    
                                    # Apply the penalty
                                    reward -= drawdown_from_high_penalty
                                    
                                    # Log significant drawdown penalties
                                    if drawdown_from_high_penalty > 0.2:
                                        steps_since_high = self.current_step - self.position_high_step
                                        logger.debug(f"Position drawdown penalty: -{drawdown_from_high_penalty:.2f} for {drawdown_from_high:.2%} decline from high ({steps_since_high} steps ago)")
                            
                            # Base reward for holding winners (reduced if drawing down from recent high)
                            if unrealized_gain_pct > 0.005:  # 0.5% threshold
                                # Scale with both gain size and duration
                                hold_duration_factor = min(position_hold_steps / 48, 2.0)  # Up to 2x for holding 2 days
                                holding_reward = min(unrealized_gain_pct * 50.0, 1.0) * (1.0 + hold_duration_factor)
                                
                                # Reduce holding reward if position is drawing down from recent high
                                if drawdown_from_high_penalty > 0:
                                    reduction_factor = min(drawdown_from_high_penalty / 1.0, 0.8)  # Up to 80% reduction
                                    holding_reward *= (1.0 - reduction_factor)
                                    logger.debug(f"Reduced holding reward by {reduction_factor:.1%} due to drawdown from high")
                                
                                reward += holding_reward
                                
                                # Log big holding rewards
                                if holding_reward > 0.5:
                                    logger.debug(f"Large holding reward: +{holding_reward:.2f} for {unrealized_gain_pct:.2%} gain")
                        
                        # Small penalty for holding losing positions (even smaller)
                        elif current_price < self.position_price and position_hold_steps > 12:
                            loss_pct = (self.position_price - current_price) / self.position_price
                            # Double the penalty for holding losers
                            holding_loss_penalty = min(loss_pct * 5.0, 0.5)  # Up to 0.5 penalty (was 0.05)
                            reward -= holding_loss_penalty
                            
                            # Log significant holding penalties
                            if holding_loss_penalty > 0.2:
                                logger.debug(f"Holding loss penalty: -{holding_loss_penalty:.2f} for {loss_pct:.2%} loss")
                    
                    # SMALL reward for holding cash during downtrends
                    elif self.position == 0:
                        if self.current_step > 5:  # Need price history
                            recent_prices = self.prices[max(0, self.current_step-5):self.current_step+1]
                            if recent_prices[-1] < recent_prices[0]:  # Downtrend
                                avoided_loss_pct = (recent_prices[0] - recent_prices[-1]) / recent_prices[0]
                                # Increased reward for sitting out downtrends (3X)
                                cash_reward = min(avoided_loss_pct * 6.0, 0.3)  # Tripled
                                reward += cash_reward
                
                # PORTFOLIO PERFORMANCE COMPONENT
                # Evaluate overall portfolio performance vs initial balance
                relative_performance = (portfolio_value / self.initial_balance) - 1.0
                
                # Exponential scaling for overall performance
                # 10% portfolio gain = +0.3 reward (was 0.1), 20% = +0.8, 50% = +3.0, 100% = +10.0
                if relative_performance > 0:
                    # Exponential scaling for positive performance
                    performance_reward = np.clip(relative_performance * relative_performance * 20.0, 0, 10.0)
                else:
                    # Linear scaling for negative performance
                    performance_reward = np.clip(relative_performance * 2.0, -1.0, 0)
                
                reward += performance_reward
                
                # SHARPE RATIO COMPONENT (major factor)
                if len(self.daily_returns) >= 5:
                    sharpe = self._calculate_sharpe_ratio()
                    
                    # Scale Sharpe ratio to reward (-0.3 to +0.3 range)
                    # Sharpe of 1.0 = 0.15 reward, -1.0 = -0.15 reward
                    sharpe_reward = np.clip(sharpe * 0.15, -0.3, 0.3)
                    reward += sharpe_reward
                    
                    # Log Sharpe contribution for significant values
                    if abs(sharpe) > 0.5:
                        logger.debug(f"Sharpe ratio: {sharpe:.4f}, reward component: {sharpe_reward:.4f}")
                
                # DRAWDOWN PENALTY (small but meaningful)
                if self.current_drawdown > 0.03:  # More than 3% drawdown
                    # Scale penalty: 10% drawdown = -0.2 reward
                    drawdown_penalty = min(self.current_drawdown * 2.0, 0.2)
                    reward -= drawdown_penalty
                    
                    # Log significant drawdowns
                    if self.current_drawdown > 0.1:  # >10% drawdown
                        logger.debug(f"Significant drawdown: {self.current_drawdown:.2%}, penalty: -{drawdown_penalty:.4f}")
                
                # TRADING FREQUENCY PENALTY (small)
                # Penalty kicks in at >500 trades, scales up to -0.2 reward
                if self.action_count > 500:
                    excess_trades = self.action_count - 500
                    trade_frequency_penalty = min(excess_trades * 0.0005, 0.2)
                    reward -= trade_frequency_penalty
                
                # WIN RATE INFLUENCE (significant for training signal)
                # After sufficient trades, factor in win rate
                sell_trades = [t for t in self.trades if t['type'] == 'sell']
                if len(sell_trades) >= 10:  # Need sufficient history
                    win_trades = [t for t in sell_trades if t.get('profit', 0) > 0]
                    win_rate = len(win_trades) / len(sell_trades) if len(sell_trades) > 0 else 0
                    
                    # Win rate influence: 50% rate = 0 reward, 100% = +1.0 (was 0.2), 0% = -1.0 (was -0.2)
                    win_rate_influence = (win_rate - 0.5) * 2.0  # 5x stronger!
                    reward += win_rate_influence
                    
                    # Log significant win rate adjustments
                    if abs(win_rate - 0.5) > 0.2:  # Win rate far from 50%
                        logger.debug(f"Win rate: {win_rate:.2%}, reward adjustment: {win_rate_influence:.4f}")
        
        # Final reward normalization to ensure reasonable scale
        reward = np.clip(reward, -5.0, 5.0)
        
        # Move to next step
        self.current_step += 1
        done = self.current_step >= len(self.prices) - 1
        
        info = {
            'portfolio_value': portfolio_value,
            'position': self.position,
            'balance': self.balance,
            'shares_held': self.shares_held,
            'dca_prevented_count': self.dca_prevented_count,
            'partial_sell_count': self.partial_sell_count
        }
            
        return self._get_observation(), reward, done, info
    
    def _get_single_observation(self):
        """Create single-step observation vector from current state"""
        # Get normalized features for current step
        features = self.normalized_features[self.current_step]
        
        # Create observation with position state
        obs = np.append(features, [self.position])
        return obs
    
    def _get_observation(self):
        """Create observation - single step for non-LSTM, sequence for LSTM"""
        # Update the observation buffer with current observation
        current_obs = self._get_single_observation()
        self.observation_buffer.append(current_obs)
        
        # Return the current observation buffer as a sequence
        # This will be used differently by LSTM vs non-LSTM networks
        return np.array(list(self.observation_buffer))
    
    def run_batch_simulation(self, agent, batch_size=100, training=True):
        """
        Run a batch of simulation steps for efficiency
        
        Args:
            agent: RL agent
            batch_size: Number of steps to process in batch
            training: Whether to use training mode (with exploration)
            
        Returns:
            List of experiences (state, action, reward, next_state, done)
        """
        experiences = []
        
        # Check if we're at the end of data
        if self.current_step >= len(self.prices) - 1:
            logger.warning(f"Cannot run batch at step {self.current_step} - end of data reached")
            # Return an empty list so the training loop can exit cleanly
            return experiences
        
        # Calculate valid state range
        start_step = self.current_step
        end_step = min(start_step + batch_size, len(self.prices) - 1)
        
        # Safety check - ensure sensible range
        if end_step <= start_step:
            logger.warning(f"Invalid batch range: start={start_step}, end={end_step}")
            return experiences
            
        # Calculate actual batch size (may be smaller than requested at the end)
        actual_batch_size = end_step - start_step
        
        # Safety check - ensure we're not processing an empty batch
        if actual_batch_size <= 0:
            logger.warning(f"Zero-sized batch detected at step {start_step}")
            return experiences
            
        # Maximum iterations safeguard to prevent infinite loops
        max_iterations = actual_batch_size * 2
        iteration_count = 0
        
        # Pre-calculate states for all steps in batch for efficiency
        states = []
        for i in range(start_step, end_step):
            # Safety check: ensure current step is in range
            if i >= len(self.prices):
                logger.warning(f"Step {i} exceeds prices length {len(self.prices)}")
                break
                
            # Save current step, get observation, then restore
            original_step = self.current_step
            self.current_step = i
            states.append(self._get_observation())
            self.current_step = original_step
            
        # Safety check: ensure we have states to work with
        if not states:
            logger.warning("No states collected for batch simulation")
            return experiences
            
        # Convert states to proper numpy array and validate shape for LSTM models
        try:
            states_array = np.array(states)
        except ValueError as e:
            logger.error(f"Failed to convert states to array: {e}")
            logger.error(f"States list length: {len(states)}")
            if len(states) > 0:
                logger.error(f"First state shape: {states[0].shape}, Last state shape: {states[-1].shape}")
            return []
        
        # FIXED: Validate and fix sequence shapes for LSTM models
        if agent.network_type in ["lstm", "stacked_lstm", "lstm_attention", "bidirectional_lstm"]:
            expected_shape = 3  # (batch_size, sequence_length, features)
            if len(states_array.shape) != expected_shape:
                logger.error(f"🚨 CRITICAL: LSTM model {agent.network_type} got states with {len(states_array.shape)}D shape: {states_array.shape}")
                logger.error(f"Expected: 3D (batch_size, sequence_length, features)")
                
                # Attempt to fix the shape
                if len(states_array.shape) == 2 and len(states) > 0:
                    # This means _get_observation() returned 1D arrays instead of 2D sequences
                    logger.error("Environment _get_observation() is returning 1D arrays instead of sequences!")
                    logger.error("This destroys temporal learning capability for LSTM models")
                    # Emergency fix: reshape to fake sequences
                    features_per_obs = states_array.shape[1]
                    states_array = states_array.reshape(len(states), 1, features_per_obs)
                    logger.warning(f"Emergency reshape: {states_array.shape} - but this destroys temporal learning!")
                elif len(states_array.shape) == 1:
                    logger.error("Got 1D states array - major error in state collection")
                    return []
                else:
                    logger.error(f"Cannot fix states shape: {states_array.shape}")
                    return []
            else:
                # Correct shape - log success occasionally
                if np.random.random() < 0.001:  # Very occasional logging
                    logger.debug(f"✅ LSTM model correctly received 3D sequences: {states_array.shape}")
        else:
            # Non-LSTM models - sequences will be handled in batch_act
            if np.random.random() < 0.001:  # Very occasional logging
                logger.debug(f"Non-LSTM model received states: {states_array.shape}")
        
        actions = agent.batch_act(states_array, training=training)
        
        # Execute each action and record experiences
        for i, action in enumerate(actions):
            # Iteration safeguard
            iteration_count += 1
            if iteration_count > max_iterations:
                logger.error(f"Max iterations ({max_iterations}) exceeded in batch simulation - possible infinite loop")
                break
                
            if start_step + i >= len(self.prices):
                logger.warning(f"Step {start_step + i} exceeds prices length {len(self.prices)}")
                break
            
            state = states[i]
            next_step = start_step + i + 1
            done = next_step >= len(self.prices) - 1
            
            # Take action and record experience
            self.current_step = start_step + i
            
            # Safety check: verify current step
            if self.current_step >= len(self.prices):
                logger.warning(f"Current step {self.current_step} exceeds prices length {len(self.prices)}")
                break
            
            _, reward, _, info = self.step(action)
            
            # Silently fix portfolio value if needed (no logging)
            current_portfolio = self.portfolio_values[self.current_step]
            position_value = 0
            if self.position == 1 and self.shares_held > 0:
                position_value = self.shares_held * self.prices[self.current_step]
            
            # Always recalculate to ensure consistency
            corrected_portfolio = self.balance + position_value
            
            # If there's a significant discrepancy, update the stored value
            if abs(current_portfolio - corrected_portfolio) > 0.01:
                self.portfolio_values[self.current_step] = corrected_portfolio
            
            # Get next state
            if done:
                next_state = state  # Doesn't matter for done states
            else:
                if i+1 < len(states):
                    next_state = states[i+1] 
                else:
                    # Safely handle edge case
                    if self.current_step + 1 < len(self.prices):
                        self.current_step += 1
                        next_state = self._get_observation()
                        self.current_step -= 1
                    else:
                        next_state = state
                
            experiences.append((state, action, reward, next_state, done))
            
            if done:
                break
            
        return experiences

    def _calculate_kelly_position_size(self):
        """
        Calculate position size based on Kelly Criterion
        
        Kelly fraction = (win_rate * (win_amount/loss_amount) - (1 - win_rate)) / (win_amount/loss_amount)
        
        Enforces a minimum position size of 2% of portfolio value.
        """
        # Need at least a few trades to calculate meaningful win rate
        if len(self.trades) < 5:
            return max(0.02, 0.2)  # Default to 20% of portfolio if not enough history, with 2% minimum
            
        # Calculate win rate
        sell_trades = [t for t in self.trades if t['type'] == 'sell']
        if not sell_trades:
            return max(0.02, 0.1)  # Conservative default with 2% minimum
            
        win_trades = [t for t in sell_trades if t.get('profit', 0) > 0]
        loss_trades = [t for t in sell_trades if t.get('profit', 0) <= 0]
        
        # Need at least some wins and losses to calculate meaningful ratio
        if not win_trades or not loss_trades:
            return max(0.02, 0.1)  # Conservative default with 2% minimum
            
        win_rate = len(win_trades) / len(sell_trades)
        
        # Calculate average win and loss
        avg_win = sum(t.get('profit', 0) for t in win_trades) / len(win_trades)
        avg_loss = abs(sum(t.get('profit', 0) for t in loss_trades) / len(loss_trades))
        
        # Avoid division by zero
        if avg_loss < 0.001:
            return max(0.02, 0.1)  # Conservative default with 2% minimum
            
        # Calculate win/loss ratio
        win_loss_ratio = avg_win / avg_loss
        
        # Kelly formula
        kelly_fraction = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        
        # Limit to reasonable range (often advisable to use half or quarter Kelly)
        # Using half-Kelly for more conservative position sizing
        kelly_fraction = 0.5 * kelly_fraction
        
        # Enforce minimum position size of 2%
        kelly_fraction = max(0.02, min(kelly_fraction, 0.5))
        
        return kelly_fraction

    def _calculate_random_position_size(self, min_size=0.05, max_size=0.3):
        """
        Generate a random position size between min_size and max_size
        as percentage of available capital.
        
        Args:
            min_size: Minimum position size as fraction of portfolio (default: 5%)
            max_size: Maximum position size as fraction of portfolio (default: 30%)
        
        Returns:
            Random fraction of portfolio to allocate
        """
        # Generate random percentage between min and max
        return np.random.uniform(min_size, max_size)

    def _calculate_reward(self):
        """Calculate the reward based on portfolio performance and risk metrics"""
        # Calculate PnL, volatility, and Sharpe ratio components
        minute_pnl = self.current_portfolio_value - self.previous_portfolio_value
        
        # Use our improved Sharpe ratio calculation that uses daily returns
        sharpe_ratio = self._calculate_sharpe_ratio()
        
        # Scale the components appropriately
        pnl_reward = minute_pnl * self.pnl_reward_scale
        sharpe_reward = sharpe_ratio * self.sharpe_reward_scale

        # Combine the reward components
        reward = pnl_reward + sharpe_reward
        
        # Transaction cost penalty for trading frequently
        if self.last_action != self.current_action and self.step_count > 1:
            transaction_cost = self.current_portfolio_value * self.transaction_cost_pct
            # Apply a penalty for transaction costs
            transaction_penalty = -transaction_cost * self.transaction_penalty_scale  
            reward += transaction_penalty
        
        # Penalty for holding overnight to discourage it (if applicable)
        current_minute = self.step_count % self.PERIODS_PER_DAY
        if current_minute == 0 and abs(self.position) > 0.1:  # End of day check
            overnight_penalty = -abs(self.position) * self.overnight_penalty_scale
            reward += overnight_penalty
        
        # Apply an additional stability term based on smoothness of returns
        if len(self.daily_returns) > 5:
            recent_volatility = np.std(self.daily_returns[-5:])
            stability_reward = -recent_volatility * self.stability_scale
            reward += stability_reward
                
        # Apply bounds to avoid extreme rewards
        reward = max(min(reward, self.max_reward), self.min_reward)
        
        return reward

class FastDQNAgent:
    """Optimized Deep Q-Network agent for trading"""
    
    def __init__(self, state_size, action_size, model_dir="models", network_type="simple", memory_buffer_size=10000, feature_names=None):
        """Initialize optimized DQN agent with experience replay
        
        Args:
            state_size: Dimension of each state
            action_size: Dimension of each action
            model_dir: Directory to save models
            network_type: Type of neural network architecture to use 
                         ('simple', 'deep', 'lstm', 'stateful_lstm', 'dueling')
        """
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=memory_buffer_size)
        self.gamma = 0.97  # Discount factor for future rewards
        self.epsilon = 1.0  # Exploration rate
        self.epsilon_min = 0.05  # Increased from 0.01 to leave some exploration in
        self.epsilon_decay = 0.995  # Decay rate for exploration prob
        self.learning_rate = 0.001  # Learning rate for optimizer
        self.target_update_freq = 1000  # Update target network every N training steps (not episodes)
        self.training_step_count = 0    # Track actual training steps for target updates
        self.network_type = network_type
        self.feature_names = feature_names  # Optional feature names for importance analysis
        self.batch_size = 32  # Default batch size needed for stateful LSTM
        self.lstm_states = None  # For stateful LSTM, will store lstm states
        
        # Add loss tracking
        self.loss_history = []
        self.recent_losses = deque(maxlen=100)  # Track recent losses for moving average
        
        # Use model directory for saving
        self.model_dir = os.path.join(os.getcwd(), model_dir)
        os.makedirs(self.model_dir, exist_ok=True)
        
        # Support various network architectures
        self.model = self._build_model()
        self.target_model = self._build_model()
        # Ensure target model has same weights as model
        self.update_target_model()
        
    def _build_model(self):
        """Build appropriate neural network based on selected architecture"""
        logger.info(f"Building model with {self.network_type} architecture")
        
        if self.network_type == "simple":
            return self._build_simple_model()
        elif self.network_type == "deep":
            return self._build_deep_model()
        elif self.network_type == "lstm":
            return self._build_lstm_model()
        elif self.network_type == "stateful_lstm":
            return self._build_stateful_lstm_model()
        elif self.network_type == "stacked_lstm":
            return self._build_stacked_lstm_model()
        elif self.network_type == "lstm_attention":
            return self._build_lstm_attention_model()
        elif self.network_type == "bidirectional_lstm":
            return self._build_bidirectional_lstm_model()
        elif self.network_type == "dueling":
            return self._build_dueling_model()
        else:
            logger.warning(f"Unknown network type: {self.network_type}, falling back to simple model")
            return self._build_simple_model()
    
    def _build_simple_model(self):
        """Simple single hidden layer model"""
        model = tf.keras.Sequential([
            tf.keras.layers.Dense(64, input_dim=self.state_size, activation='relu'),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(self.action_size, activation='linear')
        ])
        
        # Use legacy optimizer for mixed precision compatibility
        try:
            optimizer = tf.keras.optimizers.legacy.Adam(
                learning_rate=self.learning_rate,
                clipnorm=0.5  # Add gradient clipping to prevent explosions
            )
        except:
            optimizer = tf.keras.optimizers.Adam(
                learning_rate=self.learning_rate,
                clipnorm=0.5  # Add gradient clipping to prevent explosions
            )
            
        model.compile(
            loss='mse', 
            optimizer=optimizer,
            metrics=None  # Avoid unnecessary metrics for speed
        )
        return model
    
    def _build_deep_model(self):
        """Deeper network with multiple hidden layers for handling high-dimensional feature spaces"""
        model = tf.keras.Sequential([
            # First layer - expand to capture high-dimensional feature space
            tf.keras.layers.Dense(768, input_dim=self.state_size, activation='relu'),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.Dropout(0.3),
            
            # Second layer
            tf.keras.layers.Dense(512, activation='relu'),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.Dropout(0.3),
            
            # Third layer
            tf.keras.layers.Dense(384, activation='relu'),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.Dropout(0.25),
            
            # Fourth layer
            tf.keras.layers.Dense(256, activation='relu'),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.Dropout(0.25),
            
            # Fifth layer
            tf.keras.layers.Dense(192, activation='relu'),
            tf.keras.layers.Dropout(0.2),
            
            # Sixth layer
            tf.keras.layers.Dense(128, activation='relu'),
            tf.keras.layers.Dropout(0.2),
            
            # Seventh layer
            tf.keras.layers.Dense(96, activation='relu'),
            
            # Eighth layer
            tf.keras.layers.Dense(64, activation='relu'),
            
            # Ninth layer
            tf.keras.layers.Dense(32, activation='relu'),
            
            # Output layer
            tf.keras.layers.Dense(self.action_size, activation='linear')
        ])
        
        # Use legacy optimizer for mixed precision compatibility
        try:
            optimizer = tf.keras.optimizers.legacy.Adam(
                learning_rate=self.learning_rate,
                clipnorm=0.5  # Add gradient clipping to prevent explosions
            )
        except:
            optimizer = tf.keras.optimizers.Adam(
                learning_rate=self.learning_rate,
                clipnorm=0.5  # Add gradient clipping to prevent explosions
            )
            
        model.compile(
            loss='mse', 
            optimizer=optimizer,
            metrics=None  # Avoid unnecessary metrics for speed
        )
        
        # Calculate and print model parameter count for information
        total_params = model.count_params()
        logger.info(f"Built deep model with {total_params:,} parameters")
        
        return model
    
    def _build_lstm_model(self):
        """LSTM-based network for temporal pattern recognition"""
        # For LSTM, we expect sequences: (batch_size, sequence_length, features)
        # The environment will provide sequences of observations
        sequence_length = 10  # Must match environment sequence_length
        feature_size = self.state_size  # This is the feature size per timestep
        
        input_layer = tf.keras.layers.Input(shape=(sequence_length, feature_size))
        lstm_layer = tf.keras.layers.LSTM(64, return_sequences=False)(input_layer)
        dropout = tf.keras.layers.Dropout(0.2)(lstm_layer)
        output = tf.keras.layers.Dense(self.action_size, activation='linear')(dropout)
        
        model = tf.keras.Model(inputs=input_layer, outputs=output)
        
        # Use legacy optimizer for mixed precision compatibility
        try:
            optimizer = tf.keras.optimizers.legacy.Adam(learning_rate=self.learning_rate)
        except:
            optimizer = tf.keras.optimizers.Adam(learning_rate=self.learning_rate)
            
        model.compile(
            loss='mse', 
            optimizer=optimizer,
            metrics=None  # Avoid unnecessary metrics for speed
        )
        return model
    
    def _build_stacked_lstm_model(self):
        """Stacked LSTM model with multiple LSTM layers for deeper temporal pattern recognition"""
        sequence_length = 10  # Must match environment sequence_length
        feature_size = self.state_size  # This is the feature size per timestep
        
        input_layer = tf.keras.layers.Input(shape=(sequence_length, feature_size))
        
        # First LSTM layer with return sequences to allow stacking
        lstm1 = tf.keras.layers.LSTM(128, return_sequences=True)(input_layer)
        dropout1 = tf.keras.layers.Dropout(0.2)(lstm1)
        
        # Second LSTM layer
        lstm2 = tf.keras.layers.LSTM(64)(dropout1)
        dropout2 = tf.keras.layers.Dropout(0.2)(lstm2)
        
        # Dense layers for action values
        dense1 = tf.keras.layers.Dense(64, activation='relu')(dropout2)
        dropout3 = tf.keras.layers.Dropout(0.2)(dense1)
        
        # Output layer
        output = tf.keras.layers.Dense(self.action_size, activation='linear')(dropout3)
        
        model = tf.keras.Model(inputs=input_layer, outputs=output)
        
        # Use legacy optimizer for mixed precision compatibility
        try:
            optimizer = tf.keras.optimizers.legacy.Adam(learning_rate=self.learning_rate)
        except:
            optimizer = tf.keras.optimizers.Adam(learning_rate=self.learning_rate)
            
        model.compile(
            loss='mse', 
            optimizer=optimizer,
            metrics=None  # Avoid unnecessary metrics for speed
        )
        return model
    
    def _build_lstm_attention_model(self):
        """BEEFED UP LSTM model with sophisticated attention mechanism for maximum temporal pattern recognition"""
        sequence_length = 10  # Must match environment sequence_length
        feature_size = self.state_size  # This is the feature size per timestep
        
        input_layer = tf.keras.layers.Input(shape=(sequence_length, feature_size))
        
        # STACKED LSTM LAYERS - Progressive feature extraction
        # First LSTM layer - capture basic patterns (FIXED: removed recurrent_dropout for cuDNN)
        lstm1 = tf.keras.layers.LSTM(256, return_sequences=True, dropout=0.1)(input_layer)
        lstm1 = tf.keras.layers.BatchNormalization()(lstm1)
        
        # Second LSTM layer - capture complex patterns (FIXED: removed recurrent_dropout for cuDNN)
        lstm2 = tf.keras.layers.LSTM(192, return_sequences=True, dropout=0.1)(lstm1)
        lstm2 = tf.keras.layers.BatchNormalization()(lstm2)
        
        # Third LSTM layer - capture high-level patterns (FIXED: removed recurrent_dropout for cuDNN)
        lstm3 = tf.keras.layers.LSTM(128, return_sequences=True, dropout=0.1)(lstm2)
        lstm3 = tf.keras.layers.BatchNormalization()(lstm3)
        
        # MULTI-HEAD ATTENTION MECHANISM - Focus on different aspects
        # Attention Head 1 - Price movement patterns
        attention1 = tf.keras.layers.Dense(64, activation='tanh', name='attention_head_1')(lstm3)
        attention1 = tf.keras.layers.Dense(1, activation='linear')(attention1)
        attention1 = tf.keras.layers.Flatten()(attention1)
        attention1_weights = tf.keras.layers.Activation('softmax')(attention1)
        
        # Attention Head 2 - Volume/momentum patterns  
        attention2 = tf.keras.layers.Dense(64, activation='tanh', name='attention_head_2')(lstm3)
        attention2 = tf.keras.layers.Dense(1, activation='linear')(attention2)
        attention2 = tf.keras.layers.Flatten()(attention2)
        attention2_weights = tf.keras.layers.Activation('softmax')(attention2)
        
        # Attention Head 3 - Technical indicator patterns
        attention3 = tf.keras.layers.Dense(64, activation='tanh', name='attention_head_3')(lstm3)
        attention3 = tf.keras.layers.Dense(1, activation='linear')(attention3)
        attention3 = tf.keras.layers.Flatten()(attention3)
        attention3_weights = tf.keras.layers.Activation('softmax')(attention3)
        
        # Apply attention weights to LSTM output for each head
        attention1_weights = tf.keras.layers.RepeatVector(128)(attention1_weights)
        attention1_weights = tf.keras.layers.Permute([2, 1])(attention1_weights)
        attended1 = tf.keras.layers.Multiply()([lstm3, attention1_weights])
        attended1 = tf.keras.layers.Lambda(lambda x: tf.keras.backend.sum(x, axis=1))(attended1)
        
        attention2_weights = tf.keras.layers.RepeatVector(128)(attention2_weights)
        attention2_weights = tf.keras.layers.Permute([2, 1])(attention2_weights)
        attended2 = tf.keras.layers.Multiply()([lstm3, attention2_weights])
        attended2 = tf.keras.layers.Lambda(lambda x: tf.keras.backend.sum(x, axis=1))(attended2)
        
        attention3_weights = tf.keras.layers.RepeatVector(128)(attention3_weights)
        attention3_weights = tf.keras.layers.Permute([2, 1])(attention3_weights)
        attended3 = tf.keras.layers.Multiply()([lstm3, attention3_weights])
        attended3 = tf.keras.layers.Lambda(lambda x: tf.keras.backend.sum(x, axis=1))(attended3)
        
        # CONCATENATE ALL ATTENTION HEADS - Rich representation
        merged_attention = tf.keras.layers.Concatenate()([attended1, attended2, attended3])
        
        # DEEP DENSE PROCESSING - Extract trading insights
        # First dense block
        dense1 = tf.keras.layers.Dense(256, activation='relu')(merged_attention)
        dense1 = tf.keras.layers.BatchNormalization()(dense1)
        dense1 = tf.keras.layers.Dropout(0.25)(dense1)
        
        # Second dense block
        dense2 = tf.keras.layers.Dense(192, activation='relu')(dense1)
        dense2 = tf.keras.layers.BatchNormalization()(dense2)
        dense2 = tf.keras.layers.Dropout(0.25)(dense2)
        
        # Third dense block
        dense3 = tf.keras.layers.Dense(128, activation='relu')(dense2)
        dense3 = tf.keras.layers.BatchNormalization()(dense3)
        dense3 = tf.keras.layers.Dropout(0.2)(dense3)
        
        # Fourth dense block
        dense4 = tf.keras.layers.Dense(96, activation='relu')(dense3)
        dense4 = tf.keras.layers.Dropout(0.2)(dense4)
        
        # Fifth dense block
        dense5 = tf.keras.layers.Dense(64, activation='relu')(dense4)
        dense5 = tf.keras.layers.Dropout(0.15)(dense5)
        
        # Final decision layer
        dense6 = tf.keras.layers.Dense(32, activation='relu')(dense5)
        
        # Output layer
        output = tf.keras.layers.Dense(self.action_size, activation='linear', name='action_output')(dense6)
        
        model = tf.keras.Model(inputs=input_layer, outputs=output)
        
        # Use legacy optimizer for mixed precision compatibility
        try:
            optimizer = tf.keras.optimizers.legacy.Adam(
                learning_rate=self.learning_rate * 0.8,  # Slightly lower LR for deeper model
                clipnorm=0.5  # Gradient clipping for stability
            )
        except:
            optimizer = tf.keras.optimizers.Adam(
                learning_rate=self.learning_rate * 0.8,  # Slightly lower LR for deeper model
                clipnorm=0.5  # Gradient clipping for stability
            )
            
        model.compile(
            loss='mse', 
            optimizer=optimizer,
            metrics=None  # Avoid unnecessary metrics for speed
        )
        
        # Calculate and log parameter count
        total_params = model.count_params()
        logger.info(f"Built BEEFED UP LSTM Attention model with {total_params:,} parameters")
        logger.info("Features: 3x Stacked LSTMs + 3x Multi-Head Attention + 6x Dense Layers")
        
        # Test cuDNN optimization
        logger.info("🔧 LSTM OPTIMIZATION STATUS:")
        logger.info("   - Removed recurrent_dropout to enable cuDNN kernels")
        logger.info("   - Expected: cuDNN-optimized LSTM layers (much faster)")
        logger.info("   - If you still see cuDNN warnings, check TensorFlow/CUDA versions")
        
        # Hardware optimization warnings
        if total_params > 10_000_000:
            logger.warning("⚠️  LARGE MODEL DETECTED! Recommended optimizations:")
            logger.warning("   - Use batch_size=16 or batch_size=8 (instead of 32)")
            logger.warning("   - Enable mixed precision training")
            logger.warning("   - Monitor GPU memory usage closely")
        elif total_params > 5_000_000:
            logger.info("💡 MEDIUM-LARGE MODEL: Consider batch_size=16 for optimal performance")
        
        return model
    
    def _build_bidirectional_lstm_model(self):
        """Bidirectional LSTM model to capture patterns from both past and future context"""
        sequence_length = 10  # Must match environment sequence_length
        feature_size = self.state_size  # This is the feature size per timestep
        
        input_layer = tf.keras.layers.Input(shape=(sequence_length, feature_size))
        
        # Bidirectional LSTM
        bilstm = tf.keras.layers.Bidirectional(
            tf.keras.layers.LSTM(64, return_sequences=False)
        )(input_layer)
        
        # Dense processing
        dropout = tf.keras.layers.Dropout(0.2)(bilstm)
        dense = tf.keras.layers.Dense(64, activation='relu')(dropout)
        dropout2 = tf.keras.layers.Dropout(0.2)(dense)
        
        # Output layer
        output = tf.keras.layers.Dense(self.action_size, activation='linear')(dropout2)
        
        model = tf.keras.Model(inputs=input_layer, outputs=output)
        
        # Use legacy optimizer for mixed precision compatibility
        try:
            optimizer = tf.keras.optimizers.legacy.Adam(learning_rate=self.learning_rate)
        except:
            optimizer = tf.keras.optimizers.Adam(learning_rate=self.learning_rate)
            
        model.compile(
            loss='mse', 
            optimizer=optimizer,
            metrics=None  # Avoid unnecessary metrics for speed
        )
        return model
    
    def _build_dueling_model(self):
        """Dueling DQN architecture with separate value and advantage streams"""
        input_layer = tf.keras.layers.Input(shape=(self.state_size,))
        dense1 = tf.keras.layers.Dense(64, activation='relu')(input_layer)
        dropout = tf.keras.layers.Dropout(0.2)(dense1)
        
        # Value stream - estimates state value
        value_stream = tf.keras.layers.Dense(64, activation='relu')(dropout)
        value = tf.keras.layers.Dense(1)(value_stream)
        
        # Advantage stream - estimates advantage of each action
        advantage_stream = tf.keras.layers.Dense(64, activation='relu')(dropout)
        advantage = tf.keras.layers.Dense(self.action_size)(advantage_stream)
        
        # Combine value and advantage streams
        # Subtract mean advantage to ensure identifiability
        outputs = value + (advantage - tf.reduce_mean(advantage, axis=1, keepdims=True))
        
        model = tf.keras.Model(inputs=input_layer, outputs=outputs)
        
        # Use legacy optimizer for mixed precision compatibility
        try:
            optimizer = tf.keras.optimizers.legacy.Adam(learning_rate=self.learning_rate)
        except:
            optimizer = tf.keras.optimizers.Adam(learning_rate=self.learning_rate)
            
        model.compile(
            loss='mse', 
            optimizer=optimizer,
            metrics=None  # Avoid unnecessary metrics for speed
        )
        return model
        
    def _build_stateful_lstm_model(self):
        """Stateful LSTM model that maintains state across batches"""
        # Need to use a fixed batch size for stateful LSTM
        batch_input_shape = (self.batch_size, 1, self.state_size)
        
        # Create Sequential model for stateful LSTM
        model = tf.keras.Sequential([
            # Stateful LSTM layer - the key is stateful=True and batch_input_shape
            tf.keras.layers.LSTM(
                128, 
                stateful=True,
                return_sequences=False,
                batch_input_shape=batch_input_shape
            ),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.Dense(64, activation='relu'),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(self.action_size, activation='linear')
        ])
        
        # Use legacy optimizer for mixed precision compatibility
        try:
            optimizer = tf.keras.optimizers.legacy.Adam(learning_rate=self.learning_rate)
        except:
            optimizer = tf.keras.optimizers.Adam(learning_rate=self.learning_rate)
            
        model.compile(
            loss='mse', 
            optimizer=optimizer,
            metrics=None  # Avoid unnecessary metrics for speed
        )
        
        logger.info(f"Built stateful LSTM model with batch size {self.batch_size}")
        logger.info(f"Model summary: {model.input_shape} -> {model.output_shape}")
        
        return model
    
    def update_target_model(self):
        """Update target model with weights from main model"""
        self.target_model.set_weights(self.model.get_weights())
    
    def soft_update_target_model(self, tau=0.001):
        """
        Soft update target network using Polyak averaging
        target = tau * main + (1-tau) * target
        
        Args:
            tau: Update rate (0.001 = very slow, 1.0 = full copy)
        """
        main_weights = self.model.get_weights()
        target_weights = self.target_model.get_weights()
        
        for i in range(len(main_weights)):
            target_weights[i] = tau * main_weights[i] + (1 - tau) * target_weights[i]
        
        self.target_model.set_weights(target_weights)
        
    def remember(self, state, action, reward, next_state, done):
        """Store experience in replay memory"""
        self.memory.append((state, action, reward, next_state, done))
    
    def batch_remember(self, experiences):
        """Store multiple experiences in replay memory at once"""
        self.memory.extend(experiences)
        
    def act(self, state, training=True):
        """Choose action based on epsilon-greedy policy"""
        if training and np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        
        try:
            # Handle different input shapes for different network types
            if self.network_type in ["lstm", "stacked_lstm", "lstm_attention", "bidirectional_lstm"]:
                # For sequence-based LSTM models, state should be (sequence_length, features)
                if len(state.shape) == 2:
                    # State is already a sequence, add batch dimension
                    state = np.expand_dims(state, axis=0)  # (1, sequence_length, features)
                elif len(state.shape) == 1:
                    # Single observation, need to create sequence
                    # This shouldn't happen with proper environment setup, but handle it
                    state = np.expand_dims(state, axis=0)  # (1, features)
                    state = np.expand_dims(state, axis=0)  # (1, 1, features)
                
                act_values = self.model.predict(state, verbose=0)
                
            elif self.network_type == "stateful_lstm":
                # Special handling for stateful LSTM
                if len(state.shape) == 2:
                    # Sequence input, add batch dimension
                    state = np.expand_dims(state, axis=0)
                elif len(state.shape) == 1:
                    # Single observation, reshape for stateful LSTM
                    state = np.expand_dims(state, axis=0)  # (1, features)
                    state = np.expand_dims(state, axis=1)  # (1, 1, features)
                
                # Need to pad to batch_size for stateful LSTM
                if state.shape[0] < self.batch_size:
                    # Create a temporary padded batch
                    padded_batch = np.zeros((self.batch_size, state.shape[1], state.shape[2]))
                    padded_batch[0] = state[0]  # Use the actual state as first example
                    act_values = self.model.predict(padded_batch, verbose=0)
                    # Only return prediction for the actual state
                    return np.argmax(act_values[0])
                else:
                    act_values = self.model.predict(state, verbose=0)
                    
            else:
                # For non-LSTM models (simple, deep, dueling)
                if len(state.shape) == 2:
                    # If we get a sequence, just use the last observation
                    state = state[-1]  # Take last observation from sequence
                if len(state.shape) == 1:
                    state = np.expand_dims(state, axis=0)  # Add batch dimension
                
                act_values = self.model.predict(state, verbose=0)
                
        except Exception as e:
            logger.error(f"Error during model prediction: {e}")
            # Fallback to random action
            return random.randrange(self.action_size)
            
        return np.argmax(act_values[0])
    
    def batch_act(self, states, training=True):
        """Choose actions for multiple states at once"""
        
        # FIXED: Ensure LSTM models always get proper sequences
        # Force consistent sequence handling based on network type
        if self.network_type in ["lstm", "stacked_lstm", "lstm_attention", "bidirectional_lstm"]:
            # LSTM models MUST receive 3D sequences: (batch_size, sequence_length, features)
            if len(states.shape) == 2:
                # If we get 2D states, this means each state is already a sequence
                # Add batch dimension: (sequence_length, features) -> (1, sequence_length, features)
                # But we have multiple states, so this is wrong - we need to fix the environment
                logger.error(f"🚨 CRITICAL: LSTM got 2D states {states.shape} - environment not providing sequences correctly!")
                # Emergency fix: treat each row as a separate time step, create single batch
                states_to_predict = np.expand_dims(states, axis=0)  # (1, batch_size, features)
            elif len(states.shape) == 3:
                # Correct: (batch_size, sequence_length, features)
                states_to_predict = states
            elif len(states.shape) == 1:
                # Single state, treat as single sequence with one timestep
                logger.error(f"🚨 CRITICAL: LSTM got 1D state {states.shape} - major sequence handling error!")
                states_to_predict = states.reshape(1, 1, -1)  # (1, 1, features)
            else:
                raise ValueError(f"LSTM received unexpected state shape: {states.shape}")
        else:
            # Non-LSTM models need 2D: (batch_size, features) 
            if len(states.shape) == 3:
                # Environment gave us sequences, extract last observation from each
                states_to_predict = states[:, -1, :]  # (batch_size, features)
                logger.debug(f"Non-LSTM: Extracted last observations from sequences {states.shape} -> {states_to_predict.shape}")
            elif len(states.shape) == 2:
                # Already correct shape for non-LSTM
                states_to_predict = states
            else:
                raise ValueError(f"Non-LSTM received unexpected state shape: {states.shape}")
        
        # Special handling for stateful LSTM which needs fixed batch size
        if self.network_type == "stateful_lstm":
            actions = []
            
            # Generate exploration actions for the entire batch if training
            if training:
                exploration_mask = np.random.random(len(states_to_predict)) <= self.epsilon
                exploration_actions = np.random.randint(0, self.action_size, size=len(states_to_predict))
            
            # Process states in chunks of batch_size
            for i in range(0, len(states_to_predict), self.batch_size):
                chunk = states_to_predict[i:i+self.batch_size]
                chunk_size = len(chunk)
                
                # If chunk is smaller than batch_size, pad it
                if chunk_size < self.batch_size:
                    pad_shape = list(chunk.shape)
                    pad_shape[0] = self.batch_size
                    padded_chunk = np.zeros(pad_shape)
                    padded_chunk[:chunk_size] = chunk
                    chunk = padded_chunk
                
                # For stateful LSTM, reshape to (batch_size, 1, features) - single timestep
                if len(chunk.shape) == 3:
                    # Take last timestep from each sequence
                    chunk = chunk[:, -1:, :]  # (batch_size, 1, features)
                else:
                    # Add timestep dimension
                    chunk = np.expand_dims(chunk, axis=1)  # (batch_size, 1, features)
                
                # Get predictions
                chunk_values = self.model.predict(chunk, verbose=0)
                
                # Take actions for valid states (non-padded)
                valid_count = min(self.batch_size, len(states_to_predict) - i)
                chunk_actions = np.argmax(chunk_values[:valid_count], axis=1)
                
                # Apply exploration if training
                if training:
                    idx_range = slice(i, i + valid_count)
                    chunk_mask = exploration_mask[idx_range]
                    chunk_random_actions = exploration_actions[idx_range]
                    chunk_actions = np.where(chunk_mask, chunk_random_actions, chunk_actions)
                
                actions.extend(chunk_actions)
            
            return np.array(actions)
        
        # For exploration during training
        if training:
            exploration_mask = np.random.random(len(states_to_predict)) <= self.epsilon
            exploration_actions = np.random.randint(0, self.action_size, size=len(states_to_predict))
        else:
            exploration_mask = np.zeros(len(states_to_predict), dtype=bool)
            exploration_actions = np.zeros(len(states_to_predict), dtype=int)
            
        try:
            # Predict actions for all states
            act_values = self.model.predict(states_to_predict, verbose=0)
            non_random_actions = np.argmax(act_values, axis=1)
            
            # Combine random and predicted actions
            actions = np.where(exploration_mask, exploration_actions, non_random_actions)
            return actions
            
        except Exception as e:
            logger.error(f"Error during batch model prediction: {e}")
            logger.error(f"States shape: {states_to_predict.shape}, Network: {self.network_type}")
            # Fallback to random actions
            return np.random.randint(0, self.action_size, size=len(states_to_predict))
    
    def decay_epsilon(self):
        """Decay epsilon once per episode"""
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
            # Ensure we don't go below minimum
            self.epsilon = max(self.epsilon_min, self.epsilon)
            
    def replay(self, batch_size):
        """Optimized training with experiences from replay memory"""
        if len(self.memory) < batch_size:
            return 0  # Return 0 loss when no training happens
            
        # For stateful LSTM, use the fixed batch size from the model
        if self.network_type == "stateful_lstm":
            actual_batch_size = self.batch_size
            if len(self.memory) < actual_batch_size:
                return 0  # Return 0 loss when no training happens
        else:
            actual_batch_size = batch_size
        
        # Sample random batch from memory
        minibatch = random.sample(self.memory, actual_batch_size)
        
        # Extract batches for more efficient prediction
        states = np.array([experience[0] for experience in minibatch])
        actions = np.array([experience[1] for experience in minibatch])
        rewards = np.array([experience[2] for experience in minibatch])
        next_states = np.array([experience[3] for experience in minibatch])
        dones = np.array([experience[4] for experience in minibatch])
        
        # Special handling for stateful LSTM
        if self.network_type == "stateful_lstm":
            # Reshape for LSTM: (batch_size, timesteps, features)
            states_reshaped = np.reshape(states, (actual_batch_size, 1, states.shape[1]))
            next_states_reshaped = np.reshape(next_states, (actual_batch_size, 1, next_states.shape[1]))
            
            # Reset states before prediction
            self.model.reset_states()
            target_vals = self.model.predict(states_reshaped, verbose=0)
            
            # Double DQN logic 
            self.model.reset_states()
            next_q_values = self.model.predict(next_states_reshaped, verbose=0)
            best_actions = np.argmax(next_q_values, axis=1)
            
            # Get target Q-values
            self.target_model.reset_states()
            next_target_vals = self.target_model.predict(next_states_reshaped, verbose=0)
            
            # Update targets for each sample in the batch
            for i in range(actual_batch_size):
                if dones[i]:
                    target_vals[i, actions[i]] = rewards[i]
                else:
                    # Double DQN update using selected action from online network
                    target_vals[i, actions[i]] = rewards[i] + self.gamma * next_target_vals[i, best_actions[i]]
            
            # Add target value clipping to prevent extreme values
            target_vals = np.clip(target_vals, -100.0, 100.0)
            
            # Reshape again and reset states before training
            self.model.reset_states()
            history = self.model.fit(states_reshaped, target_vals, epochs=1, verbose=0, batch_size=actual_batch_size)
            
            # Record loss
            if history.history and 'loss' in history.history:
                current_loss = history.history['loss'][0]
                # Add loss value clipping to prevent infinities
                if not np.isfinite(current_loss):
                    current_loss = 1000.0  # Use a large but finite value instead
                
                self.loss_history.append(current_loss)
                self.recent_losses.append(current_loss)
            
            return current_loss if history.history and 'loss' in history.history else 0
        
        # Handle standard (non-stateful) models
        # Get predictions in batches (more efficient)
        if self.network_type in ["lstm", "stacked_lstm", "lstm_attention", "bidirectional_lstm"]:
            # For LSTM models, use sequences
            if len(states.shape) == 3:
                target_vals = self.model.predict(states, verbose=0)
            else:
                # Expand to sequence format
                states_seq = np.expand_dims(states, axis=1)
                target_vals = self.model.predict(states_seq, verbose=0)
        else:
            # For non-LSTM models
            if len(states.shape) == 3:
                # Use last observation from sequences
                states_single = states[:, -1, :]
                target_vals = self.model.predict(states_single, verbose=0)
            else:
                target_vals = self.model.predict(states, verbose=0)
        
        # FIXED: Handle different network types for prediction with proper sequence management
        if self.network_type in ["lstm", "stacked_lstm", "lstm_attention", "bidirectional_lstm"]:
            # LSTM models MUST receive 3D sequences: (batch_size, sequence_length, features)
            if len(states.shape) == 3:
                # States are already sequences - CORRECT
                states_reshaped = states
                next_states_reshaped = next_states
                logger.debug(f"LSTM replay: Using 3D sequences {states.shape}")
            elif len(states.shape) == 2:
                # CRITICAL: States are individual sequences, need to be stacked into batch
                # Each state is (sequence_length, features), expand to (1, sequence_length, features) each
                # But we have multiple states, so actually each row is a different sequence
                logger.error(f"🚨 LSTM replay got 2D states {states.shape} - sequence handling error!")
                # Emergency fix: expand each state to (1, 1, features) - destroys temporal learning!
                states_reshaped = np.expand_dims(states, axis=1)  # (batch_size, 1, features)
                next_states_reshaped = np.expand_dims(next_states, axis=1)
            else:
                raise ValueError(f"Unexpected state shape for LSTM replay: {states.shape}")
            
            next_q_values = self.model.predict(next_states_reshaped, verbose=0)
            next_target_vals = self.target_model.predict(next_states_reshaped, verbose=0)
        else:
            # Non-LSTM models need 2D: (batch_size, features)
            if len(states.shape) == 3:
                # Environment stored sequences, extract last observation from each
                states_for_prediction = states[:, -1, :]
                next_states_for_prediction = next_states[:, -1, :]
                logger.debug(f"Non-LSTM replay: Extracted last observations from sequences {states.shape} -> {states_for_prediction.shape}")
            elif len(states.shape) == 2:
                # Already correct for non-LSTM
                states_for_prediction = states
                next_states_for_prediction = next_states
            else:
                raise ValueError(f"Unexpected state shape for non-LSTM replay: {states.shape}")
                
            next_q_values = self.model.predict(next_states_for_prediction, verbose=0)
            next_target_vals = self.target_model.predict(next_states_for_prediction, verbose=0)
            
        # For double DQN: use main network to select action, target network to evaluate
        best_actions = np.argmax(next_q_values, axis=1)
        
        # Create targets
        for i in range(actual_batch_size):
            if dones[i]:
                target_vals[i, actions[i]] = rewards[i]
            else:
                # Double DQN update using selected action from online network
                target_vals[i, actions[i]] = rewards[i] + self.gamma * next_target_vals[i, best_actions[i]]
        
        # Add target value clipping to prevent extreme values
        target_vals = np.clip(target_vals, -10.0, 10.0)
        
        # FIXED: Train model with proper state handling for each network type
        if self.network_type in ["lstm", "stacked_lstm", "lstm_attention", "bidirectional_lstm"]:
            # Use the properly reshaped states for LSTM models
            history = self.model.fit(states_reshaped, target_vals, epochs=1, verbose=0, batch_size=actual_batch_size)
            logger.debug(f"LSTM training: states_reshaped {states_reshaped.shape} -> targets {target_vals.shape}")
        else:
            # Use properly handled states for non-LSTM models
            if len(states.shape) == 3:
                # Extract last observations from sequences
                training_states = states[:, -1, :]
                logger.debug(f"Non-LSTM training: extracted {training_states.shape} from sequences {states.shape}")
            elif len(states.shape) == 2:
                # Already correct shape
                training_states = states
                logger.debug(f"Non-LSTM training: using states {training_states.shape}")
            else:
                raise ValueError(f"Unexpected states shape for non-LSTM training: {states.shape}")
            
            history = self.model.fit(training_states, target_vals, epochs=1, verbose=0, batch_size=actual_batch_size)
        
        # Record loss and update target network based on training steps
        if history.history and 'loss' in history.history:
            current_loss = history.history['loss'][0]
            # Add loss value clipping to prevent infinities
            if not np.isfinite(current_loss):
                current_loss = 10.0  # Use a smaller finite value to prevent explosion
            else:
                current_loss = min(current_loss, 50.0)  # Cap finite losses too
            
            self.loss_history.append(current_loss)
            self.recent_losses.append(current_loss)
            
            # Increment training step counter and update target network if needed
            self.training_step_count += 1
            if self.training_step_count % self.target_update_freq == 0:
                self.update_target_model()
                logger.debug(f"Updated target network at training step {self.training_step_count}")
            
            return current_loss
        
        return 0  # Default return if no loss is available
    
    def save(self, name=None):
        """Save model to disk"""
        if name is None:
            name = f"fast_dqn_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        model_path = os.path.join(self.model_dir, f"{name}.h5")
        self.model.save(model_path)
        logger.info(f"Model saved to {model_path}")
        return model_path
    
    def load(self, path):
        """Load model from disk"""
        self.model = tf.keras.models.load_model(path)
        self.target_model = tf.keras.models.load_model(path)
        logger.info(f"Model loaded from {path}")
    
    def reset_lstm_states(self):
        """Reset the states of stateful LSTM layers"""
        if self.network_type == "stateful_lstm":
            logger.debug("Resetting LSTM states")
            self.model.reset_states()
            self.target_model.reset_states()

def train_fast_rl_agent(
    price_data, 
    feature_data, 
    episodes=100, 
    batch_size=256,  # Larger batch size for better GPU utilization
    initial_balance=10000.0,
    model_name=None,
    network_type="simple",  # Default to simple network
    risk_free_rate=0.0,
    sharpe_lookback=30,
    sharpe_weight=2.0,
    position_sizing="fixed",
    max_position_pct=0.20,
    resolution="1H",  # Add resolution parameter with default of 5m
    reward_type="combined",  # Options: "combined", "sharpe_only", "simplified_profit_sharpe", "profit_focused" (uses RewardCalculator)
    slippage_pct=0.0015,  # Add slippage parameter
    existing_agent=None,  # Add existing agent parameter
    memory_buffer_size=10000,  # Add memory buffer size parameter
    enable_memory_optimization=False,  # Add memory optimization parameter
    feature_names=None  # Add feature names for importance analysis
):
    """
    Train optimized RL agent on historical price data
    
    Args:
        price_data: Array of historical prices
        feature_data: Array of features for state representation
        episodes: Number of training episodes
        batch_size: Batch size for training
        initial_balance: Starting cash balance
        model_name: Name for saved model
        network_type: Type of neural network architecture to use ('simple', 'deep', 
                    'lstm', 'stateful_lstm', 'dueling')
        risk_free_rate: Annual risk-free rate for Sharpe calculation
        sharpe_lookback: Number of steps to use for Sharpe calculation
        sharpe_weight: Weight of Sharpe ratio in reward function
        position_sizing: Strategy for position sizing ('fixed', 'kelly', or 'random')
        max_position_pct: Maximum position size as percentage of portfolio
        resolution: Time resolution of the data (e.g., "1m", "5m", "15m", "1h", "4h", "1d")
        reward_type: Type of reward function to use ('combined', 'sharpe_only')
        slippage_pct: Percentage of slippage to apply to trades (0.0015 = 15 basis points)
        existing_agent: Existing agent to continue training (if None, create a new one)
        memory_buffer_size: Maximum size of experience replay buffer
        enable_memory_optimization: Whether to enable aggressive memory optimization
        feature_names: List of names for features (for importance analysis)
        
    Returns:
        Trained agent and final environment state
    """
    logger.info(f"Starting fast RL training for {episodes} episodes with {network_type} network")
    logger.info(f"Position sizing: {position_sizing}, Max position: {max_position_pct*100:.1f}%")
    print(f"\n{'='*80}\nStarting Fast RL training with {len(price_data)} data points\n{'='*80}")
    print(f"Position sizing strategy: {position_sizing}")
    print(f"Using resolution: {resolution}")
    print(f"Reward function: {reward_type}")
    print(f"Slippage: {slippage_pct*100:.3f}%")
    print(f"Memory optimization: {'Enabled' if enable_memory_optimization else 'Disabled'}")
    print(f"Memory buffer size: {memory_buffer_size} experiences")
    print(f"Feature importance analysis: {'Enabled' if feature_names is not None else 'Disabled'}")
    
    # Create optimized environment with Sharpe ratio parameters
    env = FastTradingEnvironment(
        price_data, 
        feature_data, 
        initial_balance=initial_balance,
        risk_free_rate=risk_free_rate,
        sharpe_lookback=sharpe_lookback,
        sharpe_weight=sharpe_weight,
        position_sizing=position_sizing,
        max_position_pct=max_position_pct,
        resolution=resolution,  # Pass resolution to environment
        reward_type=reward_type,  # Pass reward type
        slippage_pct=slippage_pct  # Pass slippage
    )
    state_size = feature_data.shape[1] + 1  # features + position state
    action_size = 3  # 0=hold, 1=buy with fixed size, 2=sell all
    
    # Create a new agent or use the existing one
    if existing_agent is None:
        agent = FastDQNAgent(state_size, action_size, network_type=network_type, 
                            memory_buffer_size=memory_buffer_size,
                            feature_names=feature_names)
    else:
        logger.info("Using existing agent for continued training")
        agent = existing_agent
        # Set feature names if provided
        if feature_names is not None:
            agent.feature_names = feature_names
        # Reset epsilon to allow more exploration
        if agent.epsilon < 0.1:
            agent.epsilon = max(0.1, agent.epsilon * 2)
            logger.info(f"Reset agent epsilon to {agent.epsilon:.4f} for continued training")
    
    # Custom epsilon settings for exploration-exploitation schedule
    exploration_phase = int(episodes * 0.3)  # First 30% of episodes are for exploration (increased from 20%)
    initial_epsilon = 1.0  # Pure random exploration (increased from 0.95)
    agent.epsilon = initial_epsilon  # Ensure we start with pure random
    agent.epsilon_min = 0.05  # Increased from 0.01 to leave some exploration in
    
    # Determine if this is continued training based on initial epsilon
    is_continued_training = initial_epsilon < 0.5  # Lower epsilon values suggest continued training
    
    # Adjust epsilon schedule based on whether this is continued training
    if is_continued_training:
        logger.info(f"Detected continued training (initial epsilon: {initial_epsilon:.4f}). Using conservative exploration.")
        # For continued training - much more exploitation, less exploration
        exploration_phase = max(3, int(episodes * 0.1))  # Shorter exploration phase 
        accelerated_decay_rate = agent.epsilon_decay * 0.8  # More aggressive decay
    else:
        logger.info(f"Starting new training (initial epsilon: {initial_epsilon:.4f}). Using standard exploration.")
        # Default for new training
        exploration_phase = int(episodes * 0.3)  # Keep at 30%
        accelerated_decay_rate = agent.epsilon_decay * 0.85  # More gradual decay (changed from 0.7)
    
    # Override agent's epsilon decay method with our custom schedule
    def custom_epsilon_decay(episode_num):
        if episode_num < exploration_phase:
            # During exploration phase: maintain high epsilon (pure random)
            agent.epsilon = initial_epsilon  # Keep at 1.0 for full exploration
            logger.debug(f"Exploration phase: epsilon = {agent.epsilon:.4f}")
        else:
            # Exploitation phase: more gradual decay
            agent.epsilon = max(agent.epsilon * accelerated_decay_rate, agent.epsilon_min)
            logger.debug(f"Exploitation phase: epsilon = {agent.epsilon:.4f}")
    
    # Track performance
    rewards_history = []
    portfolio_history = []
    loss_history = []
    avg_loss_history = []
    
    # Set batch size for environment steps (process multiple steps at once)
    env_batch_size = min(64, len(price_data) // 16)
    
    # Create primary progress bar for episodes with forced tty for WSL compatibility
    episode_bar = tqdm(
        range(episodes), 
        desc="Training Episodes", 
        position=0, 
        leave=True,
        ncols=100,
        bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
    )
    
    # Display initial stats
    print(f"Training will process {len(price_data)} data points per episode in batches of {env_batch_size}")
    print(f"State size: {state_size}, Action size: {action_size}")
    print(f"Action mapping: 0=hold, 1=buy (5% of portfolio), 2=sell (100% of position)")
    print(f"Starting epsilon: {agent.epsilon}")
    print(f"Custom epsilon schedule: maintain high for first {exploration_phase} episodes, then accelerated decay")
    
    # Track best model
    best_portfolio_value = 0
    best_agent = None
    
    # Training loop with progress bar and timeout protection
    for episode in episode_bar:
        # Reset environment for new episode
        state = env.reset()
        done = False
        total_reward = 0  # Reset total reward for this episode
        step_count = 0
        
        # Reset LSTM states at the beginning of each episode for stateful models
        if agent.network_type == "stateful_lstm":
            agent.reset_lstm_states()
        
        # Create a progress bar for batches within this episode
        num_batches = (len(price_data) + env_batch_size - 1) // env_batch_size
        batch_bar = tqdm(
            total=num_batches, 
            desc=f"Episode {episode+1}/{episodes}",
            position=1, 
            leave=False,
            ncols=100,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]'
        )
        
        # Episode timer to detect and break stuck episodes
        episode_start_time = time.time()
        max_episode_time = 600  # 10 minutes maximum per episode
        
        # Process environment in batches to reduce TF calls
        batch_count = 0
        
        while not done:
            # Check for timeout
            if time.time() - episode_start_time > max_episode_time:
                logger.warning(f"Episode {episode+1} timed out after {time.time() - episode_start_time:.1f} seconds. Breaking out.")
                break
                
            # Process a batch of steps at once
            experiences = env.run_batch_simulation(agent, env_batch_size, training=True)
            
            # Check if experiences is empty (safeguard against index errors)
            if not experiences:
                logger.warning("Empty experiences returned from batch simulation, breaking loop")
                break
                
            # Store all experiences
            agent.batch_remember(experiences)
            
            # Update progress
            batch_count += 1
            batch_bar.update(1)
            
            # Extract info from last experience (with safety check)
            if experiences:
                _, _, batch_rewards, _, done = experiences[-1]
                # Sum the rewards from this batch with safety check for inf/nan
                batch_sum = sum(min(max(exp[2], -10), 10) for exp in experiences)  # Clamp all reward values
                if np.isfinite(batch_sum):  # Check for inf/nan
                    total_reward += batch_sum
                else:
                    logger.warning(f"Non-finite reward detected: {batch_sum}. Using zero instead.")
                    batch_sum = 0
                
            step_count += len(experiences)
            
            # Check if we have enough samples to train
            if len(agent.memory) >= batch_size:
                batch_loss = agent.replay(batch_size)
                # Track the loss
                if batch_loss > 0:
                    loss_history.append(batch_loss)
            
            # Update state for next batch
            if not done:
                state = env._get_observation()
                
            # Extra timeout check - break if batch processing is taking too long
            if time.time() - episode_start_time > max_episode_time:
                logger.warning(f"Episode {episode+1} processing timeout during batch. Breaking loop.")
                break
            
            # Memory optimization - periodically clear large arrays in environment
            if enable_memory_optimization and batch_count % 10 == 0:
                # Clear old daily returns (keep only recent ones)
                if len(env.daily_returns) > env.sharpe_lookback * 2:
                    env.daily_returns = env.daily_returns[-env.sharpe_lookback*2:]
                
                # Limit trade history size
                if len(env.trades) > 1000:
                    env.trades = env.trades[-1000:]
        
        # Close the batch progress bar
        batch_bar.close()
        
        # Target network updates are now handled in the replay() method based on training steps
        # This ensures consistent update frequency regardless of episode length
            
        # Apply our custom epsilon decay strategy
        custom_epsilon_decay(episode)
            
        # Record performance
        final_portfolio = env.portfolio_values[-1]
        
        # Recalculate to ensure portfolio includes both cash and position value
        position_value = 0
        if env.position == 1 and env.shares_held > 0:
            position_value = env.shares_held * env.prices[-1]
        
        # Make sure final portfolio includes both cash and position value
        final_portfolio = env.balance + position_value
        
        # MASSIVE END-OF-EPISODE BONUS for finishing with profit
        if final_portfolio > initial_balance:
            # Calculate profit percentage
            profit_pct = (final_portfolio / initial_balance) - 1.0
            # Normalized bonus (0 to 1.0 scale) - much more reasonable
            # 10% profit = 0.5 bonus, 20%+ profit = 1.0 bonus
            episode_bonus = min(profit_pct * 5.0, 1.0)
            # Add to total reward - much smaller scale than before
            total_reward += episode_bonus
            logger.info(f"Added episode bonus: +{episode_bonus:.2f} for {profit_pct:.2%} profit")
        else:
            # Small penalty for finishing with a loss
            loss_pct = (initial_balance - final_portfolio) / initial_balance
            episode_penalty = min(loss_pct * 2.0, 0.5)  # Cap at -0.5
            total_reward -= episode_penalty
            logger.info(f"Applied episode penalty: -{episode_penalty:.2f} for {loss_pct:.2%} loss")
            
        rewards_history.append(total_reward)
        portfolio_history.append(final_portfolio)
        
        # Save best model
        if final_portfolio > best_portfolio_value:
            best_portfolio_value = final_portfolio
            # Deep copy the model
            best_agent = agent
        
        # Update episode progress bar with useful information
        episode_bar.set_postfix({
            'Reward': f'{total_reward:.2f}', 
            'Portfolio': f'${final_portfolio:.2f}',
            'ROI': f'{(final_portfolio/initial_balance - 1.0)*100:.1f}%',
            'Epsilon': f'{agent.epsilon:.4f}'
        })
        
        # Calculate trading statistics
        total_buys = len([t for t in env.trades if t['type'] == 'buy'])
        total_sells = len([t for t in env.trades if t['type'] == 'sell'])
        profit_sells = len([t for t in env.trades if t['type'] == 'sell' and t.get('profit', 0) > 0])
        win_rate = profit_sells / total_sells if total_sells > 0 else 0
        
        # Calculate mean loss for this episode
        episode_mean_loss = np.mean(loss_history[-step_count:]) if len(loss_history) > 0 and step_count > 0 else 0
        avg_loss_history.append(episode_mean_loss)
        
        # Print detailed stats for each episode
        print(f"\nEpisode {episode+1}/{episodes} completed:")
        print(f"  - Total Reward: {total_reward:.2f} (normalized scale)")
        print(f"  - Mean Loss: {episode_mean_loss:.6f}")
        if len(agent.recent_losses) > 0:
            print(f"  - Recent Loss (avg of last 100): {np.mean(agent.recent_losses):.6f}")
        
        if final_portfolio > initial_balance:
            profit_pct = (final_portfolio / initial_balance) - 1.0
            episode_bonus = min(profit_pct * 5.0, 1.0)
            print(f"    (includes +{episode_bonus:.2f} profit bonus for {profit_pct:.2%} profit)")
        else:
            loss_pct = (initial_balance - final_portfolio) / initial_balance
            episode_penalty = min(loss_pct * 2.0, 0.5)
            print(f"    (includes -{episode_penalty:.2f} penalty for {loss_pct:.2%} loss)")
        print(f"  - Initial Balance: ${initial_balance:.2f}")
        print(f"  - Final Portfolio: ${final_portfolio:.2f} ({(final_portfolio/initial_balance - 1.0)*100:.1f}%)")
        print(f"  - Cash Balance: ${env.balance:.2f}")
        print(f"  - Shares Held: {env.shares_held:.4f}")
        if env.shares_held > 0:
            position_value = env.shares_held * env.prices[-1]
            print(f"  - Position Value: ${position_value:.2f} ({position_value/final_portfolio*100:.1f}% of portfolio)")
        else:
            print("  - No position")
        
        # DCA prevention metrics
        print(f"\n  DCA Prevention Metrics:")
        print(f"  - Buy attempts prevented: {env.dca_prevented_count}")
        print(f"  - Partial sells: {env.partial_sell_count}")
        
        # Risk metrics section
        print("\n  Risk Metrics:")
        print(f"  - Maximum Drawdown: {env.max_drawdown:.2%}")
        
        # Calculate and print Sharpe ratio
        sharpe_ratio = 0.0
        if len(env.daily_returns) >= 2:
            sharpe_ratio = env._calculate_sharpe_ratio()
            sharpe_rating = "Poor"
            if sharpe_ratio > 0.5: sharpe_rating = "Below Average"
            if sharpe_ratio > 1.0: sharpe_rating = "Good"
            if sharpe_ratio > 1.5: sharpe_rating = "Very Good"
            if sharpe_ratio > 2.0: sharpe_rating = "Excellent"
            if sharpe_ratio < 0: sharpe_rating = "Negative"
            if sharpe_ratio < -1.0: sharpe_rating = "Very Poor"
            
            print(f"  - Sharpe Ratio: {sharpe_ratio:.4f} ({sharpe_rating})")
        else:
            print("  - Sharpe Ratio: Not enough data")
            
        # Calculate Calmar ratio if we have non-zero max drawdown
        if env.max_drawdown > 0:
            # Annualized return / max drawdown
            periods_per_year = 252 if "d" in resolution.lower() else 365 * 24 if "h" in resolution.lower() else 365 * 24 * 60
            annualized_return = ((final_portfolio / initial_balance) ** (periods_per_year / len(env.prices)) - 1)
            calmar_ratio = annualized_return / env.max_drawdown
            print(f"  - Calmar Ratio: {calmar_ratio:.4f}")
        
        # Trade statistics section
        print("\n  Trade Statistics:")
        print(f"  - Trading Activity: {total_buys} buys, {total_sells} sells (Win rate: {win_rate:.1%})")
        
        # Calculate profit factor
        profit_factor = env.gross_profit / env.gross_loss if env.gross_loss > 0 else float('inf') if env.gross_profit > 0 else 0
        print(f"  - Profit Factor: {profit_factor:.2f} (Gross profit: ${env.gross_profit:.2f}, Gross loss: ${env.gross_loss:.2f})")
        
        # Streak information
        print(f"  - Longest Win Streak: {env.longest_win_streak} trades")
        print(f"  - Longest Lose Streak: {env.longest_lose_streak} trades")
        
        # Average trade metrics
        if len(env.trade_durations) > 0:
            avg_duration = sum(env.trade_durations) / len(env.trade_durations)
            print(f"  - Average Position Hold Time: {avg_duration:.1f} steps")
        
        # Average profit per trade
        if total_sells > 0:
            avg_profit = (final_portfolio - initial_balance) / total_sells
            print(f"  - Average Profit per Trade: ${avg_profit:.2f}")
        
        # Return volatility
        if len(env.daily_returns) >= 5:
            returns_std = np.std(env.daily_returns)
            print(f"  - Return Volatility (daily): {returns_std:.2%}")
        
        print(f"\n  Training Status:")
        print(f"  - Epsilon: {agent.epsilon:.4f}")
        print(f"  - Steps processed: {step_count}")
        print(f"  - Batches processed: {batch_count}")
        print(f"  - Best portfolio so far: ${best_portfolio_value:.2f} ({(best_portfolio_value/initial_balance - 1.0)*100:.1f}%)")
        
        # Add exploration phase indicator
        if episode < exploration_phase:
            print(f"  - Phase: Exploration ({episode+1}/{exploration_phase})")
        else:
            remaining = episodes - exploration_phase
            current = episode - exploration_phase + 1
            print(f"  - Phase: Exploitation ({current}/{remaining})")
        
        # Memory usage information if optimization is enabled
        if enable_memory_optimization:
            memory_info = {}
            try:
                import psutil
                process = psutil.Process(os.getpid())
                memory_info['memory_mb'] = process.memory_info().rss / 1024 / 1024
            except:
                pass
            
            print(f"  - Memory Usage: {memory_info.get('memory_mb', '?'):.1f} MB")
            print(f"  - Replay Buffer Size: {len(agent.memory)}/{agent.memory.maxlen}")
            print(f"  - Trade History Size: {len(env.trades)}")
            print(f"  - Daily Returns Size: {len(env.daily_returns)}")
        
        # Ensure output is flushed in WSL environment
        sys.stdout.flush()
        
        # Log progress every 5 episodes
        if episode % 5 == 0 or episode == episodes - 1:
            logger.info(f"Episode: {episode+1}/{episodes}, Total Reward: {total_reward:.2f}, " +
                      f"Final Value: ${final_portfolio:.2f}, Epsilon: {agent.epsilon:.4f}")
        
        # Memory optimization - run garbage collection after each episode
        if enable_memory_optimization:
            # Force Python garbage collection
            import gc
            gc.collect()
            
            # Clear TensorFlow memory if possible
            try:
                import tensorflow as tf
                tf.keras.backend.clear_session()
            except:
                pass
    
    # Save trained model
    if model_name is None:
        model_name = f"fast_rl_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Save best model if we have one
    if best_agent is not None:
        best_agent.save(f"{model_name}_best")
        logger.info(f"Saved best model with portfolio value ${best_portfolio_value:.2f}")
    
    # Also save final model
    agent.save(model_name)
    
    # Print final summary
    print(f"\n{'='*80}")
    print(f"Training completed after {episodes} episodes")
    print(f"Final portfolio value: ${portfolio_history[-1]:.2f}")
    print(f"Best portfolio value: ${best_portfolio_value:.2f}")
    print(f"ROI: {(portfolio_history[-1] - initial_balance)/initial_balance:.2%}")
    print(f"Best ROI: {(best_portfolio_value - initial_balance)/initial_balance:.2%}")
    
    # Calculate final Sharpe ratio
    final_sharpe = 0.0
    if len(env.daily_returns) >= 2:
        final_sharpe = env._calculate_sharpe_ratio()
        sharpe_rating = "Poor"
        if final_sharpe > 0.5: sharpe_rating = "Below Average"
        if final_sharpe > 1.0: sharpe_rating = "Good"
        if final_sharpe > 1.5: sharpe_rating = "Very Good"
        if final_sharpe > 2.0: sharpe_rating = "Excellent"
        if final_sharpe < 0: sharpe_rating = "Negative"
        if final_sharpe < -1.0: sharpe_rating = "Very Poor"
        
        print(f"Final Sharpe Ratio: {final_sharpe:.4f} ({sharpe_rating})")
    else:
        print("Final Sharpe Ratio: Not enough data")
        
    print(f"{'='*80}\n")
    
    # Final memory cleanup
    if enable_memory_optimization:
        # Explicitly delete large objects
        env.portfolio_values = None
        env.trades = []
        env.daily_returns = []
        env.minute_returns = []
        
        # Force garbage collection
        import gc
        gc.collect()
    
    # Visualize training progress
    plt.figure(figsize=(15, 10))
    
    # Plot rewards
    plt.subplot(2, 2, 1)
    plt.plot(rewards_history)
    plt.title('Rewards per Episode')
    plt.xlabel('Episode')
    plt.ylabel('Total Reward')
    
    # Plot portfolio value
    plt.subplot(2, 2, 2)
    plt.plot(portfolio_history)
    plt.title('Portfolio Value per Episode')
    plt.xlabel('Episode')
    plt.ylabel('Portfolio Value ($)')
    
    # Plot loss
    plt.subplot(2, 2, 3)
    if len(avg_loss_history) > 0:
        plt.plot(avg_loss_history)
        plt.title('Mean Loss per Episode')
        plt.xlabel('Episode')
        plt.ylabel('Loss (MSE)')
        plt.yscale('log')  # Log scale for better visualization
    
    # Plot epsilon decay
    plt.subplot(2, 2, 4)
    epsilon_history = [initial_epsilon * (accelerated_decay_rate ** max(0, i - exploration_phase)) 
                      if i >= exploration_phase else initial_epsilon 
                      for i in range(episodes)]
    plt.plot(epsilon_history)
    plt.title('Epsilon Decay')
    plt.xlabel('Episode')
    plt.ylabel('Epsilon')
    
    plt.tight_layout()
    plt.savefig(os.path.join(agent.model_dir, f"{model_name}_training.png"))
    
    # Add feature importance analysis if feature names are provided
    if hasattr(agent, 'feature_names') and agent.feature_names:
        logger.info("Running feature importance analysis...")
        importance_results = analyze_feature_importance(agent, env, 
                                                     feature_names=agent.feature_names)
        plot_feature_importance(importance_results, 
                              save_path=os.path.join(agent.model_dir, f"{model_name}_importance"))
        
        # Save importance results
        with open(os.path.join(agent.model_dir, f"{model_name}_importance.json"), 'w') as f:
            # Convert numpy arrays to lists for JSON serialization
            serializable_results = {k: v.tolist() if isinstance(v, np.ndarray) else v 
                                  for k, v in importance_results.items()}
            json.dump(serializable_results, f, indent=2)
    
    return agent, env

def evaluate_fast_agent(agent, price_data, feature_data, initial_balance=10000.0, max_eval_time=300,
                   risk_free_rate=0.0, sharpe_lookback=30, sharpe_weight=2.0,
                   position_sizing="fixed", max_position_pct=0.2, resolution="1m", 
                   reward_type="combined", slippage_pct=0.0015,  # Options: "combined", "sharpe_only", "simplified_profit_sharpe", "profit_focused" (uses RewardCalculator) 
                   visualize_trades=True, orig_ohlcv_df=None):
    """
    Evaluate a trained fast RL agent on historical price data
    
    Args:
        agent: Trained RL agent
        price_data: Array of historical prices
        feature_data: Array of features for state representation
        initial_balance: Starting cash balance
        max_eval_time: Maximum evaluation time in seconds
        risk_free_rate: Annual risk-free rate for Sharpe calculation
        sharpe_lookback: Number of steps to use for Sharpe calculation
        sharpe_weight: Weight of Sharpe ratio in reward function
        position_sizing: Strategy for position sizing ('fixed', 'kelly', or 'random')
        max_position_pct: Maximum position size as percentage of portfolio
        resolution: Time resolution of the data (e.g., "1m", "5m", "15m", "1h", "4h", "1d")
        reward_type: Type of reward function to use ('combined', 'sharpe_only', 'simplified_profit_sharpe')
        slippage_pct: Percentage of slippage to apply to trades (0.0015 = 15 basis points)
        visualize_trades: Whether to create a visualization of trades
        orig_ohlcv_df: Original OHLCV dataframe with timestamps for visualization
        
    Returns:
        Dictionary of evaluation results
    """
    # Handle the case where agent is a path to a saved model
    if isinstance(agent, str):
        logger.info(f"Loading agent from {agent}")
        agent = load_fast_rl_agent(agent)
    
    logger.info(f"Evaluating fast RL agent on {len(price_data)} data points...")
    
    # Create environment for evaluation
    env = FastTradingEnvironment(
        price_data, 
        feature_data, 
        initial_balance=initial_balance,
        risk_free_rate=risk_free_rate,
        sharpe_lookback=sharpe_lookback,
        sharpe_weight=sharpe_weight,
        position_sizing=position_sizing,
        max_position_pct=max_position_pct,
        resolution=resolution,
        reward_type=reward_type,
        slippage_pct=slippage_pct
    )
    
    # Reset LSTM states if using stateful LSTM model
    if agent.network_type == "stateful_lstm":
        logger.info("Resetting LSTM states before evaluation")
        agent.reset_lstm_states()
    
    # Reset environment
    state = env.reset()
    done = False
    
    # Track performance
    eval_start_time = time.time()
    total_reward = 0
    step_count = 0
    
    # Track trade history for visualization
    trades = []
    current_position = 0
    
    # Process environment in batches to reduce sequential steps for efficiency
    env_batch_size = min(256, len(price_data) // 10)
    
    # Create a progress bar
    steps_bar = tqdm(
        total=len(price_data), 
        desc="Evaluating", 
        position=0, 
        leave=True,
        ncols=100
    )
    
    while not done:
        # Check for timeout
        if time.time() - eval_start_time > max_eval_time:
            logger.warning(f"Evaluation timed out after {time.time() - eval_start_time:.1f} seconds")
            break
            
        # For stateful LSTM, we need to handle one step at a time
        if agent.network_type == "stateful_lstm":
            action = agent.act(state, training=False)
            next_state, reward, done, info = env.step(action)
            
            # Track performance 
            total_reward += reward
            step_count += 1
            steps_bar.update(1)
            
            # Track position changes for visualization
            if info['position'] != current_position:
                # Record trade for visualization
                # Map action to type
                action_type = {
                    0: "hold",
                    1: "buy (5%)",
                    2: "sell all"
                }.get(action, "unknown")
                
                trades.append({
                    'step': env.current_step,
                    'price': price_data[env.current_step],
                    'action': action,
                    'action_type': action_type,
                    'portfolio_value': info['portfolio_value'],
                    'position': info['position'],
                    'balance': info['balance']
                })
                current_position = info['position']
            
            state = next_state
        else:
            # Use batch simulation for efficiency with non-stateful models
            experiences = env.run_batch_simulation(agent, env_batch_size, training=False)
            
            if not experiences:
                logger.warning("Empty experiences from batch simulation, breaking")
                break
            
            # Extract batch information
            for state, action, reward, next_state, step_done in experiences:
                # Increment step count
                step_count += 1
                total_reward += reward
                
                # Check step at which this experience was generated
                step_idx = env.current_step - 1
                
                # Skip if step index is out of bounds
                if step_idx < 0 or step_idx >= len(price_data):
                    continue
                
                # Get info about the current state
                info = {
                    'portfolio_value': env.portfolio_values[step_idx],
                    'position': env.position,  # Current position status
                    'balance': env.balance  # Current cash balance
                }
                
                # Track position changes for visualization
                if info['position'] != current_position:
                    # Record trade for visualization
                    # Map action to type
                    action_type = {
                        0: "hold",
                        1: "buy (5%)",
                        2: "sell all"
                    }.get(action, "unknown")
                    
                    trades.append({
                        'step': step_idx,
                        'price': price_data[step_idx],
                        'action': action,
                        'action_type': action_type,
                        'portfolio_value': info['portfolio_value'],
                        'position': info['position'],
                        'balance': info['balance']
                    })
                    current_position = info['position']
                
                # Update done status
                done = step_done
                if done:
                    break
            
            # Update progress bar with number of steps processed
            steps_bar.update(len(experiences))
    
    steps_bar.close()
    
    # Calculate performance metrics
    elapsed_time = time.time() - eval_start_time
    
    # Get final portfolio value
    final_value = env.portfolio_values[-1] if len(env.portfolio_values) > 0 else initial_balance
    cash_balance = env.balance
    position_value = 0
    if env.position == 1 and env.shares_held > 0:
        position_value = env.shares_held * price_data[-1]
    
    # Recalculate final value to ensure position is included
    final_value = cash_balance + position_value
    
    # Calculate ROI
    roi = (final_value - initial_balance) / initial_balance
    
    # Calculate buy and hold return
    buy_hold_return = (price_data[-1] - price_data[0]) / price_data[0]
    
    # Calculate win rate from actual trades
    sell_trades = [t for t in env.trades if t.get('type', 'sell') == 'sell']  # Use get with default to handle missing 'type'
    win_trades = [t for t in sell_trades if t.get('profit', 0) > 0]
    win_rate = len(win_trades) / len(sell_trades) if len(sell_trades) > 0 else 0
    
    # Calculate Sharpe ratio
    if len(env.daily_returns) > 0:
        sharpe_ratio = np.mean(env.daily_returns) / np.std(env.daily_returns) if np.std(env.daily_returns) > 0 else 0
        # Annualize Sharpe ratio
        sharpe_ratio *= np.sqrt(365)  # Assuming daily returns
    else:
        sharpe_ratio = 0
    
    logger.info(f"Evaluation completed in {elapsed_time:.2f} seconds")
    logger.info(f"Final portfolio value: ${final_value:.2f}")
    logger.info(f"Return: {roi:.2%} vs Buy & Hold: {buy_hold_return:.2%}")
    logger.info(f"Trades: {len(env.trades)}, Win rate: {win_rate:.2%}")
    
    # Visualize trades on candlestick chart if requested
    if visualize_trades and len(trades) > 0:
        try:
            if orig_ohlcv_df is not None and 'timestamp' in orig_ohlcv_df.columns:
                # Use the original dataframe with timestamps for visualization
                logger.info("Creating trade visualization with original OHLCV data")
                plot_trades_on_candlestick(
                    orig_ohlcv_df,
                    trades,
                    filename=f"trades_{int(time.time())}.png",
                    title=f"RL Agent Trading Performance (ROI: {roi:.2%}, Sharpe: {sharpe_ratio:.2f})"
                )
            else:
                # Just use the price data
                logger.info("Creating trade visualization with price data only")
                # Create a simplified DataFrame with controlled timestamps to avoid overflow
                base_date = pd.Timestamp('2020-01-01')
                timestamps = [base_date + pd.Timedelta(minutes=i) for i in range(len(price_data))]
                
                simple_df = pd.DataFrame({
                    'timestamp': timestamps,
                    'open': price_data,
                    'high': price_data * 1.001,  # Small variation for visualization
                    'low': price_data * 0.999,   # Small variation for visualization
                    'close': price_data,
                    'volume': np.ones(len(price_data))  # Dummy volume
                })
                
                plot_trades_on_candlestick(
                    simple_df,
                    trades,
                    filename=f"trades_{int(time.time())}.png",
                    title=f"RL Agent Trading Performance (ROI: {roi:.2%}, Sharpe: {sharpe_ratio:.2f})"
                )
        except Exception as e:
            logger.error(f"Error creating trade visualization: {e}")
    
    # Return results as dictionary
    return {
        'final_value': final_value,
        'cash_balance': cash_balance,
        'position_value': position_value,
        'roi': roi,
        'buy_hold_return': buy_hold_return,
        'win_rate': win_rate,
        'total_trades': len(env.trades),
        'sharpe_ratio': sharpe_ratio,
        'trades': env.trades,
        'portfolio_values': env.portfolio_values,
        'max_drawdown': env.max_drawdown,
        'execution_time': elapsed_time,
        'dca_prevented_count': env.dca_prevented_count,
        'partial_sell_count': env.partial_sell_count
    }

def analyze_feature_importance(agent, env, feature_names=None, n_repeats=3, sample_size=1000):
    """
    Analyze feature importance using multiple techniques
    
    Args:
        agent: Trained FastDQNAgent
        env: FastTradingEnvironment instance
        feature_names: List of feature names (if None, will use generic names)
        n_repeats: Number of times to repeat permutation importance
        sample_size: Number of states to sample for importance calculation
        
    Returns:
        Dictionary with feature importance metrics
    """
    logger.info(f"Analyzing feature importance with {n_repeats} repeats on {sample_size} samples")
    
    # Create feature names if not provided
    if feature_names is None:
        feature_names = [f"Feature_{i}" for i in range(env.features.shape[1])]
    
    # Ensure we have the right number of feature names
    if len(feature_names) != env.features.shape[1]:
        logger.warning(f"Feature names count ({len(feature_names)}) doesn't match feature count ({env.features.shape[1]})")
        feature_names = [f"Feature_{i}" for i in range(env.features.shape[1])]
    
    # Sample states from environment for analysis
    states = []
    original_step = env.current_step
    
    # Reset environment to get clean state samples
    env.reset()
    
    # Method 1: Collect random states from different points in data
    indices = np.random.choice(len(env.prices) - 10, min(sample_size, len(env.prices) - 10), replace=False)
    
    for idx in indices:
        env.current_step = idx
        states.append(env._get_observation())
    
    # Restore original step
    env.current_step = original_step
    
    # Convert to numpy array
    states = np.array(states)
    
    # Method 1: Permutation Importance
    # Get baseline predictions
    baseline_predictions = agent.model.predict(states, verbose=0)
    baseline_actions = np.argmax(baseline_predictions, axis=1)
    
    # Store importance scores (average drop in prediction confidence)
    permutation_importance = np.zeros(env.features.shape[1])
    
    # For each feature
    for i in range(env.features.shape[1]):
        importance_samples = []
        
        # Repeat multiple times for stability
        for _ in range(n_repeats):
            # Create a copy of the states
            permuted_states = states.copy()
            
            # Shuffle the values of the current feature across all samples
            permuted_values = permuted_states[:, i].copy()
            np.random.shuffle(permuted_values)
            permuted_states[:, i] = permuted_values
            
            # Get predictions with permuted feature
            permuted_predictions = agent.model.predict(permuted_states, verbose=0)
            
            # Calculate the mean drop in prediction confidence for the originally chosen action
            confidences = np.array([pred[act] for pred, act in zip(baseline_predictions, baseline_actions)])
            permuted_confidences = np.array([pred[act] for pred, act in zip(permuted_predictions, baseline_actions)])
            
            # Calculate importance as the mean absolute difference in confidence
            importance = np.mean(np.abs(confidences - permuted_confidences))
            importance_samples.append(importance)
        
        # Average importance across repeats
        permutation_importance[i] = np.mean(importance_samples)
    
    # Method 2: Direct Gradient-based Importance (FIXED)
    gradient_importance = np.zeros(env.features.shape[1])
    
    try:
        # Convert states to tensor with proper shape handling
        if len(states.shape) == 3:
            # For LSTM models with sequences, use the states as-is
            states_tensor = tf.convert_to_tensor(states, dtype=tf.float32)
        else:
            # For non-LSTM models, use single observations
            states_tensor = tf.convert_to_tensor(states, dtype=tf.float32)
        
        # Compute gradients using GradientTape (avoid @tf.function issues)
        with tf.GradientTape() as tape:
            tape.watch(states_tensor)
            predictions = agent.model(states_tensor)
            # Use mean of predictions to get scalar for gradient computation
            loss = tf.reduce_mean(predictions)
        
        gradients = tape.gradient(loss, states_tensor)
        
        if gradients is not None:
            # Handle different input shapes
            if len(gradients.shape) == 3:
                # For sequence models, average across time dimension and samples
                gradient_importance = np.mean(np.abs(gradients.numpy()), axis=(0, 1))
            elif len(gradients.shape) == 2:
                # For non-sequence models, average across samples
                gradient_importance = np.mean(np.abs(gradients.numpy()), axis=0)
            
            # Only keep gradients for feature columns (exclude position state)
            if len(gradient_importance) > env.features.shape[1]:
                gradient_importance = gradient_importance[:env.features.shape[1]]
        else:
            logger.warning("Gradient computation failed, using zeros")
            gradient_importance = np.zeros(env.features.shape[1])
            
    except Exception as e:
        logger.warning(f"Gradient-based importance failed: {e}")
        gradient_importance = np.zeros(env.features.shape[1])
    
    # Method 3: Action-Feature Correlation
    # Analyze how each feature correlates with choosing specific actions
    correlation_importance = np.zeros((env.features.shape[1], 3))  # 3 actions
    
    for action in range(3):  # hold, buy, sell
        action_mask = baseline_actions == action
        if np.sum(action_mask) > 5:  # Need sufficient samples
            # For each feature, compute correlation with action probability
            for i in range(env.features.shape[1]):
                feature_values = states[action_mask, i]
                action_probs = baseline_predictions[action_mask, action]
                
                # Compute correlation if we have enough samples
                if len(feature_values) > 5:
                    correlation = np.corrcoef(feature_values, action_probs)[0, 1]
                    correlation_importance[i, action] = correlation if not np.isnan(correlation) else 0
    
    # Normalize importance scores with safety checks
    if np.sum(permutation_importance) > 1e-10:
        permutation_importance = permutation_importance / np.sum(permutation_importance)
    else:
        logger.warning("Permutation importance is all zeros or too small")
        
    if np.sum(gradient_importance) > 1e-10:
        gradient_importance = gradient_importance / np.sum(gradient_importance)
    else:
        logger.warning("Gradient importance is all zeros or too small")
    
    # Create combined importance score with safety checks
    if np.sum(permutation_importance) > 0 and np.sum(gradient_importance) > 0:
        combined_importance = 0.5 * permutation_importance + 0.5 * gradient_importance
    elif np.sum(permutation_importance) > 0:
        logger.warning("Using only permutation importance (gradient importance failed)")
        combined_importance = permutation_importance
    elif np.sum(gradient_importance) > 0:
        logger.warning("Using only gradient importance (permutation importance failed)")
        combined_importance = gradient_importance
    else:
        logger.error("Both importance methods failed, creating uniform importance")
        combined_importance = np.ones(len(feature_names)) / len(feature_names)
    
    # Sort features by importance
    sorted_indices = np.argsort(combined_importance)[::-1]
    
    # Create result dictionary
    results = {
        'feature_names': feature_names,
        'permutation_importance': permutation_importance,
        'gradient_importance': gradient_importance,
        'combined_importance': combined_importance,
        'correlation_by_action': correlation_importance,
        'sorted_indices': sorted_indices,
        'sorted_features': [feature_names[i] for i in sorted_indices],
        'sorted_importance': combined_importance[sorted_indices]
    }
    
    # Print top important features
    print("\n=== Feature Importance Analysis ===")
    print("Top 10 most important features:")
    for i, idx in enumerate(sorted_indices[:10]):
        print(f"{i+1}. {feature_names[idx]}: {combined_importance[idx]:.4f}")
    
    # Visualize feature importance
    plt.figure(figsize=(12, 6))
    plt.bar(range(len(sorted_indices[:15])), combined_importance[sorted_indices[:15]])
    plt.xticks(range(len(sorted_indices[:15])), [feature_names[i] for i in sorted_indices[:15]], rotation=45, ha='right')
    plt.title('Top 15 Features by Importance')
    plt.tight_layout()
    plt.savefig(os.path.join(agent.model_dir, "feature_importance.png"))
    
    # Return the results dictionary
    return results

def plot_feature_importance(importance_results, save_path=None):
    """
    Create detailed visualizations of feature importance analysis
    
    Args:
        importance_results: Results dictionary from analyze_feature_importance
        save_path: Path to save visualizations (if None, will show plots)
    """
    feature_names = importance_results['feature_names']
    sorted_idx = importance_results['sorted_indices']
    
    # Plot top features with different importance metrics
    plt.figure(figsize=(14, 8))
    
    # Limit to top 15 features for readability
    top_n = min(15, len(sorted_idx))
    top_indices = sorted_idx[:top_n]
    
    # Get the values for each importance method
    permutation_vals = importance_results['permutation_importance'][top_indices]
    gradient_vals = importance_results['gradient_importance'][top_indices]
    combined_vals = importance_results['combined_importance'][top_indices]
    
    # Set up x positions for grouped bars
    x = np.arange(top_n)
    width = 0.25
    
    # Create grouped bar chart
    plt.bar(x - width, permutation_vals, width, label='Permutation Importance')
    plt.bar(x, gradient_vals, width, label='Gradient Importance')
    plt.bar(x + width, combined_vals, width, label='Combined Importance')
    
    plt.xlabel('Features')
    plt.ylabel('Importance Score')
    plt.title('Feature Importance by Different Methods')
    plt.xticks(x, [feature_names[i] for i in top_indices], rotation=45, ha='right')
    plt.legend()
    plt.tight_layout()
    
    if save_path:
        plt.savefig(f"{save_path}_methods_comparison.png")
    else:
        plt.show()
    
    # Plot feature correlation by action
    action_names = ['Hold', 'Buy', 'Sell']
    correlation_data = importance_results['correlation_by_action']
    
    plt.figure(figsize=(14, 8))
    for i, action in enumerate(action_names):
        plt.subplot(1, 3, i+1)
        
        # Sort correlations by magnitude
        action_corr = correlation_data[:, i]
        sorted_corr_idx = np.argsort(np.abs(action_corr))[::-1][:10]  # Top 10 by magnitude
        
        colors = ['g' if c > 0 else 'r' for c in action_corr[sorted_corr_idx]]
        plt.barh(range(len(sorted_corr_idx)), action_corr[sorted_corr_idx], color=colors)
        plt.yticks(range(len(sorted_corr_idx)), [feature_names[i] for i in sorted_corr_idx])
        plt.title(f'Feature Correlation with {action} Action')
        plt.xlabel('Correlation')
        plt.grid(axis='x', linestyle='--', alpha=0.7)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(f"{save_path}_action_correlation.png")
    else:
        plt.show()

def run_feature_importance_analysis(agent, price_data, feature_data, feature_names=None, n_repeats=3, 
                                  sample_size=1000, output_dir=None, prefix="feature_analysis"):
    """
    Run feature importance analysis on an existing trained agent
    
    Args:
        agent: Trained FastDQNAgent
        price_data: Price data array
        feature_data: Feature data array
        feature_names: List of feature names (if None, will use agent's feature_names or generic names)
        n_repeats: Number of times to repeat permutation importance
        sample_size: Number of states to sample for importance calculation
        output_dir: Directory to save results (if None, will use agent's model_dir)
        prefix: Prefix for saved files
        
    Returns:
        Dictionary with feature importance metrics
    """
    # Use provided feature names or agent's feature names if available
    if feature_names is None and hasattr(agent, 'feature_names'):
        feature_names = agent.feature_names
    
    # Create environment for analysis
    env = FastTradingEnvironment(
        price_data, 
        feature_data, 
        initial_balance=10000.0
    )
    
    # Set output directory
    if output_dir is None:
        output_dir = agent.model_dir
    
    # Run importance analysis
    importance_results = analyze_feature_importance(
        agent, env, feature_names=feature_names, 
        n_repeats=n_repeats, sample_size=sample_size
    )
    
    # Plot detailed visualizations
    plot_feature_importance(
        importance_results, 
        save_path=os.path.join(output_dir, f"{prefix}")
    )
    
    # Save results to JSON
    save_path = os.path.join(output_dir, f"{prefix}.json")
    with open(save_path, 'w') as f:
        # Convert numpy arrays to lists for JSON serialization
        serializable_results = {k: v.tolist() if isinstance(v, np.ndarray) else v 
                              for k, v in importance_results.items()}
        json.dump(serializable_results, f, indent=2)
    
    print(f"\nFeature importance analysis complete.")
    print(f"Results saved to {save_path}")
    print(f"Visualizations saved to {output_dir}")
    
    return importance_results

def load_fast_rl_agent(model_path, verbose=True, reset_epsilon=True):
    """
    Load a trained FastDQNAgent from disk with proper configuration
    
    Args:
        model_path: Path to the saved model (.h5 file)
        verbose: Whether to log detailed information
        reset_epsilon: Whether to reset epsilon to a higher value for continued exploration
        
    Returns:
        Loaded FastDQNAgent ready for continued training or inference
    """
    if verbose:
        logger.info(f"Loading trained RL agent from {model_path}")
    
    try:
        # Load the model to determine dimensions
        model = tf.keras.models.load_model(model_path)
        
        # Get state and action dimensions from model
        state_size = model.input_shape[1]
        action_size = model.output_shape[1]
        
        # Check for action size compatibility - convert if needed
        if action_size > 3:
            logger.warning(f"Model has {action_size} actions, but we're using a 3-action space. Will adapt during prediction.")
            # We'll handle this by remapping actions during act() and batch_act()
            # This doesn't change the model itself but ensures compatible behavior
            action_size = 3
        
        if verbose:
            logger.info(f"Model dimensions: state_size={state_size}, action_size={action_size}")
        
        # Try to load feature importance information if available
        feature_names = None
        importance_path = model_path.replace(".h5", "_importance.json")
        if os.path.exists(importance_path):
            try:
                with open(importance_path, 'r') as f:
                    importance_data = json.load(f)
                    if 'feature_names' in importance_data:
                        feature_names = importance_data['feature_names']
                        if verbose:
                            logger.info(f"Loaded {len(feature_names)} feature names from importance file")
            except Exception as e:
                if verbose:
                    logger.warning(f"Could not load feature names from importance file: {e}")
        
        # Create a new agent with the correct dimensions
        network_type = "deep"  # Default to deep network
        
        # Try to infer network type from model architecture
        if len(model.layers) <= 4:
            network_type = "simple"
        elif any(isinstance(layer, tf.keras.layers.LSTM) for layer in model.layers):
            network_type = "lstm"
        elif any("advantage" in layer.name.lower() for layer in model.layers):
            network_type = "dueling"
            
        agent = FastDQNAgent(
            state_size=state_size,
            action_size=action_size,
            network_type=network_type,
            feature_names=feature_names
        )
        
        # Load the weights
        agent.model = model
        agent.target_model = tf.keras.models.clone_model(model)
        agent.target_model.set_weights(model.get_weights())
        
        # If model has different action size, create a map function to convert
        original_act = agent.act
        original_batch_act = agent.batch_act
        
        if model.output_shape[1] > 3:
            # Create wrapper for act method to map actions
            def act_wrapper(state, training=True):
                action = original_act(state, training)
                # Map actions from old space to new space:
                # 0 = hold -> still 0
                # 1-4 = buy with different sizes -> 1 (buy with fixed size)
                # 5 = sell all -> 2 (sell all)
                if 1 <= action <= 4:
                    return 1  # all buy actions map to 1
                elif action == 5:
                    return 2  # sell all maps to 2
                else:
                    return 0  # hold
            
            # Create wrapper for batch_act method to map actions
            def batch_act_wrapper(states, training=True):
                actions = original_batch_act(states, training)
                # Map actions
                mapped_actions = np.zeros_like(actions)
                mapped_actions[actions == 0] = 0  # hold
                mapped_actions[(actions >= 1) & (actions <= 4)] = 1  # all buys -> 1
                mapped_actions[actions == 5] = 2  # sell -> 2
                return mapped_actions
            
            # Replace methods with wrappers
            agent.act = act_wrapper
            agent.batch_act = batch_act_wrapper
            
            if verbose:
                logger.info(f"Created action mapping from {model.output_shape[1]}-action to 3-action space")
        
        # Reset epsilon if requested (for continued training)
        if reset_epsilon:
            # Instead of doubling epsilon, use a more conservative approach
            # for continued training - keep it low enough to exploit what's been learned
            original_epsilon = agent.epsilon
            agent.epsilon = min(0.2, max(0.1, original_epsilon))  # Cap between 0.1 and 0.2
            if verbose:
                logger.info(f"Adjusted agent epsilon from {original_epsilon:.4f} to {agent.epsilon:.4f} for continued training")
                
        if verbose:
            logger.info(f"Successfully loaded agent with state_size={state_size}, action_size={action_size}")
        
        return agent
        
    except Exception as e:
        logger.error(f"Error loading model: {e}")
        raise

def plot_trades_on_candlestick(
    price_data, 
    trades, 
    filename='trade_visualization.png', 
    title='Trading Activity Visualization',
    show_last_n=200,  # Only show the last N candles for clarity
    output_dir='models'
):
    """
    Visualize trading activity on a candlestick chart
    
    Args:
        price_data: Dictionary or DataFrame with OHLCV data including 'timestamp', 'open', 'high', 'low', 'close'
        trades: List of trade dictionaries from the environment
        filename: Output filename for the plot
        title: Title for the plot
        show_last_n: Number of most recent candles to display
        output_dir: Directory to save the plot
    """
    try:
        import pandas as pd
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.patches import Rectangle
        import numpy as np
        from datetime import datetime, timedelta
        
        # Convert price_data to pandas DataFrame if it's not already
        if not isinstance(price_data, pd.DataFrame):
            # Check if it's a dictionary-like with OHLCV data
            if hasattr(price_data, 'items'):
                df = pd.DataFrame(price_data)
            else:
                # Create a simplified DataFrame with just the price data
                df = pd.DataFrame({
                    'close': price_data,
                    'timestamp': [datetime.now() - timedelta(minutes=i) for i in range(len(price_data)-1, -1, -1)]
                })
                # Estimate OHLC from close prices
                df['open'] = df['close'].shift(1).fillna(df['close'].iloc[0] * 0.998)
                df['high'] = df['close'].apply(lambda x: x * (1 + np.random.uniform(0, 0.005)))
                df['low'] = df['close'].apply(lambda x: x * (1 - np.random.uniform(0, 0.005)))
                df.iloc[0, df.columns.get_loc('open')] = df.iloc[0, df.columns.get_loc('close')] * 0.998
        else:
            df = price_data.copy()
        
        # Ensure we have a timestamp column
        if 'timestamp' not in df.columns:
            if isinstance(df.index, pd.DatetimeIndex):
                df['timestamp'] = df.index
            else:
                # Create synthetic timestamps instead of using datetime.now()
                # to avoid potential integer overflow issues
                base_date = pd.Timestamp('2020-01-01')
                df['timestamp'] = [base_date + pd.Timedelta(minutes=i) for i in range(len(df))]
        
        # Make sure timestamp is datetime with proper validation
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            try:
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                # Replace any NaT values with valid dates
                nat_mask = pd.isna(df['timestamp'])
                if nat_mask.any():
                    logger.warning(f"Found {nat_mask.sum()} invalid timestamps, replacing with synthetic dates")
                    base_date = pd.Timestamp('2020-01-01')
                    df.loc[nat_mask, 'timestamp'] = [base_date + pd.Timedelta(minutes=i) 
                                                   for i in range(sum(nat_mask))]
            except Exception as e:
                logger.warning(f"Could not convert timestamps: {e}. Creating synthetic timestamps.")
                base_date = pd.Timestamp('2020-01-01')
                df['timestamp'] = [base_date + pd.Timedelta(minutes=i) for i in range(len(df))]
        
        # Validate timestamp range to prevent matplotlib overflow
        try:
            # Check if timestamps are within matplotlib's safe range (roughly 1677-2262)
            min_safe_date = pd.Timestamp('1900-01-01')
            max_safe_date = pd.Timestamp('2200-01-01')
            
            if (df['timestamp'] < min_safe_date).any() or (df['timestamp'] > max_safe_date).any():
                logger.warning("Timestamps outside safe range for matplotlib, normalizing...")
                # Normalize to a safe range
                base_date = pd.Timestamp('2020-01-01')
                df['timestamp'] = [base_date + pd.Timedelta(minutes=i) for i in range(len(df))]
        except Exception as e:
            logger.warning(f"Error validating timestamp range: {e}. Using synthetic timestamps.")
            base_date = pd.Timestamp('2020-01-01')
            df['timestamp'] = [base_date + pd.Timedelta(minutes=i) for i in range(len(df))]
        
        # Record original data length before truncation
        original_length = len(df)
        
        # Only show the last N candles for clarity
        if len(df) > show_last_n:
            logger.info(f"Showing only the last {show_last_n} candles out of {len(df)} total")
            df = df.iloc[-show_last_n:].copy()
            # Reset index to make indexing simpler
            df = df.reset_index(drop=True)
        
        # Calculate offset between original indices and truncated df indices
        offset = max(0, original_length - show_last_n)
        
        # Extract buy and sell trades that fall within our visible range
        visible_trades = []
        for trade in trades:
            # Adjust the trade step to account for the truncated dataframe
            adjusted_step = trade['step'] - offset
            
            # Only include trades that fall within our visible range
            if 0 <= adjusted_step < len(df):
                # Create a copy of the trade with the adjusted step
                trade_copy = trade.copy()
                trade_copy['adjusted_step'] = adjusted_step
                
                # Update action_type to use simplified mapping
                if 'action' in trade_copy:
                    if trade_copy['action'] == 0:
                        trade_copy['action_type'] = 'hold'
                    elif trade_copy['action'] == 1:
                        trade_copy['action_type'] = 'buy (5%)'
                    elif trade_copy['action'] == 2:
                        trade_copy['action_type'] = 'sell all'
                
                visible_trades.append(trade_copy)
        
        # Now filter to buy/sell trades using the adjusted visible trades
        buy_trades = [t for t in visible_trades if t.get('action', 0) == 1]
        sell_trades = [t for t in visible_trades if t.get('action', 0) == 2]
        
        # Get buy and sell coordinates (safely)
        try:
            buy_x = df['timestamp'].iloc[[t['adjusted_step'] for t in buy_trades]] if buy_trades else []
            buy_y = [t['price'] for t in buy_trades] if buy_trades else []
            buy_labels = [t.get('action_type', '') for t in buy_trades] if buy_trades else []
            
            sell_x = df['timestamp'].iloc[[t['adjusted_step'] for t in sell_trades]] if sell_trades else []
            sell_y = [t['price'] for t in sell_trades] if sell_trades else []
            sell_labels = [t.get('action_type', '') for t in sell_trades] if sell_trades else []
        except IndexError as e:
            logger.warning(f"Index error when preparing trade coordinates: {e}")
            # Fallback to empty arrays if there's an indexing error
            buy_x, buy_y, buy_labels = [], [], []
            sell_x, sell_y, sell_labels = [], [], []
        
        # Create the figure
        plt.figure(figsize=(16, 8))
        
        try:
            # Set specific date formatter to avoid overflow issues
            import matplotlib.dates as mdates
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=10))
            
            # Plot candlestick chart - calculate width safely
            try:
                if len(df) > 1:
                    width = 0.6 * (df['timestamp'].iloc[1] - df['timestamp'].iloc[0]).total_seconds() * 1000000000
                else:
                    width = 60 * 1000000000  # Default to 1 minute width in nanoseconds
            except Exception as e:
                logger.warning(f"Could not calculate candlestick width: {e}. Using default.")
                width = 60 * 1000000000  # Default to 1 minute width in nanoseconds
            
            up = df[df['close'] >= df['open']]
            down = df[df['close'] < df['open']]
            
            # Plot up candles
            plt.bar(up['timestamp'], up['close']-up['open'], width, bottom=up['open'], color='green', alpha=0.5)
            plt.bar(up['timestamp'], up['high']-up['close'], 0.2*width, bottom=up['close'], color='green', alpha=0.5)
            plt.bar(up['timestamp'], up['open']-up['low'], 0.2*width, bottom=up['low'], color='green', alpha=0.5)
            
            # Plot down candles
            plt.bar(down['timestamp'], down['open']-down['close'], width, bottom=down['close'], color='red', alpha=0.5)
            plt.bar(down['timestamp'], down['high']-down['open'], 0.2*width, bottom=down['open'], color='red', alpha=0.5)
            plt.bar(down['timestamp'], down['close']-down['low'], 0.2*width, bottom=down['low'], color='red', alpha=0.5)
            
            # Plot buy and sell markers
            if len(buy_x) > 0:
                plt.scatter(buy_x, buy_y, marker='^', color='blue', s=100, label='Buy (5%)', zorder=10)
                
            if len(sell_x) > 0:
                plt.scatter(sell_x, sell_y, marker='v', color='purple', s=100, label='Sell All', zorder=10)
            
            # Format the plot
            plt.xlabel('Time')
            plt.ylabel('Price')
            plt.title(title)
            plt.legend()
            plt.grid(True, alpha=0.3)
            
            # Format x-axis to show dates nicely - use a safe approach
            try:
                from matplotlib.ticker import MaxNLocator
                date_format = mdates.DateFormatter('%Y-%m-%d')
                plt.gca().xaxis.set_major_formatter(date_format)
                plt.gca().xaxis.set_major_locator(MaxNLocator(nbins=10))  # Limited number of ticks
                plt.xticks(rotation=45)
            except Exception as e:
                logger.warning(f"Could not format date ticks: {e}. Using simple formatting.")
                # Fallback to simple numeric x-axis if date formatting fails
                try:
                    plt.gca().tick_params(axis='x', rotation=45)
                except:
                    pass
            
            # Add profit/loss labels to trades
            profitable_count = 0
            unprofitable_count = 0
            
            # Skip some labels if there are too many trades to prevent clutter
            label_interval = max(1, len(sell_trades) // 15)
            
            for i, trade in enumerate(sell_trades):
                if i % label_interval != 0:
                    continue
                    
                # Use the adjusted_step field for safe indexing
                idx = trade['adjusted_step']
                if 0 <= idx < len(df):
                    profit = trade.get('profit', 0)
                    if profit > 0:
                        profitable_count += 1
                        color = 'green'
                        marker = '+'
                    else:
                        unprofitable_count += 1
                        color = 'red'
                        marker = 'x'
                    
                    x_pos = df['timestamp'].iloc[idx]
                    y_pos = trade['price']
                    profit_pct = profit / (trade['price'] * trade.get('shares', 1)) * 100 if trade.get('shares', 1) > 0 else 0
                    
                    plt.annotate(f"{profit_pct:.1f}%", 
                                xy=(x_pos, y_pos),
                                xytext=(0, -20 if profit > 0 else 20),
                                textcoords='offset points',
                                color=color,
                                weight='bold',
                                arrowprops=dict(arrowstyle='-', color=color, alpha=0.3))
            
            # Add summary to the plot
            win_rate = profitable_count / (profitable_count + unprofitable_count) if profitable_count + unprofitable_count > 0 else 0
            plt.annotate(f"Win Rate: {win_rate:.1%} ({profitable_count}/{profitable_count + unprofitable_count})",
                        xy=(0.02, 0.02),
                        xycoords='axes fraction',
                        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))
            
            # Save the plot
            os.makedirs(output_dir, exist_ok=True)
            save_path = os.path.join(output_dir, filename)
            plt.tight_layout()
            plt.savefig(save_path)
            plt.close()
            
            logger.info(f"Trade visualization saved to {save_path}")
            return save_path
        
        except Exception as e:
            logger.error(f"Error generating trade visualization: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    except Exception as e:
        logger.error(f"Error generating trade visualization: {e}")
        import traceback
        traceback.print_exc()
        return None