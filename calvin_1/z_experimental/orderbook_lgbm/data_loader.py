"""
Data loader for Orderbook LGBM model

Loads orderbook and candle data from TimescaleDB database.
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple, List
from datetime import datetime, timedelta
import logging
from pathlib import Path
import sqlalchemy

from .config import get_config

logger = logging.getLogger(__name__)

class DataLoader:
    """Loads orderbook and candle data from database"""

    def __init__(self):
        self.config = get_config()
        self._engine = None

        # Symbol mapping for orderbook tables (different from ohlcv table)
        self.symbol_mapping = {
            'Bonk': 'BONK-USD',  # ohlcv symbol -> orderbook symbol
            'SOL': 'SOL-USD',
            'BTC': 'BTC-USD',
            'ETH': 'ETH-USD',
            'JUP': 'JUP-USD',
            'FARTCOIN': 'FARTCOIN-USD',
            'BONK': 'BONK-USD',
        }

    @property
    def engine(self):
        """Get SQLAlchemy engine"""
        if self._engine is None:
            self._engine = sqlalchemy.create_engine(self.config.get_pandas_connection_string())
        return self._engine

    def get_orderbook_symbol(self, symbol: str) -> str:
        """Get orderbook symbol name (may differ from ohlcv symbol)"""
        return self.symbol_mapping.get(symbol, symbol)

    def load_candles(self,
                     symbol: str,
                     timeframe: str = '1m',
                     start_ts: Optional[str] = None,
                     end_ts: Optional[str] = None) -> pd.DataFrame:
        """
        Load candle data from ohlcv table

        Args:
            symbol: Token symbol (e.g., 'SOL')
            timeframe: Timeframe (e.g., '1m', '5m', '1h')
            start_ts: Start timestamp string (ISO format)
            end_ts: End timestamp string (ISO format)

        Returns:
            DataFrame with OHLCV data indexed by timestamp
        """
        start_ts = start_ts or self.config.default_start_ts
        end_ts = end_ts or self.config.default_end_ts

        query = f"""
        SELECT
            o.{self.config.features.time_col_candles} as timestamp,
            o.{self.config.features.open_col} as open,
            o.{self.config.features.high_col} as high,
            o.{self.config.features.low_col} as low,
            o.{self.config.features.close_col} as close,
            o.{self.config.features.volume_col} as volume,
            t.{self.config.features.symbol_col} as symbol
        FROM {self.config.features.candles_table} o
        JOIN {self.config.features.tokens_table} t ON o.{self.config.features.token_id_col} = t.{self.config.features.token_id_col}
        WHERE LOWER(t.{self.config.features.symbol_col}) = LOWER(%s)
          AND o.{self.config.features.resolution_col} = %s
          AND o.{self.config.features.time_col_candles} >= %s
          AND o.{self.config.features.time_col_candles} < %s
        ORDER BY o.{self.config.features.time_col_candles}
        """

        # Use raw psycopg2 connection to avoid SQLAlchemy parameter issues
        conn = self.config.get_db_connection()
        try:
            df = pd.read_sql_query(
                query,
                conn,
                params=(symbol, timeframe, start_ts, end_ts)
            )
        finally:
            conn.close()

        if df.empty:
            logger.warning(f"No candle data found for {symbol} {timeframe} between {start_ts} and {end_ts}")
            return pd.DataFrame()

        # Set timestamp as index and ensure it's datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()

        logger.info(f"Loaded {len(df)} candle records for {symbol} {timeframe}")
        return df

    def load_top_of_book(self,
                        symbol: str,
                        start_ts: Optional[str] = None,
                        end_ts: Optional[str] = None,
                        freq: str = '1S',
                        use_symbol_mapping: bool = True) -> pd.DataFrame:
        """
        Load top-of-book data from tob_1s materialized view

        Args:
            symbol: Token symbol
            start_ts: Start timestamp string
            end_ts: End timestamp string
            freq: Resampling frequency if needed
            use_symbol_mapping: Whether to map symbol name for orderbook tables

        Returns:
            DataFrame with best_bid, best_ask indexed by timestamp
        """
        start_ts = start_ts or self.config.default_start_ts
        end_ts = end_ts or self.config.default_end_ts

        # Use symbol mapping for orderbook tables if requested
        query_symbol = self.get_orderbook_symbol(symbol) if use_symbol_mapping else symbol

        query = f"""
        SELECT
            {self.config.features.tob_time_col} as timestamp,
            {self.config.features.best_bid_col} as best_bid,
            {self.config.features.best_ask_col} as best_ask,
            {self.config.features.tob_symbol_col} as symbol
        FROM {self.config.features.tob_table}
        WHERE {self.config.features.tob_symbol_col} = %s
          AND {self.config.features.tob_time_col} >= %s
          AND {self.config.features.tob_time_col} < %s
        ORDER BY {self.config.features.tob_time_col}
        """

        # Use raw psycopg2 connection to avoid SQLAlchemy parameter issues
        conn = self.config.get_db_connection()
        try:
            df = pd.read_sql_query(
                query,
                conn,
                params=(query_symbol, start_ts, end_ts)
            )
        finally:
            conn.close()

        if df.empty:
            logger.warning(f"No top-of-book data found for {symbol} between {start_ts} and {end_ts}")
            return pd.DataFrame()

        # Set timestamp as index
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()

        # Resample if requested frequency is different from 1S
        if freq != '1S':
            df = df.resample(freq).agg({
                'best_bid': 'last',
                'best_ask': 'last',
                'symbol': 'last'
            }).dropna()

        logger.info(f"Loaded {len(df)} top-of-book records for {symbol}")
        return df

    def load_orderbook_microstructure(self,
                                     symbol: str,
                                     start_ts: Optional[str] = None,
                                     end_ts: Optional[str] = None) -> pd.DataFrame:
        """
        Load orderbook microstructure data from lbu_1m materialized view

        Args:
            symbol: Token symbol
            start_ts: Start timestamp string
            end_ts: End timestamp string

        Returns:
            DataFrame with orderbook microstructure features indexed by timestamp
        """
        start_ts = start_ts or self.config.default_start_ts
        end_ts = end_ts or self.config.default_end_ts

        query = f"""
        SELECT
            {self.config.features.lbu_time_col} as timestamp,
            {self.config.features.lbu_best_bid_col} as lb_best_bid,
            {self.config.features.lbu_best_ask_col} as lb_best_ask,
            {self.config.features.lbu_imbalance_col} as lb_imbalance,
            {self.config.features.lbu_spread_bps_col} as lb_spread_bps,
            {self.config.features.lbu_buy_vol_col} as lb_buy_vol,
            {self.config.features.lbu_sell_vol_col} as lb_sell_vol,
            {self.config.features.lbu_symbol_col} as symbol
        FROM {self.config.features.lbu_table}
        WHERE {self.config.features.lbu_symbol_col} = %s
          AND {self.config.features.lbu_time_col} >= %s
          AND {self.config.features.lbu_time_col} < %s
        ORDER BY {self.config.features.lbu_time_col}
        """

        # Use raw psycopg2 connection to avoid SQLAlchemy parameter issues
        conn = self.config.get_db_connection()
        try:
            df = pd.read_sql_query(
                query,
                conn,
                params=(symbol, start_ts, end_ts)
            )
        finally:
            conn.close()

        if df.empty:
            logger.warning(f"No orderbook microstructure data found for {symbol} between {start_ts} and {end_ts}")
            return pd.DataFrame()

        # Set timestamp as index
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()

        logger.info(f"Loaded {len(df)} orderbook microstructure records for {symbol}")
        return df

    def load_orderbook_snapshot(self,
                               symbol: str,
                               start_ts: Optional[str] = None,
                               end_ts: Optional[str] = None) -> pd.DataFrame:
        """
        Load orderbook data from lbu_1m microstructure table

        This provides orderbook state at each minute boundary for alignment with candles.
        Uses lbu_1m since tob_1s appears to be empty.

        Args:
            symbol: Token symbol (ohlcv symbol, will be mapped to orderbook symbol)
            start_ts: Start timestamp string
            end_ts: End timestamp string

        Returns:
            DataFrame with orderbook state per minute, indexed by timestamp
        """
        # Map symbol to orderbook naming convention
        orderbook_symbol = self.get_orderbook_symbol(symbol)
        logger.debug(f"Loading orderbook data for {symbol} -> {orderbook_symbol}")

        # Load from lbu_1m microstructure data
        lbu_df = self.load_orderbook_microstructure(orderbook_symbol, start_ts, end_ts)

        if lbu_df.empty:
            logger.warning(f"No orderbook microstructure data found for {symbol} ({orderbook_symbol})")
            return pd.DataFrame()

        # Extract top-of-book prices from microstructure data
        # lbu_1m has lb_best_bid and lb_best_ask columns
        tob_df = lbu_df[['lb_best_bid', 'lb_best_ask']].copy()

        # Rename columns for consistency
        tob_df = tob_df.rename(columns={
            'lb_best_bid': 'bid_px_1',
            'lb_best_ask': 'ask_px_1'
        })

        # Keep microstructure features too
        microstructure_cols = ['lb_imbalance', 'lb_spread_bps', 'lb_buy_vol', 'lb_sell_vol']
        for col in microstructure_cols:
            if col in lbu_df.columns:
                tob_df[col] = lbu_df[col]

        return tob_df

    def load_combined_data(self,
                          symbol: str,
                          timeframe: str = '1m',
                          start_ts: Optional[str] = None,
                          end_ts: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Load both candles and orderbook data for a symbol

        Args:
            symbol: Token symbol
            timeframe: Candle timeframe
            start_ts: Start timestamp
            end_ts: End timestamp

        Returns:
            Tuple of (candles_df, orderbook_df)
        """
        candles_df = self.load_candles(symbol, timeframe, start_ts, end_ts)
        orderbook_df = self.load_orderbook_snapshot(symbol, start_ts, end_ts)

        return candles_df, orderbook_df

    def cache_data(self,
                   df: pd.DataFrame,
                   cache_path: Path,
                   compression: str = 'parquet') -> None:
        """
        Cache DataFrame to disk

        Args:
            df: DataFrame to cache
            cache_path: Path to save to
            compression: Compression format ('parquet', 'feather', 'csv')
        """
        cache_path.parent.mkdir(exist_ok=True)

        if compression == 'parquet':
            df.to_parquet(cache_path.with_suffix('.parquet'), index=True)
        elif compression == 'feather':
            df.reset_index().to_feather(cache_path.with_suffix('.feather'))
        elif compression == 'csv':
            df.to_csv(cache_path.with_suffix('.csv'), index=True)
        else:
            raise ValueError(f"Unsupported compression format: {compression}")

        logger.info(f"Cached {len(df)} rows to {cache_path}")

    def load_cached_data(self, cache_path: Path) -> pd.DataFrame:
        """
        Load cached DataFrame from disk

        Args:
            cache_path: Path to load from

        Returns:
            Cached DataFrame
        """
        if cache_path.with_suffix('.parquet').exists():
            return pd.read_parquet(cache_path.with_suffix('.parquet'))
        elif cache_path.with_suffix('.feather').exists():
            df = pd.read_feather(cache_path.with_suffix('.feather'))
            return df.set_index(df.columns[0]) if 'timestamp' in df.columns[0].lower() else df
        elif cache_path.with_suffix('.csv').exists():
            df = pd.read_csv(cache_path.with_suffix('.csv'), index_col=0, parse_dates=True)
            return df
        else:
            raise FileNotFoundError(f"No cached data found at {cache_path}")

def get_data_loader() -> DataLoader:
    """Get DataLoader instance"""
    return DataLoader()

# Convenience functions
def load_candles(symbol: str, timeframe: str = '1m', start_ts: Optional[str] = None, end_ts: Optional[str] = None) -> pd.DataFrame:
    """Convenience function to load candle data"""
    loader = get_data_loader()
    return loader.load_candles(symbol, timeframe, start_ts, end_ts)

def load_orderbook_snapshot(symbol: str, start_ts: Optional[str] = None, end_ts: Optional[str] = None) -> pd.DataFrame:
    """Convenience function to load orderbook snapshot data"""
    loader = get_data_loader()
    return loader.load_orderbook_snapshot(symbol, start_ts, end_ts)
