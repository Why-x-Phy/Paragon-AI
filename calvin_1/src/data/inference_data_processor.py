"""
Calvin AI Inference Data Processor

Integrates DataProcessor with HourlyInferenceScheduler for complete feature engineering.
This completes Phase 1 by providing production-ready inference data preparation.
"""

import asyncio
import json
import logging
import numpy as np
import pandas as pd
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import os
from pathlib import Path

from .data_processor import DataProcessor
from ..database.production_db import ProductionDBManager
from ..config import get_config
from ..utils.logger import log_manager

logger = log_manager.get_logger("inference_data_processor")


@dataclass
class InferenceDataConfig:
    """Configuration for inference data processing"""
    # Data requirements
    min_data_points: int = 24  # Minimum hours of data
    data_quality_threshold: float = 0.95  # Minimum completeness
    lookback_hours: int = 48  # Hours of historical data for features
    
    # Technical indicators
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_period: int = 20
    bollinger_std: int = 2
    sma_periods: List[int] = None
    ema_periods: List[int] = None
    
    # Feature engineering flags
    enable_cyclical_time: bool = True
    enable_volatility_features: bool = True
    enable_fair_value_gaps: bool = True
    enable_money_flow: bool = True
    enable_multi_timeframe: bool = True
    multi_timeframe_periods: List[str] = None
    
    # Data quality
    outlier_detection: bool = True
    outlier_z_threshold: float = 3.0
    
    def __post_init__(self):
        if self.sma_periods is None:
            self.sma_periods = [5, 10, 20, 50, 200]
        if self.ema_periods is None:
            self.ema_periods = [12, 26, 50, 100]
        if self.multi_timeframe_periods is None:
            self.multi_timeframe_periods = ['1h', '4h', '1d']


class InferenceDataProcessor:
    """
    Enhanced data processor for model inference with full feature engineering
    
    Integrates the comprehensive DataProcessor with database operations
    to provide production-ready inference data preparation.
    """
    
    def __init__(self, db_manager: ProductionDBManager, config: Optional[InferenceDataConfig] = None):
        self.db_manager = db_manager
        self.config = config or self._load_config_from_env()
        self.data_processor = DataProcessor()
        self.logger = logging.getLogger(__name__)
        
        # Redis cache integration (ENHANCED: Replace in-memory cache with Redis-backed cache)
        self.redis_cache_prefix = "inference_features"
        self.redis_client = db_manager.redis_client  # Use existing connection
        
        # Environment-based configuration
        env_config = get_config()
        self.cache_ttl = int(env_config.get('DATA_PROCESSOR_CACHE_TTL', 3600))
        
        # REAL HIT/MISS TRACKING
        self.cache_stats = {
            'hits': 0,
            'misses': 0,
            'total_hit_time_ms': 0,
            'total_miss_time_ms': 0,
            'start_time': datetime.utcnow()
        }
        
    def _load_config_from_env(self) -> InferenceDataConfig:
        """Load configuration from environment variables"""
        env_config = get_config()
        
        return InferenceDataConfig(
            min_data_points=int(env_config.get('MIN_DATA_POINTS_FOR_INFERENCE', 24)),
            data_quality_threshold=float(env_config.get('DATA_QUALITY_THRESHOLD', 0.95)),
            lookback_hours=int(env_config.get('DATA_PROCESSOR_LOOKBACK_HOURS', 48)),
            
            # Technical indicators from env
            rsi_period=int(env_config.get('RSI_PERIOD', 14)),
            macd_fast=int(env_config.get('MACD_FAST', 12)),
            macd_slow=int(env_config.get('MACD_SLOW', 26)),
            macd_signal=int(env_config.get('MACD_SIGNAL', 9)),
            bollinger_period=int(env_config.get('BOLLINGER_PERIOD', 20)),
            bollinger_std=int(env_config.get('BOLLINGER_STD', 2)),
            
            # Periods from env (comma-separated)
            sma_periods=[int(p) for p in env_config.get('SMA_PERIODS', '5,10,20,50,200').split(',')],
            ema_periods=[int(p) for p in env_config.get('EMA_PERIODS', '12,26,50,100').split(',')],
            
            # Feature flags from env
            enable_cyclical_time=env_config.get('ENABLE_CYCLICAL_TIME_FEATURES', 'true').lower() == 'true',
            enable_volatility_features=env_config.get('ENABLE_VOLATILITY_FEATURES', 'true').lower() == 'true',
            enable_fair_value_gaps=env_config.get('ENABLE_FAIR_VALUE_GAPS', 'true').lower() == 'true',
            enable_money_flow=env_config.get('ENABLE_MONEY_FLOW_FEATURES', 'true').lower() == 'true',
            enable_multi_timeframe=env_config.get('ENABLE_MULTI_TIMEFRAME', 'true').lower() == 'true',
            
            # Multi-timeframe periods
            multi_timeframe_periods=env_config.get('MULTI_TIMEFRAME_PERIODS', '1h,4h,1d').split(','),
            
            # Data quality
            outlier_detection=env_config.get('OUTLIER_DETECTION_ENABLED', 'true').lower() == 'true',
            outlier_z_threshold=float(env_config.get('OUTLIER_Z_SCORE_THRESHOLD', 3.0))
        )
    
    async def prepare_inference_data(self, token_address: str, resolution: str = '1h') -> Optional[Dict[str, Any]]:
        """
        Prepare comprehensive inference data for a token
        
        Args:
            token_address: Token address to prepare data for
            resolution: Data resolution (1h recommended for inference)
            
        Returns:
            Dict containing processed features and metadata
        """
        try:
            self.logger.info(f"Preparing inference data for {token_address} at {resolution} resolution")
            
            # 1. Get token information
            token = await self._get_token_info(token_address)
            if not token:
                self.logger.error(f"Token {token_address} not found in database")
                return None
            
            # 2. Check cache first with timing
            cache_key = f"{token_address}_{resolution}"
            cache_start_time = time.time()
            cached_data = await self._get_cached_data(cache_key)
            cache_time_ms = (time.time() - cache_start_time) * 1000
            
            if cached_data:
                # CACHE HIT - Track statistics
                self.cache_stats['hits'] += 1
                self.cache_stats['total_hit_time_ms'] += cache_time_ms
                self.logger.debug(f"CACHE HIT: Using Redis cached inference data for {token_address} ({cache_time_ms:.1f}ms)")
                return cached_data
            else:
                # CACHE MISS - Will track miss timing at the end
                self.cache_stats['misses'] += 1
                miss_start_time = time.time()
            
            # 3. Fetch raw OHLCV data
            ohlcv_data = await self._fetch_ohlcv_data(token['id'], resolution)
            if not ohlcv_data or len(ohlcv_data) < self.config.min_data_points:
                self.logger.warning(f"Insufficient data for {token_address}: {len(ohlcv_data) if ohlcv_data else 0} points")
                return None
            
            # 4. Convert to DataFrame for processing
            df = self._ohlcv_to_dataframe(ohlcv_data)
            
            # 5. Validate data quality
            data_quality = self._assess_data_quality(df)
            if data_quality['completeness'] < self.config.data_quality_threshold:
                self.logger.warning(f"Data quality too low for {token_address}: {data_quality['completeness']:.2%}")
                return None
            
            # 6. Apply comprehensive feature engineering
            features_df = await self._apply_feature_engineering(df, token_address)
            
            # 7. Prepare final inference data structure
            inference_data = self._create_inference_data_structure(features_df, token, data_quality)
            
            # 8. Cache the results and track miss timing
            await self._cache_inference_data(cache_key, inference_data)
            
            # CACHE MISS - Track total computation time
            miss_time_ms = (time.time() - miss_start_time) * 1000
            self.cache_stats['total_miss_time_ms'] += miss_time_ms
            
            self.logger.info(f"CACHE MISS: Successfully prepared inference data for {token_address}: "
                           f"{len(features_df)} records, {len(features_df.columns)} features ({miss_time_ms:.1f}ms)")
            
            return inference_data
            
        except Exception as e:
            self.logger.error(f"Error preparing inference data for {token_address}: {e}")
            return None
    
    async def _get_token_info(self, token_address: str) -> Optional[Dict[str, Any]]:
        """Get token information from database"""
        try:
            query = "SELECT id, address, symbol, name FROM tokens WHERE address = $1"
            
            async with self.db_manager.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query, token_address)
            
            if row:
                return dict(row)
            return None
            
        except Exception as e:
            self.logger.error(f"Error fetching token info for {token_address}: {e}")
            return None
    
    async def _fetch_ohlcv_data(self, token_id: int, resolution: str) -> Optional[List]:
        """Fetch OHLCV data from database"""
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=self.config.lookback_hours)
            
            ohlcv_data = await self.db_manager.get_ohlcv_data(
                token_id=token_id,
                resolution=resolution,
                start_time=start_time,
                end_time=end_time,
                limit=self.config.lookback_hours + 10  # Extra buffer
            )
            
            return ohlcv_data
            
        except Exception as e:
            self.logger.error(f"Error fetching OHLCV data for token {token_id}: {e}")
            return None
    
    def _ohlcv_to_dataframe(self, ohlcv_data: List) -> pd.DataFrame:
        """Convert OHLCV data to DataFrame"""
        data = []
        for record in ohlcv_data:
            data.append({
                'timestamp': record.time,
                'open': float(record.open),
                'high': float(record.high),
                'low': float(record.low),
                'close': float(record.close),
                'volume': float(record.volume)
            })
        
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        
        return df
    
    def _assess_data_quality(self, df: pd.DataFrame) -> Dict[str, float]:
        """Assess data quality metrics"""
        total_expected = len(df)
        missing_values = df.isnull().sum().sum()
        
        # Check for price anomalies (zeros, negative values)
        price_anomalies = (
            (df['open'] <= 0).sum() + 
            (df['high'] <= 0).sum() + 
            (df['low'] <= 0).sum() + 
            (df['close'] <= 0).sum()
        )
        
        # Check for volume anomalies
        volume_anomalies = (df['volume'] < 0).sum()
        
        # Check for gap anomalies (high < low, etc.)
        structure_anomalies = (
            (df['high'] < df['low']).sum() +
            (df['high'] < df['open']).sum() +
            (df['high'] < df['close']).sum() +
            (df['low'] > df['open']).sum() +
            (df['low'] > df['close']).sum()
        )
        
        total_anomalies = price_anomalies + volume_anomalies + structure_anomalies
        total_issues = missing_values + total_anomalies
        
        completeness = max(0.0, 1.0 - (total_issues / (total_expected * len(df.columns))))
        
        return {
            'completeness': completeness,
            'missing_values': missing_values,
            'price_anomalies': price_anomalies,
            'volume_anomalies': volume_anomalies,
            'structure_anomalies': structure_anomalies,
            'total_records': total_expected
        }
    
    async def _apply_feature_engineering(self, df: pd.DataFrame, token_address: str) -> pd.DataFrame:
        """Apply comprehensive feature engineering using DataProcessor"""
        try:
            self.logger.debug(f"Applying feature engineering for {token_address}")
            
            # Reset index to get timestamp as column for DataProcessor
            df_for_processing = df.reset_index()
            
            # 1. Calculate technical indicators
            df_processed = self.data_processor.calculate_technical_indicators(df_for_processing)
            
            # 2. Add cyclical time features
            if self.config.enable_cyclical_time:
                df_processed = self.data_processor.add_time_cyclical_features(df_processed)
            
            # 3. Add volatility features
            if self.config.enable_volatility_features:
                df_processed = self.data_processor.add_volatility_of_volatility(df_processed)
            
            # 4. Add Fair Value Gaps
            if self.config.enable_fair_value_gaps:
                df_processed = self.data_processor.add_fair_value_gaps(df_processed)
            
            # 5. Add money flow features
            if self.config.enable_money_flow:
                df_processed = self.data_processor.add_money_flow_features(df_processed)
            
            # 6. Add realized volatility
            df_processed = self.data_processor.add_realized_volatility(df_processed)
            
            # 7. Add multi-timeframe analysis
            if self.config.enable_multi_timeframe:
                df_processed = self.data_processor.add_multi_timeframe_features(
                    df_processed, 
                    timeframes=self.config.multi_timeframe_periods
                )
            
            # 8. Handle outliers if enabled
            if self.config.outlier_detection:
                df_processed = self._handle_outliers(df_processed)
            
            # 9. Fill any remaining NaN values
            df_processed = df_processed.fillna(method='ffill').fillna(method='bfill').fillna(0)
            
            # Set timestamp back as index
            if 'timestamp' in df_processed.columns:
                df_processed.set_index('timestamp', inplace=True)
            
            return df_processed
            
        except Exception as e:
            self.logger.error(f"Error in feature engineering for {token_address}: {e}")
            # Return original dataframe if feature engineering fails
            return df
    
    def _handle_outliers(self, df: pd.DataFrame) -> pd.DataFrame:
        """Handle outliers using Z-score method"""
        try:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            
            for col in numeric_cols:
                if col in ['timestamp', 'open', 'high', 'low', 'close', 'volume']:
                    continue  # Skip core price/volume columns
                
                # Calculate Z-scores
                z_scores = np.abs((df[col] - df[col].mean()) / df[col].std())
                
                # Cap outliers at threshold
                outlier_mask = z_scores > self.config.outlier_z_threshold
                if outlier_mask.any():
                    # Replace outliers with median value
                    median_value = df[col].median()
                    df.loc[outlier_mask, col] = median_value
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error handling outliers: {e}")
            return df
    
    def _create_inference_data_structure(self, features_df: pd.DataFrame, token: Dict, data_quality: Dict) -> Dict[str, Any]:
        """Create final inference data structure"""
        
        # Get feature names (exclude timestamp and core OHLCV)
        core_columns = ['open', 'high', 'low', 'close', 'volume']
        feature_columns = [col for col in features_df.columns if col not in core_columns]
        
        # Get latest features for immediate inference
        latest_features = features_df[feature_columns].iloc[-1].to_dict()
        
        # Get historical feature matrix for sequence models
        feature_matrix = features_df[feature_columns].values
        
        # Price information
        latest_price_info = {
            'current_price': float(features_df['close'].iloc[-1]),
            'price_change_24h': float(features_df['close'].iloc[-1] - features_df['close'].iloc[-25]) if len(features_df) >= 25 else 0.0,
            'volume_24h': float(features_df['volume'].iloc[-24:].sum()) if len(features_df) >= 24 else float(features_df['volume'].sum())
        }
        
        return {
            'token_info': token,
            'latest_features': latest_features,
            'feature_matrix': feature_matrix.tolist(),  # Convert numpy array to list for JSON serialization
            'feature_names': feature_columns,
            'price_info': latest_price_info,
            'data_quality': data_quality,
            'timestamp': datetime.utcnow().isoformat(),
            'ready_for_inference': True,
            'data_points': len(features_df),
            'feature_count': len(feature_columns),
            'quality_score': data_quality['completeness']
        }
    
    async def _get_cached_data(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """ENHANCED: Retrieve from Redis cache"""
        try:
            redis_key = f"{self.redis_cache_prefix}:{cache_key}"
            cached_data = await self.redis_client.get(redis_key)
            if cached_data:
                return json.loads(cached_data)
            return None
        except Exception as e:
            self.logger.error(f"Redis cache read failed: {e}")
            return None
    
    async def _cache_inference_data(self, cache_key: str, data: Dict[str, Any]):
        """ENHANCED: Cache to Redis with TTL"""
        try:
            redis_key = f"{self.redis_cache_prefix}:{cache_key}"
            await self.redis_client.setex(
                redis_key, 
                self.cache_ttl,  # 1 hour TTL (aligns with inference schedule)
                json.dumps(data, default=str)
            )
            self.logger.debug(f"Cached inference data for {cache_key}")
        except Exception as e:
            self.logger.error(f"Redis cache write failed: {e}")
    
    async def get_batch_inference_data(self, token_addresses: List[str], resolution: str = '1h') -> Dict[str, Any]:
        """Prepare inference data for multiple tokens"""
        results = {}
        
        for token_address in token_addresses:
            try:
                data = await self.prepare_inference_data(token_address, resolution)
                if data:
                    results[token_address] = data
                else:
                    results[token_address] = {'error': 'Failed to prepare data', 'ready_for_inference': False}
            except Exception as e:
                results[token_address] = {'error': str(e), 'ready_for_inference': False}
        
        return results
    
    async def clear_cache(self):
        """ENHANCED: Clear Redis feature cache"""
        try:
            cache_pattern = f"{self.redis_cache_prefix}:*"
            keys = await self.redis_client.keys(cache_pattern)
            if keys:
                await self.redis_client.delete(*keys)
            self.logger.info(f"Redis feature cache cleared: {len(keys)} keys deleted")
        except Exception as e:
            self.logger.error(f"Failed to clear Redis cache: {e}")
    
    async def get_cache_statistics(self) -> Dict[str, Any]:
        """ENHANCED: Get cache statistics with REAL hit/miss tracking and performance metrics"""
        try:
            # Get Redis memory usage
            redis_info = await self.redis_client.info('memory')
            
            # Count cached inference keys
            cache_pattern = f"{self.redis_cache_prefix}:*"
            inference_keys = await self.redis_client.keys(cache_pattern)
            
            # Calculate real hit/miss rates and performance
            total_requests = self.cache_stats['hits'] + self.cache_stats['misses']
            hit_rate = (self.cache_stats['hits'] / total_requests * 100) if total_requests > 0 else 0
            
            # Calculate average response times
            avg_hit_time_ms = (self.cache_stats['total_hit_time_ms'] / self.cache_stats['hits']) if self.cache_stats['hits'] > 0 else 0
            avg_miss_time_ms = (self.cache_stats['total_miss_time_ms'] / self.cache_stats['misses']) if self.cache_stats['misses'] > 0 else 0
            
            # Calculate performance improvement
            performance_improvement = (avg_miss_time_ms / avg_hit_time_ms) if avg_hit_time_ms > 0 else 0
            
            # Calculate uptime
            uptime_seconds = (datetime.utcnow() - self.cache_stats['start_time']).total_seconds()
            
            return {
                # Basic Cache Info
                'cached_tokens': len(inference_keys),
                'redis_memory_used_mb': redis_info.get('used_memory', 0) / (1024 * 1024),
                'inference_cache_keys': len(inference_keys),
                'cache_prefix': self.redis_cache_prefix,
                'cache_ttl_seconds': self.cache_ttl,
                
                # Global Redis Statistics
                'redis_keyspace_hits': redis_info.get('keyspace_hits', 0),
                'redis_keyspace_misses': redis_info.get('keyspace_misses', 0),
                'redis_global_hit_rate': (
                    redis_info.get('keyspace_hits', 0) / 
                    (redis_info.get('keyspace_hits', 0) + redis_info.get('keyspace_misses', 0)) * 100
                ) if (redis_info.get('keyspace_hits', 0) + redis_info.get('keyspace_misses', 0)) > 0 else 0,
                
                # REAL Instance-Specific Performance Metrics
                'instance_stats': {
                    'total_requests': total_requests,
                    'cache_hits': self.cache_stats['hits'],
                    'cache_misses': self.cache_stats['misses'],
                    'hit_rate_percent': round(hit_rate, 1),
                    'average_hit_time_ms': round(avg_hit_time_ms, 2),
                    'average_miss_time_ms': round(avg_miss_time_ms, 2),
                    'performance_improvement_factor': round(performance_improvement, 1),
                    'uptime_seconds': round(uptime_seconds, 1),
                    'requests_per_minute': round(total_requests / (uptime_seconds / 60), 2) if uptime_seconds > 60 else 0
                },
                
                # Performance Summary
                'performance_summary': {
                    'status': 'excellent' if hit_rate >= 80 else 'good' if hit_rate >= 60 else 'poor',
                    'cache_effectiveness': f"{performance_improvement:.1f}x faster" if performance_improvement > 1 else "No improvement measured",
                    'efficiency_score': min(1.0, hit_rate / 100 * min(performance_improvement / 10, 1.0)) if performance_improvement > 0 else 0
                }
            }
        except Exception as e:
            self.logger.error(f"Cache statistics collection failed: {e}")
            return {'cache_statistics_error': str(e)}


# =============================================================================
# INTEGRATION FUNCTION FOR HOURLY SCHEDULER
# =============================================================================

async def create_inference_data_processor(db_manager: ProductionDBManager) -> InferenceDataProcessor:
    """Create and configure inference data processor for hourly scheduler"""
    processor = InferenceDataProcessor(db_manager)
    
    logger.info(f"Inference data processor initialized with config:")
    logger.info(f"  - Min data points: {processor.config.min_data_points}")
    logger.info(f"  - Data quality threshold: {processor.config.data_quality_threshold}")
    logger.info(f"  - Lookback hours: {processor.config.lookback_hours}")
    logger.info(f"  - Technical indicators: {processor.config.enable_cyclical_time}")
    logger.info(f"  - Multi-timeframe: {processor.config.enable_multi_timeframe}")
    
    return processor 