import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Callable, Set
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
        """Reconnect with exponential backoff"""
        self.reconnect_attempts += 1
        self.stats['reconnections'] += 1
        
        delay = min(
            self.config.reconnect_delay * (2 ** (self.reconnect_attempts - 1)),
            self.config.max_reconnect_delay
        )
        
        self.logger.info(f"Reconnecting in {delay}s (attempt {self.reconnect_attempts})")
        await asyncio.sleep(delay)
        
        try:
            # Close existing connection
            if self.ws_connection and not self.ws_connection.closed:
                await self.ws_connection.close()
            
            # Reconnect
            await self._connect()
            
            # Re-subscribe to active subscriptions
            for subscription in self.active_subscriptions:
                await self.subscribe_price(subscription)
                
        except Exception as e:
            self.logger.error(f"Reconnection failed: {e}")
            await self._handle_connection_error(e)

    def _set_connection_state(self, state: ConnectionState):
        """Update connection state and notify handlers"""
        if self.connection_state != state:
            self.logger.info(f"Connection state changed: {self.connection_state.value} -> {state.value}")
            self.connection_state = state
            
            # Notify connection handlers
            for handler in self.connection_handlers:
                try:
                    # Connection handlers are always called synchronously to avoid blocking
                    # If async handlers need to be supported, they should use asyncio.create_task
                    handler(state)
                except Exception as e:
                    self.logger.error(f"Error in connection handler: {e}")

    def get_stats(self) -> Dict:
        """Get connection and processing statistics"""
        return {
            **self.stats,
            'connection_state': self.connection_state.value,
            'active_subscriptions': len(self.active_subscriptions),
            'reconnect_attempts': self.reconnect_attempts
        }

__all__ = [
    'BirdEyeWebSocketFeed',
    'ConnectionConfig', 
    'ConnectionState',
    'PriceUpdate',
    'PriceSubscription',
    'TransactionUpdate',
    'TransactionSubscription'
] 