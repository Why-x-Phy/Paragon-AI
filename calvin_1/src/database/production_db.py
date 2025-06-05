"""
Calvin AI Production Database Manager

Handles all database operations for the Calvin AI trading system including:
- TimescaleDB (PostgreSQL) connections with connection pooling
- Redis caching and pub/sub
- Async database operations optimized for time-series data
- Real-time data insertion and querying
- Position and trade management
- Model prediction storage and retrieval
"""

import asyncio
import logging
import os
import json
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as redis
try:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
except ImportError:
    # Fallback for older SQLAlchemy versions
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    async_sessionmaker = sessionmaker
from sqlalchemy.sql import text
from sqlalchemy import create_engine
import pandas as pd

try:
    from ..config import get_config
except ImportError:
    # Fallback for when running test scripts directly
    from config import get_config


@dataclass
class TokenInfo:
    """Token information structure"""
    token_id: int
    address: str
    symbol: str
    name: str
    decimals: int
    is_active: bool


@dataclass
class OHLCVData:
    """OHLCV candle data structure"""
    time: datetime
    token_id: int
    resolution: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    volume_usd: Optional[float] = None
    trades_count: Optional[int] = None
    data_source: str = 'birdeye'


@dataclass
class PositionData:
    """Position data structure"""
    position_id: Optional[int]
    token_id: int
    position_type: str  # 'long' or 'short'
    status: str  # 'open', 'closed', 'partial'
    entry_price: float
    entry_quantity: float
    entry_value_usdc: float
    entry_time: datetime
    entry_tx_hash: Optional[str] = None
    exit_price: Optional[float] = None
    exit_quantity: Optional[float] = None
    exit_value_usdc: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_tx_hash: Optional[str] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    realized_pnl_usdc: float = 0.0
    unrealized_pnl_usdc: float = 0.0
    fees_paid_usdc: float = 0.0
    model_prediction_confidence: Optional[float] = None
    model_version: Optional[str] = None


@dataclass
class TradeData:
    """Trade execution data structure"""
    token_id: int
    trade_type: str  # 'buy' or 'sell'
    price: float
    quantity: float
    value_usdc: float
    fee_usdc: float
    tx_hash: str
    execution_time: datetime
    trade_id: Optional[int] = None
    position_id: Optional[int] = None
    slippage_bps: Optional[int] = None
    dex_name: Optional[str] = None
    block_number: Optional[int] = None
    processing_time_ms: Optional[int] = None


@dataclass
class MarketEventData:
    """Market event data structure - for transaction/orderbook data"""
    token_id: int
    event_type: str  # 'transaction', 'large_trade', 'whale_move', 'order_book'
    event_time: datetime
    event_data: Dict  # Flexible JSON data
    size_usd: Optional[float] = None
    impact_score: Optional[float] = None
    source: str = 'birdeye'
    raw_data: Optional[Dict] = None


@dataclass
class ModelPredictionData:
    """Model prediction data structure"""
    prediction_id: Optional[int]
    token_id: int
    model_name: str
    model_version: str
    prediction_time: datetime
    prediction_action: str  # 'buy', 'sell', 'hold'
    confidence_score: float
    predicted_price_change: Optional[float] = None
    prediction_horizon_minutes: Optional[int] = None
    input_features: Optional[Dict] = None
    actual_outcome: Optional[str] = None
    outcome_accuracy: Optional[float] = None


class DatabaseConnectionError(Exception):
    """Database connection error"""
    pass


class DatabaseOperationError(Exception):
    """Database operation error"""
    pass


class ProductionDBManager:
    """
    Production Database Manager for Calvin AI
    
    Manages TimescaleDB (PostgreSQL) and Redis connections with:
    - Async connection pooling
    - Time-series optimized operations
    - Real-time data caching
    - Transaction management
    - Error handling and retry logic
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config()
        self.logger = logging.getLogger(__name__)
        
        # Database connections
        self.pg_engine = None
        self.async_session_maker = None
        self.redis_client = None
        self.pg_pool = None
        
        # Connection configuration
        base_url = self.config.get('DATABASE_URL')  # Use the basic postgresql:// URL
        self.pg_url = base_url
        
        # For SQLAlchemy async, we need the +asyncpg suffix
        self.pg_url_async = base_url
        if self.pg_url_async and 'postgresql://' in self.pg_url_async and 'asyncpg' not in self.pg_url_async:
            self.pg_url_async = self.pg_url_async.replace('postgresql://', 'postgresql+asyncpg://')
        
        self.redis_url = self.config.get('REDIS_URL')
        
        # Connection pool settings
        self.max_connections = int(self.config.get('PGBOUNCER_POOL_SIZE', 25))
        self.connection_timeout = float(self.config.get('DB_CONNECTION_TIMEOUT', 10.0))
        
        # Cache settings
        self.cache_ttl = {
            'prices': 300,      # 5 minutes
            'ohlcv': 3600,      # 1 hour
            'positions': 60,    # 1 minute
            'tokens': 86400,    # 24 hours
        }
        
        # Token cache
        self._token_cache: Dict[str, TokenInfo] = {}
        self._token_id_cache: Dict[int, TokenInfo] = {}
        
    async def initialize(self):
        """Initialize database connections and pools"""
        try:
            await self._initialize_postgresql()
            await self._initialize_redis()
            await self._load_token_cache()
            
            self.logger.info("Database connections initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize database connections: {e}")
            raise DatabaseConnectionError(f"Database initialization failed: {e}")
    
    async def _initialize_postgresql(self):
        """Initialize PostgreSQL connection pool"""
        try:
            # Create async engine with connection pooling
            self.pg_engine = create_async_engine(
                self.pg_url_async,
                pool_size=self.max_connections,
                max_overflow=10,
                pool_timeout=self.connection_timeout,
                pool_recycle=3600,  # Recycle connections every hour
                echo=False,  # Set to True for SQL debugging
                connect_args={'statement_cache_size': 0}  # Disable prepared statement cache for PgBouncer compatibility
            )
            
            # Create session maker
            self.async_session_maker = async_sessionmaker(
                self.pg_engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            # Create asyncpg pool for direct operations (uses basic postgresql:// URL)
            self.pg_pool = await asyncpg.create_pool(
                self.pg_url,  # Use basic URL without +asyncpg
                min_size=5,
                max_size=self.max_connections,
                command_timeout=60,
                statement_cache_size=0  # Disable prepared statement cache for PgBouncer compatibility
            )
            
            # Test direct asyncpg connection instead of SQLAlchemy engine
            async with self.pg_pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                assert result == 1
                
            self.logger.info("PostgreSQL connection pool initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize PostgreSQL: {e}")
            raise
    
    async def _initialize_redis(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=self.connection_timeout,
                socket_timeout=self.connection_timeout,
                retry_on_timeout=True,
                health_check_interval=30
            )
            
            # Test connection
            await self.redis_client.ping()
            
            self.logger.info("Redis connection initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Redis: {e}")
            raise
    
    async def _load_token_cache(self):
        """Load tokens into memory cache"""
        try:
            query = "SELECT token_id, address, symbol, name, decimals, is_active FROM tokens"
            
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(query)
                
            for row in rows:
                token = TokenInfo(
                    token_id=row['token_id'],
                    address=row['address'],
                    symbol=row['symbol'],
                    name=row['name'],
                    decimals=row['decimals'],
                    is_active=row['is_active']
                )
                self._token_cache[token.address] = token
                self._token_id_cache[token.token_id] = token
                
            self.logger.info(f"Loaded {len(self._token_cache)} tokens into cache")
            
        except Exception as e:
            self.logger.error(f"Failed to load token cache: {e}")
            raise
    
    async def close(self):
        """Close all database connections"""
        try:
            if self.pg_engine:
                await self.pg_engine.dispose()
                
            if self.pg_pool:
                await self.pg_pool.close()
                
            if self.redis_client:
                await self.redis_client.close()
                
            self.logger.info("Database connections closed")
            
        except Exception as e:
            self.logger.error(f"Error closing database connections: {e}")
    
    # =========================================================================
    # TOKEN OPERATIONS
    # =========================================================================
    
    def get_token_by_address(self, address: str) -> Optional[TokenInfo]:
        """Get token info by address from cache"""
        return self._token_cache.get(address)
    
    def get_token_by_id(self, token_id: int) -> Optional[TokenInfo]:
        """Get token info by ID from cache"""
        return self._token_id_cache.get(token_id)
    
    async def get_token_by_symbol(self, symbol: str) -> Optional[Dict]:
        """Get token info by symbol with robust fallback to database"""
        # First try cache lookup (fast path)
        for token in self._token_cache.values():
            if token.symbol.upper() == symbol.upper():
                # Get additional LunarCrush fields from database for this token
                try:
                    query = """
                        SELECT token_id, address, symbol, name, decimals, is_active,
                               lunarcrush_id, lunarcrush_symbol, lunarcrush_topic, 
                               social_data_available
                        FROM tokens 
                        WHERE token_id = $1
                    """
                    async with self.pg_pool.acquire() as conn:
                        row = await conn.fetchrow(query, token.token_id)
                        
                    if row:
                        return {
                            'token_id': row['token_id'],
                            'address': row['address'],
                            'symbol': row['symbol'],
                            'name': row['name'],
                            'decimals': row['decimals'],
                            'is_active': row['is_active'],
                            'lunarcrush_id': row['lunarcrush_id'],
                            'lunarcrush_symbol': row['lunarcrush_symbol'],
                            'lunarcrush_topic': row['lunarcrush_topic'],
                            'social_data_available': row['social_data_available']
                        }
                except Exception as e:
                    self.logger.warning(f"Failed to get LunarCrush fields from database: {e}")
                
                # Fallback to basic cache data if database query fails
                return {
                    'token_id': token.token_id,
                    'address': token.address,
                    'symbol': token.symbol,
                    'name': token.name,
                    'decimals': token.decimals,
                    'is_active': token.is_active,
                    'lunarcrush_id': None,
                    'lunarcrush_symbol': None,
                    'lunarcrush_topic': None,
                    'social_data_available': False
                }
        
        # Cache miss - fallback to direct database query
        try:
            query = """
                SELECT token_id, address, symbol, name, decimals, is_active,
                       lunarcrush_id, lunarcrush_symbol, lunarcrush_topic, 
                       social_data_available
                FROM tokens 
                WHERE UPPER(symbol) = UPPER($1)
                LIMIT 1
            """
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query, symbol)
                
            if row:
                # Update cache with this token for future lookups
                token = TokenInfo(
                    token_id=row['token_id'],
                    address=row['address'],
                    symbol=row['symbol'],
                    name=row['name'],
                    decimals=row['decimals'],
                    is_active=row['is_active']
                )
                self._token_cache[token.address] = token
                self._token_id_cache[token.token_id] = token
                
                return {
                    'token_id': row['token_id'],
                    'address': row['address'],
                    'symbol': row['symbol'],
                    'name': row['name'],
                    'decimals': row['decimals'],
                    'is_active': row['is_active'],
                    'lunarcrush_id': row['lunarcrush_id'],
                    'lunarcrush_symbol': row['lunarcrush_symbol'],
                    'lunarcrush_topic': row['lunarcrush_topic'],
                    'social_data_available': row['social_data_available']
                }
        except Exception as e:
            self.logger.error(f"Failed to get token by symbol from database: {e}")
        
        return None
    
    async def get_or_create_token(self, address: str, symbol: str, name: str, decimals: int = 9) -> Dict:
        """Get existing token or create new one"""
        # First try to find by symbol - search cache directly
        token_info = None
        for token in self._token_cache.values():
            if token.symbol.upper() == symbol.upper():
                token_info = token
                break
                
        if token_info:
            return {
                'token_id': token_info.token_id,
                'address': token_info.address,
                'symbol': token_info.symbol,
                'name': token_info.name,
                'decimals': token_info.decimals,
                'is_active': token_info.is_active
            }
        
        # If not found by symbol, try by address
        if address:
            token_info = self.get_token_by_address(address)
            if token_info:
                return {
                    'token_id': token_info.token_id,
                    'address': token_info.address,
                    'symbol': token_info.symbol,
                    'name': token_info.name,
                    'decimals': token_info.decimals,
                    'is_active': token_info.is_active
                }
        
        # Create new token
        new_token = await self.add_token(address or f"unknown_{symbol}", symbol, name or symbol, decimals)
        return {
            'token_id': new_token.token_id,
            'address': new_token.address,
            'symbol': new_token.symbol,
            'name': new_token.name,
            'decimals': new_token.decimals,
            'is_active': new_token.is_active
        }
    
    async def get_active_tokens(self) -> List[Dict]:
        """Get all active tokens with LunarCrush data"""
        try:
            query = """
                SELECT token_id, address, symbol, name, decimals, is_active, 
                       lunarcrush_id, lunarcrush_symbol, lunarcrush_topic, 
                       social_data_available, last_social_update
                FROM tokens 
                WHERE is_active = true
                ORDER BY social_data_available DESC, lunarcrush_id DESC, symbol
            """
            
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(query)
                
            return [
                {
                    'token_id': row['token_id'],
                    'address': row['address'],
                    'symbol': row['symbol'],
                    'name': row['name'],
                    'decimals': row['decimals'],
                    'is_active': row['is_active'],
                    'lunarcrush_id': row['lunarcrush_id'],
                    'lunarcrush_symbol': row['lunarcrush_symbol'],
                    'lunarcrush_topic': row['lunarcrush_topic'],
                    'social_data_available': row['social_data_available'],
                    'last_social_update': row['last_social_update']
                }
                for row in rows
            ]
            
        except Exception as e:
            self.logger.error(f"Failed to get active tokens: {e}")
            return []
    
    async def add_token(self, address: str, symbol: str, name: str, decimals: int = 9) -> TokenInfo:
        """Add a new token to the database"""
        try:
            query = """
                INSERT INTO tokens (address, symbol, name, decimals)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (address) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    name = EXCLUDED.name,
                    decimals = EXCLUDED.decimals,
                    updated_at = NOW()
                RETURNING token_id, address, symbol, name, decimals, is_active
            """
            
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query, address, symbol, name, decimals)
                
            token = TokenInfo(
                token_id=row['token_id'],
                address=row['address'],
                symbol=row['symbol'],
                name=row['name'],
                decimals=row['decimals'],
                is_active=row['is_active']
            )
            
            # Update cache
            self._token_cache[token.address] = token
            self._token_id_cache[token.token_id] = token
            
            self.logger.info(f"Added token {symbol} ({address})")
            return token
            
        except Exception as e:
            self.logger.error(f"Failed to add token {symbol}: {e}")
            raise DatabaseOperationError(f"Failed to add token: {e}")
    
    # =========================================================================
    # OHLCV OPERATIONS
    # =========================================================================
    
    async def insert_ohlcv_data(self, ohlcv_data: List[OHLCVData]) -> int:
        """Insert OHLCV data in batch"""
        if not ohlcv_data:
            return 0
            
        try:
            query = """
                INSERT INTO ohlcv (time, token_id, resolution, open, high, low, close, 
                                 volume, volume_usd, trades_count, data_source)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (time, token_id, resolution) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    volume_usd = EXCLUDED.volume_usd,
                    trades_count = EXCLUDED.trades_count,
                    data_source = EXCLUDED.data_source
            """
            
            async with self.pg_pool.acquire() as conn:
                await conn.executemany(query, [
                    (
                        data.time, data.token_id, data.resolution,
                        data.open, data.high, data.low, data.close,
                        data.volume, data.volume_usd, data.trades_count, data.data_source
                    )
                    for data in ohlcv_data
                ])
            
            # Cache latest prices in Redis
            await self._cache_latest_prices(ohlcv_data)
            
            self.logger.debug(f"Inserted {len(ohlcv_data)} OHLCV records")
            return len(ohlcv_data)
            
        except Exception as e:
            self.logger.error(f"Failed to insert OHLCV data: {e}")
            raise DatabaseOperationError(f"Failed to insert OHLCV data: {e}")
    
    async def get_ohlcv_data(
        self, 
        token_id: int, 
        resolution: str, 
        start_time: datetime, 
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[OHLCVData]:
        """Get OHLCV data for a token"""
        try:
            # Build query
            conditions = ["token_id = $1", "resolution = $2", "time >= $3"]
            params = [token_id, resolution, start_time]
            
            if end_time:
                conditions.append("time <= $4")
                params.append(end_time)
                
            query = f"""
                SELECT time, token_id, resolution, open, high, low, close,
                       volume, volume_usd, trades_count, data_source
                FROM ohlcv 
                WHERE {' AND '.join(conditions)}
                ORDER BY time DESC
            """
            
            if limit:
                query += f" LIMIT {limit}"
                
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            
            return [
                OHLCVData(
                    time=row['time'],
                    token_id=row['token_id'],
                    resolution=row['resolution'],
                    open=row['open'],
                    high=row['high'],
                    low=row['low'],
                    close=row['close'],
                    volume=row['volume'],
                    volume_usd=row['volume_usd'],
                    trades_count=row['trades_count'],
                    data_source=row['data_source']
                )
                for row in rows
            ]
            
        except Exception as e:
            self.logger.error(f"Failed to get OHLCV data: {e}")
            raise DatabaseOperationError(f"Failed to get OHLCV data: {e}")
    
    async def get_latest_price(self, token_id: int) -> Optional[float]:
        """Get latest price for a token"""
        try:
            # Try Redis cache first
            cache_key = f"prices:{token_id}:current"
            cached_price = await self.redis_client.get(cache_key)
            
            if cached_price:
                return float(cached_price)
            
            # Fallback to database
            query = """
                SELECT close FROM ohlcv 
                WHERE token_id = $1 AND resolution = '1m'
                ORDER BY time DESC 
                LIMIT 1
            """
            
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query, token_id)
                
            if row:
                price = float(row['close'])
                # Cache for 5 minutes
                await self.redis_client.setex(cache_key, self.cache_ttl['prices'], price)
                return price
                
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to get latest price for token {token_id}: {e}")
            return None
    
    async def _cache_latest_prices(self, ohlcv_data: List[OHLCVData]):
        """Cache latest prices in Redis"""
        try:
            pipe = self.redis_client.pipeline()
            
            for data in ohlcv_data:
                if data.resolution == '1m':  # Only cache minute data
                    cache_key = f"prices:{data.token_id}:current"
                    pipe.setex(cache_key, self.cache_ttl['prices'], data.close)
            
            await pipe.execute()
            
        except Exception as e:
            self.logger.error(f"Failed to cache latest prices: {e}")
    
    # =========================================================================
    # POSITION OPERATIONS
    # =========================================================================
    
    async def create_position(self, position: PositionData) -> int:
        """Create a new position"""
        try:
            query = """
                INSERT INTO positions (token_id, position_type, entry_price, entry_quantity, 
                                     entry_value_usdc, entry_time, entry_tx_hash, 
                                     stop_loss_price, take_profit_price,
                                     model_prediction_confidence, model_version)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING position_id
            """
            
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    query,
                    position.token_id, position.position_type, position.entry_price,
                    position.entry_quantity, position.entry_value_usdc, position.entry_time,
                    position.entry_tx_hash, position.stop_loss_price, position.take_profit_price,
                    position.model_prediction_confidence, position.model_version
                )
            
            position_id = row['position_id']
            
            # Invalidate positions cache
            await self._invalidate_positions_cache(position.token_id)
            
            self.logger.info(f"Created position {position_id} for token {position.token_id}")
            return position_id
            
        except Exception as e:
            self.logger.error(f"Failed to create position: {e}")
            raise DatabaseOperationError(f"Failed to create position: {e}")
    
    async def update_position(self, position_id: int, updates: Dict) -> bool:
        """Update a position"""
        try:
            # Build dynamic update query
            set_clauses = []
            params = []
            param_idx = 1
            
            for field, value in updates.items():
                set_clauses.append(f"{field} = ${param_idx}")
                params.append(value)
                param_idx += 1
            
            set_clauses.append(f"updated_at = NOW()")
            params.append(position_id)
            
            query = f"""
                UPDATE positions 
                SET {', '.join(set_clauses)}
                WHERE position_id = ${param_idx}
                RETURNING token_id
            """
            
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            
            if row:
                # Invalidate positions cache
                await self._invalidate_positions_cache(row['token_id'])
                return True
                
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to update position {position_id}: {e}")
            raise DatabaseOperationError(f"Failed to update position: {e}")
    
    async def get_open_positions(self, token_id: Optional[int] = None) -> List[PositionData]:
        """Get open positions"""
        try:
            # Check cache first
            cache_key = f"positions:open:{token_id or 'all'}"
            cached = await self.redis_client.get(cache_key)
            
            if cached:
                data = json.loads(cached)
                return [PositionData(**pos) for pos in data]
            
            # Query database
            query = """
                SELECT position_id, token_id, position_type, status, entry_price, entry_quantity,
                       entry_value_usdc, entry_time, entry_tx_hash, exit_price, exit_quantity,
                       exit_value_usdc, exit_time, exit_tx_hash, stop_loss_price, take_profit_price,
                       realized_pnl_usdc, unrealized_pnl_usdc, fees_paid_usdc,
                       model_prediction_confidence, model_version
                FROM positions 
                WHERE status = 'open'
            """
            
            params = []
            if token_id:
                query += " AND token_id = $1"
                params.append(token_id)
            
            query += " ORDER BY entry_time DESC"
            
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            
            positions = [
                PositionData(
                    position_id=row['position_id'],
                    token_id=row['token_id'],
                    position_type=row['position_type'],
                    status=row['status'],
                    entry_price=row['entry_price'],
                    entry_quantity=row['entry_quantity'],
                    entry_value_usdc=row['entry_value_usdc'],
                    entry_time=row['entry_time'],
                    entry_tx_hash=row['entry_tx_hash'],
                    exit_price=row['exit_price'],
                    exit_quantity=row['exit_quantity'],
                    exit_value_usdc=row['exit_value_usdc'],
                    exit_time=row['exit_time'],
                    exit_tx_hash=row['exit_tx_hash'],
                    stop_loss_price=row['stop_loss_price'],
                    take_profit_price=row['take_profit_price'],
                    realized_pnl_usdc=row['realized_pnl_usdc'],
                    unrealized_pnl_usdc=row['unrealized_pnl_usdc'],
                    fees_paid_usdc=row['fees_paid_usdc'],
                    model_prediction_confidence=row['model_prediction_confidence'],
                    model_version=row['model_version']
                )
                for row in rows
            ]
            
            # Cache for 1 minute
            cache_data = [asdict(pos) for pos in positions]
            await self.redis_client.setex(
                cache_key, 
                self.cache_ttl['positions'], 
                json.dumps(cache_data, default=str)
            )
            
            return positions
            
        except Exception as e:
            self.logger.error(f"Failed to get open positions: {e}")
            raise DatabaseOperationError(f"Failed to get open positions: {e}")
    
    async def _invalidate_positions_cache(self, token_id: int):
        """Invalidate positions cache"""
        try:
            cache_keys = [
                f"positions:open:{token_id}",
                "positions:open:all"
            ]
            await self.redis_client.delete(*cache_keys)
        except Exception as e:
            self.logger.error(f"Failed to invalidate positions cache: {e}")
    
    # =========================================================================
    # TRADE OPERATIONS
    # =========================================================================
    
    async def record_trade(self, trade: TradeData) -> int:
        """Record a trade execution"""
        try:
            query = """
                INSERT INTO trades (position_id, token_id, trade_type, price, quantity, 
                                  value_usdc, fee_usdc, slippage_bps, dex_name, tx_hash,
                                  block_number, execution_time, processing_time_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                RETURNING trade_id
            """
            
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    query,
                    trade.position_id, trade.token_id, trade.trade_type, trade.price,
                    trade.quantity, trade.value_usdc, trade.fee_usdc, trade.slippage_bps,
                    trade.dex_name, trade.tx_hash, trade.block_number, trade.execution_time,
                    trade.processing_time_ms
                )
            
            trade_id = row['trade_id']
            
            self.logger.info(f"Recorded trade {trade_id}: {trade.trade_type} {trade.quantity} tokens")
            return trade_id
            
        except Exception as e:
            self.logger.error(f"Failed to record trade: {e}")
            raise DatabaseOperationError(f"Failed to record trade: {e}")
    
    # =========================================================================
    # MODEL PREDICTION OPERATIONS
    # =========================================================================
    
    async def save_model_prediction(self, prediction: ModelPredictionData) -> int:
        """Save model prediction to database"""
        try:
            async with self.pg_pool.acquire() as conn:
                query = """
                    INSERT INTO model_predictions (
                        token_id, model_name, model_version, prediction_time,
                        prediction_action, confidence_score, predicted_price_change,
                        prediction_horizon_minutes, input_features
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING prediction_id
                """
                
                result = await conn.fetchrow(
                    query,
                    prediction.token_id,
                    prediction.model_name,
                    prediction.model_version,
                    prediction.prediction_time,
                    prediction.prediction_action,
                    prediction.confidence_score,
                    prediction.predicted_price_change,
                    prediction.prediction_horizon_minutes,
                    json.dumps(prediction.input_features) if prediction.input_features else None
                )
                
                prediction_id = result['prediction_id']
                self.logger.debug(f"Saved model prediction {prediction_id}")
                return prediction_id
                
        except Exception as e:
            self.logger.error(f"Failed to save model prediction: {e}")
            raise DatabaseOperationError(f"Failed to save prediction: {e}")
    
    async def insert_market_events(self, events: List[MarketEventData]) -> int:
        """Insert market event data (transactions, trades, orderbook data)"""
        if not events:
            return 0
            
        try:
            async with self.pg_pool.acquire() as conn:
                query = """
                    INSERT INTO market_events (
                        token_id, event_type, event_time, event_data,
                        size_usd, impact_score, source, raw_data
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """
                
                # Prepare batch data
                batch_data = []
                for event in events:
                    batch_data.append((
                        event.token_id,
                        event.event_type,
                        event.event_time,
                        json.dumps(event.event_data),
                        event.size_usd,
                        event.impact_score,
                        event.source,
                        json.dumps(event.raw_data) if event.raw_data else None
                    ))
                
                # Execute batch insert
                await conn.executemany(query, batch_data)
                
                self.logger.debug(f"Inserted {len(events)} market events")
                return len(events)
                
        except Exception as e:
            self.logger.error(f"Failed to insert market events: {e}")
            raise DatabaseOperationError(f"Failed to insert market events: {e}")
    
    async def save_market_event(self, event: MarketEventData) -> bool:
        """Save market event to database"""
        try:
            async with self.pg_pool.acquire() as conn:
                query = """
                    INSERT INTO market_events (
                        event_time, token_id, event_type, event_data,
                        size_usd, impact_score, source, raw_data
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """
                
                await conn.execute(
                    query,
                    event.event_time,
                    event.token_id,
                    event.event_type,
                    json.dumps(event.event_data),
                    event.size_usd,
                    event.impact_score,
                    event.source,
                    json.dumps(event.raw_data) if event.raw_data else None
                )
                
                return True
                
        except Exception as e:
            self.logger.error(f"Error saving market event: {e}")
            return False
    
    # =========================================================================
    # HEALTH AND MONITORING
    # =========================================================================
    
    async def get_social_data(
        self, 
        token_id: int, 
        start_time: datetime, 
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Get social data from the dedicated social_data table
        
        Args:
            token_id: Token ID to query
            start_time: Start timestamp
            end_time: End timestamp (defaults to now)
            limit: Maximum number of records
            
        Returns:
            List of social data dictionaries compatible with data processor
        """
        if end_time is None:
            end_time = datetime.utcnow()
            
        try:
            query = """
                SELECT 
                    time,
                    sentiment,
                    galaxy_score,
                    alt_rank,
                    social_dominance,
                    interactions,
                    contributors_active,
                    contributors_created,
                    posts_active,
                    posts_created,
                    spam,
                    market_dominance,
                    market_cap,
                    circulating_supply,
                    close_price,
                    open_price,
                    high_price,
                    low_price,
                    volume_24h,
                    data_source,
                    lunarcrush_id
                FROM social_data
                WHERE token_id = $1 
                    AND time >= $2 
                    AND time <= $3
                ORDER BY time DESC
            """
            
            params = [token_id, start_time, end_time]
            
            if limit:
                query += " LIMIT $4"
                params.append(limit)
            
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            
            # Convert to format expected by data processor (matching original SocialMetrics structure)
            social_data = []
            for row in rows:
                record = {
                    'timestamp': row['time'],
                    'time': row['time'],  # Both formats for compatibility
                    # Core social metrics
                    'sentiment': float(row['sentiment']) if row['sentiment'] else None,
                    'galaxy_score': float(row['galaxy_score']) if row['galaxy_score'] else None,
                    'alt_rank': int(row['alt_rank']) if row['alt_rank'] else None,
                    'social_dominance': float(row['social_dominance']) if row['social_dominance'] else None,
                    'interactions': int(row['interactions']) if row['interactions'] else None,
                    'interactions_24h': int(row['interactions']) if row['interactions'] else None,  # Alias for compatibility
                    # Social engagement
                    'contributors_active': int(row['contributors_active']) if row['contributors_active'] else None,
                    'contributors_created': int(row['contributors_created']) if row['contributors_created'] else None,
                    'social_contributors_active': int(row['contributors_active']) if row['contributors_active'] else None,  # Alias for compatibility
                    'social_contributors_created': int(row['contributors_created']) if row['contributors_created'] else None,  # Alias for compatibility
                    'social_interactions': int(row['interactions']) if row['interactions'] else None,  # Alias for compatibility
                    'posts_active': int(row['posts_active']) if row['posts_active'] else None,
                    'posts_created': int(row['posts_created']) if row['posts_created'] else None,
                    'spam': int(row['spam']) if row['spam'] else None,
                    # Market metrics
                    'market_dominance': float(row['market_dominance']) if row['market_dominance'] else None,
                    'market_cap': float(row['market_cap']) if row['market_cap'] else None,
                    'circulating_supply': float(row['circulating_supply']) if row['circulating_supply'] else None,
                    'close_price': float(row['close_price']) if row['close_price'] else None,
                    'open_price': float(row['open_price']) if row['open_price'] else None,
                    'high_price': float(row['high_price']) if row['high_price'] else None,
                    'low_price': float(row['low_price']) if row['low_price'] else None,
                    'volume_24h': float(row['volume_24h']) if row['volume_24h'] else None,
                    # Alternative names for compatibility with existing code
                    'social_volume': int(row['interactions']) if row['interactions'] else None,  # Use interactions as proxy
                    # Source info
                    'data_source': row['data_source'],
                    'lunarcrush_id': int(row['lunarcrush_id']) if row['lunarcrush_id'] else None
                }
                
                social_data.append(record)
            
            self.logger.debug(f"Retrieved {len(social_data)} social data records for token {token_id}")
            return social_data
            
        except Exception as e:
            self.logger.error(f"Failed to get social data: {e}")
            raise DatabaseOperationError(f"Failed to get social data: {e}")
    
    async def get_social_data_by_symbol(
        self, 
        symbol: str, 
        days: int = 30
    ) -> List[Dict]:
        """
        Get social data by token symbol (convenience method for data processor)
        
        Args:
            symbol: Token symbol 
            days: Number of days of history
            
        Returns:
            List of social data dictionaries
        """
        try:
            # Get token by symbol
            token_info = await self.get_token_by_symbol(symbol.upper())
            if not token_info:
                self.logger.warning(f"Token {symbol} not found in database")
                return []
            
            # Calculate date range
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days)
            
            # Get social data
            social_data = await self.get_social_data(
                token_id=token_info['token_id'],
                start_time=start_time,
                end_time=end_time
            )
            
            return social_data
            
        except Exception as e:
            self.logger.error(f"Failed to get social data by symbol {symbol}: {e}")
            return []
    
    async def record_health_check(self, component: str, status: str, details: Dict = None):
        """Record system health check"""
        try:
            query = """
                INSERT INTO system_health (check_time, component, status, details)
                VALUES ($1, $2, $3, $4)
            """
            
            details_json = json.dumps(details) if details else None
            check_time = datetime.utcnow()
            
            async with self.pg_pool.acquire() as conn:
                await conn.execute(query, check_time, component, status, details_json)
                
        except Exception as e:
            self.logger.error(f"Failed to record health check: {e}")
    
    async def get_database_stats(self) -> Dict:
        """Get database statistics"""
        try:
            stats = {}
            
            # Table sizes
            size_query = """
                SELECT 
                    schemaname,
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
                FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            """
            
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(size_query)
                
            stats['table_sizes'] = {row['tablename']: row['size'] for row in rows}
            
            # Connection info
            stats['connections'] = {
                'pool_size': self.pg_pool.get_size(),
                'pool_free': self.pg_pool.get_size() - self.pg_pool.get_idle_size(),
                'pool_idle': self.pg_pool.get_idle_size()
            }
            
            # Redis info
            redis_info = await self.redis_client.info()
            stats['redis'] = {
                'used_memory': redis_info.get('used_memory_human'),
                'connected_clients': redis_info.get('connected_clients'),
                'total_commands_processed': redis_info.get('total_commands_processed')
            }
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Failed to get database stats: {e}")
            return {}
    
    # =========================================================================
    # CONTEXT MANAGERS
    # =========================================================================
    
    @asynccontextmanager
    async def transaction(self):
        """Database transaction context manager"""
        async with self.async_session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    @asynccontextmanager
    async def redis_pipeline(self):
        """Redis pipeline context manager"""
        pipe = self.redis_client.pipeline()
        try:
            yield pipe
            await pipe.execute()
        except Exception:
            await pipe.reset()
            raise

    async def store_social_data(self, token_id: int, social_metrics: Dict) -> bool:
        """
        Store social data in the dedicated social_data table
        
        Args:
            token_id: Token ID
            social_metrics: Dictionary containing social metrics from LunarCrush
            
        Returns:
            bool: Success status
        """
        try:
            query = """
                INSERT INTO social_data (
                    time, token_id, sentiment, galaxy_score, alt_rank,
                    social_dominance, interactions,
                    contributors_active, contributors_created,
                    posts_active, posts_created, spam,
                    market_dominance, market_cap, circulating_supply, 
                    close_price, open_price, high_price, low_price, volume_24h,
                    data_source, lunarcrush_id
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                    $21, $22
                )
                ON CONFLICT (time, token_id) DO UPDATE SET
                    sentiment = EXCLUDED.sentiment,
                    galaxy_score = EXCLUDED.galaxy_score,
                    alt_rank = EXCLUDED.alt_rank,
                    social_dominance = EXCLUDED.social_dominance,
                    interactions = EXCLUDED.interactions,
                    contributors_active = EXCLUDED.contributors_active,
                    contributors_created = EXCLUDED.contributors_created,
                    posts_active = EXCLUDED.posts_active,
                    posts_created = EXCLUDED.posts_created,
                    spam = EXCLUDED.spam,
                    market_dominance = EXCLUDED.market_dominance,
                    market_cap = EXCLUDED.market_cap,
                    circulating_supply = EXCLUDED.circulating_supply,
                    close_price = EXCLUDED.close_price,
                    open_price = EXCLUDED.open_price,
                    high_price = EXCLUDED.high_price,
                    low_price = EXCLUDED.low_price,
                    volume_24h = EXCLUDED.volume_24h,
                    data_source = EXCLUDED.data_source,
                    lunarcrush_id = EXCLUDED.lunarcrush_id,
                    api_fetch_time = NOW()
            """
            
            # Extract timestamp - use 'time' or 'timestamp' depending on format
            timestamp = social_metrics.get('time') or social_metrics.get('timestamp')
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            elif not isinstance(timestamp, datetime):
                timestamp = datetime.utcnow()
            
            async with self.pg_pool.acquire() as conn:
                await conn.execute(query,
                    timestamp,
                    token_id,
                    social_metrics.get('sentiment'),
                    social_metrics.get('galaxy_score'),
                    social_metrics.get('alt_rank'),
                    social_metrics.get('social_dominance'),
                    social_metrics.get('interactions'),
                    social_metrics.get('contributors_active'),
                    social_metrics.get('contributors_created'),
                    social_metrics.get('posts_active'),
                    social_metrics.get('posts_created'),
                    social_metrics.get('spam'),
                    social_metrics.get('market_dominance'),
                    social_metrics.get('market_cap'),
                    social_metrics.get('circulating_supply'),
                    social_metrics.get('close') or social_metrics.get('close_price'),
                    social_metrics.get('open') or social_metrics.get('open_price'),
                    social_metrics.get('high') or social_metrics.get('high_price'),
                    social_metrics.get('low') or social_metrics.get('low_price'),
                    social_metrics.get('volume_24h'),
                    social_metrics.get('data_source', 'lunarcrush'),
                    social_metrics.get('lunarcrush_id')
                )
            
            self.logger.debug(f"Stored social data for token {token_id} at {timestamp}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to store social data for token {token_id}: {e}")
            return False


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_db_manager_instance: Optional[ProductionDBManager] = None


async def get_db_manager() -> ProductionDBManager:
    """Get singleton database manager instance"""
    global _db_manager_instance
    
    if _db_manager_instance is None:
        _db_manager_instance = ProductionDBManager()
        await _db_manager_instance.initialize()
    
    return _db_manager_instance


async def close_db_manager():
    """Close database manager instance"""
    global _db_manager_instance
    
    if _db_manager_instance:
        await _db_manager_instance.close()
        _db_manager_instance = None 