import os
import time
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Union, Any, Tuple
from datetime import datetime, timedelta
import threading
import asyncio
from enum import Enum
import matplotlib.pyplot as plt
import tensorflow as tf

from ..data.birdeye_api import BirdEyeAPI
from ..data.data_processor import DataProcessor
from ..model.ml_model import MLModel
from .wallet import SolanaWallet
from ..config.config import config
from ..utils.logger import log_manager
from ..database.utils import (
    record_trade,
    record_prediction,
    update_prediction_actual_price,
    get_model_performance,
    get_token_by_address
)

logger = log_manager.get_logger("trading_strategy")

class Position(Enum):
    """Trading position enum"""
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"

class SignalStrength(Enum):
    """Trading signal strength enum"""
    STRONG_BUY = 3
    BUY = 2
    WEAK_BUY = 1
    NEUTRAL = 0
    WEAK_SELL = -1
    SELL = -2
    STRONG_SELL = -3

class TradingStrategy:
    """ML-based trading strategy for Solana tokens"""
    
    def __init__(
        self,
        token_address: str = None,
        symbol: str = "SOL",
        model_path: str = None,
        wallet: SolanaWallet = None
    ):
        self.token_address = token_address
        self.symbol = symbol
        
        # Initialize APIs and data processor
        self.birdeye_api = BirdEyeAPI()
        self.data_processor = DataProcessor()
        
        # Load ML model
        self.ml_model = MLModel()
        if model_path:
            self.ml_model.load(model_path)
        else:
            # Look for latest model
            latest_model = self.ml_model.get_latest_model_path()
            if latest_model:
                self.ml_model.load(latest_model)
        
        # Initialize wallet
        self.wallet = wallet or SolanaWallet()
        
        # Trading parameters
        self.trading_amount_sol = config.trading_amount_sol
        self.max_trade_amount_usd = config.max_trade_amount_usd
        self.stop_loss_pct = config.stop_loss_percentage / 100
        self.take_profit_pct = config.take_profit_percentage / 100
        
        # State variables
        self.is_running = False
        self.current_position = Position.NEUTRAL
        self.entry_price = None
        self.last_trade_time = None
        self.trades_history = []
        self.open_orders = []
        
        # Create trading directories
        self.trades_dir = os.path.join(os.getcwd(), "trades")
        os.makedirs(self.trades_dir, exist_ok=True)
        
        # Load trading history if exists
        self._load_trades_history()
        
        self.position = None
        self.model_version = "1.0"
    
    def _load_trades_history(self) -> None:
        """Load trading history from file"""
        history_file = os.path.join(self.trades_dir, f"{self.symbol}_trades.json")
        
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    self.trades_history = json.load(f)
                logger.info(f"Loaded {len(self.trades_history)} historical trades")
            except Exception as e:
                logger.error(f"Error loading trade history: {e}")
    
    def _save_trades_history(self) -> None:
        """Save trading history to file"""
        history_file = os.path.join(self.trades_dir, f"{self.symbol}_trades.json")
        
        try:
            with open(history_file, 'w') as f:
                json.dump(self.trades_history, f)
            logger.debug(f"Saved {len(self.trades_history)} trades to history")
        except Exception as e:
            logger.error(f"Error saving trade history: {e}")
    
    def _record_trade(
        self,
        action: str,
        price: float,
        amount: float,
        position: Position,
        reason: str,
        success: bool = True,
        tx_signature: Optional[str] = None
    ) -> None:
        """Record a trade in the history"""
        trade = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'symbol': self.symbol,
            'price': price,
            'amount': amount,
            'position': position.value,
            'reason': reason,
            'success': success
        }
        
        if tx_signature:
            trade['tx_signature'] = tx_signature
        
        self.trades_history.append(trade)
        self._save_trades_history()
        logger.info(f"Recorded trade: {action} {amount} {self.symbol} at {price}")
    
    async def get_current_price(self) -> float:
        """Get the current price of the token"""
        try:
            price_data = self.birdeye_api.get_token_price(self.token_address)
            
            if 'data' in price_data and 'value' in price_data['data']:
                return float(price_data['data']['value'])
            else:
                logger.error(f"Invalid price data format: {price_data}")
                return 0.0
        except Exception as e:
            logger.error(f"Error getting current price: {e}")
            return 0.0
    
    def _prepare_features(self, resolution: str = "15m", days: int = 2) -> Optional[np.ndarray]:
        """Prepare features for prediction"""
        try:
            # Get historical data
            df = self.data_processor.process_pipeline(
                self.token_address,
                self.symbol,
                resolution,
                days,
                save_data=False
            )
            
            if df.empty:
                logger.error("No data available for prediction")
                return None
            
            # Prepare sequence data
            sequence_length = 10  # Should match the model's expected input
            
            # Select features and scale
            feature_cols = [col for col in df.columns if col not in ['timestamp']]
            features = df[feature_cols].values
            
            # Scale features
            scaled_features = self.data_processor.feature_scaler.transform(features)
            
            # Create sequence
            if len(scaled_features) < sequence_length:
                logger.error(f"Not enough data points for sequence (have {len(scaled_features)}, need {sequence_length})")
                return None
            
            # Get the most recent sequence
            sequence = scaled_features[-sequence_length:].reshape(1, sequence_length, scaled_features.shape[1])
            
            return sequence
        except Exception as e:
            logger.error(f"Error preparing features for prediction: {e}")
            return None
    
    async def predict_next_price(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Predict the next price using the ML model
        
        Returns:
            Tuple of (predicted_price, current_price)
        """
        try:
            # Get current price
            current_price = await self.get_current_price()
            if current_price == 0:
                logger.error("Failed to get current price")
                return None, None
            
            # Check if model is loaded
            if not self.ml_model.model:
                logger.error("ML model not loaded")
                return None, current_price
            
            # Prepare features for prediction
            features = self._prepare_features()
            if features is None:
                return None, current_price
            
            # Make prediction
            prediction = self.ml_model.predict(features)[0][0]
            
            # Convert prediction back to original scale
            predicted_price = self.data_processor.inverse_transform_predictions(np.array([prediction]))[0]
            
            logger.info(f"Predicted price: {predicted_price}, Current price: {current_price}")
            return predicted_price, current_price
        except Exception as e:
            logger.error(f"Error in price prediction: {e}")
            return None, None
    
    def generate_signal(
        self, 
        predicted_price: float, 
        current_price: float,
        threshold: float = 0.01  # 1% change
    ) -> Tuple[Position, SignalStrength]:
        """
        Generate trading signal based on predicted price
        
        Args:
            predicted_price: ML predicted price
            current_price: Current market price
            threshold: Minimum price change to generate a signal
            
        Returns:
            Tuple of (position, signal_strength)
        """
        # Calculate price change percentage
        price_change_pct = (predicted_price - current_price) / current_price
        
        # Determine position
        if price_change_pct > threshold:
            position = Position.LONG
        elif price_change_pct < -threshold:
            position = Position.SHORT
        else:
            position = Position.NEUTRAL
        
        # Determine signal strength based on percentage change
        if price_change_pct > 0.05:  # 5%
            strength = SignalStrength.STRONG_BUY
        elif price_change_pct > 0.02:  # 2%
            strength = SignalStrength.BUY
        elif price_change_pct > 0.01:  # 1%
            strength = SignalStrength.WEAK_BUY
        elif price_change_pct < -0.05:  # -5%
            strength = SignalStrength.STRONG_SELL
        elif price_change_pct < -0.02:  # -2%
            strength = SignalStrength.SELL
        elif price_change_pct < -0.01:  # -1%
            strength = SignalStrength.WEAK_SELL
        else:
            strength = SignalStrength.NEUTRAL
        
        logger.info(f"Generated signal: {position.value} with strength {strength.name} (Change: {price_change_pct:.2%})")
        return position, strength
    
    async def execute_trade(
        self,
        position: Position,
        signal_strength: SignalStrength,
        current_price: float
    ) -> bool:
        """
        Execute a trade based on the signal
        
        Args:
            position: Recommended position
            signal_strength: Signal strength
            current_price: Current market price
            
        Returns:
            True if trade was executed, False otherwise
        """
        # Skip weak signals
        if signal_strength == SignalStrength.NEUTRAL:
            logger.info("Neutral signal, no trade executed")
            return False
        
        # Check if we already have a position
        if self.current_position != Position.NEUTRAL:
            # Check if the signal suggests closing the position
            if (self.current_position == Position.LONG and position == Position.SHORT) or \
               (self.current_position == Position.SHORT and position == Position.LONG):
                # Close the position
                return await self._close_position("Signal suggests reversing position")
            else:
                logger.info(f"Already in {self.current_position.value} position, no trade needed")
                return False
        
        # Check if signal is strong enough
        if signal_strength.value < SignalStrength.BUY.value and signal_strength.value > SignalStrength.SELL.value:
            logger.info(f"Signal strength {signal_strength.name} too weak, not trading")
            return False
        
        # Check wallet balance
        sol_balance = self.wallet.get_balance()
        if sol_balance < self.trading_amount_sol:
            logger.warning(f"Insufficient balance: {sol_balance} SOL, need {self.trading_amount_sol} SOL")
            return False
        
        # Determine trade amount (in this simplified version, we just use a fixed amount)
        trade_amount = self.trading_amount_sol
        
        # In a real implementation, you would:
        # 1. For a LONG position: Buy the token with SOL
        # 2. For a SHORT position: Short sell the token (more complex, might require derivatives)
        
        if position == Position.LONG:
            logger.info(f"Opening LONG position: Buying {trade_amount} SOL worth of {self.symbol}")
            # Here we would actually execute the buy order through a DEX
            self.current_position = Position.LONG
            self.entry_price = current_price
            self.last_trade_time = datetime.now()
            
            self._record_trade(
                action="buy",
                price=current_price,
                amount=trade_amount,
                position=Position.LONG,
                reason=f"ML signal: {signal_strength.name}"
            )
            return True
            
        elif position == Position.SHORT:
            logger.info(f"Opening SHORT position: Shorting {trade_amount} SOL worth of {self.symbol}")
            # Here we would actually execute the short order through a DEX or derivatives platform
            # This is simplified as direct shorting on Solana is more complex
            self.current_position = Position.SHORT
            self.entry_price = current_price
            self.last_trade_time = datetime.now()
            
            self._record_trade(
                action="short",
                price=current_price,
                amount=trade_amount,
                position=Position.SHORT,
                reason=f"ML signal: {signal_strength.name}"
            )
            return True
        
        return False
    
    async def _close_position(self, reason: str) -> bool:
        """Close the current position"""
        if self.current_position == Position.NEUTRAL:
            logger.info("No position to close")
            return False
        
        # Get current price
        current_price = await self.get_current_price()
        if current_price == 0:
            logger.error("Failed to get current price for closing position")
            return False
        
        # Calculate profit/loss
        if self.entry_price:
            if self.current_position == Position.LONG:
                pnl_pct = (current_price - self.entry_price) / self.entry_price
                action = "sell"
            else:  # SHORT
                pnl_pct = (self.entry_price - current_price) / self.entry_price
                action = "cover"
            
            logger.info(f"Closing {self.current_position.value} position: {action} at {current_price}, PnL: {pnl_pct:.2%}")
            
            # In a real implementation, you would:
            # 1. For a LONG position: Sell the token for SOL
            # 2. For a SHORT position: Buy back the token to cover
            
            self._record_trade(
                action=action,
                price=current_price,
                amount=self.trading_amount_sol,
                position=self.current_position,
                reason=reason
            )
            
            # Reset position
            self.current_position = Position.NEUTRAL
            self.entry_price = None
            return True
        else:
            logger.error("Cannot close position: no entry price recorded")
            return False
    
    async def check_stop_loss_take_profit(self) -> bool:
        """Check if stop loss or take profit conditions are met"""
        if self.current_position == Position.NEUTRAL or not self.entry_price:
            return False
        
        # Get current price
        current_price = await self.get_current_price()
        if current_price == 0:
            logger.error("Failed to get current price for SL/TP check")
            return False
        
        # Calculate price change
        if self.current_position == Position.LONG:
            price_change_pct = (current_price - self.entry_price) / self.entry_price
            
            # Check stop loss
            if price_change_pct <= -self.stop_loss_pct:
                logger.info(f"Stop loss triggered: {price_change_pct:.2%} loss")
                return await self._close_position("Stop loss triggered")
            
            # Check take profit
            if price_change_pct >= self.take_profit_pct:
                logger.info(f"Take profit triggered: {price_change_pct:.2%} gain")
                return await self._close_position("Take profit triggered")
                
        elif self.current_position == Position.SHORT:
            price_change_pct = (self.entry_price - current_price) / self.entry_price
            
            # Check stop loss
            if price_change_pct <= -self.stop_loss_pct:
                logger.info(f"Stop loss triggered: {price_change_pct:.2%} loss")
                return await self._close_position("Stop loss triggered")
            
            # Check take profit
            if price_change_pct >= self.take_profit_pct:
                logger.info(f"Take profit triggered: {price_change_pct:.2%} gain")
                return await self._close_position("Take profit triggered")
        
        return False
    
    async def trading_cycle(self) -> None:
        """Run one complete trading cycle"""
        try:
            # 1. Check stop loss / take profit on existing positions
            if await self.check_stop_loss_take_profit():
                return
            
            # 2. Make price prediction
            predicted_price, current_price = await self.predict_next_price()
            if predicted_price is None or current_price is None:
                logger.error("Failed to get price prediction")
                return
            
            # 3. Generate trading signal
            position, signal_strength = self.generate_signal(predicted_price, current_price)
            
            # 4. Execute trade based on signal
            await self.execute_trade(position, signal_strength, current_price)
            
        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")
    
    async def run(self, interval_minutes: int = None) -> None:
        """
        Run the trading bot continuously
        
        Args:
            interval_minutes: Trading interval in minutes (defaults to config value)
        """
        if interval_minutes is None:
            interval_minutes = config.trading_interval_minutes
        
        self.is_running = True
        
        logger.info(f"Starting trading bot with {interval_minutes} minute intervals")
        
        while self.is_running:
            try:
                await self.trading_cycle()
                
                # Wait for next interval
                logger.info(f"Waiting {interval_minutes} minutes until next cycle")
                await asyncio.sleep(interval_minutes * 60)
            except KeyboardInterrupt:
                logger.info("Trading bot stopped by user")
                self.is_running = False
                break
            except Exception as e:
                logger.error(f"Error in trading bot main loop: {e}")
                await asyncio.sleep(60)  # Wait a bit before retrying
    
    def stop(self) -> None:
        """Stop the trading bot"""
        self.is_running = False
        logger.info("Trading bot stop requested")
    
    def get_performance_metrics(self) -> Dict:
        """Calculate trading performance metrics"""
        if not self.trades_history:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "avg_profit": 0,
                "max_profit": 0,
                "max_loss": 0,
                "total_profit": 0
            }
        
        # Pair trades (buy/sell or short/cover)
        paired_trades = []
        opens = []
        
        for trade in self.trades_history:
            if trade['action'] in ['buy', 'short']:
                opens.append(trade)
            elif trade['action'] in ['sell', 'cover'] and opens:
                # Match with the most recent open
                open_trade = opens.pop()
                
                # Calculate profit
                if open_trade['action'] == 'buy' and trade['action'] == 'sell':
                    profit_pct = (trade['price'] - open_trade['price']) / open_trade['price']
                elif open_trade['action'] == 'short' and trade['action'] == 'cover':
                    profit_pct = (open_trade['price'] - trade['price']) / open_trade['price']
                else:
                    logger.warning(f"Mismatched trade pair: {open_trade['action']} and {trade['action']}")
                    continue
                
                paired_trades.append({
                    'open': open_trade,
                    'close': trade,
                    'profit_pct': profit_pct
                })
        
        # Calculate metrics
        total_trades = len(paired_trades)
        winning_trades = sum(1 for t in paired_trades if t['profit_pct'] > 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        profits = [t['profit_pct'] for t in paired_trades]
        avg_profit = sum(profits) / len(profits) if profits else 0
        max_profit = max(profits) if profits else 0
        max_loss = min(profits) if profits else 0
        total_profit = sum(profits)
        
        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "avg_profit": avg_profit,
            "max_profit": max_profit,
            "max_loss": max_loss,
            "total_profit": total_profit
        }

    def decide_action(
        self, 
        model: tf.keras.Model, 
        current_data: np.ndarray,
        current_price: float,
        confidence_threshold: float = 0.7
    ) -> Tuple[str, float, float]:
        """
        Decide whether to buy, sell, or hold based on model prediction
        
        Args:
            model: Trained model
            current_data: Current market data (features)
            current_price: Current token price
            confidence_threshold: Threshold for model confidence
            
        Returns:
            action: 'buy', 'sell', or 'hold'
            predicted_price: Model's price prediction
            confidence: Confidence score of the prediction
        """
        # Make prediction
        prediction = model.predict(np.expand_dims(current_data, axis=0), verbose=0)
        predicted_price = float(prediction[0])
        
        # Calculate price change percentage
        price_change_pct = (predicted_price - current_price) / current_price
        
        # Calculate confidence level (simplified)
        confidence = min(abs(price_change_pct) * 10, 1.0)
        
        # Decide action based on prediction and confidence
        if price_change_pct > 0.02 and confidence > confidence_threshold:
            action = "buy"
        elif price_change_pct < -0.02 and confidence > confidence_threshold:
            action = "sell"
        else:
            action = "hold"
        
        return action, predicted_price, confidence
    
    def execute_trade(
        self, 
        action: str,
        token_id: int,
        price: float,
        amount: float,
        predicted_price: float = None,
        confidence: float = None
    ) -> Dict[str, Any]:
        """
        Execute a trade and record it in the database
        
        Args:
            action: 'buy', 'sell', or 'hold'
            token_id: ID of the token being traded
            price: Current token price
            amount: Amount to trade
            predicted_price: Model's price prediction
            confidence: Confidence score of the prediction
            
        Returns:
            result: Dictionary with trade result
        """
        logger.info(f"Executing {action} trade for token_id {token_id} at price {price}")
        
        # Simulate trade execution (in a real system, this would call an exchange API)
        success = True
        try:
            # Here we would actually execute the trade via an exchange API
            # For now, we'll just simulate a successful trade
            pass
        except Exception as e:
            logger.error(f"Trade execution failed: {e}")
            success = False
        
        # Record the trade in the database
        record_trade(
            token_id=token_id,
            timestamp=datetime.now(),
            action=action,
            price=price,
            amount=amount,
            success=success
        )
        
        # If we have prediction data, record that too
        if predicted_price is not None and confidence is not None:
            prediction_id = record_prediction(
                token_id=token_id,
                timestamp=datetime.now(),
                predicted_price=predicted_price,
                confidence=confidence,
                model_version=self.model_version,
                horizon=1  # 1 time period ahead
            )
            
            # Schedule update of actual price (in a real system, this would be a background task)
            # Here we'll just log it for demonstration
            logger.info(f"Recorded prediction {prediction_id}, will update with actual price later")
        
        return {
            "action": action,
            "price": price,
            "amount": amount,
            "timestamp": datetime.now(),
            "success": success
        }
    
    def check_exit_conditions(
        self, 
        current_price: float
    ) -> bool:
        """
        Check if we should exit our position based on stop loss or take profit
        
        Args:
            current_price: Current token price
            
        Returns:
            bool: True if we should exit, False otherwise
        """
        if self.position is None:
            return False
        
        price_change_pct = (current_price - self.entry_price) / self.entry_price
        
        if self.position == "long" and (
            price_change_pct <= -self.stop_loss_pct or 
            price_change_pct >= self.take_profit_pct
        ):
            return True
        
        if self.position == "short" and (
            price_change_pct >= self.stop_loss_pct or 
            price_change_pct <= -self.take_profit_pct
        ):
            return True
        
        return False
    
    def backtest(
        self, 
        model: tf.keras.Model,
        data: pd.DataFrame,
        data_processor: Any,
        initial_balance: float = 1000.0,
        fee_rate: float = 0.001
    ) -> Dict[str, Any]:
        """
        Backtest the trading strategy
        
        Args:
            model: Trained model
            data: Historical data
            data_processor: DataProcessor instance
            initial_balance: Initial balance for backtesting
            fee_rate: Trading fee rate
            
        Returns:
            results: Dictionary with backtest results
        """
        logger.info("Starting backtest")
        
        # Prepare data
        sequence_length = 10  # Should match what the model was trained on
        feature_cols = [col for col in data.columns if col != 'target']
        
        if 'timestamp' in data.columns:
            data.set_index('timestamp', inplace=True)
        
        # Scale features
        features = data[feature_cols].values
        scaled_features = data_processor.feature_scaler.transform(features)
        
        # Create sequences
        X = []
        for i in range(len(scaled_features) - sequence_length):
            X.append(scaled_features[i:i+sequence_length])
        X = np.array(X)
        
        # Initialize backtest state
        balance = initial_balance
        token_balance = 0
        position = None
        entry_price = 0
        trades = []
        predictions = []
        
        # Run backtest
        for i in range(len(X)):
            current_data = X[i]
            current_idx = i + sequence_length
            current_price = data.iloc[current_idx]['close']
            timestamp = data.index[current_idx]
            
            # Get model prediction
            action, predicted_price, confidence = self.decide_action(
                model, current_data, current_price
            )
            
            # Record prediction
            predictions.append({
                'timestamp': timestamp,
                'current_price': current_price,
                'predicted_price': predicted_price,
                'confidence': confidence
            })
            
            # Check if we should exit position
            if position and self.check_exit_conditions(current_price):
                if position == "long":
                    # Sell tokens
                    action = "sell"
                elif position == "short":
                    # Buy to cover
                    action = "buy"
            
            # Execute action
            if action == "buy" and (position is None or position == "short"):
                # Calculate amount to buy
                amount = balance / current_price
                # Apply fee
                fee = amount * current_price * fee_rate
                amount = amount * (1 - fee_rate)
                
                # Update state
                balance = 0
                token_balance = amount
                position = "long"
                entry_price = current_price
                
                # Record trade
                trades.append({
                    'timestamp': timestamp,
                    'action': 'buy',
                    'price': current_price,
                    'amount': amount,
                    'balance': balance,
                    'token_balance': token_balance,
                    'portfolio_value': token_balance * current_price
                })
                
            elif action == "sell" and (position is None or position == "long"):
                # Calculate amount to sell
                amount = token_balance
                # Apply fee
                fee = amount * current_price * fee_rate
                
                # Update state
                balance = amount * current_price * (1 - fee_rate)
                token_balance = 0
                position = None if position == "long" else "short"
                
                # Record trade
                trades.append({
                    'timestamp': timestamp,
                    'action': 'sell',
                    'price': current_price,
                    'amount': amount,
                    'balance': balance,
                    'token_balance': token_balance,
                    'portfolio_value': balance
                })
        
        # Calculate final portfolio value
        if token_balance > 0:
            final_value = token_balance * data.iloc[-1]['close']
        else:
            final_value = balance
        
        # Calculate performance metrics
        initial_price = data.iloc[sequence_length]['close']
        final_price = data.iloc[-1]['close']
        buy_and_hold_return = (final_price - initial_price) / initial_price
        strategy_return = (final_value - initial_balance) / initial_balance
        
        # Create trade history dataframe
        trade_df = pd.DataFrame(trades)
        if not trade_df.empty:
            trade_df.set_index('timestamp', inplace=True)
        
        # Create prediction history dataframe
        pred_df = pd.DataFrame(predictions)
        if not pred_df.empty:
            pred_df.set_index('timestamp', inplace=True)
        
        return {
            'initial_balance': initial_balance,
            'final_value': final_value,
            'return': strategy_return,
            'buy_and_hold_return': buy_and_hold_return,
            'trade_count': len(trades),
            'trades': trade_df,
            'predictions': pred_df
        }
    
    def display_results(self, results: Dict[str, Any]) -> None:
        """Display backtest results"""
        logger.info(f"Backtest results:")
        logger.info(f"Initial balance: ${results['initial_balance']:.2f}")
        logger.info(f"Final value: ${results['final_value']:.2f}")
        logger.info(f"Return: {results['return']*100:.2f}%")
        logger.info(f"Buy and hold return: {results['buy_and_hold_return']*100:.2f}%")
        logger.info(f"Number of trades: {results['trade_count']}")
        
        # Plot portfolio value over time if trades exist
        if 'trades' in results and not results['trades'].empty:
            plt.figure(figsize=(12, 6))
            
            # Plot portfolio value
            if 'portfolio_value' in results['trades'].columns:
                plt.subplot(2, 1, 1)
                plt.plot(results['trades'].index, results['trades']['portfolio_value'])
                plt.title('Portfolio Value')
                plt.grid(True)
            
            # Plot trades
            plt.subplot(2, 1, 2)
            buys = results['trades'][results['trades']['action'] == 'buy']
            sells = results['trades'][results['trades']['action'] == 'sell']
            
            if 'predictions' in results and not results['predictions'].empty:
                plt.plot(results['predictions'].index, results['predictions']['current_price'], label='Price')
                
            if not buys.empty:
                plt.scatter(buys.index, buys['price'], color='green', marker='^', label='Buy')
            
            if not sells.empty:
                plt.scatter(sells.index, sells['price'], color='red', marker='v', label='Sell')
                
            plt.title('Trades')
            plt.legend()
            plt.grid(True)
            
            plt.tight_layout()
            plt.savefig('backtest_results.png')
            logger.info("Backtest results chart saved to backtest_results.png")
    
    def run_live_trading(
        self, 
        model: tf.keras.Model,
        token_address: str,
        data_processor: Any,
        resolution: str = "15m",
        initial_balance: float = 1000.0,
        trading_interval: int = 60  # seconds
    ) -> None:
        """
        Run live trading
        
        Args:
            model: Trained model
            token_address: Token address
            data_processor: DataProcessor instance
            resolution: Data resolution
            initial_balance: Initial balance
            trading_interval: Trading interval in seconds
        """
        logger.info(f"Starting live trading for {token_address} with {resolution} resolution")
        
        # Get token information from database
        token = get_token_by_address(token_address)
        if not token:
            logger.error(f"Token {token_address} not found in database")
            return
        
        # Initialize trading state
        balance = initial_balance
        token_balance = 0
        sequence_length = 10  # Should match what the model was trained on
        
        try:
            while True:
                logger.info("Getting latest market data")
                
                # Fetch latest data
                df = data_processor.fetch_price_data(
                    token_address=token_address,
                    resolution=resolution,
                    days=5  # Get enough data for technical indicators
                )
                
                # Calculate technical indicators
                df = data_processor.calculate_technical_indicators(df)
                
                # Prepare features
                feature_cols = [col for col in df.columns if col != 'target' and col != 'timestamp']
                df = df.dropna()  # Drop rows with NaN values
                
                if len(df) < sequence_length:
                    logger.error(f"Not enough data points: {len(df)} < {sequence_length}")
                    time.sleep(trading_interval)
                    continue
                
                # Get latest data point
                current_price = df.iloc[-1]['close']
                
                # Scale features
                features = df[feature_cols].values
                scaled_features = data_processor.feature_scaler.transform(features)
                
                # Create sequence
                current_data = scaled_features[-sequence_length:]
                
                # Get model prediction
                action, predicted_price, confidence = self.decide_action(
                    model, current_data, current_price
                )
                
                logger.info(f"Current price: {current_price}")
                logger.info(f"Predicted price: {predicted_price}")
                logger.info(f"Confidence: {confidence}")
                logger.info(f"Recommended action: {action}")
                
                # Record prediction
                prediction_id = record_prediction(
                    token_id=token.token_id,
                    timestamp=datetime.now(),
                    predicted_price=predicted_price,
                    confidence=confidence,
                    model_version=self.model_version,
                    horizon=1  # 1 time period ahead
                )
                
                # Execute action
                if action == "buy" and balance > 0:
                    # Calculate amount to buy
                    amount = balance / current_price
                    
                    # Execute trade
                    trade_result = self.execute_trade(
                        action="buy",
                        token_id=token.token_id,
                        price=current_price,
                        amount=amount,
                        predicted_price=predicted_price,
                        confidence=confidence
                    )
                    
                    if trade_result['success']:
                        # Update state
                        balance = 0
                        token_balance = amount
                        self.position = "long"
                        self.entry_price = current_price
                        
                        logger.info(f"Bought {amount} tokens at {current_price}")
                    
                elif action == "sell" and token_balance > 0:
                    # Execute trade
                    trade_result = self.execute_trade(
                        action="sell",
                        token_id=token.token_id,
                        price=current_price,
                        amount=token_balance,
                        predicted_price=predicted_price,
                        confidence=confidence
                    )
                    
                    if trade_result['success']:
                        # Update state
                        balance = token_balance * current_price * 0.999  # Approximate fee
                        token_balance = 0
                        self.position = None
                        
                        logger.info(f"Sold all tokens at {current_price}, new balance: {balance}")
                
                # Check model performance periodically
                model_performance = get_model_performance(
                    token_id=token.token_id,
                    model_version=self.model_version,
                    horizon=1
                )
                
                if model_performance:
                    logger.info(f"Model performance: {model_performance}")
                
                # Wait for next trading interval
                logger.info(f"Waiting {trading_interval} seconds for next trading cycle")
                time.sleep(trading_interval)
                
                # Update actual prices for previous predictions
                # In a real system, this would be a separate background task
                # Here we'll just log it
                logger.info("Updating actual prices for previous predictions")
                
        except KeyboardInterrupt:
            logger.info("Trading stopped by user")
        except Exception as e:
            logger.error(f"Error in live trading: {e}")
            raise
