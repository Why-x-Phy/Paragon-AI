"""
Utility functions for Orderbook LGBM project

Time range helpers, data alignment utilities, and other common functions.
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timedelta
from pathlib import Path
import json
import yaml
import logging
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

# Time range utilities

def parse_timestamp(ts: str) -> datetime:
    """
    Parse timestamp string flexibly

    Args:
        ts: Timestamp string (ISO format, or relative like '2024-01-01')

    Returns:
        Parsed datetime
    """
    try:
        return date_parser.parse(ts)
    except Exception as e:
        raise ValueError(f"Could not parse timestamp '{ts}': {e}")

def create_time_range(start_ts: str,
                     end_ts: Optional[str] = None,
                     days: Optional[int] = None) -> Tuple[datetime, datetime]:
    """
    Create time range from start timestamp

    Args:
        start_ts: Start timestamp string
        end_ts: End timestamp string (optional)
        days: Number of days from start (if end_ts not provided)

    Returns:
        Tuple of (start_datetime, end_datetime)
    """
    start_dt = parse_timestamp(start_ts)

    if end_ts:
        end_dt = parse_timestamp(end_ts)
    elif days:
        end_dt = start_dt + timedelta(days=days)
    else:
        # Default to 30 days
        end_dt = start_dt + timedelta(days=30)

    return start_dt, end_dt

def get_business_days(start_date: datetime, end_date: datetime) -> List[datetime]:
    """
    Get list of business days between two dates

    Args:
        start_date: Start date
        end_date: End date

    Returns:
        List of business day datetimes
    """
    # Create date range
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')

    # Filter to business days (Monday-Friday)
    business_days = date_range[date_range.weekday < 5]

    return business_days.tolist()

def split_time_range(start_ts: str,
                    end_ts: str,
                    n_splits: int) -> List[Tuple[str, str]]:
    """
    Split time range into equal periods

    Args:
        start_ts: Start timestamp
        end_ts: End timestamp
        n_splits: Number of splits

    Returns:
        List of (start, end) timestamp string tuples
    """
    start_dt = parse_timestamp(start_ts)
    end_dt = parse_timestamp(end_ts)

    # Calculate split points
    total_duration = end_dt - start_dt
    split_duration = total_duration / n_splits

    splits = []
    current_start = start_dt

    for i in range(n_splits):
        current_end = current_start + split_duration
        if i == n_splits - 1:  # Last split goes to end
            current_end = end_dt

        splits.append((current_start.isoformat(), current_end.isoformat()))
        current_start = current_end

    return splits

# Data alignment utilities

def align_dataframes(df1: pd.DataFrame,
                    df2: pd.DataFrame,
                    how: str = 'inner',
                    tolerance: Optional[pd.Timedelta] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Align two DataFrames by timestamp index

    Args:
        df1: First DataFrame (datetime index)
        df2: Second DataFrame (datetime index)
        how: Join method ('inner', 'outer', 'left', 'right')
        tolerance: Time tolerance for alignment

    Returns:
        Tuple of aligned DataFrames
    """
    if not isinstance(df1.index, pd.DatetimeIndex) or not isinstance(df2.index, pd.DatetimeIndex):
        raise ValueError("Both DataFrames must have DatetimeIndex")

    # Sort by index
    df1 = df1.sort_index()
    df2 = df2.sort_index()

    # Align
    if tolerance is None:
        # Exact alignment
        common_index = df1.index.intersection(df2.index) if how == 'inner' else df1.index.union(df2.index)
        df1_aligned = df1.reindex(common_index)
        df2_aligned = df2.reindex(common_index)
    else:
        # Tolerance-based alignment (forward fill within tolerance)
        df1_aligned = df1.reindex(df2.index, method='ffill', tolerance=tolerance)
        df2_aligned = df2.copy()

        if how == 'inner':
            valid_mask = df1_aligned.notna().any(axis=1)
            df1_aligned = df1_aligned[valid_mask]
            df2_aligned = df2_aligned[valid_mask]

    return df1_aligned, df2_aligned

def forward_fill_orderbook(orderbook_df: pd.DataFrame,
                          candle_df: pd.DataFrame,
                          max_gap: pd.Timedelta = pd.Timedelta(minutes=5)) -> pd.DataFrame:
    """
    Forward fill orderbook data up to candle times with maximum gap limit

    Args:
        orderbook_df: Orderbook DataFrame (datetime index)
        candle_df: Candle DataFrame (datetime index)
        max_gap: Maximum time gap to forward fill

    Returns:
        Forward-filled orderbook DataFrame aligned to candle times
    """
    # Reindex orderbook to candle times
    aligned = orderbook_df.reindex(candle_df.index, method='ffill')

    # Calculate time since last valid orderbook update
    valid_mask = orderbook_df.notna().any(axis=1)
    last_valid_times = orderbook_df[valid_mask].index

    # For each candle time, find time since last orderbook update
    gaps = []
    for candle_time in candle_df.index:
        # Find last orderbook update before this candle
        valid_before = last_valid_times[last_valid_times <= candle_time]
        if len(valid_before) > 0:
            gap = candle_time - valid_before[-1]
            gaps.append(gap)
        else:
            gaps.append(pd.Timedelta.max)

    # Create gap series
    gap_series = pd.Series(gaps, index=candle_df.index)

    # Mask out fills that exceed max gap
    within_gap = gap_series <= max_gap
    aligned = aligned[within_gap]

    logger.debug(f"Forward fill: {len(aligned)} candles with valid orderbook data (max_gap={max_gap})")

    return aligned

def resample_to_frequency(df: pd.DataFrame,
                         freq: str,
                         agg_funcs: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """
    Resample DataFrame to specified frequency

    Args:
        df: DataFrame with datetime index
        freq: Pandas frequency string ('1min', '5min', '1h', etc.)
        agg_funcs: Aggregation functions per column (default: mean for all)

    Returns:
        Resampled DataFrame
    """
    if agg_funcs is None:
        # Default: mean for numeric columns
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        agg_funcs = {col: 'mean' for col in numeric_cols}

    # Add 'first' for non-numeric columns (like symbols)
    for col in df.columns:
        if col not in agg_funcs:
            agg_funcs[col] = 'first'

    resampled = df.resample(freq).agg(agg_funcs)

    logger.debug(f"Resampled {len(df)} rows to {len(resampled)} rows at {freq} frequency")

    return resampled

# File I/O utilities

def save_json(data: Any, path: Path, indent: int = 2) -> None:
    """
    Save data to JSON file

    Args:
        data: Data to save
        path: Output path
        indent: JSON indentation
    """
    path.parent.mkdir(exist_ok=True)

    def json_serializer(obj):
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Series):
            return obj.to_dict()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict('records')
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    with open(path, 'w') as f:
        json.dump(data, f, indent=indent, default=json_serializer)

    logger.debug(f"Saved data to {path}")

def load_json(path: Path) -> Any:
    """
    Load data from JSON file

    Args:
        path: Path to JSON file

    Returns:
        Loaded data
    """
    with open(path, 'r') as f:
        return json.load(f)

def save_yaml(data: Any, path: Path) -> None:
    """
    Save data to YAML file

    Args:
        data: Data to save
        path: Output path
    """
    path.parent.mkdir(exist_ok=True)

    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False)

    logger.debug(f"Saved data to {path}")

def load_yaml(path: Path) -> Any:
    """
    Load data from YAML file

    Args:
        path: Path to YAML file

    Returns:
        Loaded data
    """
    with open(path, 'r') as f:
        return yaml.safe_load(f)

# Data validation utilities

def validate_dataframe(df: pd.DataFrame,
                      required_columns: Optional[List[str]] = None,
                      datetime_index: bool = True) -> Dict[str, Any]:
    """
    Validate DataFrame structure and content

    Args:
        df: DataFrame to validate
        required_columns: List of required column names
        datetime_index: Whether index should be datetime

    Returns:
        Validation results dict
    """
    validation = {
        'valid': True,
        'warnings': [],
        'errors': [],
        'stats': {}
    }

    # Check index type
    if datetime_index and not isinstance(df.index, pd.DatetimeIndex):
        validation['errors'].append("DataFrame index must be DatetimeIndex")
        validation['valid'] = False

    # Check required columns
    if required_columns:
        missing_cols = [col for col in required_columns if col not in df.columns]
        if missing_cols:
            validation['errors'].append(f"Missing required columns: {missing_cols}")
            validation['valid'] = False

    # Basic stats
    validation['stats'] = {
        'n_rows': len(df),
        'n_cols': len(df.columns),
        'columns': list(df.columns),
        'index_type': str(type(df.index)),
        'memory_usage': df.memory_usage(deep=True).sum()
    }

    # Check for NaN values
    nan_counts = df.isna().sum()
    total_nans = nan_counts.sum()

    if total_nans > 0:
        nan_cols = nan_counts[nan_counts > 0]
        validation['warnings'].append(f"Found {total_nans} NaN values in columns: {list(nan_cols.index)}")
        validation['stats']['nan_counts'] = nan_cols.to_dict()

    # Check for infinite values
    inf_counts = np.isinf(df.select_dtypes(include=[np.number])).sum().sum()
    if inf_counts > 0:
        validation['warnings'].append(f"Found {inf_counts} infinite values")

    return validation

def safe_divide(a: pd.Series, b: pd.Series, default: float = 0.0) -> pd.Series:
    """
    Safely divide two Series, handling division by zero

    Args:
        a: Numerator
        b: Denominator
        default: Default value for division by zero

    Returns:
        Result of division
    """
    return np.divide(a, b, out=np.full_like(a, default, dtype=float), where=(b != 0))

def calculate_rolling_stats(df: pd.DataFrame,
                           window: int,
                           columns: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Calculate rolling statistics for specified columns

    Args:
        df: DataFrame with datetime index
        window: Rolling window size
        columns: Columns to calculate stats for (default: all numeric)

    Returns:
        DataFrame with rolling statistics
    """
    if columns is None:
        columns = df.select_dtypes(include=[np.number]).columns.tolist()

    rolling_stats = pd.DataFrame(index=df.index)

    for col in columns:
        series = df[col]

        # Basic rolling stats
        rolling_stats[f'{col}_mean_{window}'] = series.rolling(window=window).mean()
        rolling_stats[f'{col}_std_{window}'] = series.rolling(window=window).std()
        rolling_stats[f'{col}_min_{window}'] = series.rolling(window=window).min()
        rolling_stats[f'{col}_max_{window}'] = series.rolling(window=window).max()

        # Optional: more advanced stats
        rolling_stats[f'{col}_skew_{window}'] = series.rolling(window=window).skew()
        rolling_stats[f'{col}_kurt_{window}'] = series.rolling(window=window).kurt()

    # Remove rows with NaN (from rolling window)
    rolling_stats = rolling_stats.dropna()

    logger.debug(f"Calculated rolling stats for {len(columns)} columns with window {window}")

    return rolling_stats

# Logging utilities

def setup_logging(level: str = 'INFO',
                 log_file: Optional[Path] = None,
                 format_string: Optional[str] = None) -> logging.Logger:
    """
    Setup logging configuration

    Args:
        level: Logging level
        log_file: Optional log file path
        format_string: Log format string

    Returns:
        Configured logger
    """
    if format_string is None:
        format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Create formatter
    formatter = logging.Formatter(format_string)

    # Setup root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_file.parent.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
