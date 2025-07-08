"""
Calvin AI LSTM Model Registry

Centralized registry for managing trained LSTM models with:
- Integration with existing trained models in models/ directory
- Model versioning and metadata management  
- Redis caching for model loading performance
- Hot model swapping capability
- Simple strategy parameter association
- Model performance tracking and degradation detection

This integrates with:
- Existing LSTM models (.h5 files)
- data_processor.py for feature preprocessing
- profit_functions.py simple_backtest_strategy
- Redis caching infrastructure
- Configuration system
"""

import os
import json
import asyncio
import hashlib
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import redis
import pickle
from dataclasses import dataclass, asdict

# TensorFlow imports with error handling
try:
    import tensorflow as tf
    # Suppress TensorFlow warnings for cleaner logs
    tf.get_logger().setLevel('ERROR')
    HAS_TENSORFLOW = True
except ImportError:
    HAS_TENSORFLOW = False
    tf = None

# Local imports - leveraging existing components
from ..config.config import config
from ..utils.logger import log_manager, log
from ..data.data_processor import DataProcessor
from ..model.profit_functions import simple_backtest_strategy

logger = log

@dataclass
class ModelMetadata:
    """Metadata for a trained LSTM model"""
    model_path: str
    symbol: str
    model_type: str
    created_at: datetime
    last_used: Optional[datetime]
    version: str  # Date version (YYYYMMDD) - maintained for backward compatibility
    input_shape: Tuple[int, int]
    sequence_length: int
    prediction_horizon: int
    
    # Enhanced versioning
    semantic_version: Optional[str] = None  # vMAJOR.MINOR.PATCH (e.g., "v1.0.0")
    is_legacy: bool = True  # True for old naming format, False for new
    
    # Performance metrics
    mse: Optional[float] = None
    mae: Optional[float] = None
    rmse: Optional[float] = None
    direction_accuracy: Optional[float] = None
    
    # Strategy parameters
    buy_threshold: float = 0.02  # Default 2%
    sell_threshold: float = 0.03  # Default 3%
    confidence_threshold: float = 0.10  # Will be overridden by global config in practice
    
    # Model hash for integrity checking
    model_hash: Optional[str] = None
    
    # Performance tracking
    usage_count: int = 0
    last_performance_score: Optional[float] = None
    performance_degradation_count: int = 0

class LSTMModelRegistry:
    """
    Centralized registry for managing LSTM models with Redis caching and 
    integration with existing Calvin AI infrastructure
    """
    
    def __init__(self, models_dir: Optional[str] = None, redis_client: Optional[redis.Redis] = None):
        """
        Initialize model registry
        
        Args:
            models_dir: Directory containing .h5 model files (defaults to config)
            redis_client: Redis client for caching (will create if None)
        """
        # Use existing configuration system
        self.models_dir = Path(models_dir or config.MODEL_BASE_PATH or "./calvin_1/models")
        self.registry_path = Path(config.MODEL_REGISTRY_PATH or f"{self.models_dir}/registry")
        
        # Create directories if they don't exist
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path.mkdir(parents=True, exist_ok=True)
        
        # Redis integration for caching
        self.redis_client = redis_client
        self.redis_binary_client = None  # Separate client for binary data
        
        if self.redis_client is None:
            try:
                # Text client for JSON metadata (with decode_responses=True)
                self.redis_client = redis.Redis(
                    host=config.REDIS_HOST or 'localhost',
                    port=config.REDIS_PORT or 6379,
                    password=config.REDIS_PASSWORD,
                    db=config.REDIS_DB or 0,
                    decode_responses=True
                )
                
                # Binary client for model weights (with decode_responses=False)
                self.redis_binary_client = redis.Redis(
                    host=config.REDIS_HOST or 'localhost',
                    port=config.REDIS_PORT or 6379,
                    password=config.REDIS_PASSWORD,
                    db=config.REDIS_DB or 0,
                    decode_responses=False  # Keep binary data as bytes
                )
                
                # Test connections
                self.redis_client.ping()
                self.redis_binary_client.ping()
                logger.info("Connected to Redis for model caching (text + binary clients)")
            except Exception as e:
                logger.warning(f"Redis connection failed, continuing without caching: {e}")
                self.redis_client = None
                self.redis_binary_client = None
        
        # In-memory model cache for hot swapping
        self._model_cache: Dict[str, tf.keras.Model] = {}
        self._metadata_cache: Dict[str, ModelMetadata] = {}
        
        # Cache configuration from environment
        self.cache_ttl = int(os.getenv('MODEL_CACHE_TTL', '3600'))  # 1 hour default
        self.max_models_in_memory = int(os.getenv('MAX_MODELS_IN_MEMORY', '10'))  # Keep top 10 hot
        
        # Integration with existing data processor
        self.data_processor = None
        
        # Initialize registry
        self._initialize_registry()
        
        logger.info(f"LSTM Model Registry initialized")
        logger.info(f"Models directory: {self.models_dir}")
        logger.info(f"Registry path: {self.registry_path}")
        logger.info(f"Redis caching: {'enabled' if self.redis_client else 'disabled'}")

    def _initialize_registry(self):
        """Initialize the registry by scanning existing models and only loading the latest version per symbol"""
        logger.info("Initializing model registry...")
        
        # Scan for existing .h5 files
        h5_files = list(self.models_dir.glob("*.h5"))
        logger.info(f"Found {len(h5_files)} .h5 model files")
        
        if not h5_files:
            logger.warning("No model files found to register")
            return
        
        # 🆕 OPTIMIZATION: Parse all filenames first without loading models
        parsed_models = {}  # symbol -> List[(file_path, parsed_data)]
        
        for model_file in h5_files:
            try:
                filename = model_file.stem
                parsed = self._parse_model_filename(filename)
                
                if not parsed:
                    logger.warning(f"Could not parse model filename: {filename}")
                    continue
                
                symbol = parsed['symbol']
                if symbol not in parsed_models:
                    parsed_models[symbol] = []
                
                parsed_models[symbol].append((model_file, parsed))
                
            except Exception as e:
                logger.error(f"Failed to parse model filename {model_file}: {e}")
        
        # 🆕 OPTIMIZATION: For each symbol, find and register only the latest version
        total_models_available = sum(len(models) for models in parsed_models.values())
        models_to_register = []
        
        for symbol, symbol_models in parsed_models.items():
            if not symbol_models:
                continue
            
            # Sort models using the same priority logic as _find_model_key
            def sort_key(item):
                model_file, parsed = item
                # Priority: new format first, then date (newest first), then semantic version
                is_new = not parsed['is_legacy']
                date_version = parsed['date_version']
                semantic_parts = [0, 0, 0]  # Default for legacy
                
                if parsed['semantic_version']:
                    try:
                        # Parse semantic version (e.g., "v1.0.2" -> [1, 0, 2])
                        version_str = parsed['semantic_version'][1:]  # Remove 'v'
                        semantic_parts = [int(x) for x in version_str.split('.')]
                    except (ValueError, IndexError):
                        pass
                
                return (is_new, date_version, semantic_parts)
            
            # Get the latest model for this symbol
            latest_model = max(symbol_models, key=sort_key)
            models_to_register.append(latest_model)
            
            # Log what we're skipping for transparency
            if len(symbol_models) > 1:
                latest_file, latest_parsed = latest_model
                skipped_count = len(symbol_models) - 1
                logger.debug(f"📊 {symbol}: Selected latest model {latest_parsed['filename']}, skipping {skipped_count} older versions")
        
        # 🆕 REGISTER ONLY THE LATEST MODELS
        logger.info(f"🎯 Optimization: Registering {len(models_to_register)} latest models (skipping {total_models_available - len(models_to_register)} older versions)")
        
        for model_file, parsed_data in models_to_register:
            try:
                self._register_existing_model(model_file)
            except Exception as e:
                logger.error(f"Failed to register latest model {model_file}: {e}")
        
        # 🎯 PERFORMANCE SUMMARY
        symbols_loaded = len(models_to_register)
        models_skipped = total_models_available - len(models_to_register)
        efficiency_pct = (models_skipped / total_models_available * 100) if total_models_available > 0 else 0
        
        logger.info(f"✅ Registry initialization complete: {len(self._metadata_cache)} latest models registered")
        logger.info(f"📈 Performance: {symbols_loaded} symbols loaded, {models_skipped} older models skipped ({efficiency_pct:.1f}% reduction)")
        
        # Log which symbols we have models for
        symbols = list(set(parsed['symbol'] for _, parsed in models_to_register))
        symbols.sort()
        if len(symbols) <= 10:
            logger.info(f"🎯 Available symbols: {', '.join(symbols)}")
        else:
            logger.info(f"🎯 Available symbols: {', '.join(symbols[:10])}... (and {len(symbols)-10} more)")

    def register_new_model(self, model_path: str, symbol: str, semantic_version: str, 
                          model_type: str = "lstm", **kwargs) -> bool:
        """
        Register a newly trained model with semantic versioning
        
        Args:
            model_path: Path to the .h5 model file
            symbol: Token symbol
            semantic_version: Semantic version (e.g., "v1.0.0")
            model_type: Model type (default: "lstm")
            **kwargs: Additional metadata fields
            
        Returns:
            True if registration successful, False otherwise
        """
        if not HAS_TENSORFLOW:
            logger.error("TensorFlow not available")
            return False
            
        try:
            model_path_obj = Path(model_path)
            if not model_path_obj.exists():
                logger.error(f"Model file not found: {model_path}")
                return False
            
            # Load model to get input shape
            model = tf.keras.models.load_model(str(model_path))
            input_shape = model.input_shape[1:]  # Remove batch dimension
            sequence_length = input_shape[0] if len(input_shape) > 0 else 0
            
            # Extract date from filename or use current date
            filename = model_path_obj.stem
            parsed = self._parse_model_filename(filename)
            date_version = parsed['date_version'] if parsed else datetime.now().strftime('%Y%m%d')
            
            # Create metadata
            metadata = ModelMetadata(
                model_path=str(model_path),
                symbol=symbol,
                model_type=model_type,
                created_at=datetime.fromtimestamp(model_path_obj.stat().st_mtime),
                last_used=None,
                version=date_version,
                semantic_version=semantic_version,
                is_legacy=False,  # New format
                input_shape=input_shape,
                sequence_length=sequence_length,
                prediction_horizon=kwargs.get('prediction_horizon', 1),
                mse=kwargs.get('mse'),
                mae=kwargs.get('mae'),
                rmse=kwargs.get('rmse'),
                direction_accuracy=kwargs.get('direction_accuracy'),
                model_hash=self._calculate_model_hash(model_path_obj),
                buy_threshold=kwargs.get('buy_threshold', 0.02),
                sell_threshold=kwargs.get('sell_threshold', 0.03),
                confidence_threshold=kwargs.get('confidence_threshold', 0.10)
            )
            
            # Create model key
            model_key = f"{symbol}_{semantic_version}_{date_version}"
            
            # Store in cache
            self._metadata_cache[model_key] = metadata
            
            # Save metadata to disk
            metadata_file = self.registry_path / f"{model_key}_metadata.json"
            with open(metadata_file, 'w') as f:
                json.dump(self._serialize_metadata(metadata), f, indent=2)
            
            logger.info(f"Registered new model: {model_key} (semantic: {semantic_version})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register new model {model_path}: {e}")
            return False

    def _register_existing_model(self, model_path: Path):
        """Register an existing .h5 model file"""
        if not HAS_TENSORFLOW:
            logger.warning("TensorFlow not available, skipping model registration")
            return
            
        # Parse filename using enhanced parser
        filename = model_path.stem
        parsed = self._parse_model_filename(filename)
        
        if not parsed:
            logger.warning(f"Could not parse model filename: {filename}")
            return
        
        symbol = parsed['symbol']
        model_type = parsed['model_type']
        
        # Load model to get input shape
        try:
            model = tf.keras.models.load_model(str(model_path))
            input_shape = model.input_shape[1:]  # Remove batch dimension
            sequence_length = input_shape[0] if len(input_shape) > 0 else 0
            
            # Load metrics if available
            metrics_file = model_path.parent / f"{filename}_metrics.json"
            metrics = {}
            if metrics_file.exists():
                with open(metrics_file, 'r') as f:
                    metrics = json.load(f)
            
            # Create metadata with enhanced versioning
            metadata = ModelMetadata(
                model_path=str(model_path),
                symbol=symbol,
                model_type=model_type,
                created_at=datetime.fromtimestamp(model_path.stat().st_mtime),
                last_used=None,
                version=parsed['date_version'],  # Date version for backward compatibility
                semantic_version=parsed['semantic_version'],  # New semantic version
                is_legacy=parsed['is_legacy'],  # Track format type
                input_shape=input_shape,
                sequence_length=sequence_length,
                prediction_horizon=1,  # Default, can be updated
                mse=metrics.get('mse'),
                mae=metrics.get('mae'),
                rmse=metrics.get('rmse'),
                direction_accuracy=metrics.get('direction_accuracy'),
                model_hash=self._calculate_model_hash(model_path)
            )
            
            # Create model key (maintain backward compatibility)
            if parsed['is_legacy']:
                model_key = f"{symbol}_{metadata.version}"
            else:
                # For new format, include semantic version in key for uniqueness
                model_key = f"{symbol}_{metadata.semantic_version}_{metadata.version}"
            
            # Store in cache
            self._metadata_cache[model_key] = metadata
            
            # Save metadata to disk
            metadata_file = self.registry_path / f"{model_key}_metadata.json"
            with open(metadata_file, 'w') as f:
                json.dump(self._serialize_metadata(metadata), f, indent=2)
            
            logger.info(f"Registered model: {model_key} (symbol: {symbol}, legacy: {parsed['is_legacy']})")
            
        except Exception as e:
            logger.error(f"Failed to load model {model_path}: {e}")

    def _parse_model_filename(self, filename: str) -> Dict[str, Any]:
        """
        Parse both legacy and new model filename formats
        
        Supports:
        - Legacy: symbol_modeltype_YYYYMMDD.h5 (e.g., "Fartcoin_lstm_20250614.h5")
        - New: symbol_modeltype_vMAJOR.MINOR.PATCH_YYYYMMDD.h5 (e.g., "Fartcoin_lstm_v1.0.0_20250614.h5")
        
        Returns:
            Dict with parsed components or None if invalid format
        """
        parts = filename.split('_')
        
        if len(parts) < 3:
            return None
        
        symbol = parts[0]
        model_type = parts[1]
        
        # Check for new format with semantic version
        semantic_version = None
        date_version = None
        is_legacy = True
        
        # Look for semantic version pattern (vX.Y.Z)
        for i, part in enumerate(parts[2:], 2):
            if part.startswith('v') and '.' in part:
                # Found semantic version
                semantic_version = part
                is_legacy = False
                # Date should be the next part
                if i + 1 < len(parts):
                    date_candidate = parts[i + 1]
                    if len(date_candidate) == 8 and date_candidate.isdigit():
                        date_version = date_candidate
                break
        
        # If no semantic version found, look for date in legacy format
        if is_legacy:
            for part in parts[2:]:
                if len(part) == 8 and part.isdigit():
                    date_version = part
                    break
        
        # Default date if none found
        if not date_version:
            date_version = datetime.now().strftime('%Y%m%d')
        
        return {
            'symbol': symbol,
            'model_type': model_type,
            'semantic_version': semantic_version,
            'date_version': date_version,
            'is_legacy': is_legacy,
            'filename': filename
        }

    def _extract_version_from_filename(self, filename: str) -> str:
        """Extract version/date from model filename (backward compatibility)"""
        parsed = self._parse_model_filename(filename)
        if parsed:
            return parsed['date_version']
        
        # Fallback to original logic
        parts = filename.split('_')
        for part in parts:
            if len(part) == 8 and part.isdigit():
                return part
        return datetime.now().strftime('%Y%m%d')

    def _calculate_model_hash(self, model_path: Path) -> str:
        """Calculate hash of model file for integrity checking"""
        hasher = hashlib.md5()
        with open(model_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _serialize_metadata(self, metadata: ModelMetadata) -> Dict[str, Any]:
        """Serialize metadata to JSON-compatible format"""
        data = asdict(metadata)
        # Convert datetime objects to ISO strings
        if data['created_at']:
            data['created_at'] = data['created_at'].isoformat()
        if data['last_used']:
            data['last_used'] = data['last_used'].isoformat()
        return data

    def _deserialize_metadata(self, data: Dict[str, Any]) -> ModelMetadata:
        """Deserialize metadata from JSON"""
        # Convert ISO strings back to datetime objects
        if data['created_at']:
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data['last_used']:
            data['last_used'] = datetime.fromisoformat(data['last_used'])
        
        # Handle backward compatibility for models without new fields
        if 'semantic_version' not in data:
            data['semantic_version'] = None
        if 'is_legacy' not in data:
            data['is_legacy'] = True
            
        return ModelMetadata(**data)

    def get_model(self, symbol: str, version: Optional[str] = None) -> Optional[tf.keras.Model]:
        """
        Get a trained model for a symbol
        
        Args:
            symbol: Token symbol (e.g., 'BONK', 'Fartcoin')
            version: Specific version (defaults to latest)
            
        Returns:
            Loaded TensorFlow model or None if not found
        """
        if not HAS_TENSORFLOW:
            logger.error("TensorFlow not available")
            return None
            
        # Find model key
        model_key = self._find_model_key(symbol, version)
        if not model_key:
            logger.warning(f"No model found for symbol: {symbol}, version: {version}")
            return None
        
        # Check in-memory cache first
        if model_key in self._model_cache:
            logger.debug(f"Model {model_key} loaded from memory cache")
            self._update_usage_stats(model_key)
            return self._model_cache[model_key]
        
        # Check Redis cache
        model = self._load_model_from_redis(model_key)
        if model is not None:
            self._model_cache[model_key] = model
            self._update_usage_stats(model_key)
            return model
        
        # Load from disk
        metadata = self._metadata_cache.get(model_key)
        if not metadata:
            logger.error(f"No metadata found for model: {model_key}")
            return None
        
        try:
            logger.info(f"Loading model from disk: {metadata.model_path}")
            model = tf.keras.models.load_model(metadata.model_path)
            
            # Verify model integrity
            if self._verify_model_integrity(metadata):
                # Cache in memory and Redis
                self._cache_model_in_memory(model_key, model)
                self._cache_model_in_redis(model_key, model)
                self._update_usage_stats(model_key)
                
                logger.info(f"Model {model_key} loaded successfully")
                return model
            else:
                logger.error(f"Model integrity check failed for {model_key}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to load model {model_key}: {e}")
            return None

    def _find_model_key(self, symbol: str, version: Optional[str] = None) -> Optional[str]:
        """Find the model key for a symbol and version"""
        if version:
            # Try exact match first (backward compatibility)
            model_key = f"{symbol}_{version}"
            if model_key in self._metadata_cache:
                return model_key
            
            # Try semantic version match
            for key, metadata in self._metadata_cache.items():
                if (metadata.symbol == symbol and 
                    (metadata.version == version or metadata.semantic_version == version)):
                    return key
        else:
            # Find latest version for symbol
            symbol_models = []
            for key, metadata in self._metadata_cache.items():
                if metadata.symbol == symbol:
                    symbol_models.append((key, metadata))
            
            if symbol_models:
                # Sort by priority: new format > legacy format, then by date, then by semantic version
                def sort_key(item):
                    key, metadata = item
                    # Priority: new format first, then date (newest first), then semantic version
                    is_new = not metadata.is_legacy
                    date_version = metadata.version
                    semantic_parts = [0, 0, 0]  # Default for legacy
                    
                    if metadata.semantic_version:
                        try:
                            # Parse semantic version (e.g., "v1.0.2" -> [1, 0, 2])
                            version_str = metadata.semantic_version[1:]  # Remove 'v'
                            semantic_parts = [int(x) for x in version_str.split('.')]
                        except (ValueError, IndexError):
                            pass
                    
                    return (is_new, date_version, semantic_parts)
                
                # Get the highest priority model
                latest_item = max(symbol_models, key=sort_key)
                return latest_item[0]
        
        return None

    def _verify_model_integrity(self, metadata: ModelMetadata) -> bool:
        """Verify model file integrity using stored hash"""
        if not metadata.model_hash:
            return True  # No hash stored, assume valid
        
        current_hash = self._calculate_model_hash(Path(metadata.model_path))
        return current_hash == metadata.model_hash

    def _cache_model_in_memory(self, model_key: str, model: tf.keras.Model):
        """Cache model in memory with LRU eviction"""
        # Remove oldest model if cache is full
        if len(self._model_cache) >= self.max_models_in_memory:
            # Find least recently used model
            lru_key = min(self._metadata_cache.keys(), 
                         key=lambda k: self._metadata_cache[k].last_used or datetime.min)
            if lru_key in self._model_cache:
                del self._model_cache[lru_key]
                logger.debug(f"Evicted model from memory cache: {lru_key}")
        
        self._model_cache[model_key] = model
        logger.debug(f"Cached model in memory: {model_key}")

    def _cache_model_in_redis(self, model_key: str, model: tf.keras.Model):
        """Cache model in Redis for persistence across restarts"""
        if not self.redis_binary_client:
            return
        
        try:
            # Serialize model weights (more efficient than full model)
            # Note: model.get_weights() already returns numpy arrays
            weights_data = model.get_weights()
            serialized_weights = pickle.dumps(weights_data)
            
            redis_key = f"model_weights:{model_key}"
            # Use binary client to avoid UTF-8 decoding issues
            self.redis_binary_client.setex(redis_key, self.cache_ttl, serialized_weights)
            
            logger.debug(f"Cached model weights in Redis: {model_key}")
        except Exception as e:
            logger.warning(f"Failed to cache model in Redis: {e}")

    def _load_model_from_redis(self, model_key: str) -> Optional[tf.keras.Model]:
        """Load model from Redis cache"""
        if not self.redis_binary_client:
            return None
        
        try:
            redis_key = f"model_weights:{model_key}"
            # Use binary client to get raw bytes without UTF-8 decoding
            serialized_weights = self.redis_binary_client.get(redis_key)
            
            if serialized_weights:
                # Load model architecture from disk first
                metadata = self._metadata_cache.get(model_key)
                if not metadata:
                    return None
                
                model = tf.keras.models.load_model(metadata.model_path)
                
                # Restore cached weights
                weights_data = pickle.loads(serialized_weights)
                model.set_weights(weights_data)
                
                logger.debug(f"Loaded model from Redis cache: {model_key}")
                return model
                
        except Exception as e:
            logger.debug(f"Failed to load model from Redis: {e}")
        
        return None

    def _update_usage_stats(self, model_key: str):
        """Update model usage statistics"""
        if model_key in self._metadata_cache:
            metadata = self._metadata_cache[model_key]
            metadata.last_used = datetime.now()
            metadata.usage_count += 1
            
            # Save updated metadata
            self._save_metadata(model_key, metadata)

    def _save_metadata(self, model_key: str, metadata: ModelMetadata):
        """Save metadata to disk"""
        try:
            metadata_file = self.registry_path / f"{model_key}_metadata.json"
            with open(metadata_file, 'w') as f:
                json.dump(self._serialize_metadata(metadata), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metadata for {model_key}: {e}")

    def get_model_metadata(self, symbol: str, version: Optional[str] = None) -> Optional[ModelMetadata]:
        """Get metadata for a model"""
        model_key = self._find_model_key(symbol, version)
        if not model_key:
            return None
        return self._metadata_cache.get(model_key)

    def get_display_version(self, metadata: ModelMetadata) -> str:
        """Get the display version (semantic if available, otherwise date)"""
        if metadata.semantic_version:
            return f"{metadata.semantic_version} ({metadata.version})"
        return metadata.version

    def list_models(self, symbol: Optional[str] = None) -> List[ModelMetadata]:
        """List all registered models, optionally filtered by symbol"""
        models = list(self._metadata_cache.values())
        if symbol:
            models = [m for m in models if m.symbol == symbol]
        
        # Sort by symbol and then by creation date (newest first)
        models.sort(key=lambda m: (m.symbol, m.created_at), reverse=True)
        return models

    def get_strategy_parameters(self, symbol: str, version: Optional[str] = None) -> Dict[str, float]:
        """Get simple strategy parameters for a model"""
        metadata = self.get_model_metadata(symbol, version)
        
        # Always use global config for confidence threshold (ignore metadata)
        from ..config.config import config
        
        if not metadata:
            return {
                'buy_threshold': 0.02,
                'sell_threshold': 0.03,
                'confidence_threshold': config.MIN_PREDICTION_CONFIDENCE  # Always use global config
            }
        
        return {
            'buy_threshold': metadata.buy_threshold,
            'sell_threshold': metadata.sell_threshold,
            'confidence_threshold': config.MIN_PREDICTION_CONFIDENCE  # ALWAYS use global config (ignore metadata)
        }

    async def get_adaptive_strategy_parameters(self, symbol: str, version: Optional[str] = None) -> Dict[str, float]:
        """
        Get strategy parameters with adaptive engine integration
        
        This method first checks the adaptive strategy engine for dynamically adjusted parameters,
        then falls back to static model metadata or global config defaults.
        """
        try:
            # Try to get adaptive parameters from the adaptive strategy engine
            try:
                from . import adaptive_strategy
                adaptive_engine = adaptive_strategy._adaptive_strategy_instance
                
                if adaptive_engine and symbol in adaptive_engine.strategy_parameters:
                    # Get adapted parameters with _adaptive flag
                    adapted_params = await adaptive_engine.get_adapted_parameters(symbol)
                    if adapted_params:
                        return {
                            'buy_threshold': adapted_params['buy_threshold'],
                            'sell_threshold': adapted_params['sell_threshold'],
                            'confidence_threshold': adapted_params['confidence_threshold'],
                            '_adaptive': True  # Flag to indicate these are adaptive parameters
                        }
            except (ImportError, AttributeError) as e:
                # Adaptive engine not available or not initialized
                logger.debug(f"Adaptive strategy engine not available: {e}")
            
            # Fall back to static parameters
            static_params = self.get_strategy_parameters(symbol, version)
            static_params['_adaptive'] = False  # Flag to indicate these are static parameters
            return static_params
            
        except Exception as e:
            logger.error(f"Failed to get adaptive strategy parameters for {symbol}: {e}")
            # Emergency fallback to global config
            from ..config.config import config
            return {
                'buy_threshold': 0.02,
                'sell_threshold': 0.03,
                'confidence_threshold': config.MIN_PREDICTION_CONFIDENCE,  # Uses 0.10
                '_adaptive': False
            }

    def update_strategy_parameters(self, symbol: str, buy_threshold: float, 
                                 sell_threshold: float, confidence_threshold: Optional[float] = None,
                                 version: Optional[str] = None):
        """Update simple strategy parameters for a model"""
        model_key = self._find_model_key(symbol, version)
        if not model_key or model_key not in self._metadata_cache:
            logger.error(f"Model not found: {symbol}, version: {version}")
            return
        
        # Use global config if confidence_threshold not provided
        if confidence_threshold is None:
            from ..config.config import config
            confidence_threshold = config.MIN_PREDICTION_CONFIDENCE
        
        metadata = self._metadata_cache[model_key]
        metadata.buy_threshold = buy_threshold
        metadata.sell_threshold = sell_threshold
        metadata.confidence_threshold = confidence_threshold
        
        self._save_metadata(model_key, metadata)
        logger.info(f"Updated strategy parameters for {model_key}")

    def run_simple_backtest(self, symbol: str, ohlcv_data: pd.DataFrame, 
                          version: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Run simple backtest for a model using existing simple_backtest_strategy
        
        Args:
            symbol: Token symbol
            ohlcv_data: OHLCV dataframe for backtesting
            version: Model version (defaults to latest)
            
        Returns:
            Backtest results or None if failed
        """
        # Get model and metadata
        model = self.get_model(symbol, version)
        metadata = self.get_model_metadata(symbol, version)
        
        if not model or not metadata:
            logger.error(f"Model or metadata not found for {symbol}")
            return None
        
        try:
            # Initialize data processor if needed
            if not self.data_processor:
                self.data_processor = DataProcessor()
            
            # Prepare data for prediction
            sequence_length = metadata.sequence_length
            X, _, _, _ = self.data_processor.prepare_ml_data(
                ohlcv_data,
                target_col='close',
                sequence_length=sequence_length,
                prediction_horizon=metadata.prediction_horizon,
                test_size=0.99  # Use most data for testing
            )
            
            # Generate predictions
            predictions = model.predict(X, verbose=0)
            
            # Convert predictions back to prices
            prices = ohlcv_data['close'].values[-len(predictions):]
            predicted_prices = self.data_processor.inverse_transform_predictions(
                predictions, prices[:-metadata.prediction_horizon] if metadata.prediction_horizon > 1 else prices
            )
            
            # Run simple backtest strategy
            strategy_params = self.get_strategy_parameters(symbol, version)
            results = simple_backtest_strategy(
                prices=prices,
                predictions=predicted_prices,
                ohlcv_df=ohlcv_data,
                include_detailed_trades=True,
                verbosity=1,
                resolution="1H",  # Default resolution
                **strategy_params
            )
            
            # Update performance metrics
            self._update_performance_metrics(symbol, version, results)
            
            return results
            
        except Exception as e:
            logger.error(f"Backtest failed for {symbol}: {e}")
            return None

    def _update_performance_metrics(self, symbol: str, version: Optional[str], 
                                  backtest_results: Dict[str, Any]):
        """Update model performance metrics based on backtest results"""
        model_key = self._find_model_key(symbol, version)
        if not model_key or model_key not in self._metadata_cache:
            return
        
        metadata = self._metadata_cache[model_key]
        
        # Update performance score (using total return as primary metric)
        total_return = backtest_results.get('Total Return', 0)
        
        # Check for performance degradation
        if metadata.last_performance_score is not None:
            if total_return < metadata.last_performance_score * 0.8:  # 20% drop
                metadata.performance_degradation_count += 1
                logger.warning(f"Performance degradation detected for {model_key}: "
                             f"{total_return:.2f}% vs previous {metadata.last_performance_score:.2f}%")
        
        metadata.last_performance_score = total_return
        self._save_metadata(model_key, metadata)

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of the model registry"""
        total_models = len(self._metadata_cache)
        models_in_memory = len(self._model_cache)
        
        # Check for models with performance degradation
        degraded_models = sum(1 for m in self._metadata_cache.values() 
                            if m.performance_degradation_count > 2)
        
        # Count legacy vs new format models
        legacy_models = sum(1 for m in self._metadata_cache.values() if m.is_legacy)
        new_format_models = total_models - legacy_models
        
        redis_status = "connected" if self.redis_client else "disconnected"
        try:
            if self.redis_client:
                self.redis_client.ping()
                redis_status = "connected"
        except:
            redis_status = "error"
        
        return {
            'total_models': total_models,
            'legacy_format_models': legacy_models,
            'new_format_models': new_format_models,
            'models_in_memory': models_in_memory,
            'degraded_models': degraded_models,
            'redis_status': redis_status,
            'models_directory': str(self.models_dir),
            'registry_initialized': True
        }

# Global registry instance for reuse across the application
_registry_instance: Optional[LSTMModelRegistry] = None

def get_model_registry() -> LSTMModelRegistry:
    """Get or create the global model registry instance"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = LSTMModelRegistry()
    return _registry_instance

# Convenience functions for easy integration
def load_model(symbol: str, version: Optional[str] = None) -> Optional[tf.keras.Model]:
    """Convenience function to load a model"""
    registry = get_model_registry()
    return registry.get_model(symbol, version)

def get_strategy_params(symbol: str, version: Optional[str] = None) -> Dict[str, float]:
    """Convenience function to get strategy parameters"""
    registry = get_model_registry()
    return registry.get_strategy_parameters(symbol, version)

def run_backtest(symbol: str, ohlcv_data: pd.DataFrame, 
                version: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Convenience function to run backtest"""
    registry = get_model_registry()
    return registry.run_simple_backtest(symbol, ohlcv_data, version) 

def register_model(model_path: str, symbol: str, semantic_version: str, 
                  model_type: str = "lstm", **kwargs) -> bool:
    """Convenience function to register a new model with semantic versioning"""
    registry = get_model_registry()
    return registry.register_new_model(model_path, symbol, semantic_version, model_type, **kwargs) 