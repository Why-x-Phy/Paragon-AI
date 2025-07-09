#!/usr/bin/env python3
"""
Adaptive Strategy Backtest

This script runs a backtest that simulates how the adaptive strategy would have
adjusted thresholds over time based on market conditions and performance.

Unlike production code, this is a standalone simulation that doesn't affect
the live trading system.
"""

import os
import sys
import asyncio
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import logging
import json
from collections import deque
import argparse

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.data_processor import DataProcessor
from src.model.ml_model import MLModel
from src.model.profit_functions import simple_backtest_strategy
from src.utils.logger import log as logger

# Setup logging
# logger = setup_logger("adaptive_backtest")

# Import adaptive strategy components
from src.inference.adaptive_strategy import (
    MarketRegime, AdaptationMethod, StrategyParameters, 
    AdaptationConfig, MarketConditions
)


@dataclass
class BacktestState:
    """Track state during adaptive backtest"""
    current_params: StrategyParameters
    market_conditions: MarketConditions
    performance_history: deque = field(default_factory=lambda: deque(maxlen=100))
    adaptation_history: List[Dict] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)
    portfolio_values: List[float] = field(default_factory=list)
    
    # Performance tracking
    total_signals: int = 0
    profitable_signals: int = 0
    consecutive_losses: int = 0
    last_adaptation_time: Optional[datetime] = None


class AdaptiveBacktester:
    """
    Backtester that simulates adaptive strategy behavior
    """
    
    def __init__(self, config: AdaptationConfig):
        self.config = config
        self.states: Dict[str, BacktestState] = {}
        
    def analyze_market_conditions(self, df: pd.DataFrame, current_idx: int, 
                                lookback_hours: int = 24) -> MarketConditions:
        """Analyze market conditions at a specific point in time"""
        # Get lookback window
        start_idx = max(0, current_idx - lookback_hours)
        window_df = df.iloc[start_idx:current_idx+1]
        
        if len(window_df) < 2:
            return MarketConditions()
        
        # Calculate volatility (hourly returns std)
        returns = window_df['close'].pct_change().dropna()
        volatility = returns.std() if len(returns) > 1 else 0.01
        
        # Calculate momentum (24h price change)
        price_24h_ago = window_df.iloc[0]['close']
        current_price = window_df.iloc[-1]['close']
        momentum = ((current_price - price_24h_ago) / price_24h_ago) * 100
        
        # Determine regime
        if volatility > self.config.high_volatility_threshold:
            regime = MarketRegime.HIGH_VOLATILITY
        elif volatility < self.config.low_volatility_threshold:
            regime = MarketRegime.LOW_VOLATILITY
        elif momentum > 5.0:
            regime = MarketRegime.TRENDING_UP
        elif momentum < -5.0:
            regime = MarketRegime.TRENDING_DOWN
        else:
            regime = MarketRegime.RANGE_BOUND
        
        return MarketConditions(
            volatility_24h=volatility,
            momentum_24h=momentum,
            regime=regime,
            volume_24h=window_df['volume'].sum() if 'volume' in window_df else 0,
            price_change_24h=momentum
        ) 
    
    def adapt_for_volatility(self, state: BacktestState) -> bool:
        """Adapt parameters based on market volatility"""
        params = state.current_params
        conditions = state.market_conditions
        volatility = conditions.volatility_24h
        
        original_buy = params.buy_threshold
        original_sell = params.sell_threshold
        
        if volatility > self.config.high_volatility_threshold:
            # High volatility: increase thresholds
            volatility_factor = min(volatility / self.config.high_volatility_threshold, 2.0)
            params.buy_threshold = min(
                params.buy_threshold * (1 + self.config.volatility_adaptation_factor * (volatility_factor - 1)),
                params.max_buy_threshold
            )
            params.sell_threshold = min(
                params.sell_threshold * (1 + self.config.volatility_adaptation_factor * (volatility_factor - 1)),
                params.max_sell_threshold
            )
            
        elif volatility < self.config.low_volatility_threshold:
            # Low volatility: decrease thresholds
            volatility_factor = volatility / self.config.low_volatility_threshold
            params.buy_threshold = max(
                params.buy_threshold * (volatility_factor + (1 - volatility_factor) * (1 - self.config.volatility_adaptation_factor)),
                params.min_buy_threshold
            )
            params.sell_threshold = max(
                params.sell_threshold * (volatility_factor + (1 - volatility_factor) * (1 - self.config.volatility_adaptation_factor)),
                params.min_sell_threshold
            )
        
        return (abs(params.buy_threshold - original_buy) > 0.0001 or 
                abs(params.sell_threshold - original_sell) > 0.0001)
    
    def adapt_for_performance(self, state: BacktestState) -> bool:
        """Adapt parameters based on recent performance"""
        params = state.current_params
        
        if state.total_signals < self.config.min_signals_for_adaptation:
            return False
        
        original_buy = params.buy_threshold
        original_sell = params.sell_threshold
        
        # Calculate win rate
        win_rate = state.profitable_signals / state.total_signals if state.total_signals > 0 else 0.5
        
        if win_rate < self.config.min_win_rate_threshold:
            # Poor performance: increase thresholds
            adjustment = (self.config.min_win_rate_threshold - win_rate) * 2.0
            params.buy_threshold = min(params.buy_threshold * (1 + adjustment), params.max_buy_threshold)
            params.sell_threshold = min(params.sell_threshold * (1 + adjustment), params.max_sell_threshold)
            
        elif win_rate > self.config.max_win_rate_threshold:
            # Excellent performance: decrease thresholds
            adjustment = (win_rate - self.config.max_win_rate_threshold) * 1.0
            params.buy_threshold = max(params.buy_threshold * (1 - adjustment), params.min_buy_threshold)
            params.sell_threshold = max(params.sell_threshold * (1 - adjustment), params.min_sell_threshold)
        
        return (abs(params.buy_threshold - original_buy) > 0.0001 or 
                abs(params.sell_threshold - original_sell) > 0.0001)
    
    def adapt_for_momentum(self, state: BacktestState) -> bool:
        """Adapt parameters based on market momentum"""
        params = state.current_params
        conditions = state.market_conditions
        momentum = conditions.momentum_24h
        
        original_buy = params.buy_threshold
        original_sell = params.sell_threshold
        
        if abs(momentum) > 3.0:  # Significant momentum
            momentum_factor = min(abs(momentum) / 10.0, 0.5)
            
            if momentum > 0:  # Positive momentum
                params.buy_threshold = max(
                    params.buy_threshold * (1 - momentum_factor * 0.3),
                    params.min_buy_threshold
                )
                params.sell_threshold = min(
                    params.sell_threshold * (1 + momentum_factor * 0.2),
                    params.max_sell_threshold
                )
            else:  # Negative momentum
                params.buy_threshold = min(
                    params.buy_threshold * (1 + momentum_factor * 0.3),
                    params.max_buy_threshold
                )
                params.sell_threshold = max(
                    params.sell_threshold * (1 - momentum_factor * 0.2),
                    params.min_sell_threshold
                )
        
        return (abs(params.buy_threshold - original_buy) > 0.0001 or 
                abs(params.sell_threshold - original_sell) > 0.0001)
    
    def smooth_parameters(self, original: StrategyParameters, adapted: StrategyParameters) -> StrategyParameters:
        """Apply smoothing to prevent oscillation"""
        smoothing = self.config.adaptation_smoothing_factor
        
        # Create a copy
        smoothed = StrategyParameters(
            symbol=adapted.symbol,
            buy_threshold=(original.buy_threshold * (1 - smoothing) + adapted.buy_threshold * smoothing),
            sell_threshold=(original.sell_threshold * (1 - smoothing) + adapted.sell_threshold * smoothing),
            confidence_threshold=(original.confidence_threshold * (1 - smoothing) + adapted.confidence_threshold * smoothing)
        )
        
        # Enforce bounds
        smoothed.buy_threshold = max(smoothed.min_buy_threshold, 
                                   min(smoothed.max_buy_threshold, smoothed.buy_threshold))
        smoothed.sell_threshold = max(smoothed.min_sell_threshold, 
                                    min(smoothed.max_sell_threshold, smoothed.sell_threshold))
        
        return smoothed 
    
    def run_adaptive_backtest(self, symbol: str, prices: np.ndarray, predictions: np.ndarray,
                            ohlcv_df: pd.DataFrame, initial_cash: float = 10000) -> Dict[str, Any]:
        """Run backtest with adaptive strategy"""
        
        # Initialize state
        state = BacktestState(
            current_params=StrategyParameters(
                symbol=symbol,
                buy_threshold=0.01,    # Start with default 1%
                sell_threshold=0.015   # Start with default 1.5%
            )
        )
        
        # Trading state
        cash = initial_cash
        tokens_held = 0
        position = 0  # 0 = no position, 1 = long
        entry_price = 0
        
        # Track results
        portfolio_values = [initial_cash]
        all_trades = []
        threshold_history = []
        
        # Position sizing
        position_size_pct = 0.10  # 10% of portfolio
        
        logger.info(f"Starting adaptive backtest for {symbol}")
        logger.info(f"Initial thresholds: buy={state.current_params.buy_threshold:.1%}, "
                   f"sell={state.current_params.sell_threshold:.1%}")
        
        for i in range(1, len(prices)):
            current_price = prices[i]
            predicted_price = predictions[i]
            
            # Analyze market conditions
            state.market_conditions = self.analyze_market_conditions(ohlcv_df, i)
            
            # Check if we should adapt parameters
            current_time = ohlcv_df.index[i] if hasattr(ohlcv_df, 'index') else datetime.now()
            should_adapt = False
            
            if state.last_adaptation_time is None:
                should_adapt = True
            else:
                time_since_adapt = (current_time - state.last_adaptation_time).total_seconds() / 3600
                should_adapt = time_since_adapt >= (self.config.adaptation_frequency_minutes / 60)
            
            if should_adapt:
                # Store original parameters
                original_params = StrategyParameters(
                    symbol=state.current_params.symbol,
                    buy_threshold=state.current_params.buy_threshold,
                    sell_threshold=state.current_params.sell_threshold
                )
                
                # Apply adaptations
                adapted = False
                if self.config.adaptation_method in [AdaptationMethod.VOLATILITY_BASED, AdaptationMethod.HYBRID]:
                    adapted |= self.adapt_for_volatility(state)
                
                if self.config.adaptation_method in [AdaptationMethod.MOMENTUM_BASED, AdaptationMethod.HYBRID]:
                    adapted |= self.adapt_for_momentum(state)
                
                if state.total_signals >= self.config.min_signals_for_adaptation:
                    if self.config.adaptation_method in [AdaptationMethod.PERFORMANCE_BASED, AdaptationMethod.HYBRID]:
                        adapted |= self.adapt_for_performance(state)
                
                if adapted:
                    # Apply smoothing
                    state.current_params = self.smooth_parameters(original_params, state.current_params)
                    state.last_adaptation_time = current_time
                    
                    # Record adaptation
                    state.adaptation_history.append({
                        'time': current_time,
                        'buy_threshold': state.current_params.buy_threshold,
                        'sell_threshold': state.current_params.sell_threshold,
                        'volatility': state.market_conditions.volatility_24h,
                        'momentum': state.market_conditions.momentum_24h,
                        'regime': state.market_conditions.regime.value,
                        'win_rate': state.profitable_signals / state.total_signals if state.total_signals > 0 else 0
                    })
                    
                    logger.debug(f"Adapted at step {i}: buy={state.current_params.buy_threshold:.2%}, "
                               f"sell={state.current_params.sell_threshold:.2%}")
            
            # Record current thresholds
            threshold_history.append({
                'step': i,
                'buy_threshold': state.current_params.buy_threshold,
                'sell_threshold': state.current_params.sell_threshold
            })
            
            # Generate trading signal using adaptive thresholds
            predicted_change = (predicted_price - current_price) / current_price
            
            signal = None
            if predicted_change >= state.current_params.buy_threshold and position == 0:
                signal = 'buy'
            elif predicted_change <= -state.current_params.sell_threshold and position == 1:
                signal = 'sell'
            elif position == 1 and predicted_change < 0:
                signal = 'sell'  # Exit on predicted decline
            
            # Execute trade
            if signal == 'buy' and cash > 0:
                # Buy tokens
                investment = cash * position_size_pct
                tokens_to_buy = investment / current_price
                
                if investment <= cash:
                    tokens_held += tokens_to_buy
                    cash -= investment
                    position = 1
                    entry_price = current_price
                    
                    trade = {
                        'step': i,
                        'type': 'buy',
                        'price': current_price,
                        'tokens': tokens_to_buy,
                        'value': investment,
                        'predicted_change': predicted_change,
                        'threshold': state.current_params.buy_threshold
                    }
                    all_trades.append(trade)
                    state.trades.append(trade)
                    state.total_signals += 1
                    
            elif signal == 'sell' and position == 1 and tokens_held > 0:
                # Sell tokens
                sale_value = tokens_held * current_price
                cash += sale_value
                
                # Calculate profit
                trade_return = (current_price - entry_price) / entry_price
                profitable = trade_return > 0
                
                if profitable:
                    state.profitable_signals += 1
                    state.consecutive_losses = 0
                else:
                    state.consecutive_losses += 1
                
                trade = {
                    'step': i,
                    'type': 'sell',
                    'price': current_price,
                    'tokens': tokens_held,
                    'value': sale_value,
                    'return': trade_return,
                    'profitable': profitable,
                    'predicted_change': predicted_change,
                    'threshold': state.current_params.sell_threshold
                }
                all_trades.append(trade)
                state.trades.append(trade)
                
                tokens_held = 0
                position = 0
                entry_price = 0
            
            # Calculate portfolio value
            portfolio_value = cash + (tokens_held * current_price)
            portfolio_values.append(portfolio_value)
        
        # Final portfolio value
        final_value = cash + (tokens_held * prices[-1])
        total_return = ((final_value - initial_cash) / initial_cash) * 100
        
        # Calculate metrics
        buy_hold_return = ((prices[-1] - prices[0]) / prices[0]) * 100
        
        # Win rate
        winning_trades = [t for t in all_trades if t.get('type') == 'sell' and t.get('profitable', False)]
        losing_trades = [t for t in all_trades if t.get('type') == 'sell' and not t.get('profitable', False)]
        win_rate = len(winning_trades) / (len(winning_trades) + len(losing_trades)) * 100 if (winning_trades or losing_trades) else 0
        
        # Max drawdown
        peak = initial_cash
        max_drawdown = 0
        for value in portfolio_values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            max_drawdown = max(max_drawdown, drawdown)
        
        results = {
            'total_return': total_return,
            'buy_hold_return': buy_hold_return,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'total_trades': len([t for t in all_trades if t['type'] == 'buy']),
            'final_portfolio_value': final_value,
            'portfolio_values': portfolio_values,
            'trades': all_trades,
            'adaptation_history': state.adaptation_history,
            'threshold_history': threshold_history,
            'total_adaptations': len(state.adaptation_history)
        }
        
        return results 


def plot_adaptive_backtest_results(results: Dict[str, Any], symbol: str, output_dir: str = "plots/adaptive_backtests"):
    """Plot adaptive backtest results with threshold evolution"""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.gridspec import GridSpec
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Create figure with subplots
    fig = plt.figure(figsize=(16, 12))
    gs = GridSpec(4, 2, figure=fig, hspace=0.3, wspace=0.3)
    
    # 1. Portfolio value over time
    ax1 = fig.add_subplot(gs[0, :])
    portfolio_values = results['portfolio_values']
    ax1.plot(portfolio_values, label='Portfolio Value', color='blue', linewidth=2)
    ax1.axhline(y=10000, color='gray', linestyle='--', alpha=0.5, label='Initial Value')
    ax1.set_title(f'{symbol} Adaptive Strategy - Portfolio Performance', fontsize=14, fontweight='bold')
    ax1.set_xlabel('Time Steps')
    ax1.set_ylabel('Portfolio Value ($)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # 2. Threshold evolution
    ax2 = fig.add_subplot(gs[1, :])
    threshold_history = results['threshold_history']
    steps = [t['step'] for t in threshold_history]
    buy_thresholds = [t['buy_threshold'] * 100 for t in threshold_history]
    sell_thresholds = [t['sell_threshold'] * 100 for t in threshold_history]
    
    ax2.plot(steps, buy_thresholds, label='Buy Threshold', color='green', linewidth=2)
    ax2.plot(steps, sell_thresholds, label='Sell Threshold', color='red', linewidth=2)
    
    # Mark adaptation points
    if results['adaptation_history']:
        for adapt in results['adaptation_history']:
            ax2.axvline(x=steps[0], color='purple', alpha=0.3, linestyle='--')
    
    ax2.set_title('Adaptive Threshold Evolution', fontsize=14, fontweight='bold')
    ax2.set_xlabel('Time Steps')
    ax2.set_ylabel('Threshold (%)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # 3. Trade distribution
    ax3 = fig.add_subplot(gs[2, 0])
    trades = results['trades']
    buy_trades = [t for t in trades if t['type'] == 'buy']
    sell_trades = [t for t in trades if t['type'] == 'sell']
    
    if sell_trades:
        returns = [t['return'] * 100 for t in sell_trades]
        colors = ['green' if r > 0 else 'red' for r in returns]
        ax3.bar(range(len(returns)), returns, color=colors, alpha=0.7)
        ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax3.set_title('Trade Returns Distribution', fontsize=12)
        ax3.set_xlabel('Trade Number')
        ax3.set_ylabel('Return (%)')
    
    # 4. Performance metrics
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.axis('off')
    
    metrics_text = f"""
Performance Metrics:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Return: {results['total_return']:.2f}%
Buy & Hold Return: {results['buy_hold_return']:.2f}%
Win Rate: {results['win_rate']:.2f}%
Max Drawdown: {results['max_drawdown']:.2f}%
Total Trades: {results['total_trades']}
Total Adaptations: {results['total_adaptations']}

Outperformance: {results['total_return'] - results['buy_hold_return']:.2f}%
    """
    
    ax4.text(0.1, 0.5, metrics_text, fontsize=11, family='monospace',
             verticalalignment='center', bbox=dict(boxstyle="round,pad=0.5", 
                                                  facecolor="lightgray", alpha=0.5))
    
    # 5. Adaptation history
    ax5 = fig.add_subplot(gs[3, :])
    if results['adaptation_history']:
        adaptations = results['adaptation_history']
        volatilities = [a['volatility'] * 100 for a in adaptations]
        regimes = [a['regime'] for a in adaptations]
        
        # Create a color map for regimes
        regime_colors = {
            'low_volatility': 'green',
            'normal_volatility': 'blue',
            'high_volatility': 'orange',
            'extreme_volatility': 'red',
            'trending_up': 'lightgreen',
            'trending_down': 'lightcoral',
            'range_bound': 'gray'
        }
        
        colors = [regime_colors.get(r, 'black') for r in regimes]
        ax5.scatter(range(len(adaptations)), volatilities, c=colors, s=100, alpha=0.7)
        
        # Add regime labels
        for i, (vol, regime) in enumerate(zip(volatilities, regimes)):
            if i % max(1, len(adaptations) // 10) == 0:  # Show every 10th label
                ax5.annotate(regime.replace('_', ' ').title(), 
                           (i, vol), fontsize=8, rotation=45, ha='right')
        
        ax5.set_title('Market Conditions at Adaptation Points', fontsize=12)
        ax5.set_xlabel('Adaptation Number')
        ax5.set_ylabel('Volatility (%)')
        ax5.grid(True, alpha=0.3)
    
    plt.suptitle(f'{symbol} Adaptive Strategy Backtest Results', fontsize=16, fontweight='bold')
    
    # Save plot
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{symbol}_adaptive_backtest_{timestamp}.png"
    filepath = os.path.join(output_dir, filename)
    plt.savefig(filepath, dpi=300, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Saved adaptive backtest plot to: {filepath}")
    return filepath


async def main():
    """Main function to run adaptive backtest"""
    parser = argparse.ArgumentParser(description='Run adaptive strategy backtest')
    parser.add_argument('--token-address', type=str, required=True, help='Token address')
    parser.add_argument('--symbol', type=str, default='SOL', help='Token symbol')
    parser.add_argument('--days', type=int, default=30, help='Days of historical data')
    parser.add_argument('--resolution', type=str, default='1H', help='Data resolution')
    parser.add_argument('--model-path', type=str, help='Path to model (uses latest if not specified)')
    parser.add_argument('--plot', action='store_true', help='Generate plots')
    parser.add_argument('--compare', action='store_true', help='Compare with static strategy')
    
    args = parser.parse_args()
    
    try:
        # Initialize components
        data_processor = DataProcessor()
        ml_model = MLModel()
        
        # Load model
        if args.model_path:
            ml_model.load(args.model_path)
        else:
            model_path = ml_model.get_latest_model_path()
            if not model_path:
                logger.error("No model found")
                return
            ml_model.load(model_path)
        
        logger.info(f"Loaded model: {model_path if not args.model_path else args.model_path}")
        
        # Get historical data
        logger.info(f"Fetching {args.days} days of {args.resolution} data for {args.symbol}")
        df = data_processor.process_pipeline(
            args.token_address,
            args.symbol,
            args.resolution,
            args.days,
            save_data=False
        )
        
        if df.empty:
            logger.error("No data available")
            return
        
        # Prepare data for prediction
        sequence_length = 36  # Match model training
        _, X_test, _, y_test = data_processor.prepare_ml_data(
            df,
            target_col='close',
            sequence_length=sequence_length,
            prediction_horizon=1,
            test_size=0.8,
            include_feature_names=False
        )
        
        # Make predictions
        y_pred = ml_model.predict(X_test)
        
        # Convert to prices
        y_pred_prices = data_processor.inverse_transform_predictions(
            y_pred, 
            data_processor.prices_at_sequence_end_test
        )
        
        # Get actual prices
        actual_prices = df['close'].values[-len(y_pred_prices):]
        
        # Prepare OHLCV data for the test period
        test_ohlcv = df.iloc[-len(y_pred_prices):].copy()
        
        # Initialize adaptive backtester
        config = AdaptationConfig(
            adaptation_method=AdaptationMethod.HYBRID,
            adaptation_frequency_minutes=60,  # Adapt every hour
            min_signals_for_adaptation=5,      # Need at least 5 signals
            low_volatility_threshold=0.01,     # 1% hourly volatility
            high_volatility_threshold=0.03,    # 3% hourly volatility
        )
        
        backtester = AdaptiveBacktester(config)
        
        # Run adaptive backtest
        logger.info("Running adaptive backtest...")
        adaptive_results = backtester.run_adaptive_backtest(
            args.symbol,
            actual_prices,
            y_pred_prices,
            test_ohlcv
        )
        
        # Print results
        print("\n" + "="*60)
        print("ADAPTIVE STRATEGY BACKTEST RESULTS")
        print("="*60)
        print(f"Total Return: {adaptive_results['total_return']:.2f}%")
        print(f"Buy & Hold Return: {adaptive_results['buy_hold_return']:.2f}%")
        print(f"Win Rate: {adaptive_results['win_rate']:.2f}%")
        print(f"Max Drawdown: {adaptive_results['max_drawdown']:.2f}%")
        print(f"Total Trades: {adaptive_results['total_trades']}")
        print(f"Total Adaptations: {adaptive_results['total_adaptations']}")
        print(f"Outperformance vs Buy & Hold: {adaptive_results['total_return'] - adaptive_results['buy_hold_return']:.2f}%")
        
        # Compare with static strategy if requested
        if args.compare:
            logger.info("Running static strategy for comparison...")
            static_results = simple_backtest_strategy(
                actual_prices,
                y_pred_prices,
                test_ohlcv,
                include_detailed_trades=True,
                verbosity=0,
                resolution=args.resolution,
                buy_threshold=0.01,
                sell_threshold=0.015
            )
            
            print("\n" + "-"*60)
            print("STATIC STRATEGY RESULTS (for comparison)")
            print("-"*60)
            print(f"Total Return: {static_results['Total Return']:.2f}%")
            print(f"Win Rate: {static_results['Win Rate']:.2f}%")
            print(f"Max Drawdown: {static_results['Max Drawdown']:.2f}%")
            print(f"Total Trades: {static_results['Total Trades']}")
            
            print("\n" + "-"*60)
            print("IMPROVEMENT WITH ADAPTIVE STRATEGY")
            print("-"*60)
            print(f"Return Improvement: {adaptive_results['total_return'] - static_results['Total Return']:.2f}%")
            print(f"Win Rate Improvement: {adaptive_results['win_rate'] - static_results['Win Rate']:.2f}%")
            print(f"Drawdown Improvement: {static_results['Max Drawdown'] - adaptive_results['max_drawdown']:.2f}%")
        
        # Generate plots if requested
        if args.plot:
            plot_path = plot_adaptive_backtest_results(adaptive_results, args.symbol)
            print(f"\nPlot saved to: {plot_path}")
        
        # Show some adaptation examples
        if adaptive_results['adaptation_history']:
            print("\n" + "="*60)
            print("SAMPLE ADAPTATIONS")
            print("="*60)
            for i, adapt in enumerate(adaptive_results['adaptation_history'][:5]):
                print(f"\nAdaptation {i+1}:")
                print(f"  Buy Threshold: {adapt['buy_threshold']:.2%}")
                print(f"  Sell Threshold: {adapt['sell_threshold']:.2%}")
                print(f"  Market Regime: {adapt['regime']}")
                print(f"  Volatility: {adapt['volatility']:.2%}")
                print(f"  Win Rate at Time: {adapt['win_rate']:.2%}")
        
    except Exception as e:
        logger.error(f"Error in adaptive backtest: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main()) 