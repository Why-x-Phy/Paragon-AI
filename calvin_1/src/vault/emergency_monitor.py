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
from ..trading.position_manager import PositionManager
from ..database.production_db import PositionData
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
            if not self.db_manager:
                from ..database.production_db import get_db_manager
                self.db_manager = await get_db_manager()
            
            # Initialize vault client
            await self.vault_client.initialize()
            
            # Initialize position manager
            await self.position_manager.initialize()
            
            # 🆕 RECOVER EMERGENCY STATE FROM DATABASE
            await self._recover_emergency_state()
            
            logger.info("✅ Emergency Monitor initialized with state recovery")
            
        except Exception as e:
            logger.error(f"Failed to initialize Emergency Monitor: {e}")
            raise

    async def _recover_emergency_state(self):
        """Recover emergency monitor state from database after restart"""
        try:
            # 1. Recover daily emergency exit count from today's emergency events
            await self._recover_daily_exit_count()
            
            # 2. Recover active emergency monitoring settings from health checks
            await self._recover_monitoring_settings()
            
            logger.info("✅ Emergency Monitor state recovered from database")
            
        except Exception as e:
            logger.warning(f"⚠️ Emergency state recovery failed (starting fresh): {e}")
            # Continue with default state - not critical for operation
    
    async def _recover_daily_exit_count(self):
        """Recover today's emergency exit count from emergency_events table"""
        try:
            # Query today's emergency events that resulted in exits
            query = """
                SELECT COUNT(*)
                FROM emergency_events 
                WHERE event_timestamp >= CURRENT_DATE
                  AND action_taken IN ('position_exit', 'portfolio_exit', 'emergency_liquidation')
                  AND action_successful = true
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query)
                
            if row:
                self.emergency_exits_today = row['count']
                logger.info(f"🔄 Recovered daily emergency exits: {self.emergency_exits_today}/{self.thresholds.max_daily_exits}")
                
                # Log warning if approaching limit
                if self.emergency_exits_today >= self.thresholds.max_daily_exits * 0.8:
                    logger.warning(f"⚠️ Daily emergency exits approaching limit: {self.emergency_exits_today}/{self.thresholds.max_daily_exits}")
                
        except Exception as e:
            logger.warning(f"Failed to recover daily exit count: {e}")
            self.emergency_exits_today = 0
    
    async def _recover_monitoring_settings(self):
        """Recover emergency monitoring settings from health checks"""
        try:
            # Query recent emergency monitor health check to get last known state
            query = """
                SELECT details
                FROM system_health 
                WHERE component = 'emergency_monitor'
                  AND status = 'healthy'
                  AND check_time >= NOW() - INTERVAL '6 hours'
                ORDER BY check_time DESC
                LIMIT 1
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query)
                
            if row and row['details']:
                # Parse JSON string from database
                import json
                try:
                    if isinstance(row['details'], str):
                        state_data = json.loads(row['details'])
                    else:
                        state_data = row['details']  # Already parsed
                    
                    # Restore monitoring statistics if available (using the correct stats attribute)
                    if isinstance(state_data, dict):
                        self.stats.update({
                            'total_alerts_today': state_data.get('total_alerts_today', 0),
                            'portfolio_checks_today': state_data.get('portfolio_checks_today', 0),
                            'position_checks_today': state_data.get('position_checks_today', 0)
                        })
                        
                        logger.info(f"🔄 Recovered emergency monitoring stats: {self.stats['total_alerts_today']} alerts today")
                    else:
                        logger.warning(f"⚠️ Invalid state data format: {type(state_data)}")
                        
                except (json.JSONDecodeError, TypeError) as json_error:
                    logger.warning(f"⚠️ Failed to parse monitoring settings JSON: {json_error}")
                    # Continue with default settings
                
        except Exception as e:
            logger.warning(f"Failed to recover monitoring settings: {e}")
            # Use default settings

    async def start_monitoring(self, vault_positions: Optional[Dict[str, PositionData]] = None):
        """Start emergency monitoring with enhanced startup validation"""
        try:
            if self.is_monitoring:
                logger.warning("Emergency monitoring is already running")
                return

            logger.info("🚨 Starting emergency stop loss monitoring...")
            
            # Enhanced startup validation
            startup_issues = await self._validate_startup_conditions()
            if startup_issues:
                for issue in startup_issues:
                    logger.warning(f"⚠️ Startup validation issue: {issue}")
            
            # Attempt to recover from previous state
            await self._recover_emergency_state()
            
            # Get vault positions (with improved error handling)
            if not vault_positions:
                vault_positions = await self._get_vault_positions()
            
            if not vault_positions:
                logger.warning("⚠️ No vault positions found to monitor")
                # Still start monitoring for future positions
                self.is_monitoring = True
                return
            
            # Setup position monitors
            await self._setup_position_monitors(vault_positions)
            
            # Subscribe to price feeds
            await self._subscribe_to_position_prices()
            
            # Start monitoring tasks
            self.is_monitoring = True
            
            # Start monitoring loops with error recovery
            asyncio.create_task(self._position_monitoring_loop_with_recovery())
            asyncio.create_task(self._portfolio_monitoring_loop_with_recovery())
            asyncio.create_task(self._health_monitoring_loop_with_recovery())
            asyncio.create_task(self._statistics_update_loop_with_recovery())
            
            logger.info(f"✅ Emergency monitoring started with {len(self.position_monitors)} positions")
            
        except Exception as e:
            logger.error(f"❌ Failed to start emergency monitoring: {e}")
            self.is_monitoring = False
            raise

    async def _validate_startup_conditions(self) -> List[str]:
        """Validate startup conditions and return list of issues"""
        issues = []
        
        try:
            # Check database connectivity
            if not self.db_manager:
                try:
                    from ..database.production_db import get_db_manager
                    self.db_manager = await asyncio.wait_for(get_db_manager(), timeout=10.0)
                except asyncio.TimeoutError:
                    issues.append("Database manager initialization timed out")
                except Exception as e:
                    issues.append(f"Database manager initialization failed: {e}")
            
            if self.db_manager:
                try:
                    health_ok = await asyncio.wait_for(self.db_manager.health_check(), timeout=5.0)
                    if not health_ok:
                        issues.append("Database health check failed")
                except asyncio.TimeoutError:
                    issues.append("Database health check timed out")
                except Exception as e:
                    issues.append(f"Database health check error: {e}")
            
            # Check vault client connectivity
            try:
                vault_state = await asyncio.wait_for(self.vault_client.get_vault_state(), timeout=10.0)
                if vault_state.get('error'):
                    issues.append(f"Vault state error: {vault_state['error']}")
                if not vault_state.get('initialized', False):
                    issues.append("Vault is not initialized")
            except asyncio.TimeoutError:
                issues.append("Vault state query timed out")
            except Exception as e:
                issues.append(f"Vault client error: {e}")
            
            # Check WebSocket feed
            if self.websocket_feed:
                try:
                    connection_state = getattr(self.websocket_feed, 'connection_state', None)
                    if connection_state != ConnectionState.CONNECTED:
                        issues.append(f"WebSocket not connected: {connection_state}")
                except Exception as e:
                    issues.append(f"WebSocket state check error: {e}")
            else:
                issues.append("WebSocket feed not available")
                
        except Exception as e:
            issues.append(f"Startup validation error: {e}")
        
        return issues

    async def _position_monitoring_loop_with_recovery(self):
        """Position monitoring loop with error recovery"""
        while self.is_monitoring:
            try:
                await asyncio.sleep(self.thresholds.price_check_interval)
                
                # Check individual stop losses for all positions
                for symbol in list(self.position_monitors.keys()):
                    try:
                        await self._check_individual_stop_loss(symbol)
                    except Exception as e:
                        logger.error(f"Error checking stop loss for {symbol}: {e}")
                        # Continue with other positions
                        continue
                
            except Exception as e:
                logger.error(f"Position monitoring loop error: {e}")
                await asyncio.sleep(30)  # Longer delay on error

    async def _portfolio_monitoring_loop_with_recovery(self):
        """Portfolio monitoring loop with error recovery"""
        while self.is_monitoring:
            try:
                await asyncio.sleep(self.thresholds.portfolio_check_interval)
                
                await self._check_portfolio_stop_loss()
                await self._check_volatility_conditions()
                await self._update_portfolio_stats()
                
            except Exception as e:
                logger.error(f"Portfolio monitoring loop error: {e}")
                await asyncio.sleep(60)  # Longer delay on error

    async def _health_monitoring_loop_with_recovery(self):
        """Health monitoring loop with error recovery"""
        while self.is_monitoring:
            try:
                await asyncio.sleep(self.thresholds.health_check_interval)
                
                # Check WebSocket connection health
                if self.websocket_feed and self.websocket_feed.connection_state != ConnectionState.CONNECTED:
                    logger.warning("⚠️ WebSocket connection not healthy - attempting reconnect")
                
                # Check database connectivity
                if self.db_manager:
                    try:
                        db_healthy = await asyncio.wait_for(self.db_manager.health_check(), timeout=5.0)
                        if not db_healthy:
                            logger.warning("⚠️ Database health check failed")
                    except asyncio.TimeoutError:
                        logger.warning("⚠️ Database health check timed out")
                    except Exception as e:
                        logger.warning(f"⚠️ Database health check error: {e}")
                
                # Log health status
                logger.debug(f"💊 Emergency monitor health: {len(self.position_monitors)} positions, {len(self.subscribed_tokens)} subscriptions")
                
                self.last_health_check = datetime.utcnow()
                
            except Exception as e:
                logger.error(f"❌ Health monitoring error: {e}")
                await asyncio.sleep(30)

    async def _statistics_update_loop_with_recovery(self):
        """Statistics update loop with error recovery"""
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
                await asyncio.sleep(60)  # Continue despite errors

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
        """Original portfolio monitoring loop for backward compatibility"""
        while self.is_monitoring:
            try:
                await asyncio.sleep(self.thresholds.portfolio_check_interval)
                
                await self._check_portfolio_stop_loss()
                await self._check_volatility_conditions()
                
            except Exception as e:
                logger.error(f"❌ Portfolio monitoring loop error: {e}")
                await asyncio.sleep(60)

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

    async def _setup_position_monitors(self, vault_positions: Dict[str, PositionData]):
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
        
        subscription_count = 0
        for symbol in self.position_monitors.keys():
            try:
                # Get token address from database with error handling
                token_info = None
                try:
                    if self.db_manager:
                        token_info = await self.db_manager.get_token_by_symbol(symbol)
                except Exception as db_error:
                    logger.warning(f"Database error getting token info for {symbol}: {db_error}")
                    continue
                
                if token_info:
                    subscription = PriceSubscription(
                        query_type="simple",
                        chart_type="1m",
                        address=token_info['address'],
                        currency="usd"
                    )
                    
                    try:
                        success = await self.websocket_feed.subscribe_price(subscription)
                        if success:
                            self.subscribed_tokens.add(symbol)
                            subscription_count += 1
                            logger.debug(f"✅ Subscribed to {symbol} price updates")
                        else:
                            logger.warning(f"⚠️ Failed to subscribe to {symbol} prices")
                    except Exception as sub_error:
                        logger.warning(f"Subscription error for {symbol}: {sub_error}")
                else:
                    logger.warning(f"⚠️ Token address not found for {symbol}")
                    
            except Exception as e:
                logger.error(f"❌ Failed to subscribe to {symbol} prices: {e}")
        
        logger.info(f"📡 Subscribed to {subscription_count} token price feeds")

    async def _get_vault_positions(self) -> Dict[str, PositionData]:
        """Get current vault positions from position manager"""
        try:
            positions = {}
            
            # Get vault state to check if we have any token positions
            vault_state = None
            try:
                vault_state = await self.vault_client.get_vault_state()
            except Exception as vault_error:
                logger.warning(f"Failed to get vault state: {vault_error}")
                # Continue with empty vault state for graceful degradation
                vault_state = {'paused': True, 'initialized': False}
            
            if not vault_state or vault_state.get('paused', True) or not vault_state.get('initialized', False):
                logger.debug("Vault is paused, not initialized, or unavailable - no positions to monitor")
                return positions
            
            # Ensure database manager is available with connection retry
            if not self.db_manager:
                try:
                    from ..database.production_db import get_db_manager
                    self.db_manager = await get_db_manager()
                except Exception as db_init_error:
                    logger.error(f"Failed to initialize database manager: {db_init_error}")
                    return positions
            
            # Get active positions from position manager
            if hasattr(self.position_manager, 'get_active_positions'):
                try:
                    open_positions = self.position_manager.get_active_positions()
                    
                    for position_id, position_data in open_positions.items():
                        # Get token symbol from database with error handling
                        if hasattr(position_data, 'token_id'):
                            try:
                                token_info = await self.db_manager.get_token_by_id(position_data.token_id)
                                if token_info:
                                    symbol = token_info.get('symbol', f'TOKEN_{position_data.token_id}')
                                    
                                    # Create Position object for emergency monitoring
                                    from ..trading.position_manager import Position
                                    position = Position(
                                        symbol=symbol,
                                        size=getattr(position_data, 'size', 0.0),
                                        average_price=getattr(position_data, 'average_price', 0.0),
                                        current_price=getattr(position_data, 'current_price', 0.0),
                                        unrealized_pnl=getattr(position_data, 'unrealized_pnl_usdc', 0.0),
                                        entry_time=getattr(position_data, 'entry_time', datetime.utcnow())
                                    )
                                    
                                    positions[symbol] = position
                                    logger.debug(f"📊 Found vault position: {symbol} - ${position.size:.2f} @ ${position.average_price:.6f}")
                            except Exception as token_error:
                                logger.warning(f"Failed to get token info for position {position_id}: {token_error}")
                                continue
                except Exception as position_error:
                    logger.warning(f"Failed to get active positions from position manager: {position_error}")
            
            # Alternative: Query vault client directly for token balances
            if not positions and hasattr(self.vault_client, 'get_vault_token_balances'):
                try:
                    token_balances = await self.vault_client.get_vault_token_balances()
                    
                    for token_address, balance_info in token_balances.items():
                        if balance_info.get('balance', 0) > 0:
                            # Get token info from database with error handling
                            try:
                                token_info = await self.db_manager.get_token_by_address(token_address)
                                if token_info:
                                    symbol = token_info.get('symbol', token_address[:8])
                                    
                                    # Get current price with fallback
                                    current_price = 0.0
                                    try:
                                        current_price = await self.db_manager.get_latest_price(token_info['token_id'])
                                        current_price = current_price or 0.0
                                    except Exception as price_error:
                                        logger.debug(f"Could not get current price for {symbol}: {price_error}")
                                    
                                    # Create position from vault balance
                                    from ..trading.position_manager import Position
                                    position = Position(
                                        symbol=symbol,
                                        size=balance_info['balance'],
                                        average_price=balance_info.get('average_price', current_price),
                                        current_price=current_price,
                                        unrealized_pnl=0.0,  # Will be calculated
                                        entry_time=datetime.utcnow()
                                    )
                                    
                                    positions[symbol] = position
                                    logger.debug(f"📊 Found vault token balance: {symbol} - {balance_info['balance']:.6f} tokens")
                            except Exception as token_error:
                                logger.warning(f"Failed to get token info for address {token_address}: {token_error}")
                                continue
                                
                except Exception as balance_error:
                    logger.debug(f"Could not get vault token balances: {balance_error}")
            
            logger.info(f"📊 Retrieved {len(positions)} vault positions for emergency monitoring")
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

    async def _update_portfolio_stats(self):
        """Update portfolio statistics"""
        try:
            current_time = datetime.utcnow()
            portfolio_value = sum(
                monitor.current_price * monitor.position_size 
                for monitor in self.position_monitors.values()
            )
            
            self.portfolio_value_history.append((current_time, portfolio_value))
            
            # Store portfolio monitoring data in database
            await self._store_portfolio_monitoring_data(current_time, portfolio_value)
            
            # Keep only last 24 hours
            cutoff_time = current_time - timedelta(hours=24)
            self.portfolio_value_history = [
                (t, v) for t, v in self.portfolio_value_history if t > cutoff_time
            ]
            
        except Exception as e:
            logger.error(f"❌ Portfolio stats update failed: {e}")

    async def _store_portfolio_monitoring_data(self, timestamp: datetime, portfolio_value: float):
        """Store portfolio monitoring data in database"""
        try:
            if not self.db_manager:
                return
            
            # Calculate portfolio P&L
            portfolio_pnl_pct = await self._calculate_portfolio_pnl()
            
            # Store monitoring data
            monitoring_data = {
                'timestamp': timestamp.isoformat(),
                'portfolio_value': portfolio_value,
                'portfolio_pnl_pct': portfolio_pnl_pct,
                'positions_monitored': len(self.position_monitors),
                'emergency_exits_today': self.emergency_exits_today,
                'max_drawdown_today': self.stats.get('max_drawdown_today', 0.0)
            }
            
            # Record in system health for monitoring
            await self.db_manager.record_health_check(
                'emergency_portfolio_monitoring',
                'updated',
                monitoring_data
            )
            
            logger.debug(f"📊 Stored portfolio monitoring data: ${portfolio_value:.2f} ({portfolio_pnl_pct:+.2f}%)")
            
        except Exception as e:
            logger.error(f"❌ Failed to store portfolio monitoring data: {e}")

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

    async def stop_monitoring(self):
        """Stop emergency monitoring with proper cleanup"""
        logger.info("🛑 Stopping emergency stop loss monitoring...")
        
        self.is_monitoring = False
        
        try:
            # Stop WebSocket feed
            if self.websocket_feed:
                try:
                    await self.websocket_feed.stop()
                    logger.info("✅ WebSocket feed stopped")
                except Exception as e:
                    logger.warning(f"Error stopping WebSocket feed: {e}")
            
            # Close database connections
            if self.db_manager:
                try:
                    await self.db_manager.close()
                except Exception as e:
                    logger.warning(f"Error closing database manager: {e}")
            
            # Close vault client
            try:
                await self.vault_client.close()
            except Exception as e:
                logger.warning(f"Error closing vault client: {e}")
            
            logger.info("🏁 Emergency monitoring stopped")
            
        except Exception as e:
            logger.error(f"❌ Error stopping emergency monitoring: {e}") 