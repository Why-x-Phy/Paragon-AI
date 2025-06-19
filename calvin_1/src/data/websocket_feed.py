import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Callable, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import aiohttp
from aiohttp import WSMsgType
import os
from datetime import datetime, timedelta


class SubscriptionType(Enum):
    """BirdEye WebSocket subscription types"""
    SUBSCRIBE_PRICE = "SUBSCRIBE_PRICE"
    SUBSCRIBE_TXS = "SUBSCRIBE_TXS"
    SUBSCRIBE_BASE_QUOTE_PRICE = "SUBSCRIBE_BASE_QUOTE_PRICE"
    SUBSCRIBE_TOKEN_NEW_LISTING = "SUBSCRIBE_TOKEN_NEW_LISTING"
    SUBSCRIBE_NEW_PAIR = "SUBSCRIBE_NEW_PAIR"
    SUBSCRIBE_LARGE_TRADE_TXS = "SUBSCRIBE_LARGE_TRADE_TXS"
    SUBSCRIBE_WALLET_TXS = "SUBSCRIBE_WALLET_TXS"


class ConnectionState(Enum):
    """WebSocket connection states"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ConnectionConfig:
    """WebSocket connection configuration"""
    api_key: str
    chain: str = "solana"
    reconnect_delay: float = 2.0
    max_reconnect_delay: float = 30.0
    max_reconnect_attempts: int = 5
    heartbeat_interval: float = 30.0
    connection_timeout: float = 10.0
    message_queue_size: int = 1000


@dataclass
class PriceSubscription:
    """BirdEye price subscription configuration"""
    query_type: str = "simple"  # "simple" or "complex"
    chart_type: str = "1m"      # "1m", "3m", "5m", etc.
    address: str = ""           # Token or pair address
    currency: str = "usd"       # "usd" or "pair"
    query: str = ""             # For complex queries


@dataclass
class PriceUpdate:
    """Price update event data structure - BirdEye OHLCV format"""
    address: str
    symbol: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    unix_time: int
    chart_type: str
    event_type: str
    timestamp: datetime = field(default_factory=datetime.now)
    raw_data: Dict = field(default_factory=dict)


@dataclass
class TransactionSubscription:
    """BirdEye transaction subscription configuration"""
    query_type: str = "simple"     # "simple" or "complex"
    address: str = ""              # Token address for token transactions
    pair_address: str = ""         # Pair address for pair transactions  
    query: str = ""                # For complex queries


@dataclass
class TransactionUpdate:
    """Transaction update event data structure - BirdEye TXS format"""
    block_unix_time: int
    owner: str
    source: str
    tx_hash: str
    side: Optional[str] = None              # "buy" or "sell"
    token_address: Optional[str] = None
    platform: str = ""
    price_pair: Optional[float] = None
    volume_usd: Optional[float] = None
    token_price: Optional[float] = None
    network: str = ""
    pool_id: Optional[str] = None
    
    # From token details
    from_address: str = ""
    from_symbol: str = ""
    from_amount: Optional[int] = None
    from_ui_amount: Optional[float] = None
    from_price: Optional[float] = None
    from_decimals: Optional[int] = None
    
    # To token details  
    to_address: str = ""
    to_symbol: str = ""
    to_amount: Optional[int] = None
    to_ui_amount: Optional[float] = None
    to_price: Optional[float] = None
    to_decimals: Optional[int] = None
    
    timestamp: datetime = field(default_factory=datetime.now)
    raw_data: Dict = field(default_factory=dict)


class BirdEyeWebSocketFeed:
    """
    BirdEye WebSocket price feed implementation
    
    Provides real-time price updates for Solana tokens and pairs
    with automatic reconnection and error handling.
    """
    
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Connection state
        self.ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.connection_state = ConnectionState.DISCONNECTED
        self.reconnect_attempts = 0
        self.last_heartbeat = time.time()
        
        # Event handlers
        self.price_update_handlers: List[Callable] = []
        self.transaction_update_handlers: List[Callable] = []
        self.connection_handlers: List[Callable] = []
        self.error_handlers: List[Callable] = []
        
        # Message processing
        self.message_queue = asyncio.Queue(maxsize=config.message_queue_size)
        self.processing_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            'messages_received': 0,
            'messages_processed': 0,
            'connection_errors': 0,
            'reconnections': 0,
            'price_updates': 0
        }
        
        # Active subscriptions
        self.active_subscriptions: List[PriceSubscription] = []

    @property
    def ws_url(self) -> str:
        """WebSocket URL for BirdEye"""
        return f"wss://public-api.birdeye.so/socket/{self.config.chain}?x-api-key={self.config.api_key}"

    @property
    def headers(self) -> Dict[str, str]:
        """WebSocket connection headers"""
        return {
            'Origin': 'ws://public-api.birdeye.so',
            'Sec-WebSocket-Origin': 'ws://public-api.birdeye.so',
            'Sec-WebSocket-Protocol': 'echo-protocol'
        }

    def add_price_update_handler(self, handler: Callable[[PriceUpdate], None]):
        """Add price update event handler"""
        self.price_update_handlers.append(handler)

    def add_transaction_update_handler(self, handler: Callable[[TransactionUpdate], None]):
        """Add transaction update event handler"""
        self.transaction_update_handlers.append(handler)

    def add_connection_handler(self, handler: Callable[[ConnectionState], None]):
        """Add connection state change handler"""
        self.connection_handlers.append(handler)

    def add_error_handler(self, handler: Callable[[Exception], None]):
        """Add error event handler"""
        self.error_handlers.append(handler)

    async def start(self):
        """Start the WebSocket connection"""
        self.logger.info("Starting BirdEye WebSocket price feed...")
        await self._connect()

    async def stop(self):
        """Stop the WebSocket connection"""
        self.logger.info("Stopping BirdEye WebSocket price feed...")
        
        # Cancel tasks
        if self.processing_task:
            self.processing_task.cancel()
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        
        # Close connection
        if self.ws_connection and not self.ws_connection.closed:
            await self.ws_connection.close()
        
        if self.session and not self.session.closed:
            await self.session.close()
        
        self._set_connection_state(ConnectionState.DISCONNECTED)

    async def subscribe_price(self, subscription: PriceSubscription) -> bool:
        """Subscribe to price updates"""
        if self.connection_state != ConnectionState.CONNECTED:
            self.logger.error("Cannot subscribe: WebSocket not connected")
            return False
        
        try:
            # Build subscription message
            if subscription.query_type == "complex":
                message = {
                    "type": "SUBSCRIBE_PRICE",
                    "data": {
                        "queryType": "complex",
                        "query": subscription.query
                    }
                }
            else:
                message = {
                    "type": "SUBSCRIBE_PRICE", 
                    "data": {
                        "queryType": "simple",
                        "chartType": subscription.chart_type,
                        "address": subscription.address,
                        "currency": subscription.currency
                    }
                }
            
            await self.ws_connection.send_str(json.dumps(message))
            self.active_subscriptions.append(subscription)
            self.logger.info(f"Subscribed to price updates: {subscription.address}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to subscribe to price updates: {e}")
            return False

    async def subscribe_transactions(self, subscription: TransactionSubscription) -> bool:
        """Subscribe to transaction updates"""
        if self.connection_state != ConnectionState.CONNECTED:
            self.logger.error("Cannot subscribe: WebSocket not connected")
            return False
        
        try:
            # Build subscription message
            if subscription.query_type == "complex":
                message = {
                    "type": "SUBSCRIBE_TXS",
                    "data": {
                        "queryType": "complex",
                        "query": subscription.query
                    }
                }
            else:
                # Simple subscription - can be for token or pair
                data = {"queryType": "simple"}
                if subscription.address:
                    data["address"] = subscription.address
                if subscription.pair_address:
                    data["pairAddress"] = subscription.pair_address
                    
                message = {
                    "type": "SUBSCRIBE_TXS",
                    "data": data
                }
            
            await self.ws_connection.send_str(json.dumps(message))
            self.logger.info(f"Subscribed to transaction updates: {subscription.address or subscription.pair_address}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to subscribe to transaction updates: {e}")
            return False

    async def _connect(self):
        """Establish WebSocket connection"""
        try:
            self._set_connection_state(ConnectionState.CONNECTING)
            self.logger.info(f"Connecting to {self.ws_url}")
            
            # Create session if needed
            if not self.session or self.session.closed:
                connector = aiohttp.TCPConnector(limit=100, limit_per_host=10)
                timeout = aiohttp.ClientTimeout(total=self.config.connection_timeout)
                self.session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                    headers=self.headers
                )
            
            # Connect to WebSocket
            self.ws_connection = await self.session.ws_connect(
                self.ws_url,
                protocols=['echo-protocol'],
                timeout=self.config.connection_timeout
            )
            
            self._set_connection_state(ConnectionState.CONNECTED)
            self.logger.info("BirdEye WebSocket connection established")
            self.reconnect_attempts = 0
            
            # Start processing tasks
            self.processing_task = asyncio.create_task(self._process_messages())
            self.heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
            
        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
            self.stats['connection_errors'] += 1
            self._set_connection_state(ConnectionState.ERROR)
            await self._handle_connection_error(e)

    async def _process_messages(self):
        """Process incoming WebSocket messages"""
        try:
            # Check if connection is valid before starting loop
            if not self.ws_connection or self.ws_connection.closed:
                self.logger.warning("WebSocket connection is not valid for message processing")
                return
                
            async for message in self.ws_connection:
                if message.type == WSMsgType.TEXT:
                    try:
                        self.stats['messages_received'] += 1
                        await self.message_queue.put(message.data)
                        await self._process_message(message.data)
                        self.stats['messages_processed'] += 1
                    except asyncio.QueueFull:
                        self.logger.warning("Message queue full, dropping message")
                    except Exception as e:
                        self.logger.error(f"Error processing message: {e}")
                        
                elif message.type == WSMsgType.ERROR:
                    error = self.ws_connection.exception()
                    self.logger.error(f"WebSocket error: {error}")
                    await self._handle_connection_error(error)
                    break
                    
                elif message.type == WSMsgType.CLOSE:
                    self.logger.info("WebSocket connection closed by server")
                    break
                    
        except Exception as e:
            self.logger.error(f"Message processing error: {e}")
            await self._handle_connection_error(e)

    async def _process_message(self, message_data: str):
        """Process individual WebSocket message"""
        try:
            data = json.loads(message_data)
            
            # Add debug logging to see what messages we're receiving
            message_type = data.get('type', '')
            self.logger.info(f"📨 Received WebSocket message: type='{message_type}', data_keys={list(data.keys())}")
            
            # Update heartbeat timestamp
            self.last_heartbeat = time.time()
            
            # Handle different message types
            if message_type == 'PRICE_DATA':
                await self._handle_price_data(data)
            elif message_type == 'TXS_DATA':
                await self._handle_transaction_data(data)
            else:
                # Handle other message types or log unknown types
                self.logger.info(f"📋 Unknown message type '{message_type}': {data}")
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON message: {e}")
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    async def _handle_price_data(self, data: Dict):
        """Handle price data messages from BirdEye"""
        try:
            price_data = data.get('data', {})
            
            if not price_data:
                self.logger.warning("Received empty price data")
                return
            
            # Extract price update information
            price_update = PriceUpdate(
                address=price_data.get('address', ''),
                symbol=price_data.get('symbol', ''),
                open_price=float(price_data.get('o', 0)),
                high_price=float(price_data.get('h', 0)),
                low_price=float(price_data.get('l', 0)),
                close_price=float(price_data.get('c', 0)),
                volume=float(price_data.get('v', 0)),
                unix_time=int(price_data.get('unixTime', 0)),
                chart_type=price_data.get('type', ''),
                event_type=price_data.get('eventType', ''),
                timestamp=datetime.fromtimestamp(price_data.get('unixTime', 0)),
                raw_data=price_data
            )
            
            self.stats['price_updates'] += 1
            
            # Notify handlers
            for handler in self.price_update_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(price_update)
                    else:
                        handler(price_update)
                except Exception as e:
                    self.logger.error(f"Error in price update handler: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error handling price data: {e}")

    async def _handle_transaction_data(self, data: Dict):
        """Handle transaction data messages from BirdEye"""
        try:
            transaction_data = data.get('data', {})
            
            if not transaction_data:
                self.logger.warning("Received empty transaction data")
                return
            
            # Extract transaction update information
            from_data = transaction_data.get('from', {})
            to_data = transaction_data.get('to', {})
            
            transaction_update = TransactionUpdate(
                block_unix_time=int(transaction_data.get('blockUnixTime', 0)),
                owner=transaction_data.get('owner', ''),
                source=transaction_data.get('source', ''),
                tx_hash=transaction_data.get('txHash', ''),
                side=transaction_data.get('side', None),
                token_address=transaction_data.get('tokenAddress', None),
                platform=transaction_data.get('platform', ''),
                price_pair=float(transaction_data.get('pricePair', 0)) if transaction_data.get('pricePair') is not None else None,
                volume_usd=float(transaction_data.get('volumeUSD', 0)) if transaction_data.get('volumeUSD') is not None else None,
                token_price=float(transaction_data.get('tokenPrice', 0)) if transaction_data.get('tokenPrice') is not None else None,
                network=transaction_data.get('network', ''),
                pool_id=transaction_data.get('poolId', None),
                # From token details
                from_address=from_data.get('address', ''),
                from_symbol=from_data.get('symbol', ''),
                from_amount=int(from_data.get('amount', 0)) if from_data.get('amount') is not None else None,
                from_ui_amount=float(from_data.get('uiAmount', 0)) if from_data.get('uiAmount') is not None else None,
                from_price=float(from_data.get('price', 0)) if from_data.get('price') is not None else None,
                from_decimals=int(from_data.get('decimals', 0)) if from_data.get('decimals') is not None else None,
                # To token details
                to_address=to_data.get('address', ''),
                to_symbol=to_data.get('symbol', ''),
                to_amount=int(to_data.get('amount', 0)) if to_data.get('amount') is not None else None,
                to_ui_amount=float(to_data.get('uiAmount', 0)) if to_data.get('uiAmount') is not None else None,
                to_price=float(to_data.get('price', 0)) if to_data.get('price') is not None else None,
                to_decimals=int(to_data.get('decimals', 0)) if to_data.get('decimals') is not None else None,
                timestamp=datetime.fromtimestamp(transaction_data.get('blockUnixTime', 0)),
                raw_data=transaction_data
            )
            
            self.stats['price_updates'] += 1
            
            # Notify handlers
            for handler in self.transaction_update_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(transaction_update)
                    else:
                        handler(transaction_update)
                except Exception as e:
                    self.logger.error(f"Error in transaction update handler: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error handling transaction data: {e}")

    async def _heartbeat_monitor(self):
        """Monitor connection health with heartbeat"""
        while self.connection_state == ConnectionState.CONNECTED:
            try:
                await asyncio.sleep(self.config.heartbeat_interval)
                
                # Check if we've received recent messages
                time_since_heartbeat = time.time() - self.last_heartbeat
                if time_since_heartbeat > self.config.heartbeat_interval * 2:
                    self.logger.warning(f"No heartbeat for {time_since_heartbeat:.1f}s, connection may be stale")
                    # Attempt to reconnect
                    await self._reconnect()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Heartbeat monitor error: {e}")

    async def _handle_connection_error(self, error: Exception):
        """Handle connection errors with retry logic"""
        self.stats['connection_errors'] += 1
        self._set_connection_state(ConnectionState.ERROR)
        
        # Notify error handlers
        for handler in self.error_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(error)
                else:
                    handler(error)
            except Exception as e:
                self.logger.error(f"Error in error handler: {e}")
        
        # Attempt reconnection
        if self.reconnect_attempts < self.config.max_reconnect_attempts:
            await self._reconnect()
        else:
            self.logger.error("Max reconnection attempts reached")
            self._set_connection_state(ConnectionState.DISCONNECTED)

    async def _reconnect(self):
        """Attempt to reconnect with exponential backoff"""
        if self.reconnect_attempts >= self.config.max_reconnect_attempts:
            self.logger.error(f"Max reconnect attempts ({self.config.max_reconnect_attempts}) reached")
            self._set_connection_state(ConnectionState.ERROR)
            return
        
        self.reconnect_attempts += 1
        delay = min(
            self.config.reconnect_delay * (2 ** (self.reconnect_attempts - 1)),
            self.config.max_reconnect_delay
        )
        
        self.logger.info(f"Reconnecting in {delay:.1f}s (attempt {self.reconnect_attempts})")
        await asyncio.sleep(delay)
        
        try:
            await self._connect()
            self.stats['reconnections'] += 1
            
            # Re-subscribe to all active subscriptions
            for subscription in self.active_subscriptions:
                await self.subscribe_price(subscription)
                
        except Exception as e:
            self.logger.error(f"Reconnection failed: {e}")
            await self._reconnect()

    def _set_connection_state(self, state: ConnectionState):
        """Update connection state and notify handlers"""
        if self.connection_state != state:
            self.logger.info(f"WebSocket connection state: {self.connection_state.value} → {state.value}")
            self.connection_state = state
            
            # Notify connection handlers
            for handler in self.connection_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(state))
                    else:
                        handler(state)
                except Exception as e:
                    self.logger.error(f"Error in connection handler: {e}")

    def get_stats(self) -> Dict:
        """Get WebSocket connection statistics"""
        return {
            **self.stats,
            'connection_state': self.connection_state.value,
            'reconnect_attempts': self.reconnect_attempts,
            'active_subscriptions': len(self.active_subscriptions),
            'subscribed_tokens': len(set(sub.address for sub in self.active_subscriptions)),
            'last_heartbeat': datetime.fromtimestamp(self.last_heartbeat).isoformat(),
            'uptime_seconds': time.time() - self.last_heartbeat if self.connection_state == ConnectionState.CONNECTED else 0
        }


# ===========================================================================
# WebSocket Feed Manager for Auto-Configuration
# ===========================================================================

class DualWebSocketFeedManager:
    """
    Manages dual WebSocket feeds for price and transaction data
    
    Creates exactly 2 connections as per BirdEye documentation:
    1. One connection for all token OHLCV data (complex query)
    2. One connection for all token transaction data (complex query)
    
    Provides in-memory candle storage for emergency monitoring + batch database writes.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.db_manager = None
        
        # Dual WebSocket feeds
        self.price_feed: Optional[BirdEyeWebSocketFeed] = None      # For OHLCV data
        self.transaction_feed: Optional[BirdEyeWebSocketFeed] = None # For TXS data
        
        # 🆕 IN-MEMORY STORAGE FOR EMERGENCY MONITORING
        self.current_prices: Dict[str, float] = {}                 # symbol -> latest_price
        self.price_history: Dict[str, List[Tuple[datetime, float]]] = {}  # symbol -> [(time, price), ...]
        self.current_candles: Dict[str, Dict] = {}                 # symbol -> current_1min_candle
        
        # 🆕 BATCH PROCESSING QUEUES
        self.ohlcv_write_queue: List[Dict] = []                    # Batched OHLCV data for DB
        self.market_events_queue: List[Dict] = []                  # Batched market events for DB
        self.batch_size = 50                                       # Write batches of 50 items
        self.batch_timeout = 30.0                                  # Write every 30 seconds
        
        # Tracked tokens and data
        self.tracked_tokens: Dict[str, Dict] = {}  # symbol -> token_info
        self.last_prices: Dict[str, PriceUpdate] = {}  # symbol -> latest_price_update
        self.last_transactions: Dict[str, TransactionUpdate] = {}  # symbol -> latest_tx
        
        # Event handlers
        self.price_handlers: List[Callable[[str, PriceUpdate], None]] = []
        self.transaction_handlers: List[Callable[[str, TransactionUpdate], None]] = []
        self.connection_handlers: List[Callable[[ConnectionState], None]] = []
        
        # Processing tasks
        self.database_writer_task: Optional[asyncio.Task] = None
        self.price_history_cleaner_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            'tokens_tracked': 0,
            'price_connection_active': False,
            'transaction_connection_active': False,
            'price_updates_received': 0,
            'transaction_updates_received': 0,
            'connection_errors': 0,
            'last_token_refresh': None,
            'manager_start_time': None,
            'ohlcv_writes_batched': 0,
            'market_events_batched': 0,
            'database_writes_executed': 0,
            'current_candles_count': 0,
            'price_history_points': 0
        }
        
        self.logger.info("🚀 Dual WebSocket Feed Manager initialized with in-memory storage")

    async def initialize(self):
        """Initialize the dual feed manager with database storage integration"""
        try:
            # Import here to avoid circular imports
            from ..database.production_db import get_db_manager
            from ..config.config import config
            from .realtime_storage import RealtimeDataStorage
            
            # Initialize database manager
            self.db_manager = await get_db_manager()
            
            # Get API keys for load balancing
            api_key_1 = config.get('BIRDEYE_API_KEY')
            api_key_2 = config.get('BIRDEYE_API_KEY_2', api_key_1)  # Use second key if available
            
            if not api_key_1:
                raise ValueError("BIRDEYE_API_KEY is required for WebSocket feeds")
            
            # Create configuration for both feeds
            price_config = ConnectionConfig(
                api_key=api_key_1,
                chain="solana",
                reconnect_delay=1.0,
                max_reconnect_attempts=10,
                heartbeat_interval=30.0,
                message_queue_size=2000
            )
            
            transaction_config = ConnectionConfig(
                api_key=api_key_2,  # Use different key to distribute load
                chain="solana",
                reconnect_delay=1.0,
                max_reconnect_attempts=10,
                heartbeat_interval=30.0,
                message_queue_size=2000
            )
            
            # Initialize both WebSocket feeds
            self.price_feed = BirdEyeWebSocketFeed(price_config)
            self.transaction_feed = BirdEyeWebSocketFeed(transaction_config)
            
            # CRITICAL: Set up direct database storage integration
            # We'll handle storage directly to avoid WebSocket lifecycle conflicts
            
            # Set up price feed event handlers for database storage + caching
            self.price_feed.add_price_update_handler(self._on_price_update_with_storage)
            self.price_feed.add_connection_handler(lambda state: self._on_connection_change("price", state))
            self.price_feed.add_error_handler(lambda error: self._on_connection_error("price", error))
            
            # Set up transaction feed event handlers for database storage + caching
            self.transaction_feed.add_transaction_update_handler(self._on_transaction_update_with_storage)
            self.transaction_feed.add_connection_handler(lambda state: self._on_connection_change("transaction", state))
            self.transaction_feed.add_error_handler(lambda error: self._on_connection_error("transaction", error))
            
            self.logger.info("✅ Dual WebSocket Feed Manager initialized with database storage integration")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Dual WebSocket Feed Manager: {e}")
            raise

    async def start(self):
        """Start both WebSocket feeds and database storage"""
        try:
            self.logger.info("🚀 Starting Dual WebSocket Feed Manager with database integration...")
            
            # Load tracked tokens from database
            await self._refresh_tracked_tokens()
            
            if len(self.tracked_tokens) == 0:
                self.logger.warning("⚠️ No tracked tokens found - cannot start WebSocket feeds")
                return
            
            # Start background processing tasks
            self.database_writer_task = asyncio.create_task(self._database_writer_loop())
            self.price_history_cleaner_task = asyncio.create_task(self._price_history_cleaner_loop())
            self.logger.info("✅ In-memory storage + batch database writing started")
            
            # Start both WebSocket connections
            await self._start_price_feed()
            await self._start_transaction_feed()
            
            self.stats['manager_start_time'] = datetime.utcnow()
            
            active_connections = sum([
                self.stats['price_connection_active'],
                self.stats['transaction_connection_active']
            ])
            
            self.logger.info(f"✅ Dual WebSocket Manager started with {active_connections}/2 connections:")
            self.logger.info(f"   📈 Price feed: {'✅ ACTIVE' if self.stats['price_connection_active'] else '❌ FAILED'} → ohlcv table")
            self.logger.info(f"   💱 Transaction feed: {'✅ ACTIVE' if self.stats['transaction_connection_active'] else '❌ FAILED'} → market_events table")
            self.logger.info(f"   🗄️ Database storage: ✅ ACTIVE")
            self.logger.info(f"   🎯 Monitoring {len(self.tracked_tokens)} tokens")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to start Dual WebSocket Manager: {e}")
            raise

    async def stop(self):
        """Stop all WebSocket feeds and database storage"""
        self.logger.info("🛑 Stopping Dual WebSocket Feed Manager...")
        
        # Stop background processing tasks
        if self.database_writer_task:
            self.database_writer_task.cancel()
        if self.price_history_cleaner_task:
            self.price_history_cleaner_task.cancel()
        
        # Flush remaining data to database
        await self._flush_database_queues()
        
        # Stop price feed
        if self.price_feed:
            try:
                await self.price_feed.stop()
                self.logger.debug("📈 Stopped price feed")
            except Exception as e:
                self.logger.error(f"❌ Error stopping price feed: {e}")
        
        # Stop transaction feed
        if self.transaction_feed:
            try:
                await self.transaction_feed.stop()
                self.logger.debug("💱 Stopped transaction feed")
            except Exception as e:
                self.logger.error(f"❌ Error stopping transaction feed: {e}")
        
        # Clear data
        self.last_prices.clear()
        self.last_transactions.clear()
        self.stats['price_connection_active'] = False
        self.stats['transaction_connection_active'] = False
        
        self.logger.info("✅ Dual WebSocket Manager stopped")

    async def _refresh_tracked_tokens(self):
        """Refresh tracked tokens from database"""
        try:
            if not self.db_manager:
                self.logger.error("Database manager not initialized")
                return
            
            # Get all active tokens that have trading enabled
            query = """
                SELECT symbol, address, name, decimals, lunarcrush_id, social_data_available
                FROM tokens 
                WHERE is_active = true AND trading_enabled = true
                ORDER BY symbol
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                rows = await conn.fetch(query)
            
            # Update tracked tokens
            self.tracked_tokens.clear()
            for row in rows:
                self.tracked_tokens[row['symbol']] = {
                    'symbol': row['symbol'],
                    'address': row['address'],
                    'name': row['name'],
                    'decimals': row['decimals'],
                    'lunarcrush_id': row['lunarcrush_id'],
                    'social_data_available': row['social_data_available']
                }
            
            self.stats['tokens_tracked'] = len(self.tracked_tokens)
            self.stats['last_token_refresh'] = datetime.utcnow()
            
            self.logger.info(f"📊 Refreshed {len(self.tracked_tokens)} tracked tokens")
            self.logger.debug(f"Tracked tokens: {list(self.tracked_tokens.keys())}")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to refresh tracked tokens: {e}")

    async def _start_price_feed(self):
        """Start price feed with complex query for all tokens"""
        try:
            if not self.price_feed:
                self.logger.error("Price feed not initialized")
                return
            
            # Start connection
            await self.price_feed.start()
            
            # Build complex query for all tokens (BirdEye format)
            # Format: "(address = TOKEN1 AND chartType = 1m AND currency = usd) OR (address = TOKEN2 AND chartType = 1m AND currency = usd) OR ..."
            query_parts = []
            for token_info in self.tracked_tokens.values():
                query_parts.append(f"(address = {token_info['address']} AND chartType = 1m AND currency = usd)")
            
            complex_query = " OR ".join(query_parts)
            
            # Create complex subscription
            subscription = PriceSubscription(
                query_type="complex",
                query=complex_query
            )
            
            # Subscribe to all tokens at once
            success = await self.price_feed.subscribe_price(subscription)
            
            if success:
                self.stats['price_connection_active'] = True
                self.logger.info(f"📈✅ Price feed connected - subscribed to {len(self.tracked_tokens)} tokens")
            else:
                self.logger.error("📈❌ Price feed subscription failed")
                
        except Exception as e:
            self.logger.error(f"📈❌ Failed to start price feed: {e}")

    async def _start_transaction_feed(self):
        """Start transaction feed with complex query for all tokens"""
        try:
            if not self.transaction_feed:
                self.logger.error("Transaction feed not initialized")
                return
            
            # Start connection
            await self.transaction_feed.start()
            
            # Build complex query for all tokens (BirdEye format)
            # Format: "address = TOKEN1 OR address = TOKEN2 OR address = TOKEN3 OR ..."
            query_parts = []
            for token_info in self.tracked_tokens.values():
                query_parts.append(f"address = {token_info['address']}")
            
            complex_query = " OR ".join(query_parts)
            
            # Create complex subscription
            subscription = TransactionSubscription(
                query_type="complex",
                query=complex_query
            )
            
            # Subscribe to all tokens at once
            success = await self.transaction_feed.subscribe_transactions(subscription)
            
            if success:
                self.stats['transaction_connection_active'] = True
                self.logger.info(f"💱✅ Transaction feed connected - subscribed to {len(self.tracked_tokens)} tokens")
            else:
                self.logger.error("💱❌ Transaction feed subscription failed")
                
        except Exception as e:
            self.logger.error(f"💱❌ Failed to start transaction feed: {e}")

    async def _on_price_update_with_storage(self, price_update: PriceUpdate):
        """Handle price updates with in-memory storage and batch database writes"""
        try:
            symbol = price_update.symbol
            current_time = price_update.timestamp
            current_price = price_update.close_price
            
            # 🆕 UPDATE IN-MEMORY STORAGE FOR EMERGENCY MONITORING
            self.current_prices[symbol] = current_price
            self.last_prices[symbol] = price_update
            
            # 🆕 MAINTAIN PRICE HISTORY FOR VOLATILITY CALCULATIONS
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            
            self.price_history[symbol].append((current_time, current_price))
            
            # Keep only last 24 hours of history (for volatility calculations)
            cutoff_time = current_time - timedelta(hours=24)
            self.price_history[symbol] = [
                (t, p) for t, p in self.price_history[symbol] if t > cutoff_time
            ]
            
            # 🆕 UPDATE CURRENT CANDLE (for real-time access)
            self.current_candles[symbol] = {
                'timestamp': current_time,
                'open': price_update.open_price,
                'high': price_update.high_price,
                'low': price_update.low_price,
                'close': price_update.close_price,
                'volume': price_update.volume,
                'symbol': symbol
            }
            
            # 🆕 QUEUE FOR BATCH DATABASE WRITE (instead of immediate write)
            await self._queue_ohlcv_data(price_update)
            
            self.stats['price_updates_received'] += 1
            self.stats['current_candles_count'] = len(self.current_candles)
            self.stats['price_history_points'] = sum(len(history) for history in self.price_history.values())
            
            # Debug log every 50th update to avoid spam
            if self.stats['price_updates_received'] % 50 == 0:
                self.logger.debug(f"📈 Processed {self.stats['price_updates_received']} price updates → in-memory + batch queue")
            
            # Notify all price handlers (including emergency monitoring)
            for handler in self.price_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(symbol, price_update)
                    else:
                        handler(symbol, price_update)
                except Exception as e:
                    self.logger.error(f"❌ Error in price handler: {e}")
                    
        except Exception as e:
            self.logger.error(f"❌ Error processing price update: {e}")

    async def _queue_ohlcv_data(self, price_update: PriceUpdate):
        """Queue OHLCV data for batch database write"""
        try:
            # Find token info by address
            token_info = None
            for info in self.tracked_tokens.values():
                if info['address'] == price_update.address:
                    token_info = info
                    break
            
            if not token_info:
                return  # Skip unknown tokens silently
            
            # Add to batch queue
            ohlcv_data = {
                'timestamp': price_update.timestamp,
                'address': price_update.address,
                'symbol': price_update.symbol,
                'open': price_update.open_price,
                'high': price_update.high_price,
                'low': price_update.low_price,
                'close': price_update.close_price,
                'volume': price_update.volume,
                'data_source': 'birdeye_websocket'
            }
            
            self.ohlcv_write_queue.append(ohlcv_data)
            self.stats['ohlcv_writes_batched'] += 1
                
        except Exception as e:
            self.logger.error(f"❌ Failed to queue OHLCV data: {e}")

    async def _on_transaction_update_with_storage(self, transaction_update: TransactionUpdate):
        """Handle transaction updates with database storage and caching"""
        try:
            # Store in memory for immediate access
            symbol = None
            
            # Check if we can find the symbol from the transaction data
            for tracked_symbol, token_info in self.tracked_tokens.items():
                if (transaction_update.from_address == token_info['address'] or 
                    transaction_update.to_address == token_info['address'] or
                    transaction_update.token_address == token_info['address']):
                    symbol = tracked_symbol
                    break
            
            if not symbol:
                # Fallback: use the symbol from transaction data if available
                symbol = transaction_update.from_symbol or transaction_update.to_symbol or "UNKNOWN"
            
            # Store in memory for immediate access
            self.last_transactions[symbol] = transaction_update
            self.stats['transaction_updates_received'] += 1
            
            # CRITICAL: Queue transaction data for batch write to market_events table
            await self._queue_market_event_data(transaction_update)
            
            # Debug log every 20th transaction
            if self.stats['transaction_updates_received'] % 20 == 0:
                self.logger.debug(f"💱 Processed {self.stats['transaction_updates_received']} transaction updates → market_events table")
            
            # Notify all transaction handlers
            for handler in self.transaction_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(symbol, transaction_update)
                    else:
                        handler(symbol, transaction_update)
                except Exception as e:
                    self.logger.error(f"❌ Error in transaction handler: {e}")
                    
        except Exception as e:
            self.logger.error(f"❌ Error processing transaction update: {e}")

    async def _queue_market_event_data(self, transaction_update: TransactionUpdate):
        """Queue transaction data for batch write to market_events table"""
        try:
            # Find token by any of the addresses in the transaction
            token_address = (transaction_update.token_address or 
                           transaction_update.from_address or 
                           transaction_update.to_address)
            
            if not token_address:
                return  # Skip transactions without token addresses
            
            # Create structured event data for feature engineering
            event_data = {
                'tx_hash': transaction_update.tx_hash,
                'side': transaction_update.side,
                'trader': transaction_update.owner,
                'platform': transaction_update.platform,
                'price_pair': transaction_update.price_pair,
                'token_price': transaction_update.token_price,
                'volume_usd': transaction_update.volume_usd,
                'network': transaction_update.network,
                'pool_id': transaction_update.pool_id,
                'from_token': {
                    'address': transaction_update.from_address,
                    'symbol': transaction_update.from_symbol,
                    'amount': transaction_update.from_amount,
                    'ui_amount': transaction_update.from_ui_amount,
                    'price': transaction_update.from_price,
                    'decimals': transaction_update.from_decimals,
                },
                'to_token': {
                    'address': transaction_update.to_address,
                    'symbol': transaction_update.to_symbol,
                    'amount': transaction_update.to_amount,
                    'ui_amount': transaction_update.to_ui_amount,
                    'price': transaction_update.to_price,
                    'decimals': transaction_update.to_decimals,
                }
            }
            
            # Add to batch queue
            market_event_data = {
                'event_time': datetime.fromtimestamp(transaction_update.block_unix_time),
                'token_address': token_address,
                'event_type': 'transaction',
                'event_data': event_data,
                'size_usd': transaction_update.volume_usd,
                'source': 'birdeye_websocket',
                'raw_data': transaction_update.raw_data
            }
            
            self.market_events_queue.append(market_event_data)
            self.stats['market_events_batched'] += 1
                
        except Exception as e:
            self.logger.error(f"❌ Failed to queue market event data: {e}")

    def _on_connection_change(self, feed_type: str, state: ConnectionState):
        """Handle connection state changes"""
        self.logger.debug(f"📡 {feed_type.title()} feed: {state.value}")
        
        # Update connection status
        if feed_type == "price":
            self.stats['price_connection_active'] = (state == ConnectionState.CONNECTED)
        elif feed_type == "transaction":
            self.stats['transaction_connection_active'] = (state == ConnectionState.CONNECTED)
        
        # Notify connection handlers
        for handler in self.connection_handlers:
            try:
                handler(state)
            except Exception as e:
                self.logger.error(f"❌ Error in connection handler: {e}")

    def _on_connection_error(self, feed_type: str, error: Exception):
        """Handle connection errors"""
        self.logger.error(f"📡❌ {feed_type.title()} feed error: {error}")
        self.stats['connection_errors'] += 1

    # Public API methods
    def add_price_handler(self, handler: Callable[[str, PriceUpdate], None]):
        """Add price update handler"""
        self.price_handlers.append(handler)

    def add_transaction_handler(self, handler: Callable[[str, TransactionUpdate], None]):
        """Add transaction update handler"""
        self.transaction_handlers.append(handler)

    def add_connection_handler(self, handler: Callable[[ConnectionState], None]):
        """Add connection state handler"""
        self.connection_handlers.append(handler)

    def get_latest_price(self, symbol: str) -> Optional[PriceUpdate]:
        """Get latest price for a symbol"""
        return self.last_prices.get(symbol)

    def get_latest_transaction(self, symbol: str) -> Optional[TransactionUpdate]:
        """Get latest transaction for a symbol"""
        return self.last_transactions.get(symbol)

    def get_all_latest_prices(self) -> Dict[str, PriceUpdate]:
        """Get all latest prices"""
        return self.last_prices.copy()

    def get_all_latest_transactions(self) -> Dict[str, TransactionUpdate]:
        """Get all latest transactions"""
        return self.last_transactions.copy()

    def get_stats(self) -> Dict:
        """Get comprehensive feed manager statistics"""
        uptime = None
        if self.stats['manager_start_time']:
            uptime = (datetime.utcnow() - self.stats['manager_start_time']).total_seconds()
        
        base_stats = {
            **self.stats,
            'active_connections': sum([
                self.stats['price_connection_active'],
                self.stats['transaction_connection_active']
            ]),
            'expected_connections': 2,
            'prices_cached': len(self.last_prices),
            'transactions_cached': len(self.last_transactions),
            'uptime_seconds': uptime
        }
        
        # Add in-memory storage statistics  
        base_stats['memory_storage'] = self.get_memory_stats()
        
        return base_stats

    async def refresh_tokens(self):
        """Manually refresh tracked tokens and restart connections"""
        self.logger.info("🔄 Manually refreshing tracked tokens and restarting connections...")
        
        # Stop existing connections
        await self.stop()
        
        # Refresh tokens and restart
        await self._refresh_tracked_tokens()
        await self._start_price_feed()
        await self._start_transaction_feed()
        
        self.logger.info("✅ Token refresh and connection restart complete")

    # =========================================================================
    # BACKGROUND PROCESSING TASKS
    # =========================================================================

    async def _database_writer_loop(self):
        """Background task to write batched data to database"""
        while True:
            try:
                await asyncio.sleep(self.batch_timeout)
                
                # Write OHLCV data in batches
                if self.ohlcv_write_queue:
                    await self._write_ohlcv_batch()
                
                # Write market events in batches
                if self.market_events_queue:
                    await self._write_market_events_batch()
                    
            except asyncio.CancelledError:
                # Final flush before shutdown
                await self._flush_database_queues()
                break
            except Exception as e:
                self.logger.error(f"❌ Database writer loop error: {e}")
                await asyncio.sleep(5)  # Brief pause before retry

    async def _write_ohlcv_batch(self):
        """Write batched OHLCV data to database"""
        if not self.ohlcv_write_queue or not self.db_manager:
            return
        
        try:
            # Extract batch
            batch = self.ohlcv_write_queue[:self.batch_size]
            self.ohlcv_write_queue = self.ohlcv_write_queue[self.batch_size:]
            
            if not batch:
                return
            
            async with self.db_manager.pg_pool.acquire() as conn:
                # Get token IDs for all addresses in batch
                address_to_token_id = {}
                unique_addresses = list(set(item['address'] for item in batch))
                
                for address in unique_addresses:
                    token_row = await conn.fetchrow(
                        "SELECT token_id FROM tokens WHERE address = $1", address
                    )
                    if token_row:
                        address_to_token_id[address] = token_row['token_id']
                
                # Prepare batch insert data
                insert_data = []
                for item in batch:
                    token_id = address_to_token_id.get(item['address'])
                    if token_id:
                        insert_data.append((
                            item['timestamp'],      # time
                            token_id,              # token_id
                            '1m',                  # resolution
                            item['open'],          # open
                            item['high'],          # high
                            item['low'],           # low
                            item['close'],         # close
                            item['volume'],        # volume
                            None,                  # volume_usd (not provided by BirdEye)
                            item['data_source']    # data_source
                        ))
                
                # Batch insert
                if insert_data:
                    await conn.executemany("""
                        INSERT INTO ohlcv (time, token_id, resolution, open, high, low, close, volume, volume_usd, data_source)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        ON CONFLICT (time, token_id, resolution) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume,
                            data_source = EXCLUDED.data_source
                    """, insert_data)
                    
                    self.stats['database_writes_executed'] += 1
                    self.logger.debug(f"📊 Wrote {len(insert_data)} OHLCV records to database")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to write OHLCV batch: {e}")

    async def _write_market_events_batch(self):
        """Write batched market events to database"""
        if not self.market_events_queue or not self.db_manager:
            return
        
        try:
            # Extract batch
            batch = self.market_events_queue[:self.batch_size]
            self.market_events_queue = self.market_events_queue[self.batch_size:]
            
            if not batch:
                return
            
            async with self.db_manager.pg_pool.acquire() as conn:
                # Get token IDs for all addresses in batch
                address_to_token_id = {}
                unique_addresses = list(set(item['token_address'] for item in batch))
                
                for address in unique_addresses:
                    token_row = await conn.fetchrow(
                        "SELECT token_id FROM tokens WHERE address = $1", address
                    )
                    if token_row:
                        address_to_token_id[address] = token_row['token_id']
                
                # Prepare batch insert data
                insert_data = []
                for item in batch:
                    token_id = address_to_token_id.get(item['token_address'])
                    if token_id:
                        insert_data.append((
                            item['event_time'],                                              # event_time
                            token_id,                                                       # token_id
                            item['event_type'],                                             # event_type
                            json.dumps(item['event_data']),                                 # event_data (JSONB)
                            item['size_usd'],                                               # size_usd
                            item['source'],                                                 # source
                            json.dumps(item['raw_data']) if item['raw_data'] else None     # raw_data
                        ))
                
                # Batch insert
                if insert_data:
                    await conn.executemany("""
                        INSERT INTO market_events (event_time, token_id, event_type, event_data, size_usd, source, raw_data)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT DO NOTHING
                    """, insert_data)
                    
                    self.stats['database_writes_executed'] += 1
                    self.logger.debug(f"💱 Wrote {len(insert_data)} market events to database")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to write market events batch: {e}")

    async def _price_history_cleaner_loop(self):
        """Background task to clean up old price history data"""
        while True:
            try:
                await asyncio.sleep(300)  # Clean every 5 minutes
                
                # Clean price history older than 24 hours
                current_time = datetime.utcnow()
                cutoff_time = current_time - timedelta(hours=24)
                
                for symbol in list(self.price_history.keys()):
                    if symbol in self.price_history:
                        self.price_history[symbol] = [
                            (t, p) for t, p in self.price_history[symbol] if t > cutoff_time
                        ]
                        
                        # Remove empty histories
                        if not self.price_history[symbol]:
                            del self.price_history[symbol]
                
                # Update stats
                self.stats['price_history_points'] = sum(len(history) for history in self.price_history.values())
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"❌ Price history cleaner error: {e}")
                await asyncio.sleep(60)  # Brief pause before retry

    async def _flush_database_queues(self):
        """Flush all remaining data to database before shutdown"""
        try:
            self.logger.info("🗄️ Flushing remaining database queues...")
            
            # Write any remaining OHLCV data
            while self.ohlcv_write_queue:
                await self._write_ohlcv_batch()
            
            # Write any remaining market events
            while self.market_events_queue:
                await self._write_market_events_batch()
            
            self.logger.info("✅ Database queues flushed")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to flush database queues: {e}")

    # =========================================================================
    # PUBLIC API FOR EMERGENCY MONITORING
    # =========================================================================

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price for emergency monitoring (fast in-memory access)"""
        return self.current_prices.get(symbol)

    def get_price_history(self, symbol: str, hours: int = 24) -> List[Tuple[datetime, float]]:
        """Get price history for volatility calculations (fast in-memory access)"""
        if symbol not in self.price_history:
            return []
        
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        return [(t, p) for t, p in self.price_history[symbol] if t > cutoff_time]

    def get_current_candle(self, symbol: str) -> Optional[Dict]:
        """Get current 1-minute candle data (fast in-memory access)"""
        return self.current_candles.get(symbol)

    def get_all_current_prices(self) -> Dict[str, float]:
        """Get all current prices (fast in-memory access)"""
        return self.current_prices.copy()

    def get_memory_stats(self) -> Dict:
        """Get in-memory storage statistics"""
        return {
            'current_prices_count': len(self.current_prices),
            'current_candles_count': len(self.current_candles),
            'price_history_symbols': len(self.price_history),
            'total_price_history_points': sum(len(history) for history in self.price_history.values()),
            'ohlcv_queue_size': len(self.ohlcv_write_queue),
            'market_events_queue_size': len(self.market_events_queue)
        }


# Update WebSocketFeedManager to use the new dual manager
WebSocketFeedManager = DualWebSocketFeedManager

__all__ = [
    'BirdEyeWebSocketFeed',
    'ConnectionConfig', 
    'ConnectionState',
    'PriceUpdate',
    'PriceSubscription',
    'TransactionUpdate',
    'TransactionSubscription',
    'WebSocketFeedManager'
] 