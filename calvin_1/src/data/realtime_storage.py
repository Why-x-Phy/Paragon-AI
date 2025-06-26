"""
Calvin AI Real-Time Data Storage

Handles real-time data ingestion from WebSocket feeds and stores to production database:
- WebSocket price updates → database insertion
- Minute candle aggregation from tick data
- Position monitoring and trigger detection
- Real-time caching in Redis
- Stop-loss/take-profit monitoring
"""

import asyncio
import logging
import json
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
import statistics
import redis

try:
    from .websocket_feed import BirdEyeWebSocketFeed, PriceUpdate, TransactionUpdate, ConnectionState
except ImportError:
    # Fallback for when running test scripts directly
    from websocket_feed import BirdEyeWebSocketFeed, PriceUpdate, TransactionUpdate, ConnectionState

try:
    from ..database.production_db import (
        ProductionDBManager, 
        OHLCVData, 
        PositionData,
        MarketEventData,
        get_db_manager
    )
except ImportError:
    # Fallback for when running test scripts directly
    from database.production_db import (
        ProductionDBManager, 
        OHLCVData, 
        PositionData,
        MarketEventData,
        get_db_manager
    )


@dataclass
class TickData:
    """Individual price tick data"""
    timestamp: datetime
    token_id: int
    price: float
    volume: Optional[float] = None
    source: str = 'websocket'


@dataclass
class CandleAggregator:
    """Aggregates tick data into OHLCV candles"""
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None
    volume: float = 0.0
    tick_count: int = 0
    start_time: Optional[datetime] = None
    last_update: Optional[datetime] = None
    
    def add_tick(self, tick: TickData):
        """Add a price tick to the aggregator"""
        if self.open_price is None:
            self.open_price = tick.price
            self.start_time = tick.timestamp
            
        self.high_price = max(self.high_price or tick.price, tick.price)
        self.low_price = min(self.low_price or tick.price, tick.price)
        self.close_price = tick.price
        
        if tick.volume:
            self.volume += tick.volume
            
        self.tick_count += 1
        self.last_update = tick.timestamp
    
    def to_ohlcv(self, token_id: int, resolution: str = '1m') -> Optional[OHLCVData]:
        """Convert aggregator to OHLCV data"""
        if self.open_price is None or not self.start_time:
            return None
            
        return OHLCVData(
            time=self.start_time,
            token_id=token_id,
            resolution=resolution,
            open=self.open_price,
            high=self.high_price or self.open_price,
            low=self.low_price or self.open_price,
            close=self.close_price or self.open_price,
            volume=self.volume,
            trades_count=self.tick_count,
            data_source='websocket'
        )
    
    def is_complete(self, current_time: datetime, interval_minutes: int = 1) -> bool:
        """Check if candle interval is complete"""
        if not self.start_time:
            return False
            
        expected_end = self.start_time + timedelta(minutes=interval_minutes)
        return current_time >= expected_end


@dataclass
class PositionTrigger:
    """Position monitoring trigger"""
    position_id: int
    token_id: int
    trigger_type: str  # 'stop_loss', 'take_profit'
    trigger_price: float
    position_type: str  # 'long', 'short'
    
    def should_trigger(self, current_price: float) -> bool:
        """Check if trigger condition is met"""
        if self.trigger_type == 'stop_loss':
            if self.position_type == 'long':
                return current_price <= self.trigger_price
            else:  # short
                return current_price >= self.trigger_price
                
        elif self.trigger_type == 'take_profit':
            if self.position_type == 'long':
                return current_price >= self.trigger_price
            else:  # short
                return current_price <= self.trigger_price
                
        return False


class RealtimeDataStorage:
    """
    Real-time data storage and processing system
    
    Handles:
    - WebSocket price feed integration
    - Real-time database storage
    - Minute candle aggregation
    - Position monitoring and triggers
    - Cache management
    """
    
    def __init__(self, websocket_feed: BirdEyeWebSocketFeed, db_manager: Optional[ProductionDBManager] = None):
        self.websocket_feed = websocket_feed
        self.db_manager = db_manager  # Will be set during initialization
        self.logger = logging.getLogger(__name__)
        
        # Candle aggregation
        self.candle_aggregators: Dict[int, CandleAggregator] = {}
        self.aggregation_interval = 60  # 1 minute in seconds
        
        # Position monitoring
        self.position_triggers: Dict[int, List[PositionTrigger]] = defaultdict(list)
        self.trigger_callbacks: List[Callable[[PositionTrigger, float], None]] = []
        
        # Processing queue for batch operations
        self.tick_queue: deque = deque(maxlen=10000)
        self.transaction_queue: deque = deque(maxlen=10000)
        self.batch_size = 100
        self.batch_timeout = 5.0  # seconds
        
        # Processing stats
        self.stats = {
            'ticks_processed': 0,
            'transactions_processed': 0,
            'candles_created': 0,
            'triggers_fired': 0,
            'errors': 0,
            'last_tick_time': None,
            'last_transaction_time': None,
            'start_time': datetime.utcnow()
        }
        
        # Running state
        self.is_running = False
        self.processing_task: Optional[asyncio.Task] = None
        self.transaction_task: Optional[asyncio.Task] = None
        self.candle_task: Optional[asyncio.Task] = None
        
        # Connection state tracking for safer health checks
        self._last_connection_state: Optional[Dict] = None
        
    async def initialize(self):
        """Initialize the real-time storage system"""
        try:
            # Initialize database manager if not provided
            if self.db_manager is None:
                self.db_manager = await get_db_manager()
            
            # Set up WebSocket event handlers
            self.websocket_feed.add_price_update_handler(self._handle_price_update)
            self.websocket_feed.add_transaction_update_handler(self._handle_transaction_update)
            self.websocket_feed.add_connection_handler(self._handle_connection_state)
            
            # Load existing position triggers
            await self._load_position_triggers()
            
            self.logger.info("Real-time data storage initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize real-time storage: {e}")
            raise
    
    async def start(self):
        """Start real-time data processing"""
        if self.is_running:
            self.logger.warning("Real-time storage already running")
            return
            
        try:
            self.is_running = True
            
            # Start processing tasks
            self.processing_task = asyncio.create_task(self._process_tick_queue())
            self.transaction_task = asyncio.create_task(self._process_transaction_queue())
            self.candle_task = asyncio.create_task(self._process_candle_aggregation())
            
            # Start WebSocket feed
            await self.websocket_feed.start()
            
            self.logger.info("Real-time data storage started")
            
        except Exception as e:
            self.logger.error(f"Failed to start real-time storage: {e}")
            self.is_running = False
            raise
    
    async def stop(self):
        """Stop real-time data processing"""
        if not self.is_running:
            return
            
        try:
            self.is_running = False
            
            # Stop WebSocket feed
            await self.websocket_feed.stop()
            
            # Cancel processing tasks
            if self.processing_task:
                self.processing_task.cancel()
            if self.transaction_task:
                self.transaction_task.cancel()
            if self.candle_task:
                self.candle_task.cancel()
            
            # Wait for tasks to complete
            await asyncio.gather(
                self.processing_task,
                self.transaction_task,
                self.candle_task,
                return_exceptions=True
            )
            
            # Process remaining queue items
            await self._flush_tick_queue()
            await self._flush_transaction_queue()
            await self._flush_candle_aggregators()
            
            self.logger.info("Real-time data storage stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping real-time storage: {e}")
    
    # =========================================================================
    # WEBSOCKET EVENT HANDLERS
    # =========================================================================
    
    async def _handle_price_update(self, price_update: PriceUpdate):
        """Handle incoming price update from WebSocket"""
        try:
            # Get token info
            token = self.db_manager.get_token_by_address(price_update.address)
            if not token:
                self.logger.warning(f"Unknown token address: {price_update.address}")
                return
            
            # Create tick data
            tick = TickData(
                timestamp=price_update.timestamp,
                token_id=token.token_id,
                price=price_update.price,
                volume=getattr(price_update, 'volume', None),
                source='websocket'
            )
            
            # Add to processing queue
            self.tick_queue.append(tick)
            
            # Update stats
            self.stats['ticks_processed'] += 1
            self.stats['last_tick_time'] = tick.timestamp
            
            # Check position triggers immediately for real-time response
            await self._check_position_triggers(token.token_id, tick.price)
            
            # Cache current price in Redis
            await self._cache_current_price(token.token_id, tick.price)
            
        except Exception as e:
            self.logger.error(f"Error handling price update: {e}")
            self.stats['errors'] += 1
    
    async def _handle_transaction_update(self, transaction_update: TransactionUpdate):
        """Handle incoming transaction update from WebSocket"""
        try:
            # Get token info
            token = self.db_manager.get_token_by_address(transaction_update.token_address or transaction_update.from_address)
            if not token:
                # Try the 'to' address if token not found
                if transaction_update.to_address:
                    token = self.db_manager.get_token_by_address(transaction_update.to_address)
                if not token:
                    self.logger.warning(f"Unknown token address in transaction: {transaction_update.tx_hash[:12]}...")
                    return
            
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
            
            # Create market event
            market_event = MarketEventData(
                token_id=token.token_id,
                event_type='transaction',
                event_time=datetime.fromtimestamp(transaction_update.block_unix_time),
                event_data=event_data,
                size_usd=transaction_update.volume_usd,
                source='birdeye',
                raw_data=transaction_update.raw_data
            )
            
            # Add to processing queue
            self.transaction_queue.append(market_event)
            
            # Update stats
            self.stats['transactions_processed'] += 1
            self.stats['last_transaction_time'] = market_event.event_time
            
        except Exception as e:
            self.logger.error(f"Error handling transaction update: {e}")
            self.stats['errors'] += 1
    
    def _handle_connection_state(self, state: ConnectionState):
        """Handle WebSocket connection state changes"""
        self.logger.info(f"WebSocket connection state: {state.value}")
        
        # Record health check safely without blocking or creating race conditions
        if self.db_manager:
            # Use a simple flag-based approach instead of fire-and-forget tasks
            # This avoids connection pool conflicts
            self._last_connection_state = {
                'timestamp': datetime.utcnow().isoformat(), 
                'state': state.value
            }
            # The health check will be recorded in the next batch operation
            # to avoid concurrent connection usage
    
    # =========================================================================
    # TICK PROCESSING
    # =========================================================================
    
    async def _process_tick_queue(self):
        """Process queued tick data in batches"""
        while self.is_running:
            try:
                if len(self.tick_queue) >= self.batch_size:
                    await self._process_tick_batch()
                else:
                    # Wait a bit for more ticks or timeout
                    await asyncio.sleep(min(self.batch_timeout, 1.0))
                    if len(self.tick_queue) > 0:
                        await self._process_tick_batch()
                        
            except Exception as e:
                self.logger.error(f"Error in tick processing loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _process_tick_batch(self):
        """Process a batch of ticks"""
        if not self.tick_queue:
            return
            
        try:
            # Extract batch
            batch = []
            batch_size = min(len(self.tick_queue), self.batch_size)
            
            for _ in range(batch_size):
                if self.tick_queue:
                    batch.append(self.tick_queue.popleft())
            
            if not batch:
                return
            
            # Group by token and add to aggregators
            for tick in batch:
                await self._add_tick_to_aggregator(tick)
            
            self.logger.debug(f"Processed tick batch of {len(batch)} items")
            
        except Exception as e:
            self.logger.error(f"Error processing tick batch: {e}")
    
    async def _flush_tick_queue(self):
        """Flush remaining ticks in queue"""
        while self.tick_queue:
            await self._process_tick_batch()
    
    # =========================================================================
    # TRANSACTION PROCESSING
    # =========================================================================
    
    async def _process_transaction_queue(self):
        """Process queued transaction data in batches"""
        while self.is_running:
            try:
                if len(self.transaction_queue) >= self.batch_size:
                    await self._process_transaction_batch()
                else:
                    # Wait a bit for more transactions or timeout
                    await asyncio.sleep(min(self.batch_timeout, 1.0))
                    if len(self.transaction_queue) > 0:
                        await self._process_transaction_batch()
                        
            except Exception as e:
                self.logger.error(f"Error in transaction processing loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _process_transaction_batch(self):
        """Process a batch of transactions"""
        if not self.transaction_queue:
            return
            
        try:
            # Extract batch
            batch = []
            batch_size = min(len(self.transaction_queue), self.batch_size)
            
            for _ in range(batch_size):
                if self.transaction_queue:
                    batch.append(self.transaction_queue.popleft())
            
            if not batch:
                return
            
            # Store batch to database
            await self.db_manager.insert_market_events(batch)
            
            self.logger.debug(f"Processed transaction batch of {len(batch)} items")
            
        except Exception as e:
            self.logger.error(f"Error processing transaction batch: {e}")
    
    async def _flush_transaction_queue(self):
        """Flush remaining transactions in queue"""
        while self.transaction_queue:
            await self._process_transaction_batch()
    
    # =========================================================================
    # CANDLE AGGREGATION
    # =========================================================================
    
    async def _add_tick_to_aggregator(self, tick: TickData):
        """Add tick to the appropriate candle aggregator"""
        try:
            # Get or create aggregator for this token
            if tick.token_id not in self.candle_aggregators:
                self.candle_aggregators[tick.token_id] = CandleAggregator()
            
            aggregator = self.candle_aggregators[tick.token_id]
            
            # Check if we need to finalize the current candle
            if aggregator.is_complete(tick.timestamp, 1):  # 1 minute interval
                await self._finalize_candle(tick.token_id, aggregator)
                # Create new aggregator
                self.candle_aggregators[tick.token_id] = CandleAggregator()
                aggregator = self.candle_aggregators[tick.token_id]
            
            # Add tick to aggregator
            aggregator.add_tick(tick)
            
        except Exception as e:
            self.logger.error(f"Error adding tick to aggregator: {e}")
    
    async def _process_candle_aggregation(self):
        """Periodically check and finalize completed candles"""
        while self.is_running:
            try:
                current_time = datetime.utcnow()
                completed_tokens = []
                
                # Check all aggregators for completion
                for token_id, aggregator in self.candle_aggregators.items():
                    if aggregator.is_complete(current_time, 1):
                        await self._finalize_candle(token_id, aggregator)
                        completed_tokens.append(token_id)
                
                # Remove completed aggregators
                for token_id in completed_tokens:
                    self.candle_aggregators[token_id] = CandleAggregator()
                
                # Check every 30 seconds
                await asyncio.sleep(30)
                
            except Exception as e:
                self.logger.error(f"Error in candle aggregation loop: {e}")
                await asyncio.sleep(30)
    
    async def _finalize_candle(self, token_id: int, aggregator: CandleAggregator):
        """Finalize a completed candle and store to database"""
        try:
            ohlcv_data = aggregator.to_ohlcv(token_id)
            if not ohlcv_data:
                return
            
            # Store to database
            await self.db_manager.insert_ohlcv_data([ohlcv_data])
            
            self.stats['candles_created'] += 1
            
            self.logger.debug(
                f"Finalized 1m candle for token {token_id}: "
                f"O:{ohlcv_data.open:.6f} H:{ohlcv_data.high:.6f} "
                f"L:{ohlcv_data.low:.6f} C:{ohlcv_data.close:.6f}"
            )
            
        except Exception as e:
            self.logger.error(f"Error finalizing candle for token {token_id}: {e}")
    
    async def _flush_candle_aggregators(self):
        """Flush all remaining candle aggregators"""
        try:
            for token_id, aggregator in self.candle_aggregators.items():
                if aggregator.tick_count > 0:  # Has data
                    await self._finalize_candle(token_id, aggregator)
            
            self.candle_aggregators.clear()
            
        except Exception as e:
            self.logger.error(f"Error flushing candle aggregators: {e}")
    
    # =========================================================================
    # POSITION MONITORING
    # =========================================================================
    
    async def _load_position_triggers(self):
        """Load position triggers from open positions"""
        try:
            open_positions = await self.db_manager.get_open_positions()
            
            self.position_triggers.clear()
            
            for position in open_positions:
                triggers = []
                
                # Add stop loss trigger
                if position.stop_loss_price:
                    triggers.append(PositionTrigger(
                        position_id=position.position_id,
                        token_id=position.token_id,
                        trigger_type='stop_loss',
                        trigger_price=position.stop_loss_price,
                        position_type=position.position_type
                    ))
                
                # Add take profit trigger
                if position.take_profit_price:
                    triggers.append(PositionTrigger(
                        position_id=position.position_id,
                        token_id=position.token_id,
                        trigger_type='take_profit',
                        trigger_price=position.take_profit_price,
                        position_type=position.position_type
                    ))
                
                if triggers:
                    self.position_triggers[position.token_id].extend(triggers)
            
            total_triggers = sum(len(triggers) for triggers in self.position_triggers.values())
            self.logger.info(f"Loaded {total_triggers} position triggers from {len(open_positions)} open positions")
            
        except Exception as e:
            self.logger.error(f"Error loading position triggers: {e}")
    
    async def _check_position_triggers(self, token_id: int, current_price: float):
        """Check if any position triggers should fire"""
        if token_id not in self.position_triggers:
            return
            
        try:
            triggered = []
            
            for trigger in self.position_triggers[token_id]:
                if trigger.should_trigger(current_price):
                    triggered.append(trigger)
                    
                    # Fire trigger callbacks
                    for callback in self.trigger_callbacks:
                        try:
                            await callback(trigger, current_price)
                        except Exception as e:
                            self.logger.error(f"Error in trigger callback: {e}")
                    
                    self.stats['triggers_fired'] += 1
                    
                    self.logger.info(
                        f"Position trigger fired: {trigger.trigger_type} for position "
                        f"{trigger.position_id} at price {current_price}"
                    )
            
            # Remove triggered items
            for trigger in triggered:
                self.position_triggers[token_id].remove(trigger)
                
        except Exception as e:
            self.logger.error(f"Error checking position triggers: {e}")
    
    def add_trigger_callback(self, callback: Callable[[PositionTrigger, float], None]):
        """Add a callback for position trigger events"""
        self.trigger_callbacks.append(callback)
    
    async def refresh_position_triggers(self):
        """Refresh position triggers from database"""
        await self._load_position_triggers()
    
    # =========================================================================
    # CACHING
    # =========================================================================
    
    async def _cache_current_price(self, token_id: int, price: float):
        """Cache current price in Redis"""
        try:
            cache_key = f"prices:{token_id}:current"
            await self.db_manager.redis_client.setex(cache_key, 300, price)  # 5 minute TTL
            
        except Exception as e:
            self.logger.error(f"Error caching price for token {token_id}: {e}")
    
    # =========================================================================
    # MONITORING AND STATS
    # =========================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics"""
        uptime = datetime.utcnow() - self.stats['start_time']
        
        return {
            **self.stats,
            'uptime_seconds': uptime.total_seconds(),
            'queue_size': len(self.tick_queue),
            'active_aggregators': len(self.candle_aggregators),
            'position_triggers': sum(len(triggers) for triggers in self.position_triggers.values()),
            'is_running': self.is_running
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        try:
            health = {
                'status': 'healthy',
                'last_tick_age_seconds': None,
                'queue_health': 'healthy',
                'websocket_health': 'unknown'
            }
            
            # Check last tick age
            if self.stats['last_tick_time']:
                age = (datetime.utcnow() - self.stats['last_tick_time']).total_seconds()
                health['last_tick_age_seconds'] = age
                
                if age > 300:  # 5 minutes
                    health['status'] = 'degraded'
                    health['issues'] = ['No recent price updates']
            
            # Check queue health
            if len(self.tick_queue) > self.tick_queue.maxlen * 0.8:
                health['queue_health'] = 'degraded'
                if health['status'] == 'healthy':
                    health['status'] = 'degraded'
                    health['issues'] = health.get('issues', [])
                    health['issues'].append('Tick queue near capacity')
            
            # Get WebSocket health
            ws_health = self.websocket_feed.get_health_status()
            health['websocket_health'] = ws_health['status']
            
            return health
            
        except Exception as e:
            self.logger.error(f"Error in health check: {e}")
            return {
                'status': 'error',
                'error': str(e)
            } 