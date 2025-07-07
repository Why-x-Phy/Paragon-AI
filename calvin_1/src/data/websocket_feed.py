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
    
    def __init__(self, config: ConnectionConfig, feed_name: str = "WebSocket"):
        self.config = config
        self.feed_name = feed_name
        
        # Use log_manager for consistent logging
        from ..utils.logger import log_manager
        self.logger = log_manager.get_logger(f"websocket_feed.{feed_name}")
        
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
        
        # Validate subscription data
        if subscription.query_type != "complex" and not subscription.address.strip():
            self.logger.error("Cannot subscribe: empty token address")
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
            self.logger.debug(f"Subscribed to price updates: {subscription.address}")
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
            # Commented out to reduce log spam - uncomment for debugging WebSocket issues
            # self.logger.debug(f"📨 Received WebSocket message: type='{message_type}', data_keys={list(data.keys())}")
            
            # Update heartbeat timestamp
            self.last_heartbeat = time.time()
            
            # Handle different message types
            if message_type == 'PRICE_DATA':
                await self._handle_price_data(data)
            elif message_type == 'TXS_DATA':
                await self._handle_transaction_data(data)
            else:
                # Handle other message types or log unknown types
                self.logger.debug(f"📋 Unknown message type '{message_type}': {data}")
                
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
        """Monitor connection health based on received messages"""
        while self.connection_state == ConnectionState.CONNECTED:
            try:
                await asyncio.sleep(self.config.heartbeat_interval)
                
                # Check if we've received recent messages
                time_since_heartbeat = time.time() - self.last_heartbeat
                heartbeat_threshold = self.config.heartbeat_interval * 4  # More lenient threshold (4x interval)
                
                if time_since_heartbeat > heartbeat_threshold:
                    self.logger.warning(f"[{self.feed_name}] No data received for {time_since_heartbeat:.1f}s, connection may be stale")
                    
                    # Check if connection is actually dead before reconnecting
                    if self.ws_connection and self.ws_connection.closed:
                        self.logger.info(f"[{self.feed_name}] WebSocket connection is closed, reconnecting...")
                        await self._graceful_reconnect()
                    else:
                        # Connection appears open but no data - this is normal for some feeds
                        self.logger.debug(f"[{self.feed_name}] Connection open but quiet - this may be normal")
                    
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

    async def _graceful_reconnect(self):
        """Graceful reconnection that doesn't interfere with database operations"""
        try:
            self.logger.info("Starting graceful WebSocket reconnection...")
            
            # Cancel existing tasks gracefully
            if self.processing_task and not self.processing_task.done():
                self.processing_task.cancel()
                try:
                    await asyncio.wait_for(self.processing_task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            
            if self.heartbeat_task and not self.heartbeat_task.done():
                self.heartbeat_task.cancel()
                try:
                    await asyncio.wait_for(self.heartbeat_task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            
            # Close existing connection
            if self.ws_connection and not self.ws_connection.closed:
                await self.ws_connection.close()
            
            # Wait a moment for cleanup
            await asyncio.sleep(1.0)
            
            # Reset connection state
            self._set_connection_state(ConnectionState.DISCONNECTED)
            
            # Attempt reconnection with backoff
            await self._reconnect()
            
        except Exception as e:
            self.logger.error(f"Graceful reconnection failed: {e}")
            self._set_connection_state(ConnectionState.ERROR)

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
            
            # Store subscriptions before clearing (to avoid duplication)
            subscriptions_to_restore = self.active_subscriptions.copy()
            self.active_subscriptions.clear()
            
            # Re-subscribe to all previous subscriptions
            for subscription in subscriptions_to_restore:
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

    def update_api_key(self, new_api_key: str):
        """Update the API key for this WebSocket feed"""
        if new_api_key != self.config.api_key:
            old_key_masked = self.config.api_key[:8] + "..." + self.config.api_key[-4:]
            new_key_masked = new_api_key[:8] + "..." + new_api_key[-4:]
            self.logger.info(f"🔑 Updating API key from {old_key_masked} to {new_key_masked}")
            self.config.api_key = new_api_key
            
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

    async def monitor_transaction_feed_health(self):
        """Monitor transaction feed health and reconnect if needed"""
        try:
            if not self.transaction_feed:
                return False
                
            # Check connection state
            is_connected = (self.transaction_feed.connection_state == ConnectionState.CONNECTED)
            
            # Check if we're receiving updates
            current_tx_count = self.stats['transaction_updates_received']
            
            # If we haven't received any transactions in 5 minutes, something might be wrong
            if hasattr(self, '_last_tx_count_check'):
                if current_tx_count == self._last_tx_count_check:
                    self.logger.warning("⚠️ No transaction updates received in monitoring period")
                    # Try to reconnect
                    await self.transaction_feed.stop()
                    await asyncio.sleep(2)
                    await self._start_transaction_feed()
                    return False
            
            self._last_tx_count_check = current_tx_count
            return is_connected
            
        except Exception as e:
            self.logger.error(f"❌ Error monitoring transaction feed: {e}")
            return False


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
        # Use log_manager for consistent logging
        from ..utils.logger import log_manager
        self.logger = log_manager.get_logger("websocket_feed.manager")
        self.db_manager = None
        
        # Dual WebSocket feeds
        self.price_feed: Optional[BirdEyeWebSocketFeed] = None      # For OHLCV data
        self.transaction_feed: Optional[BirdEyeWebSocketFeed] = None # For TXS data
        
        # 🆕 IN-MEMORY STORAGE FOR EMERGENCY MONITORING (MEMORY LEAK FIXES)
        self.current_prices: Dict[str, float] = {}                 # symbol -> latest_price
        self.price_history: Dict[str, List[Tuple[datetime, float]]] = {}  # symbol -> [(time, price), ...]
        self.current_candles: Dict[str, Dict] = {}                 # symbol -> current_1min_candle
        
        # 🆕 BATCH PROCESSING QUEUES (MEMORY LEAK FIXES)
        self.ohlcv_write_queue: List[Dict] = []                    # Batched OHLCV data for DB
        self.market_events_queue: List[Dict] = []                  # Batched market events for DB
        self.batch_size = 200                                      # Write batches of 200 items (increased from 50)
        self.batch_timeout = 15.0                                  # Write every 15 seconds (faster cleanup)
        
        # 🚨 MEMORY LEAK PREVENTION LIMITS
        self.max_price_history_per_token = 100                     # Only keep last 100 price points per token (vs unlimited)
        self.max_queue_size = 2000                                  # Increased from 500 to handle 19 individual subscriptions
        self.price_history_cleanup_interval = 60                   # Clean every 1 minute (vs 5 minutes)
        self.min_batch_size = 100  # Minimum batch size before writing (increased from 50)
        self.batch_write_interval = 15.0  # Decreased from 30s to write more frequently
        
        # Tracked tokens and data
        self.tracked_tokens: Dict[str, Dict] = {}  # symbol -> token_info
        self.last_prices: Dict[str, PriceUpdate] = {}  # symbol -> latest_price_update
        self.last_transactions: Dict[str, TransactionUpdate] = {}
        
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
            'price_history_points': 0,
            'memory_cleanups_performed': 0,
            'queue_overflows_prevented': 0
        }
        
        # API key rotation for resilience
        self.available_api_keys = []
        self.current_price_key_index = 0
        self.current_transaction_key_index = 0
        self.api_key_rotation_enabled = False
        
        self.logger.info("🚀 Dual WebSocket Feed Manager initialized with MEMORY LEAK PROTECTION")

    async def initialize(self):
        """Initialize the dual feed manager with database storage integration"""
        try:
            # Import here to avoid circular imports
            from ..database.production_db import get_db_manager
            from ..config.config import config
            from .realtime_storage import RealtimeDataStorage
            
            # Initialize database manager
            self.db_manager = await get_db_manager()
            
            # Collect all available API keys for rotation
            self.available_api_keys = []
            for i in range(1, 8):  # Check BIRDEYE_API_KEY through BIRDEYE_API_KEY_7
                key_name = 'BIRDEYE_API_KEY' if i == 1 else f'BIRDEYE_API_KEY_{i}'
                api_key = config.get(key_name)
                if api_key and api_key.strip():
                    self.available_api_keys.append(api_key.strip())
            
            if not self.available_api_keys:
                raise ValueError("At least one BIRDEYE_API_KEY is required for WebSocket feeds")
            
            # Use first key for price feed, fifth key (or second available) for transaction feed
            api_key_1 = self.available_api_keys[0]
            api_key_5 = self.available_api_keys[min(4, len(self.available_api_keys) - 1)]  # Use 5th key or last available
            
            # Enable API key rotation if we have multiple keys
            self.api_key_rotation_enabled = len(self.available_api_keys) > 1
            
            # Log which keys are being used (masked for security)
            key_1_masked = api_key_1[:8] + "..." + api_key_1[-4:] if api_key_1 else "None"
            key_5_masked = api_key_5[:8] + "..." + api_key_5[-4:] if api_key_5 else "None"
            self.logger.info(f"🔑 Found {len(self.available_api_keys)} API keys, rotation {'ENABLED' if self.api_key_rotation_enabled else 'DISABLED'}")
            self.logger.info(f"🔑 API key distribution: Price feed using {key_1_masked}, Transaction feed using {key_5_masked}")
            
            # Create configuration for both feeds
            price_config = ConnectionConfig(
                api_key=api_key_1,
                chain="solana",
                reconnect_delay=1.0,                  # Reasonable reconnection delay
                max_reconnect_attempts=10,            # Reasonable attempts
                heartbeat_interval=60.0,              # Check every minute for stale connections
                message_queue_size=2000
            )
            
            transaction_config = ConnectionConfig(
                api_key=api_key_5,  # Use 5th key to distribute load away from main key
                chain="solana",
                reconnect_delay=1.0,                  # Reasonable reconnection delay
                max_reconnect_attempts=10,            # Reasonable attempts
                heartbeat_interval=90.0,              # Check every 1.5 minutes (transactions can be sporadic)
                message_queue_size=2000
            )
            
            # Initialize both WebSocket feeds with descriptive names
            self.price_feed = BirdEyeWebSocketFeed(price_config, "PriceFeed")
            self.transaction_feed = BirdEyeWebSocketFeed(transaction_config, "TransactionFeed")
            
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
        
    def _rotate_api_key(self, feed_type: str) -> Optional[str]:
        """Rotate to next available API key for the specified feed type"""
        if not self.api_key_rotation_enabled or len(self.available_api_keys) < 2:
            return None
            
        if feed_type == "price":
            self.current_price_key_index = (self.current_price_key_index + 1) % len(self.available_api_keys)
            new_key = self.available_api_keys[self.current_price_key_index]
            self.logger.info(f"🔄 Rotating price feed to API key {self.current_price_key_index + 1}")
            return new_key
        elif feed_type == "transaction":
            self.current_transaction_key_index = (self.current_transaction_key_index + 1) % len(self.available_api_keys)
            new_key = self.available_api_keys[self.current_transaction_key_index]
            self.logger.info(f"🔄 Rotating transaction feed to API key {self.current_transaction_key_index + 1}")
            return new_key
        return None

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
        """Start price feed with individual subscriptions for better reliability"""
        try:
            if not self.price_feed:
                self.logger.error("Price feed not initialized")
                return
            
            # Start connection
            await self.price_feed.start()
            
            # Subscribe to each token individually for better reliability
            # Complex queries seem to cause issues with BirdEye API
            successful_subscriptions = 0
            failed_subscriptions = 0
            
            for symbol, token_info in self.tracked_tokens.items():
                try:
                    # Validate token address before subscribing
                    token_address = token_info.get('address', '').strip()
                    if not token_address:
                        self.logger.warning(f"⚠️ Skipping {symbol} - empty token address")
                        failed_subscriptions += 1
                        continue
                    
                    # Create simple subscription for each token
                    subscription = PriceSubscription(
                        query_type="simple",
                        chart_type="1m",
                        address=token_address,
                        currency="usd"
                    )
                    
                    # Subscribe with a small delay between subscriptions
                    success = await self.price_feed.subscribe_price(subscription)
                    
                    if success:
                        successful_subscriptions += 1
                        self.logger.debug(f"✅ Subscribed to {symbol} price updates")
                    else:
                        failed_subscriptions += 1
                        self.logger.warning(f"❌ Failed to subscribe to {symbol} price updates")
                    
                    # Small delay to avoid overwhelming the API
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    failed_subscriptions += 1
                    self.logger.error(f"❌ Error subscribing to {symbol} price updates: {e}")
            
            if successful_subscriptions > 0:
                self.stats['price_connection_active'] = True
                self.logger.info(f"📈✅ Price feed connected - subscribed to {successful_subscriptions}/{len(self.tracked_tokens)} tokens")
                if failed_subscriptions > 0:
                    self.logger.warning(f"⚠️ Failed to subscribe to {failed_subscriptions} tokens")
            else:
                self.logger.error("📈❌ All price subscriptions failed")
                
        except Exception as e:
            self.logger.error(f"📈❌ Failed to start price feed: {e}")

    async def _start_transaction_feed(self):
        """Start transaction feed with individual subscriptions for better reliability"""
        try:
            if not self.transaction_feed:
                self.logger.error("Transaction feed not initialized")
                return
            
            # Start connection
            await self.transaction_feed.start()
            
            # Subscribe to each token individually for better reliability
            # BirdEye docs show that simple queries have better field support
            successful_subscriptions = 0
            failed_subscriptions = 0
            
            for symbol, token_info in self.tracked_tokens.items():
                try:
                    # Create simple subscription for each token
                    subscription = TransactionSubscription(
                        query_type="simple",
                        address=token_info['address']
                    )
                    
                    # Subscribe with a small delay between subscriptions
                    success = await self.transaction_feed.subscribe_transactions(subscription)
                    
                    if success:
                        successful_subscriptions += 1
                        self.logger.debug(f"✅ Subscribed to {symbol} transactions")
                    else:
                        failed_subscriptions += 1
                        self.logger.warning(f"❌ Failed to subscribe to {symbol} transactions")
                    
                    # Small delay to avoid overwhelming the API
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    failed_subscriptions += 1
                    self.logger.error(f"❌ Error subscribing to {symbol} transactions: {e}")
            
            if successful_subscriptions > 0:
                self.stats['transaction_connection_active'] = True
                self.logger.info(f"💱✅ Transaction feed connected - subscribed to {successful_subscriptions}/{len(self.tracked_tokens)} tokens")
                if failed_subscriptions > 0:
                    self.logger.warning(f"⚠️ Failed to subscribe to {failed_subscriptions} tokens")
            else:
                self.logger.error("💱❌ All transaction subscriptions failed")
                
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
            
            # 🆕 MAINTAIN PRICE HISTORY WITH MEMORY LEAK PROTECTION
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            
            self.price_history[symbol].append((current_time, current_price))
            
            # 🚨 MEMORY LEAK FIX: Limit price history size immediately
            if len(self.price_history[symbol]) > self.max_price_history_per_token:
                # Keep only the most recent entries
                self.price_history[symbol] = self.price_history[symbol][-self.max_price_history_per_token:]
            
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
            
            # 🆕 QUEUE FOR BATCH DATABASE WRITE WITH OVERFLOW PROTECTION
            await self._queue_ohlcv_data_with_protection(price_update)
            
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

    async def _queue_ohlcv_data_with_protection(self, price_update: PriceUpdate):
        """Queue OHLCV data for batch database write with overflow protection"""
        try:
            # 🚨 MEMORY LEAK FIX: Prevent unbounded queue growth
            if len(self.ohlcv_write_queue) >= self.max_queue_size:
                self.logger.warning(f"🚨 OHLCV queue overflow ({len(self.ohlcv_write_queue)} items) - forcing immediate write")
                await self._write_ohlcv_batch()
                self.stats['queue_overflows_prevented'] += 1
            
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
        """Handle transaction updates with in-memory storage and batch database writes"""
        try:
            # 🚨 MEMORY LEAK FIX: Prevent unbounded queue growth
            if len(self.market_events_queue) >= self.max_queue_size:
                self.logger.warning(f"🚨 Market events queue overflow ({len(self.market_events_queue)} items) - forcing immediate write")
                await self._write_market_events_batch()
                self.stats['queue_overflows_prevented'] += 1
            
            # Find token info - try multiple fields since complex queries might not have tokenAddress
            token_info = None
            token_address = None
            
            # Try tokenAddress first (simple query)
            if transaction_update.token_address:
                token_address = transaction_update.token_address
                for info in self.tracked_tokens.values():
                    if info['address'] == token_address:
                        token_info = info
                        break
            
            # If not found, try from_address (complex query or swap)
            if not token_info and transaction_update.from_address:
                for info in self.tracked_tokens.values():
                    if info['address'] == transaction_update.from_address:
                        token_info = info
                        token_address = transaction_update.from_address
                        break
            
            # If still not found, try to_address
            if not token_info and transaction_update.to_address:
                for info in self.tracked_tokens.values():
                    if info['address'] == transaction_update.to_address:
                        token_info = info
                        token_address = transaction_update.to_address
                        break
            
            if not token_info:
                # Log once in a while to avoid spam
                if self.stats['transaction_updates_received'] % 100 == 0:
                    self.logger.debug(f"Skipping unknown token transaction: from={transaction_update.from_symbol}, to={transaction_update.to_symbol}")
                return  # Skip unknown tokens silently
            
            # Update last transaction cache
            self.last_transactions[token_info['symbol']] = transaction_update
            
            # Determine transaction side if not provided (for complex queries)
            side = transaction_update.side
            if not side:
                # Infer side based on which token is ours
                if token_address == transaction_update.from_address:
                    side = "sell"
                elif token_address == transaction_update.to_address:
                    side = "buy"
                else:
                    side = "unknown"
            
            # Add to batch queue
            market_event_data = {
                'timestamp': datetime.fromtimestamp(transaction_update.block_unix_time),
                'token_address': token_address,
                'symbol': token_info['symbol'],
                'event_type': 'transaction',
                'event_data': {
                    'tx_hash': transaction_update.tx_hash,
                    'side': side,
                    'trader': transaction_update.owner,
                    'volume_usd': transaction_update.volume_usd,
                    'price': transaction_update.token_price,
                    'from_symbol': transaction_update.from_symbol,
                    'to_symbol': transaction_update.to_symbol,
                    'from_amount': transaction_update.from_ui_amount,
                    'to_amount': transaction_update.to_ui_amount
                },
                'size_usd': transaction_update.volume_usd or 0.0,
                'source': 'birdeye_websocket'
            }
            
            self.market_events_queue.append(market_event_data)
            self.stats['market_events_batched'] += 1
            self.stats['transaction_updates_received'] += 1
            
            # Debug log every 50th update to avoid spam
            if self.stats['transaction_updates_received'] % 50 == 0:
                self.logger.debug(f"💱 Processed {self.stats['transaction_updates_received']} transaction updates → batch queue")
            
            # Notify all transaction handlers
            for handler in self.transaction_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(token_info['symbol'], transaction_update)
                    else:
                        handler(token_info['symbol'], transaction_update)
                except Exception as e:
                    self.logger.error(f"❌ Error in transaction handler: {e}")
                    
        except Exception as e:
            self.logger.error(f"❌ Error processing transaction update: {e}")

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
        """Handle connection errors with API key rotation"""
        self.logger.error(f"📡❌ {feed_type.title()} feed error: {error}")
        self.stats['connection_errors'] += 1
        
        # If we have multiple connection errors, try rotating API key
        if self.stats['connection_errors'] % 3 == 0:  # Every 3rd error
            new_api_key = self._rotate_api_key(feed_type)
            if new_api_key:
                self.logger.info(f"🔄 Attempting API key rotation for {feed_type} feed due to persistent errors")
                # Apply the new API key to the appropriate feed
                if feed_type == "price" and self.price_feed:
                    self.price_feed.update_api_key(new_api_key)
                elif feed_type == "transaction" and self.transaction_feed:
                    self.transaction_feed.update_api_key(new_api_key)

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
        """Background task to periodically write queued data to database"""
        while True:
            try:
                await asyncio.sleep(self.batch_write_interval)  # Use the configurable interval
                
                # Write OHLCV data
                if len(self.ohlcv_write_queue) >= self.min_batch_size:  # Write when we have enough items
                    await self._write_ohlcv_batch()
                
                # Write market events
                if len(self.market_events_queue) >= self.min_batch_size:  # Write when we have enough items
                    await self._write_market_events_batch()
                    
            except Exception as e:
                self.logger.error(f"Database writer error: {e}")
                await asyncio.sleep(5)  # Short delay on error

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
                        # Handle raw_data field - it might not exist
                        raw_data_json = None
                        if 'raw_data' in item and item['raw_data']:
                            raw_data_json = json.dumps(item['raw_data'])
                        
                        insert_data.append((
                            item['timestamp'],                                              # event_time
                            token_id,                                                       # token_id
                            item['event_type'],                                             # event_type
                            json.dumps(item['event_data']),                                # event_data (as JSON)
                            item['size_usd'],                                               # size_usd
                            None,                                                           # impact_score (NULL for now)
                            item.get('source', 'birdeye'),                                 # source
                            raw_data_json                                                   # raw_data
                        ))
                
                # Batch insert
                if insert_data:
                    query = """
                        INSERT INTO market_events (
                            event_time, token_id, event_type, event_data, 
                            size_usd, impact_score, source, raw_data
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """
                    await conn.executemany(query, insert_data)
                    
                    self.stats['database_writes_executed'] += 1
                    self.logger.debug(f"💱 Wrote {len(insert_data)} market events to database")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to write market events batch: {e}")

    async def _price_history_cleaner_loop(self):
        """Background task to clean up old price history data - MEMORY LEAK FIX"""
        while True:
            try:
                await asyncio.sleep(self.price_history_cleanup_interval)  # Clean every 1 minute vs 5 minutes
                
                # 🚨 MEMORY LEAK FIX: Aggressive cleanup
                current_time = datetime.utcnow()
                cutoff_time = current_time - timedelta(hours=1)  # Keep only 1 hour vs 24 hours
                
                cleaned_symbols = 0
                total_points_removed = 0
                
                for symbol in list(self.price_history.keys()):
                    if symbol in self.price_history:
                        original_count = len(self.price_history[symbol])
                        
                        # Remove old entries
                        self.price_history[symbol] = [
                            (t, p) for t, p in self.price_history[symbol] if t > cutoff_time
                        ]
                        
                        # Also enforce max size limit
                        if len(self.price_history[symbol]) > self.max_price_history_per_token:
                            self.price_history[symbol] = self.price_history[symbol][-self.max_price_history_per_token:]
                        
                        points_removed = original_count - len(self.price_history[symbol])
                        total_points_removed += points_removed
                        
                        if points_removed > 0:
                            cleaned_symbols += 1
                        
                        # Remove empty histories
                        if not self.price_history[symbol]:
                            del self.price_history[symbol]
                
                # Update stats
                self.stats['price_history_points'] = sum(len(history) for history in self.price_history.values())
                self.stats['memory_cleanups_performed'] += 1
                
                if total_points_removed > 0:
                    self.logger.info(f"🧹 Memory cleanup: removed {total_points_removed} old price points from {cleaned_symbols} symbols")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"❌ Price history cleaner error: {e}")
                await asyncio.sleep(30)  # Brief pause before retry

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
        """Get in-memory storage statistics with memory leak monitoring"""
        total_memory_objects = (
            len(self.current_prices) +
            len(self.current_candles) +
            sum(len(history) for history in self.price_history.values()) +
            len(self.ohlcv_write_queue) +
            len(self.market_events_queue)
        )
        
        return {
            'current_prices_count': len(self.current_prices),
            'current_candles_count': len(self.current_candles),
            'price_history_symbols': len(self.price_history),
            'total_price_history_points': sum(len(history) for history in self.price_history.values()),
            'ohlcv_queue_size': len(self.ohlcv_write_queue),
            'market_events_queue_size': len(self.market_events_queue),
            'total_memory_objects': total_memory_objects,
            'memory_cleanups_performed': self.stats.get('memory_cleanups_performed', 0),
            'queue_overflows_prevented': self.stats.get('queue_overflows_prevented', 0),
            'max_price_history_per_token': self.max_price_history_per_token,
            'max_queue_size': self.max_queue_size
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