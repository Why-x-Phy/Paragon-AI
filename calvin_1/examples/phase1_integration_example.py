#!/usr/bin/env python3
"""
Calvin AI Phase 1 Integration Example

Demonstrates how to integrate all Phase 1 components:
- Production Database (TimescaleDB + Redis)
- Real-time Data Storage (WebSocket feeds)
- Hourly Inference Scheduler (OHLCV + Social data)
- Position Management System (Risk management + P&L tracking)

Usage:
    python calvin_1/examples/phase1_integration_example.py
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from calvin_1.src.database.production_db import get_db_manager
from calvin_1.src.data.websocket_feed import WebSocketPriceFeed, SubscriptionConfig
from calvin_1.src.data.realtime_storage import RealtimeDataStorage
from calvin_1.src.data.hourly_inference_scheduler import get_inference_scheduler, InferenceScheduleConfig
from calvin_1.src.trading.position_manager import (
    get_position_manager, 
    PositionType, 
    RiskLimits,
    PositionAlert
)
from calvin_1.src.config import get_config


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CalvinPhase1System:
    """
    Integrated Calvin AI Phase 1 System
    
    Coordinates all Phase 1 components for a complete trading data infrastructure.
    """
    
    def __init__(self):
        self.config = get_config()
        self.logger = logging.getLogger(__name__)
        
        # Component instances
        self.db_manager = None
        self.websocket_feed = None
        self.realtime_storage = None
        self.inference_scheduler = None
        self.position_manager = None
        
        # State
        self.is_running = False
        self.shutdown_event = asyncio.Event()
        
    async def initialize(self):
        """Initialize all system components"""
        try:
            self.logger.info("Initializing Calvin AI Phase 1 System...")
            
            # 1. Initialize Production Database
            self.logger.info("1. Initializing production database...")
            self.db_manager = await get_db_manager()
            self.logger.info("✅ Database initialized")
            
            # 2. Initialize WebSocket Price Feed
            self.logger.info("2. Initializing WebSocket price feed...")
            api_key = self.config.get('BIRDEYE_API_KEY')
            if not api_key:
                raise ValueError("BIRDEYE_API_KEY not found in configuration")
            
            self.websocket_feed = WebSocketPriceFeed(
                api_key=api_key,
                chain="solana"
            )
            self.logger.info("✅ WebSocket feed initialized")
            
            # 3. Initialize Real-time Data Storage
            self.logger.info("3. Initializing real-time data storage...")
            self.realtime_storage = RealtimeDataStorage(
                websocket_feed=self.websocket_feed,
                db_manager=self.db_manager
            )
            await self.realtime_storage.initialize()
            self.logger.info("✅ Real-time storage initialized")
            
            # 4. Initialize Hourly Inference Scheduler
            self.logger.info("4. Initializing hourly inference scheduler...")
            scheduler_config = InferenceScheduleConfig(
                ohlcv_interval_minutes=60,  # Every hour
                social_interval_minutes=180,  # Every 3 hours
                active_tokens=[
                    'So11111111111111111111111111111111111111112',  # SOL
                    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                    'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # BONK
                    'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',  # JUP
                ]
            )
            self.inference_scheduler = await get_inference_scheduler(scheduler_config)
            self.logger.info("✅ Inference scheduler initialized")
            
            # 5. Initialize Position Manager
            self.logger.info("5. Initializing position manager...")
            risk_limits = RiskLimits(
                max_position_size_usdc=float(self.config.get('POSITION_MAX_SIZE_USDC', 10000.0)),
                max_portfolio_exposure_pct=float(self.config.get('PORTFOLIO_MAX_EXPOSURE_PCT', 80.0)),
                max_single_token_exposure_pct=float(self.config.get('TOKEN_MAX_EXPOSURE_PCT', 20.0)),
                max_daily_loss_usdc=float(self.config.get('MAX_DAILY_LOSS_USDC', 1000.0)),
                default_stop_loss_pct=float(self.config.get('DEFAULT_STOP_LOSS_PCT', 5.0)),
                default_take_profit_pct=float(self.config.get('DEFAULT_TAKE_PROFIT_PCT', 10.0))
            )
            
            self.position_manager = await get_position_manager(
                db_manager=self.db_manager,
                realtime_storage=self.realtime_storage,
                risk_limits=risk_limits
            )
            
            # Set up alert callback
            self.position_manager.add_alert_callback(self._handle_position_alert)
            self.logger.info("✅ Position manager initialized")
            
            self.logger.info("🚀 Calvin AI Phase 1 System fully initialized!")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize system: {e}")
            raise
    
    async def start(self):
        """Start all system components"""
        if self.is_running:
            self.logger.warning("System already running")
            return
            
        try:
            self.logger.info("Starting Calvin AI Phase 1 System...")
            self.is_running = True
            
            # 1. Start Real-time Data Storage (includes WebSocket)
            self.logger.info("Starting real-time data storage...")
            await self.realtime_storage.start()
            
            # 2. Start Position Manager
            self.logger.info("Starting position manager...")
            await self.position_manager.start()
            
            # 3. Start Hourly Inference Scheduler
            self.logger.info("Starting inference scheduler...")
            self.inference_scheduler.start_scheduler()
            
            # 4. Subscribe to token price feeds
            await self._setup_price_subscriptions()
            
            self.logger.info("🎯 All systems operational!")
            
            # Start monitoring task
            asyncio.create_task(self._monitoring_task())
            
        except Exception as e:
            self.logger.error(f"Failed to start system: {e}")
            self.is_running = False
            raise
    
    async def _setup_price_subscriptions(self):
        """Subscribe to price feeds for active tokens"""
        try:
            # Get active token addresses from database
            active_tokens = []
            query = "SELECT address FROM tokens WHERE is_active = true"
            
            async with self.db_manager.pg_pool.acquire() as conn:
                rows = await conn.fetch(query)
                active_tokens = [row['address'] for row in rows]
            
            if not active_tokens:
                self.logger.warning("No active tokens found, using defaults")
                active_tokens = [
                    'So11111111111111111111111111111111111111112',  # SOL
                    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                ]
            
            # Subscribe to price updates
            for token_address in active_tokens:
                config = SubscriptionConfig(
                    subscription_type="SUBSCRIBE_PRICE",
                    addresses=[token_address]
                )
                await self.websocket_feed.subscribe(config)
                self.logger.info(f"Subscribed to price feed for {token_address}")
            
        except Exception as e:
            self.logger.error(f"Failed to setup price subscriptions: {e}")
    
    async def _handle_position_alert(self, alert: PositionAlert):
        """Handle position alerts"""
        self.logger.warning(f"POSITION ALERT: {alert.message}")
        
        # In a real system, you might:
        # - Send notifications (Discord, email, SMS)
        # - Take automated actions
        # - Log to external monitoring systems
        
        if alert.severity == 'critical':
            self.logger.critical(f"CRITICAL ALERT: {alert.message}")
    
    async def _monitoring_task(self):
        """Background monitoring task"""
        while self.is_running:
            try:
                # Print system status every 60 seconds
                await asyncio.sleep(60)
                await self._print_system_status()
                
            except Exception as e:
                self.logger.error(f"Error in monitoring task: {e}")
                await asyncio.sleep(60)
    
    async def _print_system_status(self):
        """Print current system status"""
        try:
            # Get statistics from all components
            realtime_stats = self.realtime_storage.get_statistics()
            scheduler_stats = self.inference_scheduler.get_statistics()
            position_stats = self.position_manager.get_statistics()
            
            # Get portfolio P&L
            portfolio_pnl = await self.position_manager.get_portfolio_pnl()
            
            self.logger.info("=== SYSTEM STATUS ===")
            self.logger.info(f"Real-time: {realtime_stats['ticks_processed']} ticks, {realtime_stats['candles_created']} candles")
            self.logger.info(f"Scheduler: {scheduler_stats['ohlcv_runs']} OHLCV runs, {scheduler_stats['social_runs']} social runs")
            self.logger.info(f"Positions: {position_stats['active_positions']} active, Daily P&L: ${position_stats['daily_pnl']:.2f}")
            self.logger.info(f"Portfolio: Total P&L: ${portfolio_pnl.get('combined_pnl', 0):.2f}")
            
        except Exception as e:
            self.logger.error(f"Error printing system status: {e}")
    
    async def stop(self):
        """Stop all system components gracefully"""
        if not self.is_running:
            return
            
        try:
            self.logger.info("Stopping Calvin AI Phase 1 System...")
            self.is_running = False
            
            # Stop components in reverse order
            if self.inference_scheduler:
                self.inference_scheduler.stop_scheduler()
                self.logger.info("Inference scheduler stopped")
            
            if self.position_manager:
                await self.position_manager.stop()
                self.logger.info("Position manager stopped")
            
            if self.realtime_storage:
                await self.realtime_storage.stop()
                self.logger.info("Real-time storage stopped")
            
            if self.db_manager:
                await self.db_manager.close()
                self.logger.info("Database connections closed")
            
            self.logger.info("✅ System shutdown complete")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
    
    # =========================================================================
    # DEMO OPERATIONS
    # =========================================================================
    
    async def demo_position_lifecycle(self):
        """Demonstrate position management lifecycle"""
        try:
            self.logger.info("=== DEMO: Position Lifecycle ===")
            
            # Get SOL token info
            sol_token = self.db_manager.get_token_by_address(
                'So11111111111111111111111111111111111111112'
            )
            if not sol_token:
                self.logger.error("SOL token not found in database")
                return
            
            # Get current SOL price
            current_price = await self.db_manager.get_latest_price(sol_token.token_id)
            if not current_price:
                self.logger.error("No current price for SOL")
                return
            
            self.logger.info(f"Current SOL price: ${current_price:.2f}")
            
            # Open a demo position
            position_id = await self.position_manager.open_position(
                token_id=sol_token.token_id,
                position_type=PositionType.LONG,
                entry_price=current_price,
                quantity=1.0,  # 1 SOL
                stop_loss_pct=5.0,  # 5% stop loss
                take_profit_pct=10.0,  # 10% take profit
                model_confidence=0.85,
                model_version="demo_v1",
                tx_hash="demo_tx_hash_123"
            )
            
            self.logger.info(f"Opened demo position {position_id}")
            
            # Wait a bit and check unrealized P&L
            await asyncio.sleep(5)
            
            pnl_info = await self.position_manager.calculate_unrealized_pnl(position_id)
            if pnl_info:
                self.logger.info(f"Unrealized P&L: ${pnl_info['realized_pnl']:.2f} ({pnl_info['pnl_percentage']:.2f}%)")
            
            # Close the demo position
            close_result = await self.position_manager.close_position(
                position_id=position_id,
                exit_price=current_price * 1.02,  # 2% profit
                reason="demo_close",
                tx_hash="demo_close_tx_123"
            )
            
            self.logger.info(f"Closed position with P&L: ${close_result['realized_pnl']:.2f}")
            
        except Exception as e:
            self.logger.error(f"Error in demo position lifecycle: {e}")
    
    async def demo_data_operations(self):
        """Demonstrate data operations"""
        try:
            self.logger.info("=== DEMO: Data Operations ===")
            
            # Manual OHLCV fetch
            self.logger.info("Triggering manual OHLCV fetch...")
            ohlcv_result = await self.inference_scheduler.manual_ohlcv_fetch(
                'So11111111111111111111111111111111111111112'  # SOL
            )
            self.logger.info(f"OHLCV fetch result: {ohlcv_result}")
            
            # Get recent data for inference
            sol_token = self.db_manager.get_token_by_address(
                'So11111111111111111111111111111111111111112'
            )
            if sol_token:
                inference_data = await self.inference_scheduler.prepare_inference_data(
                    sol_token.token_id
                )
                if inference_data:
                    self.logger.info(f"Prepared inference data: {len(inference_data['ohlcv_features'])} features")
                    self.logger.info(f"Data quality: {inference_data['data_quality']}")
                    self.logger.info(f"Ready for inference: {inference_data['ready_for_inference']}")
            
        except Exception as e:
            self.logger.error(f"Error in demo data operations: {e}")


async def main():
    """Main function"""
    # Set up signal handling for graceful shutdown
    system = CalvinPhase1System()
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(system.stop())
        system.shutdown_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Initialize system
        await system.initialize()
        
        # Start system
        await system.start()
        
        # Run demos
        await asyncio.sleep(5)  # Let system settle
        await system.demo_data_operations()
        await system.demo_position_lifecycle()
        
        # Keep running until shutdown signal
        logger.info("System running... Press Ctrl+C to stop")
        await system.shutdown_event.wait()
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"System error: {e}")
    finally:
        await system.stop()


if __name__ == "__main__":
    # Run the system
    asyncio.run(main()) 