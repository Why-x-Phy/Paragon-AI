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
# ===== REMOVED: unused imports =====
# os, Path, joblib, sys were removed as part of the clean separation architecture

from .data_processor import DataProcessor
from ..database.production_db import ProductionDBManager
from ..config import get_config
from ..utils.logger import log_manager

logger = log_manager.get_logger("inference_data_processor")


@dataclass
class InferenceDataConfig:
    """Configuration for inference data processing"""
    # Data requirements
    min_data_points: int = 210  # Minimum hours of data (need 200+ for 200-period SMA)
    data_quality_threshold: float = 0.95  # Minimum completeness
    lookback_hours: int = 240  # Hours of historical data for features (need 200+ for 200-period SMA, 168+ for rolling beta)
    
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
            self.multi_timeframe_periods = ['4h', '1d', '1w']


class InferenceDataProcessor:
    """
    Enhanced data processor for model inference with full feature engineering
    
    Integrates the comprehensive DataProcessor with database operations
    to provide production-ready inference data preparation.
    """
    
    def __init__(self, db_manager: ProductionDBManager, config: Optional[InferenceDataConfig] = None, backtest_mode: bool = False):
        self.db_manager = db_manager
        self.config = config or self._load_config_from_env()
        self.data_processor = DataProcessor()
        self.logger = logging.getLogger(__name__)
        self.backtest_mode = backtest_mode  # Disable caching in backtest mode
        
        # ===== REMOVED: All caching complexity =====
        # Caching was removed because:
        # 1. Production runs hourly - fresh data needed each cycle
        # 2. DataFrame serialization causes bugs (str vs DataFrame)
        # 3. 1-2 second feature generation is negligible for hourly schedule
        # 4. Simpler architecture without cache invalidation complexity
        
        # ===== REMOVED: scaler_cache and models_dir =====
        # These were removed as part of the clean separation architecture.
        
        if backtest_mode:
            self.logger.info("Inference Data Processor initialized in BACKTEST MODE")
        else:
            self.logger.info("Inference Data Processor initialized in LIVE MODE - no caching for fresh hourly data")
        
    def _load_config_from_env(self) -> InferenceDataConfig:
        """Load configuration from environment variables"""
        env_config = get_config()
        
        return InferenceDataConfig(
            min_data_points=int(env_config.get('MIN_DATA_POINTS_FOR_INFERENCE', 210)),
            data_quality_threshold=float(env_config.get('DATA_QUALITY_THRESHOLD', 0.95)),
            lookback_hours=int(env_config.get('DATA_PROCESSOR_LOOKBACK_HOURS', 240)),
            
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
            multi_timeframe_periods=env_config.get('MULTI_TIMEFRAME_PERIODS', '4h,1d,1w').split(','),
            
            # Data quality
            outlier_detection=env_config.get('OUTLIER_DETECTION_ENABLED', 'true').lower() == 'true',
            outlier_z_threshold=float(env_config.get('OUTLIER_Z_SCORE_THRESHOLD', 3.0))
        )
    
    async def prepare_inference_data(self, token_address: str, resolution: str = '1H', simulation_time: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
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
            
            # 2. Fetch raw OHLCV data (no caching - always fresh for hourly inference)
            ohlcv_data = await self._fetch_ohlcv_data(token['token_id'], resolution, simulation_time)
            if not ohlcv_data or len(ohlcv_data) < self.config.min_data_points:
                self.logger.warning(f"Insufficient data for {token_address}: {len(ohlcv_data) if ohlcv_data else 0} points")
                return None
            
            # 3. Convert to DataFrame for processing
            df = self._ohlcv_to_dataframe(ohlcv_data)
            
            # 4. Validate data quality
            data_quality = self._assess_data_quality(df)
            if data_quality['completeness'] < self.config.data_quality_threshold:
                self.logger.warning(f"Data quality too low for {token_address}: {data_quality['completeness']:.2%}")
                return None
            
            # 5. Apply clean feature engineering using DataProcessor interface
            # CRITICAL: Use the SAME corrected end_time as _fetch_ohlcv_data to avoid double incomplete candle fetch
            if simulation_time:
                corrected_end_time = simulation_time
            else:
                # Use the same complete candle logic as _fetch_ohlcv_data
                now = datetime.utcnow()
                corrected_end_time = now.replace(minute=0, second=0, microsecond=0)
                if now.minute > 0 or now.second > 0:
                    corrected_end_time = corrected_end_time - timedelta(hours=1)
            
            features_df = await self.data_processor.prepare_inference_ready_data(
                token_id=token['token_id'],
                start_time=corrected_end_time - timedelta(hours=self.config.lookback_hours),
                end_time=corrected_end_time,  # Use corrected end_time to avoid incomplete candles
                symbol=token.get('symbol'),
                db_manager=self.db_manager  # Pass the db_manager for thread safety
            )
            
            if features_df is None:
                self.logger.warning(f"Failed to prepare features for {token_address}")
                return None
            
            # 6. Prepare final inference data structure
            inference_data = self._create_inference_data_structure(features_df, token, data_quality, symbol=token.get('symbol'))
            
            self.logger.info(f"Successfully prepared inference data for {token_address}: "
                           f"{len(features_df)} records, {len(features_df.columns)} features")
            
            return inference_data
            
        except Exception as e:
            self.logger.error(f"Error preparing inference data for {token_address}: {e}")
            return None
    
    async def _get_token_info(self, token_address: str) -> Optional[Dict[str, Any]]:
        """Get token information from database"""
        try:
            query = "SELECT token_id, address, symbol, name FROM tokens WHERE address = $1"
            
            async with self.db_manager.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query, token_address)
            
            if row:
                return dict(row)
            return None
            
        except Exception as e:
            self.logger.error(f"Error fetching token info for {token_address}: {e}")
            return None
    
    async def _get_token_symbol(self, token_address: str) -> Optional[str]:
        """Get token symbol from database"""
        try:
            token_info = await self._get_token_info(token_address)
            return token_info['symbol'] if token_info else None
        except Exception as e:
            self.logger.error(f"Error fetching token symbol for {token_address}: {e}")
            return None
    
    async def _fetch_social_data(self, symbol: str, price_df: pd.DataFrame) -> pd.DataFrame:
        """Fetch social data for the same time period as price data"""
        try:
            # Get the time range from price data
            if price_df.empty or 'timestamp' not in price_df.columns:
                return pd.DataFrame()
            
            # Calculate days needed based on price data timespan
            start_time = pd.to_datetime(price_df['timestamp'].min())
            end_time = pd.to_datetime(price_df['timestamp'].max())
            days_needed = (end_time - start_time).days + 1
            
            # Use the data processor's social data fetching method
            social_df = await self.data_processor.fetch_sentiment_data_timescale(symbol, days_needed)
            
            return social_df
            
        except Exception as e:
            self.logger.error(f"Error fetching social data for {symbol}: {e}")
            return pd.DataFrame()
    
    async def _fetch_ohlcv_data(self, token_id: int, resolution: str, simulation_time: Optional[datetime] = None) -> Optional[List]:
        """Fetch OHLCV data from database"""
        try:
            if simulation_time:
                # Use simulation time for backtesting
                end_time = simulation_time
            else:
                # For live trading: Use the LATEST COMPLETE hour to avoid incomplete candles
                now = datetime.utcnow()
                end_time = now.replace(minute=0, second=0, microsecond=0)
                # If we're still in the current hour, go back to the previous complete hour
                if now.minute > 0 or now.second > 0:
                    end_time = end_time - timedelta(hours=1)  # Simpler: just subtract 1 hour
                    self.logger.info(f"🕐 Live trading: Using latest COMPLETE hour {end_time} (current time: {now})")
                else:
                    self.logger.info(f"🕐 Live trading: Current hour just started, using {end_time} (current time: {now})")
            
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
        # Keep timestamp as column like training pipeline - don't set as index
        df.sort_values('timestamp', inplace=True)
        
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
    
    # ===== REMOVED: _apply_feature_engineering =====
    # This method was removed as part of the clean separation architecture.
    # Feature engineering is now handled by DataProcessor.prepare_inference_ready_data()
    # which provides the same functionality with better maintainability.
    
    def _create_inference_data_structure(self, features_df: pd.DataFrame, token: Dict, data_quality: Dict, symbol: str = None) -> Dict[str, Any]:
        """Create final inference data structure using CLEAN DataFrame from DataProcessor"""
        
        symbol = symbol or token.get('symbol', 'UNKNOWN')
        
        # CLEAN APPROACH: Return the clean processed DataFrame ready for prepare_ml_data()
        try:
            # Price information
            latest_price_info = {
                'current_price': float(features_df['close'].iloc[-1]),
                'price_change_24h': float(features_df['close'].iloc[-1] - features_df['close'].iloc[-25]) if len(features_df) >= 25 else 0.0,
                'volume_24h': float(features_df['volume'].iloc[-24:].sum()) if len(features_df) >= 24 else float(features_df['volume'].sum())
            }
            
            self.logger.info(f"✅ Inference data prepared for {symbol}:")
            self.logger.info(f"   📊 DataFrame shape: {features_df.shape}")
            self.logger.info(f"   📈 Current price: ${latest_price_info['current_price']:.4f}")
            self.logger.info(f"   🎯 Ready for DataProcessor.prepare_ml_data() call")
            
            return {
                'token_info': token,
                'features_dataframe': features_df,  # Clean DataFrame ready for prepare_ml_data()
                'price_info': latest_price_info,
                'data_quality': data_quality,
                'timestamp': datetime.utcnow().isoformat(),
                'ready_for_inference': True,
                'data_points': len(features_df),
                'quality_score': data_quality['completeness']
            }
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create inference data for {symbol}: {e}")
            return {
                'token_info': token,
                'error': f'Data processing failed: {str(e)}',
                'ready_for_inference': False,
                'data_points': len(features_df) if isinstance(features_df, pd.DataFrame) else 0
            }
    
    async def get_batch_inference_data(self, token_addresses: List[str], resolution: str = '1H') -> Dict[str, Any]:
        """Prepare inference data for multiple tokens (no caching)"""
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
    
    # ===== REMOVED: All caching methods =====
    # _get_cached_data, _cache_inference_data, clear_cache, get_cache_statistics
    # were removed to simplify the architecture for hourly inference cycles

    # ===== REMOVED: load_scalers_for_model & get_scaler_statistics =====
    # These methods were removed as part of the clean separation architecture.
    # Scaling is now handled automatically by DataProcessor.prepare_ml_data() in test_mode=True


# =============================================================================
# INTEGRATION FUNCTION FOR HOURLY SCHEDULER
# =============================================================================

async def create_inference_data_processor(db_manager: ProductionDBManager, backtest_mode: bool = False) -> InferenceDataProcessor:
    """Create and configure inference data processor for hourly scheduler"""
    processor = InferenceDataProcessor(db_manager, backtest_mode=backtest_mode)
    
    logger.info(f"Inference data processor initialized with config:")
    logger.info(f"  - Min data points: {processor.config.min_data_points}")
    logger.info(f"  - Data quality threshold: {processor.config.data_quality_threshold}")
    logger.info(f"  - Lookback hours: {processor.config.lookback_hours}")
    logger.info(f"  - Technical indicators: {processor.config.enable_cyclical_time}")
    logger.info(f"  - Multi-timeframe: {processor.config.enable_multi_timeframe}")
    logger.info(f"  - Backtest mode: {backtest_mode}")
    
    return processor 