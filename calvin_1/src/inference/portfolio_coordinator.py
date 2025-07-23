"""
Calvin AI Multi-Asset Portfolio Coordination Engine

Real-time portfolio coordination engine that manages trading signals across multiple assets
with sophisticated risk management and position allocation.

Key Features:
- Portfolio-level risk management (80% max exposure, 20% per asset)
- Multi-asset signal coordination with cash allocation logic
- Integration with existing SimpleStrategyEngine for individual signals
- Real-time position tracking and risk validation
- Performance attribution per asset
- Dynamic asset allocation based on signal strength and confidence

This integrates with:
- SimpleStrategyEngine for individual token signal generation
- LSTMModelRegistry for model access and strategy parameters
- PositionManager for portfolio state and risk validation
- ProductionDBManager for token data and price feeds
- Existing configuration system and environment variables

Architecture:
SimpleStrategyEngine (per token) → PortfolioCoordinator → Position Allocation → Risk Validation
"""

import asyncio
import os
from typing import Dict, List, Optional, Any, Tuple, Set, TYPE_CHECKING
from collections import deque
from datetime import datetime, timedelta, date
from dataclasses import dataclass, asdict
from enum import Enum
import numpy as np
import pandas as pd
import json

# Local imports
from ..config.config import config
from ..utils.logger import log
from .strategy_engine import StrategyEngine, TradingSignal, SignalType, SignalStrength
from .model_registry import get_model_registry
from ..trading.position_manager import PositionManager, RiskLimits
from ..database.production_db import get_db_manager

logger = log

class AllocationMethod(Enum):
    """Portfolio allocation methods"""
    EQUAL_WEIGHT = "equal_weight"
    SIGNAL_STRENGTH = "signal_strength"
    CONFIDENCE_WEIGHTED = "confidence_weighted"
    RISK_PARITY = "risk_parity"

@dataclass
class PortfolioConfig:
    """Configuration for portfolio coordination"""
    # Portfolio risk limits (from environment)
    max_portfolio_exposure_pct: float = 80.0  # Max % of portfolio in positions
    max_single_asset_exposure_pct: float = 20.0  # Max % in single asset
    min_cash_reserve_pct: float = 20.0  # Min cash reserve
    
    # Position sizing based on signal strength (percentage of portfolio value)
    base_position_size_pct: float = 2.0  # Base position size for weak signals
    strong_signal_multiplier: float = 1.5  # Additional % for strong signals
    moderate_signal_multiplier: float = 1.2  # Additional % for moderate signals
    weak_signal_multiplier: float = 0.8  # Additional % for weak signals
    min_position_size_usdc: float = 100.0  # Minimum position size (absolute floor)
    
    # Signal filtering  
    min_signal_confidence: float = None  # Will use config.MIN_PREDICTION_CONFIDENCE
    min_signal_strength_for_entry: str = 'weak'  # Minimum signal strength for entry
    signal_timeout_minutes: int = 15  # Signal validity timeout
    
    # Allocation method (simplified - signal strength determines position size directly)
    allocation_method: AllocationMethod = AllocationMethod.SIGNAL_STRENGTH
    
    # Performance tracking
    performance_lookback_days: int = 30  # Performance attribution period
    rebalance_frequency_minutes: int = 60  # Portfolio rebalance frequency
    
    # Risk management
    correlation_limit: float = 0.8  # Max correlation between positions
    max_drawdown_pct: float = 15.0  # Max portfolio drawdown
    
    # Token management
    max_concurrent_positions: int = 8  # Max number of open positions
    min_liquidity_usdc: float = 1000.0  # Min daily volume for trading
    
    # Portfolio coordination
    rebalance_threshold_pct: float = 5.0  # Rebalance threshold percentage
    performance_window_hours: int = 168  # Performance window in hours (1 week)
    attribution_update_frequency: int = 24  # Attribution update frequency in hours (daily)

@dataclass
class AssetAllocation:
    """Asset allocation data"""
    symbol: str
    token_id: int
    current_exposure_pct: float
    target_exposure_pct: float
    position_value_usdc: float
    signal: Optional[TradingSignal]
    last_updated: datetime
    
    # Performance attribution
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0

@dataclass
class PortfolioSignal:
    """Portfolio-level trading signal with allocation recommendations"""
    timestamp: datetime
    total_cash_available: float
    portfolio_value: float
    current_exposure_pct: float
    
    # Signal recommendations
    buy_signals: List[TradingSignal]
    sell_signals: List[TradingSignal]
    
    # Allocation recommendations
    asset_allocations: Dict[str, AssetAllocation]
    cash_allocation_pct: float
    
    # Risk metrics
    portfolio_risk_score: float
    correlation_risk: float
    concentration_risk: float
    
    # Execution priority ('HIGH', 'MEDIUM', 'LOW')
    execution_priority: str = 'MEDIUM'

class PortfolioCoordinator:
    """
    Multi-Asset Portfolio Coordination Engine
    
    Coordinates trading signals across multiple assets with sophisticated risk management
    and position allocation logic.
    """
    
    def __init__(self, config: Optional[PortfolioConfig] = None, db_manager: Optional['ProductionDBManager'] = None):
        """Initialize portfolio coordinator"""
        self.config = config or self._load_config_from_env()
        self.db_manager = db_manager  # Use provided db_manager if available
        self.redis_client = None
        self.strategy_engine: Optional[StrategyEngine] = None
        self.position_manager: Optional['PositionManager'] = None
        
        # Risk management
        self.risk_limits = self._create_risk_limits()
        
        # Performance tracking
        self.portfolio_history: deque[PortfolioSignal] = deque(maxlen=1000)
        self.signal_cache_timeout = timedelta(minutes=self.config.signal_timeout_minutes)
        self.last_signals: Dict[str, TradingSignal] = {}
        
        # Asset tracking
        self.tracked_symbols: Set[str] = set()
        
        # Daily P&L tracking
        self.daily_pnl_by_asset: Dict[str, float] = {}
        self._last_pnl_reset_date: Optional[date] = None
        
        # Performance attribution by asset
        self.performance_attribution: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"Portfolio Coordinator initialized with config: {self.config}")
        if self.db_manager:
            logger.info("Using provided database manager for thread safety")

    def _load_config_from_env(self) -> PortfolioConfig:
        """Load portfolio configuration from environment variables"""
        # Parse tracked tokens from environment
        tracked_tokens_str = os.getenv('TRACKED_TOKENS', '')
        self.tracked_tokens_addresses = [addr.strip() for addr in tracked_tokens_str.split(',') if addr.strip()]
        
        # Get global config for confidence threshold
        from ..config.config import config
        
        return PortfolioConfig(
            # Portfolio risk limits from position manager env vars
            max_portfolio_exposure_pct=float(os.getenv('PORTFOLIO_MAX_EXPOSURE_PCT', 80.0)),
            max_single_asset_exposure_pct=float(os.getenv('TOKEN_MAX_EXPOSURE_PCT', 20.0)),
            min_cash_reserve_pct=100.0 - float(os.getenv('PORTFOLIO_MAX_EXPOSURE_PCT', 80.0)),
            
            # Position sizing based on signal strength
            base_position_size_pct=float(os.getenv('BASE_POSITION_SIZE_PCT', 2.0)),
            strong_signal_multiplier=float(os.getenv('STRONG_SIGNAL_MULTIPLIER', 1.5)),
            moderate_signal_multiplier=float(os.getenv('MODERATE_SIGNAL_MULTIPLIER', 1.2)),
            weak_signal_multiplier=float(os.getenv('WEAK_SIGNAL_MULTIPLIER', 0.8)),
            
            # Portfolio coordination - FIXED: Use signal_strength as default (matches enum)
            allocation_method=AllocationMethod(os.getenv('PORTFOLIO_ALLOCATION_METHOD', 'signal_strength')),
            rebalance_threshold_pct=float(os.getenv('PORTFOLIO_REBALANCE_THRESHOLD_PCT', 5.0)),
            max_concurrent_positions=int(os.getenv('MAX_CONCURRENT_POSITIONS', 8)),
            correlation_limit=float(os.getenv('PORTFOLIO_CORRELATION_LIMIT', 0.7)),
            
            # Signal filtering - Use global config for confidence threshold
            min_signal_confidence=float(os.getenv('MIN_PREDICTION_CONFIDENCE') or config.MIN_PREDICTION_CONFIDENCE),
            min_signal_strength_for_entry=os.getenv('MIN_SIGNAL_STRENGTH_FOR_ENTRY', 'weak'),
            
            # Performance tracking
            performance_window_hours=int(os.getenv('PERFORMANCE_WINDOW_HOURS', 168)),  # 1 week
            attribution_update_frequency=int(os.getenv('ATTRIBUTION_UPDATE_FREQUENCY', 24)),  # Daily
        )

    def _create_risk_limits(self) -> RiskLimits:
        """Create risk limits for position manager integration"""
        return RiskLimits(
            max_position_size_usdc=50000.0,  # High limit since we use percentage-based sizing
            max_portfolio_exposure_pct=self.config.max_portfolio_exposure_pct,
            max_single_token_exposure_pct=self.config.max_single_asset_exposure_pct,
            max_drawdown_pct=self.config.max_drawdown_pct,
            max_daily_loss_usdc=float(os.getenv('MAX_DAILY_LOSS_USDC', 2000.0)),
            min_position_size_usdc=self.config.min_position_size_usdc
        )

    async def initialize(self):
        """Initialize the portfolio coordinator"""
        try:
            # Initialize database manager if not provided in constructor
            if not self.db_manager:
                # Check if we're in a thread
                try:
                    import asyncio
                    # Try to get the current running loop
                    current_loop = asyncio.get_running_loop()
                    
                    # If we're in a thread with its own event loop, create a new DB manager
                    # to avoid event loop conflicts
                    from ..database.production_db import ProductionDBManager
                    self.db_manager = ProductionDBManager()
                    await self.db_manager.initialize()
                    logger.info("Database manager initialized (thread-local)")
                except RuntimeError:
                    # No running loop, use the default get_db_manager
                    self.db_manager = await get_db_manager()
                    logger.info("Database manager initialized (main)")
            else:
                logger.info("Using provided database manager from scheduler")
            
            # Initialize strategy engine with our thread-local db_manager
            from ..inference.strategy_engine import get_strategy_engine
            self.strategy_engine = get_strategy_engine(db_manager=self.db_manager)
            
            # Initialize model registry
            self.model_registry = get_model_registry()
            
            # Load tracked symbols from database
            await self._load_tracked_symbols()
            
            # Initialize position manager with our risk limits and thread-local db_manager
            self.position_manager = PositionManager(
                db_manager=self.db_manager,  # Pass the thread-local db_manager
                risk_limits=self.risk_limits
            )
            await self.position_manager.initialize()
            
            # Recover portfolio state from database
            await self._recover_portfolio_state()
            
            # Recover daily P&L tracking
            await self._recover_daily_pnl_tracking()
            
            # Recover performance attribution
            await self._recover_performance_attribution()
            
            # Recover portfolio history
            await self._recover_portfolio_history()
            
            self.initialized = True
            logger.info(f"Portfolio coordinator initialized with {len(self.tracked_symbols)} tracked symbols")
            
        except Exception as e:
            logger.error(f"Portfolio coordinator initialization failed: {e}")
            raise

    async def _recover_portfolio_state(self):
        """Recover portfolio state from database after restart"""
        try:
            # 1. Recover daily P&L tracking
            await self._recover_daily_pnl_tracking()
            
            # 2. Recover performance attribution
            await self._recover_performance_attribution()
            
            # 3. Recover recent portfolio history (last 10 cycles)
            await self._recover_portfolio_history()
            
            logger.info("✅ Portfolio state recovered from database")
            
        except Exception as e:
            logger.warning(f"⚠️ Portfolio state recovery failed (starting fresh): {e}")
            # Continue with fresh state - not critical for operation
    
    async def _recover_daily_pnl_tracking(self):
        """Recover daily P&L from health check records"""
        try:
            # Query latest daily P&L data from health checks
            query = """
                SELECT details
                FROM system_health 
                WHERE component = 'daily_pnl_tracking'
                  AND status = 'healthy'
                  AND check_time >= CURRENT_DATE
                ORDER BY check_time DESC
                LIMIT 1
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query)
                
            if row and row['details']:
                pnl_data = row['details']
                self.daily_pnl_by_asset = pnl_data.get('asset_pnl', {})
                logger.info(f"📊 Recovered daily P&L for {len(self.daily_pnl_by_asset)} assets")
                
        except Exception as e:
            logger.warning(f"Failed to recover daily P&L: {e}")
            self.daily_pnl_by_asset = {}
    
    async def _recover_performance_attribution(self):
        """Recover performance attribution from health check records"""
        try:
            # Query recent performance attribution data
            query = """
                SELECT details
                FROM system_health 
                WHERE component = 'portfolio_performance_attribution'
                  AND status = 'healthy'
                  AND check_time >= NOW() - INTERVAL '24 hours'
                ORDER BY check_time DESC
                LIMIT 50
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                rows = await conn.fetch(query)
            
            # Rebuild performance attribution from recent data
            for row in rows:
                if row['details']:
                    details = row['details']
                    
                    # Handle both string and dict formats
                    if isinstance(details, str):
                        try:
                            import json
                            details = json.loads(details)
                        except json.JSONDecodeError:
                            continue
                    
                    # Now details should be a dict
                    if isinstance(details, dict):
                        symbol = details.get('symbol')
                        if symbol:
                            self.performance_attribution[symbol] = {
                                'total_signals': details.get('total_signals', 0),
                                'successful_signals': details.get('successful_signals', 0),
                                'total_pnl': details.get('total_pnl', 0.0),
                                'win_rate': details.get('signal_generation_rate', 0.0),
                                'avg_return': details.get('avg_return', 0.0),
                                'sharpe_ratio': details.get('sharpe_ratio', 0.0),
                                'max_drawdown': 0.0,
                                'last_updated': datetime.now()
                            }
            
            logger.info(f"📈 Recovered performance attribution for {len(self.performance_attribution)} assets")
            
        except Exception as e:
            logger.warning(f"Failed to recover performance attribution: {e}")
            self.performance_attribution = {}
    
    async def _recover_portfolio_history(self):
        """Recover recent portfolio history from portfolio_cycles table"""
        try:
            # Get recent portfolio cycles to rebuild history
            recent_cycles = await self.db_manager.get_recent_portfolio_cycles(limit=10)
            
            for cycle in recent_cycles:
                # Create a simplified PortfolioSignal from cycle data
                portfolio_signal = PortfolioSignal(
                    timestamp=cycle['cycle_timestamp'],
                    total_cash_available=cycle.get('available_cash_usdc', 0.0),
                    portfolio_value=cycle.get('total_portfolio_value_usdc', 0.0),
                    current_exposure_pct=cycle.get('max_position_size_pct', 0.0),
                    buy_signals=[],  # Can't recover exact signals, but that's OK
                    sell_signals=[],
                    asset_allocations={},  # Can't recover exact allocations
                    cash_allocation_pct=100.0,
                    portfolio_risk_score=cycle.get('portfolio_risk_score', 0.0),
                    correlation_risk=cycle.get('correlation_risk', 0.0),
                    concentration_risk=0.0,
                    execution_priority='MEDIUM'
                )
                self.portfolio_history.append(portfolio_signal)
            
            # Sort by timestamp (convert to list, sort, then recreate deque)
            if self.portfolio_history:
                sorted_history = sorted(self.portfolio_history, key=lambda x: x.timestamp)
                self.portfolio_history.clear()
                self.portfolio_history.extend(sorted_history)
            
            logger.info(f"📊 Recovered {len(self.portfolio_history)} recent portfolio cycles")
            
        except Exception as e:
            logger.warning(f"Failed to recover portfolio history: {e}")
            self.portfolio_history = []

    async def _load_tracked_symbols(self):
        """Load tracked symbols from database using token addresses"""
        try:
            self.tracked_symbols = set()
            
            # Define tokens to exclude from inference/trading
            # NOTE: We still fetch OHLCV data for these tokens since they're needed for 
            # intermarket correlation features (BTC/ETH correlations, etc.)
            excluded_symbols = {'USDC', 'SOL', 'WBTC', 'WETH'}
            
            # Get all active tokens from database
            active_tokens = await self.db_manager.get_active_tokens()
            
            # Filter to only tracked tokens AND exclude specified tokens
            for token in active_tokens:
                if token['address'] in self.tracked_tokens_addresses:
                    # Skip excluded tokens
                    if token['symbol'] in excluded_symbols:
                        logger.info(f"🚫 Excluding {token['symbol']} from inference (infrastructure token)")
                        continue
                    
                    self.tracked_symbols.add(token['symbol'])
            
            # Fallback: if no tracked symbols found, use available models (with exclusions)
            if not self.tracked_symbols:
                logger.warning("No tracked symbols found in database, using available models")
                models = self.model_registry.list_models()
                for model in models:
                    if model.symbol not in excluded_symbols:
                        self.tracked_symbols.add(model.symbol)
            
            logger.info(f"✅ Loaded {len(self.tracked_symbols)} tracked symbols (excluded: {excluded_symbols})")
            logger.info(f"📋 Trading symbols: {sorted(list(self.tracked_symbols))}")
            
        except Exception as e:
            logger.error(f"Failed to load tracked symbols: {e}")
            # Fallback to basic symbols (excluding infrastructure tokens)
            self.tracked_symbols = {'BONK', 'JUP', 'Fartcoin'}

    async def generate_portfolio_signals(self, simulation_time: Optional[datetime] = None, override_portfolio_state: Optional[Dict[str, Any]] = None) -> Optional[PortfolioSignal]:
        """
        Generate coordinated portfolio signals across all tracked assets
        
        Returns:
            PortfolioSignal with allocation recommendations or None if failed
        """
        try:
            start_time = datetime.now()
            
            # 1. Get current portfolio state (use override for backtest mode)
            if override_portfolio_state:
                portfolio_state = override_portfolio_state
                logger.debug(f"Using override portfolio state: ${portfolio_state['portfolio_value']:,.2f} portfolio value")
            else:
                portfolio_state = await self._get_portfolio_state()
                if not portfolio_state:
                    logger.error("Failed to get portfolio state")
                    return None
            
            # 2. Generate individual signals for each tracked symbol
            individual_signals = await self._generate_individual_signals(simulation_time)
            
            # 3. Filter and validate signals
            valid_signals = self._filter_signals(individual_signals)
            
            # 4. Perform portfolio-level risk assessment
            risk_assessment = await self._assess_portfolio_risk(valid_signals, portfolio_state)
            
            # 5. Generate asset allocation recommendations
            asset_allocations = await self._calculate_asset_allocations(
                valid_signals, portfolio_state, risk_assessment
            )
            
            # Filter sell signals to only include tokens we actually hold
            open_positions = portfolio_state.get('open_positions', {})
            filtered_sell_signals = []
            for signal in valid_signals:
                if signal.signal_type == SignalType.SELL:
                    if signal.symbol in open_positions:
                        filtered_sell_signals.append(signal)
                        logger.debug(f"✅ Including SELL signal for {signal.symbol} - we hold this position")
                    else:
                        logger.debug(f"🚫 Filtering out SELL signal for {signal.symbol} - no position held")
            
            # 6. Create portfolio signal
            portfolio_signal = PortfolioSignal(
                timestamp=datetime.now(),
                total_cash_available=portfolio_state['cash_balance'],
                portfolio_value=portfolio_state['portfolio_value'],
                current_exposure_pct=portfolio_state['exposure_percentage'],
                buy_signals=[s for s in valid_signals if s.signal_type == SignalType.BUY],
                sell_signals=filtered_sell_signals,  # Only sell signals for tokens we hold
                asset_allocations=asset_allocations,
                cash_allocation_pct=self._calculate_target_cash_allocation(asset_allocations),
                portfolio_risk_score=risk_assessment['portfolio_risk'],
                correlation_risk=risk_assessment['correlation_risk'],
                concentration_risk=risk_assessment['concentration_risk'],
                execution_priority=self._calculate_execution_priority(valid_signals, risk_assessment)
            )
            
            # 7. Cache and track performance
            self._update_performance_tracking(portfolio_signal)
            
            # 🆕 8. Feed ALL signals to adaptive strategy engine for performance tracking
            await self._update_adaptive_strategy_with_signals(individual_signals)
            
            # 9. Update signal performance from verified trades (simple database query)
            await self._update_signal_performance_from_verified_trades()
            
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"Generated portfolio signals for {len(self.tracked_symbols)} assets in {processing_time:.1f}ms")
            logger.info(f"Signals: {len(portfolio_signal.buy_signals)} BUY, {len(portfolio_signal.sell_signals)} SELL, "
                       f"exposure: {portfolio_signal.current_exposure_pct:.1f}%")
            
            return portfolio_signal
            
        except Exception as e:
            logger.error(f"Portfolio signal generation failed: {e}")
            return None

    async def _get_portfolio_state(self) -> Optional[Dict[str, Any]]:
        """Get current portfolio state from position manager and vault"""
        try:
            # Get total portfolio value from position manager (which integrates with vault)
            portfolio_value = self.position_manager._get_portfolio_value()
            
            # Get current positions from position manager
            open_positions = self.position_manager.get_active_positions()
            
            # Calculate position metrics by getting current prices
            total_position_value = 0.0
            open_positions_by_symbol = {}
            
            for pos_id, position in open_positions.items():
                # Get current price for the position
                current_price = await self.db_manager.get_latest_price(position.token_id)
                if current_price:
                    position_value = position.entry_quantity * current_price
                    total_position_value += position_value
                else:
                    # If no current price, use entry value as fallback
                    position_value = position.entry_value_usdc
                    total_position_value += position_value
                
                # Get token info to map by symbol
                token_info = self.db_manager.get_token_by_id(position.token_id)
                if token_info:
                    open_positions_by_symbol[token_info.symbol] = {
                        'position': position,
                        'current_value': position_value,
                        'current_price': current_price or position.entry_price
                    }
            
            position_count = len(open_positions)
            
            # Calculate exposure
            cash_balance = portfolio_value - total_position_value
            exposure_pct = (total_position_value / portfolio_value * 100) if portfolio_value > 0 else 0
            
            # Get P&L summary
            pnl_summary = await self.position_manager.get_portfolio_pnl()
            
            return {
                'portfolio_value': portfolio_value,
                'cash_balance': cash_balance,
                'available_buying_power': max(0, cash_balance * 0.95),  # Keep 5% reserve
                'total_position_value': total_position_value,
                'position_count': position_count,
                'exposure_percentage': exposure_pct,
                'open_positions': open_positions_by_symbol,  # Now mapped by symbol
                'daily_pnl': pnl_summary.get('daily_realized_pnl', 0),
                'total_pnl': pnl_summary.get('total_realized_pnl', 0),
                'unrealized_pnl': pnl_summary.get('total_unrealized_pnl', 0),
                'timestamp': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Failed to get portfolio state: {e}")
            return None

    async def _generate_individual_signals(self, simulation_time: Optional[datetime] = None) -> List[TradingSignal]:
        """Generate trading signals for all tracked symbols SEQUENTIALLY to avoid DataProcessor race conditions"""
        signals = []
        
        logger.debug(f"Generating signals sequentially for {len(self.tracked_symbols)} symbols")
        
        # Generate signals one by one (no race conditions, simple and reliable)
        for symbol in self.tracked_symbols:
            try:
                signal = await self.strategy_engine.generate_signal(symbol, simulation_time=simulation_time)
                
                if signal is not None:
                    signals.append(signal)
                    self.last_signals[symbol] = signal
                    logger.debug(f"Generated {signal.signal_type.value} signal for {symbol}: {signal.confidence:.3f} confidence")
                else:
                    logger.debug(f"No signal generated for {symbol}")
                    
            except Exception as e:
                logger.warning(f"Signal generation failed for {symbol}: {e}")
                continue
        
        # Sort signals by strength (confidence * predicted_change magnitude) - BEST SIGNALS FIRST
        actionable_signals = [s for s in signals if s.signal_type != SignalType.HOLD]
        actionable_signals.sort(
            key=lambda s: s.confidence * abs(s.predicted_change_pct), 
            reverse=True
        )
        
        logger.debug(f"Generated {len(signals)} total signals ({len(actionable_signals)} actionable) from {len(self.tracked_symbols)} symbols")
        if actionable_signals:
            logger.info(f"Top signals: {[(s.symbol, s.signal_type.value, f'{s.confidence:.2f}', f'{s.predicted_change_pct:.1f}%') for s in actionable_signals[:3]]}")
        
        return signals

    def _filter_signals(self, signals: List[TradingSignal]) -> List[TradingSignal]:
        """Filter signals based on confidence and validity"""
        valid_signals = []
        
        for signal in signals:
            # Check confidence threshold
            if signal.confidence < self.config.min_signal_confidence:
                logger.debug(f"Signal filtered for {signal.symbol}: confidence {signal.confidence:.2f} < {self.config.min_signal_confidence:.2f}")
                continue
            
            # Check signal age
            signal_age = datetime.now() - signal.timestamp
            if signal_age > self.signal_cache_timeout:
                logger.debug(f"Signal filtered for {signal.symbol}: age {signal_age.total_seconds():.0f}s > {self.signal_cache_timeout.total_seconds():.0f}s")
                continue
            
            # Signal is valid
            valid_signals.append(signal)
        
        logger.debug(f"Filtered to {len(valid_signals)} valid signals from {len(signals)} total")
        return valid_signals

    async def _assess_portfolio_risk(self, signals: List[TradingSignal], 
                                   portfolio_state: Dict[str, Any]) -> Dict[str, float]:
        """Assess portfolio-level risk metrics"""
        try:
            # Calculate concentration risk
            concentration_risk = self._calculate_concentration_risk(signals, portfolio_state)
            
            # Calculate correlation risk (simplified - would need price data for full calculation)
            correlation_risk = self._estimate_correlation_risk(signals)
            
            # Calculate portfolio risk score
            exposure_risk = portfolio_state['exposure_percentage'] / self.config.max_portfolio_exposure_pct
            signal_count_risk = len(signals) / self.config.max_concurrent_positions
            
            portfolio_risk = np.mean([concentration_risk, correlation_risk, exposure_risk, signal_count_risk])
            
            return {
                'portfolio_risk': portfolio_risk,
                'concentration_risk': concentration_risk,
                'correlation_risk': correlation_risk,
                'exposure_risk': exposure_risk,
                'signal_count_risk': signal_count_risk
            }
            
        except Exception as e:
            logger.error(f"Risk assessment failed: {e}")
            return {
                'portfolio_risk': 0.5,
                'concentration_risk': 0.5,
                'correlation_risk': 0.5,
                'exposure_risk': 0.5,
                'signal_count_risk': 0.5
            }

    def _calculate_concentration_risk(self, signals: List[TradingSignal], 
                                    portfolio_state: Dict[str, Any]) -> float:
        """Calculate portfolio concentration risk"""
        if not signals:
            return 0.0
        
        # Calculate proposed position sizes
        position_sizes = []
        for signal in signals:
            if signal.signal_type in [SignalType.BUY]:
                # Calculate position size based on signal strength and confidence
                base_size = self.config.base_position_size_pct / 100
                confidence_multiplier = signal.confidence
                strength_multiplier = {'weak': self.config.weak_signal_multiplier, 'moderate': self.config.moderate_signal_multiplier, 'strong': self.config.strong_signal_multiplier}.get(
                    signal.strength.value, 1.0
                )
                
                position_size = base_size * confidence_multiplier * strength_multiplier
                position_size = min(position_size, self.config.max_single_asset_exposure_pct / 100)
                position_sizes.append(position_size)
        
        if not position_sizes:
            return 0.0
        
        # Calculate Herfindahl index for concentration
        total_allocation = sum(position_sizes)
        if total_allocation == 0:
            return 0.0
        
        normalized_sizes = [size / total_allocation for size in position_sizes]
        herfindahl_index = sum(size ** 2 for size in normalized_sizes)
        
        # Convert to risk score (higher concentration = higher risk)
        max_herfindahl = 1.0  # Perfect concentration
        min_herfindahl = 1.0 / len(position_sizes)  # Perfect diversification
        
        if max_herfindahl == min_herfindahl:
            return 0.0
        
        concentration_risk = (herfindahl_index - min_herfindahl) / (max_herfindahl - min_herfindahl)
        return concentration_risk

    def _estimate_correlation_risk(self, signals: List[TradingSignal]) -> float:
        """Estimate correlation risk based on signal patterns"""
        if len(signals) < 2:
            return 0.0
        
        # Simple heuristic: if many signals have same direction and similar confidence,
        # assume higher correlation risk
        buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
        sell_signals = [s for s in signals if s.signal_type == SignalType.SELL]
        
        total_signals = len(signals)
        buy_ratio = len(buy_signals) / total_signals
        sell_ratio = len(sell_signals) / total_signals
        
        # High correlation risk if most signals are in same direction
        directional_concentration = max(buy_ratio, sell_ratio)
        
        # Additional risk if confidences are very similar (herd behavior)
        confidences = [s.confidence for s in signals]
        confidence_std = np.std(confidences) if len(confidences) > 1 else 0.0
        confidence_similarity = 1.0 - min(confidence_std * 4, 1.0)  # Scale std to 0-1
        
        correlation_risk = (directional_concentration * 0.7 + confidence_similarity * 0.3)
        return correlation_risk

    async def _calculate_asset_allocations(self, signals: List[TradingSignal], 
                                         portfolio_state: Dict[str, Any],
                                         risk_assessment: Dict[str, float]) -> Dict[str, AssetAllocation]:
        """Calculate asset allocations based on signal strength and portfolio percentage"""
        allocations = {}
        
        try:
            # Get portfolio metrics
            portfolio_value = portfolio_state['portfolio_value']
            available_cash = portfolio_state['available_buying_power']
            
            # Get current open positions to avoid duplicates
            open_positions = portfolio_state.get('open_positions', {})
            position_count = portfolio_state.get('position_count', len(open_positions))
            
            # Count pending sell signals to calculate expected freed slots
            sell_signals = [s for s in signals if s.signal_type == SignalType.SELL and s.symbol in open_positions]
            expected_freed_slots = len(sell_signals)
            
            # 🚫 ENFORCE MAX CONCURRENT POSITIONS LIMIT (considering pending sells)
            effective_position_count = position_count - expected_freed_slots
            if effective_position_count >= self.config.max_concurrent_positions:
                logger.warning(f"⚠️ MAX CONCURRENT POSITIONS REACHED: {position_count}/{self.config.max_concurrent_positions}")
                logger.info(f"   Currently holding: {list(open_positions.keys())}")
                logger.info(f"   Blocking all new buy signals until positions are closed")
                return allocations  # Return empty allocations - no new positions allowed
            
            # Calculate how many new positions we can open (including expected freed slots)
            available_position_slots = self.config.max_concurrent_positions - effective_position_count
            logger.info(f"📊 Position slots: {position_count}/{self.config.max_concurrent_positions} used")
            if expected_freed_slots > 0:
                logger.info(f"   📤 Expecting to free {expected_freed_slots} slots from sell signals")
            logger.info(f"   📥 {available_position_slots} slots available for new positions")
            
            # Filter to actionable signals
            buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
            
            if not buy_signals:
                logger.debug("No buy signals to allocate")
                return allocations
            
            logger.debug(f"Calculating allocations for {len(buy_signals)} buy signals")
            logger.debug(f"Portfolio value: ${portfolio_value:,.2f}, Available cash: ${available_cash:,.2f}")
            logger.debug(f"Currently holding {len(open_positions)} positions: {list(open_positions.keys())}")
            
            # Sort buy signals by confidence to prioritize the best ones
            buy_signals_sorted = sorted(buy_signals, key=lambda s: s.confidence, reverse=True)
            
            # Limit buy signals to available position slots
            if len(buy_signals_sorted) > available_position_slots:
                logger.info(f"🎯 Limiting {len(buy_signals_sorted)} buy signals to {available_position_slots} available slots")
                logger.info(f"   Prioritizing by confidence: {[(s.symbol, f'{s.confidence:.2f}') for s in buy_signals_sorted[:available_position_slots]]}")
                buy_signals_sorted = buy_signals_sorted[:available_position_slots]
            
            # Calculate position sizes based on signal strength
            allocated_count = 0
            for signal in buy_signals_sorted:
                try:
                    # 🆕 CHECK IF WE ALREADY HOLD THIS POSITION
                    if signal.symbol in open_positions:
                        existing_position = open_positions[signal.symbol]
                        logger.info(f"🚫 Already holding {signal.symbol}: {existing_position['size']:.6f} tokens @ ${existing_position['entry_price']:.6f} = ${existing_position['current_value']:.2f}")
                        logger.info(f"   Skipping buy signal to prevent duplicate position")
                        continue
                    
                    # Get token info
                    token_info = await self.db_manager.get_token_by_symbol(signal.symbol)
                    if not token_info:
                        logger.warning(f"Token info not found for {signal.symbol}")
                        continue
                    
                    # Calculate position size based on signal strength
                    # Base position size is 5% of portfolio
                    base_position_pct = self.config.base_position_size_pct
                    
                    if signal.strength == SignalStrength.WEAK:
                        position_pct = base_position_pct * self.config.weak_signal_multiplier
                    elif signal.strength == SignalStrength.MODERATE:
                        position_pct = base_position_pct * self.config.moderate_signal_multiplier
                    elif signal.strength == SignalStrength.STRONG:
                        position_pct = base_position_pct * self.config.strong_signal_multiplier
                    else:
                        position_pct = base_position_pct  # Default to base size
                    
                    # Calculate target position value
                    target_position_value = portfolio_value * (position_pct / 100.0)
                    
                    # Apply minimum position size constraint
                    target_position_value = max(target_position_value, self.config.min_position_size_usdc)
                    
                    # Check if we have enough available cash
                    if target_position_value > available_cash:
                        logger.info(f"Insufficient cash for {signal.symbol}: need ${target_position_value:,.2f}, have ${available_cash:,.2f} - skipping trade")
                        continue
                    
                    # Create allocation
                    allocation = AssetAllocation(
                        symbol=signal.symbol,
                        token_id=token_info['token_id'],
                        current_exposure_pct=0.0,  # Would get from position manager
                        target_exposure_pct=position_pct,
                        position_value_usdc=target_position_value,
                        signal=signal,
                        last_updated=datetime.now()
                    )
                    
                    allocations[signal.symbol] = allocation
                    
                    # Reduce available cash for next allocation
                    available_cash -= target_position_value
                    
                    # Track successful allocation
                    allocated_count += 1
                    
                    logger.debug(f"Allocated {signal.symbol}: {signal.strength.value} signal = {position_pct:.2f}% = ${target_position_value:,.2f}")
                    
                    # Check if we've reached the position limit
                    if position_count + allocated_count >= self.config.max_concurrent_positions:
                        logger.info(f"🛑 Reached max concurrent positions limit ({self.config.max_concurrent_positions}) - stopping allocations")
                        break
                    
                except Exception as e:
                    logger.error(f"Failed to calculate allocation for {signal.symbol}: {e}")
                    continue
            
            logger.info(f"Portfolio allocations calculated: {len(allocations)} positions, total value: ${sum(a.position_value_usdc for a in allocations.values()):,.2f}")
            return allocations
            
        except Exception as e:
            logger.error(f"Asset allocation calculation failed: {e}")
            return {}

    def _calculate_allocation_weights(self, signals: List[TradingSignal], 
                                    risk_assessment: Dict[str, float]) -> List[float]:
        """Calculate allocation weights - simplified since we use percentage-based sizing"""
        if not signals:
            return []
        
        # With percentage-based sizing, we don't need complex weighting
        # Signal strength determines position size directly in _calculate_asset_allocations
        return [1.0 / len(signals)] * len(signals)  # Equal weights for any remaining usage

    def _calculate_target_cash_allocation(self, asset_allocations: Dict[str, AssetAllocation]) -> float:
        """Calculate target cash allocation percentage"""
        total_target_exposure = sum(alloc.target_exposure_pct for alloc in asset_allocations.values())
        target_cash_pct = 100.0 - total_target_exposure
        
        # Ensure minimum cash reserve
        target_cash_pct = max(target_cash_pct, self.config.min_cash_reserve_pct)
        
        return target_cash_pct

    def _calculate_execution_priority(self, signals: List[TradingSignal], 
                                    risk_assessment: Dict[str, float]) -> str:
        """Calculate execution priority ('HIGH', 'MEDIUM', 'LOW')"""
        # High priority for high-confidence signals with low portfolio risk
        avg_confidence = np.mean([s.confidence for s in signals]) if signals else 0.5
        portfolio_risk = risk_assessment.get('portfolio_risk', 0.5)
        
        # Priority score: higher confidence and lower risk = higher priority (lower number)
        priority_score = (1.0 - avg_confidence) + portfolio_risk
        
        # Convert to categorical priority
        if priority_score <= 0.6:
            return 'HIGH'
        elif priority_score <= 1.2:
            return 'MEDIUM'
        else:
            return 'LOW'

    def _update_performance_tracking(self, portfolio_signal: PortfolioSignal):
        """Update performance tracking metrics"""
        try:
            # Add the new signal to history
            self.portfolio_history.append(portfolio_signal)
            
            # Keep only recent history
            max_history = 1000
            if len(self.portfolio_history) > max_history:
                self.portfolio_history = self.portfolio_history[-max_history:]
            
            # Update daily PnL tracking with actual position data
            self._update_daily_pnl_tracking(portfolio_signal)
            
            # Update performance attribution per asset
            self._update_asset_performance_attribution(portfolio_signal)
            
        except Exception as e:
            logger.error(f"Performance tracking update failed: {e}")

    def _update_daily_pnl_tracking(self, portfolio_signal: PortfolioSignal):
        """Update daily P&L tracking for portfolio and individual assets"""
        try:
            current_date = datetime.now().date()
            
            # Calculate portfolio-level P&L
            if len(self.portfolio_history) >= 2:
                previous_signal = self.portfolio_history[-2]
                # Convert to float to handle potential Decimal types from database
                current_value = float(portfolio_signal.portfolio_value)
                previous_value = float(previous_signal.portfolio_value)
                portfolio_pnl_change = current_value - previous_value
                portfolio_pnl_pct = (portfolio_pnl_change / previous_value) * 100 if previous_value > 0 else 0.0
                
                # Update daily P&L by asset
                for symbol, allocation in portfolio_signal.asset_allocations.items():
                    if symbol not in self.daily_pnl_by_asset:
                        self.daily_pnl_by_asset[symbol] = 0.0
                    
                    # Calculate asset contribution to portfolio P&L
                    asset_weight = float(allocation.position_value_usdc) / current_value if current_value > 0 else 0.0
                    asset_pnl_contribution = portfolio_pnl_change * asset_weight
                    
                    self.daily_pnl_by_asset[symbol] += asset_pnl_contribution
                
                logger.debug(f"📊 Portfolio P&L: ${portfolio_pnl_change:.2f} ({portfolio_pnl_pct:.2f}%)")
            
            # Reset daily P&L at midnight
            if not hasattr(self, '_last_pnl_reset_date') or self._last_pnl_reset_date != current_date:
                # Store yesterday's data before reset
                if hasattr(self, '_last_pnl_reset_date') and self.daily_pnl_by_asset:
                    # Schedule async storage (don't await in sync context)
                    import asyncio
                    asyncio.create_task(self._store_daily_pnl_data())
                
                self.daily_pnl_by_asset.clear()
                self._last_pnl_reset_date = current_date
                logger.debug("🔄 Daily P&L tracking reset")
                
        except Exception as e:
            logger.error(f"Daily P&L tracking update failed: {e}")

    def _update_asset_performance_attribution(self, portfolio_signal: PortfolioSignal):
        """Update performance attribution metrics for individual assets"""
        try:
            for symbol, allocation in portfolio_signal.asset_allocations.items():
                if symbol not in self.performance_attribution:
                    self.performance_attribution[symbol] = {
                        'total_signals': 0,
                        'successful_signals': 0,
                        'total_pnl': 0.0,
                        'win_rate': 0.0,
                        'avg_return': 0.0,
                        'sharpe_ratio': 0.0,
                        'max_drawdown': 0.0,
                        'last_updated': datetime.now()
                    }
                
                perf = self.performance_attribution[symbol]
                
                # Update signal tracking
                if allocation.signal:
                    perf['total_signals'] += 1
                    
                    # Note: Actual trade success tracking is handled by trade_verifier.py
                    # This tracks signal generation success only
                    signal_generated_successfully = allocation.signal.confidence > self.config.min_signal_confidence
                    if signal_generated_successfully:
                        perf['successful_signals'] += 1
                    
                    # Update signal generation rate (not trade success rate)
                    perf['win_rate'] = perf['successful_signals'] / perf['total_signals'] if perf['total_signals'] > 0 else 0.0
                
                # Update P&L tracking
                perf['total_pnl'] += allocation.daily_pnl
                
                # Update allocation object with performance metrics
                allocation.total_pnl = perf['total_pnl']
                allocation.win_rate = perf['win_rate']
                
                # Calculate simple Sharpe ratio (returns / volatility)
                if len(self.portfolio_history) >= 10:
                    recent_returns = []
                    for i in range(1, min(31, len(self.portfolio_history))):  # Last 30 periods
                        prev_signal = self.portfolio_history[-(i+1)]
                        curr_signal = self.portfolio_history[-i]
                        
                        if symbol in prev_signal.asset_allocations and symbol in curr_signal.asset_allocations:
                            prev_value = prev_signal.asset_allocations[symbol].position_value_usdc
                            curr_value = curr_signal.asset_allocations[symbol].position_value_usdc
                            
                            if prev_value > 0:
                                period_return = (curr_value - prev_value) / prev_value
                                recent_returns.append(period_return)
                    
                    if len(recent_returns) >= 5:
                        import statistics
                        avg_return = statistics.mean(recent_returns)
                        return_volatility = statistics.stdev(recent_returns) if len(recent_returns) > 1 else 0.0
                        
                        perf['avg_return'] = avg_return
                        perf['sharpe_ratio'] = avg_return / return_volatility if return_volatility > 0 else 0.0
                        allocation.sharpe_ratio = perf['sharpe_ratio']
                
                perf['last_updated'] = datetime.now()
                
                # Store performance attribution in database (schedule async task)
                import asyncio
                asyncio.create_task(self._store_performance_attribution(symbol, perf, allocation))
                
        except Exception as e:
            logger.error(f"Asset performance attribution update failed: {e}")

    async def _store_performance_attribution(self, symbol: str, perf: Dict[str, Any], allocation: AssetAllocation):
        """Store performance attribution data in database"""
        try:
            if not self.db_manager:
                return
            
            # Store in portfolio_performance table (if exists) or create custom table
            performance_data = {
                'symbol': symbol,
                'timestamp': datetime.now(),
                'total_signals': perf['total_signals'],
                'successful_signals': perf['successful_signals'],
                'signal_generation_rate': perf['win_rate'],
                'total_pnl': perf['total_pnl'],
                'avg_return': perf.get('avg_return', 0.0),
                'sharpe_ratio': perf.get('sharpe_ratio', 0.0),
                'current_position_value': allocation.position_value_usdc,
                'target_exposure_pct': allocation.target_exposure_pct
            }
            
            # Record in system health for now (until dedicated performance table is created)
            # Convert datetime to string for JSON serialization
            performance_data_json = {
                **performance_data,
                'timestamp': performance_data['timestamp'].isoformat()
            }
            await self.db_manager.record_health_check(
                'portfolio_performance_attribution',
                'healthy',
                performance_data_json
            )
            
            logger.debug(f"📊 Stored performance attribution for {symbol}")
            
        except Exception as e:
            logger.error(f"Failed to store performance attribution for {symbol}: {e}")

    async def _store_daily_pnl_data(self):
        """Store daily P&L data in database"""
        try:
            if not self.db_manager or not self.daily_pnl_by_asset:
                return
            
            # Store daily P&L summary
            pnl_summary = {
                'date': datetime.now().date().isoformat(),
                'total_assets': len(self.daily_pnl_by_asset),
                'total_pnl': sum(self.daily_pnl_by_asset.values()),
                'asset_pnl': dict(self.daily_pnl_by_asset),
                'portfolio_value': getattr(self, '_last_portfolio_value', 0.0)
            }
            
            # Record in system health for monitoring
            await self.db_manager.record_health_check(
                'daily_pnl_tracking',
                'updated',
                pnl_summary
            )
            
            logger.debug(f"📊 Stored daily P&L data for {len(self.daily_pnl_by_asset)} assets")
            
        except Exception as e:
            logger.error(f"Failed to store daily P&L data: {e}")

    async def _update_signal_performance_from_verified_trades(self):
        """Update signal performance tracking based on verified trade results from database"""
        try:
            if not self.db_manager:
                return
            
            # Query verified trades from the last 24 hours
            query = """
                SELECT 
                    t.trade_id,
                    tk.symbol,
                    t.trade_type,
                    t.signal_confidence,
                    t.predicted_change_pct,
                    t.execution_status,
                    t.confirmed_at,
                    t.value_usdc,
                    t.actual_output_amount
                FROM trades t
                JOIN tokens tk ON t.token_id = tk.token_id
                WHERE t.execution_status IN ('confirmed', 'failed')
                  AND t.confirmed_at >= NOW() - INTERVAL '24 hours'
                  AND t.cycle_timestamp IS NOT NULL
                ORDER BY t.confirmed_at DESC
                LIMIT 100
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                rows = await conn.fetch(query)
            
            if not rows:
                return
            
            # Process verified trades and update performance attribution
            for row in rows:
                symbol = row['symbol']
                trade_successful = row['execution_status'] == 'confirmed'
                
                # Initialize performance tracking if not exists
                if symbol not in self.performance_attribution:
                    self.performance_attribution[symbol] = {
                        'total_signals': 0,
                        'successful_signals': 0,
                        'total_pnl': 0.0,
                        'win_rate': 0.0,
                        'avg_return': 0.0,
                        'sharpe_ratio': 0.0,
                        'max_drawdown': 0.0,
                        'last_updated': datetime.now()
                    }
                
                perf = self.performance_attribution[symbol]
                
                # Update actual trade execution success (not just signal generation)
                perf['total_signals'] += 1
                if trade_successful:
                    perf['successful_signals'] += 1
                
                # Calculate actual trade success rate
                perf['win_rate'] = perf['successful_signals'] / perf['total_signals'] if perf['total_signals'] > 0 else 0.0
                perf['last_updated'] = datetime.now()
                
                logger.debug(f"📈 Updated trade performance for {symbol}: {perf['win_rate']:.1%} success rate ({perf['successful_signals']}/{perf['total_signals']})")
            
            logger.info(f"🔄 Updated signal performance from {len(rows)} verified trades")
            
        except Exception as e:
            logger.error(f"Failed to update signal performance from verified trades: {e}")

    async def _update_adaptive_strategy_with_signals(self, signals: List[TradingSignal]):
        """Feed generated signals to the adaptive strategy engine for performance tracking."""
        try:
            # Get the adaptive strategy engine directly
            from .adaptive_strategy import get_adaptive_strategy_engine
            adaptive_engine = await get_adaptive_strategy_engine()
            
            # Track all signals (both actionable and non-actionable)
            signals_tracked = 0
            for signal in signals:
                try:
                    # For now, we don't have actual returns yet, so we'll estimate success
                    # based on whether the signal would have been actionable
                    is_actionable = (
                        signal.signal_type in [SignalType.BUY, SignalType.SELL] and
                        abs(signal.predicted_change_pct) >= 0.015  # Use magnitude directly, not confidence
                    )
                    
                    # Estimate "success" based on predicted change magnitude
                    # This is a placeholder until we have actual trade results
                    magnitude = abs(signal.predicted_change_pct)
                    estimated_success = is_actionable and magnitude >= 0.02  # 2%+ changes more likely successful
                    estimated_return = signal.predicted_change_pct if estimated_success else -magnitude * 0.4
                    
                    # Update the adaptive strategy with signal performance
                    await adaptive_engine.update_signal_performance(
                        symbol=signal.symbol,
                        signal=signal,
                        actual_return=estimated_return,
                        success=estimated_success
                    )
                    
                    signals_tracked += 1
                    
                except Exception as signal_error:
                    logger.warning(f"Failed to track signal for {signal.symbol}: {signal_error}")
                    continue
            
            logger.debug(f"🧠 Adaptive strategy updated with {signals_tracked}/{len(signals)} signals")

        except Exception as e:
            logger.error(f"Failed to update adaptive strategy engine: {e}")

    async def get_portfolio_status(self) -> Dict[str, Any]:
        """Get current portfolio status and performance metrics"""
        try:
            portfolio_state = await self._get_portfolio_state()
            if not portfolio_state:
                return {}
            
            # Calculate performance metrics
            recent_signals = self.portfolio_history[-24:] if len(self.portfolio_history) >= 24 else self.portfolio_history
            
            avg_risk_score = np.mean([s.portfolio_risk_score for s in recent_signals]) if recent_signals else 0.0
            
            return {
                'timestamp': datetime.now().isoformat(),
                'portfolio_value': portfolio_state['portfolio_value'],
                'cash_balance': portfolio_state['cash_balance'],
                'exposure_pct': portfolio_state['exposure_percentage'],
                'position_count': portfolio_state['position_count'],
                'tracked_symbols': len(self.tracked_symbols),
                'avg_risk_score': avg_risk_score,
                'last_signal_count': len(recent_signals),
                'allocation_method': self.config.allocation_method.value,
                'max_exposure_limit': self.config.max_portfolio_exposure_pct,
                'max_per_asset_limit': self.config.max_single_asset_exposure_pct
            }
            
        except Exception as e:
            logger.error(f"Portfolio status retrieval failed: {e}")
            return {}

    async def close(self):
        """Clean up resources"""
        try:
            if self.position_manager:
                await self.position_manager.close()
            
            if self.db_manager:
                await self.db_manager.close()
                
            logger.info("Portfolio Coordinator closed")
        except Exception as e:
            logger.error(f"Error closing Portfolio Coordinator: {e}")

# Global coordinator instance for reuse across the application
_coordinator_instance: Optional[PortfolioCoordinator] = None

async def get_portfolio_coordinator(config: Optional[PortfolioConfig] = None, db_manager: Optional['ProductionDBManager'] = None) -> PortfolioCoordinator:
    """Get or create the global portfolio coordinator instance"""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = PortfolioCoordinator(config, db_manager)
        await _coordinator_instance.initialize()
    return _coordinator_instance

# Convenience functions for easy integration
async def generate_portfolio_signals(simulation_time: Optional[datetime] = None, override_portfolio_state: Optional[Dict[str, Any]] = None) -> Optional[PortfolioSignal]:
    """Convenience function to generate portfolio signals"""
    coordinator = await get_portfolio_coordinator()
    return await coordinator.generate_portfolio_signals(simulation_time, override_portfolio_state)

async def get_portfolio_status() -> Dict[str, Any]:
    """Convenience function to get portfolio status"""
    coordinator = await get_portfolio_coordinator()
    return await coordinator.get_portfolio_status() 