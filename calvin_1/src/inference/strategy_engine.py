"""
Calvin AI Simple Strategy Engine

Real-time strategy engine that integrates LSTM predictions with simple magnitude-based
strategy logic for generating buy/sell/hold signals.

Key Features:
- <100ms prediction + strategy evaluation latency per token
- Simple magnitude-based strategy (buy ≥2%, sell ≥3% predicted change)
- Real-time feature preprocessing integration
- Configurable confidence-based signal filtering (default 10% minimal threshold)
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
from ..config.config import config
from ..utils.logger import log
from .model_registry import get_model_registry, ModelMetadata
from ..data.inference_data_processor import create_inference_data_processor
from ..database.production_db import get_db_manager

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
    default_confidence_threshold: float = None  # Will use config.MIN_PREDICTION_CONFIDENCE
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
    
    def __init__(self, config: Optional[StrategyConfig] = None, backtest_mode: bool = False):
        """Initialize the strategy engine with optimized LSTM prediction pipeline"""
        # Initialize configuration with proper defaults
        if config is None:
            # Get the global config for correct defaults
            from ..config.config import config as global_config
            config = StrategyConfig(
                default_confidence_threshold=global_config.MIN_PREDICTION_CONFIDENCE  # Use 0.10 from global config
            )
        
        self.config = config
        self.backtest_mode = backtest_mode
        
        # Initialize model registry
        self.model_registry = get_model_registry()
        
        # Initialize caching and performance tracking
        self._feature_cache = {}
        self._prediction_cache = {}
        self.prediction_times = []
        
        # Initialize async components (will be set on first use)
        self.db_manager = None
        self.inference_processor = None
        
        # Initialize Redis connection
        self._init_redis()
        
        # Initialize database manager (async initialization)
        self._init_db_manager()
        
        # Configure GPU memory for TensorFlow
        self._configure_gpu_memory()
        
        # Log configuration
        self._log_initialization()

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
                # Check if we're in a different event loop than the main one
                # This happens when called from scheduler threads
                import asyncio
                try:
                    # Try to get the current running loop
                    current_loop = asyncio.get_running_loop()
                    
                    # If we're in a thread with its own event loop, create a new DB manager
                    # to avoid event loop conflicts
                    from ..database.production_db import ProductionDBManager
                    self.db_manager = ProductionDBManager()
                    await self.db_manager.initialize()
                    logger.info("Database manager initialized (thread-local)")
                except RuntimeError:
                    # No running loop, use the default get_db_manager
                    self.db_manager = await get_db_manager()
                    logger.info("Database manager initialized (main)")
            except Exception as e:
                logger.error(f"Failed to initialize database manager: {e}")
                raise

    async def _ensure_inference_processor(self):
        """Ensure inference data processor is initialized"""
        if self.inference_processor is None:
            try:
                await self._ensure_db_manager()
                # Pass the thread-local db_manager to the inference processor
                self.inference_processor = await create_inference_data_processor(self.db_manager, backtest_mode=self.backtest_mode)
                logger.info(f"Inference data processor initialized (backtest_mode={self.backtest_mode})")
            except Exception as e:
                logger.error(f"Failed to initialize inference processor: {e}")
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

    async def generate_signal(self, symbol: str, version: Optional[str] = None, simulation_time: Optional[datetime] = None) -> Optional[TradingSignal]:
        """
        Generate trading signal for a token using LSTM prediction + simple strategy
        
        Args:
            symbol: Token symbol (e.g., 'BONK', 'JUP')
            version: Model version (defaults to latest)
            simulation_time: Optional time for backtesting (defaults to current time)
            
        Returns:
            TradingSignal or None if failed
        """
        start_time = time.time()
        
        try:
            # 1. Get model and strategy parameters (ADAPTIVE if available)
            model = self.model_registry.get_model(symbol, version)
            if not model:
                logger.warning(f"No model available for {symbol}")
                return None
            
            metadata = self.model_registry.get_model_metadata(symbol, version)
            
            # 🆕 USE ADAPTIVE PARAMETERS (if available)
            strategy_params = await self.model_registry.get_adaptive_strategy_parameters(symbol, version)
            
            # Log whether we're using adaptive or static parameters
            if strategy_params.get('_adaptive'):
                logger.debug(f"Using ADAPTIVE parameters for {symbol}: "
                           f"buy={strategy_params['buy_threshold']:.1%}, "
                           f"sell={strategy_params['sell_threshold']:.1%}")
            else:
                logger.debug(f"Using static parameters for {symbol}: "
                           f"buy={strategy_params['buy_threshold']:.1%}, "
                           f"sell={strategy_params['sell_threshold']:.1%}")
            
            # 2. Get current market data
            logger.debug(f"Getting current price for {symbol} at {simulation_time}")
            current_price = await self._get_current_price(symbol, simulation_time)
            if not current_price:
                logger.warning(f"No current price data for {symbol}")
                return None
            logger.debug(f"Current price for {symbol}: ${current_price}")
            
            # 3. Prepare features for prediction
            logger.debug(f"Preparing features for {symbol}")
            features = await self._prepare_features(symbol, metadata, simulation_time)
            if features is None:
                logger.warning(f"Failed to prepare features for {symbol}")
                return None
            logger.debug(f"Features prepared for {symbol}: shape {features.shape}")
            
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
            
            # 11. Store prediction in database (NEW: Fix for missing predictions)
            await self._store_prediction(trading_signal, metadata)
            
            return trading_signal
            
        except Exception as e:
            logger.error(f"Signal generation failed for {symbol}: {e}")
            return None

    async def _get_current_price(self, symbol: str, simulation_time: Optional[datetime] = None) -> Optional[float]:
        """Get current price from database or cache"""
        try:
            # Ensure database manager is initialized
            await self._ensure_db_manager()
            
            # Skip Redis cache in backtest mode or when simulation_time is provided
            if not self.backtest_mode and not simulation_time and self.redis_client:
                cache_key = f"price:current:{symbol}"
                cached_price = self.redis_client.get(cache_key)
                if cached_price:
                    return float(cached_price)
            
            # Get token info first
            token_info = await self.db_manager.get_token_by_symbol(symbol)
            if not token_info:
                logger.warning(f"Token {symbol} not found in database")
                return None
            
            # Handle both dictionary and object returns from get_token_by_symbol
            if hasattr(token_info, 'token_id'):
                token_id = token_info.token_id
            else:
                token_id = token_info['token_id']
            
            # Get price from database (latest or at simulation time)
            if simulation_time:
                # For backtesting: get the most recent price before or at simulation time
                # Make simulation_time timezone-aware if needed
                from datetime import timezone
                if simulation_time.tzinfo is None:
                    simulation_time_utc = simulation_time.replace(tzinfo=timezone.utc)
                else:
                    simulation_time_utc = simulation_time
                
                # Go back further to ensure we find data
                start_time = simulation_time_utc - timedelta(days=7)  # Go back 7 days
                
                logger.debug(f"Looking for {symbol} price data from {start_time} to {simulation_time_utc}")
                
                ohlcv_data = await self.db_manager.get_ohlcv_data(
                    token_id=token_id,
                    resolution='1H',
                    start_time=start_time,
                    end_time=simulation_time_utc + timedelta(hours=1)  # Include simulation time
                )
                
                if ohlcv_data:
                    # Filter to only records at or before simulation time and get the most recent
                    valid_records = [r for r in ohlcv_data if r.time <= simulation_time_utc]
                    if valid_records:
                        latest_record = max(valid_records, key=lambda x: x.time)
                        logger.debug(f"Found price for {symbol} at {latest_record.time}: ${latest_record.close}")
                        return float(latest_record.close)
                    else:
                        logger.warning(f"No records found at or before {simulation_time_utc} for {symbol}")
                        # Debug: show what records we did find
                        if ohlcv_data:
                            logger.debug(f"Available records for {symbol}: {[r.time for r in ohlcv_data[:3]]}")
                else:
                    logger.warning(f"No OHLCV data found for {symbol} in range {start_time} to {simulation_time_utc}")
            else:
                # For live trading: get latest price
                price = await self.db_manager.get_latest_price(token_id)
                
            if price:
                return float(price)
            
            # Final fallback - could integrate with external API here
            logger.warning(f"No current price data available for {symbol}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            return None

    async def _prepare_features(self, symbol: str, metadata: ModelMetadata, simulation_time: Optional[datetime] = None) -> Optional[np.ndarray]:
        """
        Prepare features using EXACT same pattern as test_simple_inference.py (PROVEN TO WORK)
        
        Args:
            symbol: Token symbol
            metadata: Model metadata with input requirements
            simulation_time: Optional time for backtesting (defaults to current time)
            
        Returns:
            Feature array ready for model inference or None if failed
        """
        try:
            logger.debug(f"Preparing features for {symbol} using WORKING test_simple_inference.py pattern")
            
            # Get token address from symbol
            await self._ensure_db_manager()
            token_info = await self.db_manager.get_token_by_symbol(symbol)
            if not token_info:
                logger.error(f"Token {symbol} not found in database")
                return None
            
            # Handle both dictionary and object returns from get_token_by_symbol
            if hasattr(token_info, 'address'):
                token_address = token_info.address
            else:
                token_address = token_info['address']
            logger.debug(f"Found token {symbol} with address {token_address}")
            
            # Get clean DataFrame from InferenceDataProcessor (with caching benefits)
            await self._ensure_inference_processor()
            inference_data = await self.inference_processor.prepare_inference_data(
                token_address=token_address,
                resolution='1H',
                simulation_time=simulation_time
            )
            
            if not inference_data or not inference_data.get('ready_for_inference'):
                logger.warning(f"Inference data not ready for {symbol}")
                return None
            
            # Get clean DataFrame (processed by DataProcessor.prepare_inference_ready_data)
            features_df = inference_data['features_dataframe']
            logger.debug(f"Got clean DataFrame for {symbol}: shape {features_df.shape}")
            
            # Use EXACT same DataProcessor.prepare_ml_data() call as test_simple_inference.py
            from ..data.data_processor import DataProcessor
            data_processor = DataProcessor()
            _, X_test, _, _ = data_processor.prepare_ml_data(
                features_df,
                target_col='close',
                sequence_length=metadata.sequence_length,
                prediction_horizon=1,
                test_size=0.0,  # Use all data
                include_feature_names=False,
                test_mode=True  # CRITICAL: Same as test_simple_inference.py
            )
            
            if len(X_test) == 0:
                logger.warning(f"No sequences generated for {symbol}")
                return None
            
            # Get the latest sequence (for immediate prediction)
            latest_sequence = X_test[-1]  # Shape: (sequence_length, num_features)
            
            # Store the data_processor for inverse transform (CRITICAL)
            self._current_data_processor = data_processor
            
            logger.debug(f"Prepared inference sequence for {symbol}: shape {latest_sequence.shape}, ready for model.predict()")
            
            return latest_sequence.astype(np.float32)
                
        except Exception as e:
            logger.error(f"Feature preparation failed for {symbol}: {e}")
            return None

    async def _predict_with_model(self, model, features: np.ndarray, symbol: str) -> Optional[float]:
        """Generate prediction using LSTM model"""
        try:
            # Validate inputs
            if model is None:
                logger.error(f"Model is None for {symbol}")
                return None
            
            if features is None:
                logger.error(f"Features is None for {symbol}")
                return None
            
            # Check prediction cache (skip in backtest mode)
            cache_key = f"prediction:{symbol}:{hash(features.tobytes())}"
            if not self.backtest_mode and cache_key in self._prediction_cache:
                cached_time, prediction = self._prediction_cache[cache_key]
                if (datetime.now() - cached_time).seconds < self.config.cache_predictions_seconds:
                    return prediction
            
            # Make prediction
            features_batch = np.expand_dims(features, axis=0)  # Add batch dimension
            logger.debug(f"Making prediction for {symbol} with features shape: {features_batch.shape}")
            prediction = model.predict(features_batch, verbose=0)
            
            # Check if prediction is valid
            if prediction is None:
                logger.error(f"Model returned None prediction for {symbol}")
                return None
            
            # Extract scalar prediction
            raw_prediction = float(prediction[0][0]) if len(prediction.shape) > 1 else float(prediction[0])
            
            # Cache the prediction (skip in backtest mode)
            if not self.backtest_mode:
                self._prediction_cache[cache_key] = (datetime.now(), raw_prediction)
            
            return raw_prediction
            
        except Exception as e:
            logger.error(f"Model prediction failed for {symbol}: {e}")
            return None

    async def _convert_prediction_to_price(self, raw_prediction: float, current_price: float, 
                                         symbol: str, metadata: ModelMetadata) -> float:
        """Convert raw model prediction to actual price prediction using the same method as training"""
        try:
            # Check for invalid predictions first
            if np.isnan(raw_prediction) or np.isinf(raw_prediction):
                logger.warning(f"Invalid raw prediction for {symbol}: {raw_prediction}, using current price")
                return current_price
            
            # CRITICAL: Use the SAME conversion method as the training pipeline
            # The models output scaled percentage changes that need to be:
            # 1. Inverse scaled using the price_scaler 
            # 2. Converted to absolute price using: price * (1 + percentage_change)
            
            # SIMPLIFIED APPROACH: Use the same simple logic as test_simple_inference.py
            # The model output is already scaled appropriately, we just need to apply it
            
            try:
                # Use the SAME data_processor that was used for feature preparation
                if hasattr(self, '_current_data_processor') and self._current_data_processor is not None:
                    data_processor = self._current_data_processor
                    
                    # Use the same inverse_transform_predictions method as training
                    scaled_predictions = np.array([raw_prediction])  # Single prediction
                    prices_at_sequence_end = np.array([current_price])  # Current price is the reference
                    
                    # This uses the exact same logic as test_simple_inference.py
                    absolute_predictions = data_processor.inverse_transform_predictions(
                        scaled_predictions, prices_at_sequence_end
                    )
                    predicted_price = absolute_predictions[0]
                    
                    # Calculate the actual percentage change for logging
                    percentage_change = (predicted_price / current_price - 1) * 100
                    
                    logger.debug(f"Prediction conversion for {symbol}: raw={raw_prediction:.6f}, pct_change={percentage_change:.3f}%, price=${current_price:.6f} -> ${predicted_price:.6f}")
                else:
                    # No data_processor available, fallback
                    logger.warning(f"No data_processor available for {symbol}, using fallback conversion")
                    predicted_price = current_price * (1 + raw_prediction)
                
            except Exception as convert_e:
                logger.warning(f"Failed to use inverse_transform_predictions for {symbol}: {convert_e}")
                # Fallback: treat as raw percentage change
                predicted_price = current_price * (1 + raw_prediction)
            
            # Sanity check - prevent unrealistic predictions
            max_change = 0.50  # 50% max change
            min_price = current_price * (1 - max_change)
            max_price = current_price * (1 + max_change)
            
            if predicted_price < min_price or predicted_price > max_price:
                change_pct = (predicted_price / current_price - 1) * 100
                logger.warning(f"Extreme prediction for {symbol}: {change_pct:.2f}% change, clamping to ±50%")
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
            
            # Use configurable confidence threshold
            from ..config.config import config
            default_confidence = self.config.default_confidence_threshold or config.MIN_PREDICTION_CONFIDENCE
            confidence_threshold = strategy_params.get('confidence_threshold', default_confidence)
            
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
        """Cache the generated signal in Redis (disabled in backtest mode)"""
        if not self.redis_client or self.backtest_mode:
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

    async def _store_prediction(self, signal: TradingSignal, metadata: ModelMetadata):
        """Store the model prediction in the database"""
        if not self.db_manager or self.backtest_mode:
            return
            
        try:
            # Get token_id from database
            token_info = await self.db_manager.get_token_by_symbol(signal.symbol)
            if not token_info:
                logger.warning(f"Token not found for symbol {signal.symbol}, skipping prediction storage")
                return
            
            # Create prediction data
            from ..database.production_db import ModelPredictionData
            prediction_data = ModelPredictionData(
                prediction_id=None,  # Will be auto-generated
                token_id=token_info['token_id'],
                model_name=f"LSTM_{signal.symbol}",
                model_version=signal.model_version,
                prediction_time=signal.timestamp,
                prediction_action=signal.signal_type.value,
                confidence_score=signal.confidence,
                predicted_price_change=signal.predicted_change_pct,
                prediction_horizon_minutes=60,  # Default 1 hour
                input_features=None  # Could add feature data later if needed
            )
            
            # Save to database
            prediction_id = await self.db_manager.save_model_prediction(prediction_data)
            logger.debug(f"Stored prediction {prediction_id} for {signal.symbol}: {signal.signal_type.value} ({signal.confidence:.2f} confidence)")
            
        except Exception as e:
            logger.warning(f"Failed to store prediction for {signal.symbol}: {e}")

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

    def _log_initialization(self):
        """Log strategy engine initialization details"""
        logger.info(f"Simple Strategy Engine initialized (backtest_mode={self.backtest_mode})")
        
        # Get actual confidence threshold value for logging
        from ..config.config import config
        actual_confidence_threshold = self.config.default_confidence_threshold or config.MIN_PREDICTION_CONFIDENCE
        
        logger.info(f"Config: buy_threshold={self.config.default_buy_threshold:.1%}, "
                   f"sell_threshold={self.config.default_sell_threshold:.1%}, "
                   f"confidence_threshold={actual_confidence_threshold:.1%}")
        logger.info(f"Performance: target_latency={self.config.max_prediction_latency_ms}ms "
                   f"(Note: First model loads will be slower due to GPU initialization)")
        logger.info(f"Memory: max_models_in_memory={self.config.max_models_in_memory}, "
                   f"threshold={self.config.model_memory_threshold_mb}MB "
                   f"(Optimized for ~20 token models)")

# Convenience functions for easy integration
_strategy_engine_instance: Optional[SimpleStrategyEngine] = None

def get_strategy_engine(backtest_mode: bool = False) -> SimpleStrategyEngine:
    """Get or create the global strategy engine instance"""
    global _strategy_engine_instance
    if _strategy_engine_instance is None or (backtest_mode and not getattr(_strategy_engine_instance, 'backtest_mode', False)):
        _strategy_engine_instance = SimpleStrategyEngine(backtest_mode=backtest_mode)
    return _strategy_engine_instance

async def generate_signal(symbol: str, version: Optional[str] = None) -> Optional[TradingSignal]:
    """Convenience function to generate a single signal"""
    engine = get_strategy_engine()
    return await engine.generate_signal(symbol, version)

async def generate_signals(symbols: List[str]) -> Dict[str, Optional[TradingSignal]]:
    """Convenience function to generate multiple signals"""
    engine = get_strategy_engine()
    return await engine.generate_signals_batch(symbols) 