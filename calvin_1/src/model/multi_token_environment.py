#!/usr/bin/env python3
"""
Multi-token trading environment for reinforcement learning
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)

class MultiTokenTradingEnvironment:
    """
    A trading environment that supports trading multiple tokens simultaneously.
    This environment allows the agent to build and manage a diversified portfolio.
    """
    
    def __init__(self, 
                 price_data_dict: Dict[str, pd.DataFrame], 
                 initial_balance: float = 10000, 
                 lookback_window: int = 30,
                 transaction_fee: float = 0.001,
                 max_position_size: float = 0.2):
        """
        Initialize the multi-token trading environment
        
        Args:
            price_data_dict: Dictionary mapping token symbols to their respective price DataFrames
            initial_balance: Initial cash balance
            lookback_window: Number of historical prices to include in state
            transaction_fee: Fee per transaction as a percentage (e.g., 0.001 = 0.1%)
            max_position_size: Maximum position size as a percentage of portfolio (e.g., 0.2 = 20%)
        """
        self.price_data_dict = price_data_dict
        self.tokens = list(price_data_dict.keys())
        self.num_tokens = len(self.tokens)
        
        # Verify that all price data has the same timestamps
        self._synchronize_timestamps()
        
        self.initial_balance = initial_balance
        self.lookback_window = lookback_window
        self.transaction_fee = transaction_fee
        self.max_position_size = max_position_size
        
        # Initialize portfolio and positions
        self.reset()
        
    def _synchronize_timestamps(self):
        """
        Ensure all token price data has aligned timestamps by resampling if needed
        """
        # First, ensure all dataframes have a timestamp column and it's a datetime type
        for token, df in self.price_data_dict.items():
            # Ensure timestamp column exists
            if 'timestamp' not in df.columns:
                if isinstance(df.index, pd.DatetimeIndex):
                    df = df.reset_index()
                    self.price_data_dict[token] = df
                else:
                    raise ValueError(f"No timestamp column found for {token}")
            
            # Convert timestamp to datetime if it's not already
            if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
                try:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                    self.price_data_dict[token] = df
                except Exception as e:
                    raise ValueError(f"Could not convert timestamps for {token}: {str(e)}")
        
        # Get the range of dates from all tokens
        min_dates = {}
        max_dates = {}
        for token, df in self.price_data_dict.items():
            min_dates[token] = df['timestamp'].min()
            max_dates[token] = df['timestamp'].max()
        
        # Find the common date range
        start_date = max(min_dates.values())
        end_date = min(max_dates.values())
        
        logger.info(f"Common date range: {start_date} to {end_date}")
        
        # Filter each DataFrame to only include the common date range
        for token in self.tokens:
            df = self.price_data_dict[token]
            self.price_data_dict[token] = df[(df['timestamp'] >= start_date) & 
                                           (df['timestamp'] <= end_date)].copy()
        
        # Determine the most common time interval
        intervals = []
        for token, df in self.price_data_dict.items():
            df = df.sort_values('timestamp')
            # Calculate time differences in seconds
            time_diffs = df['timestamp'].diff().dropna().dt.total_seconds()
            # Get the most common interval
            if not time_diffs.empty:
                most_common = time_diffs.value_counts().idxmax()
                intervals.append(most_common)
        
        # Use the median interval
        if intervals:
            target_interval = np.median(intervals)
            logger.info(f"Using median time interval of {target_interval} seconds")
        else:
            # Default to 5 minutes (300 seconds)
            target_interval = 300
            logger.warning(f"Could not determine common interval, using default: {target_interval} seconds")
        
        # Create a unified time range with the target interval
        time_range = pd.date_range(start=start_date, end=end_date, freq=f"{int(target_interval)}S")
        
        # Resample each DataFrame to the unified time range
        for token in self.tokens:
            df = self.price_data_dict[token].sort_values('timestamp')
            df.set_index('timestamp', inplace=True)
            
            # Resample to the target interval
            resampled = df.resample(f"{int(target_interval)}S").agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).fillna(method='ffill')
            
            # Reset index to get timestamp back as a column
            resampled.reset_index(inplace=True)
            
            # Filter to the common time range
            self.price_data_dict[token] = resampled[resampled['timestamp'].isin(time_range)].reset_index(drop=True)
        
        # Verify all DataFrames have the same timestamps and length
        lengths = [len(df) for df in self.price_data_dict.values()]
        
        if len(set(lengths)) != 1:
            logger.warning(f"Not all tokens have the same number of timestamps after synchronization: {lengths}")
            
            # Find the minimum length and truncate all DataFrames to that length
            min_length = min(lengths)
            for token in self.tokens:
                self.price_data_dict[token] = self.price_data_dict[token].iloc[:min_length].reset_index(drop=True)
        
        logger.info(f"Successfully synchronized {len(self.price_data_dict[self.tokens[0]])} timestamps across {self.num_tokens} tokens")
    
    def reset(self):
        """
        Reset the environment to its initial state
        
        Returns:
            Initial state
        """
        # Reset portfolio
        self.balance = self.initial_balance  # Cash balance
        self.positions = {token: 0 for token in self.tokens}  # Number of tokens held
        self.avg_entry_prices = {token: 0 for token in self.tokens}  # Average entry price per token
        
        # Reset metrics
        self.current_step = 0
        self.trade_history = []
        self.portfolio_values = [self.initial_balance]
        self.highest_portfolio_value = self.initial_balance
        self.max_drawdown = 0
        
        # Performance tracking
        self.total_trades = {token: 0 for token in self.tokens}
        self.winning_trades = {token: 0 for token in self.tokens}
        self.total_profits = {token: 0 for token in self.tokens}
        self.total_losses = {token: 0 for token in self.tokens}
        self.realized_profit = {token: 0 for token in self.tokens}
        self.unrealized_profit = {token: 0 for token in self.tokens}
        
        # Timer for last trade
        self.last_trade_step = {token: 0 for token in self.tokens}
        
        return self._get_state()
    
    def _get_state(self):
        """
        Get current state representation including all tokens
        
        Returns:
            State representation as numpy array
        """
        # Start with portfolio-level features
        portfolio_value = self.portfolio_value()
        portfolio_allocation = self._get_portfolio_allocation()
        
        # Calculate portfolio features
        features = [
            self.balance / self.initial_balance,  # Normalized cash balance
            portfolio_value / self.initial_balance,  # Normalized portfolio value
            len([p for p in self.positions.values() if p > 0]) / self.num_tokens,  # Portfolio diversity (% of tokens held)
        ]
        
        # Add token-specific features for each token
        for token in self.tokens:
            # Get price data for this token
            price_data = self.price_data_dict[token]
            
            # Get current price and volume
            current_price = price_data.iloc[self.current_step]['close']
            current_volume = price_data.iloc[self.current_step]['volume']
            
            # Get historical prices for lookback window
            lookback_start = max(0, self.current_step - self.lookback_window)
            lookback_end = self.current_step
            historical_data = price_data.iloc[lookback_start:lookback_end]
            
            # Pad with earliest available data if needed
            if len(historical_data) < self.lookback_window:
                padding = self.lookback_window - len(historical_data)
                pad_data = price_data.iloc[0:1].copy()
                for _ in range(padding):
                    historical_data = pd.concat([pad_data, historical_data])
            
            # Normalize historical prices relative to current price
            normalized_prices = historical_data['close'].values / current_price - 1  # % change from current
            normalized_volumes = historical_data['volume'].values / current_volume
            
            # Add token position information
            position_size = self.positions[token] * current_price / portfolio_value if portfolio_value > 0 else 0
            has_position = 1.0 if self.positions[token] > 0 else 0.0
            avg_entry_price = self.avg_entry_prices[token]
            price_to_entry_ratio = current_price / avg_entry_price if avg_entry_price > 0 else 1.0
            
            # Add all features for this token
            token_features = [
                current_price / price_data['close'].max(),  # Normalized current price
                current_volume / price_data['volume'].max(),  # Normalized current volume
                position_size,  # Position size as % of portfolio
                has_position,  # Position indicator
                price_to_entry_ratio - 1.0,  # Entry price vs current price (% change)
            ]
            
            # Add price history and volume history
            features.extend(token_features)
            features.extend(normalized_prices)
            features.extend(normalized_volumes)
        
        # Add correlation features between tokens
        if self.num_tokens > 1:
            for i in range(self.num_tokens):
                for j in range(i+1, self.num_tokens):
                    token_i = self.tokens[i]
                    token_j = self.tokens[j]
                    
                    # Get price series for correlation
                    lookback_start = max(0, self.current_step - 30)  # 30-period correlation
                    lookback_end = self.current_step + 1
                    
                    prices_i = self.price_data_dict[token_i].iloc[lookback_start:lookback_end]['close'].values
                    prices_j = self.price_data_dict[token_j].iloc[lookback_start:lookback_end]['close'].values
                    
                    # Calculate correlation if we have enough data points
                    if len(prices_i) > 5:
                        correlation = np.corrcoef(prices_i, prices_j)[0, 1]
                        features.append(correlation)
                    else:
                        features.append(0)  # Default if not enough data
        
        return np.array(features)
    
    def _get_portfolio_allocation(self):
        """
        Calculate current portfolio allocation across tokens
        
        Returns:
            Dictionary mapping tokens to their percentage of portfolio value
        """
        portfolio_value = self.portfolio_value()
        if portfolio_value == 0:
            return {token: 0 for token in self.tokens}
        
        allocation = {}
        for token in self.tokens:
            current_price = self.price_data_dict[token].iloc[self.current_step]['close']
            token_value = self.positions[token] * current_price
            allocation[token] = token_value / portfolio_value
            
        return allocation
    
    def step(self, token_idx, action):
        """
        Execute action for a specific token and move to next state
        
        Args:
            token_idx: Index of the token to trade
            action: Action to take (0: buy, 1: sell, 2: hold)
            
        Returns:
            next_state, reward, done, info
        """
        # Ensure we stay within bounds
        if self.current_step >= len(next(iter(self.price_data_dict.values()))) - 1:
            # Force liquidation at the end
            return self._get_state(), 0, True, {'msg': 'End of data reached'}
        
        # Get token for the action
        token = self.tokens[token_idx]
        
        # Get current price for the token
        current_price = self.price_data_dict[token].iloc[self.current_step]['close']
        
        # Store portfolio value before action
        prev_portfolio_value = self.portfolio_value()
        
        # Execute action
        reward = 0
        info = {'token': token, 'action': 'hold'}
        trade_made = False
        profit = 0
        
        if action == 0:  # Buy
            # Calculate how many tokens we can buy
            # Limit to max_position_size of portfolio
            max_allocation = self.max_position_size * prev_portfolio_value
            available_allocation = max(0, max_allocation - (self.positions[token] * current_price))
            max_tokens = min(
                available_allocation / current_price,
                self.balance / (current_price * (1 + self.transaction_fee))
            )
            
            if max_tokens > 0.001:  # Only buy if meaningful amount
                # Calculate cost
                num_tokens = max_tokens
                cost = num_tokens * current_price * (1 + self.transaction_fee)
                
                # Update position
                if self.positions[token] > 0:
                    # Average down/up
                    total_tokens = self.positions[token] + num_tokens
                    self.avg_entry_prices[token] = (
                        (self.positions[token] * self.avg_entry_prices[token]) + 
                        (num_tokens * current_price)
                    ) / total_tokens
                else:
                    # New position
                    self.avg_entry_prices[token] = current_price
                
                # Update position size and balance
                self.positions[token] += num_tokens
                self.balance -= cost
                
                # Record trade
                self.trade_history.append({
                    'step': self.current_step,
                    'token': token,
                    'action': 'buy',
                    'price': current_price,
                    'quantity': num_tokens,
                    'cost': cost
                })
                self.total_trades[token] += 1
                self.last_trade_step[token] = self.current_step
                trade_made = True
                
                info['action'] = 'buy'
                info['tokens'] = num_tokens
                info['price'] = current_price
                info['cost'] = cost
            else:
                info['action'] = 'hold (insufficient funds/allocation)'
        
        elif action == 1:  # Sell
            # Only sell if we have a position
            if self.positions[token] > 0:
                # Calculate profit/loss
                num_tokens = self.positions[token]
                entry_value = num_tokens * self.avg_entry_prices[token]
                exit_value = num_tokens * current_price
                profit_loss = exit_value - entry_value
                
                # Update balance (considering transaction costs)
                self.balance += exit_value - (exit_value * self.transaction_fee)
                info['profit'] = profit_loss
                
                # Track profit/loss
                if profit_loss > 0:
                    self.winning_trades[token] += 1
                    self.total_profits[token] += profit_loss
                else:
                    self.total_losses[token] += abs(profit_loss)
                
                profit = profit_loss
                self.realized_profit[token] += profit_loss
                
                # Record trade
                self.trade_history.append({
                    'step': self.current_step,
                    'token': token,
                    'action': 'sell',
                    'price': current_price,
                    'quantity': num_tokens,
                    'profit': profit_loss
                })
                self.total_trades[token] += 1
                self.last_trade_step[token] = self.current_step
                trade_made = True
                
                # Clear position
                self.positions[token] = 0
                self.avg_entry_prices[token] = 0
                
                info['action'] = 'sell'
                info['tokens'] = num_tokens
                info['price'] = current_price
                info['profit'] = profit_loss
            else:
                info['action'] = 'hold (no position to sell)'
        
        else:  # Hold
            info['action'] = 'hold'
        
        # Calculate new portfolio value
        new_portfolio_value = self.portfolio_value()
        self.portfolio_values.append(new_portfolio_value)
        
        # Update metrics
        if new_portfolio_value > self.highest_portfolio_value:
            self.highest_portfolio_value = new_portfolio_value
        
        # Calculate drawdown
        drawdown = (self.highest_portfolio_value - new_portfolio_value) / self.highest_portfolio_value
        if drawdown > self.max_drawdown and new_portfolio_value < prev_portfolio_value:
            self.max_drawdown = drawdown
        
        # Calculate unrealized profit for each token
        for t in self.tokens:
            t_price = self.price_data_dict[t].iloc[self.current_step]['close']
            if self.positions[t] > 0:
                self.unrealized_profit[t] = self.positions[t] * (t_price - self.avg_entry_prices[t])
            else:
                self.unrealized_profit[t] = 0
        
        # Calculate reward
        # 1. Reward based on portfolio change
        portfolio_change = (new_portfolio_value - prev_portfolio_value) / prev_portfolio_value if prev_portfolio_value > 0 else 0
        reward_portfolio = portfolio_change * 10.0  # Scale factor
        
        # 2. Additional reward/penalty for trades
        reward_trade = 0
        if trade_made:
            if profit > 0:  # Profitable trade
                reward_trade = 0.2
            elif profit < 0:  # Losing trade
                reward_trade = -0.1
        
        # 3. Penalty for excessive trading
        reward_frequency = 0
        if self.current_step - self.last_trade_step[token] < 5 and trade_made:
            reward_frequency = -0.05
        
        # 4. Penalty for large drawdowns
        reward_drawdown = 0
        if self.max_drawdown > 0.2:  # More than 20% drawdown
            reward_drawdown = -0.5
        
        # 5. Reward for diversification
        num_active_positions = sum(1 for p in self.positions.values() if p > 0)
        diversification_ratio = num_active_positions / self.num_tokens
        
        # Encourage moderate diversification (not too concentrated, not too spread out)
        reward_diversification = 0
        if diversification_ratio < 0.2:  # Too concentrated
            reward_diversification = -0.1
        elif 0.3 <= diversification_ratio <= 0.7:  # Good diversification
            reward_diversification = 0.1
        
        # Combine rewards
        reward = reward_portfolio + reward_trade + reward_frequency + reward_drawdown + reward_diversification
        
        # Ensure the reward aligns with portfolio performance
        if new_portfolio_value < self.initial_balance and reward > 0:
            reward = -abs(reward) * 0.5  # Convert to negative but reduce magnitude
        
        # If we're making money overall, ensure the reward is positive
        if new_portfolio_value > self.initial_balance * 1.05 and reward < 0:
            reward = abs(reward) * 0.3  # Convert to positive but reduce magnitude
        
        # No state changes until all token actions are processed (one step per token)
        # Move to next step after all tokens have been processed
        if token_idx == self.num_tokens - 1:
            self.current_step += 1
        
        # Check if we've reached the end of data
        done = self.current_step >= len(next(iter(self.price_data_dict.values()))) - 1
        
        # Add additional info
        info['portfolio_value'] = new_portfolio_value
        info['balance'] = self.balance
        info['position'] = self.positions[token]
        info['avg_entry_price'] = self.avg_entry_prices[token]
        info['total_trades'] = self.total_trades[token]
        info['win_rate'] = self.winning_trades[token] / max(1, self.total_trades[token])
        info['max_drawdown'] = self.max_drawdown
        info['positions'] = self.positions.copy()  # All token positions
        
        # Force liquidation at the end
        if done:
            # Calculate final portfolio value
            final_portfolio = new_portfolio_value
            
            # Calculate ROI
            roi = (final_portfolio - self.initial_balance) / self.initial_balance
            
            # Additional reward at the end based on overall performance
            if roi > 0:
                reward += roi * 20  # Bonus reward for positive ROI
            else:
                reward += roi * 10  # Penalty for negative ROI
            
            info['final_portfolio'] = final_portfolio
            info['roi'] = roi
        
        return self._get_state(), reward, done, info
    
    def portfolio_value(self):
        """
        Calculate current total portfolio value
        
        Returns:
            Total portfolio value (cash + all token positions)
        """
        # Start with cash balance
        total_value = self.balance
        
        # Add value of all token positions
        for token in self.tokens:
            if self.positions[token] > 0:
                current_price = self.price_data_dict[token].iloc[min(self.current_step, len(self.price_data_dict[token])-1)]['close']
                token_value = self.positions[token] * current_price
                total_value += token_value
        
        return total_value
    
    def portfolio_summary(self):
        """
        Get a summary of the current portfolio
        
        Returns:
            Dictionary with portfolio summary
        """
        portfolio_value = self.portfolio_value()
        allocation = self._get_portfolio_allocation()
        
        # Calculate unrealized P&L
        unrealized_pnl = sum(self.unrealized_profit.values())
        unrealized_pnl_pct = (unrealized_pnl / (portfolio_value - unrealized_pnl)) * 100 if portfolio_value > unrealized_pnl else 0
        
        # Calculate realized P&L
        realized_pnl = sum(self.realized_profit.values())
        
        return {
            'portfolio_value': portfolio_value,
            'cash_balance': self.balance,
            'cash_allocation': self.balance / portfolio_value if portfolio_value > 0 else 1.0,
            'token_allocation': allocation,
            'positions': self.positions,
            'unrealized_pnl': unrealized_pnl,
            'unrealized_pnl_pct': unrealized_pnl_pct,
            'realized_pnl': realized_pnl,
            'max_drawdown': self.max_drawdown * 100,  # As percentage
            'num_positions': sum(1 for p in self.positions.values() if p > 0),
            'total_trades': sum(self.total_trades.values()),
            'winning_trades': sum(self.winning_trades.values()),
            'win_rate': sum(self.winning_trades.values()) / max(1, sum(self.total_trades.values())) * 100,
        } 