import tensorflow as tf
import numpy as np
from typing import Dict, Tuple
import re
import pandas as pd
from typing import List
import os
from datetime import timezone, timedelta

from utils.logger import log # Import the configured logger instance
logger = log # Assign to the 'logger' variable used in this module

def denormalize_data(data, scale=1.0, offset=0.0):
    """Helper function to denormalize data if needed"""
    return data * scale + offset

def direction_accuracy(y_true, y_pred):
    """
    Calculate directional accuracy based on actual price movements.
    
    IMPORTANT: This function assumes y_true and y_pred represent actual price values,
    not normalized/scaled values. For meaningful directional accuracy, the inputs
    should be in the same scale as actual prices.
    
    Args:
        y_true: True price values (should be actual prices, not normalized)
        y_pred: Predicted price values (should be actual prices, not normalized)
    
    Returns:
        Directional accuracy as a float between 0 and 1
    """
    # Cast to float32 to ensure consistent types
    y_true = tf.cast(y_true, tf.float32)
    y_pred = tf.cast(y_pred, tf.float32)
    
    # Calculate price changes from previous time step
    # For the first element, we can't calculate change, so we'll skip it
    if tf.shape(y_true)[0] <= 1:
        return tf.constant(0.0, dtype=tf.float32)
    
    # Calculate actual and predicted price changes
    true_changes = y_true[1:] - y_true[:-1]
    pred_changes = y_pred[1:] - y_true[:-1]  # Compare predicted vs previous actual
    
    # Get direction signs (1 for up, -1 for down, 0 for no change)
    true_directions = tf.sign(true_changes)
    pred_directions = tf.sign(pred_changes)
    
    # Calculate if directions match (1 if match, 0 if not)
    direction_matches = tf.cast(tf.equal(true_directions, pred_directions), tf.float32)
    
    # Create mask to ignore very small changes (less than 0.1% might be noise)
    epsilon = tf.constant(0.001, dtype=tf.float32)  # 0.1% threshold
    significant_changes = tf.greater(tf.abs(true_changes), epsilon * tf.abs(y_true[:-1]))
    significant_mask = tf.cast(significant_changes, tf.float32)
    
    # Count matches only for significant price movements
    match_count = tf.reduce_sum(direction_matches * significant_mask)
    valid_count = tf.reduce_sum(significant_mask)
    
    # Avoid division by zero
    accuracy = tf.cond(
        tf.greater(valid_count, 0),
        lambda: match_count / valid_count,
        lambda: tf.constant(0.0, dtype=tf.float32)
    )
    
    return accuracy

def profit_loss(y_true, y_pred, transaction_cost_pct=0.001, debug=False):
    """
    Custom loss function that maximizes trading profit.
    
    Args:
        y_true: True price values
        y_pred: Predicted price values
        transaction_cost_pct: Trading fee as percentage of trade value
        debug: Whether to print debug information
    
    Returns:
        Loss value (negative profit)
    """
    # Ensure consistent data types - cast inputs to float32 to avoid mixed precision issues
    y_true = tf.cast(y_true, tf.float32)
    y_pred = tf.cast(y_pred, tf.float32)
    
    # Small epsilon to prevent division by zero
    epsilon = tf.keras.backend.epsilon()
    
    # Get price at previous timestep (for calculating returns)
    prev_price = tf.concat([tf.zeros_like(y_true[:, :1]) + epsilon, y_true[:, :-1]], axis=1)
    prev_price = tf.maximum(prev_price, epsilon)  # Ensure no zeros
    
    # Calculate actual price change percentage
    actual_returns = (y_true - prev_price) / (prev_price + epsilon)
    
    # Calculate predicted price change percentage
    pred_returns = (y_pred - prev_price) / (prev_price + epsilon)
    
    # Clip returns to prevent extreme values
    actual_returns = tf.clip_by_value(actual_returns, -0.5, 0.5)
    pred_returns = tf.clip_by_value(pred_returns, -0.5, 0.5)
    
    # Add small bias to encourage directional predictions (prevent all zeros)
    biased_returns = pred_returns + 1e-7  # Tiny bias toward buy signals
    
    # Get trading signals: 1 for buy (predicted increase), -1 for sell (predicted decrease), 0 for hold
    pred_signals = tf.sign(biased_returns)
    
    if debug:
        # Count number of each signal type
        buy_signals = tf.reduce_sum(tf.cast(tf.greater(pred_signals, 0), tf.float32))
        sell_signals = tf.reduce_sum(tf.cast(tf.less(pred_signals, 0), tf.float32))
        hold_signals = tf.reduce_sum(tf.cast(tf.equal(pred_signals, 0), tf.float32))
        tf.print("Signals - Buy:", buy_signals, "Sell:", sell_signals, "Hold:", hold_signals)
    
    # Simulation of position constraints (can't sell what you don't own)
    # Start with no position
    position = tf.zeros_like(y_true[:,0], dtype=tf.float32)
    modified_signals = tf.TensorArray(tf.float32, size=tf.shape(pred_signals)[1])
    
    # Loop through each time step
    for i in range(tf.shape(pred_signals)[1]):
        current_signals = pred_signals[:, i]
        
        # Can only sell if we have a position (position > 0)
        valid_sell = tf.logical_and(current_signals < 0, position > 0)
        # Can always buy
        valid_buy = current_signals > 0
        
        # Update signals based on constraints
        valid_signals = tf.where(valid_sell, -1.0, 0.0)
        valid_signals = tf.where(valid_buy, 1.0, valid_signals)
        
        # Ensure valid_signals has the same dtype as position
        valid_signals = tf.cast(valid_signals, position.dtype)
        
        # Update position
        position = position + valid_signals
        
        # Store the valid signals
        modified_signals = modified_signals.write(i, valid_signals)
    
    # Convert back to tensor
    modified_signals = tf.transpose(modified_signals.stack())
    
    if debug:
        total_active_signals = tf.reduce_sum(tf.abs(modified_signals))
        tf.print("Total trading actions:", total_active_signals)
    
    # Calculate profit from each trade (actual return * valid prediction direction)
    # This is positive when we correctly predict direction, negative when wrong
    trade_profit = actual_returns * modified_signals
    
    # Apply transaction costs (only for non-zero signals)
    transaction_costs = transaction_cost_pct * tf.abs(modified_signals)
    net_profit = trade_profit - transaction_costs
    
    # Mask out the first timestep (where we don't have previous data)
    mask = tf.concat([tf.zeros_like(y_true[:, :1]), tf.ones_like(y_true[:, 1:])], axis=1)
    masked_profit = net_profit * mask
    
    # Mix with MSE loss for numerical stability
    profit_loss = -tf.reduce_mean(masked_profit)
    mse_loss = tf.reduce_mean(tf.square(y_true - y_pred))
    
    # Return a mix of profit loss and MSE with a small weight on MSE
    # This helps stabilize training while still optimizing for profit
    mixed_loss = profit_loss + 0.1 * mse_loss
    
    # Safety check for NaN or Inf values
    return tf.where(
        tf.math.is_finite(mixed_loss),
        mixed_loss,
        1.0 + mse_loss  # Fallback to MSE if profit loss becomes unstable
    )

def directional_loss(y_true, y_pred):
    """
    Loss function that penalizes incorrect prediction of price movement direction
    
    Args:
        y_true: True price values
        y_pred: Predicted price values
    
    Returns:
        Loss value
    """
    # Get price at previous timestep
    prev_price = tf.concat([tf.zeros_like(y_true[:, :1]), y_true[:, :-1]], axis=1)
    
    # Calculate actual and predicted directions
    actual_direction = tf.sign(y_true - prev_price)
    pred_direction = tf.sign(y_pred - prev_price)
    
    # Direction error: 0 when correct, 2 when completely wrong
    direction_error = tf.abs(actual_direction - pred_direction) / 2.0
    
    # Mask out the first timestep
    mask = tf.concat([tf.zeros_like(y_true[:, :1]), tf.ones_like(y_true[:, 1:])], axis=1)
    masked_error = direction_error * mask
    
    return tf.reduce_mean(masked_error)

def combined_profit_mse_loss(y_true, y_pred, profit_weight=0.7, mse_weight=0.3, transaction_cost_pct=0.001):
    """
    Combined loss function with both profit and MSE components
    
    Args:
        y_true: True price values
        y_pred: Predicted price values
        profit_weight: Weight for the profit component
        mse_weight: Weight for the MSE component
        transaction_cost_pct: Trading fee percentage
    
    Returns:
        Combined loss value
    """
    # Ensure consistent data types
    y_true = tf.cast(y_true, tf.float32)
    y_pred = tf.cast(y_pred, tf.float32)
    
    profit_component = profit_loss(y_true, y_pred, transaction_cost_pct)
    mse_component = tf.keras.losses.mean_squared_error(y_true, y_pred)
    
    # Normalize profit component (can be large compared to MSE)
    # This scaling factor might need adjustment based on data
    profit_scale = 10.0
    
    return profit_weight * (profit_component / profit_scale) + mse_weight * mse_component

# Metrics for tracking performance during training and evaluation

def cumulative_return_metric(y_true, y_pred, transaction_cost_pct=0.001, price_scale=1.0):
    """
    Metric to track cumulative return during training
    
    Args:
        y_true: True price values
        y_pred: Predicted price values
        transaction_cost_pct: Trading fee percentage
        price_scale: Factor to scale normalized prices to a more realistic range
    
    Returns:
        Cumulative return value
    """
    # Ensure consistent data types
    y_true = tf.cast(y_true, tf.float32)
    y_pred = tf.cast(y_pred, tf.float32)
    
    # For proper trading metrics, we need reasonable price changes relative to the price scale
    # Scale the data to ensure sufficient movement
    if price_scale != 1.0:
        # Don't actually scale for metric calculation, as it could break gradients
        # Instead, scale the return calculation threshold for signal generation
        min_return_threshold = 1e-6 / price_scale
    else:
        min_return_threshold = 1e-6
    
    # Small epsilon to prevent division by zero
    epsilon = tf.keras.backend.epsilon()
    
    # Get price at previous timestep
    prev_price = tf.concat([tf.zeros_like(y_true[:, :1]) + epsilon, y_true[:, :-1]], axis=1)
    prev_price = tf.maximum(prev_price, epsilon)  # Ensure no zeros
    
    # Calculate actual returns
    actual_returns = (y_true - prev_price) / (prev_price + epsilon)
    
    # Calculate predicted returns
    pred_returns = (y_pred - prev_price) / (prev_price + epsilon)
    
    # Clip returns to prevent extreme values
    actual_returns = tf.clip_by_value(actual_returns, -0.5, 0.5)
    pred_returns = tf.clip_by_value(pred_returns, -0.5, 0.5)
    
    # Add small bias to encourage non-zero directional predictions
    biased_returns = pred_returns + min_return_threshold
    
    # Get simple directional signals and ensure they're non-zero
    pred_signals = tf.sign(biased_returns)
    
    # Create a simplified trading simulation for the metric
    trade_returns = actual_returns * pred_signals
    
    # Apply transaction costs
    transaction_costs = transaction_cost_pct * tf.abs(pred_signals)
    net_returns = trade_returns - transaction_costs
    
    # Mask out the first timestep
    mask = tf.concat([tf.zeros_like(y_true[:, :1]), tf.ones_like(y_true[:, 1:])], axis=1)
    masked_returns = net_returns * mask
    
    # Calculate cumulative return (sum of returns)
    return tf.reduce_sum(masked_returns)

def win_rate_metric(y_true, y_pred, price_scale=1.0):
    """
    Metric to track win rate (percentage of profitable trades)
    
    Args:
        y_true: True price values
        y_pred: Predicted price values
        price_scale: Factor to scale normalized prices to a more realistic range
    
    Returns:
        Win rate (0.0 to 1.0)
    """
    # Ensure consistent data types
    y_true = tf.cast(y_true, tf.float32)
    y_pred = tf.cast(y_pred, tf.float32)
    
    # For proper trading metrics, we need reasonable price changes relative to the price scale
    # Scale the data to ensure sufficient movement
    if price_scale != 1.0:
        # Don't actually scale for metric calculation, as it could break gradients
        # Instead, scale the return calculation threshold for signal generation
        min_return_threshold = 1e-6 / price_scale
    else:
        min_return_threshold = 1e-6
    
    # Small epsilon to prevent division by zero
    epsilon = tf.keras.backend.epsilon()
    
    # Get price at previous timestep
    prev_price = tf.concat([tf.zeros_like(y_true[:, :1]) + epsilon, y_true[:, :-1]], axis=1)
    prev_price = tf.maximum(prev_price, epsilon)  # Ensure no zeros
    
    # Calculate actual returns
    actual_returns = (y_true - prev_price) / (prev_price + epsilon)
    
    # Calculate predicted direction
    pred_returns = (y_pred - prev_price) / (prev_price + epsilon)
    
    # Add small bias to encourage non-zero directional predictions
    biased_returns = pred_returns + min_return_threshold
    
    # Get directional signals (ignoring zero changes)
    pred_signals = tf.sign(biased_returns)
    
    # Calculate trade results - profitable when signal matches direction
    trade_profit = actual_returns * pred_signals
    
    # Count winning trades (profitable after counting transaction cost)
    transaction_cost = 0.001  # 0.1% fee
    wins = tf.cast(trade_profit > transaction_cost, tf.float32)
    
    # Count total trades (non-zero signals)
    trades = tf.cast(tf.abs(pred_signals) > 0, tf.float32)
    
    # Mask out the first timestep
    mask = tf.concat([tf.zeros_like(y_true[:, :1]), tf.ones_like(y_true[:, 1:])], axis=1)
    masked_wins = wins * mask
    masked_trades = trades * mask
    
    # Calculate win rate
    total_wins = tf.reduce_sum(masked_wins)
    total_trades = tf.reduce_sum(masked_trades)
    
    return tf.math.divide_no_nan(total_wins, total_trades)

def sharpe_ratio_metric(y_true, y_pred, risk_free_rate=0.0, transaction_cost_pct=0.001, price_scale=1.0):
    """
    Metric to track Sharpe ratio
    
    Args:
        y_true: True price values
        y_pred: Predicted price values
        risk_free_rate: Annual risk-free rate
        transaction_cost_pct: Trading fee percentage
        price_scale: Factor to scale normalized prices to a more realistic range
    
    Returns:
        Sharpe ratio
    """
    # Ensure consistent data types
    y_true = tf.cast(y_true, tf.float32)
    y_pred = tf.cast(y_pred, tf.float32)
    
    # For proper trading metrics, we need reasonable price changes relative to the price scale
    # Scale the data to ensure sufficient movement
    if price_scale != 1.0:
        # Don't actually scale for metric calculation, as it could break gradients
        # Instead, scale the return calculation threshold for signal generation
        min_return_threshold = 1e-6 / price_scale
    else:
        min_return_threshold = 1e-6
    
    # Small epsilon to prevent division by zero
    epsilon = tf.keras.backend.epsilon()
    
    # Get price at previous timestep
    prev_price = tf.concat([tf.zeros_like(y_true[:, :1]) + epsilon, y_true[:, :-1]], axis=1)
    prev_price = tf.maximum(prev_price, epsilon)  # Ensure no zeros
    
    # Calculate actual returns
    actual_returns = (y_true - prev_price) / (prev_price + epsilon)
    
    # Calculate predicted direction
    pred_returns = (y_pred - prev_price) / (prev_price + epsilon)
    
    # Clip returns to prevent extreme values
    actual_returns = tf.clip_by_value(actual_returns, -0.5, 0.5)
    pred_returns = tf.clip_by_value(pred_returns, -0.5, 0.5)
    
    # Add small bias to encourage non-zero directional predictions
    biased_returns = pred_returns + min_return_threshold
    
    # Get trading signals
    pred_signals = tf.sign(biased_returns)
    
    # Calculate profit from each trade
    trade_profit = actual_returns * pred_signals
    
    # Apply transaction costs
    transaction_costs = transaction_cost_pct * tf.abs(pred_signals)
    net_profit = trade_profit - transaction_costs
    
    # Mask out the first timestep
    mask = tf.concat([tf.zeros_like(y_true[:, :1]), tf.ones_like(y_true[:, 1:])], axis=1)
    masked_profit = net_profit * mask
    
    # Calculate mean and std of returns
    mean_return = tf.reduce_mean(masked_profit)
    
    # Handle potential zeros by adding epsilon
    squared_diffs = tf.square(masked_profit - mean_return)
    avg_squared_diff = tf.reduce_mean(squared_diffs)
    std_return = tf.sqrt(avg_squared_diff + epsilon)
    
    # Daily risk-free rate (assuming 252 trading days per year)
    daily_rfr = risk_free_rate / 252.0
    
    # Calculate Sharpe ratio (annualized by multiplying by sqrt(252))
    return tf.math.multiply(
        tf.math.divide_no_nan(mean_return - daily_rfr, std_return),
        tf.constant(15.87, dtype=tf.float32)  # sqrt(252)
    )

def backtest_trades(prices, predictions, transaction_cost_pct=0.001):
    """
    Backtest trading strategy based on price predictions
    
    Args:
        prices: Array of actual prices
        predictions: Array of predicted prices
        transaction_cost_pct: Trading fee percentage
        
    Returns:
        Dictionary with backtest results
    """
    if len(prices) != len(predictions):
        raise ValueError("Prices and predictions must have the same length")
    
    # Initialize variables
    position = 0  # 0: no position, 1: long position (holding tokens)
    entry_price = 0
    cash = 10000.0  # Starting capital
    portfolio_value = []
    trades = []
    
    tokens_held = 0  # Track exact number of tokens held
    consecutive_losses = 0  # Track consecutive losses for risk management
    max_consecutive_losses = 3  # Stop trading after this many consecutive losses
    
    # Calculate moving averages for trend confirmation
    window = 12  # 1-hour window (assuming 5-minute data)
    if len(prices) > window:
        sma = np.convolve(prices, np.ones(window)/window, mode='valid')
        # Pad the beginning to match length
        sma = np.concatenate([np.full(window-1, sma[0]), sma])
    else:
        sma = prices  # If not enough data, just use prices
    
    for i in range(1, len(prices)):
        # Skip early periods where we don't have enough history
        if i < window:
            portfolio_value.append(cash)
            continue
            
        # Calculate predicted direction and confidence based on previous price
        pred_return = (predictions[i] - prices[i-1]) / prices[i-1]
        
        # Trend confirmation - only buy in uptrends, only sell in downtrends
        trend_up = prices[i-1] > sma[i-1]
        trend_down = prices[i-1] < sma[i-1]
        
        # Enhanced signal generation with trend confirmation and confidence thresholds
        buy_threshold = 0.005  # 0.5%
        sell_threshold = -0.005  # -0.5%
        
        # Generate signal: 1 = buy, -1 = sell, 0 = hold
        # Only buy in confirmed uptrends with strong signal
        if pred_return > buy_threshold and trend_up and consecutive_losses < max_consecutive_losses:
            signal = 1
        # Only sell in confirmed downtrends with strong signal, or if we hit stop loss
        elif (pred_return < sell_threshold and trend_down) or (position == 1 and (prices[i] < entry_price * 0.97)):
            signal = -1
        # Also sell if we have a profit target (10% gain)
        elif position == 1 and prices[i] > entry_price * 1.10:
            signal = -1
        else:
            signal = 0
        
        # Current portfolio value
        current_price = prices[i]
        current_value = cash + (tokens_held * current_price)
        portfolio_value.append(current_value)
        
        # Execute trades with position constraints
        if signal == 1 and position == 0 and cash > 0:  # BUY signal, no position, and we have cash
            # Calculate how many tokens we can buy
            # Only use 95% of available cash to leave room for fees
            amount_to_spend = cash * 0.95
            fee = amount_to_spend * transaction_cost_pct
            tokens_to_buy = (amount_to_spend - fee) / current_price
            
            # Update state
            tokens_held = tokens_to_buy
            cash -= (amount_to_spend) 
            position = 1
            entry_price = current_price
            
            # Record trade
            trades.append({
                'timestamp': i,
                'action': 'buy',
                'price': current_price,
                'tokens': tokens_to_buy,
                'cost': fee,
                'cash_spent': amount_to_spend,
                'remaining_cash': cash,
                'tokens_held': tokens_held,
                'portfolio_value': current_value
            })
            
        elif signal == -1 and position == 1 and tokens_held > 0:  # SELL signal and we have tokens
            # Calculate value and fee
            amount_received = tokens_held * current_price
            fee = amount_received * transaction_cost_pct
            
            # Calculate profit
            profit = amount_received - fee - (tokens_held * entry_price)
            
            # Update consecutive loss counter
            if profit <= 0:
                consecutive_losses += 1
            else:
                consecutive_losses = 0
            
            # Update state
            cash += (amount_received - fee)
            tokens_held = 0
            position = 0
            
            # Record trade
            trades.append({
                'timestamp': i,
                'action': 'sell',
                'price': current_price,
                'tokens': tokens_held,
                'cost': fee,
                'cash_received': amount_received - fee,
                'profit': profit,
                'remaining_cash': cash,
                'tokens_held': 0,
                'portfolio_value': current_value
            })
    
    # Close final position if open
    if tokens_held > 0:
        # Calculate value and fee
        final_price = prices[-1]
        amount_received = tokens_held * final_price
        fee = amount_received * transaction_cost_pct
        
        # Calculate profit
        profit = amount_received - fee - (tokens_held * entry_price)
        
        # Update state
        cash += (amount_received - fee)
        
        # Record trade
        trades.append({
            'timestamp': len(prices) - 1,
            'action': 'sell',
            'price': final_price,
            'tokens': tokens_held,
            'cost': fee,
            'cash_received': amount_received - fee,
            'profit': profit,
            'remaining_cash': cash,
            'tokens_held': 0,
            'portfolio_value': cash
        })
    
    # Calculate metrics
    initial_cash = 10000.0
    final_value = cash
    total_return = (final_value - initial_cash) / initial_cash
    
    # Buy and hold strategy return
    buy_hold_return = (prices[-1] - prices[0]) / prices[0]
    
    # Calculate wins and losses
    wins = sum(1 for trade in trades if 'profit' in trade and trade['profit'] > 0)
    losses = sum(1 for trade in trades if 'profit' in trade and trade['profit'] <= 0)
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0
    
    # Calculate average profit per trade
    total_profit = sum(trade.get('profit', 0) for trade in trades if 'profit' in trade)
    avg_profit_per_trade = total_profit / (wins + losses) if (wins + losses) > 0 else 0
    
    # Calculate max drawdown CORRECTLY - portfolio peak to trough
    max_drawdown = 0.0
    portfolio_peak = initial_cash
    
    for value in portfolio_value:
        # Skip invalid values
        if not np.isfinite(value) or value <= 0:
            continue
            
        # Update peak
        if value > portfolio_peak:
            portfolio_peak = value
        
        # Calculate current drawdown from peak
        if portfolio_peak > 0:
            current_drawdown = (portfolio_peak - value) / portfolio_peak
            max_drawdown = max(max_drawdown, current_drawdown)
    
    # Remove the old portfolio-based drawdown debug info since it was incorrect
    # Print corrected drawdown analysis
    verbosity = verbosity if 'verbosity' in locals() else 0  # Safety check
    if verbosity > 0 and max_drawdown > 0.05:  # Only log significant position drawdowns
        print(f"\n📊 PORTFOLIO DRAWDOWN ANALYSIS:")
        print(f"Max Portfolio Drawdown: {max_drawdown:.2%} (peak to trough)")
        print(f"  Portfolio peak: ${portfolio_peak:.2f}")
        print(f"  Minimum portfolio value: ${min(portfolio_value):.2f}")
        print(f"  Buy & Hold decline: {buy_hold_return:.2%}")
        print(f"  Strategy vs Buy & Hold: {(total_return - buy_hold_return):.2%} {'better' if total_return > buy_hold_return else 'worse'}")
    
    # Cap maximum drawdown at reasonable levels  
    max_drawdown = min(max_drawdown, 0.6)
    
    return {
        'total_return': total_return,
        'buy_hold_return': buy_hold_return,
        'final_value': final_value,
        'win_rate': win_rate,
        'avg_profit_per_trade': avg_profit_per_trade,
        'max_drawdown': max_drawdown,
        'total_trades': len(trades) // 2,  # Each round trip is 2 trades
        'portfolio_value': portfolio_value,
        'trades': trades
    }

def simple_directional_loss(y_true, y_pred):
    """
    Simple loss function that optimizes for our trading strategy.
    - Strongly penalizes predicting wrong direction
    - Adds a mild penalty for magnitude errors
    - Adds extra penalty for missing large downward moves (which we need for stop-losses)
    
    Args:
        y_true: True price values/changes
        y_pred: Predicted price values/changes
    
    Returns:
        Loss value (lower is better)
    """
    # Cast to float32 to ensure consistent types
    y_true = tf.cast(y_true, tf.float32)
    y_pred = tf.cast(y_pred, tf.float32)
    
    # Calculate directions (up=positive, down=negative)
    true_direction = tf.sign(y_true)
    pred_direction = tf.sign(y_pred)
    
    # 1. Direction component - heavily penalize wrong directions
    # Calculate if directions match (1 = match, 0 = mismatch)
    direction_match = tf.cast(tf.equal(true_direction, pred_direction), tf.float32)
    direction_loss = 1.0 - tf.reduce_mean(direction_match)  # 0 if all directions match
    
    # 2. Magnitude component - mildly penalize magnitude errors
    # Use mean squared error between predictions and targets
    magnitude_loss = tf.reduce_mean(tf.square(y_true - y_pred))
    
    # 3. Special case - heavily penalize missing large downward moves
    # Identify large downward moves (true change < -3%)
    large_down_moves = tf.cast(y_true < -0.03, tf.float32)
    # Check if we correctly predicted the direction for these moves
    correct_down_preds = large_down_moves * tf.cast(y_pred < 0, tf.float32)
    # Only apply if we have large down moves
    has_large_downs = tf.reduce_sum(large_down_moves)
    down_move_accuracy = tf.cond(
        has_large_downs > 0,
        lambda: tf.reduce_sum(correct_down_preds) / has_large_downs,
        lambda: tf.constant(1.0, dtype=tf.float32)  # No down moves, so "perfect" score
    )
    down_move_loss = 1.0 - down_move_accuracy
    
    # Combine losses with appropriate weights
    # Direction is most important (60%), followed by catching down moves (30%), 
    # then general magnitude (10%)
    combined_loss = 0.6 * direction_loss + 0.3 * down_move_loss + 0.1 * magnitude_loss
    
    return combined_loss

def simple_backtest_strategy(prices, predictions, ohlcv_df=None, include_detailed_trades=False, verbosity=0, resolution="1H",
                             buy_threshold=0.02,  # Buy when predicted increase >= 2%
                             sell_threshold=0.03,  # Sell when predicted decrease >= 3%
                             **kwargs):  # Accept any additional parameters but ignore them
    """
    SIMPLE magnitude-based backtest strategy:
    - Buy when predicted price increase >= buy_threshold (default 2%)
    - Hold when predicted price change >= -sell_threshold (not falling by more than sell_threshold)
    - Sell when predicted price decrease >= sell_threshold (default 3%)
    
    Args:
        prices (np.array): Array of actual close prices.
        predictions (np.array): Array of predicted close prices (1-step ahead).
        ohlcv_df (pd.DataFrame): DataFrame with OHLCV data (optional, for compatibility).
        include_detailed_trades (bool): If True, returns a list of all trades.
        verbosity (int): Logging level for trade details.
        resolution (str): Time resolution of data (e.g., "1H", "15m").
        buy_threshold (float): Percentage prediction must be above current price to buy.
        sell_threshold (float): Percentage prediction must be below current price to sell.
        **kwargs: Any additional parameters (ignored for compatibility with optimization).
        
    Returns:
        dict: Dictionary containing backtest performance metrics.
    """
    
    initial_cash = 10000
    cash = initial_cash
    tokens_held = 0
    position = 0  # 0 = no position, 1 = long
    entry_price = 0
    portfolio_values = [initial_cash]
    trades = []
    
    # Position sizing - use 90% of available cash
    position_size_pct = 0.10
    
    if verbosity > 0:
        logger.info(f"Simple Magnitude Strategy - Buy Threshold: {buy_threshold*100:.1f}%, Sell Threshold: {sell_threshold*100:.1f}%")
    
    for i in range(1, len(prices)):
        current_price = float(prices[i])
        prediction_value = float(predictions[i])  # Model's predicted price for the next period
        
        # Calculate predicted price change percentage
        prediction_change_pct = (prediction_value / current_price - 1) if current_price > 0 else 0
        
        # Calculate current portfolio value
        current_value = cash + (tokens_held * current_price)
        portfolio_values.append(current_value)
        
        # Trading Logic
        if position == 0:  # No position - check for BUY signal
            # Buy when predicted increase >= buy_threshold (e.g., 2%)
            if prediction_change_pct >= buy_threshold and cash > 100:
                trade_amount = cash * position_size_pct
                trade_fee = trade_amount * 0.005  # 0.5% fee
                amount_to_spend = trade_amount - trade_fee
                
                if amount_to_spend > 0:
                    tokens_bought = amount_to_spend / current_price
                    cash -= trade_amount
                    tokens_held += tokens_bought
                    position = 1
                    entry_price = current_price
                    
                    if verbosity > 0:
                        logger.info(f"BUY at step {i}: price=${current_price:.4f}, predicted_change={prediction_change_pct*100:.2f}%, tokens={tokens_bought:.2f}")
                    
                    trades.append({
                        'type': 'buy',
                        'step': i,
                        'price': current_price,
                        'tokens': tokens_bought,
                        'value': amount_to_spend,
                        'fee': trade_fee,
                        'predicted_change_pct': prediction_change_pct * 100
                    })
        
        elif position == 1:  # Have position - check for SELL signal
            # Sell when predicted decrease >= sell_threshold (e.g., -3%)
            if prediction_change_pct <= -sell_threshold:
                trade_value = tokens_held * current_price
                trade_fee = trade_value * 0.005  # 0.5% fee
                net_proceeds = trade_value - trade_fee
                cash += net_proceeds
                
                # Calculate profit
                total_cost = entry_price * tokens_held * 1.005  # Original cost + buy fee
                profit = net_proceeds - total_cost
                
                if verbosity > 0:
                    return_pct = (current_price / entry_price - 1) * 100
                    logger.info(f"SELL at step {i}: price=${current_price:.4f}, predicted_change={prediction_change_pct*100:.2f}%, return={return_pct:.2f}%, profit=${profit:.2f}")
                
                trades.append({
                    'type': 'sell',
                    'reason': 'magnitude_signal',
                    'step': i,
                    'price': current_price,
                    'tokens': tokens_held,
                    'value': trade_value,
                    'fee': trade_fee,
                    'profit': profit,
                    'entry_price': entry_price,
                    'return_pct': (current_price / entry_price - 1) * 100,
                    'predicted_change_pct': prediction_change_pct * 100
                })
                
                tokens_held = 0
                position = 0
                entry_price = 0
            
            # Otherwise HOLD (prediction_change_pct > -sell_threshold)
            elif verbosity > 1:
                logger.debug(f"HOLD at step {i}: price=${current_price:.4f}, predicted_change={prediction_change_pct*100:.2f}%")

    # If still holding at the end, liquidate
    if position == 1 and tokens_held > 0:
        final_price = float(prices[-1])
        trade_value = tokens_held * final_price
        trade_fee = trade_value * 0.005
        net_proceeds = trade_value - trade_fee
        cash += net_proceeds
        
        # Calculate profit
        total_cost = entry_price * tokens_held * 1.005  # Original cost + buy fee
        profit = net_proceeds - total_cost
        
        if verbosity > 0:
            return_pct = (final_price / entry_price - 1) * 100
            logger.info(f"SELL (end_of_data) at step {len(prices)-1}: price=${final_price:.4f}, return={return_pct:.2f}%, profit=${profit:.2f}")
        
        trades.append({
            'type': 'sell',
            'reason': 'end_of_data',
            'step': len(prices)-1,
            'price': final_price,
            'tokens': tokens_held,
            'value': trade_value,
            'fee': trade_fee,
            'profit': profit,
            'entry_price': entry_price,
            'return_pct': (final_price / entry_price - 1) * 100
        })
        tokens_held = 0

    # --- Performance Metrics ---
    portfolio_values = np.array(portfolio_values)
    total_return_pct = (portfolio_values[-1] / initial_cash - 1) * 100
    
    # Buy and Hold benchmark
    buy_and_hold_return_pct = (prices[-1] / prices[0] - 1) * 100 if len(prices) > 0 and prices[0] > 0 else 0

    # Trade statistics
    buy_trades = [trade for trade in trades if trade['type'] == 'buy']
    sell_trades = [trade for trade in trades if trade['type'] == 'sell']
    
    num_trades = len(buy_trades)
    winning_trades = sum(1 for trade in sell_trades if trade['profit'] > 0)
    losing_trades = sum(1 for trade in sell_trades if trade['profit'] <= 0)
    win_rate_pct = (winning_trades / len(sell_trades) * 100) if len(sell_trades) > 0 else 0

    # Calculate Sharpe Ratio
    returns = pd.Series(portfolio_values).pct_change().dropna()
    
    # Annualization factor based on resolution
    periods_per_day = 1
    if 'm' in resolution.lower(): 
        periods_per_day = 1440 // int(resolution.lower().replace('m',''))
    elif 'h' in resolution.lower(): 
        periods_per_day = 24 // int(resolution.lower().replace('h',''))
    elif 'd' in resolution.lower(): 
        periods_per_day = 1
    
    annual_trading_days = 365
    annualization_factor = annual_trading_days * periods_per_day

    if len(returns) > 1 and returns.std() != 0:
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(annualization_factor)
    else:
        sharpe_ratio = 0.0
    
    # Max Drawdown
    peak = portfolio_values[0]
    drawdown = np.zeros_like(portfolio_values)
    for i in range(len(portfolio_values)):
        if portfolio_values[i] > peak:
            peak = portfolio_values[i]
        drawdown[i] = (peak - portfolio_values[i]) / peak if peak > 0 else 0
    max_drawdown_pct = np.max(drawdown) * 100

    results = {
        "Total Return": total_return_pct,
        "Buy & Hold Return": buy_and_hold_return_pct,
        "Win Rate": win_rate_pct,
        "Max Drawdown": max_drawdown_pct,
        "Sharpe Ratio": sharpe_ratio,
        "Total Trades": num_trades,
        "Final Portfolio Value": portfolio_values[-1]
    }
    
    if include_detailed_trades:
        results['trades'] = trades
        results['portfolio_history'] = portfolio_values.tolist()
        
    return results

def plot_backtest_with_signals(
    ohlcv_data: pd.DataFrame,
    trades: List[Dict],
    filename: str = None,
    title: str = "Backtest Results with Trade Signals",
    output_dir: str = "models"
):
    """
    Plot backtest results with buy/sell signals on a candlestick chart
    
    Args:
        ohlcv_data: DataFrame with OHLCV data (must include timestamp, open, high, low, close)
        trades: List of trade dictionaries from backtest_trades or simple_backtest_strategy
        filename: Optional filename to save the plot
        title: Title for the plot
        output_dir: Directory to save the plot
        
    Returns:
        Path to saved plot file, or None if plotting failed
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import numpy as np
        import os
        from datetime import datetime
        
        # Validate and clean data
        df = ohlcv_data.copy()
        
        # Ensure we have required columns
        required_cols = ['timestamp', 'open', 'high', 'low', 'close']
        for col in required_cols:
            if col not in df.columns:
                print(f"Error: Missing required column '{col}' in OHLCV data")
                return None
        
        # Handle timestamp conversion safely
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            # Use safer conversion with errors='coerce' to handle invalid timestamps
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            
            # Fill any NaT values with reasonable timestamps
            if df['timestamp'].isna().any():
                print(f"Warning: Found {df['timestamp'].isna().sum()} invalid timestamps, replacing with default values")
                start_date = datetime.now() - timedelta(days=len(df))
                for i, idx in enumerate(df.index[df['timestamp'].isna()]):
                    df.loc[idx, 'timestamp'] = start_date + timedelta(days=i)
        
        # Check for extreme timestamp values and fix them
        min_valid_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
        max_valid_date = datetime(2050, 1, 1, tzinfo=timezone.utc)
        
        # Replace extreme dates with reasonable defaults
        try:
            mask = (df['timestamp'] < min_valid_date) | (df['timestamp'] > max_valid_date)
            if mask.any():
                print(f"Warning: Found {mask.sum()} extreme timestamp values, replacing with defaults")
                start_date = datetime.now(timezone.utc) - timedelta(days=len(df))
                for i, idx in enumerate(df.index[mask]):
                    df.loc[idx, 'timestamp'] = start_date + timedelta(days=i)
        except TypeError as e:
            # Handle mixed timezone issues by converting all to timezone-aware
            print(f"Warning: Timezone comparison issue, converting timestamps: {e}")
            if not df['timestamp'].dt.tz:
                # If timestamps are naive, assume UTC
                df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
            else:
                # If timestamps are already timezone-aware, convert to UTC
                df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
            
            # Retry the comparison with UTC timestamps
            mask = (df['timestamp'] < min_valid_date) | (df['timestamp'] > max_valid_date)
            if mask.any():
                print(f"Warning: Found {mask.sum()} extreme timestamp values, replacing with defaults")
                start_date = datetime.now(timezone.utc) - timedelta(days=len(df))
                for i, idx in enumerate(df.index[mask]):
                    df.loc[idx, 'timestamp'] = start_date + timedelta(days=i)
        
        # Create figure and subplots (price, volume, portfolio)
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 16), gridspec_kw={'height_ratios': [3, 1, 2]})
        
        # Use integer indices to avoid matplotlib date issues
        x_indices = np.arange(len(df))
        x_ticks = np.linspace(0, len(df)-1, min(10, len(df))).astype(int)
        x_labels = [df['timestamp'].iloc[i].strftime('%Y-%m-%d') for i in x_ticks]
        
        # Extract buy and sell trades
        buy_trades = [t for t in trades if t.get('type') == 'buy']
        sell_trades = [t for t in trades if t.get('type') == 'sell']
        
        # Map timestamps to indices
        timestamp_to_idx = {}
        for i, ts in enumerate(df['timestamp']):
            timestamp_to_idx[pd.Timestamp(ts)] = i
        
        # Plot candlestick chart on first subplot
        up = df[df['close'] >= df['open']]
        down = df[df['close'] < df['open']]
        
        up_idx = x_indices[df['close'] >= df['open']]
        down_idx = x_indices[df['close'] < df['open']]
        
        # Plot up candles
        width = 0.6
        ax1.bar(up_idx, up['close']-up['open'], width, bottom=up['open'], color='green', alpha=0.5)
        ax1.bar(up_idx, up['high']-up['close'], 0.2*width, bottom=up['close'], color='green', alpha=0.5)
        ax1.bar(up_idx, up['open']-up['low'], 0.2*width, bottom=up['low'], color='green', alpha=0.5)
        
        # Plot down candles
        ax1.bar(down_idx, down['open']-down['close'], width, bottom=down['close'], color='red', alpha=0.5)
        ax1.bar(down_idx, down['high']-down['open'], 0.2*width, bottom=down['open'], color='red', alpha=0.5)
        ax1.bar(down_idx, down['close']-down['low'], 0.2*width, bottom=down['low'], color='red', alpha=0.5)
        
        # Plot trade markers
        buy_indices = []
        sell_indices = []
        buy_prices = []
        sell_prices = []
        
        for trade in buy_trades:
            # Get index for this trade's timestamp
            ts = trade.get('step', 0)
            if isinstance(ts, int) and 0 <= ts < len(df):
                # If timestamp is an integer index
                buy_indices.append(ts)
                buy_prices.append(trade.get('price', df['close'].iloc[ts]))
            elif ts in timestamp_to_idx:
                # If timestamp is a datetime that matches exactly
                buy_indices.append(timestamp_to_idx[ts])
                buy_prices.append(trade.get('price', df['close'].iloc[timestamp_to_idx[ts]]))
            elif isinstance(ts, (pd.Timestamp, datetime)) and min(df['timestamp']) <= ts <= max(df['timestamp']):
                # Find closest timestamp
                closest_ts = df['timestamp'].iloc[(df['timestamp'] - ts).abs().argsort()[0]]
                idx = timestamp_to_idx.get(pd.Timestamp(closest_ts), 0)
                buy_indices.append(idx)
                buy_prices.append(trade.get('price', df['close'].iloc[idx]))
        
        for trade in sell_trades:
            # Get index for this trade's timestamp
            ts = trade.get('step', 0)
            if isinstance(ts, int) and 0 <= ts < len(df):
                # If timestamp is an integer index
                sell_indices.append(ts)
                sell_prices.append(trade.get('price', df['close'].iloc[ts]))
            elif ts in timestamp_to_idx:
                # If timestamp is a datetime that matches exactly
                sell_indices.append(timestamp_to_idx[ts])
                sell_prices.append(trade.get('price', df['close'].iloc[timestamp_to_idx[ts]]))
            elif isinstance(ts, (pd.Timestamp, datetime)) and min(df['timestamp']) <= ts <= max(df['timestamp']):
                # Find closest timestamp
                closest_ts = df['timestamp'].iloc[(df['timestamp'] - ts).abs().argsort()[0]]
                idx = timestamp_to_idx.get(pd.Timestamp(closest_ts), 0)
                sell_indices.append(idx)
                sell_prices.append(trade.get('price', df['close'].iloc[idx]))
        
        if buy_indices and buy_prices:
            ax1.scatter(buy_indices, buy_prices, marker='^', color='blue', s=100, label='Buy', zorder=10)
        if sell_indices and sell_prices:
            ax1.scatter(sell_indices, sell_prices, marker='v', color='purple', s=100, label='Sell', zorder=10)
        
        # Add title and legend to first subplot
        ax1.set_title(title)
        ax1.set_ylabel('Price')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Plot volume on second subplot
        if 'volume' in df.columns:
            # Normalize volume for display
            volume = df['volume']
            if len(volume) > 0 and volume.max() > 0:
                normalized_volume = volume / volume.max() * 100
                ax2.bar(x_indices, normalized_volume, width=0.8, color='blue', alpha=0.3)
                ax2.set_ylabel('Volume')
                ax2.grid(True, alpha=0.3)
        
        # Plot portfolio value if available in trades
        portfolio_values = []
        portfolio_indices = []
        
        # Try to extract portfolio values from trades
        try:
            # First check if portfolio_value field exists in trades
            if trades and 'portfolio_value' in trades[0]:
                # Collect unique timestamps and their portfolio values
                for trade in trades:
                    ts = trade.get('step', 0)
                    if isinstance(ts, int) and 0 <= ts < len(df) and 'portfolio_value' in trade:
                        portfolio_indices.append(ts)
                        portfolio_values.append(trade['portfolio_value'])
                    elif ts in timestamp_to_idx and 'portfolio_value' in trade:
                        portfolio_indices.append(timestamp_to_idx[ts])
                        portfolio_values.append(trade['portfolio_value'])
                
                # Plot portfolio values if we have them
                if portfolio_indices and portfolio_values:
                    # Sort by index
                    sorted_data = sorted(zip(portfolio_indices, portfolio_values))
                    indices, values = zip(*sorted_data)
                    ax3.plot(indices, values, 'g-', label='Portfolio Value')
                    ax3.set_ylabel('Portfolio Value')
                    ax3.grid(True, alpha=0.3)
                    
                    # Add markers for buy/sell on portfolio line
                    for idx in buy_indices:
                        if idx < len(df):
                            ax3.axvline(x=idx, color='blue', linestyle='--', alpha=0.3)
                    for idx in sell_indices:
                        if idx < len(df):
                            ax3.axvline(x=idx, color='purple', linestyle='--', alpha=0.3)
                            
                    # Add starting and ending portfolio values as text
                    if values:
                        initial_cash = values[0]
                        final_value = values[-1]
                        roi = (final_value / initial_cash - 1) * 100 if initial_cash > 0 else 0
                        ax3.text(0.02, 0.95, f"Initial: ${initial_cash:.2f}", transform=ax3.transAxes)
                        ax3.text(0.02, 0.90, f"Final: ${final_value:.2f}", transform=ax3.transAxes)
                        ax3.text(0.02, 0.85, f"ROI: {roi:.2f}%", transform=ax3.transAxes)
        except Exception as e:
            print(f"Warning: Could not plot portfolio values. Error: {e}")
        
        # Set custom x-ticks for all subplots
        for ax in [ax1, ax2, ax3]:
            ax.set_xticks(x_ticks)
            ax.set_xticklabels(x_labels, rotation=45)
        
        # Only add xlabel to the bottom subplot
        ax3.set_xlabel('Date')
        
        # Calculate trade performance if sell trades exist
        if sell_trades:
            total_trades = len(sell_trades)
            profitable_trades = len([t for t in sell_trades if t.get('profit', 0) > 0])
            win_rate = profitable_trades / total_trades if total_trades > 0 else 0
            
            # Add trade statistics as text annotation
            stats_text = (
                f"Win Rate: {win_rate:.1%} ({profitable_trades}/{total_trades})\n"
                f"Total Trades: {total_trades}"
            )
            ax1.text(0.02, 0.02, stats_text, transform=ax1.transAxes,
                     bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))
        
        # Adjust the layout
        plt.tight_layout()
        
        # Save the figure
        if filename:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, filename)
            plt.savefig(output_path)
            plt.close(fig)
            print(f"Saved backtest visualization to {output_path}")
            return output_path
        else:
            plt.show()
            return None
    
    except Exception as e:
        print(f"Error plotting backtest with signals: {e}")
        import traceback
        traceback.print_exc()
        return None 