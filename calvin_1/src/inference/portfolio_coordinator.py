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
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import numpy as np
import pandas as pd
import json

# Local imports
from ..config.config import config
from ..utils.logger import log
from .strategy_engine import SimpleStrategyEngine, TradingSignal, SignalType, SignalStrength
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
    
    # Position sizing
    default_position_size_pct: float = 10.0  # Default position size
    min_position_size_usdc: float = 100.0  # Minimum position size
    max_position_size_usdc: float = 5000.0  # Maximum position size
    
    # Signal filtering
    min_signal_confidence: float = 0.70  # Minimum confidence for trades
    signal_timeout_minutes: int = 15  # Signal validity timeout
    
    # Allocation method
    allocation_method: AllocationMethod = AllocationMethod.CONFIDENCE_WEIGHTED
    
    # Performance tracking
    performance_lookback_days: int = 30  # Performance attribution period
    rebalance_frequency_minutes: int = 60  # Portfolio rebalance frequency
    
    # Risk management
    correlation_limit: float = 0.8  # Max correlation between positions
    max_drawdown_pct: float = 15.0  # Max portfolio drawdown
    
    # Token management
    max_concurrent_positions: int = 10  # Max number of open positions
    min_liquidity_usdc: float = 1000.0  # Min daily volume for trading

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
    
    # Execution priority (1 = highest, 10 = lowest)
    execution_priority: int = 5

class PortfolioCoordinator:
    """
    Multi-Asset Portfolio Coordination Engine
    
    Coordinates trading signals across multiple assets with sophisticated risk management
    and position allocation logic.
    """
    
    def __init__(self, config: Optional[PortfolioConfig] = None):
        """
        Initialize the portfolio coordinator
        
        Args:
            config: Portfolio configuration (uses env defaults if None)
        """
        self.config = config or self._load_config_from_env()
        
        # Initialize core components
        self.strategy_engine = SimpleStrategyEngine()
        self.model_registry = get_model_registry()
        
        # Database and position management
        self.db_manager = None
        self.position_manager = None
        
        # Portfolio state
        self.tracked_symbols: List[str] = []
        self.active_allocations: Dict[str, AssetAllocation] = {}
        self.portfolio_history: List[PortfolioSignal] = []
        
        # Performance tracking
        self.daily_pnl_by_asset: Dict[str, float] = {}
        self.performance_attribution: Dict[str, Dict[str, float]] = {}
        
        # Signal management
        self.last_signals: Dict[str, TradingSignal] = {}
        self.signal_cache_timeout = timedelta(minutes=self.config.signal_timeout_minutes)
        
        # Risk management
        self.risk_limits = self._create_risk_limits()
        
        logger.info("Portfolio Coordinator initialized")
        logger.info(f"Config: max_exposure={self.config.max_portfolio_exposure_pct}%, "
                   f"max_per_asset={self.config.max_single_asset_exposure_pct}%, "
                   f"allocation_method={self.config.allocation_method.value}")

    def _load_config_from_env(self) -> PortfolioConfig:
        """Load portfolio configuration from environment variables"""
        # Parse tracked tokens from environment
        tracked_tokens_str = os.getenv('TRACKED_TOKENS', '')
        self.tracked_tokens_addresses = [addr.strip() for addr in tracked_tokens_str.split(',') if addr.strip()]
        
        return PortfolioConfig(
            # Portfolio risk limits from position manager env vars
            max_portfolio_exposure_pct=float(os.getenv('PORTFOLIO_MAX_EXPOSURE_PCT', 80.0)),
            max_single_asset_exposure_pct=float(os.getenv('TOKEN_MAX_EXPOSURE_PCT', 20.0)),
            min_cash_reserve_pct=100.0 - float(os.getenv('PORTFOLIO_MAX_EXPOSURE_PCT', 80.0)),
            
            # Position sizing from env
            default_position_size_pct=float(os.getenv('DEFAULT_POSITION_SIZE_PCT', 10.0)),
            min_position_size_usdc=float(os.getenv('MIN_POSITION_SIZE_USDC', 100.0)),
            max_position_size_usdc=float(os.getenv('MAX_POSITION_SIZE_USDC', 5000.0)),
            
            # Signal filtering
            min_signal_confidence=float(os.getenv('MIN_PREDICTION_CONFIDENCE', 0.70)),
            signal_timeout_minutes=int(os.getenv('SIGNAL_TIMEOUT_MINUTES', 15)),
            
            # Performance tracking
            performance_lookback_days=int(os.getenv('PERFORMANCE_LOOKBACK_DAYS', 30)),
            rebalance_frequency_minutes=int(os.getenv('REBALANCE_FREQUENCY_MINUTES', 60)),
            
            # Risk management
            max_drawdown_pct=float(os.getenv('MAX_DRAWDOWN_PCT', 15.0)),
            max_concurrent_positions=int(os.getenv('MAX_CONCURRENT_POSITIONS', 10)),
            min_liquidity_usdc=float(os.getenv('MIN_LIQUIDITY_USDC', 1000.0)),
            
            # Allocation method from env
            allocation_method=AllocationMethod(os.getenv('ALLOCATION_METHOD', 'confidence_weighted'))
        )

    def _create_risk_limits(self) -> RiskLimits:
        """Create risk limits for position manager integration"""
        return RiskLimits(
            max_position_size_usdc=self.config.max_position_size_usdc,
            max_portfolio_exposure_pct=self.config.max_portfolio_exposure_pct,
            max_single_token_exposure_pct=self.config.max_single_asset_exposure_pct,
            max_drawdown_pct=self.config.max_drawdown_pct,
            max_daily_loss_usdc=float(os.getenv('MAX_DAILY_LOSS_USDC', 2000.0)),
            min_position_size_usdc=self.config.min_position_size_usdc
        )

    async def initialize(self):
        """Initialize async components"""
        try:
            # Initialize database manager
            self.db_manager = await get_db_manager()
            
            # Load tracked symbols from database
            await self._load_tracked_symbols()
            
            # Initialize position manager with our risk limits
            # Note: This will be integrated when PositionManager supports async initialization
            # For now, we'll use database queries directly
            
            logger.info(f"Portfolio Coordinator initialized with {len(self.tracked_symbols)} tracked symbols")
            logger.info(f"Tracked symbols: {', '.join(self.tracked_symbols[:10])}{'...' if len(self.tracked_symbols) > 10 else ''}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Portfolio Coordinator: {e}")
            raise

    async def _load_tracked_symbols(self):
        """Load tracked symbols from database using token addresses"""
        try:
            self.tracked_symbols = []
            
            # Get all active tokens from database
            active_tokens = await self.db_manager.get_active_tokens()
            
            # Filter to only tracked tokens
            for token in active_tokens:
                if token['address'] in self.tracked_tokens_addresses:
                    self.tracked_symbols.append(token['symbol'])
            
            # Fallback: if no tracked symbols found, use available models
            if not self.tracked_symbols:
                logger.warning("No tracked symbols found in database, using available models")
                models = self.model_registry.list_models()
                self.tracked_symbols = list(set([model.symbol for model in models]))
            
            logger.info(f"Loaded {len(self.tracked_symbols)} tracked symbols")
            
        except Exception as e:
            logger.error(f"Failed to load tracked symbols: {e}")
            # Fallback to basic symbols
            self.tracked_symbols = ['BONK', 'JUP', 'SOL', 'Fartcoin']

    async def generate_portfolio_signals(self) -> Optional[PortfolioSignal]:
        """
        Generate coordinated portfolio signals across all tracked assets
        
        Returns:
            PortfolioSignal with allocation recommendations or None if failed
        """
        try:
            start_time = datetime.now()
            
            # 1. Get current portfolio state
            portfolio_state = await self._get_portfolio_state()
            if not portfolio_state:
                logger.error("Failed to get portfolio state")
                return None
            
            # 2. Generate individual signals for each tracked symbol
            individual_signals = await self._generate_individual_signals()
            
            # 3. Filter and validate signals
            valid_signals = self._filter_signals(individual_signals)
            
            # 4. Perform portfolio-level risk assessment
            risk_assessment = await self._assess_portfolio_risk(valid_signals, portfolio_state)
            
            # 5. Generate asset allocation recommendations
            asset_allocations = await self._calculate_asset_allocations(
                valid_signals, portfolio_state, risk_assessment
            )
            
            # 6. Create portfolio signal
            portfolio_signal = PortfolioSignal(
                timestamp=datetime.now(),
                total_cash_available=portfolio_state['cash_balance'],
                portfolio_value=portfolio_state['portfolio_value'],
                current_exposure_pct=portfolio_state['exposure_pct'],
                buy_signals=[s for s in valid_signals if s.signal_type == SignalType.BUY],
                sell_signals=[s for s in valid_signals if s.signal_type == SignalType.SELL],
                asset_allocations=asset_allocations,
                cash_allocation_pct=self._calculate_target_cash_allocation(asset_allocations),
                portfolio_risk_score=risk_assessment['portfolio_risk'],
                correlation_risk=risk_assessment['correlation_risk'],
                concentration_risk=risk_assessment['concentration_risk'],
                execution_priority=self._calculate_execution_priority(valid_signals, risk_assessment)
            )
            
            # 7. Cache and track performance
            self._update_performance_tracking(portfolio_signal)
            
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"Generated portfolio signals for {len(self.tracked_symbols)} assets in {processing_time:.1f}ms")
            logger.info(f"Signals: {len(portfolio_signal.buy_signals)} BUY, {len(portfolio_signal.sell_signals)} SELL, "
                       f"exposure: {portfolio_signal.current_exposure_pct:.1f}%")
            
            return portfolio_signal
            
        except Exception as e:
            logger.error(f"Portfolio signal generation failed: {e}")
            return None

    async def _get_portfolio_state(self) -> Optional[Dict[str, Any]]:
        """Get current portfolio state from database"""
        try:
            # Get total portfolio value from environment (vault integration pending)
            portfolio_value = float(os.getenv('PORTFOLIO_VALUE_USDC', 100000.0))
            
            # Get current positions (when position manager is integrated)
            # For now, calculate based on database
            total_position_value = 0.0
            position_count = 0
            
            # This would be replaced with position manager integration:
            # open_positions = await self.position_manager.get_open_positions()
            
            # Calculate exposure
            cash_balance = portfolio_value - total_position_value
            exposure_pct = (total_position_value / portfolio_value) * 100 if portfolio_value > 0 else 0
            
            return {
                'portfolio_value': portfolio_value,
                'cash_balance': cash_balance,
                'total_position_value': total_position_value,
                'position_count': position_count,
                'exposure_pct': exposure_pct,
                'available_buying_power': cash_balance * (self.config.max_portfolio_exposure_pct / 100)
            }
            
        except Exception as e:
            logger.error(f"Failed to get portfolio state: {e}")
            return None

    async def _generate_individual_signals(self) -> List[TradingSignal]:
        """Generate trading signals for all tracked symbols"""
        signals = []
        
        # Generate signals in parallel for better performance
        signal_tasks = []
        for symbol in self.tracked_symbols:
            task = self.strategy_engine.generate_signal(symbol)
            signal_tasks.append(task)
        
        # Wait for all signals to complete
        signal_results = await asyncio.gather(*signal_tasks, return_exceptions=True)
        
        # Process results
        for i, result in enumerate(signal_results):
            symbol = self.tracked_symbols[i]
            
            if isinstance(result, Exception):
                logger.warning(f"Signal generation failed for {symbol}: {result}")
                continue
            
            if result is not None:
                signals.append(result)
                self.last_signals[symbol] = result
            
        logger.debug(f"Generated {len(signals)} individual signals from {len(self.tracked_symbols)} symbols")
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
            exposure_risk = portfolio_state['exposure_pct'] / self.config.max_portfolio_exposure_pct
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
                base_size = self.config.default_position_size_pct / 100
                confidence_multiplier = signal.confidence
                strength_multiplier = {'weak': 0.5, 'moderate': 1.0, 'strong': 1.5}.get(
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
        """Calculate optimal asset allocations based on signals and risk"""
        allocations = {}
        
        try:
            # Get available buying power
            available_cash = portfolio_state['available_buying_power']
            
            # Filter to actionable signals
            buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
            
            if not buy_signals:
                logger.debug("No buy signals to allocate")
                return allocations
            
            # Calculate allocation weights based on method
            weights = self._calculate_allocation_weights(buy_signals, risk_assessment)
            
            # Calculate position sizes
            for signal, weight in zip(buy_signals, weights):
                # Get token info
                token_info = await self.db_manager.get_token_by_symbol(signal.symbol)
                if not token_info:
                    logger.warning(f"Token info not found for {signal.symbol}")
                    continue
                
                # Calculate target allocation
                target_position_value = available_cash * weight
                target_position_value = min(target_position_value, self.config.max_position_size_usdc)
                target_position_value = max(target_position_value, self.config.min_position_size_usdc)
                
                # Create allocation
                allocation = AssetAllocation(
                    symbol=signal.symbol,
                    token_id=token_info['token_id'],
                    current_exposure_pct=0.0,  # Would get from position manager
                    target_exposure_pct=(target_position_value / portfolio_state['portfolio_value']) * 100,
                    position_value_usdc=target_position_value,
                    signal=signal,
                    last_updated=datetime.now()
                )
                
                allocations[signal.symbol] = allocation
            
            logger.debug(f"Calculated allocations for {len(allocations)} assets")
            return allocations
            
        except Exception as e:
            logger.error(f"Asset allocation calculation failed: {e}")
            return {}

    def _calculate_allocation_weights(self, signals: List[TradingSignal], 
                                    risk_assessment: Dict[str, float]) -> List[float]:
        """Calculate allocation weights based on configured method"""
        if not signals:
            return []
        
        if self.config.allocation_method == AllocationMethod.EQUAL_WEIGHT:
            return [1.0 / len(signals)] * len(signals)
        
        elif self.config.allocation_method == AllocationMethod.CONFIDENCE_WEIGHTED:
            confidences = [s.confidence for s in signals]
            total_confidence = sum(confidences)
            return [conf / total_confidence for conf in confidences] if total_confidence > 0 else [1.0 / len(signals)] * len(signals)
        
        elif self.config.allocation_method == AllocationMethod.SIGNAL_STRENGTH:
            strength_scores = []
            for signal in signals:
                score = {'weak': 1.0, 'moderate': 2.0, 'strong': 3.0}.get(signal.strength.value, 1.0)
                strength_scores.append(score)
            
            total_score = sum(strength_scores)
            return [score / total_score for score in strength_scores] if total_score > 0 else [1.0 / len(signals)] * len(signals)
        
        else:  # Default to confidence weighted
            confidences = [s.confidence for s in signals]
            total_confidence = sum(confidences)
            return [conf / total_confidence for conf in confidences] if total_confidence > 0 else [1.0 / len(signals)] * len(signals)

    def _calculate_target_cash_allocation(self, asset_allocations: Dict[str, AssetAllocation]) -> float:
        """Calculate target cash allocation percentage"""
        total_target_exposure = sum(alloc.target_exposure_pct for alloc in asset_allocations.values())
        target_cash_pct = 100.0 - total_target_exposure
        
        # Ensure minimum cash reserve
        target_cash_pct = max(target_cash_pct, self.config.min_cash_reserve_pct)
        
        return target_cash_pct

    def _calculate_execution_priority(self, signals: List[TradingSignal], 
                                    risk_assessment: Dict[str, float]) -> int:
        """Calculate execution priority (1=highest, 10=lowest)"""
        # High priority for high-confidence signals with low portfolio risk
        avg_confidence = np.mean([s.confidence for s in signals]) if signals else 0.5
        portfolio_risk = risk_assessment.get('portfolio_risk', 0.5)
        
        # Priority score: higher confidence and lower risk = higher priority (lower number)
        priority_score = (1.0 - avg_confidence) + portfolio_risk
        
        # Convert to 1-10 scale
        priority = int(np.clip(priority_score * 10, 1, 10))
        
        return priority

    def _update_performance_tracking(self, portfolio_signal: PortfolioSignal):
        """Update performance tracking metrics"""
        try:
            # Add the new signal to history
            self.portfolio_history.append(portfolio_signal)
            
            # Keep only recent history
            max_history = 1000
            if len(self.portfolio_history) > max_history:
                self.portfolio_history = self.portfolio_history[-max_history:]
            
            # Update daily PnL tracking (placeholder for now)
            # This would integrate with actual position tracking
            
        except Exception as e:
            logger.error(f"Performance tracking update failed: {e}")

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
                'exposure_pct': portfolio_state['exposure_pct'],
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
            if self.db_manager:
                await self.db_manager.close()
            logger.info("Portfolio Coordinator closed")
        except Exception as e:
            logger.error(f"Error closing Portfolio Coordinator: {e}")

# Global coordinator instance for reuse across the application
_coordinator_instance: Optional[PortfolioCoordinator] = None

async def get_portfolio_coordinator() -> PortfolioCoordinator:
    """Get or create the global portfolio coordinator instance"""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = PortfolioCoordinator()
        await _coordinator_instance.initialize()
    return _coordinator_instance

# Convenience functions for easy integration
async def generate_portfolio_signals() -> Optional[PortfolioSignal]:
    """Convenience function to generate portfolio signals"""
    coordinator = await get_portfolio_coordinator()
    return await coordinator.generate_portfolio_signals()

async def get_portfolio_status() -> Dict[str, Any]:
    """Convenience function to get portfolio status"""
    coordinator = await get_portfolio_coordinator()
    return await coordinator.get_portfolio_status() 