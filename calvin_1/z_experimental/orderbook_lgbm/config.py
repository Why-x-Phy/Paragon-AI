"""
Configuration for Orderbook LGBM Trading Model

Loads database connection settings and model parameters from environment/docker compose.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

@dataclass
class DatabaseConfig:
    """Database connection configuration"""
    host: str
    port: int
    database: str
    user: str
    password: str

    def get_connection_string(self) -> str:
        """Get psycopg2 connection string"""
        return f"host={self.host} port={self.port} dbname={self.database} user={self.user} password={self.password}"

    def get_sqlalchemy_url(self) -> str:
        """Get SQLAlchemy URL for pandas"""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

@dataclass
class ModelConfig:
    """LightGBM model configuration"""
    objective: str = 'regression'
    metric: str = 'rmse'
    learning_rate: float = 0.05
    num_leaves: int = 64
    feature_fraction: float = 0.9
    bagging_fraction: float = 0.8
    bagging_freq: int = 1
    min_data_in_leaf: int = 50
    n_estimators: int = 2000
    early_stopping_rounds: int = 100
    random_state: int = 42

@dataclass
class FeatureConfig:
    """Feature engineering configuration"""
    # Data source tables
    candles_table: str = 'ohlcv'
    tokens_table: str = 'tokens'
    tob_table: str = 'tob_1s'  # top-of-book every second
    lbu_table: str = 'lbu_1m'  # orderbook microstructure per minute

    # Column mappings
    time_col_candles: str = 'time'
    token_id_col: str = 'token_id'
    symbol_col: str = 'symbol'
    resolution_col: str = 'resolution'

    # OHLCV columns
    open_col: str = 'open'
    high_col: str = 'high'
    low_col: str = 'low'
    close_col: str = 'close'
    volume_col: str = 'volume'

    # Orderbook columns (tob_1s)
    tob_time_col: str = 'bucket'
    tob_symbol_col: str = 'symbol'
    best_bid_col: str = 'best_bid'
    best_ask_col: str = 'best_ask'

    # Orderbook microstructure columns (lbu_1m)
    lbu_time_col: str = 'bucket'
    lbu_symbol_col: str = 'symbol'
    lbu_best_bid_col: str = 'lb_best_bid'
    lbu_best_ask_col: str = 'lb_best_ask'
    lbu_imbalance_col: str = 'lb_imbalance'
    lbu_spread_bps_col: str = 'lb_spread_bps'
    lbu_buy_vol_col: str = 'lb_buy_vol'
    lbu_sell_vol_col: str = 'lb_sell_vol'

class Config:
    """Main configuration class"""

    def __init__(self):
        # Database configuration
        self.db = self._load_database_config()

        # Default data parameters
        self.default_symbol = os.getenv('DEFAULT_SYMBOL', 'SOL')
        self.default_timeframe = os.getenv('DEFAULT_TIMEFRAME', '1m')
        self.default_start_ts = os.getenv('DEFAULT_START_TS', '2024-01-01')
        self.default_end_ts = os.getenv('DEFAULT_END_TS', '2024-12-01')

        # Feature configuration
        self.features = FeatureConfig()

        # Model configuration
        self.model = ModelConfig()

        # Paths
        self.project_root = Path(__file__).parent
        self.models_dir = self.project_root / 'models'
        self.data_cache_dir = self.project_root / 'data_cache'
        self.scripts_dir = self.project_root / 'scripts'

        # Ensure directories exist
        self.models_dir.mkdir(exist_ok=True)
        self.data_cache_dir.mkdir(exist_ok=True)

    def _load_database_config(self) -> DatabaseConfig:
        """Load database configuration from environment/docker compose"""

        # Try environment variables first (from .env file)
        host = os.getenv('DB_HOST', 'localhost')
        port = int(os.getenv('DB_PORT', '5433'))
        database = os.getenv('DB_NAME', 'calvin_trading_dev')
        user = os.getenv('DB_USER', 'calvin_dev')
        password = os.getenv('DB_PASSWORD', 'calvin_dev_password')

        # Override with development defaults if not set
        if host == 'localhost' and not os.getenv('DB_HOST'):
            # Check if we're in docker environment
            if os.path.exists('/.dockerenv'):
                host = 'timescaledb'
                port = 5432
            # Otherwise use dev defaults from .env

        return DatabaseConfig(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )

    def get_db_connection(self):
        """Get a psycopg2 database connection"""
        return psycopg2.connect(self.db.get_connection_string())

    def get_pandas_connection_string(self) -> str:
        """Get connection string for pandas read_sql"""
        return self.db.get_sqlalchemy_url()

# Global config instance
config = Config()

def get_config() -> Config:
    """Get global configuration instance"""
    return config

def validate_config() -> bool:
    """Validate configuration and database connectivity"""
    try:
        # Test database connection
        conn = config.get_db_connection()
        conn.close()
        print("✅ Database connection successful")
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
