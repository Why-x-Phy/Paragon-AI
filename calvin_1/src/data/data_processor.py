import os
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Union, Any, Tuple
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.model_selection import train_test_split
import time
import concurrent.futures
import pandas_ta as ta
from scipy import stats
import asyncio
import joblib

from .birdeye_api import BirdEyeAPI
from .helius_api import HeliusAPI
from .lunarcrush_api import LunarCrushAPI
from ..config.config import config
from ..utils.logger import log_manager
from ..database.production_db import ProductionDBManager, OHLCVData

logger = log_manager.get_logger("data_processor")

class DataProcessor:
    """Process and combine data from different sources for ML model training"""
    
    def __init__(self):
        self.birdeye_api = BirdEyeAPI()
        self.helius_api = HeliusAPI()
        self.lunarcrush_api = LunarCrushAPI()
        
        # Create data directory if it doesn't exist
        self.data_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Scalers for normalization
        self.price_scaler = MinMaxScaler()
        self.feature_scaler = StandardScaler()
        
        # Store last known prices for predictions
        self.last_prices = {}
        
        # Store prices at sequence end for test set
        self.prices_at_sequence_end_test = None
    
    def fetch_price_data(
        self, 
        token_address: str, 
        resolution: str = "1H", 
        days: int = 30,
        day_offset: int = 0
    ) -> pd.DataFrame:
        """
        Fetch historical price data for a token using ProductionDBManager
        
        Args:
            token_address: Address of the token
            resolution: Time resolution (1m, 5m, 15m, 1h, 4h, 1d)
            days: Number of days to fetch
            day_offset: Offset days from current time (for chunked processing)
            
        Returns:
            DataFrame with OHLCV data
        """
        logger.info(f"Fetching price data for {token_address}, days {days}, resolution {resolution}" +
                   (f", offset {day_offset} days" if day_offset > 0 else ""))
        
        # Use async context manager to properly handle database connections
        async def fetch_data_async():
            db_manager = ProductionDBManager()
            try:
                await db_manager.initialize()
                
                # Get token by address
                token_info = db_manager.get_token_by_address(token_address)
                if not token_info:
                    logger.warning(f"Token {token_address} not found in database.")
                    return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # Calculate date range with offset
                end_date = datetime.now() - timedelta(days=day_offset)
                start_date = end_date - timedelta(days=days)
                
                logger.info(f"Fetching OHLCV data for token_id {token_info.token_id} from {start_date} to {end_date}")
                
                # Get OHLCV data from TimescaleDB
                ohlcv_data = await db_manager.get_ohlcv_data(
                    token_id=token_info.token_id,
                    resolution=resolution,
                    start_time=start_date,
                    end_time=end_date
                )
                
                if ohlcv_data:
                    logger.info(f"Found {len(ohlcv_data):,} OHLCV records in TimescaleDB")
                    
                    # Convert OHLCVData objects to DataFrame
                    data_records = []
                    for data in ohlcv_data:
                        data_records.append({
                            'timestamp': data.time,
                            'open': data.open,
                            'high': data.high,
                            'low': data.low,
                            'close': data.close,
                            'volume': data.volume
                        })
                    
                    df = pd.DataFrame(data_records)
                    if not df.empty:
                        # Sort by timestamp ascending (oldest first)
                        df = df.sort_values('timestamp')
                        logger.info(f"Successfully loaded {len(df)} price records")
                        return df
                else:
                    logger.warning(f"No OHLCV data found for {token_address}")
                
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
            except Exception as e:
                logger.error(f"Error fetching price data: {e}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            finally:
                await db_manager.close()
        
        # Run the async function
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're in an async context, use run_in_executor
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(lambda: asyncio.run(fetch_data_async()))
                    return future.result()
            else:
                return asyncio.run(fetch_data_async())
        except Exception as e:
            logger.error(f"Error running async fetch_price_data: {e}")
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    async def fetch_sentiment_data_timescale(
        self, 
        symbol: str = "SOL", 
        days: int = 30,
        db_manager: Optional['ProductionDBManager'] = None
    ) -> pd.DataFrame:
        """
        Fetch social sentiment data from TimescaleDB market_events table
        
        Args:
            symbol: Token symbol to fetch data for
            days: Number of days of historical data to fetch
            
        Returns:
            DataFrame containing social metrics compatible with existing feature engineering
        """
        logger.info(f"Fetching social data from TimescaleDB for {symbol} ({days} days)")
        
        # Use provided db_manager or create a new one
        local_db_manager = db_manager or ProductionDBManager()
        should_close = db_manager is None
        try:
            if should_close:
                await local_db_manager.initialize()
            
            # Get social data from TimescaleDB
            social_data = await local_db_manager.get_social_data_by_symbol(symbol, days)
            
            if social_data and len(social_data) > 0:
                logger.info(f"Found {len(social_data)} social records in TimescaleDB for {symbol}")
                
                # Convert to DataFrame (already in the right format from get_social_data)
                df = pd.DataFrame(social_data)
                
                # Set timestamp as index
                if 'timestamp' in df.columns:
                    df.set_index('timestamp', inplace=True)
                
                # Sort by timestamp descending
                df.sort_index(ascending=False, inplace=True)
                
                logger.info(f"Loaded social data from TimescaleDB for {symbol}, shape: {df.shape}")
                return df
            else:
                logger.warning(f"No social data found in TimescaleDB for {symbol}, falling back to API")
                
        except Exception as e:
            logger.error(f"Error fetching social data from TimescaleDB: {e}")
            logger.info("Falling back to API call")
        finally:
            if should_close:
                await local_db_manager.close()
        
        # If we reach here, either there was an error or no data in database
        # Fall back to API call
        return self.lunarcrush_api.get_social_sentiment(symbol, days)
    
    def fetch_sentiment_data_from_timescale(
        self, 
        symbol: str = "SOL", 
        days: int = 30
    ) -> pd.DataFrame:
        """
        Sync wrapper for TimescaleDB social data fetching with improved API fallback
        
        This method provides a drop-in replacement for the legacy fetch_sentiment_data
        while using the new TimescaleDB backend and LunarCrush ID-based API calls.
        
        Args:
            symbol: Token symbol to fetch data for
            days: Number of days of historical data to fetch
            
        Returns:
            DataFrame containing social metrics compatible with existing feature engineering
        """
        logger.info(f"Fetching social data for {symbol} using TimescaleDB backend")
        
        try:
            # Use thread pool executor to run async functions to avoid event loop conflicts
            import concurrent.futures
            import threading
            
            def run_async_in_thread(coro):
                """Helper to run async function in a new thread with its own event loop"""
                def thread_runner():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        return loop.run_until_complete(coro)
                    finally:
                        loop.close()
                
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(thread_runner)
                    return future.result()
            
            # Get token data with LunarCrush fields
            token_data = run_async_in_thread(self._fetch_token_with_social_data(symbol))
            
            if not token_data:
                logger.warning(f"Token {symbol} not found in database")
                return self._create_empty_social_dataframe()
            
            logger.info(f"Found token: {token_data['symbol']} (ID: {token_data['token_id']}, LunarCrush ID: {token_data.get('lunarcrush_id', 'N/A')})")
            
            # Try to get existing social data from TimescaleDB first
            social_df = run_async_in_thread(self._fetch_social_data_from_db(token_data['token_id'], days))
            
            if not social_df.empty:
                logger.info(f"Using existing social data from TimescaleDB: {len(social_df)} records")
                return social_df
            
            # No existing data - fetch from API using LunarCrush ID if available
            logger.warning(f"No social data found in TimescaleDB for {symbol}, falling back to API")
            
            # Use LunarCrush ID if available, otherwise fall back to address and symbol
            from ..utils.social_data_fetcher import LunarCrushAPI
            api_fetcher = LunarCrushAPI()
            
            # Use LunarCrush ID if available for most accurate results
            if token_data.get('lunarcrush_id'):
                logger.info(f"Using LunarCrush ID {token_data['lunarcrush_id']} for API call")
                social_data = api_fetcher.get_asset_data(
                    symbol=token_data['symbol'],
                    address=token_data.get('address'),
                    lunarcrush_id=token_data['lunarcrush_id'],
                    interval='1d', 
                    days=min(days, 90)
                )
            else:
                logger.info(f"No LunarCrush ID available, using symbol and address for API call")
                social_data = api_fetcher.get_asset_data(
                    symbol=token_data['symbol'],
                    address=token_data.get('address'),
                    interval='1d', 
                    days=min(days, 90)
                )
            
            if social_data:
                # Convert to DataFrame
                social_df = pd.DataFrame(social_data)
                
                if not social_df.empty:
                    logger.info(f"Successfully fetched {len(social_df)} social data records from API")
                    return social_df
                else:
                    logger.warning(f"API returned empty data for {symbol}")
            else:
                logger.error(f"Failed to fetch social data from API for {symbol}")
            
        except Exception as e:
            logger.error(f"Error fetching social data from TimescaleDB: {e}")
        
        logger.info(f"Falling back to LunarCrush API for {symbol}")
        
        # Final fallback to direct API call (legacy behavior)
        try:
            from ..utils.social_data_fetcher import LunarCrushAPI
            api_fetcher = LunarCrushAPI()
            social_data = api_fetcher.get_asset_data(symbol=symbol, interval='1d', days=min(days, 90))
            
            if social_data:
                social_df = pd.DataFrame(social_data)
                if not social_df.empty:
                    logger.info(f"Successfully fetched {len(social_df)} records from LunarCrush API (final fallback)")
                    return social_df
        except Exception as e:
            logger.error(f"Final API fallback failed: {e}")
        
        # Return empty DataFrame with expected columns if all else fails
        logger.warning(f"All social data fetch attempts failed for {symbol}, returning empty DataFrame")
        return self._create_empty_social_dataframe()
    
    async def _fetch_token_with_social_data(self, symbol: str) -> Optional[Dict]:
        """Helper to fetch token data including LunarCrush fields"""
        db_manager = ProductionDBManager()
        try:
            await db_manager.initialize()
            return await db_manager.get_token_by_symbol(symbol)
        finally:
            await db_manager.close()
    
    async def _fetch_social_data_from_db(self, token_id: int, days: int) -> pd.DataFrame:
        """Helper to fetch existing social data from database"""
        db_manager = ProductionDBManager()
        try:
            await db_manager.initialize()
            start_time = datetime.now() - timedelta(days=days)
            social_data = await db_manager.get_social_data(token_id, start_time)
            
            if social_data:
                return pd.DataFrame(social_data)
            else:
                return pd.DataFrame()
        finally:
            await db_manager.close()
    
    async def _store_social_data_to_db(self, social_df: pd.DataFrame, token_id: int):
        """Helper to store social data to database"""
        # Implementation would convert DataFrame to MarketEventData objects
        # and store via db_manager.insert_market_events() 
        # For now, we'll skip this to avoid complexity
        pass
    
    def _create_empty_social_dataframe(self) -> pd.DataFrame:
        """Create empty DataFrame with expected social data columns"""
        return pd.DataFrame(columns=[
            'time', 'galaxy_score', 'alt_rank', 'social_volume_24h', 
            'social_dominance', 'interactions_24h', 'sentiment', 'close'
        ])
    
    def fetch_sentiment_data(
        self, 
        symbol: str = "SOL", 
        days: int = 30
    ) -> pd.DataFrame:
        """Fetch sentiment data from LunarCrush"""
        logger.info(f"Fetching sentiment data for {symbol}, days {days}")
        
        # Try to get data from database first
        try:
            from ..database.db import get_session, Token, SocialMetrics
            
            # Get session
            session = get_session()
            
            try:
                # Find token in database
                token = session.query(Token).filter(Token.symbol.ilike(symbol)).first()
                if not token:
                    logger.warning(f"Token {symbol} not found in database")
                    # Fall back to API call
                    return self.lunarcrush_api.get_social_sentiment(symbol, days)
                
                # Calculate date range
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days)
                
                logger.info(f"Querying social_metrics table for {symbol} from {start_date} to {end_date}")
                
                # Query social metrics from database
                social_records = session.query(SocialMetrics).filter(
                    SocialMetrics.token_id == token.token_id,
                    SocialMetrics.timestamp >= start_date,
                    SocialMetrics.timestamp <= end_date
                ).order_by(SocialMetrics.timestamp.desc()).all()
                
                if social_records and len(social_records) > 0:
                    logger.info(f"Found {len(social_records)} social records in database for {symbol}")
                    
                    # Convert to DataFrame
                    data = []
                    for record in social_records:
                        data.append({
                            'timestamp': record.timestamp,
                            'sentiment': record.sentiment,
                            'social_contributors_active': record.contributors_active,
                            'social_contributors_created': record.contributors_created,
                            'social_interactions': record.interactions,
                            'posts_active': record.posts_active,
                            'posts_created': record.posts_created,
                            'spam': record.spam,
                            'alt_rank': record.alt_rank,
                            'galaxy_score': record.galaxy_score,
                            'social_dominance': record.social_dominance,
                            'social_volume': record.interactions,  # Use interactions as proxy for volume
                            'market_dominance': record.market_dominance
                        })
                    
                    df = pd.DataFrame(data)
                    
                    # Set timestamp as index
                    if 'timestamp' in df.columns:
                        df.set_index('timestamp', inplace=True)
                    
                    # Sort by timestamp descending
                    df.sort_index(ascending=False, inplace=True)
                    
                    logger.info(f"Loaded social data from database for {symbol}, shape: {df.shape}")
                    return df
                else:
                    logger.warning(f"No social data found in database for {symbol}, falling back to API")
            
            finally:
                session.close()
        
        except Exception as e:
            logger.error(f"Error fetching social data from database: {e}")
            logger.info("Falling back to API call")
        
        # If we reach here, either there was an error or no data in database
        # Fall back to API call
        return self.lunarcrush_api.get_social_sentiment(symbol, days)
    
    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """ENHANCED: Calculate technical indicators using pandas_ta with caching metadata"""
        logger.info("Calculating technical indicators using pandas_ta")
        
        # ADD: Caching metadata for Redis optimization
        computation_start = time.time()
        
        # Ensure 'timestamp' column exists and set it as index
        if 'timestamp' not in df.columns:
            logger.error("Timestamp column missing, cannot calculate TA indicators requiring DatetimeIndex.")
            return df # Return original df if timestamp is missing
            
        # Make a copy to avoid modifying the original
        df = df.copy()
            
        # Convert timestamp to datetime if it's not already and set as index
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
        # Set timestamp as index for pandas_ta calculations that require DatetimeIndex
        df.set_index('timestamp', inplace=True)
        
        # IMPORTANT: Sort by index to ensure chronological order for TA calculations
        df.sort_index(inplace=True)
        
        # Make sure we have the required columns (adjust for pandas_ta needs)
        required_cols = ['open', 'high', 'low', 'close', 'volume'] # VWAP needs open
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"Missing required columns for pandas_ta indicators: {required_cols}")
            # Calculate what we can without full OHLCV
            if 'close' in df.columns:
                df.ta.rsi(append=True)
                df.ta.macd(append=True)
                df.ta.ema(length=12, append=True, col='ema_12')
                df.ta.ema(length=26, append=True, col='ema_26')
                df.ta.sma(length=7, append=True, col='sma_7')
                df.ta.sma(length=20, append=True, col='sma_20')
                df.ta.sma(length=50, append=True, col='sma_50')
                df.ta.roc(append=True)
                df.ta.willr(append=True)
                df.ta.cci(append=True)
            if 'volume' in df.columns:
                 df.ta.obv(append=True)
            # Cannot calculate ATR, BBands, Stoch, VWAP without full OHLCV
            logger.warning("Could not calculate ATR, BBands, Stoch, VWAP due to missing columns.")
        else:
            # Calculate all indicators using pandas_ta strategy
            custom_strategy = ta.Strategy(
                name="MLFeatures",
                description="Common features for ML",
                ta=[
                    # Momentum
                    {"kind": "rsi"},             # RSI
                    {"kind": "stoch"},           # Stochastic Oscillator (%K, %D)
                    {"kind": "cci"},             # Commodity Channel Index
                    {"kind": "roc"},             # Rate of Change
                    {"kind": "willr"},           # Williams %R
                    
                    # Trend / Momentum
                    {"kind": "macd"},            # MACD
                    {"kind": "adx"},             # Average Directional Index (ADX, DMP, DMN)
                    {"kind": "sma", "length": 7, "col_names": "sma_7"},
                    {"kind": "sma", "length": 20, "col_names": "sma_20"},
                    {"kind": "sma", "length": 50, "col_names": "sma_50"},
                    {"kind": "ema", "length": 12, "col_names": "ema_12"},
                    {"kind": "ema", "length": 26, "col_names": "ema_26"},
                    
                    # Volume
                    {"kind": "obv"},             # On Balance Volume
                    # VWAP needs DatetimeIndex - apply separately with explicit check
                    
                    # Volatility
                    {"kind": "atr"},             # Average True Range
                    {"kind": "bbands", "length": 20} # Bollinger Bands (BBL, BBM, BBU, BBB, BBP)
                ]
            )
            
            # Apply the strategy to the DataFrame
            df.ta.strategy(custom_strategy)
            
            # Add VWAP separately with explicit check for DatetimeIndex
            try:
                # Ensure we have a proper DatetimeIndex
                if isinstance(df.index, pd.DatetimeIndex):
                    df.ta.vwap(append=True)
                else:
                    logger.warning("Cannot calculate VWAP: index is not DatetimeIndex")
            except Exception as e:
                logger.warning(f"Error calculating VWAP: {e}")

            # Rename columns for clarity if needed (pandas_ta uses default names)
            # Example: df.rename(columns={'STOCHk_14_3_3': 'stoch_k', 'STOCHd_14_3_3': 'stoch_d'}, inplace=True)
            
            # Calculate Fibonacci features separately (existing custom logic)
            try:
                self._calculate_fibonacci_features(df)
            except Exception as e:
                logger.warning(f"Error calculating Fibonacci features: {e}")
                # Initialize Fibonacci columns with NaNs if calculation fails
                fib_retracement_levels = [0.236, 0.382, 0.5, 0.618, 0.786]
                fib_extension_levels = [1.272, 1.618, 2.618]
                for level in fib_retracement_levels:
                    df[f'fib_ret_{int(level*1000)}'] = np.nan
                for level in fib_extension_levels:
                    df[f'fib_ext_{int(level*1000)}'] = np.nan
                df['distance_to_fib_support'] = np.nan
                df['distance_to_fib_resistance'] = np.nan
                df['nearest_fib_support'] = np.nan
                df['nearest_fib_resistance'] = np.nan

        # Handle NaNs generated by indicators (especially at the start)
        original_cols = list(df.columns) # Keep track of original columns
        df = df.ffill() # Forward fill only
        
        # Ensure only numeric columns resulted from ta
        for col in df.columns:
            if col not in original_cols and not pd.api.types.is_numeric_dtype(df[col]):
                df.loc[:, col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            elif df[col].isnull().any(): # Fill any remaining NaNs in numeric cols
                 if pd.api.types.is_numeric_dtype(df[col]):
                      df.loc[:, col] = df[col].fillna(0)

        # Reset index so 'timestamp' is a column again for later processing stages
        df.reset_index(inplace=True)

        # ADD: Store metadata for cache validation and monitoring
        computation_time = time.time() - computation_start
        df.attrs['cache_metadata'] = {
            'computation_time_seconds': computation_time,
            'feature_count': len([col for col in df.columns if col not in ['open', 'high', 'low', 'close', 'volume']]),
            'data_quality_score': self._calculate_data_quality_score(df),
            'last_computation': datetime.utcnow().isoformat(),
            'cache_key_factors': {
                'rows': len(df),
                'timespan_hours': self._calculate_timespan_hours(df),
                'resolution': df.attrs.get('resolution', 'unknown')
            }
        }

        logger.info(f"Calculated indicators. DataFrame shape: {df.shape}, Columns: {list(df.columns)}")
        return df
    
    def _calculate_fibonacci_features(self, df: pd.DataFrame, window: int = 48) -> None:
        """
        Calculate Fibonacci retracement and extension levels as features
        
        Args:
            df: DataFrame with OHLCV data (must have DatetimeIndex)
            window: Lookback window to identify swing highs and lows
            
        Returns:
            None (modifies df in-place)
        """
        # Temporary columns storage
        temp_cols_to_drop = []
        try:
            # Helper function to safely check if a value is finite
            def safe_isfinite(x):
                try:
                    # Handle non-numeric types and NaN values
                    if x is None or pd.isna(x):
                        return False
                    # Convert to float and check if finite
                    return np.isfinite(float(x))
                except (ValueError, TypeError):
                    return False
            
            # Common Fibonacci ratios
            fib_retracement_levels = [0.236, 0.382, 0.5, 0.618, 0.786]
            fib_extension_levels = [1.272, 1.618, 2.618]
            
            # We need at least 'window' periods of data
            if len(df) < window:
                logger.warning(f"Not enough data for Fibonacci features (need at least {window} periods)")
                return
            
            # Initialize columns for features
            for level in fib_retracement_levels:
                df[f'fib_ret_{int(level*1000)}'] = np.nan
            
            for level in fib_extension_levels:
                df[f'fib_ext_{int(level*1000)}'] = np.nan
            
            # Add columns for distance to nearest levels
            df['distance_to_fib_support'] = np.nan
            df['distance_to_fib_resistance'] = np.nan
            df['nearest_fib_support'] = np.nan
            df['nearest_fib_resistance'] = np.nan
            
            # Helper function to detect unique swing points (first occurrence of extreme)
            def is_center_extreme(x, comp_func=max):
                center = len(x) // 2
                # Check if center is extreme AND it's the first occurrence of this value
                # This ensures we don't get duplicated swings at the same level
                is_extreme = x.iloc[center] == comp_func(x)
                return is_extreme
            
            # Find significant swing highs and lows
            try:
                # FIXED: Changed center=True to center=False to avoid look-ahead bias
                # Now only looks at past data when identifying swing points
                df['swing_high'] = df['high'].rolling(window=window, center=False).apply(
                    lambda x: x.iloc[-1] == x.max() if len(x) == window else False, raw=False
                ).astype(bool)
                temp_cols_to_drop.append('swing_high')
                
                df['swing_low'] = df['low'].rolling(window=window, center=False).apply(
                    lambda x: x.iloc[-1] == x.min() if len(x) == window else False, raw=False
                ).astype(bool)
                temp_cols_to_drop.append('swing_low')
            except Exception as e:
                 logger.warning(f"Error calculating swing points: {e}")
                 df['swing_high'] = False
                 df['swing_low'] = False
                 temp_cols_to_drop.extend(['swing_high', 'swing_low']) # Ensure they are marked for dropping
                 if len(df) > window * 2:
                     idx1, idx2 = window, len(df) - window
                     df.iloc[idx1, df.columns.get_loc('swing_high')] = True
                     df.iloc[idx2, df.columns.get_loc('swing_low')] = True
            
            # Forward fill swing points
            df['last_swing_high'] = df[df['swing_high']]['high']
            df['last_swing_low'] = df[df['swing_low']]['low']
            temp_cols_to_drop.extend(['last_swing_high', 'last_swing_low'])
            
            df['last_swing_high'] = df['last_swing_high'].ffill()
            df['last_swing_low'] = df['last_swing_low'].ffill()
            
            # Safety check: if no swing points detected
            if df['last_swing_high'].isna().all():
                logger.warning("No swing highs detected, using data max")
                df['last_swing_high'] = df['high'].max()
                
            if df['last_swing_low'].isna().all():
                logger.warning("No swing lows detected, using data min")
                df['last_swing_low'] = df['low'].min()
            
            # Get ATR (ensure the column name matches pandas_ta output, e.g., ATRr_14)
            atr_col_name = 'ATRr_14' # Adjust if pandas_ta uses a different name
            if atr_col_name not in df.columns:
                 logger.warning(f"ATR column '{atr_col_name}' not found for Fibonacci calculation. Using fallback.")
                 atr = df['close'].diff().abs().rolling(window=14).mean().fillna(method='ffill').fillna(0.001 * df['close'])
            else:
                 atr = df[atr_col_name].fillna(method='ffill').fillna(df['close'].diff().abs().mean())
            
            # Loop through points to calculate levels
            for i in range(window, len(df)):
                try:
                    # Get last swing high and low before current point
                    segment = df.iloc[max(0, i-window*2):i]
                    
                    if segment.empty:
                        continue
                        
                    # Ensure we have valid numeric data in key columns
                    for col in ['high', 'low', 'close']:
                        if not pd.api.types.is_numeric_dtype(df[col].dtype):
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    swing_highs = segment[segment['swing_high']]
                    swing_lows = segment[segment['swing_low']]
                    
                    if swing_highs.empty or swing_lows.empty:
                        # If no swing points in segment, use the last known values
                        last_swing_high = df.iloc[i]['last_swing_high']
                        last_swing_low = df.iloc[i]['last_swing_low']
                        
                        # If still no values, skip this point
                        if pd.isna(last_swing_high) or pd.isna(last_swing_low):
                            continue
                            
                        # Default to uptrend for direction
                        trend_direction = 'up'
                    else:
                        # Get most recent swing points
                        last_swing_high = swing_highs.iloc[-1]['high']
                        last_swing_low = swing_lows.iloc[-1]['low']
                        
                        # Determine if we're in an uptrend or downtrend
                        # For uptrend, swing low comes before swing high
                        # For downtrend, swing high comes before swing low
                        last_swing_high_idx = swing_highs.index[-1]
                        last_swing_low_idx = swing_lows.index[-1]
                        
                        trend_direction = 'up' if last_swing_high_idx > last_swing_low_idx else 'down'
                    
                    # Safety check: ensure swing points make sense
                    if last_swing_high <= last_swing_low:
                        # Adjust to ensure valid price range
                        eps = 0.001 * df.iloc[i]['close']  # Small epsilon based on current price
                        if trend_direction == 'up':
                            last_swing_high = last_swing_low + eps
                        else:
                            last_swing_low = last_swing_high - eps
                    
                    # Calculate price range with safety check
                    price_range = abs(last_swing_high - last_swing_low)
                    
                    # Sanity check on price range
                    if price_range == 0 or not np.isfinite(price_range) or last_swing_high is None or last_swing_low is None:
                        price_range = 0.001 * df.iloc[i]['close']  # Use small percentage of current price
                        # Also reset the high/low values if they're problematic
                        current_price = df.iloc[i]['close']
                        if not np.isfinite(last_swing_high) or last_swing_high is None:
                            last_swing_high = current_price * 1.01  # 1% above current price
                        if not np.isfinite(last_swing_low) or last_swing_low is None:
                            last_swing_low = current_price * 0.99   # 1% below current price
                    
                    # Calculate Fibonacci levels based on trend direction
                    if trend_direction == 'up':
                        # Uptrend - calculate retracements from low to high
                        for level in fib_retracement_levels:
                            df.loc[df.index[i], f'fib_ret_{int(level*1000)}'] = last_swing_high - (price_range * level)
                            
                        # Calculate extension levels
                        for level in fib_extension_levels:
                            df.loc[df.index[i], f'fib_ext_{int(level*1000)}'] = last_swing_high + (price_range * (level - 1))
                    else:
                        # Downtrend - calculate retracements from high to low
                        for level in fib_retracement_levels:
                            df.loc[df.index[i], f'fib_ret_{int(level*1000)}'] = last_swing_low + (price_range * level)
                            
                        # Calculate extension levels
                        for level in fib_extension_levels:
                            df.loc[df.index[i], f'fib_ext_{int(level*1000)}'] = last_swing_low - (price_range * (level - 1))
                    
                    # Calculate distance to nearest Fibonacci levels
                    current_price = df.iloc[i]['close']
                    # Ensure current price is a valid number
                    if not safe_isfinite(current_price):
                        current_price = df['close'].iloc[i-1] if i > 0 else 0
                        if not safe_isfinite(current_price):
                            # If we still don't have a valid price, skip this iteration
                            continue
                            
                    current_atr = atr[i] if i < len(atr) else atr.iloc[-1]
                    # Ensure ATR is valid
                    if not safe_isfinite(current_atr):
                        current_atr = 0.001 * current_price  # Use a small default value
                    
                    # Find nearest support (fib level below current price) and resistance (above)
                    fib_columns = [col for col in df.columns if col.startswith('fib_')]
                    fib_values = df.iloc[i][fib_columns].dropna()
                    
                    # Safety check for NaN
                    if len(fib_values) > 0:
                        # Filter out NaN or infinite values - add explicit conversion to float
                        try:
                            # Convert fib_values to numeric type explicitly before checking isfinite
                            fib_values = pd.to_numeric(fib_values, errors='coerce')
                                    # Now filter finite values using our safe function
                            fib_values = fib_values[fib_values.apply(safe_isfinite)]
                        except Exception as e:
                            logger.warning(f"Error converting Fibonacci values at index {i}: {e}")
                            continue
                        
                        if len(fib_values) > 0:
                            supports = fib_values[fib_values < current_price]
                            resistances = fib_values[fib_values > current_price]
                            
                            if len(supports) > 0:
                                nearest_support = max(supports)
                                df.loc[df.index[i], 'nearest_fib_support'] = nearest_support
                                
                                # Calculate distance normalized by ATR (more stable across instruments)
                                if current_atr > 0:
                                    # FIXED: Use log ratio for more stable distance metric
                                    support_distance = np.log(current_price / nearest_support) / np.log(1 + current_atr)
                                    # Clip to reasonable range
                                    support_distance = np.clip(support_distance, -5.0, 5.0)
                                    df.loc[df.index[i], 'distance_to_fib_support'] = support_distance
                                else:
                                    # Fallback to simple log ratio if ATR is zero
                                    support_distance = np.log(current_price / nearest_support)
                                    support_distance = np.clip(support_distance, -1.0, 1.0)
                                    df.loc[df.index[i], 'distance_to_fib_support'] = support_distance
                            
                            if len(resistances) > 0:
                                nearest_resistance = min(resistances)
                                df.loc[df.index[i], 'nearest_fib_resistance'] = nearest_resistance
                                
                                # Calculate distance normalized by ATR
                                if current_atr > 0:
                                    # FIXED: Use log ratio for more stable distance metric
                                    resistance_distance = np.log(nearest_resistance / current_price) / np.log(1 + current_atr)
                                    # Clip to reasonable range
                                    resistance_distance = np.clip(resistance_distance, -5.0, 5.0)
                                    df.loc[df.index[i], 'distance_to_fib_resistance'] = resistance_distance
                                else:
                                    # Fallback to simple log ratio if ATR is zero
                                    resistance_distance = np.log(nearest_resistance / current_price)
                                    resistance_distance = np.clip(resistance_distance, -1.0, 1.0)
                                    df.loc[df.index[i], 'distance_to_fib_resistance'] = resistance_distance
                except Exception as e:
                    logger.warning(f"Error calculating Fibonacci levels at index {i}: {e}")
                    continue
            
        finally:
            # Ensure temporary columns are always dropped
            cols_to_drop_now = [col for col in temp_cols_to_drop if col in df.columns]
            if cols_to_drop_now:
                df.drop(columns=cols_to_drop_now, inplace=True)
                logger.debug(f"Dropped temporary Fibonacci columns: {cols_to_drop_now}")
    
    def _calculate_data_quality_score(self, df: pd.DataFrame) -> float:
        """ADD: Data quality score for cache validation"""
        if df.empty:
            return 0.0
        
        # Calculate completeness (non-null ratio)
        total_cells = df.shape[0] * df.shape[1]
        null_cells = df.isnull().sum().sum()
        completeness = 1 - (null_cells / total_cells) if total_cells > 0 else 0
        
        # Calculate recency score (newer data = higher score)
        recency_score = 0.5  # Default if no timestamp
        if 'timestamp' in df.columns:
            try:
                latest_time = pd.to_datetime(df['timestamp']).max()
                age_hours = (datetime.utcnow() - latest_time).total_seconds() / 3600
                recency_score = max(0, 1 - (age_hours / 24))  # Decay over 24 hours
            except:
                pass
        
        return (completeness * 0.7) + (recency_score * 0.3)
    
    def _calculate_timespan_hours(self, df: pd.DataFrame) -> float:
        """ADD: Calculate data timespan for cache key generation"""
        if 'timestamp' not in df.columns or df.empty:
            return 0.0
        
        try:
            timestamps = pd.to_datetime(df['timestamp'])
            timespan = (timestamps.max() - timestamps.min()).total_seconds() / 3600
            return timespan
        except:
            return 0.0
    
    def add_fair_value_gaps(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add Fair Value Gap (FVG) detection and related metrics
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame with FVG indicators added
        """
        logger.info("Calculating Fair Value Gap (FVG) indicators")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Ensure we have required columns
        if not all(col in df.columns for col in ['open', 'high', 'low', 'close']):
            logger.warning("Missing required OHLC columns for FVG calculation")
            return df
        
        # Bullish FVG: Current candle's low > previous candle's high
        df['bullish_fvg'] = (df['low'] > df['high'].shift(1)).astype(float)
        
        # Bearish FVG: Current candle's high < previous candle's low
        df['bearish_fvg'] = (df['high'] < df['low'].shift(1)).astype(float)
        
        # FVG size (as percentage of price)
        df['bullish_fvg_size'] = np.where(
            df['bullish_fvg'] == 1, 
            (df['low'] - df['high'].shift(1)) / df['close'], 
            0
        )
        
        df['bearish_fvg_size'] = np.where(
            df['bearish_fvg'] == 1, 
            (df['low'].shift(1) - df['high']) / df['close'], 
            0
        )
        
        # Calculate nearest FVG in a lookback window (15 bars)
        window = 15
        
        # For each point, scan backward to find the closest FVG and its distance
        for i in range(window, len(df)):
            # Look for bullish FVGs in the past window bars
            bullish_indices = np.where(df['bullish_fvg'].values[i-window:i] == 1)[0]
            if len(bullish_indices) > 0:
                # Calculate distance to most recent bullish FVG
                closest_bullish = window - bullish_indices[-1]
                df.loc[df.index[i], 'dist_to_bullish_fvg'] = closest_bullish
                # Get the size of that FVG
                df.loc[df.index[i], 'closest_bullish_fvg_size'] = df['bullish_fvg_size'].values[i-window+bullish_indices[-1]]
            else:
                df.loc[df.index[i], 'dist_to_bullish_fvg'] = window + 1  # More than window away
                df.loc[df.index[i], 'closest_bullish_fvg_size'] = 0
            
            # Look for bearish FVGs in the past window bars
            bearish_indices = np.where(df['bearish_fvg'].values[i-window:i] == 1)[0]
            if len(bearish_indices) > 0:
                # Calculate distance to most recent bearish FVG
                closest_bearish = window - bearish_indices[-1]
                df.loc[df.index[i], 'dist_to_bearish_fvg'] = closest_bearish
                # Get the size of that FVG
                df.loc[df.index[i], 'closest_bearish_fvg_size'] = df['bearish_fvg_size'].values[i-window+bearish_indices[-1]]
            else:
                df.loc[df.index[i], 'dist_to_bearish_fvg'] = window + 1  # More than window away
                df.loc[df.index[i], 'closest_bearish_fvg_size'] = 0
        
        # Fill NaN values from the lookback with default values
        df['dist_to_bullish_fvg'] = df['dist_to_bullish_fvg'].fillna(window + 1)
        df['closest_bullish_fvg_size'] = df['closest_bullish_fvg_size'].fillna(0)
        df['dist_to_bearish_fvg'] = df['dist_to_bearish_fvg'].fillna(window + 1)
        df['closest_bearish_fvg_size'] = df['closest_bearish_fvg_size'].fillna(0)
        
        # Normalize distances (0 = FVG on current bar, 1 = FVG is window bars away or more)
        df['norm_dist_to_bullish_fvg'] = df['dist_to_bullish_fvg'] / (window + 1)
        df['norm_dist_to_bearish_fvg'] = df['dist_to_bearish_fvg'] / (window + 1)
        
        # High-value FVG feature: Are we near a FVG being filled?
        # Initialize price-to-fill columns with default values
        df['price_to_fill_bullish_fvg'] = 1.0
        df['price_to_fill_bearish_fvg'] = 1.0
        
        # Calculate price-to-fill for each row where the FVG distance is within range
        for i in range(window, len(df)):
            # Bullish FVG distance and price calculation
            if df['dist_to_bullish_fvg'].iloc[i] <= window:
                dist = int(df['dist_to_bullish_fvg'].iloc[i])
                if i - dist >= 0:  # Ensure the index is valid
                    fvg_high = df['high'].iloc[i - dist]
                    current_low = df['low'].iloc[i]
                    current_close = df['close'].iloc[i]
                    # FIXED: Calculate absolute distance to fill as a percentage
                    # For bullish FVG, we need price to go UP to fill the gap
                    df.loc[df.index[i], 'price_to_fill_bullish_fvg'] = abs(fvg_high - current_low) / current_close
            
            # Bearish FVG distance and price calculation
            if df['dist_to_bearish_fvg'].iloc[i] <= window:
                dist = int(df['dist_to_bearish_fvg'].iloc[i])
                if i - dist >= 0:  # Ensure the index is valid
                    fvg_low = df['low'].iloc[i - dist]
                    current_high = df['high'].iloc[i]
                    current_close = df['close'].iloc[i]
                    # FIXED: Calculate absolute distance to fill as a percentage
                    # For bearish FVG, we need price to go DOWN to fill the gap
                    df.loc[df.index[i], 'price_to_fill_bearish_fvg'] = abs(current_high - fvg_low) / current_close
        
        # Create FVG-based potential reversal signal
        df['fvg_reversal_signal'] = np.where(
            (df['bullish_fvg'] == 1) & (df['close'] < df['close'].shift(1)),
            1,  # Bullish FVG but price closed down - potential reversal up
            np.where(
                (df['bearish_fvg'] == 1) & (df['close'] > df['close'].shift(1)),
                -1,  # Bearish FVG but price closed up - potential reversal down
                0
            )
        )
        
        logger.info(f"Added {sum('fvg' in col for col in df.columns)} FVG-related features")
        return df
    
    def add_volatility_of_volatility(self, df: pd.DataFrame, window: int = 14, vov_window: int = 7) -> pd.DataFrame:
        """
        Add Volatility-of-Volatility (VoV) features
        
        Args:
            df: DataFrame with OHLCV data
            window: Window length for realized volatility calculation
            vov_window: Window length for VoV calculation
            
        Returns:
            DataFrame with VoV indicators added
        """
        logger.info("Calculating Volatility-of-Volatility (VoV) indicators")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Ensure we have required columns
        if 'close' not in df.columns:
            logger.warning("Missing 'close' column for VoV calculation")
            return df
        
        # Step 1: Calculate log returns
        df['log_return'] = np.log(df['close'] / df['close'].shift(1))
        
        # Step 2: Compute realized volatility using standard deviation of log returns
        df['realized_vol'] = df['log_return'].rolling(window=window).std() * np.sqrt(252)  # Annualized
        
        # Step 3: Calculate volatility of volatility as the standard deviation of the realized volatility
        df['vov'] = df['realized_vol'].rolling(window=vov_window).std()
        
        # Step 4: Scale VoV by realized volatility to get relative measure
        df['vov_relative'] = df['vov'] / df['realized_vol'].replace(0, np.nan)
        
        # Step 5: Calculate VoV regime indicators (is VoV high/low relative to recent history)
        df['vov_zscore'] = (df['vov'] - df['vov'].rolling(window=window*2).mean()) / df['vov'].rolling(window=window*2).std()
        
        # Step 6: Create regime indicator (1 = high vol-of-vol regime, 0 = normal, -1 = low vol-of-vol)
        df['vov_regime'] = np.where(df['vov_zscore'] > 1.5, 1, np.where(df['vov_zscore'] < -1.5, -1, 0))
        
        # Handle NaN values
        vov_cols = ['realized_vol', 'vov', 'vov_relative', 'vov_zscore', 'vov_regime']
        for col in vov_cols:
            df[col] = df[col].fillna(method='ffill').fillna(0)
        
        # Clean up temporary columns
        df.drop(columns=['log_return'], inplace=True, errors='ignore')
        
        logger.info(f"Added {len(vov_cols)} VoV-related features")
        return df
    
    def add_time_cyclical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add cyclical time features (hour of day, day of week, month of year)
        using sin/cos transformations to preserve cyclical nature
        
        Args:
            df: DataFrame with timestamp data
            
        Returns:
            DataFrame with cyclical time features added
        """
        logger.info("Calculating cyclical time features")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Ensure we have datetime timestamps
        if 'timestamp' not in df.columns:
            logger.warning("Missing 'timestamp' column for cyclical time features")
            return df
            
        # Convert timestamp to datetime if needed
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Extract time components
        df['hour'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.dayofweek  # Monday=0, Sunday=6
        df['day_of_month'] = df['timestamp'].dt.day
        df['month'] = df['timestamp'].dt.month
        
        # Convert hour to cyclical features (24-hour cycle)
        df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
        
        # Convert day of week to cyclical features (7-day cycle)
        df['day_of_week_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
        df['day_of_week_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
        
        # Convert month to cyclical features (12-month cycle)
        df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
        df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
        
        # Special times-of-day indicators
        # Asian session (UTC 0-8)
        df['asian_session'] = ((df['hour'] >= 0) & (df['hour'] < 8)).astype(int)
        # European session (UTC 8-16)
        df['european_session'] = ((df['hour'] >= 8) & (df['hour'] < 16)).astype(int)
        # American session (UTC 14-22, overlap with European)
        df['american_session'] = ((df['hour'] >= 14) & (df['hour'] < 22)).astype(int)
        # Overnight (UTC 22-0)
        df['overnight_session'] = ((df['hour'] >= 22) | (df['hour'] < 0)).astype(int)
        
        # Weekend indicator (Saturday=5, Sunday=6)
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
        
        # Special periods known for crypto volatility
        # Options expiry week - last week of month
        df['options_expiry_week'] = (df['day_of_month'] >= 22).astype(int)
        # First week of month - often shows different pattern
        df['first_week_of_month'] = (df['day_of_month'] <= 7).astype(int)
        
        # Drop intermediate columns
        df.drop(columns=['hour', 'day_of_week', 'day_of_month', 'month'], inplace=True, errors='ignore')
        
        # Count all the time-related features we've added
        time_cols = [col for col in df.columns if any(x in col for x in ['_sin', '_cos', '_session', 'is_weekend', 'week_of'])]
        logger.info(f"Added {len(time_cols)} cyclical time features")
        
        return df
    
    def add_money_flow_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add Chaikin Money Flow (CMF) and Price-Volume Trend (PVT) indicators
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame with money flow indicators added
        """
        logger.info("Calculating money flow indicators (CMF and PVT)")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Ensure we have required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"Missing required columns {required_cols} for money flow calculation")
            return df
            
        # 1. Calculate Money Flow Multiplier (MFM)
        # MFM = ((Close - Low) - (High - Close)) / (High - Low)
        # This measures the buying/selling pressure during a period
        
        # Avoid division by zero when high=low (no price movement in period)
        price_range = df['high'] - df['low']
        price_range = price_range.replace(0, np.nan)  # Replace zeros with NaN
        
        # Calculate the money flow multiplier
        df['mf_multiplier'] = ((df['close'] - df['low']) - (df['high'] - df['close'])) / price_range
        
        # Handle NaN values in multiplier (no price range)
        df['mf_multiplier'] = df['mf_multiplier'].fillna(0)
        
        # 2. Calculate Money Flow Volume (MFV)
        df['mf_volume'] = df['mf_multiplier'] * df['volume']
        
        # 3. Calculate Chaikin Money Flow (CMF)
        # CMF is the 21-period sum of Money Flow Volume divided by the 21-period sum of volume
        for period in [14, 21]:
            sum_mf_volume = df['mf_volume'].rolling(window=period).sum()
            sum_volume = df['volume'].rolling(window=period).sum()
            df[f'cmf_{period}'] = sum_mf_volume / sum_volume
        
        # 4. Calculate Price-Volume Trend (PVT)
        # PVT adds/subtracts a portion of the volume based on price movement relative to prior period
        df['price_change_pct'] = df['close'].pct_change()
        df['pvt_change'] = df['price_change_pct'] * df['volume']  # Volume * percent price change
        df['pvt'] = df['pvt_change'].cumsum()  # Cumulative sum
        
        # 5. Calculate additional money flow indicators
        
        # A. PVT Oscillator (14-period EMA of PVT)
        df['pvt_ema'] = df['pvt'].ewm(span=14, adjust=False).mean()
        df['pvt_oscillator'] = 100 * (df['pvt'] - df['pvt_ema']) / df['pvt_ema']
        
        # B. CMF Rate of Change (acceleration of money flow)
        df['cmf_21_roc'] = df['cmf_21'].pct_change(periods=3)
        
        # C. CMF Divergence (price increase with decreasing CMF = bearish)
        df['price_up'] = (df['close'] > df['close'].shift(1)).astype(int)
        df['cmf_up'] = (df['cmf_21'] > df['cmf_21'].shift(1)).astype(int)
        df['cmf_divergence'] = np.where(
            (df['price_up'] == 1) & (df['cmf_up'] == 0), 
            -1,  # Bearish divergence (price up, CMF down)
            np.where(
                (df['price_up'] == 0) & (df['cmf_up'] == 1),
                1,   # Bullish divergence (price down, CMF up)
                0    # No divergence
            )
        )
        
        # D. Create a CMF signal based on zero crossovers
        df['cmf_signal'] = np.where(
            (df['cmf_21'].shift(1) < 0) & (df['cmf_21'] > 0),
            1,  # Bullish zero line crossover
            np.where(
                (df['cmf_21'].shift(1) > 0) & (df['cmf_21'] < 0),
                -1,  # Bearish zero line crossover
                0    # No crossover
            )
        )
        
        # Drop intermediate calculation columns
        temp_cols = ['mf_multiplier', 'mf_volume', 'price_change_pct', 'pvt_change', 'price_up', 'cmf_up']
        df.drop(columns=temp_cols, inplace=True, errors='ignore')
        
        # Handle NaN values
        money_flow_cols = [col for col in df.columns if col not in required_cols and col not in temp_cols]
        for col in money_flow_cols:
            df[col] = df[col].fillna(0)
            
            # Clip extreme values to prevent outliers
            if 'pvt_oscillator' in col or 'cmf_21_roc' in col:
                df[col] = df[col].clip(-10, 10)
        
        logger.info(f"Added {len(money_flow_cols)} money flow features")
        return df
    
    def add_realized_volatility(self, df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
        """
        Add range-based realized volatility metrics (Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang)
        These provide more efficient volatility estimates using OHLC data rather than just close prices
        
        Args:
            df: DataFrame with OHLCV data
            window: Lookback period for volatility calculation
            
        Returns:
            DataFrame with realized volatility indicators added
        """
        logger.info(f"Calculating range-based realized volatility metrics with {window}-period window")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Ensure we have required columns
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"Missing required columns {required_cols} for realized volatility calculation")
            return df
        
        # Constants for annualization and scaling
        sqrt_252 = np.sqrt(252)  # Annualization factor (trading days in a year)
        
        # 1. Calculate Parkinson volatility estimator
        # Parkinson volatility uses high-low range and is more efficient than close-to-close
        # Formula: σ² = 1/(4*ln(2)) * Σ(ln(high/low))²
        hlr = np.log(df['high'] / df['low'])
        df['parkinson_vol'] = hlr.rolling(window=window).apply(
            lambda x: np.sqrt(np.sum(x**2) / (4 * np.log(2) * window)) * sqrt_252, 
            raw=True
        )
        
        # 2. Calculate Garman-Klass volatility estimator
        # Garman-Klass incorporates open and close prices for better efficiency
        # Formula: σ² = 0.5*ln(high/low)² - (2*ln(2)-1)*ln(close/open)²
        
        # Calculate log changes
        co = np.log(df['close'] / df['open'])**2
        
        # Coefficient for the second term
        gk_coef = 2 * np.log(2) - 1
        
        # Calculate Garman-Klass volatility term-by-term
        df['gk_term'] = 0.5 * hlr**2 - gk_coef * co
        
        # Calculate rolling volatility
        df['garman_klass_vol'] = df['gk_term'].rolling(window=window).apply(
            lambda x: np.sqrt(np.sum(x) / window) * sqrt_252,
            raw=True
        )
        
        # 3. Calculate Rogers-Satchell volatility estimator
        # Rogers-Satchell accounts for drift in the price series
        # Formula: σ² = ln(high/close)*ln(high/open) + ln(low/close)*ln(low/open)
        
        ho = np.log(df['high'] / df['open'])
        hc = np.log(df['high'] / df['close'])
        lo = np.log(df['low'] / df['open'])
        lc = np.log(df['low'] / df['close'])
        
        df['rs_term'] = hc*ho + lc*lo
        
        df['rogers_satchell_vol'] = df['rs_term'].rolling(window=window).apply(
            lambda x: np.sqrt(np.sum(x) / window) * sqrt_252,
            raw=True
        )
        
        # 4. Calculate Yang-Zhang volatility estimator
        # Yang-Zhang combines overnight volatility and intraday volatility
        # It's the most efficient estimator, robust to both opening jumps and drift
        
        # Calculate overnight volatility (close to next open)
        co_shifted = np.log(df['open'] / df['close'].shift(1))**2
        
        # Calculate overnight variance estimator
        df['overnight_var'] = co_shifted.rolling(window=window).apply(
            lambda x: np.sum(x) / window,
            raw=True
        )
        
        # Calculate open-close variance estimator
        df['open_close_var'] = co.rolling(window=window).apply(
            lambda x: np.sum(x) / window,
            raw=True
        )
        
        # Calculate Rogers-Satchell variance estimator
        df['rs_var'] = df['rs_term'].rolling(window=window).apply(
            lambda x: np.sum(x) / window,
            raw=True
        )
        
        # k parameter for optimal weighting (usually 0.34 for daily data)
        k = 0.34
        
        # Calculate Yang-Zhang volatility
        df['yang_zhang_vol'] = np.sqrt(
            df['overnight_var'] + k * df['open_close_var'] + (1 - k) * df['rs_var']
        ) * sqrt_252
        
        # 5. Calculate volatility ratios (useful for regime detection)
        
        # 5.1 Ratio of range-based vol to standard vol (efficiency measure)
        # First calculate close-to-close volatility
        df['close_to_close_vol'] = np.log(df['close'] / df['close'].shift(1)).rolling(window=window).std() * sqrt_252
        
        # Calculate ratio
        df['vol_efficiency'] = df['yang_zhang_vol'] / df['close_to_close_vol']
        
        # 5.2 Ratio to ATR (normalized volatility)
        atr_col = 'ATRr_14' if 'ATRr_14' in df.columns else 'atr'
        if atr_col in df.columns:
            # FIXED: Add safeguard to prevent division by very small ATR values
            min_atr = 0.001  # Minimum ATR threshold
            safe_atr = np.maximum(df[atr_col], min_atr)
            # Use log ratio for more stable values
            df['vol_to_atr'] = np.log1p(df['yang_zhang_vol']) - np.log1p(safe_atr)
        
        # Clean up intermediate calculation columns
        temp_cols = ['gk_term', 'rs_term', 'overnight_var', 'open_close_var', 'rs_var']
        df.drop(columns=temp_cols, inplace=True, errors='ignore')
        
        # Handle NaN values
        vol_cols = ['parkinson_vol', 'garman_klass_vol', 'rogers_satchell_vol', 
                    'yang_zhang_vol', 'close_to_close_vol', 'vol_efficiency']
        if 'vol_to_atr' in df.columns:
            vol_cols.append('vol_to_atr')
            
        for col in vol_cols:
            # First forward fill
            df[col] = df[col].fillna(method='ffill')
            
            # Then fill remaining NaNs with a reasonable default
            if 'efficiency' in col or 'to_atr' in col:
                df[col] = df[col].fillna(1.0)  # Default ratio is 1.0
            else:
                # For actual volatility measures, use mean of non-NaN values or a small default
                non_nan_mean = df[col].mean()
                df[col] = df[col].fillna(non_nan_mean if np.isfinite(non_nan_mean) else 0.01)
            
            # Clip extreme values
            df[col] = df[col].clip(0.0001, 10.0)  # Avoid zero or extreme values
        
        logger.info(f"Added {len(vol_cols)} realized volatility features")
        return df
    
    def add_adaptive_moving_averages(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add adaptive moving averages (KAMA, HMA) and trend slope indicators
        which adapt more quickly to price changes than standard moving averages
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame with adaptive MA indicators added
        """
        logger.info("Calculating adaptive moving averages and trend slope indicators")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Ensure we have required columns
        if 'close' not in df.columns:
            logger.warning("Missing 'close' column for adaptive MA calculation")
            return df
            
        # Make sure pandas_ta is imported
        try:
            import pandas_ta as ta
        except ImportError:
            logger.error("pandas_ta package is required for adaptive MAs but not installed")
            return df
        
        # 1. Calculate Kaufman's Adaptive Moving Average (KAMA)
        # KAMA adapts to market volatility and trends, moving fast in trending markets and slow in ranging markets
        for length in [10, 20, 50]:
            # Calculate KAMA using pandas_ta
            try:
                kama = ta.kama(df['close'], length=length)
                df[f'kama_{length}'] = kama
            except Exception as e:
                logger.warning(f"Error calculating KAMA ({length}): {e}")
                # Use EMA as fallback
                df[f'kama_{length}'] = df['close'].ewm(span=length, adjust=False).mean()
        
        # 2. Calculate Hull Moving Average (HMA)
        # HMA reduces lag and improves smoothing compared to simple moving averages
        for length in [9, 21, 55]:
            try:
                hma = ta.hma(df['close'], length=length)
                df[f'hma_{length}'] = hma
            except Exception as e:
                logger.warning(f"Error calculating HMA ({length}): {e}")
                # Use WMA as fallback
                df[f'hma_{length}'] = df['close'].rolling(window=length, min_periods=1).mean()
        
        # 3. Calculate Moving Average slopes (for trend strength)
        # Slope measures how fast the MA is changing, indicating trend strength
        
        # Define slope function with safety checks
        def safe_slope(series, periods=5):
            # Convert to numpy array for speed
            arr = series.values
            # Initialize slope array (same size as input)
            slopes = np.zeros_like(arr)
            # Calculate slopes starting from index 'periods'
            for i in range(periods, len(arr)):
                # Get the slice of data for this window
                window = arr[i-periods:i+1]
                # Only calculate if we have enough non-NaN values
                if not np.isnan(window).any():
                    # Create X array (0, 1, 2, 3...)
                    x = np.arange(len(window))
                    # Calculate slope using least squares formula
                    # slope = (n*sum(x*y) - sum(x)*sum(y)) / (n*sum(x^2) - sum(x)^2)
                    n = len(window)
                    sum_x = np.sum(x)
                    sum_y = np.sum(window)
                    sum_xy = np.sum(x * window)
                    sum_xx = np.sum(x**2)
                    # Calculate slope with safety check for division by zero
                    denominator = n*sum_xx - sum_x**2
                    if denominator != 0:
                        slopes[i] = (n*sum_xy - sum_x*sum_y) / denominator
            return slopes
            
        # Calculate slopes for each of the adaptive MAs
        for ma_type in ['kama', 'hma']:
            for length in [9, 21, 55] if ma_type == 'hma' else [10, 20, 50]:
                ma_col = f'{ma_type}_{length}'
                if ma_col in df.columns:
                    # Calculate normalized slope (as percentage of price)
                    slope = safe_slope(df[ma_col], periods=5)
                    df[f'{ma_col}_slope'] = slope / df[ma_col] * 100  # Slope as percentage of MA value
        
        # 4. Calculate adaptive MA crossovers (trend change signals)
        # Fast MA crossing above slow MA is bullish, below is bearish
        
        # Check all combinations of MAs for crossovers
        ma_cols = [col for col in df.columns if col.startswith('kama_') or col.startswith('hma_') and not col.endswith('_slope')]
        
        # Sort MAs by length (ascending)
        ma_cols = sorted(ma_cols, key=lambda x: int(x.split('_')[1]))
        
        # Calculate crossovers for adjacent MA pairs
        for i in range(len(ma_cols) - 1):
            fast_ma = ma_cols[i]
            slow_ma = ma_cols[i+1]
            
            # Current crossover state (1=fast above slow, -1=fast below slow)
            df[f'{fast_ma}_over_{slow_ma}'] = np.where(
                df[fast_ma] > df[slow_ma], 1, -1
            )
            
            # Crossover signal (when the state changes) - only occurs at the crossing point
            df[f'{fast_ma}_{slow_ma}_cross'] = np.where(
                (df[f'{fast_ma}_over_{slow_ma}'] == 1) & 
                (df[f'{fast_ma}_over_{slow_ma}'].shift(1) == -1),
                1,  # Bullish cross (fast crosses above slow)
                np.where(
                    (df[f'{fast_ma}_over_{slow_ma}'] == -1) & 
                    (df[f'{fast_ma}_over_{slow_ma}'].shift(1) == 1),
                    -1,  # Bearish cross (fast crosses below slow)
                    0    # No cross
                )
            )
            
        # 5. Calculate price position relative to MAs
        # Position of price above/below multiple MAs indicates trend strength
        
        # Count MAs price is above
        ma_count_cols = []
        for ma_col in ma_cols:
            ma_count_cols.append(f'price_above_{ma_col}')
            df[f'price_above_{ma_col}'] = np.where(df['close'] > df[ma_col], 1, 0)
            
        # Sum to get total count
        if ma_count_cols:
            df['mas_above_count'] = df[ma_count_cols].sum(axis=1)
            
            # Normalize to percentage of total MAs
            df['price_relative_position'] = df['mas_above_count'] / len(ma_cols)
        
        # 6. Clean up columns and handle NaNs
        
        # Clean up intermediate columns
        drop_cols = [col for col in df.columns if col.startswith('price_above_')]
        if 'mas_above_count' in df.columns:
            drop_cols.append('mas_above_count')
        df.drop(columns=drop_cols, inplace=True, errors='ignore')
        
        # Get list of all added columns
        adaptive_ma_cols = [col for col in df.columns if any(x in col for x in 
                            ['kama_', 'hma_', '_cross', '_over_', 'price_relative_position'])]
        
        # Fill NaN values
        for col in adaptive_ma_cols:
            df[col] = df[col].fillna(method='ffill').fillna(0)
            
            # Clip slope values to reasonable range
            if col.endswith('_slope'):
                df[col] = df[col].clip(-10, 10)
        
        logger.info(f"Added {len(adaptive_ma_cols)} adaptive MA features")
        return df
    
    def add_candlestick_patterns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add candlestick pattern features to the dataframe using custom implementations
        instead of TA-Lib (avoiding TA-Lib compatibility issues)
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame with added candlestick pattern features
        """
        logger.info("Adding candlestick pattern features (custom implementation)")
        
        # Check if dataframe is empty or missing OHLCV columns
        if df.empty:
            logger.warning("Empty dataframe provided for candlestick pattern calculation")
            return df
            
        # Check for required columns
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"Missing required columns for candlestick patterns: {required_cols}")
            return df
        
        # Create a copy to avoid modifying the original
        result = df.copy()
        
        try:
            # Calculate basic candlestick properties
            result['candle_body'] = abs(result['close'] - result['open'])
            result['candle_wick_upper'] = result['high'] - np.maximum(result['open'], result['close'])
            result['candle_wick_lower'] = np.minimum(result['open'], result['close']) - result['low']
            
            # FIXED: Ensure non-negative values and handle division by zero
            candle_range = result['high'] - result['low']
            # Add small epsilon to prevent division by zero
            safe_range = np.maximum(candle_range, 0.0001)
            result['candle_ratio'] = result['candle_body'] / safe_range
            
            # Encode the direction
            result['candle_direction'] = (result['close'] > result['open']).astype(int) * 2 - 1  # 1 for bullish, -1 for bearish
            
            # Size relative to recent candles (normalized)
            lookback = 5
            result['candle_rel_size'] = result['candle_body'] / result['candle_body'].rolling(lookback).mean()
            result['candle_rel_size'] = result['candle_rel_size'].fillna(1.0)
            
            # Relative position of close within recent range
            result['close_rel_position'] = (result['close'] - result['low'].rolling(lookback).min()) / \
                                          (result['high'].rolling(lookback).max() - result['low'].rolling(lookback).min())
            result['close_rel_position'] = result['close_rel_position'].fillna(0.5)
            
            # Implementation of common candlestick patterns
            
            # 1. Doji pattern (very small body compared to range)
            body_to_range_ratio = result['candle_body'] / (result['high'] - result['low'])
            result['doji'] = (body_to_range_ratio < 0.1).astype(int) * result['candle_direction']
            
            # 2. Hammer (small body at top, long lower wick, little/no upper wick)
            result['hammer'] = (
                (result['candle_body'] <= 0.3 * (result['high'] - result['low'])) &  # Small body
                (result['candle_wick_lower'] >= 2 * result['candle_body']) &  # Long lower wick
                (result['candle_wick_upper'] <= 0.1 * result['candle_wick_lower'])  # Small/no upper wick
            ).astype(int) * result['candle_direction']
            
            # 3. Inverted Hammer (small body at bottom, long upper wick, little/no lower wick)
            result['inverted_hammer'] = (
                (result['candle_body'] <= 0.3 * (result['high'] - result['low'])) &  # Small body
                (result['candle_wick_upper'] >= 2 * result['candle_body']) &  # Long upper wick
                (result['candle_wick_lower'] <= 0.1 * result['candle_wick_upper'])  # Small/no lower wick
            ).astype(int) * result['candle_direction']
            
            # 4. Engulfing pattern (current candle completely engulfs previous candle)
            bullish_engulfing = (
                (result['candle_direction'] == 1) &  # Current candle is bullish
                (result['candle_direction'].shift(1) == -1) &  # Previous candle is bearish
                (result['open'] <= result['close'].shift(1)) &  # Current open below previous close
                (result['close'] >= result['open'].shift(1))  # Current close above previous open
            )
            
            bearish_engulfing = (
                (result['candle_direction'] == -1) &  # Current candle is bearish
                (result['candle_direction'].shift(1) == 1) &  # Previous candle is bullish
                (result['open'] >= result['close'].shift(1)) &  # Current open above previous close
                (result['close'] <= result['open'].shift(1))  # Current close below previous open
            )
            
            result['engulfing'] = bullish_engulfing.astype(int) - bearish_engulfing.astype(int)
            
            # 5. Marubozu (strong trend candle - all body, minimal wicks)
            result['marubozu'] = (
                (result['candle_body'] >= 0.9 * (result['high'] - result['low']))  # Body is at least 90% of range
            ).astype(int) * result['candle_direction']
            
            # 6. Dragonfly Doji (body at top, long lower wick, almost no upper wick)
            result['dragonfly_doji'] = (
                (result['candle_body'] <= 0.1 * (result['high'] - result['low'])) &  # Small body
                (result['candle_wick_lower'] >= 3 * result['candle_body']) &  # Long lower wick
                (result['candle_wick_upper'] <= 0.05 * (result['high'] - result['low']))  # Very small upper wick
            ).astype(int)
            
            # 7. Gravestone Doji (body at bottom, long upper wick, almost no lower wick)
            result['gravestone_doji'] = (
                (result['candle_body'] <= 0.1 * (result['high'] - result['low'])) &  # Small body
                (result['candle_wick_upper'] >= 3 * result['candle_body']) &  # Long upper wick
                (result['candle_wick_lower'] <= 0.05 * (result['high'] - result['low']))  # Very small lower wick
            ).astype(int)
            
            logger.info("Added candlestick pattern features using custom implementation")
        except Exception as e:
            logger.error(f"Error calculating candlestick patterns: {e}")
            # Fall back to basic candlestick metrics without pattern recognition
            result['candle_body'] = abs(result['close'] - result['open'])
            result['candle_wick_upper'] = result['high'] - np.maximum(result['open'], result['close'])
            result['candle_wick_lower'] = np.minimum(result['open'], result['close']) - result['low']
            result['candle_ratio'] = result['candle_body'] / (result['high'] - result['low']).replace(0, np.nan)
            result['candle_ratio'] = result['candle_ratio'].fillna(0)
            result['candle_direction'] = (result['close'] > result['open']).astype(int) * 2 - 1
        
        return result
    
    def add_multi_timeframe_features(self, df: pd.DataFrame, original_resolution: str, 
                                     include_timeframes: list = None) -> pd.DataFrame:
        """
        Generate features from multiple timeframes and combine them with the original data.
        This is particularly useful for trading algorithms that need to consider trends
        across different time horizons.
        
        Args:
            df: DataFrame with OHLCV data at the original resolution
            original_resolution: The timeframe of the input data (e.g., '1m', '5m', '1h')
            include_timeframes: List of higher timeframes to include (e.g., ['1h', '4h', '1d'])
                                If None, will automatically select appropriate higher timeframes
                                
        Returns:
            DataFrame with additional multi-timeframe features
        """
        logger.info(f"Adding multi-timeframe features based on {original_resolution} data")
        
        # Check if dataframe is empty or missing OHLCV columns
        if df.empty:
            logger.warning("Empty dataframe provided for multi-timeframe feature generation")
            return df
            
        # Check for required columns
        required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"Missing required columns for multi-timeframe features: {required_cols}")
            return df
            
        # Create a copy to avoid modifying the original
        result = df.copy()
        
        # Ensure timestamp is a datetime
        if not pd.api.types.is_datetime64_any_dtype(result['timestamp']):
            result['timestamp'] = pd.to_datetime(result['timestamp'])
        
        # Set timestamp as index for resampling
        result = result.set_index('timestamp')
        
        # Define available timeframes in minutes for easy comparison
        timeframe_minutes = {
            '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480,
            '12h': 720, '1d': 1440, '3d': 4320, '1w': 10080
        }
        
        # Get original timeframe in minutes
        orig_minutes = timeframe_minutes.get(original_resolution.lower(), 5)
        
        # Automatically determine appropriate higher timeframes if not specified
        if include_timeframes is None:
            # Choose timeframes based on original resolution
            if orig_minutes < 60:  # Less than 1h data
                include_timeframes = ['1h', '4h', '1d']
            elif orig_minutes < 240:  # Less than 4h data
                include_timeframes = ['4h', '1d', '1w']
            else:  # 4h or higher
                include_timeframes = ['1d', '1w']
        
        # Filter to include only timeframes higher than original
        valid_timeframes = []
        for tf in include_timeframes:
            tf_minutes = timeframe_minutes.get(tf.lower(), 0)
            if tf_minutes > orig_minutes:
                valid_timeframes.append(tf)
            else:
                logger.warning(f"Skipping {tf} timeframe as it's not higher than original {original_resolution}")
        
        # Create multi-timeframe features
        for tf in valid_timeframes:
            logger.info(f"Generating {tf} timeframe features")
            
            # Convert to pandas offset string for resampling
            if 'm' in tf.lower():
                resample_rule = tf.lower().replace('m', 'min')
            elif 'h' in tf.lower():
                resample_rule = tf.lower().replace('h', 'H')
            elif 'd' in tf.lower():
                resample_rule = tf.lower().replace('d', 'D')
            elif 'w' in tf.lower():
                resample_rule = tf.lower().replace('w', 'W')
            else:
                logger.warning(f"Unsupported timeframe format: {tf}, skipping")
                continue
            
            # Resample OHLCV data to higher timeframe
            resampled = result.resample(resample_rule).agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            })
            
            # Calculate key indicators on the higher timeframe
            # 1. Trend indicators (SMA, EMA)
            resampled[f'{tf}_sma20'] = resampled['close'].rolling(window=20).mean()
            resampled[f'{tf}_sma50'] = resampled['close'].rolling(window=50).mean()
            resampled[f'{tf}_ema12'] = resampled['close'].ewm(span=12, adjust=False).mean()
            resampled[f'{tf}_ema26'] = resampled['close'].ewm(span=26, adjust=False).mean()
            
            # 2. Price momentum indicators (RSI)
            try:
                resampled[f'{tf}_rsi'] = ta.momentum.rsi(resampled['close'], window=14)
            except Exception as e:
                logger.warning(f"Error calculating RSI for {tf} timeframe: {e}")
                resampled[f'{tf}_rsi'] = np.nan
            
            # 3. Volatility indicators (Bollinger Bands)
            try:
                # Calculate Bollinger Bands using pandas_ta if available, otherwise use manual calculation
                bb_window = 20
                std_dev = 2
                
                # Manual calculation as fallback
                sma = resampled['close'].rolling(window=bb_window).mean()
                std = resampled['close'].rolling(window=bb_window).std()
                resampled[f'{tf}_bb_upper'] = sma + (std * std_dev)
                resampled[f'{tf}_bb_lower'] = sma - (std * std_dev)
                resampled[f'{tf}_bb_width'] = (resampled[f'{tf}_bb_upper'] - resampled[f'{tf}_bb_lower']) / sma
            except Exception as e:
                logger.warning(f"Error calculating Bollinger Bands for {tf} timeframe: {e}")
            
            # 4. Additional trend-strength indicators
            # Trend direction and strength
            resampled[f'{tf}_trend_pct'] = resampled['close'].pct_change(periods=3) * 100
            
            # 5. Calculate trend alignment features (original timeframe vs higher timeframe)
            # Forward fill the resampled dataframe to match the original index
            filled_resampled = resampled.reindex(result.index, method='ffill')
            
            # Get only the indicators we need to merge back
            indicator_cols = [col for col in filled_resampled.columns if tf in col]
            
            # Merge these indicators into the original dataframe
            for col in indicator_cols:
                result[col] = filled_resampled[col]
        
        # Add trend alignment features across timeframes
        # For each valid timeframe, create cross-timeframe trend alignment indicators
        if len(valid_timeframes) > 0:
            # Basic trend alignment - positive means aligned uptrend, negative aligned downtrend, near zero means conflicting
            original_trend = result['close'].pct_change(5)
            
            for tf in valid_timeframes:
                if f'{tf}_trend_pct' in result.columns:
                    result[f'trend_align_{tf}'] = original_trend * result[f'{tf}_trend_pct'] 
                    result[f'trend_align_{tf}'] = result[f'trend_align_{tf}'].clip(-1, 1)  # Normalize to [-1, 1]
            
            # Multi-timeframe trend strength (how many timeframes show same trend direction)
            result['mtt_trend_strength'] = 0  # Initialize trend strength
            
            # Count aligned timeframes (original trend + higher timeframes)
            orig_trend_up = (original_trend > 0).astype(int)
            orig_trend_down = (original_trend < 0).astype(int)
            
            for tf in valid_timeframes:
                if f'{tf}_trend_pct' in result.columns:
                    # Add +1 for each aligned uptrend, -1 for each aligned downtrend
                    result['mtt_trend_strength'] += ((result[f'{tf}_trend_pct'] > 0) & (orig_trend_up == 1)).astype(int)
                    result['mtt_trend_strength'] -= ((result[f'{tf}_trend_pct'] < 0) & (orig_trend_down == 1)).astype(int)
            
            # Normalize to range [-1, 1] where:
            # 1 = all timeframes aligned in uptrend
            # -1 = all timeframes aligned in downtrend
            # 0 = no alignment or balanced up/down
            result['mtt_trend_strength'] = result['mtt_trend_strength'] / (len(valid_timeframes) + 1)
        
        # Reset index to get timestamp as a column again
        result = result.reset_index()
        
        # Check for and handle NaN values
        nan_cols = result.columns[result.isna().any()].tolist()
        if nan_cols:
            logger.info(f"Handling NaN values in {len(nan_cols)} multi-timeframe feature columns")
            result = result.fillna(method='ffill').fillna(0)
        
        # Count the multi-timeframe features added
        mtf_cols = [col for col in result.columns if any(tf in col for tf in valid_timeframes) or 'mtt_' in col]
        logger.info(f"Added {len(mtf_cols)} multi-timeframe features from {len(valid_timeframes)} higher timeframes")
        
        return result
    
    def merge_data(
        self, 
        price_df: pd.DataFrame, 
        sentiment_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Merge price and sentiment data while preserving original price resolution"""
        logger.info("Merging price and sentiment data")
        
        # Check if dataframes are empty
        if price_df.empty or sentiment_df.empty:
            logger.error("One or both dataframes are empty")
            return pd.DataFrame()

        # CRITICAL: Remove price columns from social data to avoid conflicts with OHLCV data
        # The model should only use OHLCV prices, not LunarCrush prices
        social_price_columns = ['close_price', 'open_price', 'high_price', 'low_price', 'volume_24h']
        sentiment_df_filtered = sentiment_df.drop(columns=[col for col in social_price_columns if col in sentiment_df.columns])
        
        if len([col for col in social_price_columns if col in sentiment_df.columns]) > 0:
            logger.info(f"Removed social data price columns to avoid conflicts with OHLCV data: {[col for col in social_price_columns if col in sentiment_df.columns]}")
        
        # Make sure sentiment_df has a timestamp column or index
        if not isinstance(sentiment_df_filtered.index, pd.DatetimeIndex):
            if 'timestamp' in sentiment_df_filtered.columns:
                sentiment_df_filtered.set_index('timestamp', inplace=True)
            else:
                logger.error("Sentiment dataframe has no timestamp column or index")
                return price_df
        
        # Make sure price_df has a timestamp column or index
        if not isinstance(price_df.index, pd.DatetimeIndex):
            if 'timestamp' in price_df.columns:
                price_df.set_index('timestamp', inplace=True)
            else:
                logger.error("Price dataframe has no timestamp column or index")
                return price_df

        # Get original price data size
        original_price_rows = len(price_df)
        
        # Preserve price data resolution by reindexing sentiment data to price data
        try:
            # 1. Reindex sentiment data to match all timestamp indices in price data
            aligned_sentiment = sentiment_df_filtered.reindex(
                index=pd.DatetimeIndex(sorted(set(list(price_df.index) + list(sentiment_df_filtered.index)))),
                method=None
            )
            
            # 2. Forward-fill sentiment data (each price point gets most recent sentiment data)
            aligned_sentiment = aligned_sentiment.ffill()
            
            # 3. Reindex back to just the price data timestamps
            aligned_sentiment = aligned_sentiment.reindex(price_df.index)
            
            # 4. Merge on index (price and aligned sentiment now have same index)
            merged_df = pd.concat([price_df, aligned_sentiment], axis=1)
            
            logger.info(f"Merged data while preserving {original_price_rows} price points")
        except Exception as e:
            logger.error(f"Error during high-precision merge: {e}")
            logger.warning("Falling back to basic merge method")
            
            # Fallback to a simple join which will preserve price data if sentiment is less frequent
            merged_df = price_df.join(sentiment_df_filtered, how='left')
        
        # Handle missing values with forward fill (sentiment data frequency is lower than price)
        merged_df = merged_df.ffill()
        
        # If any columns are still missing values, fill with zeros as last resort
        merged_df = merged_df.fillna(0)
        
        # Log final column information for debugging
        close_related_cols = [col for col in merged_df.columns if 'close' in col.lower()]
        logger.info(f"Final merged data shape: {merged_df.shape}, 'close' related columns: {close_related_cols}")
        
        return merged_df
    
    def prepare_ml_data(
        self, 
        df: pd.DataFrame, 
        target_col: str = 'close',
        sequence_length: int = 24,  # Updated from 36 to 24 for new models
        prediction_horizon: int = 1,
        test_size: float = 0.2,
        include_feature_names: bool = True,
        test_mode: bool = False
    ) -> Union[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], 
               Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[str]]]:
        """
        Prepare data for ML model training, predicting percentage change.
        
        Args:
            df: DataFrame with features and target column.
            target_col: Column to predict (used for calculating change).
            sequence_length: Number of time steps to use for sequence data.
            prediction_horizon: Number of time steps to predict into the future.
            test_size: Proportion of data to use for testing.
            include_feature_names: Whether to return feature names as well.
            test_mode: If True, use all data for scaling (no train/test split for scalers).
            
        Returns:
            X_train, X_test, y_train, y_test (and feature_names if include_feature_names=True)
            Note: In test_mode, X_train and y_train will be None.
        """
        logger.info(f"Preparing ML data with sequence length {sequence_length} and horizon {prediction_horizon}")
        
        # CRITICAL: Handle duplicate columns FIRST before any operations
        duplicate_cols = df.columns[df.columns.duplicated()].tolist()
        if duplicate_cols:
            logger.warning(f"Found duplicate column names: {duplicate_cols}")
            # Keep only the first occurrence of each column
            df = df.loc[:, ~df.columns.duplicated(keep='first')]
            logger.info(f"Removed duplicate columns, new shape: {df.shape}")
        
        # ADDITIONAL: Check for any remaining duplicate column names after removal
        remaining_duplicates = df.columns[df.columns.duplicated()].tolist()
        if remaining_duplicates:
            logger.error(f"Still have duplicate columns after removal: {remaining_duplicates}")
            # Force unique column names by adding suffixes
            df.columns = pd.Index([f"{col}_{i}" if df.columns.tolist().count(col) > 1 and df.columns.tolist()[:j+1].count(col) > 1 else col 
                                  for j, col in enumerate(df.columns)])
            logger.info(f"Applied unique suffixes to force unique columns")
        
        # Debug: Log column information related to target
        close_related_cols = [col for col in df.columns if 'close' in col.lower()]
        logger.info(f"Columns containing 'close': {close_related_cols}")
        
        # Ensure the target column exists and is unique
        if target_col not in df.columns:
            logger.error(f"Available columns: {list(df.columns)}")
            raise ValueError(f"Target column '{target_col}' not found in DataFrame.")
        
        # CRITICAL: Ensure we get exactly one column
        target_col_count = (df.columns == target_col).sum()
        if target_col_count > 1:
            logger.error(f"Multiple columns named '{target_col}' found ({target_col_count} occurrences)")
            raise ValueError(f"Multiple columns with name '{target_col}' found. This should not happen after duplicate removal.")
        
        # Get the target series - this should now be guaranteed to be a Series
        target_series = df[target_col]
        
        # Double-check that we got a Series, not a DataFrame
        if isinstance(target_series, pd.DataFrame):
            logger.error(f"Target column '{target_col}' returned DataFrame instead of Series")
            logger.error(f"DataFrame columns: {target_series.columns.tolist()}")
            logger.error(f"This indicates duplicate columns were not properly handled")
            raise ValueError(f"Target column '{target_col}' selection returned multiple columns")
        
        logger.info(f"Successfully selected target column '{target_col}' as Series with shape {target_series.shape}")
        
        # Calculate the target variable: percentage change from the *current* step to prediction_horizon steps ahead
        df['target'] = target_series.pct_change(periods=prediction_horizon).shift(-prediction_horizon)
        
        # Save the last known prices for inverse transformation later
        # We need the price at time t to convert the predicted % change at t+horizon back to a price
        df['price_for_inverse'] = target_series.copy()
        
        # Drop all rows with any NaN values (crucial after shift and pct_change)
        original_len = len(df)
        df = df.dropna()
        dropped_len = original_len - len(df)
        if dropped_len > 0:
            logger.info(f"Dropped {dropped_len} rows with NaN values ({dropped_len/original_len:.2%} of data)")
        
        if df.empty:
            logger.error("DataFrame is empty after dropping NaN values. Cannot proceed.")
            if include_feature_names:
                return np.array([]), np.array([]), np.array([]), np.array([]), []
            else:
                return np.array([]), np.array([]), np.array([]), np.array([])
        
        # Drop the first sequence_length rows (to purge any forward-filled ghosts)
        df = df.iloc[sequence_length:].copy()
        logger.info(f"Dropped first {sequence_length} rows to remove forward-fill artifacts, new shape: {df.shape}")
                
        # Categorize features by type for better feature selection
        technical_features = [
            'ma7', 'ma20', 'ma50', 'ema12', 'ema26', 'macd', 'macd_signal', 'macd_hist',
            'rsi', 'bb_upper', 'bb_middle', 'bb_lower', 'volume_ma7', 'volume_change',
            'price_change_1d', 'price_change_3d', 'price_change_7d', 'atr'
        ]
        
        price_features = ['open', 'high', 'low', 'close', 'volume']
        
        # Identify social features (any columns with these substrings)
        social_indicators = [
            'sentiment', 'social', 'galaxy', 'contributors', 'posts', 
            'interactions', 'spam', 'dominance'
        ]
        
        # Select features (drop target, original price used for inverse, and timestamps)
        drop_cols = ['target', 'price_for_inverse', 'timestamp', 'date', 'time', 'data_source', 'lunarcrush_id']
        feature_cols = [col for col in df.columns if col not in drop_cols and col != target_col]
        
        # Log feature types for transparency
        social_features = [col for col in feature_cols if any(ind in col for ind in social_indicators)]
        if social_features:
            logger.info(f"Including {len(social_features)} social features: {social_features}")
        
        # Apply intelligent outlier handling and scaling based on feature types
        df = self._handle_outliers_and_scaling(df, feature_cols)
        
        # Store feature names if requested
        if include_feature_names:
            feature_names = feature_cols.copy()
            logger.info(f"Returning {len(feature_names)} feature names: {feature_names[:10]}...")
        
        # Fit scalers based on mode
        if test_mode:
            # In test mode: fit scalers on ALL data (no train/test split for scalers)
            logger.info("Test mode: fitting scalers on entire dataset")
            self.feature_scaler.fit(df[feature_cols].values)
            self.price_scaler.fit(df['target'].values.reshape(-1, 1))
        else:
            # Normal training mode: fit scalers on training slice only
            train_cutoff = int(len(df) * (1 - test_size))
            self.feature_scaler.fit(
                df.iloc[:train_cutoff][feature_cols].values
            )
            self.price_scaler.fit(
                df.iloc[:train_cutoff]['target'].values.reshape(-1, 1)
            )

        features = self.feature_scaler.transform(df[feature_cols].values)
        targets  = self.price_scaler.transform(
            df['target'].values.reshape(-1, 1)
        ).flatten()
        
        # Keep the original prices corresponding to the features for inverse transform
        prices_for_inverse = df['price_for_inverse'].values
        
        # Create sequences
        # We need to keep track of the price at the *end* of each feature sequence
        # to use for inverse transforming the prediction
        X, y, prices_at_sequence_end = self._create_sequences_with_price(
            features, targets, prices_for_inverse, sequence_length
        )
        
        # Store prices_at_sequence_end for inverse transformation (required by main.py)
        self.prices_at_sequence_end = prices_at_sequence_end
        
        # Final safety checks for NaN/inf (as before)
        if np.isnan(X).any():
            logger.warning(f"NaN values detected in X after sequence creation: {np.isnan(X).sum()}")
            X = np.nan_to_num(X, nan=0.0)
        
        if np.isnan(y).any():
            logger.warning(f"NaN values detected in y after sequence creation: {np.isnan(y).sum()}")
            y = np.nan_to_num(y, nan=0.0)
        
        if np.isinf(X).any():
            logger.warning(f"Inf values detected in X after sequence creation: {np.isinf(X).sum()}")
            X = np.nan_to_num(X, nan=0.0, posinf=1.0, neginf=-1.0)
        
        if np.isinf(y).any():
            logger.warning(f"Inf values detected in y after sequence creation: {np.isinf(y).sum()}")
            y = np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=-1.0)
        
        if X.size == 0 or y.size == 0:
            logger.error("Empty arrays after sequence creation")
            if include_feature_names:
                return np.array([]), np.array([]), np.array([]), np.array([]), []
            else:
                return np.array([]), np.array([]), np.array([]), np.array([])
        
        # Split the data based on mode
        if test_mode:
            # In test mode: use ALL data for testing, no training split
            logger.info("Test mode: using entire dataset for evaluation")
            X_train, y_train = None, None
            X_test, y_test = X, y
            
            # Store all prices for inverse transformation
            self.prices_at_sequence_end_train = None
            self.prices_at_sequence_end_test = prices_at_sequence_end
            
            logger.info(f"Test mode data shapes - X_test: {X_test.shape}, y_test: {y_test.shape}")
        else:
            # Normal training mode: split the data
            split_index = int(len(X) * (1 - test_size))
            
            X_train = X[:split_index]
            X_test = X[split_index:]
            y_train = y[:split_index]
            y_test = y[split_index:]
            
            # Split the prices for inverse transformation (required by main.py)
            self.prices_at_sequence_end_train = prices_at_sequence_end[:split_index]
            self.prices_at_sequence_end_test = prices_at_sequence_end[split_index:]
            
            logger.info(f"Training mode data shapes - X_train: {X_train.shape}, X_test: {X_test.shape}, y_train: {y_train.shape}, y_test: {y_test.shape}")
        
        if include_feature_names:
            return X_train, X_test, y_train, y_test, feature_names
        else:
            return X_train, X_test, y_train, y_test

    def _create_sequences_with_price(
        self, 
        features: np.ndarray, 
        targets: np.ndarray, 
        prices: np.ndarray, # Original prices corresponding to features/targets
        sequence_length: int
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Create sequence data and store the price at the end of each feature sequence."""
        X, y, prices_end_seq = [], [], []
        
        # We need to stop early enough to have a target for the last sequence
        for i in range(len(features) - sequence_length):
            X.append(features[i:i+sequence_length])
            y.append(targets[i+sequence_length])
            # Store the actual price at the end of the input sequence (time t)
            prices_end_seq.append(prices[i+sequence_length-1]) 
            
        return np.array(X), np.array(y), np.array(prices_end_seq)
    
    def inverse_transform_predictions(self, scaled_predictions: np.ndarray, prices_at_sequence_end: np.ndarray) -> np.ndarray:
        """
        Transform scaled percentage change predictions back to absolute price predictions.
        Requires the actual price at the end of the corresponding input sequence.
        
        Args:
            scaled_predictions: Scaled percentage change predictions from the model.
            prices_at_sequence_end: Actual prices at the end of each input sequence used for prediction.
                                    Must correspond one-to-one with scaled_predictions.
                                    Use self.prices_at_sequence_end_test for test set predictions.

        Returns:
            Absolute price predictions.
        """
        if len(scaled_predictions) != len(prices_at_sequence_end):
            raise ValueError(
                f"Number of predictions ({len(scaled_predictions)}) must match "
                f"number of prices ({len(prices_at_sequence_end)}) for inverse transform."
            )
            
        # Inverse scale the percentage change predictions
        predicted_pct_changes = self.price_scaler.inverse_transform(scaled_predictions.reshape(-1, 1)).flatten()
        
        # Calculate the absolute predicted price:
        # predicted_price = price_at_sequence_end * (1 + predicted_pct_change)
        absolute_predictions = prices_at_sequence_end * (1 + predicted_pct_changes)
        
        return absolute_predictions
    
    def save_data(self, df: pd.DataFrame, filename: str) -> None:
        """Save processed data to CSV"""
        file_path = os.path.join(self.data_dir, filename)
        df.to_csv(file_path)
        logger.info(f"Saved data to {file_path}")
    
    def load_data(self, filename: str) -> pd.DataFrame:
        """Load processed data from CSV"""
        file_path = os.path.join(self.data_dir, filename)
        
        if os.path.exists(file_path):
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            logger.info(f"Loaded data from {file_path}, shape: {df.shape}")
            return df
        else:
            logger.warning(f"File {file_path} does not exist")
            return pd.DataFrame()
    
    def plot_features(self, df: pd.DataFrame, columns: List[str], filename: str = None) -> None:
        """Plot selected features from the dataframe"""
        plt.figure(figsize=(15, 10))
        
        for i, col in enumerate(columns):
            if col in df.columns:
                plt.subplot(len(columns), 1, i+1)
                plt.plot(df.index, df[col])
                plt.title(col)
                plt.grid(True)
        
        plt.tight_layout()
        
        if filename:
            file_path = os.path.join(self.data_dir, filename)
            plt.savefig(file_path)
            logger.info(f"Saved plot to {file_path}")
        else:
            plt.show()
    
    def calculate_social_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate indicators based on social data from LunarCrush
        
        Args:
            df: DataFrame containing social metrics
            
        Returns:
            DataFrame with calculated social indicators
        """
        logger.info("Calculating social indicators")
        
        # Check if dataframe is empty or missing key columns
        if df.empty:
            logger.warning("Empty dataframe provided for social indicators calculation")
            return df
        
        # These are the columns we expect from the LunarCrush API
        social_columns = [
            'sentiment', 'social_score', 'social_volume', 
            'social_impact_score', 'social_contributors_active',
            'social_contributors_created', 'social_interactions', 
            'posts_active', 'posts_created', 'spam', 
            'galaxy_score', 'social_dominance'
        ]
        
        # Check which columns are available
        available_cols = [col for col in social_columns if col in df.columns]
        if not available_cols:
            logger.warning("No social data columns found in dataframe")
            return df
        
        logger.info(f"Found {len(available_cols)} social data columns: {available_cols}")
        
        # Create a copy to avoid modifying the original
        result = df.copy()
        
        # Calculate social momentum indicators (moving averages of social metrics)
        for col in available_cols:
            try:
                # Skip non-numeric columns
                if pd.api.types.is_numeric_dtype(result[col]):
                    # Calculate moving averages over different time periods
                    result[f'{col}_ma3'] = result[col].rolling(window=3).mean()
                    result[f'{col}_ma7'] = result[col].rolling(window=7).mean()
                    
                    # Calculate rate of change over different periods
                    # FIXED: Use safer log calculations to prevent warnings
                    
                    # Ensure minimum values to prevent log(0) warnings
                    safe_col = result[col].clip(lower=1e-10)  # Much smaller minimum
                    safe_col_1d = result[col].shift(1).clip(lower=1e-10)
                    safe_col_3d = result[col].shift(3).clip(lower=1e-10)
                    
                    # Use np.log1p for better numerical stability near zero
                    # log1p(x) = log(1 + x) which is more stable for small x
                    ratio_1d = (safe_col / safe_col_1d) - 1.0  # Convert to percentage change
                    ratio_3d = (safe_col / safe_col_3d) - 1.0  # Convert to percentage change
                    
                    # Apply log1p which is stable for values near zero
                    result[f'{col}_change_1d'] = np.log1p(ratio_1d.clip(-0.9999, 10))  # Prevent log1p(-1)
                    result[f'{col}_change_3d'] = np.log1p(ratio_3d.clip(-0.9999, 10))  # Prevent log1p(-1)
                    
                    # Clip extreme values (log1p changes rarely exceed ±2)
                    result[f'{col}_change_1d'] = result[f'{col}_change_1d'].clip(-2, 2)
                    result[f'{col}_change_3d'] = result[f'{col}_change_3d'].clip(-2, 2)
                    
                    # Calculate acceleration (change in the rate of change)
                    result[f'{col}_accel'] = result[f'{col}_change_1d'].diff()
                    
                    # Calculate Z-score to identify outliers (how many std devs from the mean)
                    rolling_mean = result[col].rolling(window=14).mean()
                    rolling_std = result[col].rolling(window=14).std()
                    result[f'{col}_zscore'] = (result[col] - rolling_mean) / rolling_std.replace(0, 1)  # Avoid div by zero
                    
                    # Clip Z-scores to prevent extreme values
                    result[f'{col}_zscore'] = result[f'{col}_zscore'].clip(-5, 5)
            except Exception as e:
                logger.warning(f"Error calculating indicators for {col}: {e}")
        
        # Create combined social indicators
        if 'sentiment' in result.columns and 'social_volume' in result.columns:
            # Sentiment-weighted volume (volume * normalized sentiment)
            # Normalize sentiment to 0-1 range first
            norm_sentiment = (result['sentiment'] / 100) if result['sentiment'].max() > 1 else result['sentiment']
            result['sentiment_volume'] = norm_sentiment * result['social_volume']
        
        if 'social_dominance' in result.columns and 'sentiment' in result.columns:
            # Dominance-weighted sentiment
            norm_sentiment = (result['sentiment'] / 100) if result['sentiment'].max() > 1 else result['sentiment']
            result['dominance_sentiment'] = result['social_dominance'] * norm_sentiment
        
        if 'galaxy_score' in result.columns and 'price_change_1d' in result.columns:
            # Calculate correlation between galaxy score and price change
            # Using rolling window of 7 days
            result['galaxy_price_corr'] = result['galaxy_score'].rolling(window=7).corr(result['price_change_1d'])
        
        # Clean up missing values
        for col in result.columns:
            if col not in df.columns and pd.api.types.is_numeric_dtype(result[col]):
                # Replace infinities with NaN
                result[col] = result[col].replace([np.inf, -np.inf], np.nan)
                # Fill NaN values using interpolation then forward/backward fill
                result[col] = result[col].interpolate(method='linear', limit_direction='forward').ffill()
                # As a last resort, fill any remaining NaNs with 0
                result[col] = result[col].fillna(0)
        
        logger.info(f"Calculated {len(result.columns) - len(df.columns)} new social indicators")
        return result
    
    def process_pipeline(
        self, 
        token_address: str,
        symbol: str = "SOL",
        resolution: str = "5m",
        days: int = 30,
        save_data: bool = True,
        include_sentiment: bool = True,
        day_offset: int = 0
    ) -> pd.DataFrame:
        """
        Run the full data processing pipeline
        
        Args:
            token_address: Address of the token
            symbol: Symbol of the token
            resolution: Time resolution (1m, 5m, 15m, 1h, 4h, 1d)
            days: Number of days to fetch
            save_data: Whether to save the processed data
            include_sentiment: Whether to include sentiment data
            day_offset: Offset days from current time (for chunked processing)
            
        Returns:
            Processed DataFrame with price data and features
        """
        logger.info(f"Starting data processing pipeline for {symbol} ({token_address})")
        logger.info(f"Fetching {days} days of {resolution} data" + 
                   (f" with {day_offset} day offset" if day_offset > 0 else ""))
        
        # Fetch price data
        price_df = self.fetch_price_data(token_address, resolution, days, day_offset=day_offset)
        
        if price_df.empty:
            logger.error("Failed to fetch price data")
            return pd.DataFrame()
        
        # Calculate technical indicators
        df = self.calculate_technical_indicators(price_df)
        
        # Calculate Fair Value Gap indicators
        df = self.add_fair_value_gaps(df)
        
        # Calculate Volatility-of-Volatility (VoV) features
        df = self.add_volatility_of_volatility(df)
        
        # Add cyclical time features
        df = self.add_time_cyclical_features(df)
        
        # Add Chaikin Money Flow and Price-Volume Trend
        df = self.add_money_flow_features(df)
        
        # Add range-based realized volatility
        df = self.add_realized_volatility(df)
        
        # Add adaptive moving averages (KAMA, Hull MA)
        df = self.add_adaptive_moving_averages(df)
        
        # Add multi-timeframe features
        df = self.add_multi_timeframe_features(df, resolution)
        
        # Add candlestick patterns
        df = self.add_candlestick_patterns(df)
        
        # Add new advanced features
        
        # Add price action swing points
        df = self.add_price_action_swing_points(df)
        
        # Add statistical features (Hurst exponent, moments)
        df = self.add_statistical_features(df)
        
        # Add advanced momentum features with divergence detection
        df = self.add_advanced_momentum_features(df)
        
        # Add support and resistance zones
        df = self.add_support_resistance_zones(df)
        
        # Add market regime features
        df = self.add_market_regime_features(df)
        
        # Add volume profile features
        df = self.add_volume_profile_features(df)
        
        # Add intermarket correlation features (BTC/ETH)
        df = self.add_intermarket_correlation_features(df, symbol)
        
        # Include sentiment data if requested
        if include_sentiment:
            sentiment_df = self.fetch_sentiment_data_from_timescale(symbol, days)
            if not sentiment_df.empty:
                # First merge the data
                df = self.merge_data(df, sentiment_df)
                
                # Then calculate social indicators on the merged data
                df = self.calculate_social_indicators(df)
                
                logger.info(f"Added social data and indicators, total columns: {len(df.columns)}")
            else:
                logger.warning(f"No social data available for {symbol}, skipping social features")
                # Add placeholder social columns to maintain consistency
                df = self._add_placeholder_social_features(df)
        
        # Save the processed data if requested
        if save_data:
            filename = f"{symbol}_{resolution}_{days}days_" + datetime.now().strftime("%Y%m%d")
            if day_offset > 0:
                filename += f"_offset{day_offset}"
            if include_sentiment:
                filename += "_with_social"
            self.save_data(df, filename)
        
        return df
    
    def add_price_action_swing_points(self, df: pd.DataFrame, window: int = 12) -> pd.DataFrame:
        """
        Detect swing highs and lows in price data using rolling windows.
        These are key structural points in price action.
        
        Args:
            df: DataFrame with OHLCV data
            window: Number of bars to look on each side for swing detection
            
        Returns:
            DataFrame with added swing point features
        """
        logger.info(f"Detecting price action swing points with window {window}")
        
        # Check if dataframe is empty or missing required columns
        if df.empty or not all(col in df.columns for col in ['high', 'low']):
            logger.warning("Missing data for swing point detection")
            return df
            
        # Create a copy to avoid modifying the original
        result = df.copy()
        
        # FIXED: Only use backward-looking shifts to avoid look-ahead bias
        # Create only backward shifts for comparison
        shifts = list(range(1, window+1))
        
        # Initialize swing point columns
        result['swing_high'] = True
        result['swing_low'] = True
        
        # For each shift, check if the current point is higher/lower than past bars only
        for shift in shifts:
            # Current high must be higher than all past bars in the window
            result['swing_high'] &= (result['high'] > result['high'].shift(shift))
            
            # Current low must be lower than all past bars in the window
            result['swing_low'] &= (result['low'] < result['low'].shift(shift))
        
        # Fill NaN values (from shifting) with False
        result['swing_high'] = result['swing_high'].fillna(False)
        result['swing_low'] = result['swing_low'].fillna(False)
        
        # Add swing point strength based on price distance
        result['swing_high_strength'] = 0.0
        result['swing_low_strength'] = 0.0
        
        # Calculate how much higher/lower compared to surrounding bars
        for idx in result.index[result['swing_high']]:
            window_highs = [result.loc[idx - shift, 'high'] if idx - shift in result.index else np.nan 
                           for shift in shifts if shift != 0]
            avg_window_high = np.nanmean(window_highs)
            if not np.isnan(avg_window_high) and avg_window_high > 0:
                # FIXED: Use log ratio for more stable strength calculation
                result.loc[idx, 'swing_high_strength'] = np.log(result.loc[idx, 'high'] / avg_window_high)
                
        for idx in result.index[result['swing_low']]:
            window_lows = [result.loc[idx - shift, 'low'] if idx - shift in result.index else np.nan 
                          for shift in shifts if shift != 0]
            avg_window_low = np.nanmean(window_lows)
            if not np.isnan(avg_window_low) and avg_window_low > 0:
                # FIXED: Use log ratio for more stable strength calculation
                result.loc[idx, 'swing_low_strength'] = np.log(avg_window_low / result.loc[idx, 'low'])
        
        # Add proximity to recent swing points
        result['distance_to_last_swing_high'] = np.nan
        result['distance_to_last_swing_low'] = np.nan
        
        # Initialize columns to store the positions of the last swing points
        result['last_swing_high_idx'] = np.nan
        result['last_swing_low_idx'] = np.nan
        
        # Set the values where swing points occur
        result.loc[result['swing_high'], 'last_swing_high_idx'] = result.index[result['swing_high']]
        result.loc[result['swing_low'], 'last_swing_low_idx'] = result.index[result['swing_low']]
        
        # Forward fill the values to propagate the last known swing point
        result['last_swing_high_idx'] = result['last_swing_high_idx'].ffill()
        result['last_swing_low_idx'] = result['last_swing_low_idx'].ffill()
        
        # Calculate bar distance to last swing points
        for idx in result.index:
            if not pd.isna(result.loc[idx, 'last_swing_high_idx']):
                result.loc[idx, 'distance_to_last_swing_high'] = idx - result.loc[idx, 'last_swing_high_idx']
            
            if not pd.isna(result.loc[idx, 'last_swing_low_idx']):
                result.loc[idx, 'distance_to_last_swing_low'] = idx - result.loc[idx, 'last_swing_low_idx']
        
        # Drop intermediate columns
        result = result.drop(columns=['last_swing_high_idx', 'last_swing_low_idx'], errors='ignore')
        
        logger.info(f"Added swing point features: found {result['swing_high'].sum()} swing highs and {result['swing_low'].sum()} swing lows")
        return result
    
    def add_statistical_features(self, df: pd.DataFrame, windows: list = [14, 30, 50]) -> pd.DataFrame:
        """
        Calculate advanced statistical features including Hurst exponent and statistical moments.
        These features help identify market regimes and predict future volatility.
        
        Args:
            df: DataFrame with OHLCV data
            windows: List of rolling windows to use for calculations
            
        Returns:
            DataFrame with added statistical features
        """
        logger.info("Calculating advanced statistical features")
        
        # Check if dataframe is empty or missing required columns
        if df.empty or 'close' not in df.columns:
            logger.warning("Missing price data for statistical features")
            return df
            
        # Create a copy to avoid modifying the original
        result = df.copy()
        
        # Calculate returns
        result['returns'] = result['close'].pct_change()
        result['log_returns'] = np.log(result['close'] / result['close'].shift(1))
        
        # Replace infinities and NaNs
        result['returns'] = result['returns'].replace([np.inf, -np.inf], np.nan).fillna(0)
        result['log_returns'] = result['log_returns'].replace([np.inf, -np.inf], np.nan).fillna(0)
        
        # Calculate Hurst exponent (trend vs mean-reversion)
        def calculate_hurst(ts, max_lag=20):
            """Calculate Hurst exponent (>0.5=trending, <0.5=mean-reverting)"""
            # Need at least 2*max_lag data points
            if len(ts) < 2*max_lag:
                return np.nan
                
            # Only use finite values
            ts = ts[np.isfinite(ts)]
            if len(ts) < 2*max_lag:
                return np.nan
                
            # Calculate lags
            lags = range(2, max_lag)
            
            # Calculate variance of differenced series for each lag
            tau = [np.std(np.subtract(ts[lag:], ts[:-lag])) for lag in lags]
            
            # Avoid log(0) error
            if any(t <= 0 for t in tau):
                return np.nan
                
            # Calculate Hurst as the slope of the log-log plot
            reg = np.polyfit(np.log(lags), np.log(tau), 1)
            return reg[0]
        
        # Calculate Hurst exponent for each window
        for window in windows:
            result[f'hurst_{window}'] = result['log_returns'].rolling(window=window*2).apply(
                lambda x: calculate_hurst(x, max_lag=min(20, window//2)),
                raw=True
            )
        
        # Calculate statistical moments for returns
        for window in windows:
            # Skewness (asymmetry of distribution)
            result[f'returns_skew_{window}'] = result['returns'].rolling(window).skew()
            
            # Kurtosis (tail heaviness)
            result[f'returns_kurt_{window}'] = result['returns'].rolling(window).kurt()
            
            # Normalized range (high-low range divided by standard deviation)
            price_range = (result['high'] - result['low'])
            returns_std = result['returns'].rolling(window).std()
            # FIXED: Add minimum threshold to prevent division by very small std
            min_std = 0.0001
            safe_std = np.maximum(returns_std * result['close'], min_std * result['close'])
            result[f'normalized_range_{window}'] = price_range / safe_std
            
            # Tail risk measures
            # Calculate VaR (Value at Risk) - 5th percentile
            result[f'var_5pct_{window}'] = result['returns'].rolling(window).quantile(0.05)
            
            # Calculate expected shortfall (average of worst 5% returns)
            def expected_shortfall(x, percentile=0.05):
                """Calculate expected shortfall (CVaR)"""
                cutoff = int(len(x) * percentile)
                if cutoff == 0:
                    return np.nan
                worst_returns = np.sort(x)[:cutoff]
                return np.mean(worst_returns) if len(worst_returns) > 0 else np.nan
                
            result[f'cvar_5pct_{window}'] = result['returns'].rolling(window).apply(
                lambda x: expected_shortfall(x, 0.05),
                raw=True
            )
        
        # Handle NaN values
        for col in result.columns:
            if col.startswith(('hurst_', 'returns_skew_', 'returns_kurt_', 'normalized_range_', 'var_', 'cvar_')):
                # Forward fill only
                result[col] = result[col].fillna(method='ffill')
                
                # Clip extreme values
                if 'skew' in col or 'kurt' in col:
                    # Skewness and kurtosis can be extreme
                    result[col] = result[col].clip(-10, 10)
                elif 'var' in col or 'cvar' in col:
                    # Risk measures shouldn't be extreme
                    result[col] = result[col].clip(-0.5, 0.5)
                elif 'hurst' in col:
                    # Hurst should be between 0 and 1 
                    result[col] = result[col].clip(0, 1)
                    
        # Drop temporary columns
        result = result.drop(columns=['returns', 'log_returns'], errors='ignore')
        
        logger.info(f"Added {sum(col.startswith(('hurst_', 'returns_', 'normalized_', 'var_', 'cvar_')) for col in result.columns)} statistical features")
        return result
    
    def add_advanced_momentum_features(self, df: pd.DataFrame, windows: list = [14, 21]) -> pd.DataFrame:
        """
        Calculate advanced momentum features including divergence detection.
        Divergence between price and momentum oscillators often precedes reversals.
        
        Args:
            df: DataFrame with OHLCV data
            windows: List of lookback periods for momentum calculations
            
        Returns:
            DataFrame with added momentum features
        """
        logger.info("Calculating advanced momentum features with divergence detection")
        
        # Check if dataframe is empty or missing required columns
        if df.empty or not all(col in df.columns for col in ['close']):
            logger.warning("Missing data for momentum features calculation")
            return df
            
        # Create a copy to avoid modifying the original
        result = df.copy()
        
        # Calculate basic price action patterns
        result['higher_high'] = (result['high'] > result['high'].shift(1))
        result['lower_low'] = (result['low'] < result['low'].shift(1))
        result['higher_close'] = (result['close'] > result['close'].shift(1))
        
        # Calculate swing points for divergence detection if not already present
        if 'swing_high' not in result.columns:
            # Use this simple definition if swing points haven't been calculated
            window = 2
            result['swing_high'] = (result['high'] > result['high'].shift(window)) & \
                                  (result['high'] > result['high'].shift(1))
            result['swing_low'] = (result['low'] < result['low'].shift(window)) & \
                                 (result['low'] < result['low'].shift(1))
        
        # Calculate classic RSI if not already in dataframe
        for window in windows:
            if f'RSI_{window}' not in result.columns:
                # Calculate price changes
                delta = result['close'].diff()
                
                # Calculate gains (positive changes) and losses (negative changes)
                gain = delta.copy()
                loss = delta.copy()
                gain[gain < 0] = 0
                loss[loss > 0] = 0
                loss = abs(loss)
                
                # Calculate average gains and losses over 'window' periods
                avg_gain = gain.rolling(window=window).mean()
                avg_loss = loss.rolling(window=window).mean()
                
                # Calculate relative strength
                rs = avg_gain / avg_loss
                
                # Calculate RSI
                result[f'RSI_{window}'] = 100 - (100 / (1 + rs))
                result[f'RSI_{window}'] = result[f'RSI_{window}'].replace([np.inf, -np.inf], np.nan).fillna(50)
        
        # Add rate of change for price and oscillators
        for window in [3, 5, 10]:
            # Price momentum
            result[f'price_roc_{window}'] = result['close'].pct_change(periods=window) * 100
            
            # Oscillator momentum
            for base_window in windows:
                result[f'rsi_{base_window}_roc_{window}'] = result[f'RSI_{base_window}'].diff(periods=window)
        
        # Detect regular and hidden divergences
        for window in windows:
            rsi_col = f'RSI_{window}'
            
            # Create columns for storing divergence information
            result[f'reg_bearish_div_{window}'] = False
            result[f'reg_bullish_div_{window}'] = False
            result[f'hidden_bearish_div_{window}'] = False
            result[f'hidden_bullish_div_{window}'] = False
            
            # Find regular bearish divergence (price higher high, RSI lower high)
            # Look at swing highs
            for i in range(window, len(result)):
                if not result.iloc[i]['swing_high']:
                    continue
                    
                # Find previous swing high within reasonable range
                prev_idx = None
                for j in range(i-window, i-1):
                    if j >= 0 and result.iloc[j]['swing_high']:
                        prev_idx = j
                        break
                
                if prev_idx is not None:
                    # Check for bearish divergence (price up, RSI down)
                    if (result.iloc[i]['high'] > result.iloc[prev_idx]['high'] and 
                        result.iloc[i][rsi_col] < result.iloc[prev_idx][rsi_col]):
                        result.iloc[i, result.columns.get_loc(f'reg_bearish_div_{window}')] = True
                    
                    # Check for hidden bearish divergence (price lower high, RSI higher high)
                    if (result.iloc[i]['high'] < result.iloc[prev_idx]['high'] and 
                        result.iloc[i][rsi_col] > result.iloc[prev_idx][rsi_col]):
                        result.iloc[i, result.columns.get_loc(f'hidden_bearish_div_{window}')] = True
            
            # Find regular bullish divergence (price lower low, RSI higher low)
            # Look at swing lows
            for i in range(window, len(result)):
                if not result.iloc[i]['swing_low']:
                    continue
                    
                # Find previous swing low within reasonable range
                prev_idx = None
                for j in range(i-window, i-1):
                    if j >= 0 and result.iloc[j]['swing_low']:
                        prev_idx = j
                        break
                
                if prev_idx is not None:
                    # Check for bullish divergence (price down, RSI up)
                    if (result.iloc[i]['low'] < result.iloc[prev_idx]['low'] and 
                        result.iloc[i][rsi_col] > result.iloc[prev_idx][rsi_col]):
                        result.iloc[i, result.columns.get_loc(f'reg_bullish_div_{window}')] = True
                    
                    # Check for hidden bullish divergence (price higher low, RSI lower low)
                    if (result.iloc[i]['low'] > result.iloc[prev_idx]['low'] and 
                        result.iloc[i][rsi_col] < result.iloc[prev_idx][rsi_col]):
                        result.iloc[i, result.columns.get_loc(f'hidden_bullish_div_{window}')] = True
        
        # Calculate strength of divergences based on magnitude of difference
        for window in windows:
            rsi_col = f'RSI_{window}'
            
            # Create columns for storing divergence strength
            result[f'bearish_div_strength_{window}'] = 0.0
            result[f'bullish_div_strength_{window}'] = 0.0
            
            # Calculate strength for regular bearish divergences
            bearish_div_mask = result[f'reg_bearish_div_{window}'] | result[f'hidden_bearish_div_{window}']
            bullish_div_mask = result[f'reg_bullish_div_{window}'] | result[f'hidden_bullish_div_{window}']
            
            if bearish_div_mask.sum() > 0:
                # For bearish divergences, get the price and RSI changes
                for i in result.index[bearish_div_mask]:
                    # Find previous swing high
                    prev_idx = None
                    for j in range(1, window):
                        if i-j in result.index and (result.loc[i-j, 'swing_high']):
                            prev_idx = i-j
                            break
                    
                    if prev_idx is not None:
                        # Calculate price change percentage
                        price_change = (result.loc[i, 'high'] - result.loc[prev_idx, 'high']) / result.loc[prev_idx, 'high']
                        
                        # Calculate RSI change
                        rsi_change = result.loc[i, rsi_col] - result.loc[prev_idx, rsi_col]
                        
                        # FIXED: Use bounded divergence strength calculation
                        # Divergence strength is function of both changes
                        # For bearish div: bigger price increase with bigger RSI decrease = stronger divergence
                        if result.loc[i, f'reg_bearish_div_{window}']:
                            # Regular bearish: price up, RSI down 
                            strength = np.tanh(price_change * 10) * np.tanh(-rsi_change / 20)
                        else:
                            # Hidden bearish: price down, RSI up
                            strength = np.tanh(-price_change * 10) * np.tanh(rsi_change / 20)
                            
                        result.loc[i, f'bearish_div_strength_{window}'] = max(0, strength)
            
            if bullish_div_mask.sum() > 0:
                # For bullish divergences, get the price and RSI changes
                for i in result.index[bullish_div_mask]:
                    # Find previous swing low
                    prev_idx = None
                    for j in range(1, window):
                        if i-j in result.index and (result.loc[i-j, 'swing_low']):
                            prev_idx = i-j
                            break
                    
                    if prev_idx is not None:
                        # Calculate price change percentage
                        price_change = (result.loc[i, 'low'] - result.loc[prev_idx, 'low']) / result.loc[prev_idx, 'low']
                        
                        # Calculate RSI change
                        rsi_change = result.loc[i, rsi_col] - result.loc[prev_idx, rsi_col]
                        
                        # FIXED: Use bounded divergence strength calculation
                        # Divergence strength is function of both changes
                        # For bullish div: bigger price decrease with bigger RSI increase = stronger divergence
                        if result.loc[i, f'reg_bullish_div_{window}']:
                            # Regular bullish: price down, RSI up
                            strength = np.tanh(-price_change * 10) * np.tanh(rsi_change / 20)
                        else:
                            # Hidden bullish: price up, RSI down
                            strength = np.tanh(price_change * 10) * np.tanh(-rsi_change / 20)
                            
                        result.loc[i, f'bullish_div_strength_{window}'] = max(0, strength)
            
        # Compute distance from overbought/oversold conditions
        for window in windows:
            rsi_col = f'RSI_{window}'
            
            # Distance from overbought (70) and oversold (30) levels
            result[f'rsi_{window}_ob_distance'] = 70 - result[rsi_col]
            result[f'rsi_{window}_os_distance'] = result[rsi_col] - 30
            
            # Normalized distance (-1 to 1, where -1 is extremely oversold, 1 is extremely overbought)
            result[f'rsi_{window}_norm'] = (result[rsi_col] - 50) / 50
        
        # Add RSI-based regime classification
        for window in windows:
            rsi_col = f'RSI_{window}'
            
            # Create regime column (1=bullish, 0=neutral, -1=bearish)
            result[f'rsi_{window}_regime'] = 0
            
            # Bullish when RSI > 60 and rising
            bull_mask = (result[rsi_col] > 60) & (result[rsi_col] > result[rsi_col].shift(1))
            result.loc[bull_mask, f'rsi_{window}_regime'] = 1
            
            # Bearish when RSI < 40 and falling
            bear_mask = (result[rsi_col] < 40) & (result[rsi_col] < result[rsi_col].shift(1))
            result.loc[bear_mask, f'rsi_{window}_regime'] = -1
        
        # Drop temporary columns if no longer needed
        temp_cols = ['higher_high', 'lower_low', 'higher_close']
        result = result.drop(columns=temp_cols, errors='ignore')
        
        # Count divergence signals
        div_columns = [col for col in result.columns if 'div_' in col and not 'strength' in col]
        div_count = result[div_columns].sum().sum()
        
        logger.info(f"Added advanced momentum features with {div_count} divergence signals detected")
        return result
    
    def add_support_resistance_zones(self, df: pd.DataFrame, window: int = 50, tolerance: float = 0.01) -> pd.DataFrame:
        """
        Identify support and resistance zones based on swing points and price clusters.
        These zones are critical areas where price often reverses or pauses.
        
        Args:
            df: DataFrame with OHLCV data
            window: Lookback window for identifying zones
            tolerance: Percentage tolerance for clustering levels
            
        Returns:
            DataFrame with support/resistance zone features
        """
        logger.info(f"Calculating support and resistance zones with {window} bar lookback")
        
        # Check if dataframe is empty or missing required columns
        if df.empty or not all(col in df.columns for col in ['high', 'low']):
            logger.warning("Missing data for support/resistance calculation")
            return df
            
        # Create a copy to avoid modifying the original
        result = df.copy()
        
        # Calculate swing points if not already present
        if 'swing_high' not in result.columns:
            # FIXED: Removed negative shift to avoid look-ahead bias
            # Now only compares with past data
            swing_window = 2
            result['swing_high'] = (result['high'] > result['high'].shift(swing_window)) & \
                                  (result['high'] > result['high'].shift(1))
            result['swing_low'] = (result['low'] < result['low'].shift(swing_window)) & \
                                 (result['low'] < result['low'].shift(1))
        
        # Identify swing levels in the lookback window
        def identify_levels_in_window(row_idx):
            """Identify support and resistance levels in the lookback window"""
            if row_idx < window:
                # Not enough data for lookback
                return [], []
                
            # Get window data
            start_idx = max(0, row_idx - window)
            window_data = result.iloc[start_idx:row_idx]
            
            # Get swing high and low points
            swing_highs = window_data[window_data['swing_high']]['high'].values
            swing_lows = window_data[window_data['swing_low']]['low'].values
            
            # Cluster nearby levels together
            def cluster_levels(levels, tolerance, reference_price):
                """Group nearby price levels into clusters"""
                if len(levels) == 0:
                    return []
                    
                # Sort levels
                sorted_levels = np.sort(levels)
                clusters = []
                current_cluster = [sorted_levels[0]]
                
                for level in sorted_levels[1:]:
                    # Check if level is within tolerance of current cluster average
                    cluster_avg = np.mean(current_cluster)
                    if abs(level - cluster_avg) / reference_price <= tolerance:
                        # Add to current cluster
                        current_cluster.append(level)
                    else:
                        # Finalize current cluster and start a new one
                        clusters.append(np.mean(current_cluster))
                        current_cluster = [level]
                
                # Add the last cluster
                if current_cluster:
                    clusters.append(np.mean(current_cluster))
                    
                return clusters
            
            # Get current price for tolerance normalization
            current_price = result.iloc[row_idx]['close']
            
            # Cluster levels
            resistance_levels = cluster_levels(swing_highs, tolerance, current_price)
            support_levels = cluster_levels(swing_lows, tolerance, current_price)
            
            return resistance_levels, support_levels
        
        # Initialize columns for S/R levels
        max_levels = 3  # Track top 3 closest levels
        
        for i in range(1, max_levels + 1):
            result[f'resistance_{i}'] = np.nan
            result[f'support_{i}'] = np.nan
            result[f'resistance_{i}_strength'] = 0
            result[f'support_{i}_strength'] = 0
            result[f'resistance_{i}_distance_pct'] = np.nan
            result[f'support_{i}_distance_pct'] = np.nan
        
        # Calculate for each row
        for idx in range(window, len(result)):
            # Get current price
            current_price = result.iloc[idx]['close']
            
            # Get resistance and support levels
            resistance_levels, support_levels = identify_levels_in_window(idx)
            
            # Sort resistance levels (lowest to highest) and filter to those above current price
            resistance_levels = [level for level in resistance_levels if level > current_price]
            resistance_levels.sort()
            
            # Sort support levels (highest to lowest) and filter to those below current price
            support_levels = [level for level in support_levels if level < current_price]
            support_levels.sort(reverse=True)
            
            # Add resistance levels to dataframe (limit to max_levels)
            for i, level in enumerate(resistance_levels[:max_levels]):
                col_idx = i + 1
                # Calculate strength based on number of times level was tested
                strength = sum(1 for price in result.iloc[idx-window:idx]['high'] 
                              if abs(price - level) / level <= tolerance)
                
                # Calculate distance as percentage from current price
                distance_pct = (level - current_price) / current_price * 100
                
                # Store values
                result.iloc[idx, result.columns.get_loc(f'resistance_{col_idx}')] = level
                result.iloc[idx, result.columns.get_loc(f'resistance_{col_idx}_strength')] = strength
                result.iloc[idx, result.columns.get_loc(f'resistance_{col_idx}_distance_pct')] = distance_pct
            
            # Add support levels to dataframe (limit to max_levels)
            for i, level in enumerate(support_levels[:max_levels]):
                col_idx = i + 1
                # Calculate strength based on number of times level was tested
                strength = sum(1 for price in result.iloc[idx-window:idx]['low'] 
                              if abs(price - level) / level <= tolerance)
                
                # Calculate distance as percentage from current price
                distance_pct = (level - current_price) / current_price * 100
                
                # Store values
                result.iloc[idx, result.columns.get_loc(f'support_{col_idx}')] = level
                result.iloc[idx, result.columns.get_loc(f'support_{col_idx}_strength')] = strength
                result.iloc[idx, result.columns.get_loc(f'support_{col_idx}_distance_pct')] = distance_pct
        
        # Identify when price breaks through support or resistance
        result['breaks_resistance'] = False
        result['breaks_support'] = False
        
        for idx in range(window + 1, len(result)):
            # Check if current close breaks above previous resistance
            for i in range(1, max_levels + 1):
                prev_resistance = result.iloc[idx-1][f'resistance_{i}']
                if not pd.isna(prev_resistance) and result.iloc[idx]['close'] > prev_resistance:
                    result.iloc[idx, result.columns.get_loc('breaks_resistance')] = True
                    break
            
            # Check if current close breaks below previous support
            for i in range(1, max_levels + 1):
                prev_support = result.iloc[idx-1][f'support_{i}']
                if not pd.isna(prev_support) and result.iloc[idx]['close'] < prev_support:
                    result.iloc[idx, result.columns.get_loc('breaks_support')] = True
                    break
        
        # Calculate a key support/resistance strength metric
        result['sr_zone_strength'] = 0
        
        for idx in range(window, len(result)):
            # Sum the strengths of nearby support and resistance zones
            sr_strength = 0
            
            # Add resistance strengths that are within 2% of price
            for i in range(1, max_levels + 1):
                distance_col = f'resistance_{i}_distance_pct'
                strength_col = f'resistance_{i}_strength'
                if not pd.isna(result.iloc[idx][distance_col]) and \
                   abs(result.iloc[idx][distance_col]) < 2.0:
                    sr_strength += result.iloc[idx][strength_col]
            
            # Add support strengths that are within 2% of price
            for i in range(1, max_levels + 1):
                distance_col = f'support_{i}_distance_pct'
                strength_col = f'support_{i}_strength'
                if not pd.isna(result.iloc[idx][distance_col]) and \
                   abs(result.iloc[idx][distance_col]) < 2.0:
                    sr_strength += result.iloc[idx][strength_col]
            
            # Store the combined strength
            result.iloc[idx, result.columns.get_loc('sr_zone_strength')] = sr_strength
        
        # Fill NaN values in distance columns
        for i in range(1, max_levels + 1):
            result[f'resistance_{i}_distance_pct'] = result[f'resistance_{i}_distance_pct'].fillna(100)
            result[f'support_{i}_distance_pct'] = result[f'support_{i}_distance_pct'].fillna(-100)
        
        # Create nearest S/R zone feature
        result['nearest_zone_distance_pct'] = 100.0
        result['nearest_zone_type'] = 'none'  # 'support', 'resistance', or 'none'
        
        for idx in range(window, len(result)):
            # Check resistance distances
            for i in range(1, max_levels + 1):
                distance = result.iloc[idx][f'resistance_{i}_distance_pct']
                if not pd.isna(distance) and abs(distance) < abs(result.iloc[idx]['nearest_zone_distance_pct']):
                    result.iloc[idx, result.columns.get_loc('nearest_zone_distance_pct')] = distance
                    result.iloc[idx, result.columns.get_loc('nearest_zone_type')] = 'resistance'
            
            # Check support distances
            for i in range(1, max_levels + 1):
                distance = result.iloc[idx][f'support_{i}_distance_pct']
                if not pd.isna(distance) and abs(distance) < abs(result.iloc[idx]['nearest_zone_distance_pct']):
                    result.iloc[idx, result.columns.get_loc('nearest_zone_distance_pct')] = distance
                    result.iloc[idx, result.columns.get_loc('nearest_zone_type')] = 'support'
        
        # Create indicator variables for when price is near key levels
        result['at_resistance'] = (result['nearest_zone_type'] == 'resistance') & \
                                 (abs(result['nearest_zone_distance_pct']) < 0.5)
        result['at_support'] = (result['nearest_zone_type'] == 'support') & \
                              (abs(result['nearest_zone_distance_pct']) < 0.5)
        
        # Encode nearest_zone_type as numeric for ML models
        result['zone_type_numeric'] = 0  # Default: no zone
        result.loc[result['nearest_zone_type'] == 'support', 'zone_type_numeric'] = -1
        result.loc[result['nearest_zone_type'] == 'resistance', 'zone_type_numeric'] = 1
        
        # Replace the string categorical column with a numeric version
        # This ensures consistent encoding and prevents string conversion issues later
        zone_type_map = {'none': 0, 'support': -1, 'resistance': 1}
        result['nearest_zone_type'] = result['nearest_zone_type'].map(zone_type_map)
        
        logger.info(f"Added support and resistance zone features with {max_levels} levels tracked")
        return result
    
    def add_market_regime_features(self, df: pd.DataFrame, 
                                  windows: list = [20, 50, 100],
                                  volatility_window: int = 20) -> pd.DataFrame:
        """
        Calculate market regime features to identify trending, ranging, and volatile markets.
        Different trading strategies perform better in different market regimes.
        
        Args:
            df: DataFrame with OHLCV data
            windows: List of lookback periods for regime calculations
            volatility_window: Window for volatility calculations
            
        Returns:
            DataFrame with market regime features
        """
        logger.info("Calculating market regime features")
        
        # Check if dataframe is empty or missing required columns
        if df.empty or not all(col in df.columns for col in ['close']):
            logger.warning("Missing data for market regime calculation")
            return df
            
        # Create a copy to avoid modifying the original
        result = df.copy()
        
        # Calculate log returns
        result['log_return'] = np.log(result['close'] / result['close'].shift(1))
        result['log_return'] = result['log_return'].replace([np.inf, -np.inf], np.nan).fillna(0)
        
        # Calculate Directional Movement for trending vs ranging detection
        for window in windows:
            # Calculate True Range (TR)
            result['tr'] = np.maximum(
                result['high'] - result['low'],
                np.maximum(
                    abs(result['high'] - result['close'].shift(1)),
                    abs(result['low'] - result['close'].shift(1))
                )
            )
            
            # Calculate Directional Movement
            result['plus_dm'] = np.where(
                (result['high'] - result['high'].shift(1)) > (result['low'].shift(1) - result['low']),
                np.maximum(result['high'] - result['high'].shift(1), 0),
                0
            )
            
            result['minus_dm'] = np.where(
                (result['low'].shift(1) - result['low']) > (result['high'] - result['high'].shift(1)),
                np.maximum(result['low'].shift(1) - result['low'], 0),
                0
            )
            
            # Calculate smoothed averages
            result[f'atr_{window}'] = result['tr'].rolling(window=window).mean()
            result[f'plus_di_{window}'] = 100 * (result['plus_dm'].rolling(window=window).mean() / 
                                                result[f'atr_{window}'])
            result[f'minus_di_{window}'] = 100 * (result['minus_dm'].rolling(window=window).mean() / 
                                                 result[f'atr_{window}'])
            
            # Calculate directional movement index (DX)
            result[f'dx_{window}'] = 100 * abs(
                (result[f'plus_di_{window}'] - result[f'minus_di_{window}']) / 
                (result[f'plus_di_{window}'] + result[f'minus_di_{window}'])
            )
            
            # Calculate Average Directional Index (ADX)
            result[f'adx_{window}'] = result[f'dx_{window}'].rolling(window=window).mean()
            
            # Get trend direction: +1 for uptrend, -1 for downtrend, 0 for no clear trend
            result[f'trend_direction_{window}'] = np.where(
                result[f'plus_di_{window}'] > result[f'minus_di_{window}'], 1,
                np.where(result[f'plus_di_{window}'] < result[f'minus_di_{window}'], -1, 0)
            )
            
            # Define regimes based on ADX thresholds
            # ADX > 25: Trending, ADX < 20: Ranging, Between: Mixed
            result[f'adx_regime_{window}'] = np.where(
                result[f'adx_{window}'] > 25, 'trending',
                np.where(result[f'adx_{window}'] < 20, 'ranging', 'mixed')
            )
            
            # Combine trend direction and strength
            result[f'regime_{window}'] = np.where(
                result[f'adx_regime_{window}'] == 'trending',
                np.where(result[f'trend_direction_{window}'] == 1, 'strong_uptrend', 'strong_downtrend'),
                np.where(result[f'adx_regime_{window}'] == 'ranging', 'ranging', 
                        np.where(result[f'trend_direction_{window}'] == 1, 'weak_uptrend', 'weak_downtrend'))
            )
            
            # Encode regimes numerically for machine learning
            result[f'regime_numeric_{window}'] = np.where(
                result[f'regime_{window}'] == 'strong_uptrend', 2,
                np.where(result[f'regime_{window}'] == 'weak_uptrend', 1,
                        np.where(result[f'regime_{window}'] == 'ranging', 0,
                                np.where(result[f'regime_{window}'] == 'weak_downtrend', -1, -2)))
            )
        
        # Calculate volatility regimes
        # Calculate rolling volatility
        result['volatility'] = result['log_return'].rolling(window=volatility_window).std() * np.sqrt(252)
        
        # Calculate z-score of volatility to identify relative volatility regimes
        vol_mean = result['volatility'].rolling(window=volatility_window*2).mean()
        vol_std = result['volatility'].rolling(window=volatility_window*2).std()
        result['volatility_zscore'] = (result['volatility'] - vol_mean) / vol_std
        
        # Define volatility regimes
        result['volatility_regime'] = np.where(
            result['volatility_zscore'] > 1.0, 'high_volatility',
            np.where(result['volatility_zscore'] < -1.0, 'low_volatility', 'normal_volatility')
        )
        
        # Encode volatility regimes numerically
        result['volatility_regime_numeric'] = np.where(
            result['volatility_regime'] == 'high_volatility', 1,
            np.where(result['volatility_regime'] == 'low_volatility', -1, 0)
        )
        
        # Handle NaN values
        regime_cols = [col for col in result.columns if any(x in col for x in 
                      ['regime', 'adx_', 'trend_', 'volatility', 'dx_', 'plus_di_', 'minus_di_'])]
        
        for col in regime_cols:
            if result[col].dtype == 'object':
                # For categorical columns, fill with most common value or 'unknown'
                most_common = result[col].mode().iloc[0] if not result[col].isna().all() else 'unknown'
                result[col] = result[col].fillna(most_common)
            else:
                # For numeric columns, forward fill only
                result[col] = result[col].fillna(method='ffill').fillna(0)
        
        # Convert string categorical columns to numeric values to prevent conversion issues
        # Define mapping dictionaries for each categorical column
        adx_regime_map = {'ranging': 0, 'mixed': 1, 'trending': 2, 'unknown': 0}
        regime_map = {
            'ranging': 0, 
            'weak_uptrend': 1, 
            'strong_uptrend': 2, 
            'weak_downtrend': -1, 
            'strong_downtrend': -2,
            'unknown': 0  # Default value for any unknown categories
        }
        volatility_regime_map = {'low_volatility': -1, 'normal_volatility': 0, 'high_volatility': 1, 'unknown': 0}
        
        # Apply mappings to convert string categoricals to numeric
        for window in windows:
            if f'adx_regime_{window}' in result.columns and result[f'adx_regime_{window}'].dtype == 'object':
                result[f'adx_regime_{window}'] = result[f'adx_regime_{window}'].map(adx_regime_map).fillna(0)
            
            if f'regime_{window}' in result.columns and result[f'regime_{window}'].dtype == 'object':
                result[f'regime_{window}'] = result[f'regime_{window}'].map(regime_map).fillna(0)
        
        if 'volatility_regime' in result.columns and result['volatility_regime'].dtype == 'object':
            result['volatility_regime'] = result['volatility_regime'].map(volatility_regime_map).fillna(0)
        
        # Clean up temporary columns
        temp_cols = ['tr', 'plus_dm', 'minus_dm', 'log_return']
        result = result.drop(columns=temp_cols, errors='ignore')
        
        logger.info(f"Added {len(regime_cols)} market regime features")
        return result
    
    def add_volume_profile_features(self, df: pd.DataFrame, n_bins: int = 10, window: int = 100) -> pd.DataFrame:
        """
        Calculate volume profile features to identify high-volume price levels and
        volume distribution patterns.
        
        Args:
            df: DataFrame with OHLCV data
            n_bins: Number of price bins for volume profiling
            window: Rolling window size for volume profile calculation
            
        Returns:
            DataFrame with volume profile features
        """
        logger.info(f"Calculating volume profile features using {n_bins} price bins")
        
        # Check if dataframe is empty or missing required columns
        if df.empty or not all(col in df.columns for col in ['high', 'low', 'close', 'volume']):
            logger.warning("Missing data for volume profile calculation")
            return df
            
        # Create a copy to avoid modifying the original
        result = df.copy()
        
        # Function to calculate a volume profile in a given window
        def calculate_volume_profile(window_data, n_bins):
            # Skip if not enough data
            if len(window_data) < 10:
                return None
                
            # Get price range
            price_min = window_data['low'].min()
            price_max = window_data['high'].max()
            
            # Skip if no price range
            if price_max <= price_min:
                return None
                
            # Create price bins
            bin_edges = np.linspace(price_min, price_max, n_bins + 1)
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
            
            # Calculate volume per bin (approximate using VWAP within each candle)
            volumes_by_bin = np.zeros(n_bins)
            
            for _, row in window_data.iterrows():
                # Calculate average price for this candle
                avg_price = (row['high'] + row['low'] + row['close']) / 3
                
                # Find which bin this price belongs to
                bin_idx = max(0, min(n_bins - 1, int((avg_price - price_min) / (price_max - price_min) * n_bins)))
                
                # Add volume to this bin
                volumes_by_bin[bin_idx] += row['volume']
            
            return {
                'bin_centers': bin_centers,
                'volumes': volumes_by_bin,
                'price_min': price_min,
                'price_max': price_max
            }
        
        # Initialize columns
        result['poc_price'] = np.nan  # Point of Control (highest volume price)
        result['poc_distance_pct'] = np.nan  # Distance from current price to POC
        result['volume_above_poc'] = np.nan  # % of volume above POC
        result['volume_below_poc'] = np.nan  # % of volume below POC
        result['volume_distribution_skew'] = np.nan  # Skewness of volume distribution
        result['volume_at_price_ratio'] = np.nan  # Ratio of volume at current price to average
        
        # For Value Area (70% of volume distribution)
        result['value_area_high'] = np.nan
        result['value_area_low'] = np.nan
        result['in_value_area'] = False
        result['value_area_width_pct'] = np.nan
        
        # For each point, calculate the volume profile of the preceding window
        for i in range(window, len(result)):
            # Get window data
            window_data = result.iloc[i-window:i]
            
            # Calculate volume profile
            profile = calculate_volume_profile(window_data, n_bins)
            
            if profile is None:
                continue
                
            # Find Point of Control (price level with highest volume)
            poc_idx = np.argmax(profile['volumes'])
            poc_price = profile['bin_centers'][poc_idx]
            
            # Current price
            current_price = result.iloc[i]['close']
            
            # Store Point of Control price
            result.iloc[i, result.columns.get_loc('poc_price')] = poc_price
            
            # Calculate distance from current price to POC as percentage
            poc_distance_pct = (poc_price - current_price) / current_price * 100
            result.iloc[i, result.columns.get_loc('poc_distance_pct')] = poc_distance_pct
            
            # Calculate volume distribution statistics
            total_volume = np.sum(profile['volumes'])
            
            if total_volume > 0:
                # Volume above and below POC as percentage
                volume_above_poc = np.sum(profile['volumes'][poc_idx+1:]) / total_volume * 100
                volume_below_poc = np.sum(profile['volumes'][:poc_idx]) / total_volume * 100
                
                result.iloc[i, result.columns.get_loc('volume_above_poc')] = volume_above_poc
                result.iloc[i, result.columns.get_loc('volume_below_poc')] = volume_below_poc
                
                # Calculate distribution skewness
                # Positive skew = more volume below POC, negative skew = more volume above POC
                volume_distribution_skew = (volume_below_poc - volume_above_poc) / 100
                result.iloc[i, result.columns.get_loc('volume_distribution_skew')] = volume_distribution_skew
                
                # Find current price bin
                current_bin_idx = max(0, min(n_bins - 1, 
                                            int((current_price - profile['price_min']) / 
                                                (profile['price_max'] - profile['price_min']) * n_bins)))
                
                # Calculate volume at current price relative to average
                if current_bin_idx < len(profile['volumes']):
                    current_bin_volume = profile['volumes'][current_bin_idx]
                    avg_bin_volume = total_volume / n_bins
                    
                    volume_at_price_ratio = current_bin_volume / avg_bin_volume if avg_bin_volume > 0 else 0
                    result.iloc[i, result.columns.get_loc('volume_at_price_ratio')] = volume_at_price_ratio
                
                # Calculate Value Area (70% of volume)
                # Start from POC and expand outward until 70% of volume is captured
                target_volume = total_volume * 0.7
                current_volume = profile['volumes'][poc_idx]
                
                # Initialize upper and lower bounds
                upper_idx = poc_idx
                lower_idx = poc_idx
                
                # Expand outward
                while current_volume < target_volume and (upper_idx < n_bins - 1 or lower_idx > 0):
                    # Decide whether to go up or down
                    up_volume = profile['volumes'][upper_idx + 1] if upper_idx < n_bins - 1 else 0
                    down_volume = profile['volumes'][lower_idx - 1] if lower_idx > 0 else 0
                    
                    if up_volume >= down_volume and upper_idx < n_bins - 1:
                        # Go up
                        upper_idx += 1
                        current_volume += up_volume
                    elif lower_idx > 0:
                        # Go down
                        lower_idx -= 1
                        current_volume += down_volume
                
                # Set Value Area High and Low
                value_area_high = profile['bin_centers'][upper_idx]
                value_area_low = profile['bin_centers'][lower_idx]
                
                result.iloc[i, result.columns.get_loc('value_area_high')] = value_area_high
                result.iloc[i, result.columns.get_loc('value_area_low')] = value_area_low
                
                # Check if current price is inside Value Area
                in_value_area = value_area_low <= current_price <= value_area_high
                result.iloc[i, result.columns.get_loc('in_value_area')] = in_value_area
                
                # Calculate Value Area width as percentage of current price
                value_area_width_pct = (value_area_high - value_area_low) / current_price * 100
                result.iloc[i, result.columns.get_loc('value_area_width_pct')] = value_area_width_pct
        
        # Fill NaN values for volume profile features
        vol_profile_cols = [
            'poc_price', 'poc_distance_pct', 'volume_above_poc', 'volume_below_poc',
            'volume_distribution_skew', 'volume_at_price_ratio', 
            'value_area_high', 'value_area_low', 'value_area_width_pct'
        ]
        
        for col in vol_profile_cols:
            # Forward fill only
            result[col] = result[col].fillna(method='ffill')
        
        logger.info(f"Added {len(vol_profile_cols) + 1} volume profile features")
        return result
    
    def add_intermarket_correlation_features(self, df: pd.DataFrame, symbol: str = None, 
                                            correlation_windows: list = [24, 48, 168]) -> pd.DataFrame:
        """
        Fix #25: Add BTC and ETH correlation features for better market context
        
        Most crypto assets are highly correlated with BTC and ETH movements.
        This adds rolling correlations and relative performance metrics.
        
        Args:
            df: DataFrame with OHLCV data
            symbol: Current token symbol (to avoid self-correlation)
            correlation_windows: Rolling windows for correlation calculation (hours)
            
        Returns:
            DataFrame with intermarket correlation features
        """
        logger.info("Adding intermarket correlation features (BTC/ETH)")
        
        # Skip if this is BTC or ETH itself
        if symbol and symbol.upper() in ['BTC', 'BITCOIN', 'ETH', 'ETHEREUM']:
            logger.info(f"Skipping intermarket features for {symbol} (self-correlation)")
            return df
        
        result = df.copy()
        
        try:
            # Get BTC and ETH data for the same time period
            from ..database.production_db import get_db_manager
            import asyncio
            
            # Get time range from current data
            start_time = df['timestamp'].min()
            end_time = df['timestamp'].max()
            
            # Fetch BTC and ETH data
            async def fetch_market_data():
                db_manager = await get_db_manager()
                
                # Get token IDs for BTC and ETH (these should be in your database)
                # You'll need to adjust these based on your actual token IDs
                btc_token_id = 59  # WBTC (Wrapped BTC on Solana)
                eth_token_id = 60  # WETH (Wrapped Ether on Solana)
                
                btc_data = await db_manager.get_ohlcv_data(
                    token_id=btc_token_id,
                    resolution='1H',
                    start_time=start_time,
                    end_time=end_time
                )
                
                eth_data = await db_manager.get_ohlcv_data(
                    token_id=eth_token_id,
                    resolution='1H',
                    start_time=start_time,
                    end_time=end_time
                )
                
                return btc_data, eth_data
            
            # Run async fetch - handle existing event loop
            try:
                # Check if we're already in an event loop
                loop = asyncio.get_running_loop()
                # If we're in an event loop, we need to run in a thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, fetch_market_data())
                    btc_data, eth_data = future.result()
            except RuntimeError:
                # No event loop running, safe to use asyncio.run
                btc_data, eth_data = asyncio.run(fetch_market_data())
            
            if not btc_data or not eth_data:
                logger.warning("Could not fetch BTC/ETH data for correlation features")
                # Add placeholder columns
                for window in correlation_windows:
                    result[f'btc_correlation_{window}h'] = 0.5
                    result[f'eth_correlation_{window}h'] = 0.5
                    result[f'btc_relative_strength_{window}h'] = 0.0
                    result[f'eth_relative_strength_{window}h'] = 0.0
                
                result['btc_eth_spread'] = 0.0
                result['market_regime_correlation'] = 0.5
                return result
            
            # Convert to DataFrames
            btc_df = pd.DataFrame([{
                'timestamp': r.time,
                'close': float(r.close),
                'volume': float(r.volume)
            } for r in btc_data])
            btc_df['timestamp'] = pd.to_datetime(btc_df['timestamp'])
            btc_df.set_index('timestamp', inplace=True)
            btc_df['returns'] = btc_df['close'].pct_change()
            
            eth_df = pd.DataFrame([{
                'timestamp': r.time,
                'close': float(r.close),
                'volume': float(r.volume)
            } for r in eth_data])
            eth_df['timestamp'] = pd.to_datetime(eth_df['timestamp'])
            eth_df.set_index('timestamp', inplace=True)
            eth_df['returns'] = eth_df['close'].pct_change()
            
            # Calculate returns for current asset
            result['returns'] = result['close'].pct_change()
            
            # Align data by timestamp
            result_indexed = result.set_index('timestamp')
            
            # Calculate correlation features for each window
            for window in correlation_windows:
                # Rolling correlation with BTC
                btc_corr = result_indexed['returns'].rolling(window).corr(btc_df['returns'])
                result[f'btc_correlation_{window}h'] = btc_corr.values
                
                # Rolling correlation with ETH
                eth_corr = result_indexed['returns'].rolling(window).corr(eth_df['returns'])
                result[f'eth_correlation_{window}h'] = eth_corr.values
                
                # Relative strength vs BTC (cumulative return difference)
                asset_cum_return = result_indexed['returns'].rolling(window).sum()
                btc_cum_return = btc_df['returns'].rolling(window).sum()
                btc_relative = (asset_cum_return - btc_cum_return).values
                result[f'btc_relative_strength_{window}h'] = btc_relative
                
                # Relative strength vs ETH
                eth_cum_return = eth_df['returns'].rolling(window).sum()
                eth_relative = (asset_cum_return - eth_cum_return).values
                result[f'eth_relative_strength_{window}h'] = eth_relative
            
            # BTC-ETH spread (market regime indicator)
            btc_eth_spread = (btc_df['returns'].rolling(24).mean() - 
                             eth_df['returns'].rolling(24).mean()).values
            result['btc_eth_spread'] = btc_eth_spread
            
            # Market regime based on BTC-ETH correlation
            # High correlation = risk-on, Low correlation = rotation
            btc_eth_corr = btc_df['returns'].rolling(48).corr(eth_df['returns'])
            result['market_regime_correlation'] = btc_eth_corr.values
            
            # Beta to BTC (market sensitivity)
            # Calculate rolling beta using 168h window
            btc_variance = btc_df['returns'].rolling(168).var()
            covariance = result_indexed['returns'].rolling(168).cov(btc_df['returns'])
            beta_btc = (covariance / btc_variance).values
            result['beta_to_btc'] = beta_btc
            
            # Beta to ETH
            eth_variance = eth_df['returns'].rolling(168).var()
            covariance_eth = result_indexed['returns'].rolling(168).cov(eth_df['returns'])
            beta_eth = (covariance_eth / eth_variance).values
            result['beta_to_eth'] = beta_eth
            
            # Market dominance indicator (are we following BTC or ETH more closely?)
            # Positive = following BTC, Negative = following ETH
            dominance = (abs(result[f'btc_correlation_24h']) - abs(result[f'eth_correlation_24h']))
            result['btc_eth_dominance'] = dominance
            
            # Fill NaN values
            correlation_cols = [col for col in result.columns if 'correlation' in col or 
                              'relative_strength' in col or 'beta' in col or 
                              'spread' in col or 'dominance' in col]
            
            for col in correlation_cols:
                # Forward fill then use neutral values
                result[col] = result[col].fillna(method='ffill')
                if 'correlation' in col or 'regime' in col:
                    result[col] = result[col].fillna(0.5)  # Neutral correlation
                else:
                    result[col] = result[col].fillna(0.0)  # Neutral relative strength
            
            # Drop temporary returns column if it wasn't there originally
            if 'returns' not in df.columns:
                result.drop('returns', axis=1, inplace=True)
            
            logger.info(f"Added {len(correlation_cols)} intermarket correlation features")
            
        except Exception as e:
            logger.error(f"Error adding intermarket correlation features: {e}")
            # Add placeholder columns on error
            for window in correlation_windows:
                result[f'btc_correlation_{window}h'] = 0.5
                result[f'eth_correlation_{window}h'] = 0.5
                result[f'btc_relative_strength_{window}h'] = 0.0
                result[f'eth_relative_strength_{window}h'] = 0.0
            
            result['btc_eth_spread'] = 0.0
            result['market_regime_correlation'] = 0.5
            result['beta_to_btc'] = 1.0
            result['beta_to_eth'] = 1.0
            result['btc_eth_dominance'] = 0.0
        
        return result
    
    def _handle_outliers_and_scaling(self, df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
        """
        Handle outliers and scaling more intelligently based on feature type
        
        Args:
            df: DataFrame with features
            feature_cols: List of feature column names
            
        Returns:
            DataFrame with handled outliers
        """
        # Make a copy to avoid SettingWithCopyWarning
        result = df.copy()
        
        # Categorize features by type
        price_based_features = ['open', 'high', 'low', 'close', 'vwap', 'sma_', 'ema_', 'kama_', 'hma_', 
                               'bb_upper', 'bb_lower', 'bb_middle', 'fib_', 'resistance_', 'support_',
                               'poc_price', 'value_area_high', 'value_area_low']
        
        ratio_features = ['rsi', 'stoch', 'willr', 'cci', 'cmf', 'pvt_oscillator', 'vol_efficiency',
                         'price_relative_position', 'candle_ratio', 'close_rel_position']
        
        percentage_features = ['returns', 'price_change', 'trend_pct', 'distance_pct', 'width_pct',
                              'volume_above_poc', 'volume_below_poc', 'win_rate']
        
        count_features = ['volume', 'social_volume', 'interactions', 'posts', 'contributors']
        
        binary_features = ['swing_high', 'swing_low', 'bullish_fvg', 'bearish_fvg', 'at_support', 
                          'at_resistance', 'in_value_area', 'breaks_resistance', 'breaks_support']
        
        for col in feature_cols:
            if col not in result.columns:
                continue
                
            # Skip non-numeric columns
            if not pd.api.types.is_numeric_dtype(result[col]):
                continue
            
            # Determine feature type
            feature_type = None
            
            # Check if it's a binary feature
            if col in binary_features or result[col].nunique() <= 2:
                feature_type = 'binary'
            # Check if it's a price-based feature
            elif any(pattern in col for pattern in price_based_features):
                feature_type = 'price'
            # Check if it's a ratio feature (typically 0-100 or 0-1)
            elif any(pattern in col for pattern in ratio_features):
                feature_type = 'ratio'
            # Check if it's a percentage feature
            elif any(pattern in col for pattern in percentage_features):
                feature_type = 'percentage'
            # Check if it's a count feature
            elif any(pattern in col for pattern in count_features):
                feature_type = 'count'
            else:
                feature_type = 'unknown'
            
            # Apply appropriate handling based on feature type
            if feature_type == 'binary':
                # Binary features don't need outlier handling
                result.loc[:, col] = result[col].fillna(0).astype(int)
                
            elif feature_type == 'price':
                # Price features: use log transformation to reduce scale
                # Only apply to positive values
                mask = result[col] > 0
                if mask.any():
                    result.loc[mask, col] = np.log1p(result.loc[mask, col])
                result.loc[:, col] = result[col].fillna(0)
                
            elif feature_type == 'ratio':
                # Ratio features: clip to expected range
                if 'rsi' in col or 'stoch' in col:
                    result.loc[:, col] = result[col].clip(0, 100)
                elif 'willr' in col:
                    result.loc[:, col] = result[col].clip(-100, 0)
                else:
                    result.loc[:, col] = result[col].clip(-1, 1)
                result.loc[:, col] = result[col].fillna(0)
                
            elif feature_type == 'percentage':
                # Percentage features: use tanh to compress extreme values
                result.loc[:, col] = np.tanh(result[col] / 100) * 100  # Compress while maintaining scale
                result.loc[:, col] = result[col].fillna(0)
                
            elif feature_type == 'count':
                # Count features: use log transformation
                result.loc[:, col] = np.log1p(result[col])
                result.loc[:, col] = result[col].fillna(0)
                
            else:
                # Unknown features: use robust scaling (IQR-based)
                q25 = result[col].quantile(0.25)
                q75 = result[col].quantile(0.75)
                iqr = q75 - q25
                
                if iqr > 0:
                    # Winsorize at 3 IQRs from quartiles
                    lower_bound = q25 - 3 * iqr
                    upper_bound = q75 + 3 * iqr
                    result.loc[:, col] = result[col].clip(lower_bound, upper_bound)
                
                result.loc[:, col] = result[col].fillna(0)
        
        return result

    def _add_placeholder_social_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add placeholder social features to maintain consistency when social data is missing"""
        # Add placeholder columns for social data
        df['sentiment'] = np.nan
        df['social_score'] = np.nan
        df['social_volume'] = np.nan
        df['social_impact_score'] = np.nan
        df['social_contributors_active'] = np.nan
        df['social_contributors_created'] = np.nan
        df['social_interactions'] = np.nan
        df['posts_active'] = np.nan
        df['posts_created'] = np.nan
        df['spam'] = np.nan
        df['galaxy_score'] = np.nan
        df['social_dominance'] = np.nan
        
        return df

    async def prepare_inference_ready_data(
        self, 
        token_id: int, 
        start_time: datetime, 
        end_time: datetime, 
        symbol: str = None,
        db_manager: Optional['ProductionDBManager'] = None  # Add optional db_manager parameter
    ) -> Optional[pd.DataFrame]:
        """
        CLEAN INTERFACE: Prepare inference-ready data using proven training pipeline
        
        This method provides the EXACT same processing as training but for live inference.
        Returns a clean DataFrame ready for prepare_ml_data() call.
        
        Args:
            token_id: Database token ID
            start_time: Start time for data fetch  
            end_time: End time for data fetch
            symbol: Token symbol for social data (optional)
            db_manager: Optional database manager to use (for thread safety)
            
        Returns:
            Clean DataFrame with all features engineered, ready for prepare_ml_data()
        """
        logger.info(f"Preparing inference-ready data for token {token_id} from {start_time} to {end_time}")
        
        try:
            # 1. Fetch OHLCV data from database
            # Use provided db_manager or get the singleton instance
            if db_manager is None:
                from ..database.production_db import get_db_manager
                db_manager = await get_db_manager()
            
            # Get OHLCV data using the same method as training pipeline
            ohlcv_data = await db_manager.get_ohlcv_data(
                token_id=token_id,
                resolution='1H',
                start_time=start_time,
                end_time=end_time
            )
            
            if not ohlcv_data or len(ohlcv_data) < 50:  # Need sufficient data
                logger.warning(f"Insufficient OHLCV data for token {token_id}: {len(ohlcv_data) if ohlcv_data else 0} records")
                return None
            
            # 2. Convert to DataFrame (same format as training)
            data_records = []
            for record in ohlcv_data:
                data_records.append({
                    'timestamp': record.time,
                    'open': float(record.open),
                    'high': float(record.high),
                    'low': float(record.low),
                    'close': float(record.close),
                    'volume': float(record.volume)
                })
            
            df = pd.DataFrame(data_records)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.sort_values('timestamp', inplace=True)
            
            logger.debug(f"Loaded {len(df)} OHLCV records for token {token_id}")
            
            # 3. Apply the EXACT same feature engineering pipeline as training
            
            # Calculate technical indicators
            df = self.calculate_technical_indicators(df)
            
            # Add Fair Value Gaps
            df = self.add_fair_value_gaps(df)
            
            # Add Volatility-of-Volatility (VoV) features
            df = self.add_volatility_of_volatility(df)
            
            # Add cyclical time features
            df = self.add_time_cyclical_features(df)
            
            # Add Chaikin Money Flow and Price-Volume Trend
            df = self.add_money_flow_features(df)
            
            # Add range-based realized volatility
            df = self.add_realized_volatility(df)
            
            # Add adaptive moving averages (KAMA, Hull MA)
            df = self.add_adaptive_moving_averages(df)
            
            # Add multi-timeframe features
            df = self.add_multi_timeframe_features(df, '1H')
            
            # Add candlestick patterns
            df = self.add_candlestick_patterns(df)
            
            # Add price action swing points
            df = self.add_price_action_swing_points(df)
            
            # Add statistical features (Hurst exponent, moments)
            df = self.add_statistical_features(df)
            
            # Add advanced momentum features with divergence detection
            df = self.add_advanced_momentum_features(df)
            
            # Add support and resistance zones
            df = self.add_support_resistance_zones(df)
            
            # Add market regime features
            df = self.add_market_regime_features(df)
            
            # Add volume profile features
            df = self.add_volume_profile_features(df)
            
            # Add intermarket correlation features (BTC/ETH)
            df = self.add_intermarket_correlation_features(df, symbol)
            
            # 4. Add social data if symbol provided
            if symbol:
                try:
                    # Calculate days needed based on timespan
                    days_needed = (end_time - start_time).days + 1
                    social_df = await self.fetch_sentiment_data_timescale(symbol, days_needed, db_manager)
                    
                    if not social_df.empty:
                        # Merge social data with price data
                        df = self.merge_data(df, social_df)
                        # Calculate social indicators on merged data
                        df = self.calculate_social_indicators(df)
                        logger.debug(f"Added social data for {symbol}")
                    else:
                        # Add placeholder social features for consistency
                        df = self._add_placeholder_social_features(df)
                        logger.debug(f"No social data for {symbol}, using placeholders")
                        
                except Exception as e:
                    logger.warning(f"Social data processing failed for {symbol}: {e}")
                    df = self._add_placeholder_social_features(df)
            else:
                # Add placeholder social features for consistency
                df = self._add_placeholder_social_features(df)
            
            # 5. Final cleanup
            df = df.fillna(method='ffill').fillna(method='bfill').fillna(0)
            
            logger.info(f"Successfully prepared inference data for token {token_id}: {len(df)} records, {len(df.columns)} features")
            
            return df
            
        except Exception as e:
            logger.error(f"Error preparing inference data for token {token_id}: {e}")
            return None

    def save_scalers(self, symbol: str, model_version: str) -> None:
        """Save fitted scalers to disk for use in production"""
        import pickle
        
        # Create scalers directory if it doesn't exist
        scalers_dir = os.path.join(self.data_dir, "scalers")
        os.makedirs(scalers_dir, exist_ok=True)
        
        # Save price scaler
        price_scaler_path = os.path.join(scalers_dir, f"{symbol}_{model_version}_price_scaler.pkl")
        with open(price_scaler_path, 'wb') as f:
            pickle.dump(self.price_scaler, f)
        logger.info(f"Saved price scaler to {price_scaler_path}")
        
        # Save feature scaler
        feature_scaler_path = os.path.join(scalers_dir, f"{symbol}_{model_version}_feature_scaler.pkl")
        with open(feature_scaler_path, 'wb') as f:
            pickle.dump(self.feature_scaler, f)
        logger.info(f"Saved feature scaler to {feature_scaler_path}")
    
    def load_scalers(self, symbol: str, model_version: str) -> bool:
        """Load fitted scalers from disk for production use"""
        import pickle
        
        scalers_dir = os.path.join(self.data_dir, "scalers")
        
        # Load price scaler
        price_scaler_path = os.path.join(scalers_dir, f"{symbol}_{model_version}_price_scaler.pkl")
        if os.path.exists(price_scaler_path):
            with open(price_scaler_path, 'rb') as f:
                self.price_scaler = pickle.load(f)
            logger.info(f"Loaded price scaler from {price_scaler_path}")
        else:
            logger.warning(f"Price scaler not found at {price_scaler_path}")
            return False
        
        # Load feature scaler
        feature_scaler_path = os.path.join(scalers_dir, f"{symbol}_{model_version}_feature_scaler.pkl")
        if os.path.exists(feature_scaler_path):
            with open(feature_scaler_path, 'rb') as f:
                self.feature_scaler = pickle.load(f)
            logger.info(f"Loaded feature scaler from {feature_scaler_path}")
        else:
            logger.warning(f"Feature scaler not found at {feature_scaler_path}")
            return False
        
        return True
