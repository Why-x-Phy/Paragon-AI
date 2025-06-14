"""
Calvin AI Position Management System

Handles real-time position tracking and risk management:
- Real-time position tracking from WebSocket feeds
- Stop-loss and take-profit trigger detection
- Position size and P&L calculation  
- Risk monitoring and alerts
- Database integration for position persistence
- Integration with vault system for reporting
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
from enum import Enum

from ..database.production_db import (
    ProductionDBManager,
    PositionData,
    TradeData,
    get_db_manager
)
from ..data.realtime_storage import RealtimeDataStorage, PositionTrigger
from ..config.config import config


class PositionStatus(Enum):
    """Position status enumeration"""
    OPEN = "open"
    CLOSED = "closed"
    PARTIAL = "partial"


class PositionType(Enum):
    """Position type enumeration"""
    LONG = "long"
    SHORT = "short"


class TriggerType(Enum):
    """Trigger type enumeration"""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    RISK_LIMIT = "risk_limit"


@dataclass
class RiskLimits:
    """Risk management configuration"""
    max_position_size_usdc: float = 10000.0  # Max position size in USDC
    max_portfolio_exposure_pct: float = 80.0  # Max % of portfolio in positions
    max_single_token_exposure_pct: float = 20.0  # Max % exposure to single token
    max_drawdown_pct: float = 10.0  # Max portfolio drawdown %
    max_daily_loss_usdc: float = 1000.0  # Max daily loss in USDC
    
    # Stop loss settings
    default_stop_loss_pct: float = 5.0  # Default 5% stop loss
    max_stop_loss_pct: float = 15.0  # Maximum 15% stop loss
    
    # Take profit settings  
    default_take_profit_pct: float = 10.0  # Default 10% take profit
    max_take_profit_pct: float = 50.0  # Maximum 50% take profit
    
    # Position sizing
    min_position_size_usdc: float = 10.0  # Minimum position size
    position_size_precision: int = 2  # Decimal places for position sizing


@dataclass
class PositionAlert:
    """Position alert data structure"""
    alert_id: str
    position_id: int
    alert_type: str  # 'stop_loss', 'take_profit', 'risk_limit', 'exposure'
    severity: str  # 'info', 'warning', 'critical'
    message: str
    current_price: float
    trigger_price: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    acknowledged: bool = False


class PositionManager:
    """
    Real-time position management system
    
    Integrates with:
    - RealtimeDataStorage for live price feeds and triggers
    - ProductionDBManager for position persistence
    - Risk management and alerts
    """
    
    def __init__(
        self, 
        db_manager: Optional[ProductionDBManager] = None,
        realtime_storage: Optional[RealtimeDataStorage] = None,
        risk_limits: Optional[RiskLimits] = None
    ):
        self.db_manager = db_manager  # Will be set during initialization
        self.realtime_storage = realtime_storage  # Will be set during initialization
        self.logger = logging.getLogger(__name__)
        
        # Load configuration from environment
        self.config = config
        self.risk_limits = risk_limits or self._load_risk_limits_from_env()
        
        # Position tracking
        self.active_positions: Dict[int, PositionData] = {}  # position_id -> PositionData
        self.position_by_token: Dict[int, List[int]] = {}  # token_id -> [position_ids]
        
        # Alert system
        self.alerts: List[PositionAlert] = []
        self.alert_callbacks: List[Callable[[PositionAlert], None]] = []
        
        # Performance tracking
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.daily_reset_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Statistics
        self.stats = {
            'positions_opened': 0,
            'positions_closed': 0,
            'stop_losses_triggered': 0,
            'take_profits_triggered': 0,
            'total_alerts': 0,
            'start_time': datetime.utcnow()
        }
        
        # State
        self.is_running = False
        
    def _load_risk_limits_from_env(self) -> RiskLimits:
        """Load risk limits from environment variables"""
        return RiskLimits(
            max_position_size_usdc=float(getattr(self.config, 'POSITION_MAX_SIZE_USDC', 10000.0)),
            max_portfolio_exposure_pct=float(getattr(self.config, 'PORTFOLIO_MAX_EXPOSURE_PCT', 80.0)),
            max_single_token_exposure_pct=float(getattr(self.config, 'TOKEN_MAX_EXPOSURE_PCT', 20.0)),
            max_drawdown_pct=float(getattr(self.config, 'MAX_DRAWDOWN_PCT', 10.0)),
            max_daily_loss_usdc=float(getattr(self.config, 'MAX_DAILY_LOSS_USDC', 1000.0)),
            
            default_stop_loss_pct=float(getattr(self.config, 'DEFAULT_STOP_LOSS_PCT', 5.0)),
            max_stop_loss_pct=float(getattr(self.config, 'MAX_STOP_LOSS_PCT', 15.0)),
            
            default_take_profit_pct=float(getattr(self.config, 'DEFAULT_TAKE_PROFIT_PCT', 10.0)),
            max_take_profit_pct=float(getattr(self.config, 'MAX_TAKE_PROFIT_PCT', 50.0)),
            
            min_position_size_usdc=float(getattr(self.config, 'MIN_POSITION_SIZE_USDC', 10.0)),
            position_size_precision=int(getattr(self.config, 'POSITION_SIZE_PRECISION', 2))
        )
    
    async def initialize(self):
        """Initialize the position manager"""
        try:
            # Initialize database manager if not provided
            if self.db_manager is None:
                self.db_manager = await get_db_manager()
            
            # Load existing open positions
            await self._load_open_positions()
            
            # Set up trigger callbacks if realtime storage is available
            if self.realtime_storage:
                self.realtime_storage.add_trigger_callback(self._handle_position_trigger)
            
            self.logger.info(f"Position manager initialized with {len(self.active_positions)} open positions")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize position manager: {e}")
            raise
    
    async def _load_open_positions(self):
        """Load open positions from database"""
        try:
            open_positions = await self.db_manager.get_open_positions()
            
            self.active_positions.clear()
            self.position_by_token.clear()
            
            for position in open_positions:
                self.active_positions[position.position_id] = position
                
                # Group by token
                if position.token_id not in self.position_by_token:
                    self.position_by_token[position.token_id] = []
                self.position_by_token[position.token_id].append(position.position_id)
            
            self.logger.info(f"Loaded {len(open_positions)} open positions")
            
        except Exception as e:
            self.logger.error(f"Failed to load open positions: {e}")
            raise
    
    async def start(self):
        """Start the position manager"""
        if self.is_running:
            self.logger.warning("Position manager already running")
            return
        
        try:
            self.is_running = True
            
            # Start daily P&L reset task
            asyncio.create_task(self._daily_reset_task())
            
            # Start position monitoring task
            asyncio.create_task(self._position_monitoring_task())
            
            self.logger.info("Position manager started")
            
        except Exception as e:
            self.logger.error(f"Failed to start position manager: {e}")
            self.is_running = False
            raise
    
    async def stop(self):
        """Stop the position manager"""
        self.is_running = False
        self.logger.info("Position manager stopped")
    
    # =========================================================================
    # POSITION LIFECYCLE MANAGEMENT
    # =========================================================================
    
    async def open_position(
        self,
        token_id: int,
        position_type: PositionType,
        entry_price: float,
        quantity: float,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        model_confidence: Optional[float] = None,
        model_version: Optional[str] = None,
        tx_hash: Optional[str] = None
    ) -> int:
        """
        Open a new position
        
        Args:
            token_id: Token ID from database
            position_type: LONG or SHORT
            entry_price: Entry price for the position
            quantity: Quantity of tokens
            stop_loss_pct: Stop loss percentage (optional)
            take_profit_pct: Take profit percentage (optional)
            model_confidence: Model prediction confidence (optional)
            model_version: Model version used (optional)
            tx_hash: Transaction hash (optional)
            
        Returns:
            Position ID
        """
        try:
            # Validate risk limits
            position_value = entry_price * quantity
            await self._validate_position_risk(token_id, position_value)
            
            # Calculate stop loss and take profit prices
            stop_loss_price = None
            take_profit_price = None
            
            if stop_loss_pct:
                stop_loss_pct = min(stop_loss_pct, self.risk_limits.max_stop_loss_pct)
                if position_type == PositionType.LONG:
                    stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
                else:
                    stop_loss_price = entry_price * (1 + stop_loss_pct / 100)
            
            if take_profit_pct:
                take_profit_pct = min(take_profit_pct, self.risk_limits.max_take_profit_pct)
                if position_type == PositionType.LONG:
                    take_profit_price = entry_price * (1 + take_profit_pct / 100)
                else:
                    take_profit_price = entry_price * (1 - take_profit_pct / 100)
            
            # Create position data
            position = PositionData(
                position_id=None,  # Will be set by database
                token_id=token_id,
                position_type=position_type.value,
                status=PositionStatus.OPEN.value,
                entry_price=entry_price,
                entry_quantity=quantity,
                entry_value_usdc=position_value,
                entry_time=datetime.utcnow(),
                entry_tx_hash=tx_hash,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                model_prediction_confidence=model_confidence,
                model_version=model_version
            )
            
            # Save to database
            position_id = await self.db_manager.create_position(position)
            position.position_id = position_id
            
            # Add to active positions
            self.active_positions[position_id] = position
            if token_id not in self.position_by_token:
                self.position_by_token[token_id] = []
            self.position_by_token[token_id].append(position_id)
            
            # Refresh triggers in realtime storage
            if self.realtime_storage:
                await self.realtime_storage.refresh_position_triggers()
            
            # Update statistics
            self.stats['positions_opened'] += 1
            
            self.logger.info(f"Opened {position_type.value} position {position_id} for token {token_id}: {quantity} @ ${entry_price}")
            
            return position_id
            
        except Exception as e:
            self.logger.error(f"Failed to open position: {e}")
            raise
    
    async def close_position(
        self,
        position_id: int,
        exit_price: float,
        quantity: Optional[float] = None,
        reason: str = "manual",
        tx_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Close a position (fully or partially)
        
        Args:
            position_id: Position ID to close
            exit_price: Exit price
            quantity: Quantity to close (None = full position)
            reason: Reason for closing
            tx_hash: Transaction hash
            
        Returns:
            Dict with closing details and P&L
        """
        try:
            if position_id not in self.active_positions:
                raise ValueError(f"Position {position_id} not found or not active")
            
            position = self.active_positions[position_id]
            close_quantity = quantity if quantity is not None else position.entry_quantity
            
            if close_quantity > position.entry_quantity:
                raise ValueError(f"Close quantity {close_quantity} exceeds position quantity {position.entry_quantity}")
            
            # Calculate P&L
            pnl_info = self._calculate_pnl(position, exit_price, close_quantity)
            
            # Determine new position status
            is_full_close = close_quantity >= position.entry_quantity
            new_status = PositionStatus.CLOSED if is_full_close else PositionStatus.PARTIAL
            
            # Update position in database
            updates = {
                'exit_price': exit_price,
                'exit_quantity': close_quantity,
                'exit_value_usdc': exit_price * close_quantity,
                'exit_time': datetime.utcnow(),
                'exit_tx_hash': tx_hash,
                'realized_pnl_usdc': pnl_info['realized_pnl'],
                'status': new_status.value
            }
            
            await self.db_manager.update_position(position_id, updates)
            
            # Update local position data
            for key, value in updates.items():
                setattr(position, key, value)
            
            # Remove from active positions if fully closed
            if is_full_close:
                del self.active_positions[position_id]
                if position.token_id in self.position_by_token:
                    self.position_by_token[position.token_id].remove(position_id)
                    if not self.position_by_token[position.token_id]:
                        del self.position_by_token[position.token_id]
                
                # Refresh triggers
                if self.realtime_storage:
                    await self.realtime_storage.refresh_position_triggers()
            
            # Update P&L tracking
            self.daily_pnl += pnl_info['realized_pnl']
            self.total_pnl += pnl_info['realized_pnl']
            
            # Update statistics
            self.stats['positions_closed'] += 1
            
            # Create alert for significant P&L
            if abs(pnl_info['realized_pnl']) > 100:  # Alert for P&L > $100
                alert = PositionAlert(
                    alert_id=f"pnl_{position_id}_{datetime.utcnow().timestamp()}",
                    position_id=position_id,
                    alert_type='pnl_significant',
                    severity='info' if pnl_info['realized_pnl'] > 0 else 'warning',
                    message=f"Position closed with {'profit' if pnl_info['realized_pnl'] > 0 else 'loss'} of ${pnl_info['realized_pnl']:.2f}",
                    current_price=exit_price
                )
                await self._emit_alert(alert)
            
            self.logger.info(f"Closed position {position_id}: {close_quantity} @ ${exit_price}, P&L: ${pnl_info['realized_pnl']:.2f}")
            
            return {
                'position_id': position_id,
                'close_type': 'full' if is_full_close else 'partial',
                'quantity_closed': close_quantity,
                'exit_price': exit_price,
                'reason': reason,
                **pnl_info
            }
            
        except Exception as e:
            self.logger.error(f"Failed to close position {position_id}: {e}")
            raise
    
    # =========================================================================
    # TRIGGER HANDLING
    # =========================================================================
    
    async def _handle_position_trigger(self, trigger: PositionTrigger, current_price: float):
        """Handle position trigger from realtime storage"""
        try:
            if trigger.position_id not in self.active_positions:
                self.logger.warning(f"Received trigger for inactive position {trigger.position_id}")
                return
            
            position = self.active_positions[trigger.position_id]
            
            self.logger.info(f"Position trigger fired: {trigger.trigger_type} for position {trigger.position_id} at ${current_price}")
            
            # Create alert
            alert = PositionAlert(
                alert_id=f"trigger_{trigger.position_id}_{datetime.utcnow().timestamp()}",
                position_id=trigger.position_id,
                alert_type=trigger.trigger_type,
                severity='critical',
                message=f"{trigger.trigger_type.replace('_', ' ').title()} triggered at ${current_price}",
                current_price=current_price,
                trigger_price=trigger.trigger_price
            )
            
            await self._emit_alert(alert)
            
            # Update statistics
            if trigger.trigger_type == 'stop_loss':
                self.stats['stop_losses_triggered'] += 1
            elif trigger.trigger_type == 'take_profit':
                self.stats['take_profits_triggered'] += 1
            
            # Note: Actual position closing should be handled by trading engine
            # This is just for monitoring and alerting
            
        except Exception as e:
            self.logger.error(f"Error handling position trigger: {e}")
    
    # =========================================================================
    # RISK MANAGEMENT
    # =========================================================================
    
    async def _validate_position_risk(self, token_id: int, position_value: float):
        """Validate position against risk limits"""
        # Check minimum position size
        if position_value < self.risk_limits.min_position_size_usdc:
            raise ValueError(f"Position value ${position_value:.2f} below minimum ${self.risk_limits.min_position_size_usdc}")
        
        # Check maximum position size
        if position_value > self.risk_limits.max_position_size_usdc:
            raise ValueError(f"Position value ${position_value:.2f} exceeds maximum ${self.risk_limits.max_position_size_usdc}")
        
        # Check daily loss limit
        if self.daily_pnl < -self.risk_limits.max_daily_loss_usdc:
            raise ValueError(f"Daily loss limit reached: ${self.daily_pnl:.2f}")
        
        # Check token exposure
        token_exposure = await self._calculate_token_exposure(token_id)
        max_token_exposure = self.risk_limits.max_single_token_exposure_pct / 100 * self._get_portfolio_value()
        
        if token_exposure + position_value > max_token_exposure:
            raise ValueError(f"Token exposure would exceed limit: ${token_exposure + position_value:.2f} > ${max_token_exposure:.2f}")
        
        # Check portfolio exposure
        portfolio_exposure = await self._calculate_portfolio_exposure()
        max_portfolio_exposure = self.risk_limits.max_portfolio_exposure_pct / 100 * self._get_portfolio_value()
        
        if portfolio_exposure + position_value > max_portfolio_exposure:
            raise ValueError(f"Portfolio exposure would exceed limit: ${portfolio_exposure + position_value:.2f} > ${max_portfolio_exposure:.2f}")
    
    async def _calculate_token_exposure(self, token_id: int) -> float:
        """Calculate current exposure to a specific token"""
        exposure = 0.0
        
        if token_id in self.position_by_token:
            for position_id in self.position_by_token[token_id]:
                position = self.active_positions[position_id]
                current_price = await self.db_manager.get_latest_price(token_id)
                if current_price:
                    exposure += position.entry_quantity * current_price
        
        return exposure
    
    async def _calculate_portfolio_exposure(self) -> float:
        """Calculate total portfolio exposure"""
        total_exposure = 0.0
        
        for position in self.active_positions.values():
            current_price = await self.db_manager.get_latest_price(position.token_id)
            if current_price:
                total_exposure += position.entry_quantity * current_price
        
        return total_exposure
    
    def _get_portfolio_value(self) -> float:
        """Get total portfolio value from vault smart contract"""
        # TODO: Integrate with vault smart contract when Phase 3 is implemented
        # 
        # Real implementation should:
        # 1. Query Calvin Vault Program for current total_usdc
        # 2. Add unrealized P&L from external positions  
        # 3. Add any pending settlement amounts
        # 
        # For now, use environment variable as fallback for development
        return float(getattr(self.config, 'PORTFOLIO_VALUE_USDC', 100000.0))
    
    # =========================================================================
    # P&L CALCULATION
    # =========================================================================
    
    def _calculate_pnl(self, position: PositionData, current_price: float, quantity: Optional[float] = None) -> Dict[str, float]:
        """Calculate P&L for a position"""
        calc_quantity = quantity if quantity is not None else position.entry_quantity
        
        if position.position_type == PositionType.LONG.value:
            pnl = (current_price - position.entry_price) * calc_quantity
        else:  # SHORT
            pnl = (position.entry_price - current_price) * calc_quantity
        
        pnl_pct = (pnl / (position.entry_price * calc_quantity)) * 100
        
        return {
            'realized_pnl': round(pnl, self.risk_limits.position_size_precision),
            'pnl_percentage': round(pnl_pct, 2),
            'quantity': calc_quantity,
            'entry_price': position.entry_price,
            'current_price': current_price
        }
    
    async def calculate_unrealized_pnl(self, position_id: int) -> Optional[Dict[str, float]]:
        """Calculate unrealized P&L for an open position"""
        try:
            if position_id not in self.active_positions:
                return None
            
            position = self.active_positions[position_id]
            current_price = await self.db_manager.get_latest_price(position.token_id)
            
            if not current_price:
                return None
            
            return self._calculate_pnl(position, current_price)
            
        except Exception as e:
            self.logger.error(f"Error calculating unrealized P&L for position {position_id}: {e}")
            return None
    
    async def get_portfolio_pnl(self) -> Dict[str, Any]:
        """Get portfolio-wide P&L summary"""
        try:
            total_unrealized = 0.0
            position_pnls = []
            
            for position_id, position in self.active_positions.items():
                pnl_info = await self.calculate_unrealized_pnl(position_id)
                if pnl_info:
                    total_unrealized += pnl_info['realized_pnl']  # Actually unrealized here
                    position_pnls.append({
                        'position_id': position_id,
                        'token_id': position.token_id,
                        **pnl_info
                    })
            
            return {
                'daily_realized_pnl': self.daily_pnl,
                'total_realized_pnl': self.total_pnl,
                'total_unrealized_pnl': total_unrealized,
                'combined_pnl': self.total_pnl + total_unrealized,
                'active_positions': len(self.active_positions),
                'position_details': position_pnls
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating portfolio P&L: {e}")
            return {'error': str(e)}
    
    # =========================================================================
    # MONITORING AND ALERTS
    # =========================================================================
    
    async def _position_monitoring_task(self):
        """Background task for position monitoring"""
        while self.is_running:
            try:
                await self._check_risk_limits()
                await self._update_unrealized_pnl()
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                self.logger.error(f"Error in position monitoring task: {e}")
                await asyncio.sleep(60)
    
    async def _check_risk_limits(self):
        """Check all risk limits and generate alerts"""
        try:
            # Check daily loss limit
            if self.daily_pnl <= -self.risk_limits.max_daily_loss_usdc:
                alert = PositionAlert(
                    alert_id=f"daily_loss_{datetime.utcnow().timestamp()}",
                    position_id=0,  # Portfolio-wide alert
                    alert_type='risk_limit',
                    severity='critical',
                    message=f"Daily loss limit reached: ${self.daily_pnl:.2f}",
                    current_price=0.0
                )
                await self._emit_alert(alert)
            
            # Check portfolio exposure
            portfolio_exposure = await self._calculate_portfolio_exposure()
            portfolio_value = self._get_portfolio_value()
            exposure_pct = (portfolio_exposure / portfolio_value) * 100
            
            if exposure_pct > self.risk_limits.max_portfolio_exposure_pct:
                alert = PositionAlert(
                    alert_id=f"portfolio_exposure_{datetime.utcnow().timestamp()}",
                    position_id=0,
                    alert_type='exposure',
                    severity='warning',
                    message=f"Portfolio exposure high: {exposure_pct:.1f}%",
                    current_price=0.0
                )
                await self._emit_alert(alert)
                
        except Exception as e:
            self.logger.error(f"Error checking risk limits: {e}")
    
    async def _update_unrealized_pnl(self):
        """Update unrealized P&L for all positions"""
        try:
            for position_id, position in self.active_positions.items():
                current_price = await self.db_manager.get_latest_price(position.token_id)
                if current_price:
                    pnl_info = self._calculate_pnl(position, current_price)
                    
                    # Update position unrealized P&L in database
                    await self.db_manager.update_position(
                        position_id, 
                        {'unrealized_pnl_usdc': pnl_info['realized_pnl']}
                    )
                    
                    # Update local copy
                    position.unrealized_pnl_usdc = pnl_info['realized_pnl']
                    
        except Exception as e:
            self.logger.error(f"Error updating unrealized P&L: {e}")
    
    async def _daily_reset_task(self):
        """Reset daily P&L at midnight"""
        while self.is_running:
            try:
                now = datetime.utcnow()
                next_reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                sleep_seconds = (next_reset - now).total_seconds()
                
                await asyncio.sleep(sleep_seconds)
                
                self.daily_pnl = 0.0
                self.daily_reset_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                
                self.logger.info("Daily P&L reset completed")
                
            except Exception as e:
                self.logger.error(f"Error in daily reset task: {e}")
                await asyncio.sleep(3600)  # Retry in 1 hour
    
    async def _emit_alert(self, alert: PositionAlert):
        """Emit an alert to all registered callbacks"""
        try:
            self.alerts.append(alert)
            self.stats['total_alerts'] += 1
            
            # Call all alert callbacks
            for callback in self.alert_callbacks:
                try:
                    await callback(alert)
                except Exception as e:
                    self.logger.error(f"Error in alert callback: {e}")
            
            # Log alert
            self.logger.log(
                logging.CRITICAL if alert.severity == 'critical' else logging.WARNING,
                f"ALERT [{alert.severity.upper()}] {alert.alert_type}: {alert.message}"
            )
            
        except Exception as e:
            self.logger.error(f"Error emitting alert: {e}")
    
    def add_alert_callback(self, callback: Callable[[PositionAlert], None]):
        """Add callback for position alerts"""
        self.alert_callbacks.append(callback)
    
    # =========================================================================
    # PUBLIC API
    # =========================================================================
    
    def get_active_positions(self) -> Dict[int, PositionData]:
        """Get all active positions"""
        return self.active_positions.copy()
    
    def get_position(self, position_id: int) -> Optional[PositionData]:
        """Get specific position"""
        return self.active_positions.get(position_id)
    
    def get_positions_by_token(self, token_id: int) -> List[PositionData]:
        """Get all positions for a specific token"""
        if token_id not in self.position_by_token:
            return []
        
        return [
            self.active_positions[pos_id] 
            for pos_id in self.position_by_token[token_id]
            if pos_id in self.active_positions
        ]
    
    def get_alerts(self, unacknowledged_only: bool = False) -> List[PositionAlert]:
        """Get position alerts"""
        if unacknowledged_only:
            return [alert for alert in self.alerts if not alert.acknowledged]
        return self.alerts.copy()
    
    async def acknowledge_alert(self, alert_id: str):
        """Acknowledge an alert"""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                break
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get position manager statistics"""
        uptime = datetime.utcnow() - self.stats['start_time']
        
        return {
            **self.stats,
            'uptime_seconds': uptime.total_seconds(),
            'active_positions': len(self.active_positions),
            'daily_pnl': self.daily_pnl,
            'total_pnl': self.total_pnl,
            'unacknowledged_alerts': len([a for a in self.alerts if not a.acknowledged]),
            'is_running': self.is_running
        }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_position_manager_instance: Optional[PositionManager] = None


async def get_position_manager(
    db_manager: Optional[ProductionDBManager] = None,
    realtime_storage: Optional[RealtimeDataStorage] = None,
    risk_limits: Optional[RiskLimits] = None
) -> PositionManager:
    """Get singleton position manager instance"""
    global _position_manager_instance
    
    if _position_manager_instance is None:
        _position_manager_instance = PositionManager(db_manager, realtime_storage, risk_limits)
        await _position_manager_instance.initialize()
    
    return _position_manager_instance


async def stop_position_manager():
    """Stop position manager instance"""
    global _position_manager_instance
    
    if _position_manager_instance:
        await _position_manager_instance.stop()
        _position_manager_instance = None 