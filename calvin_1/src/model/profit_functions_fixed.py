"""
Fixed Profit Functions for Backtesting

Key fixes:
1. No look-ahead bias - predictions[i] is the prediction MADE at time i for time i+1
2. Realistic position sizing
3. Proper fee and slippage modeling
4. Clear signal generation logic
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from src.utils.logger import log_manager

logger = log_manager.get_logger("profit_functions_fixed")


def fixed_backtest_strategy(
    actual_prices: np.ndarray,
    predicted_prices: np.ndarray,
    initial_cash: float = 10000,
    position_size_pct: float = 0.95,  # Use 95% of available capital
    transaction_fee_pct: float = 0.001,  # 0.1% more realistic for crypto
    slippage_pct: float = 0.001,  # 0.1% slippage
    buy_threshold: float = 0.01,  # Buy when predicted increase >= 1%
    sell_threshold: float = 0.015,  # Sell when predicted decrease >= 1.5%
    stop_loss_pct: float = 0.05,  # Stop loss at 5% loss
    take_profit_pct: float = 0.10,  # Take profit at 10% gain
    enable_stops: bool = True,  # Enable stop loss/take profit
    verbosity: int = 0,
    resolution: str = "1H"
) -> Dict:
    """
    Fixed backtest strategy without look-ahead bias.
    
    CRITICAL: 
    - actual_prices[i] is the price at time i
    - predicted_prices[i] is the prediction MADE at time i-1 FOR time i
    - We make trading decisions at time i based on prediction for time i+1
    
    Args:
        actual_prices: Array of actual prices
        predicted_prices: Array of predicted prices (shifted by 1)
        initial_cash: Starting capital
        position_size_pct: Fraction of capital to use per trade
        transaction_fee_pct: Trading fee percentage
        slippage_pct: Slippage percentage
        buy_threshold: Min predicted increase to buy
        sell_threshold: Min predicted decrease to sell
        stop_loss_pct: Stop loss percentage
        take_profit_pct: Take profit percentage
        enable_stops: Whether to use stop loss/take profit
        verbosity: Logging level
        resolution: Time resolution
        
    Returns:
        Dictionary with backtest results
    """
    
    if len(actual_prices) != len(predicted_prices):
        raise ValueError(f"Length mismatch: actual={len(actual_prices)}, predicted={len(predicted_prices)}")
    
    # Initialize state
    cash = initial_cash
    position = 0  # Number of tokens held
    trades = []
    portfolio_values = []
    signals = []  # Track all signals for debugging
    
    # Position tracking
    entry_price = 0
    entry_time = 0
    peak_price = 0  # For trailing stop
    
    if verbosity > 0:
        logger.info(f"Starting backtest with ${initial_cash:.2f}")
        logger.info(f"Buy threshold: {buy_threshold*100:.1f}%, Sell threshold: {sell_threshold*100:.1f}%")
        if enable_stops:
            logger.info(f"Stop loss: {stop_loss_pct*100:.1f}%, Take profit: {take_profit_pct*100:.1f}%")
    
    for i in range(len(actual_prices)):
        current_price = float(actual_prices[i])
        
        # Calculate portfolio value
        portfolio_value = cash + (position * current_price)
        portfolio_values.append(portfolio_value)
        
        # Can't trade on first bar (no prediction yet)
        if i == 0:
            continue
            
        # Get prediction for NEXT period (made at current time)
        # This avoids look-ahead bias
        if i < len(predicted_prices) - 1:
            next_predicted_price = float(predicted_prices[i + 1])
            predicted_change = (next_predicted_price - current_price) / current_price
        else:
            # No prediction for next period, hold or close
            predicted_change = 0
        
        # Track signal
        signals.append({
            'time': i,
            'current_price': current_price,
            'predicted_change': predicted_change,
            'position': position
        })
        
        # Check stop loss / take profit if we have a position
        if position > 0 and enable_stops:
            # Update peak price for trailing stop
            if current_price > peak_price:
                peak_price = current_price
            
            # Calculate current P&L
            current_return = (current_price - entry_price) / entry_price
            
            # Check stop loss
            if current_return <= -stop_loss_pct:
                # Execute stop loss with slippage
                exit_price = current_price * (1 - slippage_pct)
                proceeds = position * exit_price
                trade_fee = proceeds * transaction_fee_pct
                net_proceeds = proceeds - trade_fee
                
                cash += net_proceeds
                
                trades.append({
                    'type': 'sell',
                    'reason': 'stop_loss',
                    'time': i,
                    'price': exit_price,
                    'quantity': position,
                    'proceeds': net_proceeds,
                    'fee': trade_fee,
                    'return_pct': current_return * 100,
                    'entry_price': entry_price,
                    'entry_time': entry_time
                })
                
                if verbosity > 0:
                    logger.info(f"STOP LOSS at {i}: price=${exit_price:.4f}, loss={current_return*100:.2f}%")
                
                position = 0
                entry_price = 0
                peak_price = 0
                continue
                
            # Check take profit
            elif current_return >= take_profit_pct:
                # Execute take profit with slippage
                exit_price = current_price * (1 - slippage_pct)
                proceeds = position * exit_price
                trade_fee = proceeds * transaction_fee_pct
                net_proceeds = proceeds - trade_fee
                
                cash += net_proceeds
                
                trades.append({
                    'type': 'sell',
                    'reason': 'take_profit',
                    'time': i,
                    'price': exit_price,
                    'quantity': position,
                    'proceeds': net_proceeds,
                    'fee': trade_fee,
                    'return_pct': current_return * 100,
                    'entry_price': entry_price,
                    'entry_time': entry_time
                })
                
                if verbosity > 0:
                    logger.info(f"TAKE PROFIT at {i}: price=${exit_price:.4f}, gain={current_return*100:.2f}%")
                
                position = 0
                entry_price = 0
                peak_price = 0
                continue
        
        # Regular signal-based trading
        if position == 0 and predicted_change >= buy_threshold:
            # BUY signal
            available_cash = cash * position_size_pct
            
            # Calculate buy price with slippage
            buy_price = current_price * (1 + slippage_pct)
            
            # Calculate position size after fees
            trade_value = available_cash / (1 + transaction_fee_pct)
            position_size = trade_value / buy_price
            trade_fee = trade_value * transaction_fee_pct
            
            if trade_value > 10:  # Min trade size
                cash -= (trade_value + trade_fee)
                position = position_size
                entry_price = buy_price
                entry_time = i
                peak_price = buy_price
                
                trades.append({
                    'type': 'buy',
                    'time': i,
                    'price': buy_price,
                    'quantity': position_size,
                    'cost': trade_value + trade_fee,
                    'fee': trade_fee,
                    'predicted_change_pct': predicted_change * 100
                })
                
                if verbosity > 0:
                    logger.info(f"BUY at {i}: price=${buy_price:.4f}, predicted_change={predicted_change*100:.2f}%, quantity={position_size:.4f}")
                    
        elif position > 0 and predicted_change <= -sell_threshold:
            # SELL signal
            exit_price = current_price * (1 - slippage_pct)
            proceeds = position * exit_price
            trade_fee = proceeds * transaction_fee_pct
            net_proceeds = proceeds - trade_fee
            
            cash += net_proceeds
            
            # Calculate return
            total_cost = entry_price * position * (1 + transaction_fee_pct)
            trade_return = (net_proceeds - total_cost) / total_cost
            
            trades.append({
                'type': 'sell',
                'reason': 'signal',
                'time': i,
                'price': exit_price,
                'quantity': position,
                'proceeds': net_proceeds,
                'fee': trade_fee,
                'return_pct': trade_return * 100,
                'predicted_change_pct': predicted_change * 100,
                'entry_price': entry_price,
                'entry_time': entry_time
            })
            
            if verbosity > 0:
                logger.info(f"SELL at {i}: price=${exit_price:.4f}, predicted_change={predicted_change*100:.2f}%, return={trade_return*100:.2f}%")
            
            position = 0
            entry_price = 0
            peak_price = 0
    
    # Close any remaining position at the end
    if position > 0:
        final_price = float(actual_prices[-1])
        exit_price = final_price * (1 - slippage_pct)
        proceeds = position * exit_price
        trade_fee = proceeds * transaction_fee_pct
        net_proceeds = proceeds - trade_fee
        
        cash += net_proceeds
        
        # Calculate return
        total_cost = entry_price * position * (1 + transaction_fee_pct)
        trade_return = (net_proceeds - total_cost) / total_cost
        
        trades.append({
            'type': 'sell',
            'reason': 'end_of_period',
            'time': len(actual_prices) - 1,
            'price': exit_price,
            'quantity': position,
            'proceeds': net_proceeds,
            'fee': trade_fee,
            'return_pct': trade_return * 100,
            'entry_price': entry_price,
            'entry_time': entry_time
        })
        
        position = 0
        portfolio_values.append(cash)  # Final value
    
    # Calculate metrics
    portfolio_values = np.array(portfolio_values)
    final_value = portfolio_values[-1]
    total_return_pct = (final_value - initial_cash) / initial_cash * 100
    
    # Buy and hold benchmark
    buy_hold_return_pct = (actual_prices[-1] - actual_prices[0]) / actual_prices[0] * 100
    
    # Trade statistics
    buy_trades = [t for t in trades if t['type'] == 'buy']
    sell_trades = [t for t in trades if t['type'] == 'sell']
    
    winning_trades = [t for t in sell_trades if t.get('return_pct', 0) > 0]
    losing_trades = [t for t in sell_trades if t.get('return_pct', 0) <= 0]
    
    win_rate = len(winning_trades) / len(sell_trades) * 100 if sell_trades else 0
    
    # Calculate Sharpe ratio
    if len(portfolio_values) > 1:
        returns = pd.Series(portfolio_values).pct_change().dropna()
        
        # Annualization factor
        if 'h' in resolution.lower():
            periods_per_year = 24 * 365 / int(resolution.lower().replace('h', ''))
        elif 'm' in resolution.lower():
            periods_per_year = 525600 / int(resolution.lower().replace('m', ''))  # Minutes per year
        else:
            periods_per_year = 365  # Daily
        
        if returns.std() > 0:
            sharpe_ratio = returns.mean() / returns.std() * np.sqrt(periods_per_year)
        else:
            sharpe_ratio = 0
    else:
        sharpe_ratio = 0
    
    # Max drawdown
    peak = portfolio_values[0]
    max_drawdown = 0
    for value in portfolio_values:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0
        max_drawdown = max(max_drawdown, drawdown)
    
    # Average trade metrics
    if sell_trades:
        returns = [t.get('return_pct', 0) for t in sell_trades]
        avg_return = np.mean(returns)
        avg_win = np.mean([r for r in returns if r > 0]) if winning_trades else 0
        avg_loss = np.mean([r for r in returns if r <= 0]) if losing_trades else 0
    else:
        avg_return = avg_win = avg_loss = 0
    
    results = {
        'total_return_pct': total_return_pct,
        'buy_hold_return_pct': buy_hold_return_pct,
        'final_value': final_value,
        'win_rate': win_rate,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown_pct': max_drawdown * 100,
        'num_trades': len(buy_trades),
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        'avg_return_pct': avg_return,
        'avg_win_pct': avg_win,
        'avg_loss_pct': avg_loss,
        'trades': trades,
        'portfolio_values': portfolio_values.tolist(),
        'signals': signals
    }
    
    # Add reason breakdown
    if sell_trades:
        reasons = {}
        for trade in sell_trades:
            reason = trade.get('reason', 'unknown')
            reasons[reason] = reasons.get(reason, 0) + 1
        results['exit_reasons'] = reasons
    
    return results


def validate_predictions_alignment(
    actual_prices: np.ndarray,
    predicted_prices: np.ndarray,
    sample_size: int = 10
) -> Dict:
    """
    Validate that predictions are properly aligned with actual prices.
    
    This helps detect look-ahead bias and alignment issues.
    
    Args:
        actual_prices: Array of actual prices
        predicted_prices: Array of predicted prices
        sample_size: Number of samples to check
        
    Returns:
        Dictionary with validation results
    """
    
    results = {
        'aligned': True,
        'issues': [],
        'samples': []
    }
    
    # Check lengths
    if len(actual_prices) != len(predicted_prices):
        results['aligned'] = False
        results['issues'].append(f"Length mismatch: actual={len(actual_prices)}, predicted={len(predicted_prices)}")
        return results
    
    # Check correlation at different lags
    correlations = {}
    for lag in [-2, -1, 0, 1, 2]:
        if lag < 0:
            # Predictions lead actuals (look-ahead bias!)
            corr = np.corrcoef(
                predicted_prices[:lag],
                actual_prices[-lag:]
            )[0, 1]
        elif lag > 0:
            # Predictions lag actuals (correct)
            corr = np.corrcoef(
                predicted_prices[lag:],
                actual_prices[:-lag]
            )[0, 1]
        else:
            # No lag
            corr = np.corrcoef(predicted_prices, actual_prices)[0, 1]
        
        correlations[f'lag_{lag}'] = corr
    
    results['correlations'] = correlations
    
    # Check for look-ahead bias
    if correlations['lag_-1'] > correlations['lag_0']:
        results['aligned'] = False
        results['issues'].append("Possible look-ahead bias: predictions correlate better with future prices")
    
    # Sample some predictions
    sample_indices = np.linspace(0, len(actual_prices) - 2, sample_size, dtype=int)
    
    for idx in sample_indices:
        actual = actual_prices[idx]
        predicted = predicted_prices[idx]
        
        # Check if prediction is too close to future actual
        if idx < len(actual_prices) - 1:
            next_actual = actual_prices[idx + 1]
            pred_error_current = abs(predicted - actual) / actual
            pred_error_next = abs(predicted - next_actual) / next_actual
            
            sample = {
                'index': idx,
                'actual': actual,
                'predicted': predicted,
                'next_actual': next_actual,
                'error_vs_current': pred_error_current * 100,
                'error_vs_next': pred_error_next * 100
            }
            
            # If prediction is much closer to next price, we have alignment issue
            if pred_error_next < pred_error_current * 0.5:
                sample['warning'] = 'Prediction closer to future price!'
                results['aligned'] = False
                
            results['samples'].append(sample)
    
    return results 