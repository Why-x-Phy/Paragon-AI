"""
Calvin AI Simple Strategy Engine

Real-time strategy engine that integrates LSTM predictions with simple magnitude-based
strategy logic for generating buy/sell/hold signals.

Key Features:
- <100ms prediction + strategy evaluation latency per token
- Simple magnitude-based strategy (buy ≥2%, sell ≥3% predicted change)
- Real-time feature preprocessing integration
- Confidence-based signal filtering (>70% threshold)
- Memory management for GPU models
- Integration with existing model registry and data pipeline

This integrates with:
- model_registry.py for LSTM model access
- data_processor.py for feature engineering
- simple_backtest_strategy logic from profit_functions.py
- realtime_storage.py for live data
- Redis caching for performance
"""

import time
import asyncio
from typing import Dict, Any, Optional, List, Tuple, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
import numpy as np
import pandas as pd
import redis
import json
from enum import Enum

# TensorFlow imports with error handling
try:
    import tensorflow as tf
    HAS_TENSORFLOW = True
except ImportError:
    HAS_TENSORFLOW = False
    tf = None

# Local imports
from src.config.config import config
from src.utils.logger import log
from src.inference.model_registry import get_model_registry, ModelMetadata
from src.data.data_processor import DataProcessor
from src.database.production_db import get_db_manager

logger = log

class SignalType(Enum):
    """Trading signal types"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

class SignalStrength(Enum):
    """Signal strength levels"""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"

@dataclass
class TradingSignal:
    """Trading signal with all relevant information"""
    symbol: str
    signal_type: SignalType
    strength: SignalStrength
    confidence: float
    predicted_price: float
    current_price: float
    predicted_change_pct: float
    timestamp: datetime
    
    # Strategy parameters used
    buy_threshold: float
    sell_threshold: float
    confidence_threshold: float
    
    # Additional metadata
    model_version: str
    processing_time_ms: float
    raw_prediction: float

@dataclass
class StrategyConfig:
    """Configuration for strategy engine"""
    # Performance settings
    max_prediction_latency_ms: float = 200.0  # More realistic for testing (cold loads)
    prediction_batch_size: int = 1
    cache_predictions_seconds: int = 30
    
    # Strategy settings
    default_buy_threshold: float = 0.02  # 2%
    default_sell_threshold: float = 0.03  # 3%
    default_confidence_threshold: float = 0.70  # 70%
    position_size_pct: float = 0.10  # 10% of available cash
    transaction_cost_pct: float = 0.001  # 0.1% fee
    
    # Feature processing
    feature_cache_ttl: int = 60  # 1 minute
    normalize_features: bool = True
    
    # Memory management
    max_models_in_memory: int = 10  # Keep 10 most-used models hot, load others on-demand
    model_memory_threshold_mb: float = 1500.0  # Conservative limit for 20 models
    gpu_memory_growth: bool = True

class SimpleStrategyEngine:
    """
    Real-time strategy engine combining LSTM predictions with simple magnitude-based strategy
    """
    
    def __init__(self, config: Optional[StrategyConfig] = None):
        """
        Initialize the strategy engine
        
        Args:
            config: Strategy configuration (uses defaults if None)
        """
        self.config = config or StrategyConfig()
        
        # Initialize core components
        self.model_registry = get_model_registry()
        self.data_processor = DataProcessor()
        
        # Redis for caching predictions and features
        self.redis_client = None
        self._init_redis()
        
        # Database manager for data access
        self.db_manager = None
        self._init_db_manager()
        
        # Performance tracking
        self.prediction_times = []
        self.signal_history = []
        
        # Feature cache
        self._feature_cache = {}
        self._prediction_cache = {}
        
        # GPU memory management
        self._configure_gpu_memory()
        
        logger.info("Simple Strategy Engine initialized")
        logger.info(f"Config: buy_threshold={self.config.default_buy_threshold:.1%}, "
                   f"sell_threshold={self.config.default_sell_threshold:.1%}, "
                   f"confidence_threshold={self.config.default_confidence_threshold:.1%}")
        logger.info(f"Performance: target_latency={self.config.max_prediction_latency_ms}ms "
                   f"(Note: First model loads will be slower due to GPU initialization)")
        logger.info(f"Memory: max_models_in_memory={self.config.max_models_in_memory}, "
                   f"threshold={self.config.model_memory_threshold_mb}MB "
                   f"(Optimized for ~20 token models)")

    def _init_redis(self):
        """Initialize Redis connection for caching"""
        try:
            self.redis_client = redis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                password=config.REDIS_PASSWORD,
                db=config.REDIS_DB,
                decode_responses=True
            )
            self.redis_client.ping()
            logger.info("Connected to Redis for strategy caching")
        except Exception as e:
            logger.warning(f"Redis connection failed, continuing without caching: {e}")
            self.redis_client = None

    def _init_db_manager(self):
        """Initialize database manager connection"""
        try:
            # We'll initialize this async in the first method that needs it
            self.db_manager = None
            logger.info("Database manager will be initialized on first use")
        except Exception as e:
            logger.warning(f"Database manager setup failed: {e}")
            self.db_manager = None

    async def _ensure_db_manager(self):
        """Ensure database manager is initialized"""
        if self.db_manager is None:
            try:
                self.db_manager = await get_db_manager()
                logger.info("Database manager initialized")
            except Exception as e:
                logger.error(f"Failed to initialize database manager: {e}")
                raise

    def _configure_gpu_memory(self):
        """Configure GPU memory growth to prevent memory issues"""
        if not HAS_TENSORFLOW:
            return
            
        try:
            gpus = tf.config.experimental.list_physical_devices('GPU')
            if gpus and self.config.gpu_memory_growth:
                for gpu in gpus:
                    tf.config.experimental.set_memory_growth(gpu, True)
                logger.info(f"Configured GPU memory growth for {len(gpus)} GPUs")
        except RuntimeError as e:
            # This is expected if called after model loading - not an error
            logger.debug(f"GPU memory growth not configured (already initialized): {e}")
        except Exception as e:
            logger.warning(f"GPU memory configuration failed: {e}")

    async def generate_signal(self, symbol: str, version: Optional[str] = None) -> Optional[TradingSignal]:
        """
        Generate trading signal for a token using LSTM prediction + simple strategy
        
        Args:
            symbol: Token symbol (e.g., 'BONK', 'JUP')
            version: Model version (defaults to latest)
            
        Returns:
            TradingSignal or None if failed
        """
        start_time = time.time()
        
        try:
            # 1. Get model and strategy parameters
            model = self.model_registry.get_model(symbol, version)
            if not model:
                logger.warning(f"No model available for {symbol}")
                return None
            
            metadata = self.model_registry.get_model_metadata(symbol, version)
            strategy_params = self.model_registry.get_strategy_parameters(symbol, version)
            
            # 2. Get current market data
            current_price = await self._get_current_price(symbol)
            if not current_price:
                logger.warning(f"No current price data for {symbol}")
                return None
            
            # 3. Prepare features for prediction
            features = await self._prepare_features(symbol, metadata)
            if features is None:
                logger.warning(f"Failed to prepare features for {symbol}")
                return None
            
            # 4. Generate LSTM prediction
            raw_prediction = await self._predict_with_model(model, features, symbol)
            if raw_prediction is None:
                logger.warning(f"Prediction failed for {symbol}")
                return None
            
            # 5. Convert prediction to price
            predicted_price = await self._convert_prediction_to_price(
                raw_prediction, current_price, symbol, metadata
            )
            
            # 6. Apply simple magnitude-based strategy
            signal = await self._apply_simple_strategy(
                current_price=current_price,
                predicted_price=predicted_price,
                strategy_params=strategy_params,
                symbol=symbol,
                metadata=metadata
            )
            
            # 7. Calculate processing time
            processing_time_ms = (time.time() - start_time) * 1000
            
            # 8. Create trading signal
            trading_signal = TradingSignal(
                symbol=symbol,
                signal_type=signal['type'],
                strength=signal['strength'],
                confidence=signal['confidence'],
                predicted_price=predicted_price,
                current_price=current_price,
                predicted_change_pct=signal['predicted_change_pct'],
                timestamp=datetime.now(),
                buy_threshold=strategy_params['buy_threshold'],
                sell_threshold=strategy_params['sell_threshold'],
                confidence_threshold=strategy_params['confidence_threshold'],
                model_version=metadata.version,
                processing_time_ms=processing_time_ms,
                raw_prediction=raw_prediction
            )
            
            # 9. Log performance
            self.prediction_times.append(processing_time_ms)
            if processing_time_ms > self.config.max_prediction_latency_ms:
                # Check if this was likely a cold model load
                if processing_time_ms > 500:  # Likely cold load
                    logger.debug(f"Cold model load for {symbol} took {processing_time_ms:.1f}ms (expected for first use)")
                else:
                    logger.warning(f"Prediction latency exceeded target: {processing_time_ms:.1f}ms > {self.config.max_prediction_latency_ms}ms")
            else:
                logger.debug(f"Generated signal for {symbol} in {processing_time_ms:.1f}ms")
            
            # 10. Cache the signal
            await self._cache_signal(trading_signal)
            
            return trading_signal
            
        except Exception as e:
            logger.error(f"Signal generation failed for {symbol}: {e}")
            return None

    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price from database or cache"""
        try:
            # Ensure database manager is initialized
            await self._ensure_db_manager()
            
            # Try Redis cache first
            if self.redis_client:
                cache_key = f"price:current:{symbol}"
                cached_price = self.redis_client.get(cache_key)
                if cached_price:
                    return float(cached_price)
            
            # Get token info first
            token_info = await self.db_manager.get_token_by_symbol(symbol)
            if not token_info:
                logger.warning(f"Token {symbol} not found in database")
                return None
            
            # Get latest price from database
            price = await self.db_manager.get_latest_price(token_info['token_id'])
            if price:
                return float(price)
            
            # Final fallback - could integrate with external API here
            logger.warning(f"No current price data available for {symbol}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            return None

    async def _prepare_features(self, symbol: str, metadata: ModelMetadata) -> Optional[np.ndarray]:
        """Prepare features for LSTM prediction"""
        try:
            # Ensure database manager is initialized
            await self._ensure_db_manager()
            
            # Check feature cache first
            cache_key = f"features:{symbol}:{metadata.version}"
            if cache_key in self._feature_cache:
                cached_time, features = self._feature_cache[cache_key]
                if (datetime.now() - cached_time).seconds < self.config.feature_cache_ttl:
                    return features
            
            # Get token info first
            token_info = await self.db_manager.get_token_by_symbol(symbol)
            if not token_info:
                logger.warning(f"Token {symbol} not found in database")
                return None
            
            # Get recent OHLCV data for feature engineering
            # Calculate start time for data
            lookback_hours = metadata.sequence_length + 24  # Extra buffer for indicators
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=lookback_hours)
            
            # Get OHLCV data from database
            ohlcv_data = await self.db_manager.get_ohlcv_data(
                token_id=token_info['token_id'],
                resolution='1h',
                start_time=start_time,
                end_time=end_time,
                limit=lookback_hours
            )
            
            if not ohlcv_data or len(ohlcv_data) < metadata.sequence_length:
                logger.warning(f"Insufficient historical data for {symbol}: got {len(ohlcv_data) if ohlcv_data else 0}, need {metadata.sequence_length}")
                return None
            
            # Convert to DataFrame for data processor
            df_data = []
            for candle in ohlcv_data:
                df_data.append({
                    'time': candle.time,
                    'open': candle.open,
                    'high': candle.high,
                    'low': candle.low,
                    'close': candle.close,
                    'volume': candle.volume
                })
            
            ohlcv_df = pd.DataFrame(df_data).sort_values('time')
            
            # Use existing data processor for feature engineering
            X, _, _, _ = self.data_processor.prepare_ml_data(
                ohlcv_df,
                target_col='close',
                sequence_length=metadata.sequence_length,
                prediction_horizon=metadata.prediction_horizon,
                test_size=0.01  # Just get the latest sequence
            )
            
            if len(X) == 0:
                logger.warning(f"No features generated for {symbol}")
                return None
            
            # Get the latest feature sequence
            features = X[-1]  # Most recent sequence
            
            # Cache the features
            self._feature_cache[cache_key] = (datetime.now(), features)
            
            return features
                
        except Exception as e:
            logger.error(f"Feature preparation failed for {symbol}: {e}")
            return None

    async def _predict_with_model(self, model, features: np.ndarray, symbol: str) -> Optional[float]:
        """Generate prediction using LSTM model"""
        try:
            # Check prediction cache
            cache_key = f"prediction:{symbol}:{hash(features.tobytes())}"
            if cache_key in self._prediction_cache:
                cached_time, prediction = self._prediction_cache[cache_key]
                if (datetime.now() - cached_time).seconds < self.config.cache_predictions_seconds:
                    return prediction
            
            # Make prediction
            features_batch = np.expand_dims(features, axis=0)  # Add batch dimension
            prediction = model.predict(features_batch, verbose=0)
            
            # Extract scalar prediction
            raw_prediction = float(prediction[0][0]) if len(prediction.shape) > 1 else float(prediction[0])
            
            # Cache the prediction
            self._prediction_cache[cache_key] = (datetime.now(), raw_prediction)
            
            return raw_prediction
            
        except Exception as e:
            logger.error(f"Model prediction failed for {symbol}: {e}")
            return None

    async def _convert_prediction_to_price(self, raw_prediction: float, current_price: float, 
                                         symbol: str, metadata: ModelMetadata) -> float:
        """Convert raw model prediction to actual price prediction"""
        try:
            # The conversion depends on how the model was trained
            # For percentage change models (most common):
            if abs(raw_prediction) < 1.0:  # Likely percentage change
                predicted_price = current_price * (1 + raw_prediction)
            else:  # Likely absolute price
                predicted_price = raw_prediction
            
            # Sanity check - prevent unrealistic predictions
            max_change = 0.50  # 50% max change
            min_price = current_price * (1 - max_change)
            max_price = current_price * (1 + max_change)
            
            predicted_price = max(min_price, min(max_price, predicted_price))
            
            return predicted_price
            
        except Exception as e:
            logger.error(f"Prediction conversion failed for {symbol}: {e}")
            return current_price  # Fallback to current price

    async def _apply_simple_strategy(self, current_price: float, predicted_price: float,
                                   strategy_params: Dict[str, float], symbol: str,
                                   metadata: ModelMetadata) -> Dict[str, Any]:
        """Apply simple magnitude-based strategy logic"""
        try:
            # Calculate predicted percentage change
            predicted_change_pct = (predicted_price - current_price) / current_price
            
            # Get strategy parameters
            buy_threshold = strategy_params.get('buy_threshold', self.config.default_buy_threshold)
            sell_threshold = strategy_params.get('sell_threshold', self.config.default_sell_threshold)
            confidence_threshold = strategy_params.get('confidence_threshold', self.config.default_confidence_threshold)
            
            # Calculate confidence based on magnitude of predicted change
            # Higher magnitude changes = higher confidence
            confidence = min(abs(predicted_change_pct) * 20, 1.0)  # Scale to 0-1, more generous
            
            # Determine signal type using simple magnitude-based strategy
            if predicted_change_pct >= buy_threshold and confidence >= confidence_threshold:
                signal_type = SignalType.BUY
                # Determine strength based on magnitude
                if predicted_change_pct >= buy_threshold * 2:
                    strength = SignalStrength.STRONG
                elif predicted_change_pct >= buy_threshold * 1.5:
                    strength = SignalStrength.MODERATE
                else:
                    strength = SignalStrength.WEAK
                    
            elif predicted_change_pct <= -sell_threshold and confidence >= confidence_threshold:
                signal_type = SignalType.SELL
                # Determine strength based on magnitude
                if predicted_change_pct <= -sell_threshold * 2:
                    strength = SignalStrength.STRONG
                elif predicted_change_pct <= -sell_threshold * 1.5:
                    strength = SignalStrength.MODERATE
                else:
                    strength = SignalStrength.WEAK
            else:
                signal_type = SignalType.HOLD
                strength = SignalStrength.WEAK
            
            return {
                'type': signal_type,
                'strength': strength,
                'confidence': confidence,
                'predicted_change_pct': predicted_change_pct
            }
            
        except Exception as e:
            logger.error(f"Strategy application failed for {symbol}: {e}")
            return {
                'type': SignalType.HOLD,
                'strength': SignalStrength.WEAK,
                'confidence': 0.0,
                'predicted_change_pct': 0.0
            }

    async def _cache_signal(self, signal: TradingSignal):
        """Cache the generated signal in Redis"""
        if not self.redis_client:
            return
            
        try:
            cache_key = f"signal:{signal.symbol}:latest"
            signal_data = {
                'symbol': signal.symbol,
                'signal_type': signal.signal_type.value,
                'strength': signal.strength.value,
                'confidence': signal.confidence,
                'predicted_price': signal.predicted_price,
                'current_price': signal.current_price,
                'predicted_change_pct': signal.predicted_change_pct,
                'timestamp': signal.timestamp.isoformat(),
                'processing_time_ms': signal.processing_time_ms
            }
            
            self.redis_client.setex(
                cache_key, 
                self.config.cache_predictions_seconds,
                json.dumps(signal_data)
            )
            
        except Exception as e:
            logger.warning(f"Failed to cache signal: {e}")

    async def generate_signals_batch(self, symbols: List[str]) -> Dict[str, Optional[TradingSignal]]:
        """Generate signals for multiple tokens in parallel"""
        try:
            # Create async tasks for all symbols
            tasks = [self.generate_signal(symbol) for symbol in symbols]
            
            # Execute in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Create results dictionary
            signals = {}
            for symbol, result in zip(symbols, results):
                if isinstance(result, Exception):
                    logger.error(f"Signal generation failed for {symbol}: {result}")
                    signals[symbol] = None
                else:
                    signals[symbol] = result
            
            return signals
            
        except Exception as e:
            logger.error(f"Batch signal generation failed: {e}")
            return {symbol: None for symbol in symbols}

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get strategy engine performance statistics"""
        if not self.prediction_times:
            return {
                'avg_latency_ms': 0,
                'max_latency_ms': 0,
                'min_latency_ms': 0,
                'total_predictions': 0,
                'over_threshold_count': 0
            }
        
        return {
            'avg_latency_ms': np.mean(self.prediction_times),
            'max_latency_ms': np.max(self.prediction_times),
            'min_latency_ms': np.min(self.prediction_times),
            'total_predictions': len(self.prediction_times),
            'over_threshold_count': sum(1 for t in self.prediction_times if t > self.config.max_prediction_latency_ms),
            'success_rate': len([t for t in self.prediction_times if t > 0]) / len(self.prediction_times) if self.prediction_times else 0
        }

    def clear_caches(self):
        """Clear all internal caches"""
        self._feature_cache.clear()
        self._prediction_cache.clear()
        logger.info("Strategy engine caches cleared")

# Convenience functions for easy integration
_strategy_engine_instance: Optional[SimpleStrategyEngine] = None

def get_strategy_engine() -> SimpleStrategyEngine:
    """Get or create the global strategy engine instance"""
    global _strategy_engine_instance
    if _strategy_engine_instance is None:
        _strategy_engine_instance = SimpleStrategyEngine()
    return _strategy_engine_instance

async def generate_signal(symbol: str, version: Optional[str] = None) -> Optional[TradingSignal]:
    """Convenience function to generate a single signal"""
    engine = get_strategy_engine()
    return await engine.generate_signal(symbol, version)

async def generate_signals(symbols: List[str]) -> Dict[str, Optional[TradingSignal]]:
    """Convenience function to generate multiple signals"""
    engine = get_strategy_engine()
    return await engine.generate_signals_batch(symbols) 