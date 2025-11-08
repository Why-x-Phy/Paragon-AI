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

        # Base/quote mapping for new CoinAPI-based orderbook (exchange/market/base/quote)
        # Default exchange/market if not specified: BINANCE/SPOT
        # Default quote: USDT for majors, otherwise USDC where appropriate
        self.base_quote_mapping = {
            'BTC': ('BTC', 'USDT'),
            'ETH': ('ETH', 'USDT'),
            'SOL': ('SOL', 'USDC'),
            'JUP': ('JUP', 'USDC'),
            'BONK': ('BONK', 'USDC'),
            'FARTCOIN': ('FARTCOIN', 'USDC'),
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

    def get_orderbook_keys(self, symbol: str):
        """
        Get (exchange, market_type, base, quote) for querying ob_* views.
        Defaults to (BINANCE, SPOT, SYMBOL, USDT/USDC) if not mapped.
        """
        sym = (symbol or "").upper()
        base, quote = self.base_quote_mapping.get(sym, (sym, 'USDT'))
        return 'BINANCE', 'SPOT', base, quote

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
                         freq: str = '1S') -> pd.DataFrame:
        """
        Load top-of-book data from ob_tob_1s materialized view (new pipeline).
        """
        start_ts = start_ts or self.config.default_start_ts
        end_ts = end_ts or self.config.default_end_ts

        exchange, market_type, base, quote = self.get_orderbook_keys(symbol)

        query = """
        SELECT
          bucket AS timestamp,
          best_bid,
          best_ask
        FROM ob_tob_1s
        WHERE exchange = %s AND base = %s AND quote = %s
          AND bucket >= %s AND bucket < %s
        ORDER BY bucket
        """

        df = pd.read_sql_query(
            query,
            self.engine,
            params=(exchange, base, quote, start_ts, end_ts)
        )

        if df.empty:
            logger.warning(f"No top-of-book data found for {symbol} {exchange}/{base}-{quote} between {start_ts} and {end_ts}")
            return pd.DataFrame()

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()

        if freq and freq != '1S':
            df = df.resample(freq).agg({
                'best_bid': 'last',
                'best_ask': 'last',
            }).dropna()

        logger.info(f"Loaded {len(df)} top-of-book records for {symbol}")
        return df

    def load_orderbook_microstructure(self,
                                     symbol: str,
                                     start_ts: Optional[str] = None,
                                     end_ts: Optional[str] = None) -> pd.DataFrame:
        """
        Load orderbook microstructure data from ob_depth_1m_k20 materialized view (new pipeline).

        Args:
            symbol: Token symbol
            start_ts: Start timestamp string
            end_ts: End timestamp string

        Returns:
            DataFrame with orderbook microstructure features indexed by timestamp
        """
        start_ts = start_ts or self.config.default_start_ts
        end_ts = end_ts or self.config.default_end_ts

        exchange, market_type, base, quote = self.get_orderbook_keys(symbol)

        query = """
        SELECT
          bucket AS timestamp,
          med_bid_px    AS lb_best_bid,
          med_ask_px    AS lb_best_ask,
          imbalance_k   AS lb_imbalance,
          spread_bps    AS lb_spread_bps,
          bid_vol_k     AS lb_buy_vol,
          ask_vol_k     AS lb_sell_vol
        FROM ob_depth_1m_k20
        WHERE exchange = %s AND base = %s AND quote = %s
          AND bucket >= %s AND bucket < %s
        ORDER BY bucket
        """

        df = pd.read_sql_query(
            query,
            self.engine,
            params=(exchange, base, quote, start_ts, end_ts)
        )

        if df.empty:
            logger.warning(f"No orderbook microstructure data found for {symbol} {exchange}/{base}-{quote} between {start_ts} and {end_ts}")
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
        Load orderbook snapshot and microstructure (minute-level) from ob_depth_1m_k20 view.

        This provides orderbook state at each minute boundary for alignment with candles.

        Args:
            symbol: Token symbol (ohlcv symbol, will be mapped to orderbook symbol)
            start_ts: Start timestamp string
            end_ts: End timestamp string

        Returns:
            DataFrame with orderbook state per minute, indexed by timestamp
        """
        logger.debug(f"Loading orderbook data for {symbol}")
        lbu_df = self.load_orderbook_microstructure(symbol, start_ts, end_ts)

        if lbu_df.empty:
            logger.warning(f"No orderbook microstructure data found for {symbol}")
            return pd.DataFrame()

        # Extract top-of-book prices from microstructure data
        # ob_depth_1m_k20 has lb_best_bid and lb_best_ask columns (mapped)
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

    def load_orderbook_levels_snapshots(self,
                                        symbol: str,
                                        date: str) -> pd.DataFrame:
        """
        Load full per-snapshot L1..L20 bids/asks for a single day from orderbook_levels.

        Returns a DataFrame indexed by timestamp (ts) with columns:
        bid_px_1..20, bid_sz_1..20, ask_px_1..20, ask_sz_1..20
        """
        exchange, market_type, base, quote = self.get_orderbook_keys(symbol)
        start_ts = f"{date}T00:00:00Z"
        end_dt = pd.to_datetime(date) + pd.Timedelta(days=1)
        end_ts = f"{end_dt.strftime('%Y-%m-%d')}T00:00:00Z"

        query = """
        SELECT ts, side, level, price, size
        FROM orderbook_levels
        WHERE exchange = %s AND base = %s AND quote = %s
          AND ts >= %s AND ts < %s
        ORDER BY ts
        """

        df = pd.read_sql_query(
            query,
            self.engine,
            params=(exchange, base, quote, start_ts, end_ts)
        )

        if df.empty:
            logger.warning(f"No orderbook_levels data for {symbol} {exchange}/{base}-{quote} on {date}")
            return pd.DataFrame()

        df['ts'] = pd.to_datetime(df['ts'])

        bids = df[df['side'] == True]
        asks = df[df['side'] == False]

        bid_px = bids.pivot(index='ts', columns='level', values='price')
        bid_px = bid_px.rename(columns=lambda k: f"bid_px_{int(k)}")
        bid_sz = bids.pivot(index='ts', columns='level', values='size')
        bid_sz = bid_sz.rename(columns=lambda k: f"bid_sz_{int(k)}")

        ask_px = asks.pivot(index='ts', columns='level', values='price')
        ask_px = ask_px.rename(columns=lambda k: f"ask_px_{int(k)}")
        ask_sz = asks.pivot(index='ts', columns='level', values='size')
        ask_sz = ask_sz.rename(columns=lambda k: f"ask_sz_{int(k)}")

        snap = pd.concat([bid_px, bid_sz, ask_px, ask_sz], axis=1).sort_index()
        snap = snap.dropna(how='all')
        return snap

    def load_tob_mid_1s(self,
                        symbol: str,
                        start_ts: str,
                        end_ts: str) -> pd.DataFrame:
        """
        Load per-second mid price from ob_tob_1s for a time range.
        """
        exchange, market_type, base, quote = self.get_orderbook_keys(symbol)

        query = """
        SELECT bucket AS timestamp, best_bid, best_ask
        FROM ob_tob_1s
        WHERE exchange = %s AND base = %s AND quote = %s
          AND bucket >= %s AND bucket < %s
        ORDER BY bucket
        """

        df = pd.read_sql_query(
            query,
            self.engine,
            params=(exchange, base, quote, start_ts, end_ts)
        )

        if df.empty:
            return pd.DataFrame()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()
        df['mid'] = (df['best_bid'] + df['best_ask']) / 2.0
        return df[['mid']]

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
