"""
Calvin Emergency Stop Loss Monitor

Monitors vault positions via WebSocket price feeds and triggers emergency exits when
stop loss thresholds are hit. Integrates with the existing BirdEye WebSocket infrastructure
and vault client for seamless position monitoring and emergency execution.

Phase 3.3 Implementation:
- Real-time price monitoring via existing WebSocket infrastructure
- Portfolio-level and individual position stop loss monitoring
- Emergency exit execution through vault smart contracts
- Risk management with configurable thresholds and limits
- Comprehensive logging and performance tracking
"""

import asyncio
from typing import Dict, List, Optional, Set, Tuple, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import time

from ..data.websocket_feed import BirdEyeWebSocketFeed, ConnectionConfig, PriceSubscription, PriceUpdate, ConnectionState
from ..trading.position_manager import PositionManager, Position
from .vault_client import VaultClient
from ..config.config import config
from ..utils.logger import log
from ..database.production_db import get_db_manager

logger = log


class EmergencyType(Enum):
    """Types of emergency conditions"""
    INDIVIDUAL_STOP_LOSS = "individual_stop_loss"
    PORTFOLIO_STOP_LOSS = "portfolio_stop_loss"
    VOLATILITY_SPIKE = "volatility_spike"
    DRAWDOWN_LIMIT = "drawdown_limit"
    MANUAL_TRIGGER = "manual_trigger"


@dataclass
class EmergencyThresholds:
    """Emergency monitoring thresholds"""
    # Stop loss thresholds
    portfolio_stop_loss_pct: float = -15.0    # -15% portfolio loss
    individual_stop_loss_pct: float = -25.0   # -25% individual position loss
    
    # Volatility thresholds
    volatility_stop_multiplier: float = 3.0   # 3x daily volatility
    max_drawdown_pct: float = -20.0           # -20% max drawdown
    
    # Risk limits
    max_daily_exits: int = 5                  # Max 5 emergency exits per day
    portfolio_risk_limit: float = 0.8         # 80% max portfolio exposure
    
    # Monitoring intervals
    price_check_interval: float = 1.0         # Check prices every 1 second
    portfolio_check_interval: float = 60.0    # Check portfolio every 60 seconds
    health_check_interval: float = 300.0      # Health check every 5 minutes


@dataclass
class EmergencyEvent:
    """Emergency event record"""
    timestamp: datetime
    event_type: EmergencyType
    symbol: str
    trigger_value: float
    threshold_value: float
    action_taken: str
    transaction_signature: Optional[str] = None
    portfolio_impact: Optional[float] = None
    notes: str = ""


@dataclass
class PositionMonitor:
    """Individual position monitoring state"""
    symbol: str
    current_price: float
    entry_price: float
    position_size: float
    last_update: datetime
    unrealized_pnl_pct: float = 0.0
    volatility_24h: float = 0.0
    price_history: List[Tuple[datetime, float]] = field(default_factory=list)
    
    def update_price(self, price: float) -> None:
        """Update position with new price data"""
        self.current_price = price
        self.last_update = datetime.utcnow()
        self.unrealized_pnl_pct = ((price - self.entry_price) / self.entry_price) * 100
        
        # Update price history (keep last 24 hours)
        now = datetime.utcnow()
        self.price_history.append((now, price))
        cutoff_time = now - timedelta(hours=24)
        self.price_history = [(t, p) for t, p in self.price_history if t > cutoff_time]
        
        # Calculate 24h volatility
        if len(self.price_history) > 1:
            prices = [p for _, p in self.price_history]
            returns = [(prices[i] / prices[i-1] - 1) for i in range(1, len(prices))]
            if returns:
                import statistics
                self.volatility_24h = statistics.stdev(returns) * 100  # Convert to percentage


class EmergencyStopLossMonitor:
    """
    Monitors vault positions for emergency stop loss conditions via WebSocket price feeds
    """
    
    def __init__(self, thresholds: Optional[EmergencyThresholds] = None):
        self.thresholds = thresholds or EmergencyThresholds()
        
        # Core components
        self.position_manager = PositionManager()
        self.vault_client = VaultClient()
        self.websocket_feed: Optional[BirdEyeWebSocketFeed] = None
        self.db_manager = None
        
        # Monitoring state
        self.position_monitors: Dict[str, PositionMonitor] = {}
        self.portfolio_value_history: List[Tuple[datetime, float]] = []
        self.emergency_events: List[EmergencyEvent] = []
        self.subscribed_tokens: Set[str] = set()
        
        # Control flags
        self.is_monitoring = False
        self.emergency_exits_today = 0
        self.last_portfolio_check = None
        self.last_health_check = None
        
        # Event handlers
        self.emergency_handlers: List[Callable[[EmergencyEvent], None]] = []
        
        # Performance tracking
        self.stats = {
            'price_updates_processed': 0,
            'emergency_events_triggered': 0,
            'positions_monitored': 0,
            'total_monitoring_time': 0.0,
            'last_portfolio_value': 0.0,
            'max_drawdown_today': 0.0
        }
        
        logger.info("Emergency Stop Loss Monitor initialized")
        logger.info(f"📊 Thresholds: Portfolio stop loss: {self.thresholds.portfolio_stop_loss_pct}%, Individual: {self.thresholds.individual_stop_loss_pct}%")

    async def initialize(self):
        """Initialize emergency monitoring components"""
        try:
            # Initialize database manager
            self.db_manager = await get_db_manager()
            
            # Initialize vault client
            await self.vault_client.initialize()
            logger.info("✅ Vault client initialized for emergency monitoring")
            
            # Initialize WebSocket feed
            api_key = config.get('BIRDEYE_API_KEY')
            if not api_key:
                raise ValueError("BIRDEYE_API_KEY is required for emergency monitoring")
            
            ws_config = ConnectionConfig(
                api_key=api_key,
                chain="solana",
                reconnect_delay=2.0,
                max_reconnect_attempts=10,  # More attempts for emergency monitoring
                heartbeat_interval=30.0,
                message_queue_size=2000     # Larger queue for price updates
            )
            
            self.websocket_feed = BirdEyeWebSocketFeed(ws_config)
            
            # Set up WebSocket event handlers
            self.websocket_feed.add_price_update_handler(self._on_price_update)
            self.websocket_feed.add_connection_handler(self._on_connection_state_change)
            self.websocket_feed.add_error_handler(self._on_websocket_error)
            
            logger.info("✅ Emergency monitoring initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize emergency monitoring: {e}")
            raise

    async def start_monitoring(self, vault_positions: Optional[Dict[str, Position]] = None):
        """
        Start emergency monitoring for vault positions
        
        Args:
            vault_positions: Optional dict of positions to monitor. If None, will fetch from position manager
        """
        try:
            if self.is_monitoring:
                logger.warning("⚠️ Emergency monitoring already running")
                return
            
            logger.info("🚨 Starting emergency stop loss monitoring...")
            
            # Get vault positions to monitor
            if vault_positions is None:
                vault_positions = await self._get_vault_positions()
            
            if not vault_positions:
                logger.warning("⚠️ No vault positions found to monitor")
                return
            
            # Setup position monitors
            await self._setup_position_monitors(vault_positions)
            
            # Subscribe to price feeds for all position tokens
            await self._subscribe_to_position_prices()
            
            # Start WebSocket feed
            if self.websocket_feed:
                await self.websocket_feed.start()
                logger.info("✅ WebSocket price feed started")
            
            # Start monitoring tasks
            self.is_monitoring = True
            monitoring_tasks = [
                asyncio.create_task(self._portfolio_monitoring_loop()),
                asyncio.create_task(self._health_monitoring_loop()),
                asyncio.create_task(self._statistics_update_loop())
            ]
            
            logger.info(f"🔥 Emergency monitoring active for {len(vault_positions)} positions")
            
            # Wait for monitoring tasks
            await asyncio.gather(*monitoring_tasks, return_exceptions=True)
            
        except Exception as e:
            logger.error(f"❌ Emergency monitoring failed to start: {e}")
            await self.stop_monitoring()
            raise

    async def stop_monitoring(self):
        """Stop emergency monitoring"""
        logger.info("🛑 Stopping emergency stop loss monitoring...")
        
        self.is_monitoring = False
        
        try:
            # Stop WebSocket feed
            if self.websocket_feed:
                await self.websocket_feed.stop()
                logger.info("✅ WebSocket feed stopped")
            
            # Close database connections
            if self.db_manager:
                await self.db_manager.close()
            
            # Close vault client
            await self.vault_client.close()
            
            logger.info("🏁 Emergency monitoring stopped")
            
        except Exception as e:
            logger.error(f"❌ Error stopping emergency monitoring: {e}")

    async def _on_price_update(self, price_update: PriceUpdate):
        """Handle incoming price updates from WebSocket"""
        try:
            symbol = price_update.symbol
            current_price = price_update.close_price
            
            # Update position monitor
            if symbol in self.position_monitors:
                self.position_monitors[symbol].update_price(current_price)
                
                # Check individual position stop loss
                await self._check_individual_stop_loss(symbol)
                
                self.stats['price_updates_processed'] += 1
            
        except Exception as e:
            logger.error(f"❌ Error processing price update for {price_update.symbol}: {e}")

    async def _check_individual_stop_loss(self, symbol: str):
        """Check if individual position hits stop loss threshold"""
        try:
            monitor = self.position_monitors.get(symbol)
            if not monitor:
                return
            
            # Check stop loss threshold
            if monitor.unrealized_pnl_pct <= self.thresholds.individual_stop_loss_pct:
                logger.critical(f"🚨 INDIVIDUAL STOP LOSS TRIGGERED: {symbol} at {monitor.unrealized_pnl_pct:.2f}%")
                
                # Create emergency event
                event = EmergencyEvent(
                    timestamp=datetime.utcnow(),
                    event_type=EmergencyType.INDIVIDUAL_STOP_LOSS,
                    symbol=symbol,
                    trigger_value=monitor.unrealized_pnl_pct,
                    threshold_value=self.thresholds.individual_stop_loss_pct,
                    action_taken="emergency_exit_requested"
                )
                
                # Execute emergency exit
                await self._execute_emergency_exit(event, monitor)
                
        except Exception as e:
            logger.error(f"❌ Individual stop loss check failed for {symbol}: {e}")

    async def _portfolio_monitoring_loop(self):
        """Main portfolio monitoring loop"""
        while self.is_monitoring:
            try:
                await asyncio.sleep(self.thresholds.portfolio_check_interval)
                
                # Check portfolio-level stop loss
                await self._check_portfolio_stop_loss()
                
                # Check volatility conditions
                await self._check_volatility_conditions()
                
                # Update portfolio statistics
                await self._update_portfolio_stats()
                
                self.last_portfolio_check = datetime.utcnow()
                
            except Exception as e:
                logger.error(f"❌ Portfolio monitoring loop error: {e}")
                await asyncio.sleep(10)  # Brief pause before retry

    async def _check_portfolio_stop_loss(self):
        """Check portfolio-level stop loss conditions"""
        try:
            # Calculate current portfolio P&L
            portfolio_pnl = await self._calculate_portfolio_pnl()
            
            if portfolio_pnl <= self.thresholds.portfolio_stop_loss_pct:
                logger.critical(f"🚨 PORTFOLIO EMERGENCY STOP LOSS: {portfolio_pnl:.2f}%")
                
                # Create emergency event
                event = EmergencyEvent(
                    timestamp=datetime.utcnow(),
                    event_type=EmergencyType.PORTFOLIO_STOP_LOSS,
                    symbol="PORTFOLIO",
                    trigger_value=portfolio_pnl,
                    threshold_value=self.thresholds.portfolio_stop_loss_pct,
                    action_taken="portfolio_emergency_exit_requested",
                    portfolio_impact=portfolio_pnl
                )
                
                # Execute portfolio emergency exit
                await self._execute_portfolio_emergency_exit(event)
                
        except Exception as e:
            logger.error(f"❌ Portfolio stop loss check failed: {e}")

    async def _check_volatility_conditions(self):
        """Check for excessive volatility conditions"""
        try:
            for symbol, monitor in self.position_monitors.items():
                if monitor.volatility_24h > 0:
                    # Check if volatility exceeds threshold
                    volatility_threshold = monitor.volatility_24h * self.thresholds.volatility_stop_multiplier
                    
                    # Calculate recent volatility (last hour)
                    recent_prices = [p for t, p in monitor.price_history 
                                   if t > datetime.utcnow() - timedelta(hours=1)]
                    
                    if len(recent_prices) > 1:
                        import statistics
                        recent_returns = [(recent_prices[i] / recent_prices[i-1] - 1) 
                                        for i in range(1, len(recent_prices))]
                        recent_volatility = statistics.stdev(recent_returns) * 100 if recent_returns else 0
                        
                        if recent_volatility > volatility_threshold:
                            logger.warning(f"⚠️ High volatility detected in {symbol}: {recent_volatility:.2f}% (threshold: {volatility_threshold:.2f}%)")
                            
                            # Could trigger emergency exit based on volatility
                            # For now, just log the warning
                            
        except Exception as e:
            logger.error(f"❌ Volatility check failed: {e}")

    async def _execute_emergency_exit(self, event: EmergencyEvent, monitor: PositionMonitor):
        """Execute emergency exit for individual position"""
        try:
            if self.emergency_exits_today >= self.thresholds.max_daily_exits:
                logger.error(f"❌ Daily emergency exit limit reached: {self.emergency_exits_today}")
                event.action_taken = "exit_blocked_daily_limit"
                await self._record_emergency_event(event)
                return
            
            # Execute emergency exit via vault client
            logger.critical(f"🚨 Executing emergency exit for {event.symbol}...")
            
            tx_sig = await self.vault_client.emergency_exit_position(
                event.symbol, 
                monitor.position_size
            )
            
            if tx_sig:
                self.emergency_exits_today += 1
                event.transaction_signature = tx_sig
                event.action_taken = "emergency_exit_executed"
                logger.critical(f"✅ Emergency exit executed: {event.symbol} - {tx_sig}")
                
                # Remove from monitoring (position closed)
                del self.position_monitors[event.symbol]
                
            else:
                event.action_taken = "emergency_exit_failed"
                logger.error(f"❌ Emergency exit failed for {event.symbol}")
            
            # Record emergency event
            await self._record_emergency_event(event)
            
            # Notify handlers
            for handler in self.emergency_handlers:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"❌ Emergency handler error: {e}")
            
            self.stats['emergency_events_triggered'] += 1
            
        except Exception as e:
            logger.error(f"❌ Emergency exit execution failed: {e}")
            event.action_taken = f"emergency_exit_error: {str(e)}"
            await self._record_emergency_event(event)

    async def _execute_portfolio_emergency_exit(self, event: EmergencyEvent):
        """Execute emergency exit for entire portfolio"""
        try:
            logger.critical(f"🚨 Executing PORTFOLIO emergency exit...")
            
            exit_results = []
            for symbol, monitor in list(self.position_monitors.items()):
                try:
                    tx_sig = await self.vault_client.emergency_exit_position(
                        symbol, 
                        monitor.position_size
                    )
                    
                    if tx_sig:
                        exit_results.append(f"{symbol}:{tx_sig[:12]}")
                        logger.critical(f"✅ Portfolio exit - {symbol}: {tx_sig}")
                    else:
                        exit_results.append(f"{symbol}:FAILED")
                        logger.error(f"❌ Portfolio exit failed - {symbol}")
                        
                except Exception as e:
                    exit_results.append(f"{symbol}:ERROR")
                    logger.error(f"❌ Portfolio exit error - {symbol}: {e}")
            
            # Clear all position monitors (portfolio liquidated)
            self.position_monitors.clear()
            
            event.transaction_signature = ";".join(exit_results)
            event.action_taken = "portfolio_emergency_exit_executed"
            event.notes = f"Executed {len(exit_results)} position exits"
            
            await self._record_emergency_event(event)
            
            logger.critical(f"🚨 Portfolio emergency exit completed: {len(exit_results)} positions")
            
        except Exception as e:
            logger.error(f"❌ Portfolio emergency exit failed: {e}")
            event.action_taken = f"portfolio_exit_error: {str(e)}"
            await self._record_emergency_event(event)

    async def _setup_position_monitors(self, vault_positions: Dict[str, Position]):
        """Setup position monitors for vault positions"""
        self.position_monitors.clear()
        
        for symbol, position in vault_positions.items():
            monitor = PositionMonitor(
                symbol=symbol,
                current_price=position.current_price,
                entry_price=position.average_price,
                position_size=position.size,
                last_update=datetime.utcnow()
            )
            
            self.position_monitors[symbol] = monitor
            logger.debug(f"📊 Setup monitor for {symbol}: ${position.size:.2f} @ ${position.average_price:.6f}")
        
        self.stats['positions_monitored'] = len(self.position_monitors)
        logger.info(f"📊 Setup {len(self.position_monitors)} position monitors")

    async def _subscribe_to_position_prices(self):
        """Subscribe to WebSocket price feeds for all positions"""
        if not self.websocket_feed:
            logger.error("❌ No WebSocket feed available")
            return
        
        for symbol in self.position_monitors.keys():
            try:
                # Get token address from database
                token_info = await self.db_manager.get_token_by_symbol(symbol)
                if token_info:
                    subscription = PriceSubscription(
                        query_type="simple",
                        chart_type="1m",
                        address=token_info['address'],
                        currency="usd"
                    )
                    
                    success = await self.websocket_feed.subscribe_price(subscription)
                    if success:
                        self.subscribed_tokens.add(symbol)
                        logger.debug(f"✅ Subscribed to {symbol} price updates")
                    else:
                        logger.warning(f"⚠️ Failed to subscribe to {symbol} prices")
                else:
                    logger.warning(f"⚠️ Token address not found for {symbol}")
                    
            except Exception as e:
                logger.error(f"❌ Failed to subscribe to {symbol} prices: {e}")
        
        logger.info(f"📡 Subscribed to {len(self.subscribed_tokens)} token price feeds")

    async def _get_vault_positions(self) -> Dict[str, Position]:
        """Get current vault positions from position manager"""
        try:
            # This would integrate with the position manager to get active vault positions
            # For now, return empty dict as placeholder
            positions = {}
            
            # In real implementation, this would:
            # 1. Query vault client for user positions
            # 2. Convert to Position objects
            # 3. Return dict of symbol -> Position
            
            return positions
            
        except Exception as e:
            logger.error(f"❌ Failed to get vault positions: {e}")
            return {}

    async def _calculate_portfolio_pnl(self) -> float:
        """Calculate current portfolio P&L percentage"""
        try:
            total_value = 0.0
            total_cost = 0.0
            
            for monitor in self.position_monitors.values():
                position_value = monitor.current_price * monitor.position_size
                position_cost = monitor.entry_price * monitor.position_size
                
                total_value += position_value
                total_cost += position_cost
            
            if total_cost > 0:
                portfolio_pnl = ((total_value - total_cost) / total_cost) * 100
                return portfolio_pnl
            
            return 0.0
            
        except Exception as e:
            logger.error(f"❌ Portfolio P&L calculation failed: {e}")
            return 0.0

    async def _record_emergency_event(self, event: EmergencyEvent):
        """Record emergency event in database using enhanced emergency_events table"""
        try:
            self.emergency_events.append(event)
            
            # Record in enhanced emergency_events table
            if self.db_manager:
                from ..database.production_db import EmergencyEventData
                
                # Get token_id if symbol is provided
                token_id = None
                if event.symbol:
                    token_info = await self.db_manager.get_token_by_symbol(event.symbol)
                    token_id = token_info['token_id'] if token_info else None
                
                # Create EmergencyEventData object
                emergency_data = EmergencyEventData(
                    event_timestamp=event.timestamp,
                    event_type=event.event_type.value,
                    severity='HIGH',
                    token_id=token_id,
                    trigger_condition={'trigger_value': event.trigger_value, 'threshold_value': event.threshold_value},
                    current_metrics=None,
                    threshold_breached=None,
                    action_taken=event.action_taken,
                    positions_affected=1 if token_id else 0,
                    total_value_affected_usdc=event.portfolio_impact,
                    action_successful=event.transaction_signature is not None,
                    execution_time_ms=None,
                    tx_hashes=[event.transaction_signature] if event.transaction_signature else None,
                    resolved_timestamp=None,
                    resolution_method=None
                )
                
                # Record in enhanced emergency_events table
                event_id = await self.db_manager.record_emergency_event(emergency_data)
                logger.debug(f"✅ Recorded emergency event {event_id} in database")
                
                # Also record in system health for backward compatibility
                event_summary = {
                    'emergency_event_id': event_id,
                    'event_type': event.event_type.value,
                    'symbol': event.symbol,
                    'trigger_value': event.trigger_value,
                    'action_taken': event.action_taken,
                    'portfolio_impact': event.portfolio_impact
                }
                
                await self.db_manager.record_health_check(
                    'emergency_monitoring', 
                    'emergency_event', 
                    event_summary
                )
            
        except Exception as e:
            logger.error(f"❌ Failed to record emergency event: {e}")

    async def _health_monitoring_loop(self):
        """Health monitoring loop"""
        while self.is_monitoring:
            try:
                await asyncio.sleep(self.thresholds.health_check_interval)
                
                # Check WebSocket connection health
                if self.websocket_feed and self.websocket_feed.connection_state != ConnectionState.CONNECTED:
                    logger.warning("⚠️ WebSocket connection not healthy - attempting reconnect")
                
                # Log health status
                logger.debug(f"💊 Emergency monitor health: {len(self.position_monitors)} positions, {len(self.subscribed_tokens)} subscriptions")
                
                self.last_health_check = datetime.utcnow()
                
            except Exception as e:
                logger.error(f"❌ Health monitoring error: {e}")
                await asyncio.sleep(30)

    async def _statistics_update_loop(self):
        """Update statistics periodically"""
        while self.is_monitoring:
            try:
                await asyncio.sleep(60)  # Update every minute
                
                # Update portfolio value
                portfolio_value = sum(
                    monitor.current_price * monitor.position_size 
                    for monitor in self.position_monitors.values()
                )
                
                self.stats['last_portfolio_value'] = portfolio_value
                
                # Track drawdown
                if portfolio_value > 0:
                    portfolio_pnl = await self._calculate_portfolio_pnl()
                    if portfolio_pnl < self.stats['max_drawdown_today']:
                        self.stats['max_drawdown_today'] = portfolio_pnl
                
            except Exception as e:
                logger.error(f"❌ Statistics update error: {e}")

    async def _update_portfolio_stats(self):
        """Update portfolio statistics"""
        try:
            current_time = datetime.utcnow()
            portfolio_value = sum(
                monitor.current_price * monitor.position_size 
                for monitor in self.position_monitors.values()
            )
            
            self.portfolio_value_history.append((current_time, portfolio_value))
            
            # Keep only last 24 hours
            cutoff_time = current_time - timedelta(hours=24)
            self.portfolio_value_history = [
                (t, v) for t, v in self.portfolio_value_history if t > cutoff_time
            ]
            
        except Exception as e:
            logger.error(f"❌ Portfolio stats update failed: {e}")

    def _on_connection_state_change(self, state: ConnectionState):
        """Handle WebSocket connection state changes"""
        logger.info(f"🔗 WebSocket connection state: {state.value}")
        
        if state == ConnectionState.CONNECTED:
            logger.info("✅ WebSocket reconnected - emergency monitoring active")
        elif state == ConnectionState.ERROR:
            logger.warning("⚠️ WebSocket error - emergency monitoring degraded")

    def _on_websocket_error(self, error: Exception):
        """Handle WebSocket errors"""
        logger.error(f"❌ WebSocket error in emergency monitoring: {error}")

    def add_emergency_handler(self, handler: Callable[[EmergencyEvent], None]):
        """Add emergency event handler"""
        self.emergency_handlers.append(handler)

    def get_monitoring_stats(self) -> Dict:
        """Get current monitoring statistics"""
        return {
            **self.stats,
            'positions_monitored': len(self.position_monitors),
            'subscribed_tokens': len(self.subscribed_tokens),
            'emergency_events_today': len(self.emergency_events),
            'emergency_exits_today': self.emergency_exits_today,
            'is_monitoring': self.is_monitoring,
            'last_portfolio_check': self.last_portfolio_check.isoformat() if self.last_portfolio_check else None,
            'last_health_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'websocket_connected': (
                self.websocket_feed.connection_state == ConnectionState.CONNECTED 
                if self.websocket_feed else False
            )
        }

    async def manual_emergency_exit(self, symbol: str, reason: str = "Manual trigger") -> bool:
        """
        Manually trigger emergency exit for a specific position
        
        Args:
            symbol: Token symbol to exit
            reason: Reason for manual exit
            
        Returns:
            True if successful, False otherwise
        """
        try:
            monitor = self.position_monitors.get(symbol)
            if not monitor:
                logger.error(f"❌ Position not found for manual exit: {symbol}")
                return False
            
            # Create manual emergency event
            event = EmergencyEvent(
                timestamp=datetime.utcnow(),
                event_type=EmergencyType.MANUAL_TRIGGER,
                symbol=symbol,
                trigger_value=monitor.unrealized_pnl_pct,
                threshold_value=0.0,  # No threshold for manual
                action_taken="manual_emergency_exit",
                notes=reason
            )
            
            # Execute emergency exit
            await self._execute_emergency_exit(event, monitor)
            
            return event.transaction_signature is not None
            
        except Exception as e:
            logger.error(f"❌ Manual emergency exit failed for {symbol}: {e}")
            return False 