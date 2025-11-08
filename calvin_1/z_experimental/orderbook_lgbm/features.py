"""
Feature engineering for Orderbook LGBM model

Creates minimal orderbook-derived features and target variable (next candle percent change).
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional, Dict, Any
import logging

from .config import get_config

logger = logging.getLogger(__name__)

class FeatureEngineer:
    """Engineers features from orderbook and candle data"""

    def __init__(self):
        self.config = get_config()

    def make_features(self,
                     candles_df: pd.DataFrame,
                     orderbook_df: pd.DataFrame,
                     params: Optional[Dict[str, Any]] = None,
                     target_type: str = 'regression') -> Tuple[pd.DataFrame, pd.Series]:
        """
        Create features and target from raw data

        Args:
            candles_df: OHLCV data indexed by timestamp
            orderbook_df: Orderbook data indexed by timestamp
            params: Feature engineering parameters
            target_type: 'regression' for raw returns, 'classification' for direction

        Returns:
            Tuple of (features_df, target_series)
        """
        params = params or {}

        if candles_df.empty or orderbook_df.empty:
            logger.warning("Empty input data provided")
            return pd.DataFrame(), pd.Series()

        # Align orderbook data to candle timestamps
        aligned_orderbook = self._align_orderbook_to_candles(orderbook_df, candles_df)

        # Create features
        features_df = self._create_orderbook_features(aligned_orderbook, params)
        # Add OHLCV-derived, level-free features
        ohlcv_features = self._create_ohlcv_features(candles_df, params)
        if not ohlcv_features.empty:
            features_df = features_df.join(ohlcv_features, how='left')

        # Create target (next candle percent change or direction)
        target_series = self._create_target(candles_df, target_type, params)

        # Align features and target
        X, y = self._align_features_target(features_df, target_series)

        # Remove rows with NaN
        valid_mask = ~(X.isna().any(axis=1) | y.isna())
        X_clean = X[valid_mask]
        y_clean = y[valid_mask]

        dropped_rows = len(X) - len(X_clean)
        if dropped_rows > 0:
            logger.info(f"Dropped {dropped_rows} rows with NaN values ({dropped_rows/len(X)*100:.1f}%)")

        logger.info(f"Created {len(X_clean)} feature rows with {X_clean.shape[1]} features")
        return X_clean, y_clean

    def _align_orderbook_to_candles(self,
                                   orderbook_df: pd.DataFrame,
                                   candles_df: pd.DataFrame) -> pd.DataFrame:
        """
        Align orderbook snapshots to candle close times

        For each candle close time t, use the last orderbook snapshot at or before t.
        """
        if orderbook_df.empty or candles_df.empty:
            return pd.DataFrame()

        # Get candle timestamps
        candle_times = candles_df.index

        # Reindex orderbook to candle times using forward fill (last known value)
        aligned = orderbook_df.reindex(candle_times, method='ffill')

        # Only keep rows where we have orderbook data
        aligned = aligned.dropna()

        logger.debug(f"Aligned orderbook data: {len(aligned)} rows from {len(orderbook_df)} original")
        return aligned

    def _create_orderbook_features(self,
                                  orderbook_df: pd.DataFrame,
                                  params: Dict[str, Any]) -> pd.DataFrame:
        """
        Create comprehensive orderbook-derived features

        Features include:
        - Basic price/spread features
        - Momentum and trend features
        - Volatility features
        - Volume imbalance features
        - Microstructure features
        - Time-based features
        """
        if orderbook_df.empty:
            return pd.DataFrame()

        features = pd.DataFrame(index=orderbook_df.index)

        # Basic price and spread features
        if 'bid_px_1' in orderbook_df.columns and 'ask_px_1' in orderbook_df.columns:
            bid_px = orderbook_df['bid_px_1']
            ask_px = orderbook_df['ask_px_1']

            # Core price features
            features['mid_price'] = (bid_px + ask_px) / 2
            features['spread'] = ask_px - bid_px
            features['rel_spread'] = features['spread'] / features['mid_price']
            features['spread_bps'] = (features['spread'] / features['mid_price']) * 10000

            # Price levels relative to mid
            features['bid_to_mid'] = (bid_px - features['mid_price']) / features['mid_price']
            features['ask_to_mid'] = (ask_px - features['mid_price']) / features['mid_price']

            # Microprice (volume-weighted inside quote) if sizes available
            if 'bid_sz_1' in orderbook_df.columns and 'ask_sz_1' in orderbook_df.columns:
                bid_sz = orderbook_df['bid_sz_1']
                ask_sz = orderbook_df['ask_sz_1']
                denom = (bid_sz + ask_sz).replace(0, np.nan)
                microprice = (ask_px * bid_sz + bid_px * ask_sz) / denom
                features['microprice'] = microprice.fillna(method='ffill')
                features['microprice_ret_1'] = features['microprice'].pct_change(1)

        # Depth imbalance features
        if 'bid_sz_1' in orderbook_df.columns and 'ask_sz_1' in orderbook_df.columns:
            bid_sz = orderbook_df['bid_sz_1']
            ask_sz = orderbook_df['ask_sz_1']

            features['depth_imbalance'] = (bid_sz - ask_sz) / (bid_sz + ask_sz + 1e-9)
            features['bid_ask_ratio'] = bid_sz / (ask_sz + 1e-9)
            features['total_depth'] = bid_sz + ask_sz
        else:
            features['depth_imbalance'] = 0.0
            features['bid_ask_ratio'] = 1.0
            features['total_depth'] = 0.0

        # Momentum and trend features (if mid_price available)
        if 'mid_price' in features.columns and params.get('include_momentum', True):
            mid_px = features['mid_price']

            # Multiple lag returns
            for lag in [1, 2, 5, 10, 20]:
                features[f'mid_ret_{lag}'] = mid_px.pct_change(lag)

            # Rolling statistics
            features['mid_rolling_mean_5'] = mid_px.rolling(5).mean()
            features['mid_rolling_std_5'] = mid_px.rolling(5).std()
            features['mid_rolling_mean_20'] = mid_px.rolling(20).mean()
            features['mid_rolling_std_20'] = mid_px.rolling(20).std()

            # Trend indicators
            features['mid_trend_5'] = (mid_px - mid_px.rolling(5).mean()) / mid_px.rolling(5).std()
            features['mid_momentum'] = mid_px / mid_px.shift(20) - 1

        # Spread momentum features
        if 'spread' in features.columns and params.get('include_spread_momentum', True):
            spread = features['spread']
            features['spread_ret_1'] = spread.pct_change(1)
            features['spread_rolling_std_10'] = spread.rolling(10).std()
            features['spread_zscore_20'] = (spread - spread.rolling(20).mean()) / (spread.rolling(20).std() + 1e-9)

        # Volume imbalance features (from microstructure data)
        if 'lb_buy_vol' in orderbook_df.columns and 'lb_sell_vol' in orderbook_df.columns:
            buy_vol = orderbook_df['lb_buy_vol']
            sell_vol = orderbook_df['lb_sell_vol']

            features['vol_imbalance'] = (buy_vol - sell_vol) / (buy_vol + sell_vol + 1e-9)
            features['buy_sell_ratio'] = buy_vol / (sell_vol + 1e-9)
            features['total_vol'] = buy_vol + sell_vol

            # Volume trends
            features['buy_vol_ret_1'] = buy_vol.pct_change(1)
            features['sell_vol_ret_1'] = sell_vol.pct_change(1)

        # Microstructure features from lbu_1m
        microstructure_cols = ['lb_imbalance', 'lb_spread_bps', 'lb_avg_buy_px', 'lb_avg_sell_px']
        for col in microstructure_cols:
            if col in orderbook_df.columns:
                features[col] = orderbook_df[col]

                # Add momentum for microstructure features
                if params.get('include_microstructure_momentum', True):
                    features[f'{col}_ret_1'] = orderbook_df[col].pct_change(1)

        # Approximate L1 depth proxies using available per-minute flow and spread
        if {'lb_buy_vol', 'lb_sell_vol', 'lb_spread_bps'}.issubset(orderbook_df.columns):
            buy_vol = orderbook_df['lb_buy_vol'].astype(float)
            sell_vol = orderbook_df['lb_sell_vol'].astype(float)
            spread_bps = orderbook_df['lb_spread_bps'].astype(float)

            # Liquidity proxy: tighter spread => larger proxy (avoid div by zero)
            liq_proxy = 1.0 / (np.abs(spread_bps).replace(0, np.nan) + 1.0)
            liq_proxy = liq_proxy.fillna(liq_proxy.median())

            # Scale per-minute flow to per-second and modulate by liquidity proxy
            bid_sz_1_proxy = (buy_vol / 60.0) * liq_proxy
            ask_sz_1_proxy = (sell_vol / 60.0) * liq_proxy

            features['bid_sz_1_proxy'] = bid_sz_1_proxy
            features['ask_sz_1_proxy'] = ask_sz_1_proxy
            features['total_depth_proxy'] = bid_sz_1_proxy + ask_sz_1_proxy
            features['depth_imbalance_proxy'] = (bid_sz_1_proxy - ask_sz_1_proxy) / (features['total_depth_proxy'] + 1e-9)
            features['bid_ask_ratio_proxy'] = bid_sz_1_proxy / (ask_sz_1_proxy + 1e-9)
            features['liq_proxy'] = liq_proxy

            # Add simple dynamics and normalization for proxies
            for base in ['bid_sz_1_proxy', 'ask_sz_1_proxy', 'total_depth_proxy', 'depth_imbalance_proxy', 'bid_ask_ratio_proxy', 'liq_proxy']:
                series = features[base]
                features[f'{base}_ret_1'] = series.pct_change(1)
                features[f'{base}_z_50'] = (series - series.rolling(50).mean()) / (series.rolling(50).std() + 1e-9)

        # Imbalance derivatives and z-scores (if depth features exist)
        if 'depth_imbalance' in features.columns:
            di = features['depth_imbalance']
            features['depth_imbalance_ret_1'] = di.diff(1)
            features['depth_imbalance_z_50'] = (di - di.rolling(50).mean()) / (di.rolling(50).std() + 1e-9)
        if 'bid_ask_ratio' in features.columns:
            bar = features['bid_ask_ratio']
            features['bid_ask_ratio_ret_1'] = bar.pct_change(1)
            features['bid_ask_ratio_z_50'] = (bar - bar.rolling(50).mean()) / (bar.rolling(50).std() + 1e-9)

        # Microprice premium relative to mid price if both exist
        if 'microprice' in features.columns and 'mid_price' in features.columns:
            mp = features['microprice']
            mid_px = features['mid_price']
            features['microprice_premium'] = (mp - mid_px) / (mid_px + 1e-9)
            features['microprice_premium_ret_1'] = features['microprice_premium'].diff(1)
            features['microprice_premium_z_50'] = (features['microprice_premium'] - features['microprice_premium'].rolling(50).mean()) / (features['microprice_premium'].rolling(50).std() + 1e-9)

        # Optionally drop price-level features
        if params.get('drop_price_level', True):
            for col in ['mid_price', 'mid_rolling_mean_5', 'mid_rolling_mean_20']:
                if col in features.columns:
                    features.drop(columns=[col], inplace=True, errors='ignore')
            # Add mid z-score if bid/ask exists
            if 'bid_px_1' in orderbook_df.columns and 'ask_px_1' in orderbook_df.columns:
                mid_tmp = (orderbook_df['bid_px_1'] + orderbook_df['ask_px_1']) / 2
                features['mid_zscore_20'] = (mid_tmp - mid_tmp.rolling(20).mean()) / (mid_tmp.rolling(20).std() + 1e-9)

        # Time-based features
        if params.get('include_time_features', True):
            # Hour of day (for intraday seasonality)
            features['hour_of_day'] = features.index.hour

            # Minute of hour
            features['minute_of_hour'] = features.index.minute

            # Is it a business hour? (9-16 EST equivalent)
            hour_of_day = features.index.hour
            features['is_business_hour'] = ((hour_of_day >= 9) & (hour_of_day <= 16)).astype(int)

        # Advanced orderbook features
        if params.get('include_advanced_features', True):
            # Orderbook pressure indicators
            if 'lb_buy_vol' in orderbook_df.columns and 'lb_sell_vol' in orderbook_df.columns:
                features['pressure_buy'] = orderbook_df['lb_buy_vol'] * orderbook_df.get('lb_avg_buy_px', features.get('mid_price', 1.0))
                features['pressure_sell'] = orderbook_df['lb_sell_vol'] * orderbook_df.get('lb_avg_sell_px', features.get('mid_price', 1.0))
                features['net_pressure'] = features['pressure_buy'] - features['pressure_sell']

            # Spread effectiveness (how well spread captures volatility)
            if 'mid_price' in features.columns:
                features['spread_effectiveness'] = features['spread'] / (features['mid_price'].rolling(20).std() + 1e-9)

        # Remove rows with excessive NaN values (but keep some for momentum features)
        nan_threshold = params.get('nan_threshold', 0.5)  # Allow up to 50% NaN
        features = features.dropna(thresh=int(len(features.columns) * (1 - nan_threshold)))

        # Forward fill remaining NaN values (for momentum features at the start)
        features = features.fillna(method='ffill').fillna(0)

        logger.debug(f"Created {len(features)} feature rows with {features.shape[1]} features")
        return features

    def _create_ohlcv_features(self,
                               candles_df: pd.DataFrame,
                               params: Dict[str, Any]) -> pd.DataFrame:
        """
        Create level-free OHLCV features (returns, vol, ranges, volume signals)
        """
        if candles_df.empty or not set(['open', 'high', 'low', 'close', 'volume']).issubset(candles_df.columns):
            return pd.DataFrame()

        df = pd.DataFrame(index=candles_df.index)

        close = candles_df['close'].astype(float)
        high = candles_df['high'].astype(float)
        low = candles_df['low'].astype(float)
        open_ = candles_df['open'].astype(float)
        vol = candles_df['volume'].astype(float)

        # Returns
        ret_1 = close.pct_change(1)
        df['ret_1'] = ret_1
        for lag in [2, 3, 5, 10]:
            df[f'ret_{lag}'] = close.pct_change(lag)

        # Realized volatility (std of returns)
        for w in [5, 20, 60]:
            df[f'realized_vol_{w}'] = ret_1.rolling(w).std()

        # Range-based vol estimators
        # Parkinson (uses high/low)
        with np.errstate(divide='ignore', invalid='ignore'):
            hl = np.log((high / low).replace(0, np.nan))
        parkinson_base = (hl ** 2).rolling(20).mean()
        df['parkinson_vol_20'] = np.sqrt(parkinson_base / (4.0 * np.log(2.0)))

        # True range and ATR normalized by previous close
        prev_close = close.shift(1)
        tr1 = (high - low) / (prev_close + 1e-9)
        tr2 = (high - prev_close).abs() / (prev_close + 1e-9)
        tr3 = (low - prev_close).abs() / (prev_close + 1e-9)
        tr_pct = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr_pct_14'] = tr_pct.rolling(14).mean()

        # Location/range features (level-free)
        range_ = (high - low)
        df['clv'] = ((close - low) - (high - close)) / (range_ + 1e-9)
        df['body_to_range'] = (close - open_).abs() / (range_ + 1e-9)
        df['norm_range'] = range_ / (prev_close + 1e-9)

        # RSI on returns (use rolling means)
        up = ret_1.clip(lower=0)
        down = (-ret_1.clip(upper=0))
        roll = 14
        avg_gain = up.rolling(roll).mean()
        avg_loss = down.rolling(roll).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        df['rsi_ret_14'] = 100.0 - (100.0 / (1.0 + rs))

        # Autocorrelation proxies
        # Rolling autocorr can be expensive; include simple lag products as proxy
        df['autocorr1_proxy_20'] = (ret_1 * ret_1.shift(1)).rolling(20).mean()
        df['abs_autocorr1_proxy_20'] = ((ret_1.abs()) * (ret_1.shift(1).abs())).rolling(20).mean()

        # Volume features (normalized)
        df['vol_z_20'] = (vol - vol.rolling(20).mean()) / (vol.rolling(20).std() + 1e-9)
        df['vol_change_1'] = vol.pct_change(1)
        # Illiquidity proxy (Amihud-like without price): |r| normalized by mean volume
        df['illiquidity_proxy_20'] = ret_1.abs() / (vol.rolling(20).mean() + 1.0)

        # VWAP deviation surrogate (typical price vs rolling mean) -> z-scored, not raw levels
        typical = (high + low + close) / 3.0
        df['typical_dev_z_20'] = (typical - typical.rolling(20).mean()) / (typical.rolling(20).std() + 1e-9)

        return df

    def _create_target(self, candles_df: pd.DataFrame, target_type: str = 'regression', params: Optional[Dict[str, Any]] = None) -> pd.Series:
        """
        Create target variable

        Args:
            candles_df: OHLCV data
            target_type: 'regression' for raw returns, 'classification' for sign of returns

        Returns:
            Target series
        """
        if candles_df.empty or 'close' not in candles_df.columns:
            return pd.Series()

        params = params or {}
        closes = candles_df['close']

        # Horizon (prediction steps ahead)
        horizon = int(params.get('horizon', 1))
        next_close = closes.shift(-horizon)

        # Percent change
        returns = (next_close - closes) / closes

        # Remove last horizon rows (no future)
        returns = returns.iloc[:-horizon]

        if target_type == 'classification':
            # Dynamic neutral band
            neutral_mode = params.get('neutral_mode', 'vol')  # 'vol'|'percentile'|'fixed'
            neutral_value = params.get('neutral_value', 0.15)

            if neutral_mode == 'vol':
                roll = returns.rolling(200, min_periods=50).std()
                thr = (float(neutral_value) * roll).fillna(roll.median())
            elif neutral_mode == 'percentile':
                abs_r = returns.abs().rolling(200, min_periods=50)
                thr = abs_r.quantile(float(neutral_value)).fillna(returns.abs().quantile(float(neutral_value)))
            else:  # fixed in basis points
                thr = pd.Series(float(neutral_value) / 10000.0, index=returns.index)

            target = pd.Series(0, index=returns.index)
            target[returns > thr] = 1
            target[returns < -thr] = -1
        else:
            target = returns

        logger.debug(f"Created {target_type} target series with {len(target)} values")
        if target_type == 'classification':
            logger.debug(f"Class distribution: {target.value_counts().to_dict()}")

        return target

    def _align_features_target(self,
                              features_df: pd.DataFrame,
                              target_series: pd.Series) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Align features and target by timestamp

        Features at time t predict target at time t.
        """
        # Find common timestamps
        common_index = features_df.index.intersection(target_series.index)

        if len(common_index) == 0:
            logger.warning("No overlapping timestamps between features and target")
            return pd.DataFrame(), pd.Series()

        X_aligned = features_df.loc[common_index]
        y_aligned = target_series.loc[common_index]

        logger.debug(f"Aligned {len(X_aligned)} feature-target pairs")
        return X_aligned, y_aligned

def get_feature_engineer() -> FeatureEngineer:
    """Get FeatureEngineer instance"""
    return FeatureEngineer()

def make_features(candles_df: pd.DataFrame,
                 orderbook_df: pd.DataFrame,
                 params: Optional[Dict[str, Any]] = None,
                 target_type: str = 'regression') -> Tuple[pd.DataFrame, pd.Series]:
    """
    Convenience function to create features and target

    Args:
        candles_df: OHLCV data
        orderbook_df: Orderbook data
        params: Feature engineering parameters
        target_type: 'regression' for raw returns, 'classification' for direction

    Returns:
        Tuple of (features_df, target_series)
    """
    engineer = get_feature_engineer()
    return engineer.make_features(candles_df, orderbook_df, params, target_type)

# Feature validation functions

def validate_features(X: pd.DataFrame, y: pd.Series) -> Dict[str, Any]:
    """
    Validate feature and target data

    Returns dict with validation results and warnings
    """
    validation = {
        'valid': True,
        'warnings': [],
        'stats': {}
    }

    # Basic checks
    if X.empty or y.empty:
        validation['valid'] = False
        validation['warnings'].append("Empty features or target data")
        return validation

    if len(X) != len(y):
        validation['valid'] = False
        validation['warnings'].append(f"Mismatched lengths: X={len(X)}, y={len(y)}")
        return validation

    # Check for NaN
    nan_features = X.isna().sum().sum()
    nan_target = y.isna().sum()

    if nan_features > 0:
        validation['warnings'].append(f"Features contain {nan_features} NaN values")

    if nan_target > 0:
        validation['warnings'].append(f"Target contains {nan_target} NaN values")

    # Statistical checks
    validation['stats'] = {
        'n_samples': len(X),
        'n_features': X.shape[1],
        'feature_names': list(X.columns),
        'target_mean': float(y.mean()),
        'target_std': float(y.std()),
        'target_min': float(y.min()),
        'target_max': float(y.max()),
        'target_skew': float(y.skew()),
        'nan_features': int(nan_features),
        'nan_target': int(nan_target)
    }

    # Check for extreme target values
    extreme_pct = ((y.abs() > 0.1).sum() / len(y)) * 100  # >10% moves
    if extreme_pct > 5:
        validation['warnings'].append(f"High percentage of extreme moves: {extreme_pct:.1f}%")

    return validation
