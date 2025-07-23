"""
Pyth SSE (Server-Sent Events) Client for Real-time Price Streaming

Provides continuous price updates from Pyth's Hermes SSE endpoint as a more reliable
alternative to WebSocket feeds. Handles automatic reconnection after 24 hours.
"""

import asyncio
import aiohttp
import json
import struct
from typing import Dict, List, Optional, Callable, Set, Awaitable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from ..utils.logger import log
from .oracle_handler import TOKEN_ORACLE_HEX_MAPPING

logger = log


class ConnectionState(Enum):
    """SSE connection state"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class PriceUpdate:
    """Price update from Pyth SSE stream"""
    symbol: str
    token_mint: str
    price: float
    confidence: float
    timestamp: datetime
    publish_time: int
    slot: int


class PythSSEClient:
    """
    Client for streaming real-time prices from Pyth's Hermes SSE endpoint
    
    Features:
    - Continuous price streaming via Server-Sent Events
    - Automatic reconnection after 24 hours (Pyth limitation)
    - Symbol to price feed ID mapping
    - Error handling and recovery
    """
    
    HERMES_SSE_ENDPOINT = "https://hermes.pyth.network/v2/updates/price/stream"
    RECONNECT_INTERVAL = timedelta(hours=23, minutes=55)  # Reconnect before 24h limit
    
    def __init__(self):
        """Initialize Pyth SSE client"""
        self.connection_state = ConnectionState.DISCONNECTED
        self.subscribed_tokens: Dict[str, str] = {}  # symbol -> token_mint
        self.price_callbacks: List[Callable[[PriceUpdate], Awaitable[None]]] = []
        self.error_callbacks: List[Callable[[Exception], None]] = []
        
        # Token mapping from database (will be populated on init)
        self.token_info_cache: Dict[str, Dict] = {}  # token_mint -> {symbol, decimals, etc}
        
        # Connection management
        self.session: Optional[aiohttp.ClientSession] = None
        self.sse_response: Optional[aiohttp.ClientResponse] = None
        self.is_running = False
        self.reconnect_task: Optional[asyncio.Task] = None
        self.last_connect_time: Optional[datetime] = None
        
        # Performance tracking
        self.stats = {
            'messages_received': 0,
            'price_updates_processed': 0,
            'errors': 0,
            'reconnections': 0,
            'uptime_start': datetime.utcnow()
        }
        
        logger.info("📊 Pyth SSE Client initialized")
    
    async def initialize(self):
        """Initialize the SSE client and load token mappings"""
        try:
            # Load token info from database
            from ..database.production_db import get_db_manager
            db_manager = await get_db_manager()
            
            # Cache token info for symbol lookup
            for token_mint, feed_id in TOKEN_ORACLE_HEX_MAPPING.items():
                token_info = db_manager.get_token_by_address(token_mint)
                if token_info:
                    self.token_info_cache[token_mint] = {
                        'symbol': token_info.symbol,
                        'decimals': token_info.decimals,
                        'feed_id': feed_id
                    }
            
            logger.info(f"✅ Loaded {len(self.token_info_cache)} token mappings")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Pyth SSE client: {e}")
            raise
    
    async def subscribe_to_symbols(self, symbols: List[str]):
        """
        Subscribe to price updates for specific symbols
        
        Args:
            symbols: List of token symbols (e.g., ['RENDER', 'WIF'])
        """
        try:
            # Convert symbols to token mints and feed IDs
            for symbol in symbols:
                # Find token mint for symbol
                token_mint = None
                for mint, info in self.token_info_cache.items():
                    if info['symbol'] == symbol:
                        token_mint = mint
                        break
                
                if token_mint:
                    self.subscribed_tokens[symbol] = token_mint
                    logger.debug(f"📈 Subscribed to {symbol} (mint: {token_mint[:8]}...)")
                else:
                    logger.warning(f"⚠️ Token mint not found for symbol: {symbol}")
            
            logger.info(f"📊 Subscribed to {len(self.subscribed_tokens)} symbols")
            
            # Restart connection if already running to update subscriptions
            if self.is_running:
                await self._reconnect()
                
        except Exception as e:
            logger.error(f"❌ Failed to subscribe to symbols: {e}")
    
    async def start(self):
        """Start the SSE price streaming"""
        if self.is_running:
            logger.warning("⚠️ Pyth SSE client already running")
            return
        
        self.is_running = True
        logger.info("🚀 Starting Pyth SSE price streaming...")
        
        # Create session
        self.session = aiohttp.ClientSession()
        
        # Start streaming
        asyncio.create_task(self._streaming_loop())
        
        # Schedule periodic reconnection (before 24h limit)
        self.reconnect_task = asyncio.create_task(self._scheduled_reconnect_loop())
        
        logger.info("✅ Pyth SSE client started")
    
    async def stop(self):
        """Stop the SSE price streaming"""
        logger.info("🛑 Stopping Pyth SSE client...")
        self.is_running = False
        
        # Cancel reconnect task
        if self.reconnect_task:
            self.reconnect_task.cancel()
            try:
                await self.reconnect_task
            except asyncio.CancelledError:
                pass
        
        # Close SSE connection
        if self.sse_response:
            self.sse_response.close()
        
        # Close session
        if self.session:
            await self.session.close()
        
        self.connection_state = ConnectionState.DISCONNECTED
        logger.info("🏁 Pyth SSE client stopped")
    
    async def _streaming_loop(self):
        """Main streaming loop with error recovery"""
        while self.is_running:
            try:
                await self._connect_and_stream()
            except Exception as e:
                logger.error(f"❌ SSE streaming error: {e}")
                self.connection_state = ConnectionState.ERROR
                self._emit_error(e)
                
                # Wait before reconnecting
                await asyncio.sleep(5)
                
                if self.is_running:
                    logger.info("🔄 Attempting to reconnect...")
                    self.stats['reconnections'] += 1
    
    async def _connect_and_stream(self):
        """Connect to SSE endpoint and stream prices"""
        try:
            # Build query parameters for subscribed tokens
            if not self.subscribed_tokens:
                logger.warning("⚠️ No tokens subscribed, skipping connection")
                return
            
            # Get price feed IDs for subscribed tokens
            feed_ids = []
            for symbol, token_mint in self.subscribed_tokens.items():
                if token_mint in TOKEN_ORACLE_HEX_MAPPING:
                    feed_id = TOKEN_ORACLE_HEX_MAPPING[token_mint]
                    # Remove 0x prefix if present
                    if feed_id.startswith('0x'):
                        feed_id = feed_id[2:]
                    feed_ids.append(feed_id)
            
            if not feed_ids:
                logger.warning("⚠️ No valid price feed IDs found")
                return
            
            # Build URL with feed IDs
            params = [('ids[]', fid) for fid in feed_ids]
            
            self.connection_state = ConnectionState.CONNECTING
            logger.info(f"🔌 Connecting to Pyth SSE for {len(feed_ids)} feeds...")
            logger.debug(f"📋 Feed IDs: {feed_ids[:2]}..." if len(feed_ids) > 2 else f"📋 Feed IDs: {feed_ids}")
            
            # Connect with timeout
            timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
            
            async with self.session.get(
                self.HERMES_SSE_ENDPOINT,
                params=params,
                timeout=timeout,
                headers={
                    'Accept': 'text/event-stream',
                    'Cache-Control': 'no-cache'
                }
            ) as response:
                self.sse_response = response
                
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"SSE connection failed: {response.status} - {error_text}")
                
                self.connection_state = ConnectionState.CONNECTED
                self.last_connect_time = datetime.utcnow()
                logger.info("✅ Connected to Pyth SSE stream")
                logger.info(f"📡 Monitoring prices for symbols: {list(self.subscribed_tokens.keys())}")
                
                # Stream price updates
                async for line_bytes in response.content:
                    if not self.is_running:
                        break
                    
                    try:
                        line = line_bytes.decode('utf-8').strip()
                        
                        # SSE format: "data: {json}"
                        if line.startswith('data: '):
                            json_str = line[6:]  # Remove "data: " prefix
                            await self._process_price_update(json_str)
                            self.stats['messages_received'] += 1
                            
                    except Exception as e:
                        logger.error(f"❌ Error processing SSE message: {e}")
                        self.stats['errors'] += 1
                        continue
                
        except asyncio.CancelledError:
            logger.info("📡 SSE streaming cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ SSE connection error: {e}")
            self.connection_state = ConnectionState.ERROR
            raise
        finally:
            self.sse_response = None
            if self.connection_state == ConnectionState.CONNECTED:
                self.connection_state = ConnectionState.DISCONNECTED
    
    async def _process_price_update(self, json_str: str):
        """Process a price update from the SSE stream"""
        try:
            data = json.loads(json_str)
            
            # Parse binary data if present
            if 'binary' in data and 'data' in data['binary']:
                # Binary format (as shown in example)
                await self._process_binary_update(data)
            elif 'parsed' in data:
                # Parsed format
                await self._process_parsed_update(data['parsed'])
            else:
                logger.warning(f"⚠️ Unknown SSE data format: {list(data.keys())}")
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse SSE JSON: {e}")
        except Exception as e:
            logger.error(f"❌ Failed to process price update: {e}")
    
    async def _process_parsed_update(self, parsed_data: List[Dict]):
        """Process parsed price updates"""
        for price_data in parsed_data:
            try:
                feed_id = price_data.get('id', '')
                if feed_id.startswith('0x'):
                    feed_id = '0x' + feed_id
                else:
                    feed_id = '0x' + feed_id
                
                # Find token mint for this feed ID
                token_mint = None
                for mint, mapped_feed_id in TOKEN_ORACLE_HEX_MAPPING.items():
                    if mapped_feed_id == feed_id:
                        token_mint = mint
                        break
                
                if not token_mint or token_mint not in self.token_info_cache:
                    continue
                
                # Get token info
                token_info = self.token_info_cache[token_mint]
                symbol = token_info['symbol']
                
                # Skip if not subscribed
                if symbol not in self.subscribed_tokens:
                    continue
                
                # Extract price data
                price_info = price_data.get('price', {})
                price_raw = int(price_info.get('price', 0))
                confidence_raw = int(price_info.get('conf', 0))
                exponent = int(price_info.get('expo', 0))
                publish_time = int(price_info.get('publish_time', 0))
                
                # Convert to human-readable price
                price = price_raw * (10 ** exponent)
                confidence = confidence_raw * (10 ** exponent)
                
                # Get metadata
                metadata = price_data.get('metadata', {})
                slot = metadata.get('slot', 0)
                
                # Create price update
                update = PriceUpdate(
                    symbol=symbol,
                    token_mint=token_mint,
                    price=price,
                    confidence=confidence,
                    timestamp=datetime.utcnow(),
                    publish_time=publish_time,
                    slot=slot
                )
                
                # Emit to callbacks
                await self._emit_price_update(update)
                self.stats['price_updates_processed'] += 1
                
                # Log first few updates for verification
                if self.stats['price_updates_processed'] <= 5 or self.stats['price_updates_processed'] % 100 == 0:
                    logger.info(f"✅ Pyth price update #{self.stats['price_updates_processed']}: {symbol} = ${price:.6f} (±${confidence:.6f})")
                
                logger.debug(f"💰 {symbol}: ${price:.6f} (±${confidence:.6f})")
                
            except Exception as e:
                logger.error(f"❌ Error processing parsed price data: {e}")
    
    async def _process_binary_update(self, data: Dict):
        """Process binary format updates (VAA)"""
        # For now, just log that we received binary data
        # Full VAA parsing would require additional implementation
        logger.debug("📦 Received binary price update (VAA format)")
        
        # If we have parsed data alongside binary, use that
        if 'parsed' in data:
            await self._process_parsed_update(data['parsed'])
    
    async def _scheduled_reconnect_loop(self):
        """Reconnect before the 24-hour SSE limit"""
        while self.is_running:
            try:
                # Wait until next reconnect time
                await asyncio.sleep(self.RECONNECT_INTERVAL.total_seconds())
                
                if self.is_running and self.connection_state == ConnectionState.CONNECTED:
                    logger.info("⏰ Scheduled reconnection (24h limit prevention)")
                    await self._reconnect()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Scheduled reconnect error: {e}")
    
    async def _reconnect(self):
        """Reconnect to SSE stream"""
        logger.info("🔄 Reconnecting to Pyth SSE...")
        
        # Close current connection
        if self.sse_response:
            self.sse_response.close()
        
        self.connection_state = ConnectionState.RECONNECTING
        
        # Small delay before reconnecting
        await asyncio.sleep(1)
        
        # Connection will be re-established by the streaming loop
    
    async def _emit_price_update(self, update: PriceUpdate):
        """Emit price update to all callbacks"""
        for callback in self.price_callbacks:
            try:
                await callback(update)
            except Exception as e:
                logger.error(f"❌ Price callback error: {e}")
    
    def _emit_error(self, error: Exception):
        """Emit error to all callbacks"""
        for callback in self.error_callbacks:
            try:
                callback(error)
            except Exception as e:
                logger.error(f"❌ Error callback error: {e}")
    
    def add_price_callback(self, callback: Callable[[PriceUpdate], Awaitable[None]]):
        """Add price update callback"""
        self.price_callbacks.append(callback)
    
    def add_error_callback(self, callback: Callable[[Exception], None]):
        """Add error callback"""
        self.error_callbacks.append(callback)
    
    def get_stats(self) -> Dict:
        """Get client statistics"""
        uptime = datetime.utcnow() - self.stats['uptime_start']
        
        return {
            **self.stats,
            'connection_state': self.connection_state.value,
            'subscribed_symbols': len(self.subscribed_tokens),
            'uptime_seconds': uptime.total_seconds(),
            'last_connect_time': self.last_connect_time.isoformat() if self.last_connect_time else None
        } 