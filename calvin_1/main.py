#!/usr/bin/env python3
import os
import sys
import argparse
import asyncio
import json
import signal
from typing import Dict, Any
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path
import pandas as pd

# Add current directory to path for consistent src imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Find and load environment variables from .env file
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent  # Navigate to project root
root_env_path = project_root / '.env'

if root_env_path.exists():
    load_dotenv(root_env_path)
else:
    # Fallback to the current directory
    current_dir_env = current_file.parent / '.env'
    if current_dir_env.exists():
        load_dotenv(current_dir_env)
    else:
        # Last resort, try default behavior
        load_dotenv()

from src.data.data_processor import DataProcessor
from src.model.ml_model import MLModel
from src.trading.trading_strategy import TradingStrategy
from src.trading.wallet import SolanaWallet
from src.config.config import config
from src.utils.logger import log_manager, log


# NEW: Phase 3.2 imports
from src.data.hourly_inference_scheduler import HourlyInferenceScheduler
from src.database.production_db import get_db_manager

# Initialize global logger
logger = log


class CalvinVaultSystem:
    """
    Calvin AI Vault Trading System - Main Orchestrator (Phase 3.2)
    
    Coordinates the complete Calvin AI trading system with vault integration.
    """
    
    def __init__(self):
        self.scheduler = None
        self.websocket_manager = None
        self.emergency_monitor = None
        self.running = False
        
        logger.info("Calvin Vault System initializing...")

    async def initialize(self):
        """Initialize all system components"""
        try:
            # Initialize database connection
            db_manager = await get_db_manager()
            await db_manager.health_check()
            logger.info("✅ Database connection established")
            
            # Initialize WebSocket Feed Manager for all tracked tokens
            from src.data.websocket_feed import WebSocketFeedManager
            self.websocket_manager = WebSocketFeedManager()
            await self.websocket_manager.initialize()
            logger.info("✅ WebSocket Feed Manager initialized")
            
            # Initialize inference scheduler with vault trading
            self.scheduler = HourlyInferenceScheduler()
            await self.scheduler.initialize()
            logger.info("✅ Inference scheduler initialized")
            
            # Initialize emergency monitoring
            from src.vault.emergency_monitor import EmergencyStopLossMonitor
            self.emergency_monitor = EmergencyStopLossMonitor()
            await self.emergency_monitor.initialize()
            
            # 🚨 CRITICAL FIX: Connect emergency monitor to WebSocket feeds
            # The emergency monitor needs access to the WebSocket feed for price monitoring
            if hasattr(self.websocket_manager, 'price_feed') and self.websocket_manager.price_feed:
                self.emergency_monitor.websocket_feed = self.websocket_manager.price_feed
                logger.info("✅ Emergency monitor connected to WebSocket price feed")
            else:
                logger.warning("⚠️ Emergency monitor running without WebSocket feeds (price monitoring disabled)")
            
            # Connect emergency monitor to websocket price feeds
            self.websocket_manager.add_price_handler(self._relay_price_to_emergency_monitor)
            logger.info("✅ Emergency monitoring initialized")
            
            # Validate environment configuration
            self._validate_configuration()
            
            # 🆕 VALIDATE SYSTEM STATE RECOVERY
            await self._validate_state_recovery()
            
            logger.info("✅ Calvin Vault System initialization complete with state recovery")
            
        except Exception as e:
            logger.error(f"System initialization failed: {e}")
            raise

    def _validate_configuration(self):
        """Validate required configuration"""
        required_vars = [
            'DATABASE_URL',
            'REDIS_URL',
            'BIRDEYE_API_KEY'  # Required for WebSocket feeds
        ]
        
        # Optional vault-specific variables (will use defaults if not set)
        vault_vars = [
            'CALVIN_AUTHORITY_PRIVATE_KEY',
            'CALVIN_VAULT_PROGRAM_ID', 
            'CALVIN_STAKING_PROGRAM_ID',
            'SOLANA_RPC_URL'
        ]
        
        missing = [var for var in required_vars if not config.get(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {missing}")
        
        missing_vault = [var for var in vault_vars if not config.get(var)]
        if missing_vault:
            logger.warning(f"⚠️ Vault variables not set (will run in simulation mode): {missing_vault}")
        
        logger.info("✅ Configuration validation passed")

    async def start(self):
        """Start the complete Calvin vault trading system"""
        try:
            # Track startup time for uptime calculation
            self.start_time = datetime.utcnow()
            
            await self.initialize()
            
            logger.info("🚀 Starting Calvin AI Vault Trading System")
            logger.info(f"⏰ Inference + Trading Interval: {self.scheduler.config.ohlcv_interval_minutes} minutes")
            logger.info(f"📊 Social Data Interval: {self.scheduler.config.social_interval_minutes} minutes (hourly for model features)")
            logger.info(f"🔍 Health Check Interval: {self.scheduler.config.health_check_interval_minutes} minutes")
            
            self.running = True
            
            # Start WebSocket feeds for all tracked tokens FIRST
            await self.websocket_manager.start()
            logger.info("✅ WebSocket feeds started for all tracked tokens")
            
            # Start inference and trading scheduler
            await self.scheduler.start_async()
            logger.info("✅ Enhanced inference scheduler started with vault trading")
            
            # Start emergency monitoring (will use existing websocket feeds)
            asyncio.create_task(self._start_emergency_monitoring())
            logger.info("✅ Emergency monitoring started")
            
            # Keep running with enhanced health monitoring
            while self.running:
                await asyncio.sleep(60)  # Check every minute
                
                # Periodic health checks and status reports
                if datetime.now().minute == 0:  # Every hour
                    await self._comprehensive_health_check()
            
        except Exception as e:
            logger.error(f"❌ System startup failed: {e}")
            await self.shutdown()
            raise

    async def _start_emergency_monitoring(self):
        """Start emergency monitoring in background"""
        try:
            if self.emergency_monitor:
                # Emergency monitor will use websocket feeds from the manager
                await self.emergency_monitor.start_monitoring()
        except Exception as e:
            logger.error(f"❌ Emergency monitoring startup failed: {e}")

    async def _relay_price_to_emergency_monitor(self, symbol: str, price_update):
        """Relay price updates from websocket manager to emergency monitor"""
        try:
            if self.emergency_monitor and hasattr(self.emergency_monitor, '_on_price_update'):
                # The emergency monitor expects a PriceUpdate object directly
                await self.emergency_monitor._on_price_update(price_update)
        except Exception as e:
            logger.error(f"❌ Error relaying price update to emergency monitor: {e}")

    async def _comprehensive_health_check(self):
        """Enhanced system health check with all components"""
        try:
            # Check scheduler health
            if not self.scheduler or not self.scheduler.is_running:
                logger.warning("⚠️ Scheduler not running - attempting restart")
                await self.scheduler.start_async()
            
            # Check WebSocket feed health
            if self.websocket_manager:
                ws_stats = self.websocket_manager.get_stats()
                logger.info(f"📡 WebSocket Health: {ws_stats['tokens_subscribed']} tokens, {ws_stats['price_updates_received']} updates")
                
                # Refresh tokens periodically (every 6 hours)
                if ws_stats['last_token_refresh']:
                    last_refresh = ws_stats['last_token_refresh']
                    if isinstance(last_refresh, str):
                        from datetime import datetime
                        last_refresh = datetime.fromisoformat(last_refresh.replace('Z', '+00:00'))
                    
                    hours_since_refresh = (datetime.utcnow() - last_refresh).total_seconds() / 3600
                    if hours_since_refresh > 6:  # Refresh every 6 hours
                        logger.info("🔄 Refreshing tracked tokens...")
                        await self.websocket_manager.refresh_tokens()
            
            # Check database connectivity
            db_manager = await get_db_manager()
            await db_manager.health_check()
            
            # Log enhanced system stats
            stats = self.scheduler.get_enhanced_statistics()
            logger.info(f"📈 System Health Report:")
            logger.info(f"   Inference cycles: {stats.get('vault_trading', {}).get('total_cycles', 0)}")
            logger.info(f"   Vault trades: {stats.get('vault_trading', {}).get('total_trades', 0)}")
            logger.info(f"   Success rate: {stats.get('vault_trading', {}).get('cycles_per_hour', 0):.1f} cycles/hour")
            
            # Log emergency monitoring stats
            if self.emergency_monitor:
                emergency_stats = self.emergency_monitor.get_monitoring_stats()
                logger.info(f"🚨 Emergency Monitor: {emergency_stats.get('positions_monitored', 0)} positions, {emergency_stats.get('emergency_events_triggered', 0)} events")
            
        except Exception as e:
            logger.error(f"❌ Comprehensive health check failed: {e}")

    async def shutdown(self):
        """Graceful system shutdown with state persistence"""
        logger.info("🛑 Initiating graceful Calvin Vault System shutdown...")
        
        self.running = False
        
        try:
            # 🆕 PERSIST STATE BEFORE SHUTDOWN
            await self._persist_system_state()
            
            # Stop scheduler
            if self.scheduler:
                logger.info("🔄 Stopping inference scheduler...")
                await self.scheduler.stop_async()
                logger.info("✅ Scheduler stopped")
            
            # Stop WebSocket manager
            if self.websocket_manager:
                logger.info("🔄 Stopping WebSocket feed manager...")
                await self.websocket_manager.stop()
                logger.info("✅ WebSocket manager stopped")
            
            # Stop emergency monitor
            if self.emergency_monitor:
                logger.info("🔄 Stopping emergency monitor...")
                await self.emergency_monitor.stop_monitoring()
                logger.info("✅ Emergency monitor stopped")
            
            # Final health check record
            await self._record_shutdown_status()
            
            logger.info("🏁 Calvin Vault System shutdown complete")
            
        except Exception as e:
            logger.error(f"Shutdown error: {e}")

    async def _persist_system_state(self):
        """Persist critical system state before shutdown"""
        try:
            logger.info("💾 Persisting system state before shutdown...")
            
            # 1. Persist portfolio coordinator state
            await self._persist_portfolio_state()
            
            # 2. Persist emergency monitor state
            await self._persist_emergency_state()
            
            # 3. Record final system statistics
            await self._record_final_system_stats()
            
            logger.info("✅ System state persisted successfully")
            
        except Exception as e:
            logger.warning(f"⚠️ State persistence failed (non-critical): {e}")
    
    async def _persist_portfolio_state(self):
        """Persist portfolio coordinator state to database"""
        try:
            from src.inference.portfolio_coordinator import get_portfolio_coordinator
            coordinator = await get_portfolio_coordinator()
            
            # Persist daily P&L tracking
            if coordinator.daily_pnl_by_asset:
                db_manager = await get_db_manager()
                await db_manager.record_health_check(
                    component='daily_pnl_tracking',
                    status='updated',
                    details={
                        'asset_pnl': coordinator.daily_pnl_by_asset,
                        'total_assets': len(coordinator.daily_pnl_by_asset),
                        'last_updated': datetime.utcnow().isoformat()
                    }
                )
            
            # Persist performance attribution for each asset
            for symbol, perf_data in coordinator.performance_attribution.items():
                db_manager = await get_db_manager()
                await db_manager.record_health_check(
                    component='portfolio_performance_attribution',
                    status='healthy',
                    details={
                        'symbol': symbol,
                        'total_signals': perf_data.get('total_signals', 0),
                        'successful_signals': perf_data.get('successful_signals', 0),
                        'total_pnl': perf_data.get('total_pnl', 0.0),
                        'signal_generation_rate': perf_data.get('win_rate', 0.0),
                        'avg_return': perf_data.get('avg_return', 0.0),
                        'sharpe_ratio': perf_data.get('sharpe_ratio', 0.0),
                        'last_updated': datetime.utcnow().isoformat()
                    }
                )
            
            logger.info(f"💾 Persisted portfolio state: {len(coordinator.daily_pnl_by_asset)} P&L assets, {len(coordinator.performance_attribution)} performance records")
            
        except Exception as e:
            logger.warning(f"Failed to persist portfolio state: {e}")
    
    async def _persist_emergency_state(self):
        """Persist emergency monitor state to database"""
        try:
            if self.emergency_monitor:
                db_manager = await get_db_manager()
                
                # Get monitoring stats from the correct method
                monitoring_stats = self.emergency_monitor.get_monitoring_stats()
                
                await db_manager.record_health_check(
                    component='emergency_monitor',
                    status='healthy',
                    details={
                        'emergency_exits_today': self.emergency_monitor.emergency_exits_today,
                        'max_daily_exits': self.emergency_monitor.thresholds.max_daily_exits,
                        'total_alerts_today': monitoring_stats.get('total_alerts', 0),
                        'portfolio_checks_today': monitoring_stats.get('portfolio_checks', 0),
                        'position_checks_today': monitoring_stats.get('position_checks', 0),
                        'price_updates_processed': monitoring_stats.get('price_updates_processed', 0),
                        'emergency_events_triggered': monitoring_stats.get('emergency_events_triggered', 0),
                        'positions_monitored': monitoring_stats.get('positions_monitored', 0),
                        'last_updated': datetime.utcnow().isoformat(),
                        'shutdown_persist': True
                    }
                )
                
                logger.info(f"💾 Persisted emergency state: {self.emergency_monitor.emergency_exits_today} exits today")
            
        except Exception as e:
            logger.warning(f"Failed to persist emergency state: {e}")
    
    async def _record_final_system_stats(self):
        """Record final system statistics before shutdown"""
        try:
            db_manager = await get_db_manager()
            
            # Calculate system uptime
            if hasattr(self, 'start_time'):
                uptime_seconds = (datetime.utcnow() - self.start_time).total_seconds()
            else:
                uptime_seconds = 0
            
            # Collect final stats
            stats = {
                'shutdown_timestamp': datetime.utcnow().isoformat(),
                'uptime_seconds': uptime_seconds,
                'uptime_hours': uptime_seconds / 3600,
                'graceful_shutdown': True,
                'components_active': {
                    'scheduler': self.scheduler is not None,
                    'websocket_manager': self.websocket_manager is not None,
                    'emergency_monitor': self.emergency_monitor is not None
                }
            }
            
            # Use 'healthy' status instead of 'completed' to avoid constraint violation
            await db_manager.record_health_check(
                component='system_shutdown',
                status='healthy',  # FIXED: Use valid health status
                details=stats
            )
            
            logger.info(f"💾 Recorded final system stats: {uptime_seconds/3600:.1f}h uptime")
            
        except Exception as e:
            logger.warning(f"Failed to record final system stats: {e}")
    
    async def _record_shutdown_status(self):
        """Record final shutdown status"""
        try:
            db_manager = await get_db_manager()
            # Use 'healthy' status for successful shutdown instead of 'shutdown'
            await db_manager.record_health_check(
                component='calvin_vault_system',
                status='healthy',  # FIXED: Use valid health status
                details={
                    'timestamp': datetime.utcnow().isoformat(),
                    'shutdown_type': 'graceful',
                    'all_components_stopped': True
                }
            )
            
        except Exception as e:
            logger.warning(f"Failed to record shutdown status: {e}")

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum} - initiating shutdown")
        asyncio.create_task(self.shutdown())

    async def _validate_state_recovery(self):
        """Validate that all components have properly recovered their state"""
        try:
            logger.info("🔍 Validating system state recovery...")
            recovery_report = {}
            
            # 1. Validate database connectivity and recent data
            db_validation = await self._validate_database_state()
            recovery_report['database'] = db_validation
            
            # 2. Validate portfolio coordinator state recovery
            portfolio_validation = await self._validate_portfolio_state()
            recovery_report['portfolio_coordinator'] = portfolio_validation
            
            # 3. Validate position manager state recovery
            position_validation = await self._validate_position_state()
            recovery_report['position_manager'] = position_validation
            
            # 4. Validate emergency monitor state recovery
            emergency_validation = await self._validate_emergency_state()
            recovery_report['emergency_monitor'] = emergency_validation
            
            # 5. Validate vault connectivity
            vault_validation = await self._validate_vault_connectivity()
            recovery_report['vault_connectivity'] = vault_validation
            
            # Generate recovery summary
            successful_recoveries = sum(1 for result in recovery_report.values() if result['status'] == 'recovered')
            total_components = len(recovery_report)
            
            logger.info(f"📊 State Recovery Summary: {successful_recoveries}/{total_components} components recovered successfully")
            
            for component, result in recovery_report.items():
                status_emoji = "✅" if result['status'] == 'recovered' else "⚠️" if result['status'] == 'partial' else "❌"
                logger.info(f"  {status_emoji} {component}: {result['message']}")
            
            # Log any warnings or issues
            warnings = [result['message'] for result in recovery_report.values() if result['status'] in ['partial', 'failed']]
            if warnings:
                logger.warning(f"⚠️ State recovery warnings: {'; '.join(warnings)}")
            
            # Record state recovery status in database
            await self._record_state_recovery_status(recovery_report)
            
        except Exception as e:
            logger.error(f"State recovery validation failed: {e}")
            # Don't fail initialization - system can still operate with default state
    
    async def _validate_database_state(self) -> Dict[str, str]:
        """Validate database state and recent data availability"""
        try:
            db_manager = await get_db_manager()
            
            # Check recent portfolio cycles
            recent_cycles = await db_manager.get_recent_portfolio_cycles(limit=5)
            cycles_count = len(recent_cycles)
            
            # Check open positions
            open_positions = await db_manager.get_open_positions()
            positions_count = len(open_positions)
            
            # Check recent trades
            recent_trades = await db_manager.get_pending_trades(hours_back=24)
            trades_count = len(recent_trades)
            
            if cycles_count > 0:
                last_cycle = recent_cycles[0]['cycle_timestamp']
                hours_since_last = (datetime.utcnow() - last_cycle).total_seconds() / 3600
                
                if hours_since_last < 2:  # Recent activity
                    return {
                        'status': 'recovered',
                        'message': f"{cycles_count} recent cycles, {positions_count} open positions, {trades_count} pending trades"
                    }
                else:
                    return {
                        'status': 'partial',
                        'message': f"Last cycle {hours_since_last:.1f}h ago, {positions_count} positions"
                    }
            else:
                return {
                    'status': 'partial',
                    'message': f"No recent cycles, {positions_count} positions available"
                }
                
        except Exception as e:
            return {
                'status': 'failed',
                'message': f"Database validation failed: {e}"
            }
    
    async def _validate_portfolio_state(self) -> Dict[str, str]:
        """Validate portfolio coordinator state recovery"""
        try:
            # Check if portfolio coordinator recovered state
            from src.inference.portfolio_coordinator import get_portfolio_coordinator
            coordinator = await get_portfolio_coordinator()
            
            # Check recovered data
            daily_pnl_assets = len(coordinator.daily_pnl_by_asset)
            performance_assets = len(coordinator.performance_attribution)
            history_length = len(coordinator.portfolio_history)
            tracked_symbols = len(coordinator.tracked_symbols)
            
            if daily_pnl_assets > 0 or performance_assets > 0 or history_length > 0:
                return {
                    'status': 'recovered',
                    'message': f"{tracked_symbols} tracked symbols, {daily_pnl_assets} P&L assets, {performance_assets} perf. assets, {history_length} history"
                }
            else:
                return {
                    'status': 'partial',
                    'message': f"{tracked_symbols} tracked symbols loaded (no historical state recovered)"
                }
                
        except Exception as e:
            return {
                'status': 'failed',
                'message': f"Portfolio validation failed: {e}"
            }
    
    async def _validate_position_state(self) -> Dict[str, str]:
        """Validate position manager state recovery"""
        try:
            # Check if position manager recovered positions
            from src.trading.position_manager import get_position_manager
            position_manager = await get_position_manager()
            
            active_positions = len(position_manager.get_active_positions())
            position_tokens = len(position_manager.position_by_token)
            
            if active_positions > 0:
                return {
                    'status': 'recovered',
                    'message': f"{active_positions} active positions across {position_tokens} tokens"
                }
            else:
                return {
                    'status': 'recovered',
                    'message': "No active positions (clean slate)"
                }
                
        except Exception as e:
            return {
                'status': 'failed',
                'message': f"Position validation failed: {e}"
            }
    
    async def _validate_emergency_state(self) -> Dict[str, str]:
        """Validate emergency monitor state recovery"""
        try:
            if self.emergency_monitor:
                emergency_exits = self.emergency_monitor.emergency_exits_today
                max_exits = self.emergency_monitor.thresholds.max_daily_exits
                
                return {
                    'status': 'recovered',
                    'message': f"{emergency_exits}/{max_exits} emergency exits today"
                }
            else:
                return {
                    'status': 'failed',
                    'message': "Emergency monitor not initialized"
                }
                
        except Exception as e:
            return {
                'status': 'failed',
                'message': f"Emergency validation failed: {e}"
            }
    
    async def _validate_vault_connectivity(self) -> Dict[str, str]:
        """Validate vault smart contract connectivity"""
        try:
            # Test vault connectivity through emergency monitor
            if self.emergency_monitor and self.emergency_monitor.vault_client:
                vault_state = await self.emergency_monitor.vault_client.get_vault_state()
                
                if vault_state.get('initialized', False):
                    total_usdc = vault_state.get('total_usdc', 0)
                    total_shares = vault_state.get('total_shares', 0)
                    return {
                        'status': 'recovered',
                        'message': f"Vault: ${total_usdc:,.2f} USDC, {total_shares:,} shares"
                    }
                else:
                    return {
                        'status': 'failed',
                        'message': "Vault not initialized or unreachable"
                    }
            else:
                return {
                    'status': 'failed',
                    'message': "Vault client not available"
                }
                
        except Exception as e:
            return {
                'status': 'failed',
                'message': f"Vault connectivity failed: {e}"
            }
    
    async def _record_state_recovery_status(self, recovery_report: Dict):
        """Record state recovery status in database for monitoring"""
        try:
            db_manager = await get_db_manager()
            
            # Record overall system recovery status
            await db_manager.record_health_check(
                component='system_state_recovery',
                status='healthy',  # FIXED: Use valid health status instead of 'completed'
                details={
                    'timestamp': datetime.utcnow().isoformat(),
                    'recovery_report': recovery_report,
                    'successful_components': sum(1 for r in recovery_report.values() if r['status'] == 'recovered'),
                    'total_components': len(recovery_report),
                    'system_ready': all(r['status'] in ['recovered', 'partial'] for r in recovery_report.values())
                }
            )
            
        except Exception as e:
            logger.warning(f"Failed to record state recovery status: {e}")


async def run_vault_system(args: Dict[str, Any]) -> None:
    """
    Run the Calvin AI Vault Trading System (Phase 3.2)
    
    This is the main entry point for the enhanced system with vault integration.
    """
    system = CalvinVaultSystem()
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, system.signal_handler)
    signal.signal(signal.SIGTERM, system.signal_handler)
    
    try:
        await system.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)
    finally:
        await system.shutdown()


async def train_model(args: Dict[str, Any]) -> None:
    """Train the ML model with historical data"""
    logger.info("Starting model training")
    
    # Validate token address
    if not args['token_address']:
        logger.error("Token address is required for training")
        return
    
    token_address = args['token_address']
    symbol = args.get('symbol', 'SOL')
    days = args.get('days', 30)
    resolution = args.get('resolution', '5m')
    
    # Initialize data processor
    data_processor = DataProcessor()
    
    # Get and process data
    logger.info(f"Fetching and processing data for {symbol} ({token_address}), {days} days, {resolution} resolution")
    df = data_processor.process_pipeline(
        token_address, 
        symbol, 
        resolution, 
        days, 
        save_data=True,
        include_sentiment=True  # Skip sentiment data for now
    )
    
    if df.empty:
        logger.error("No data available for training")
        return
    
    # Prepare data for ML
    sequence_length = args.get('sequence_length', 36)
    prediction_steps = args.get('prediction_horizon', 1)
    
    logger.info(f"Preparing ML data with sequence_length={sequence_length}, prediction_horizon={prediction_steps} steps")
    X_train, X_test, y_train, y_test = data_processor.prepare_ml_data(
        df, 
        target_col='close',
        sequence_length=sequence_length,
        prediction_horizon=prediction_steps,
        include_feature_names=False
    )
    
    logger.info(f"Data prepared: {X_train.shape[0]} training samples, {X_test.shape[0]} testing samples")
    
    # Initialize and train model
    model_type = args.get('model_type', config.model_type)
    ml_model = MLModel(model_type=model_type)
    
    # Check if we should use bidirectional LSTM
    use_bidirectional = args.get('bidirectional', True)
    
    # Build the model
    ml_model.build_model(input_shape=(X_train.shape[1], X_train.shape[2]), use_bidirectional=use_bidirectional)
    
    # Train the model
    epochs = args.get('epochs', 100)
    batch_size = args.get('batch_size', 32)
    
    # Enhanced model naming with simple versioning
    if not args.get('model_name'):
        timestamp = datetime.now().strftime("%Y%m%d")
        base_name = f"{symbol}_{model_type}"
        version = "v1.0.0"
        
        # Check for existing models today and increment patch version
        import glob
        existing_models = glob.glob(f"models/{base_name}_v1.0.*_{timestamp}.h5")
        if existing_models:
            # Extract patch numbers and increment
            patch_numbers = []
            for model_path in existing_models:
                try:
                    # Extract patch number from filename like "symbol_lstm_v1.0.X_date.h5"
                    parts = os.path.basename(model_path).split('_')
                    version_part = [p for p in parts if p.startswith('v1.0.')][0]
                    patch_num = int(version_part.split('.')[2])
                    patch_numbers.append(patch_num)
                except (IndexError, ValueError):
                    continue
            
            if patch_numbers:
                next_patch = max(patch_numbers) + 1
                version = f"v1.0.{next_patch}"
        
        model_name = f"{base_name}_{version}_{timestamp}"
    else:
        model_name = args.get('model_name')
    
    history = ml_model.train(
        X_train, y_train,
        X_test, y_test,
        epochs=epochs,
        batch_size=batch_size,
        model_name=model_name
    )
    
    # Evaluate the model - DISABLE the broken backtest like in testing
    metrics = ml_model.evaluate(X_test, y_test, include_backtest=False)  # FIXED: Disable broken backtest
    ml_model.save_evaluation_metrics(metrics, model_name)
    
    # Plot results if requested
    if args.get('plot', False):
        ml_model.plot_training_history(history, f"{model_name}_training_history.png")
        
        # Make predictions and plot
        y_pred = ml_model.predict(X_test)
        y_true = y_test
        
        # Convert predictions back to original scale
        y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
        y_true_orig = data_processor.inverse_transform_predictions(y_true, data_processor.prices_at_sequence_end_test)
        
        ml_model.plot_predictions(y_true_orig, y_pred_orig, f"{model_name}_predictions.png")
    
    logger.info(f"Model training completed: {model_name}")
    logger.info(f"Evaluation metrics: {metrics}")

async def test_model(args: Dict[str, Any]) -> None:
    """Test the trained model against historical data"""
    logger.info("Starting model testing")
    
    # Find the model to test
    model_path = args.get('model_path')
    if not model_path:
        # Look for latest model
        ml_model = MLModel()
        model_path = ml_model.get_latest_model_path()
        
        if not model_path:
            logger.error("No model found for testing")
            return
    
    logger.info(f"Testing model: {model_path}")
    
    # Load the model
    ml_model = MLModel()
    ml_model.load(model_path)
    
    # Get test data
    token_address = args.get('token_address')
    symbol = args.get('symbol', 'SOL')
    days = args.get('days', 10)  # Use fewer days for testing
    resolution = args.get('resolution', '15m')  # Add resolution parameter with default
    
    data_processor = DataProcessor()
    df = data_processor.process_pipeline(token_address, symbol, resolution, days, save_data=False)
    
    if df.empty:
        logger.error("No data available for testing")
        return
    
    # Prepare test data using a consistent dataframe
    sequence_length = args.get('sequence_length', 36)  # Should match the model's expected input
    prediction_steps = args.get('prediction_horizon', 1)  # Use 1 to match optimization script default
    
    logger.info(f"Testing with sequence_length={sequence_length}, prediction_horizon={prediction_steps} steps")
    
    df_for_ml = df.copy()  # Use consistent processed dataframe
    _, X_test, _, y_test = data_processor.prepare_ml_data(
        df_for_ml,  # Use the same dataframe consistently
        target_col='close',
        sequence_length=sequence_length,
        prediction_horizon=prediction_steps,
        test_size=0.2,  # Not used in test_mode, but keep for compatibility
        include_feature_names=False,
        test_mode=True  # Use test mode: fit scalers on entire dataset
    )
    
    # Evaluate model - get basic metrics only (no backtest)
    metrics = ml_model.evaluate(X_test, y_test, include_backtest=False)  # DISABLE old backtest - it uses normalized data
    logger.info(f"Test metrics: {metrics}")
    
    # Make predictions and convert back to original scale
    y_pred = ml_model.predict(X_test)
    # Use the stored prices from the data_processor for inverse transform
    y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
    # Similarly for y_test - need prices at the *start* of the prediction horizon
    # Let's recalculate y_test_orig from the original dataframe for simplicity here
    # We need the price at the step *before* the target step
    original_indices = df_for_ml.index[-(len(y_test)+prediction_steps-1):-(prediction_steps-1)] if prediction_steps > 1 else df_for_ml.index[-len(y_test):]
    base_prices_for_y_test = df_for_ml.loc[original_indices, 'close'].values
    # Get the original target pct changes (we didn't store these)
    target_pct_changes = data_processor.price_scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()
    y_true_orig = base_prices_for_y_test * (1 + target_pct_changes)
    
    logger.info("\n" + "="*70)
    logger.info("RUNNING BACKTEST WITH REAL PRICE DATA")
    logger.info("="*70)

    # Run ONLY our new simple backtest using the optimized strategy
    from src.model.profit_functions import simple_backtest_strategy
    backtest_results = simple_backtest_strategy(
        prices=y_true_orig,
        predictions=y_pred_orig,
        ohlcv_df=df_for_ml, # Use the SAME processed DataFrame for consistent calculations
        include_detailed_trades=True,
        verbosity=1,
        resolution=resolution,
        buy_threshold=0.02,  # Buy when predicted increase >= 2%
        sell_threshold=0.03  # Sell when predicted decrease >= 3%
    )
    
    # Log backtest results (only the new/correct ones)
    logger.info(f"Backtest Results:")
    logger.info(f"  Total Return: {backtest_results['Total Return']:.2f}%")
    logger.info(f"  Buy & Hold Return: {backtest_results['Buy & Hold Return']:.2f}%")
    logger.info(f"  Win Rate: {backtest_results['Win Rate']:.2f}%")
    logger.info(f"  Max Drawdown: {backtest_results['Max Drawdown']:.2f}%")
    logger.info(f"  Sharpe Ratio: {backtest_results['Sharpe Ratio']:.2f}")
    logger.info(f"  Total Trades: {backtest_results['Total Trades']}")
    logger.info(f"  Final Portfolio Value: ${backtest_results['Final Portfolio Value']:.2f}")
    
    # Plot if requested
    if args.get('plot', False):
        # Create model-specific plot names
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        model_base_name = f"{symbol}_lstm_test_{timestamp}"
        
        # Original prediction plots
        ml_model.plot_predictions(
            y_true_orig, 
            y_pred_orig, 
            f"{model_base_name}_predictions.png"
        )
        
        # Add the price comparison plot
        ml_model.plot_price_comparison(
            y_true_orig,
            y_pred_orig,
            f"{model_base_name}_price_comparison.png"
        )
        
        # NEW: Plot backtest with signals using the improved function
        from src.model.profit_functions import plot_backtest_with_signals
        
        # Use the REAL OHLCV data we already fetched, not fake data
        # Get the test period OHLCV data that corresponds to our predictions
        test_start_idx = len(df) - len(y_true_orig)
        real_ohlcv_df = df.iloc[test_start_idx:].copy()
        
        # DEBUG: Check original DataFrame structure
        logger.info(f"Original DataFrame index type: {type(df.index)}")
        logger.info(f"Original DataFrame index name: {df.index.name}")
        logger.info(f"Original DataFrame has timestamp column: {'timestamp' in df.columns}")
        logger.info(f"Original DataFrame columns containing 'time': {[col for col in df.columns if 'time' in col.lower()]}")
        
        # Ensure we have the required columns and proper indexing
        if len(real_ohlcv_df) == len(y_true_orig):
            # Reset index to avoid any issues and bring timestamp back as column if it's the index
            if real_ohlcv_df.index.name == 'timestamp' or 'timestamp' in str(type(real_ohlcv_df.index)):
                real_ohlcv_df = real_ohlcv_df.reset_index()
            else:
                real_ohlcv_df = real_ohlcv_df.reset_index(drop=True)
            
            # DEBUG: Check what columns we actually have
            logger.info(f"OHLCV DataFrame columns: {list(real_ohlcv_df.columns)}")
            logger.info(f"OHLCV DataFrame shape: {real_ohlcv_df.shape}")
            
            # Ensure timestamp column exists - if not, create one from index
            if 'timestamp' not in real_ohlcv_df.columns:
                # Check for common timestamp column names - but exclude sentiment data
                timestamp_cols = [col for col in real_ohlcv_df.columns 
                                if ('time' in col.lower() or 'date' in col.lower()) 
                                and 'sentiment' not in col.lower()]
                if timestamp_cols:
                    real_ohlcv_df['timestamp'] = real_ohlcv_df[timestamp_cols[0]]
                    logger.info(f"Using column '{timestamp_cols[0]}' as timestamp")
                else:
                    # Create timestamps from index (using the actual test period)
                    # Use the original DataFrame index as reference if available
                    test_start_idx = len(df) - len(y_true_orig)
                    if test_start_idx >= 0 and 'timestamp' in df.columns:
                        # Use actual timestamps from the original DataFrame
                        real_ohlcv_df['timestamp'] = df['timestamp'].iloc[test_start_idx:test_start_idx + len(y_true_orig)].values
                        logger.info("Using actual timestamps from original DataFrame")
                    else:
                        # Fall back to synthetic timestamps
                        start_time = datetime.now() - timedelta(hours=len(real_ohlcv_df))
                        real_ohlcv_df['timestamp'] = [start_time + timedelta(hours=i) for i in range(len(real_ohlcv_df))]
                        logger.info("Created synthetic timestamp column from index")
            
            # Plot backtest with signals using REAL market data
            plot_filename = f"{model_base_name}_backtest_signals.png"
            # Save to plots/backtests directory
            plots_dir = os.path.join(os.path.dirname(os.getcwd()), 'plots', 'backtests')
            os.makedirs(plots_dir, exist_ok=True)
            plot_path = plot_backtest_with_signals(
                ohlcv_data=real_ohlcv_df,
                trades=backtest_results.get('trades', []),
                filename=plot_filename,
                title=f"{symbol} Backtest Results - {resolution} Resolution (Real OHLCV)",
                output_dir=plots_dir
            )
            
            if plot_path:
                logger.info(f"Backtest visualization saved to: {plot_path}")
        else:
            logger.warning(f"OHLCV data length mismatch: {len(real_ohlcv_df)} vs predictions: {len(y_true_orig)}")
            logger.info("Skipping backtest visualization due to data mismatch")
    
    # Calculate price change accuracy
    correct_direction = 0
    for i in range(1, len(y_true_orig)):
        actual_change = y_true_orig[i] - y_true_orig[i-1]
        predicted_change = y_pred_orig[i] - y_true_orig[i-1]
        
        if (actual_change >= 0 and predicted_change >= 0) or (actual_change < 0 and predicted_change < 0):
            correct_direction += 1
    
    direction_accuracy = correct_direction / (len(y_true_orig) - 1) if len(y_true_orig) > 1 else 0
    logger.info(f"Price direction accuracy: {direction_accuracy:.2%}")

async def run_trading_bot(args: Dict[str, Any]) -> None:
    """Run the trading bot"""
    logger.info("Starting trading bot")
    
    # Validate required parameters
    token_address = args.get('token_address')
    if not token_address:
        logger.error("Token address is required for trading")
        return
    
    symbol = args.get('symbol', 'SOL')
    model_path = args.get('model_path')
    
    # Initialize wallet
    wallet = SolanaWallet()
    balance = wallet.get_balance()
    logger.info(f"Wallet initialized: {wallet.public_key}")
    logger.info(f"Wallet balance: {balance} SOL")
    
    # Initialize trading strategy
    strategy = TradingStrategy(
        token_address=token_address,
        symbol=symbol,
        model_path=model_path,
        wallet=wallet
    )
    
    # Run strategy with specified interval
    interval_minutes = args.get('interval', config.trading_interval_minutes)
    await strategy.run(interval_minutes=interval_minutes)

async def create_wallet(args: Dict[str, Any]) -> None:
    """Create a new Solana wallet"""
    logger.info("Creating new Solana wallet")
    
    # Create wallet
    wallet = SolanaWallet()
    
    # Save wallet information (for development only)
    save_path = args.get('save_path', 'wallet.json')
    wallet.save_wallet_info(save_path)
    
    logger.info(f"New wallet created: {wallet.public_key}")
    logger.info(f"Wallet information saved to: {save_path}")
    logger.info("IMPORTANT: Store this file securely and never share your private key!")

async def get_token_info(args: Dict[str, Any]) -> None:
    """Get information about a token"""
    logger.info("Fetching token information")
    
    from src.data.birdeye_api import BirdEyeAPI
    from src.data.helius_api import HeliusAPI
    
    token_address = args.get('token_address')
    if not token_address:
        logger.error("Token address is required")
        return
    
    # Get info from BirdEye
    try:
        birdeye = BirdEyeAPI()
        price_data = birdeye.get_token_price(token_address)
        metadata = birdeye.get_token_metadata(token_address)
        
        print("\n===== Token Information =====")
        if 'data' in metadata:
            token_data = metadata['data']
            print(f"Name: {token_data.get('name', 'Unknown')}")
            print(f"Symbol: {token_data.get('symbol', 'Unknown')}")
            print(f"Decimals: {token_data.get('decimals', 'Unknown')}")
            
            # Check if we have extensions data in the v3 API format
            if 'extensions' in token_data:
                ext = token_data['extensions']
                if ext.get('website'):
                    print(f"Website: {ext['website']}")
                if ext.get('twitter'):
                    print(f"Twitter: {ext['twitter']}")
                if ext.get('description'):
                    print(f"Description: {ext['description']}")
        
        if 'data' in price_data and 'value' in price_data['data']:
            print(f"Price: ${float(price_data['data']['value']):.6f}")
        
        # Get more data
        print("\n===== Market Data =====")
        ohlcv = birdeye.get_token_ohlcv(token_address, "1d", 1)
        if not ohlcv.empty:
            print(f"24h Volume: ${ohlcv['volume'].iloc[0]:.2f}")
            print(f"24h High: ${ohlcv['high'].iloc[0]:.6f}")
            print(f"24h Low: ${ohlcv['low'].iloc[0]:.6f}")
    
    except Exception as e:
        logger.error(f"Error getting token info: {e}")

async def plot_price_comparison_cmd(args: Dict[str, Any]) -> None:
    """Generate a plot showing actual vs predicted closing prices for a specific model"""
    logger.info("Generating price comparison plot")
    
    # Find the model to use
    model_path = args.get('model_path')
    if not model_path:
        # Look for latest model
        ml_model = MLModel()
        model_path = ml_model.get_latest_model_path()
        
        if not model_path:
            logger.error("No model found for generating plot")
            return
    
    logger.info(f"Using model: {model_path}")
    
    # Load the model
    ml_model = MLModel()
    ml_model.load(model_path)
    
    # Get data for the plot
    token_address = args.get('token_address')
    symbol = args.get('symbol', 'SOL')
    days = args.get('days', 30)
    resolution = args.get('resolution', '1H')
    
    data_processor = DataProcessor()
    df = data_processor.process_pipeline(token_address, symbol, resolution, days, save_data=False)
    
    if df.empty:
        logger.error("No data available for plotting")
        return
    
    # Prepare test data
    sequence_length = args.get('sequence_length', 36)
    prediction_steps = args.get('prediction_horizon', 1)
    
    logger.info(f"Preparing data with sequence_length={sequence_length}, prediction_horizon={prediction_steps} steps")
    
    _, X_test, _, y_test = data_processor.prepare_ml_data(
        df, 
        target_col='close',
        sequence_length=sequence_length,
        prediction_horizon=prediction_steps,
        test_size=0.8,  # Use most of the data for testing
        include_feature_names=False
    )
    
    # Make predictions
    y_pred = ml_model.predict(X_test)
    
    # Transform predictions back to original scale
    # Use the stored prices from the data_processor for inverse transform
    y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
    # Recalculate y_test_orig from original df
    original_indices = df.index[-(len(y_test)+prediction_steps-1):-(prediction_steps-1)] if prediction_steps > 1 else df.index[-len(y_test):]
    base_prices_for_y_test = df.loc[original_indices, 'close'].values
    target_pct_changes = data_processor.price_scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()
    y_test_orig = base_prices_for_y_test * (1 + target_pct_changes)
    
    # Generate the price comparison plot
    output_file = args.get('output_file', f"{symbol}_price_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    ml_model.plot_price_comparison(y_test_orig, y_pred_orig, output_file)
    
    logger.info(f"Price comparison plot generated: {output_file}")


def run_api_server(args: Dict[str, Any]) -> None:
    """Run the Calvin AI Trades API server for frontend integration"""
    logger.info("🚀 Starting Calvin AI Trades API Server")
    
    try:
        # Import uvicorn here to avoid import issues if not needed
        import uvicorn
        
        # Get configuration from arguments
        host = args.get('host', '0.0.0.0')
        port = args.get('port', 8000)
        reload = args.get('reload', False)
        log_level = args.get('log_level', 'info')
        
        logger.info(f"🌐 Server configuration:")
        logger.info(f"   Host: {host}")
        logger.info(f"   Port: {port}")
        logger.info(f"   Reload: {reload}")
        logger.info(f"   Log Level: {log_level}")
        
        # Run the FastAPI server (uvicorn.run creates its own event loop)
        uvicorn.run(
            "api_server:app",
            host=host,
            port=port,
            reload=reload,
            log_level=log_level,
            access_log=True
        )
        
    except ImportError:
        logger.error("❌ FastAPI/Uvicorn not installed. Install with: pip install fastapi uvicorn[standard]")
        raise
    except Exception as e:
        logger.error(f"❌ Failed to start API server: {e}")
        raise


def parse_arguments():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description="Solana Trading Bot")
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Train model command
    train_parser = subparsers.add_parser('train', help='Train the ML model')
    train_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to train on')
    train_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    train_parser.add_argument('--days', type=int, default=30, help='Number of days of historical data to use')
    train_parser.add_argument('--resolution', type=str, default='1H', help='Data resolution (1m, 5m, 15m, 1H, 4H, 1D)')
    train_parser.add_argument('--model-type', type=str, default=config.model_type, help='Type of ML model to use')
    train_parser.add_argument('--sequence-length', type=int, default=36, help='Number of time steps in each input sequence')
    train_parser.add_argument('--prediction-horizon', type=int, default=1, help='Number of time steps in the future to predict')
    train_parser.add_argument('--epochs', type=int, default=100, help='Number of training epochs')
    train_parser.add_argument('--batch-size', type=int, default=64, help='Training batch size')
    train_parser.add_argument('--plot', action='store_true', help='Plot training results')
    train_parser.add_argument('--bidirectional', action='store_true', default=True, help='Use bidirectional LSTM')
    train_parser.add_argument('--no-bidirectional', dest='bidirectional', action='store_false', help='Disable bidirectional LSTM')
    
    
    test_parser = subparsers.add_parser('test', help='Test the ML model')
    test_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to test on')
    test_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    test_parser.add_argument('--model-path', type=str, help='Path to the model to test')
    test_parser.add_argument('--days', type=int, default=10, help='Number of days of historical data to use')
    test_parser.add_argument('--resolution', type=str, default='1H', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    test_parser.add_argument('--sequence-length', type=int, default=36, help='Number of time steps in each input sequence')
    test_parser.add_argument('--prediction-horizon', type=int, default=1, help='Number of time steps in the future to predict')
    test_parser.add_argument('--plot', action='store_true', help='Plot test results')
    
    # Run trading bot command
    run_parser = subparsers.add_parser('run', help='Run the trading bot')
    run_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to trade')
    run_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    run_parser.add_argument('--model-path', type=str, help='Path to the ML model to use')
    run_parser.add_argument('--interval', type=int, help='Trading interval in minutes')
    
    # Create wallet command
    wallet_parser = subparsers.add_parser('create-wallet', help='Create a new Solana wallet')
    wallet_parser.add_argument('--save-path', type=str, default='wallet.json', help='Path to save wallet information')
    
    # Get token info command
    info_parser = subparsers.add_parser('token-info', help='Get information about a token')
    info_parser.add_argument('--token-address', type=str, required=True, help='Address of the token to get info about')
    
    # Add plot-prices command
    plot_prices_parser = subparsers.add_parser('plot-prices', help='Generate a price comparison plot')
    plot_prices_parser.add_argument('--token-address', type=str, required=True, help='Address of the token')
    plot_prices_parser.add_argument('--symbol', type=str, default='SOL', help='Symbol of the token')
    plot_prices_parser.add_argument('--model-path', type=str, help='Path to the model to use')
    plot_prices_parser.add_argument('--days', type=int, default=30, help='Number of days of historical data to use')
    plot_prices_parser.add_argument('--resolution', type=str, default='1h', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    plot_prices_parser.add_argument('--sequence-length', type=int, default=36, help='Number of time steps in each input sequence')
    plot_prices_parser.add_argument('--prediction-horizon', type=int, default=1, help='Number of time steps in the future to predict')
    plot_prices_parser.add_argument('--output-file', type=str, help='Output filename for the plot')
    
    # NEW: Phase 3.2 - Vault Trading System command
    vault_system_parser = subparsers.add_parser('run-vault-system', help='Run the Calvin AI Vault Trading System (Phase 3.2)')
    vault_system_parser.add_argument('--config-file', type=str, help='Optional configuration file path')
    vault_system_parser.add_argument('--log-level', type=str, default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging level')
    vault_system_parser.add_argument('--simulation-mode', action='store_true', help='Force simulation mode even if vault clients are available')
    vault_system_parser.add_argument('--ohlcv-interval', type=int, default=60, help='OHLCV data fetch interval in minutes')
    vault_system_parser.add_argument('--social-interval', type=int, default=60, help='Social data fetch interval in minutes (hourly for model features)')
    vault_system_parser.add_argument('--min-viable-tokens', type=int, default=5, help='Minimum tokens ready for inference to trigger trading')
    
    # NEW: API Server command for frontend integration
    api_server_parser = subparsers.add_parser('run-api-server', help='Run the Calvin AI Trades API server for frontend integration')
    api_server_parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind the API server to')
    api_server_parser.add_argument('--port', type=int, default=8000, help='Port to bind the API server to')
    api_server_parser.add_argument('--reload', action='store_true', help='Enable auto-reload for development')
    api_server_parser.add_argument('--log-level', type=str, default='info', choices=['debug', 'info', 'warning', 'error'], help='Logging level')
    
    return parser.parse_args()

def main():
    """Main entry point for the application"""
    args = parse_arguments()
    
    # Convert arguments to dictionary
    args_dict = vars(args)
    command = args.command
    
    # Run appropriate function based on command
    try:
        if command == 'train':
            asyncio.run(train_model(args_dict))
        elif command == 'test':
            asyncio.run(test_model(args_dict))
        elif command == 'run':
            asyncio.run(run_trading_bot(args_dict))
        elif command == 'create-wallet':
            asyncio.run(create_wallet(args_dict))
        elif command == 'token-info':
            asyncio.run(get_token_info(args_dict))
        elif command == 'plot-prices':
            asyncio.run(plot_price_comparison_cmd(args_dict))
        elif command == 'run-vault-system':
            asyncio.run(run_vault_system(args_dict))
        elif command == 'run-api-server':
            run_api_server(args_dict)  # No asyncio.run() needed - uvicorn creates its own event loop
        else:
            logger.error(f"Unknown command: {command}")
    except KeyboardInterrupt:
        logger.info("Program interrupted by user")
    except Exception as e:
        logger.error(f"Error running command {command}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
