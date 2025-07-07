"""
Calvin AI Hourly Inference Data Scheduler

Enhanced for Phase 3.2: Vault Trading Integration
- Integrates existing data fetching with portfolio signal generation
- Executes vault trades based on LSTM predictions and portfolio coordination
- Stores vault trading cycle data in TimescaleDB for monitoring and analysis
- Fetches social data hourly to maintain model feature consistency (~70 social features)
"""

import asyncio
import json
import schedule
import time
import subprocess
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import os

from ..database.production_db import get_db_manager, ProductionDBManager
from ..config.config import config as app_config
from ..utils.logger import log_manager


@dataclass
class InferenceScheduleConfig:
    """Configuration for inference data scheduling"""
    # UPDATED: Data fetch timing (1 min after hour for fresh data)
    ohlcv_interval_minutes: int = 60  # Every hour
    ohlcv_fetch_delay_seconds: int = 60  # Wait 60 seconds after hour for fresh data
    ohlcv_lookback_hours: int = 48   # Get last 48 hours from API (freshness buffer)
    ohlcv_inference_lookback_hours: int = 360  # Total data needed for inference (15 days)
    ohlcv_resolution: str = "1H"     # Hourly resolution for inference
    
    # UPDATED: Social data timing (1 min after hour, same as OHLCV)
    social_interval_minutes: int = 60   # Every hour for model feature consistency
    social_fetch_delay_seconds: int = 60  # Wait 60 seconds after hour
    social_lookback_days: int = 3      # Get last 3 days from API (freshness)
    social_inference_lookback_days: int = 7  # Total social data needed for inference
    social_resolution: str = "1d"      # Daily social data
    
    # NEW: Adaptive strategy timing (5 min before hour)
    adaptive_strategy_enabled: bool = True
    adaptive_strategy_offset_minutes: int = -5  # Run 5 minutes before hour (XX:55)
    
    # Token management
    active_tokens: List[str] = field(default_factory=list)  # Token addresses
    
    # Infrastructure settings
    max_retries: int = 3
    retry_delay_minutes: int = 5
    health_check_interval_minutes: int = 15
    
    # Trading execution settings
    min_viable_tokens: int = 0  # Minimum tokens ready for inference to trigger trading (lowered for testing)


class HourlyInferenceScheduler:
    """
    Enhanced Inference Scheduler with Vault Trading Integration (Phase 3.2)
    
    Coordinates scheduled data fetching for model inference AND executes vault trades:
    - Uses existing proven scripts for data fetching
    - Integrates with portfolio coordinator for signal generation  
    - Executes trades through Calvin vault smart contracts
    - Records all trading cycle data in TimescaleDB
    """
    
    def __init__(self, config: Optional[InferenceScheduleConfig] = None, db_manager: Optional[ProductionDBManager] = None):
        self.config = config or InferenceScheduleConfig()
        self.db_manager = db_manager  # Will be set during initialization
        self.logger = log_manager.get_logger("hourly_inference_scheduler")
        
        # Paths to existing scripts
        self.scripts_dir = Path(__file__).parent.parent / "scripts"
        self.historical_script = self.scripts_dir / "fetch_historical_data.py"
        self.social_script = self.scripts_dir / "fetch_social_data.py"
        
        # Verify scripts exist
        if not self.historical_script.exists():
            raise FileNotFoundError(f"Historical data script not found: {self.historical_script}")
        if not self.social_script.exists():
            raise FileNotFoundError(f"Social data script not found: {self.social_script}")
        
        # Scheduler state
        self.is_running = False
        self.scheduler_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        # Statistics - ENHANCED for Phase 3.2
        self.stats = {
            'ohlcv_runs': 0,
            'social_runs': 0,
            'inference_trading_cycles': 0,  # NEW: Track complete cycles
            'vault_trades_executed': 0,     # NEW: Track vault trades
            'total_errors': 0,
            'last_ohlcv_run': None,
            'last_social_run': None,
            'last_trading_cycle': None,     # NEW: Track last complete cycle
            'start_time': datetime.utcnow()
        }
    
    async def _ensure_thread_db_manager(self):
        """Ensure we have a thread-local database manager for isolated operations"""
        try:
            # Check if we're in a different event loop than where db_manager was created
            current_loop = asyncio.get_event_loop()
            
            # If db_manager doesn't have a loop attribute or it's different, create new one
            if not hasattr(self.db_manager, '_loop') or self.db_manager._loop != current_loop:
                self.logger.debug("Creating thread-local database manager for isolated operations")
                
                # Import here to avoid circular imports
                from ..database.production_db import ProductionDBManager
                
                # Create new database manager for this thread/loop
                thread_db_manager = ProductionDBManager()
                await thread_db_manager.initialize()
                
                # Store the loop reference
                thread_db_manager._loop = current_loop
                
                # Store original and use thread-local
                if not hasattr(self, '_original_db_manager'):
                    self._original_db_manager = self.db_manager
                self.db_manager = thread_db_manager
                
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error ensuring thread DB manager: {e}")
            return False
    
    async def _restore_original_db_manager(self):
        """Restore original database manager and clean up thread-local one"""
        try:
            if hasattr(self, '_original_db_manager'):
                # Close thread-local manager if different
                if self.db_manager != self._original_db_manager:
                    try:
                        await self.db_manager.close()
                    except Exception as e:
                        self.logger.debug(f"Error closing thread-local DB manager: {e}")
                
                # Restore original
                self.db_manager = self._original_db_manager
                delattr(self, '_original_db_manager')
        except Exception as e:
            self.logger.error(f"Error restoring DB manager: {e}")
        
    async def initialize(self):
        """Initialize the inference scheduler"""
        try:
            self.logger.info("🔄 Initializing inference scheduler...")
            
            # Initialize database manager if not provided
            if self.db_manager is None:
                self.logger.info("📊 Initializing database manager...")
                self.db_manager = await get_db_manager()
                self.logger.info("✅ Database manager initialized")
            
            # Load active tokens if not configured
            if not self.config.active_tokens:
                self.logger.info("🔍 Loading active tokens...")
                await self._load_active_tokens()
                self.logger.info("✅ Active tokens loaded")
            else:
                self.logger.info(f"📋 Using pre-configured {len(self.config.active_tokens)} tokens")
            
            self.logger.info(f"✅ Inference scheduler initialized for {len(self.config.active_tokens)} tokens")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize inference scheduler: {e}")
            raise
    
    async def _load_active_tokens(self):
        """Load active token addresses from database with timeout and fallback"""
        self.logger.info("🔄 Loading active tokens from database...")
        
        try:
            # Add timeout to prevent hanging
            import asyncio
            query = "SELECT address FROM tokens WHERE is_active = true"
            
            # Use a timeout to prevent hanging
            async def fetch_with_timeout():
                async with self.db_manager.pg_pool.acquire() as conn:
                    return await conn.fetch(query)
            
            rows = await asyncio.wait_for(fetch_with_timeout(), timeout=10.0)
            
            self.config.active_tokens = [row['address'] for row in rows]
            
            self.logger.info(f"✅ Loaded {len(self.config.active_tokens)} active tokens from database")
            if len(self.config.active_tokens) > 0:
                self.logger.info(f"📋 First 5 tokens: {[addr[:8]+'...' for addr in self.config.active_tokens[:5]]}")
            else:
                self.logger.warning("⚠️ No active tokens found in database - falling back to environment tokens")
                self._load_fallback_tokens()
            
        except asyncio.TimeoutError:
            self.logger.error("❌ Database token query timed out after 10 seconds - using fallback tokens")
            self._load_fallback_tokens()
        except Exception as e:
            self.logger.error(f"❌ Failed to load active tokens from database: {e}")
            self._load_fallback_tokens()
    
    def _load_fallback_tokens(self):
        """Load fallback tokens from environment variable"""
        import os
        tracked_tokens = os.getenv('TRACKED_TOKENS', '')
        if tracked_tokens:
            self.config.active_tokens = [token.strip() for token in tracked_tokens.split(',') if token.strip()]
            self.logger.info(f"✅ Using {len(self.config.active_tokens)} tokens from TRACKED_TOKENS env var")
            self.logger.info(f"📋 First 5 tokens: {[addr[:8]+'...' for addr in self.config.active_tokens[:5]]}")
        else:
            # Final fallback to default tokens
            self.config.active_tokens = [
                'So11111111111111111111111111111111111111112',  # SOL
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC  
                'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # BONK
                'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',  # JUP
            ]
            self.logger.warning("⚠️ Using minimal fallback tokens (4 tokens)")
    
    def start_scheduler(self):
        """Start the enhanced inference data scheduler with optimized timing"""
        self.logger.info("🔄 start_scheduler() called...")
        
        if self.is_running:
            self.logger.warning("Inference scheduler already running")
            return
            
        try:
            self.logger.info("🔄 Setting is_running = True...")
            self.is_running = True
            self.stop_event.clear()
            
            # 🕐 NEW TIMING SCHEDULE
            # XX:55 - Adaptive Strategy Updates (5 min before hour)
            # XX:01 - Data Fetch + Inference + Trading (1 min after hour for fresh data)
            
            if self.config.adaptive_strategy_enabled:
                # Schedule adaptive strategy updates 5 minutes before each hour
                schedule.every().hour.at(":55").do(self._run_adaptive_strategy_updates)
                self.logger.info("📊 Adaptive strategy: XX:55 (5 min before trading)")
            
            # Schedule data fetch + inference + trading 1 minute after each hour
            schedule.every().hour.at(":01").do(self._run_data_and_trading_cycle)
            self.logger.info("🚀 Data + Trading: XX:01 (60s buffer for fresh data)")
            
            # Health checks remain the same
            schedule.every(self.config.health_check_interval_minutes).minutes.do(
                self._run_health_check
            )
            
            # Start scheduler thread
            self.scheduler_thread = threading.Thread(target=self._scheduler_loop)
            self.scheduler_thread.daemon = True
            self.scheduler_thread.start()
            
            self.logger.info("🚀 Enhanced inference scheduler started with optimized timing")
            self.logger.info("⏰ Schedule:")
            if self.config.adaptive_strategy_enabled:
                self.logger.info("   XX:55 - Adaptive strategy parameter updates")
            self.logger.info("   XX:01 - Fresh data fetch + LSTM inference + vault trading")
            self.logger.info(f"   Every {self.config.health_check_interval_minutes}min - Health checks")
            
            # 🕐 TIMING INFO: Show when next cycle will run
            current_time = datetime.now()
            minutes_after_hour = current_time.minute
            
            self.logger.info(f"🕐 Current time: {current_time.strftime('%H:%M')} (minutes after hour: {minutes_after_hour})")
            
            # Calculate next run times
            if minutes_after_hour < 1:
                next_data_run = "in a few minutes (XX:01)"
            else:
                next_hour = (current_time.hour + 1) % 24
                next_data_run = f"at {next_hour:02d}:01"
            
            if self.config.adaptive_strategy_enabled:
                if minutes_after_hour < 55:
                    next_adaptive_run = f"at {current_time.hour:02d}:55"
                else:
                    next_hour = (current_time.hour + 1) % 24
                    next_adaptive_run = f"at {next_hour:02d}:55"
                self.logger.info(f"📅 Next runs: Adaptive strategy {next_adaptive_run}, Data+Trading {next_data_run}")
            else:
                self.logger.info(f"📅 Next data+trading run: {next_data_run}")
            
            self.logger.info("✅ Scheduler will run on schedule to avoid event loop conflicts")
            
        except Exception as e:
            self.logger.error(f"Failed to start enhanced scheduler: {e}")
            self.is_running = False
            raise
    
    def stop_scheduler(self):
        """Stop the inference scheduler"""
        if not self.is_running:
            return
            
        try:
            self.is_running = False
            self.stop_event.set()
            
            # Clear schedule
            schedule.clear()
            
            # Wait for scheduler thread
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                self.scheduler_thread.join(timeout=5.0)
            
            self.logger.info("Inference scheduler stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping inference scheduler: {e}")
    
    def _scheduler_loop(self):
        """Main scheduler loop (runs in separate thread)"""
        while not self.stop_event.is_set():
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in scheduler loop: {e}")
                time.sleep(5)
    
    def _run_ohlcv_fetch(self):
        """Run OHLCV data fetch as scheduled job"""
        if not self.is_running:
            return
            
        try:
            self.logger.info("Starting scheduled OHLCV data fetch")
            
            # Use subprocess to run the historical data script
            success_count = 0
            error_count = 0
            
            for token_address in self.config.active_tokens:
                try:
                    # Build command using ACTUAL fetch_historical_data.py parameters
                    cmd = [
                        "python", str(self.historical_script),
                        "--token-address", token_address,
                        "--resolution", self.config.ohlcv_resolution,
                        "--days", str(self.config.ohlcv_lookback_hours // 24),
                        "--max-workers", "3",
                        "--delay", "2",
                        "--batch-size", "1000"
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=300,  # 5 minute timeout
                        cwd=self.scripts_dir.parent.parent
                    )
                    
                    if result.returncode == 0:
                        success_count += 1
                        self.logger.debug(f"OHLCV data fetched successfully for {token_address}")
                    else:
                        error_count += 1
                        self.logger.error(f"OHLCV fetch failed for {token_address}: {result.stderr}")
                    
                    # Respect rate limits - delay between tokens
                    time.sleep(1)
                    
                except subprocess.TimeoutExpired:
                    error_count += 1
                    self.logger.error(f"OHLCV fetch timeout for {token_address}")
                except Exception as e:
                    error_count += 1
                    self.logger.error(f"OHLCV fetch error for {token_address}: {e}")
            
            # Update statistics
            self.stats['ohlcv_runs'] += 1
            self.stats['last_ohlcv_run'] = datetime.utcnow()
            if error_count > 0:
                self.stats['total_errors'] += error_count
            
            success_rate = success_count / len(self.config.active_tokens) if self.config.active_tokens else 0
            self.logger.info(f"OHLCV fetch completed: {success_count}/{len(self.config.active_tokens)} tokens successful ({success_rate:.1%})")
            
            # 🚨 DISABLED: Health check recording to prevent database spam
            # Health checks are now throttled in the database manager
            self.logger.info(f"OHLCV fetch completed: {success_count}/{len(self.config.active_tokens)} tokens, {success_rate:.1f}% success rate")
            
        except Exception as e:
            self.logger.error(f"OHLCV fetch failed: {e}")
            self.stats['total_errors'] += 1
            
            # Don't try to record health checks from thread context - just log the error
    
    def _run_social_fetch(self):
        """Run social data fetch for all tokens"""
        self.logger.info("Starting scheduled social data fetch")
        
        try:
            # Build command for fetch_social_data.py  
            # Fetch for all active tokens at once
            cmd = [
                "python", str(self.social_script),
                "--days", str(self.config.social_lookback_days),
                "--interval", self.config.social_resolution,
                "--batch-size", "50"  # Conservative batch size
            ]
            
            # Run the script
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout for social data
                cwd=self.scripts_dir.parent.parent
            )
            
            # Update statistics
            self.stats['social_runs'] += 1
            self.stats['last_social_run'] = datetime.utcnow()
            
            if result.returncode == 0:
                self.logger.info("Social data fetch completed successfully")
                
                # 🚨 DISABLED: Health check recording to prevent database spam
                self.logger.info(f"Social data fetch completed successfully for {len(self.config.active_tokens)} tokens")
            else:
                self.logger.error(f"Social data fetch failed: {result.stderr}")
                self.stats['total_errors'] += 1
                
                # 🚨 DISABLED: Health check recording to prevent database spam
                # Error is already logged above
                
        except subprocess.TimeoutExpired:
            self.logger.error("Social data fetch timeout")
            self.stats['total_errors'] += 1
            
            # Don't try to record health checks from thread context - just log the error
            
        except Exception as e:
            self.logger.error(f"Error in social fetch run: {e}")
            self.stats['total_errors'] += 1
            
            # Don't try to record health checks from thread context - just log the error
    
    def _run_health_check(self):
        """Run periodic health check"""
        try:
            # Use asyncio.run() but handle potential loop conflicts
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're in a running loop, schedule the task
                    asyncio.create_task(self._perform_health_check())
                else:
                    # No running loop, safe to use asyncio.run()
                    asyncio.run(self._perform_health_check())
            except RuntimeError:
                # No event loop, create new one
                asyncio.run(self._perform_health_check())
        except Exception as e:
            self.logger.error(f"Error in health check: {e}")
    
    def _sanitize_stats_for_json(self, stats_dict: Dict) -> Dict:
        """Convert datetime objects to strings for JSON serialization"""
        sanitized = {}
        for key, value in stats_dict.items():
            if isinstance(value, datetime):
                sanitized[key] = value.isoformat()
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_stats_for_json(value)
            else:
                sanitized[key] = value
        return sanitized

    async def _record_health_check(self, component: str, status: str, details: Dict):
        """Record health check to database"""
        try:
            if self.db_manager:
                # Use a new connection to avoid conflicts
                async with self.db_manager.pg_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO system_health (component, status, details, check_time)
                        VALUES ($1, $2, $3, $4)
                        """,
                        component, status, details, datetime.utcnow()
                    )
        except Exception as e:
            self.logger.error(f"Failed to record health check for {component}: {e}")
    
    async def _perform_health_check(self):
        """Perform comprehensive health check on all components"""
        try:
            health_info = {
                'timestamp': datetime.utcnow().isoformat(),  # Convert to string for JSON serialization
                'uptime_hours': (datetime.utcnow() - self.stats['start_time']).total_seconds() / 3600,
                'is_running': self.is_running,
                'scheduler_thread_alive': self.scheduler_thread.is_alive() if self.scheduler_thread else False,
                'stats': self._sanitize_stats_for_json(self.stats.copy())  # Sanitize datetime objects
            }
            
            # Database health - skip if we're in a thread to avoid event loop conflicts
            try:
                # Check if we're in the main thread or a scheduler thread
                import threading
                if threading.current_thread() is threading.main_thread():
                    # Main thread - safe to use the existing db_manager
                    if self.db_manager:
                        db_healthy = await self.db_manager.health_check()
                        health_info['database_healthy'] = db_healthy
                        
                        # Get recent token count
                        active_tokens = await self.db_manager.get_active_tokens()
                        health_info['active_tokens_count'] = len(active_tokens)
                    else:
                        health_info['database_healthy'] = False
                        health_info['active_tokens_count'] = 0
                else:
                    # Scheduler thread - skip database checks to avoid event loop conflicts
                    health_info['database_healthy'] = 'skipped_in_thread'
                    health_info['active_tokens_count'] = len(self.config.active_tokens)
            except Exception as db_error:
                health_info['database_healthy'] = False
                health_info['database_error'] = str(db_error)
            
            # Memory usage check
            try:
                import psutil
                memory_info = psutil.virtual_memory()
                health_info['memory_usage_pct'] = memory_info.percent
                health_info['available_memory_gb'] = memory_info.available / (1024**3)
            except ImportError:
                health_info['memory_usage_pct'] = None
            
            # Disk space check
            try:
                import shutil
                total, used, free = shutil.disk_usage("/")
                health_info['disk_usage_pct'] = (used / total) * 100
                health_info['free_space_gb'] = free / (1024**3)
            except Exception:
                health_info['disk_usage_pct'] = None
            
            # Enhanced cache health monitoring - skip in threads to avoid conflicts
            import threading
            if threading.current_thread() is threading.main_thread():
                try:
                    cache_metrics = await self.get_cache_performance_metrics()
                    health_info['cache_health'] = cache_metrics
                    
                    # Trigger cache maintenance if needed
                    if cache_metrics.get('redis_memory_usage_mb', 0) > 1000:  # 1GB threshold
                        self.logger.info("Triggering cache maintenance due to high Redis memory usage")
                        await self.cache_maintenance()
                        
                except Exception as cache_error:
                    health_info['cache_health'] = {'error': str(cache_error)}
                    self.logger.error(f"Cache health monitoring failed: {cache_error}")
            else:
                health_info['cache_health'] = 'skipped_in_thread'
            
            # Determine overall health status
            status = 'healthy'
            if not self.is_running:
                status = 'stopped'
            elif health_info.get('database_healthy', False) is False:
                status = 'degraded'
            elif health_info.get('memory_usage_pct', 0) > 90:
                status = 'degraded'
            elif health_info.get('disk_usage_pct', 0) > 90:
                status = 'degraded'
            
            # Record enhanced health check - DISABLED in threads to avoid event loop conflicts
            import threading
            if threading.current_thread() is threading.main_thread():
                await self._record_health_check('inference_scheduler_enhanced', status, health_info)
            else:
                self.logger.debug(f"Health check status: {status} (recording disabled in thread)")
            
        except Exception as e:
            self.logger.error(f"Enhanced health check failed: {e}")
            await self._record_health_check('inference_scheduler_enhanced', 'error', {'error': str(e)})
    
    # =========================================================================
    # MANUAL OPERATIONS
    # =========================================================================
    
    async def manual_ohlcv_fetch(self, token_address: Optional[str] = None) -> Dict[str, Any]:
        """Manually trigger OHLCV data fetch"""
        try:
            tokens_to_fetch = [token_address] if token_address else self.config.active_tokens
            
            results = {}
            for token_addr in tokens_to_fetch:
                cmd = [
                    "python", str(self.historical_script),
                    "--token-address", token_addr,
                    "--resolution", self.config.ohlcv_resolution,
                    "--days", str(self.config.ohlcv_lookback_hours // 24 + 1),
                    "--max-workers", "1"
                ]
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=self.scripts_dir.parent.parent
                )
                
                results[token_addr] = {
                    'success': result.returncode == 0,
                    'output': result.stdout if result.returncode == 0 else result.stderr
                }
            
            return results
            
        except Exception as e:
            self.logger.error(f"Manual OHLCV fetch failed: {e}")
            return {'error': str(e)}
    
    async def manual_social_fetch(self) -> Dict[str, Any]:
        """Manually trigger social data fetch"""
        try:
            cmd = [
                "python", str(self.social_script),
                "--days", str(self.config.social_lookback_days),
                "--interval", self.config.social_resolution,
                "--batch-size", "50"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=self.scripts_dir.parent.parent
            )
            
            return {
                'success': result.returncode == 0,
                'output': result.stdout if result.returncode == 0 else result.stderr
            }
            
        except Exception as e:
            self.logger.error(f"Manual social fetch failed: {e}")
            return {'error': str(e)}
    
    # =========================================================================
    # INFERENCE DATA PREPARATION
    # =========================================================================
    
    async def prepare_inference_data(self, token_address: str) -> Optional[Dict[str, Any]]:
        """
        Prepare comprehensive inference data using enhanced data processor
        
        Args:
            token_address: Token address to prepare data for
            
        Returns:
            Comprehensive inference data with full feature engineering
        """
        try:
            # Initialize inference data processor if not already done
            if not hasattr(self, '_inference_processor'):
                from .inference_data_processor import create_inference_data_processor
                self._inference_processor = await create_inference_data_processor(self.db_manager)
            
            # Use enhanced data processor for comprehensive feature engineering
            inference_data = await self._inference_processor.prepare_inference_data(
                token_address=token_address,
                resolution='1H'
            )
            
            return inference_data
            
        except Exception as e:
            self.logger.error(f"Error preparing inference data for {token_address}: {e}")
            return None
    
    async def prepare_batch_inference_data(self, token_addresses: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        ENHANCED: Redis-backed batch caching with smart cache management
        
        Args:
            token_addresses: List of token addresses. If None, uses active_tokens
            
        Returns:
            Dict mapping token addresses to their inference data
        """
        try:
            tokens_to_process = token_addresses or self.config.active_tokens
            
            # Initialize inference data processor if not already done
            if not hasattr(self, '_inference_processor'):
                from .inference_data_processor import create_inference_data_processor
                self._inference_processor = await create_inference_data_processor(self.db_manager)
            
            # PHASE 1: Check Redis cache for each token
            cached_results = {}
            uncached_tokens = []
            cache_check_start = time.time()
            
            # Use Redis pipeline for efficient batch cache checking
            # Check if we have Redis client available
            if hasattr(self.db_manager, 'redis_client') and self.db_manager.redis_client:
                cache_results = []
                for token in tokens_to_process:
                    key = f"batch_inference:{token}"
                    try:
                        cached_data = await self.db_manager.redis_client.get(key)
                        cache_results.append(cached_data)
                    except Exception as e:
                        self.logger.debug(f"Redis get error for {key}: {e}")
                        cache_results.append(None)
            else:
                # No Redis available, treat all as uncached
                cache_results = [None] * len(tokens_to_process)
                
            for i, (token_address, cached_data) in enumerate(zip(tokens_to_process, cache_results)):
                if cached_data:
                    try:
                        cached_results[token_address] = json.loads(cached_data)
                    except json.JSONDecodeError:
                        uncached_tokens.append(token_address)
                else:
                    uncached_tokens.append(token_address)
            
            cache_check_time = time.time() - cache_check_start
            
            # PHASE 2: Process only uncached tokens
            new_results = {}
            if uncached_tokens:
                processing_start = time.time()
                new_results = await self._inference_processor.get_batch_inference_data(
                    token_addresses=uncached_tokens,
                    resolution='1H'
                )
                processing_time = time.time() - processing_start
                
                # PHASE 3: Cache new results
                cache_write_start = time.time()
                if hasattr(self.db_manager, 'redis_client') and self.db_manager.redis_client:
                    for token_address, data in new_results.items():
                        if data.get('ready_for_inference', False):
                            cache_key = f"batch_inference:{token_address}"
                            try:
                                await self.db_manager.redis_client.setex(
                                    cache_key,
                                    3600,  # 1 hour TTL
                                    json.dumps(data, default=str)
                                )
                            except Exception as e:
                                self.logger.debug(f"Redis cache write error for {cache_key}: {e}")
                cache_write_time = time.time() - cache_write_start
                
                self.logger.info(f"Batch processing performance: "
                               f"cache_check={cache_check_time:.2f}s, "
                               f"processing={processing_time:.2f}s, "
                               f"cache_write={cache_write_time:.2f}s")
            
            # PHASE 4: Combine results
            final_results = {**cached_results, **new_results}
            
            # Log summary with cache performance
            successful = sum(1 for data in final_results.values() if data.get('ready_for_inference', False))
            failed = len(final_results) - successful
            cache_hit_rate = len(cached_results) / len(tokens_to_process) * 100 if tokens_to_process else 0
            
            self.logger.info(f"Batch inference completed: {len(cached_results)} cached, "
                           f"{len(new_results)} newly processed, "
                           f"cache hit rate: {cache_hit_rate:.1f}%")
            
            return final_results
            
        except Exception as e:
            self.logger.error(f"Error in enhanced batch inference: {e}")
            return {}
    
    async def get_cache_performance_metrics(self) -> Dict[str, Any]:
        """ENHANCED: Cache performance monitoring with comprehensive metrics"""
        try:
            # Use the app_config that was imported at the top
            env_config = app_config
            
            # Check Redis memory usage for inference cache
            redis_info = await self.db_manager.redis_client.info('memory')
            
            # Count cached inference keys
            inference_pattern = env_config.get('REDIS_INFERENCE_KEY_PREFIX', 'inference_features') + ":*"
            batch_pattern = env_config.get('REDIS_BATCH_KEY_PREFIX', 'batch_inference') + ":*"
            
            inference_keys = await self.db_manager.redis_client.keys(inference_pattern)
            batch_keys = await self.db_manager.redis_client.keys(batch_pattern)
            
            # Calculate cache age statistics
            cache_ages = []
            if inference_keys:
                # Sample a few keys to check TTL
                sample_keys = inference_keys[:min(10, len(inference_keys))]
                for key in sample_keys:
                    ttl = await self.db_manager.redis_client.ttl(key)
                    if ttl > 0:
                        # Calculate age from TTL (assuming 1 hour initial TTL)
                        age_seconds = 3600 - ttl
                        cache_ages.append(age_seconds / 60)  # Convert to minutes
            
            average_cache_age_minutes = sum(cache_ages) / len(cache_ages) if cache_ages else 0
            
            # Get cache efficiency score
            cache_efficiency = await self._calculate_cache_efficiency()
            
            # Calculate cache hit rate if we have historical data
            # This could be enhanced to track actual hit/miss ratios
            cache_hit_rate_estimate = min(85.0, cache_efficiency * 100) if cache_efficiency > 0 else 0
            
            return {
                'redis_memory_used_mb': redis_info.get('used_memory', 0) / (1024 * 1024),
                'redis_memory_peak_mb': redis_info.get('used_memory_peak', 0) / (1024 * 1024),
                'inference_cache_keys': len(inference_keys),
                'batch_cache_keys': len(batch_keys),
                'total_cached_tokens': len(inference_keys) + len(batch_keys),
                'average_cache_age_minutes': average_cache_age_minutes,
                'cache_efficiency_score': cache_efficiency,
                'cache_hit_rate_percent_estimate': cache_hit_rate_estimate,
                'cache_patterns': {
                    'inference_pattern': inference_pattern,
                    'batch_pattern': batch_pattern
                },
                'redis_stats': {
                    'connected_clients': redis_info.get('connected_clients', 0),
                    'keyspace_hits': redis_info.get('keyspace_hits', 0),
                    'keyspace_misses': redis_info.get('keyspace_misses', 0)
                }
            }
        except Exception as e:
            self.logger.error(f"Cache metrics collection failed: {e}")
            return {'cache_metrics_error': str(e)}
    
    async def _calculate_cache_efficiency(self) -> float:
        """Calculate cache efficiency score based on REAL hit rates and performance data"""
        try:
            # Get real cache statistics from the inference processor
            if hasattr(self, '_inference_processor'):
                cache_stats = await self._inference_processor.get_cache_statistics()
                
                # Extract real performance metrics
                instance_stats = cache_stats.get('instance_stats', {})
                hit_rate = instance_stats.get('hit_rate_percent', 0) / 100  # Convert to 0-1 scale
                performance_factor = instance_stats.get('performance_improvement_factor', 1)
                
                # Calculate efficiency based on real metrics
                # Hit rate contributes 60% to efficiency
                hit_efficiency = hit_rate
                
                # Performance improvement contributes 40% to efficiency
                # Normalize performance factor (10x improvement = 1.0 efficiency)
                performance_efficiency = min(1.0, performance_factor / 10) if performance_factor > 0 else 0
                
                # Combined efficiency score
                total_efficiency = (hit_efficiency * 0.6) + (performance_efficiency * 0.4)
                
                self.logger.debug(f"Real cache efficiency: hit_rate={hit_rate:.1%}, "
                                f"performance={performance_factor:.1f}x, "
                                f"efficiency={total_efficiency:.2f}")
                
                return min(1.0, total_efficiency)
            
            else:
                # Fallback if inference processor not initialized
                self.logger.warning("Inference processor not available for real cache metrics")
                return 0.5  # Conservative baseline
                
        except Exception as e:
            self.logger.error(f"Real cache efficiency calculation failed: {e}")
            return 0.0
    
    # =========================================================================
    # CACHE MAINTENANCE
    # =========================================================================
    
    async def cache_maintenance(self) -> Dict[str, Any]:
        """Perform cache maintenance and cleanup operations"""
        try:
            # Use the app_config that was imported at the top
            env_config = app_config
            
            maintenance_results = {
                'cleanup_performed': False,
                'keys_cleaned': 0,
                'memory_freed_mb': 0,
                'maintenance_time_seconds': 0
            }
            
            start_time = time.time()
            
            # Get current memory usage
            redis_info_before = await self.db_manager.redis_client.info('memory')
            memory_before_mb = redis_info_before.get('used_memory', 0) / (1024 * 1024)
            
            # Get cache limits
            cache_limit_mb = int(env_config.get('FEATURE_CACHE_MAX_SIZE_MB', 100))
            
            # Check if cleanup is needed (if using >80% of limit)
            if memory_before_mb > cache_limit_mb * 0.8:
                self.logger.info(f"Cache maintenance triggered: {memory_before_mb:.1f}MB / {cache_limit_mb}MB")
                
                # Clean up expired cache entries
                inference_pattern = env_config.get('REDIS_INFERENCE_KEY_PREFIX', 'inference_features') + ":*"
                batch_pattern = env_config.get('REDIS_BATCH_KEY_PREFIX', 'batch_inference') + ":*"
                
                # Count keys before cleanup
                inference_keys = await self.db_manager.redis_client.keys(inference_pattern)
                batch_keys = await self.db_manager.redis_client.keys(batch_pattern)
                keys_before = len(inference_keys) + len(batch_keys)
                
                # Clean up expired keys (Redis handles TTL automatically, but we can force cleanup)
                # In practice, this would involve more sophisticated cleanup logic
                await self.db_manager.redis_client.execute_command('MEMORY', 'PURGE')
                
                # Get updated stats
                redis_info_after = await self.db_manager.redis_client.info('memory')
                memory_after_mb = redis_info_after.get('used_memory', 0) / (1024 * 1024)
                
                # Count keys after cleanup
                inference_keys_after = await self.db_manager.redis_client.keys(inference_pattern)
                batch_keys_after = await self.db_manager.redis_client.keys(batch_pattern)
                keys_after = len(inference_keys_after) + len(batch_keys_after)
                
                maintenance_results.update({
                    'cleanup_performed': True,
                    'keys_cleaned': keys_before - keys_after,
                    'memory_freed_mb': max(0, memory_before_mb - memory_after_mb),
                    'memory_before_mb': memory_before_mb,
                    'memory_after_mb': memory_after_mb
                })
                
                self.logger.info(f"Cache maintenance completed: freed {maintenance_results['memory_freed_mb']:.1f}MB, "
                               f"cleaned {maintenance_results['keys_cleaned']} keys")
            
            maintenance_results['maintenance_time_seconds'] = time.time() - start_time
            return maintenance_results
            
        except Exception as e:
            self.logger.error(f"Cache maintenance failed: {e}")
            return {'maintenance_error': str(e)}
    
    async def get_cache_health_report(self) -> Dict[str, Any]:
        """Generate comprehensive cache health report"""
        try:
            # Use the app_config that was imported at the top
            env_config = app_config
            
            # Get current metrics
            cache_metrics = await self.get_cache_performance_metrics()
            
            # Analyze health status
            memory_mb = cache_metrics.get('redis_memory_used_mb', 0)
            limit_mb = int(env_config.get('FEATURE_CACHE_MAX_SIZE_MB', 100))
            hit_rate_target = int(env_config.get('CACHE_HIT_RATE_TARGET', 70))
            
            # Calculate health scores
            memory_health = max(0, 1 - (memory_mb / limit_mb))  # 1.0 = no usage, 0.0 = at limit
            efficiency_health = cache_metrics.get('cache_efficiency_score', 0)
            
            overall_health = (memory_health + efficiency_health) / 2
            
            # Determine status
            if overall_health >= 0.8:
                status = 'healthy'
            elif overall_health >= 0.6:
                status = 'degraded'
            else:
                status = 'poor'
            
            return {
                'overall_status': status,
                'overall_health_score': overall_health,
                'memory_health_score': memory_health,
                'efficiency_health_score': efficiency_health,
                'metrics': cache_metrics,
                'recommendations': self._get_cache_recommendations(cache_metrics, limit_mb),
                'thresholds': {
                    'memory_limit_mb': limit_mb,
                    'hit_rate_target_percent': hit_rate_target,
                    'efficiency_target': 0.7
                }
            }
            
        except Exception as e:
            self.logger.error(f"Cache health report generation failed: {e}")
            return {'health_report_error': str(e)}
    
    def _get_cache_recommendations(self, metrics: Dict[str, Any], limit_mb: int) -> List[str]:
        """Generate cache optimization recommendations"""
        recommendations = []
        
        memory_mb = metrics.get('redis_memory_used_mb', 0)
        efficiency = metrics.get('cache_efficiency_score', 0)
        
        if memory_mb > limit_mb * 0.9:
            recommendations.append("Consider increasing FEATURE_CACHE_MAX_SIZE_MB or implementing more aggressive cleanup")
        
        if memory_mb > limit_mb * 0.8:
            recommendations.append("Memory usage is high - consider running cache maintenance")
        
        if efficiency < 0.7:
            recommendations.append("Cache efficiency is low - review TTL settings and access patterns")
        
        if metrics.get('total_cached_tokens', 0) < 5:
            recommendations.append("Very few cached tokens - check if caching is working properly")
        
        if not recommendations:
            recommendations.append("Cache performance is optimal")
        
        return recommendations
    
    # =========================================================================
    # MONITORING
    # =========================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get scheduler statistics"""
        uptime = datetime.utcnow() - self.stats['start_time']
        
        return {
            **self.stats,
            'uptime_seconds': uptime.total_seconds(),
            'configured_tokens': len(self.config.active_tokens),
            'ohlcv_interval_minutes': self.config.ohlcv_interval_minutes,
            'social_interval_minutes': self.config.social_interval_minutes,
            'is_running': self.is_running
        }

    async def run_inference_and_trading_cycle(self):
        """
        Complete cycle: data → inference → vault execution (Phase 3.2)
        
        This is the main integration method that:
        1. Prepares inference data using existing pipeline
        2. Generates portfolio signals via portfolio coordinator
        3. Executes vault trades based on signals
        4. Records all data in TimescaleDB
        """
        cycle_start_time = datetime.utcnow()
        
        # Ensure we have the correct database manager for this event loop
        created_new_manager = await self._ensure_thread_db_manager()
        
        # Initialize timing tracking
        timing_data = {
            'data_fetch_start': None,
            'data_fetch_duration_ms': None,
            'inference_start': None,
            'inference_duration_ms': None,
            'signal_processing_start': None,
            'signal_processing_duration_ms': None,
            'trade_execution_start': None,
            'trade_execution_duration_ms': None
        }
        
        try:
            self.logger.info("🚀 Starting inference and trading cycle")
            
            # 1. Prepare inference data (EXISTING FUNCTIONALITY) - WITH TIMING
            timing_data['data_fetch_start'] = datetime.utcnow()
            self.logger.info("📊 Preparing batch inference data...")
            inference_data = await self.prepare_batch_inference_data()
            timing_data['data_fetch_duration_ms'] = int((datetime.utcnow() - timing_data['data_fetch_start']).total_seconds() * 1000)
            
            ready_tokens = [addr for addr, data in inference_data.items() 
                           if data.get('ready_for_inference', False)]
            
            # Debug logging to understand why tokens aren't ready
            self.logger.info(f"🔍 Token readiness debug:")
            for addr, data in inference_data.items():
                ready = data.get('ready_for_inference', False)
                data_points = data.get('data_points', 0)
                quality_score = data.get('quality_score', 0)
                error = data.get('error', 'None')
                self.logger.info(f"  📊 {addr[:8]}...{addr[-8:]}: ready={ready}, data_points={data_points}, quality={quality_score:.2f}, error={error}")
            
            # REMOVED: Arbitrary minimum token check - let the system work with whatever tokens are available
            self.logger.info(f"📊 Proceeding with {len(ready_tokens)} ready tokens (minimum check disabled)")
            
            self.logger.info(f"✅ {len(ready_tokens)} tokens ready for inference (data fetch: {timing_data['data_fetch_duration_ms']}ms)")
            
            # 2. Generate portfolio signals (EXISTING INTEGRATION) - WITH TIMING
            timing_data['inference_start'] = datetime.utcnow()
            self.logger.info("🧠 Generating portfolio signals...")
            from ..inference.portfolio_coordinator import PortfolioCoordinator
            
            # Create a portfolio coordinator with the thread-local db_manager
            portfolio_coordinator = PortfolioCoordinator(db_manager=self.db_manager)
            await portfolio_coordinator.initialize()
            
            portfolio_signals = await portfolio_coordinator.generate_portfolio_signals()
            timing_data['inference_duration_ms'] = int((datetime.utcnow() - timing_data['inference_start']).total_seconds() * 1000)
            
            if not portfolio_signals:
                self.logger.info("📊 No portfolio signals generated")
                await self._record_vault_trading_cycle(None, [], "no_signals", cycle_start_time, None, timing_data)
                return
            
            # 3. Signal processing and risk analysis - WITH TIMING
            timing_data['signal_processing_start'] = datetime.utcnow()
            
            # Calculate correlation risk
            correlation_risk = await self._calculate_correlation_risk(portfolio_signals)
            
            # Get available cash from vault state
            available_cash_usdc = await self._get_available_cash_from_vault()
            
            timing_data['signal_processing_duration_ms'] = int((datetime.utcnow() - timing_data['signal_processing_start']).total_seconds() * 1000)
            
            self.logger.info(f"📈 Portfolio signals generated: {len(portfolio_signals.buy_signals)} buy, {len(portfolio_signals.sell_signals)} sell")
            self.logger.info(f"🔍 Risk analysis: correlation_risk={correlation_risk:.1f}%, available_cash=${available_cash_usdc:,.2f}")
            
            # 4. Execute vault trades (NEW FUNCTIONALITY) - WITH TIMING
            trade_results = []
            if portfolio_signals.buy_signals:
                timing_data['trade_execution_start'] = datetime.utcnow()
                self.logger.info("💰 Executing vault trades...")
                
                try:
                    from ..vault.trade_executor import VaultTradeExecutor
                    executor = VaultTradeExecutor()
                    await executor.initialize()
                    
                    trade_results = await executor.execute_portfolio_trades(portfolio_signals)
                    timing_data['trade_execution_duration_ms'] = int((datetime.utcnow() - timing_data['trade_execution_start']).total_seconds() * 1000)
                    
                    self.logger.info(f"✅ Executed {len(trade_results)} vault trades (execution: {timing_data['trade_execution_duration_ms']}ms)")
                    if trade_results:
                        self.logger.info(f"🔗 Trade signatures: {trade_results[:3]}{'...' if len(trade_results) > 3 else ''}")
                        
                except ImportError:
                    self.logger.warning("⚠️ VaultTradeExecutor not available - running in data-only mode")
                    trade_results = []
                    timing_data['trade_execution_duration_ms'] = 0
                except Exception as e:
                    self.logger.error(f"❌ Vault trade execution failed: {e}")
                    trade_results = []
                    timing_data['trade_execution_duration_ms'] = int((datetime.utcnow() - timing_data['trade_execution_start']).total_seconds() * 1000) if timing_data['trade_execution_start'] else 0
            else:
                self.logger.info("📊 No buy signals to execute")
                timing_data['trade_execution_duration_ms'] = 0
            
            # 5. Record successful trading cycle in database with enhanced metrics
            try:
                await self._record_vault_trading_cycle(
                    portfolio_signals, trade_results, "completed", cycle_start_time, None, timing_data, 
                    correlation_risk, available_cash_usdc
                )
            except Exception as db_error:
                self.logger.warning(f"⚠️ Failed to record trading cycle (non-critical): {db_error}")
                # Continue execution even if database recording fails
            
            # Update statistics
            self.stats['inference_trading_cycles'] += 1
            self.stats['vault_trades_executed'] += len(trade_results)
            self.stats['last_trading_cycle'] = cycle_start_time
            
            cycle_duration = (datetime.utcnow() - cycle_start_time).total_seconds()
            self.logger.info(f"🏁 Inference and trading cycle completed in {cycle_duration:.1f}s")
            self.logger.info(f"⏱️ Timing breakdown: data={timing_data['data_fetch_duration_ms']}ms, inference={timing_data['inference_duration_ms']}ms, signals={timing_data['signal_processing_duration_ms']}ms, trades={timing_data['trade_execution_duration_ms']}ms")
            
        except Exception as e:
            self.logger.error(f"❌ Inference and trading cycle failed: {e}")
            
            # 🚨 DISABLED: Health check recording to prevent database connection spam
            # await self._record_health_check('trading_cycle', 'error', {'error': str(e)})
            await self._record_vault_trading_cycle(None, [], "error", cycle_start_time, str(e), timing_data)
        finally:
            # Restore original database manager if we created a new one
            if created_new_manager:
                await self._restore_original_db_manager()

    async def _calculate_correlation_risk(self, portfolio_signals) -> float:
        """
        Calculate correlation risk for the portfolio based on asset allocations
        
        Args:
            portfolio_signals: PortfolioSignal object with asset allocations
            
        Returns:
            Correlation risk score (0-100, higher = more correlated/risky)
        """
        try:
            if not portfolio_signals or not hasattr(portfolio_signals, 'asset_allocations'):
                return 0.0
            
            allocations = portfolio_signals.asset_allocations
            if len(allocations) <= 1:
                return 100.0  # Single asset = maximum correlation risk
            
            # Get token symbols for correlation analysis
            symbols = list(allocations.keys())
            
            # Simple correlation risk calculation based on:
            # 1. Number of assets (more assets = lower correlation risk)
            # 2. Allocation concentration (more concentrated = higher risk)
            # 3. Asset type diversity (crypto tokens have high correlation)
            
            # Base correlation risk for crypto assets (they tend to be highly correlated)
            base_crypto_correlation = 70.0
            
            # Diversification benefit: reduce risk based on number of assets
            num_assets = len(allocations)
            diversification_factor = min(0.5, (num_assets - 1) / 10)  # Max 50% reduction for 11+ assets
            
            # Concentration penalty: increase risk for concentrated positions
            allocation_values = [alloc.target_exposure_pct for alloc in allocations.values()]
            max_allocation = max(allocation_values) if allocation_values else 0
            concentration_penalty = max(0, (max_allocation - 20) / 2)  # Penalty for >20% allocations
            
            # Calculate final correlation risk
            correlation_risk = base_crypto_correlation * (1 - diversification_factor) + concentration_penalty
            correlation_risk = max(0, min(100, correlation_risk))  # Clamp to 0-100
            
            self.logger.debug(f"Correlation risk calculation: base={base_crypto_correlation}, assets={num_assets}, "
                            f"diversification_factor={diversification_factor:.2f}, max_allocation={max_allocation:.1f}%, "
                            f"concentration_penalty={concentration_penalty:.1f}, final_risk={correlation_risk:.1f}")
            
            return correlation_risk
            
        except Exception as e:
            self.logger.error(f"Failed to calculate correlation risk: {e}")
            return 50.0  # Default moderate risk if calculation fails

    async def _get_available_cash_from_vault(self) -> float:
        """
        Get available cash (USDC) from vault state
        
        Returns:
            Available cash in USDC
        """
        try:
            # Import vault client here to avoid circular imports
            from ..vault.vault_client import VaultClient
            from solana.rpc.async_api import AsyncClient
            from solders.keypair import Keypair
            import os
            import json
            
            # Create and initialize vault client with proper parameters
            rpc_url = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
            vault_program_id = os.getenv('VAULT_PROGRAM_ID', 'tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z')
            
            # Load authority keypair
            authority_key_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'onchain', 'calvin-ai-authority.json')
            with open(authority_key_path, 'r') as f:
                authority_key_data = json.load(f)
            authority_keypair = Keypair.from_bytes(authority_key_data)
            
            # Create connection and vault client
            connection = AsyncClient(rpc_url)
            vault_client = VaultClient(
                vault_program=vault_program_id,
                connection=connection,
                authority_keypair=authority_keypair
            )
            await vault_client.initialize()
            
            # Get vault state
            vault_state = await vault_client.get_vault_state()
            
            # Extract available cash (total USDC in vault)
            available_cash = vault_state.get('total_usdc', 0.0)
            
            # Close vault client connection
            await vault_client.close()
            
            self.logger.debug(f"Retrieved available cash from vault: ${available_cash:,.2f}")
            return available_cash
            
        except Exception as e:
            self.logger.error(f"Failed to get available cash from vault: {e}")
            
            # Fallback: try to get from database (last known portfolio value)
            try:
                if self.db_manager:
                    latest_cycle = await self.db_manager.get_latest_portfolio_cycle()
                    if latest_cycle and latest_cycle.get('available_cash_usdc'):
                        fallback_cash = float(latest_cycle['available_cash_usdc'])
                        self.logger.info(f"Using last known available cash from database: ${fallback_cash:,.2f}")
                        return fallback_cash
                    elif latest_cycle and latest_cycle.get('total_portfolio_value_usdc'):
                        # Estimate available cash as 20% of total portfolio value
                        estimated_cash = float(latest_cycle['total_portfolio_value_usdc']) * 0.2
                        self.logger.warning(f"Estimating available cash as 20% of portfolio: ${estimated_cash:,.2f}")
                        return estimated_cash
            except Exception as db_error:
                self.logger.error(f"Database fallback also failed: {db_error}")
            
            # Final fallback: use environment variable
            from ..config.config import config
            fallback_cash = float(getattr(config, 'PORTFOLIO_VALUE_USDC', 100000.0)) * 0.2
            self.logger.warning(f"Using environment fallback for available cash: ${fallback_cash:,.2f}")
            return fallback_cash

    async def _record_vault_trading_cycle(self, signals, results: List[str], status: str, 
                                        cycle_start: datetime, error: str = None, timing_data: Dict[str, Any] = None, 
                                        correlation_risk: float = None, available_cash_usdc: float = None):
        """
        Record trading cycle results in TimescaleDB using enhanced portfolio_cycles table
        
        Args:
            signals: PortfolioSignal object or None
            results: List of transaction signatures
            status: Cycle status ('completed', 'no_signals', 'insufficient_tokens', 'error')
            cycle_start: Cycle start timestamp
            error: Error message if status is 'error'
            timing_data: Dictionary containing timing data for the cycle
            correlation_risk: Correlation risk for the cycle
            available_cash_usdc: Available cash from vault state
        """
        try:
            # Create PortfolioCycleData object for database recording
            from ..database.production_db import PortfolioCycleData
            
            cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
            
            # Extract portfolio metrics from signals if available
            portfolio_risk_score = None
            portfolio_value = None
            diversification_score = None
            max_position_pct = None
            
            if signals:
                portfolio_risk_score = getattr(signals, 'portfolio_risk_score', None)
                portfolio_value = getattr(signals, 'portfolio_value', None)
                
                # Calculate diversification metrics from asset allocations
                if hasattr(signals, 'asset_allocations') and signals.asset_allocations:
                    allocations = list(signals.asset_allocations.values())
                    max_position_pct = max(alloc.target_exposure_pct for alloc in allocations) if allocations else None
                    
                    # Simple diversification score: inverse of concentration
                    if len(allocations) > 1:
                        concentration = sum(alloc.target_exposure_pct ** 2 for alloc in allocations) / 100
                        diversification_score = max(0, 100 - concentration)
            
            portfolio_cycle = PortfolioCycleData(
                cycle_timestamp=cycle_start,
                # Cycle metrics - CORRECTED FIELD NAMES
                tokens_analyzed=len(self.config.active_tokens) if hasattr(self, 'config') else 0,
                signals_generated=len(signals.buy_signals + signals.sell_signals) if signals else 0,
                buy_signals=len(signals.buy_signals) if signals else 0,
                sell_signals=len(signals.sell_signals) if signals else 0,
                trades_executed=len(results),
                # Portfolio risk assessment - CORRECTED FIELD NAMES
                portfolio_risk_score=portfolio_risk_score,
                max_position_size_pct=max_position_pct,
                diversification_score=diversification_score,
                correlation_risk=correlation_risk,
                # Performance metrics - CORRECTED FIELD NAMES
                total_portfolio_value_usdc=portfolio_value,
                available_cash_usdc=available_cash_usdc,
                execution_priority=getattr(signals, 'execution_priority', None) if signals else None,
                # Execution timing - CORRECTED FIELD NAMES
                data_fetch_duration_ms=timing_data['data_fetch_duration_ms'] if timing_data else None,
                inference_duration_ms=timing_data['inference_duration_ms'] if timing_data else None,
                signal_processing_duration_ms=timing_data['signal_processing_duration_ms'] if timing_data else None,
                trade_execution_duration_ms=timing_data['trade_execution_duration_ms'] if timing_data else None,
                total_cycle_duration_ms=int(cycle_duration * 1000),  # Convert to milliseconds
                # Status and metadata - CORRECTED FIELD NAMES
                cycle_status=status,  # CORRECTED: was 'status'
                error_message=error
            )
            
            # Record in enhanced portfolio_cycles table
            if self.db_manager:
                cycle_id = await self.db_manager.record_portfolio_cycle(portfolio_cycle)
                self.logger.debug(f"✅ Recorded portfolio cycle {cycle_id} in database")
            
            # Also record in system health for monitoring compatibility
            cycle_summary = {
                'cycle_id': getattr(portfolio_cycle, 'cycle_id', None),
                'timestamp': cycle_start,
                'duration_seconds': cycle_duration,
                'status': status,
                'signals_generated': portfolio_cycle.signals_generated,
                'trades_executed': len(results),
                'portfolio_risk_score': portfolio_risk_score,
                'error_message': error
            }
            
            # 🚨 DISABLED: Health check recording to prevent database connection spam
            # await self._record_health_check('vault_trading_cycle', 
            #                                'healthy' if status == 'completed' else 'degraded', 
            #                                cycle_summary)
            
            # Record individual trade executions for monitoring
            if results:
                for i, tx_sig in enumerate(results):
                    trade_data = {
                        'cycle_timestamp': cycle_start,
                        'trade_index': i,
                        'transaction_signature': tx_sig,
                        'status': 'executed'
                    }
                    # 🚨 DISABLED: Health check recording to prevent database connection spam
                    # await self._record_health_check('vault_trade_execution', 'healthy', trade_data)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to record trading cycle: {e}")
            # Fallback to basic health check recording
            try:
                # 🚨 DISABLED: Health check recording to prevent database connection spam
                # await self._record_health_check('vault_trading_cycle', 'error', {
                #     'timestamp': cycle_start,
                #     'status': status,
                #     'error': str(e),
                #     'original_error': error
                # })
                pass  # Empty try block needs pass statement
            except Exception as fallback_error:
                self.logger.error(f"❌ Fallback recording also failed: {fallback_error}")

    def _run_adaptive_strategy_updates(self):
        """Run adaptive strategy parameter updates (XX:55)"""
        self.logger.info("🧠 Starting adaptive strategy parameter updates")
        
        try:
            # Create a completely isolated event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Create a new database manager for this thread's loop
            # This avoids conflicts with the main application's database connections
            from ..database.production_db import ProductionDBManager
            thread_db_manager = ProductionDBManager()
            loop.run_until_complete(thread_db_manager.initialize())
            
            try:
                # Run the async updates in this isolated loop
                # Store the db_manager temporarily and use the thread's
                original_db_manager = self.db_manager
                self.db_manager = thread_db_manager
                
                loop.run_until_complete(self._run_adaptive_strategy_updates_async())
                
                # Restore original db_manager
                self.db_manager = original_db_manager
            finally:
                # Clean up the thread's database connection
                loop.run_until_complete(thread_db_manager.close())
                # Clean up the loop
                loop.close()
                asyncio.set_event_loop(None)
            
        except Exception as e:
            self.logger.error(f"Error in adaptive strategy updates: {e}")
            # Import traceback for better error logging
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
    
    async def _run_adaptive_strategy_updates_async(self):
        """Async adaptive strategy parameter updates"""
        # Ensure we have a thread-local database manager if needed
        await self._ensure_thread_db_manager()
        
        try:
            from ..inference.adaptive_strategy import get_adaptive_strategy_engine
            
            # Get adaptive strategy engine
            adaptive_engine = await get_adaptive_strategy_engine()
            
            # Update parameters for all active tokens
            updated_count = 0
            error_count = 0
            
            for token_address in self.config.active_tokens:
                try:
                    # FIXED: get_token_by_address is synchronous and returns TokenInfo object
                    token_info = self.db_manager.get_token_by_address(token_address)
                    if not token_info:
                        continue
                    
                    # FIXED: Access TokenInfo object attributes directly (not dictionary keys)
                    symbol = token_info.symbol
                    
                    # Run adaptive strategy update
                    was_adapted = await adaptive_engine.adapt_strategy_parameters(symbol)
                    
                    if was_adapted:
                        updated_count += 1
                        # Get the updated parameters for logging
                        current_params = await adaptive_engine.get_adapted_parameters(symbol)
                        if current_params:
                            self.logger.debug(f"Updated adaptive parameters for {symbol}: "
                                            f"buy={current_params['buy_threshold']:.1%}, "
                                            f"sell={current_params['sell_threshold']:.1%}")
                        else:
                            self.logger.debug(f"Updated adaptive parameters for {symbol} (details unavailable)")
                    
                except Exception as e:
                    error_count += 1
                    self.logger.error(f"Adaptive update failed for {token_address}: {e}")
            
            self.logger.info(f"📊 Adaptive strategy updates completed: {updated_count} updated, {error_count} errors")
            
            # Record health check
            # 🚨 DISABLED: Health check recording to prevent database connection spam
            # await self._record_health_check(
            #     'adaptive_strategy_updates',
            #     'healthy' if error_count == 0 else 'degraded',
            #     {
            #         'tokens_updated': updated_count,
            #         'error_count': error_count,
            #         'total_tokens': len(self.config.active_tokens)
            #     }
            # )
            
        except Exception as e:
            self.logger.error(f"Adaptive strategy updates failed: {e}")
            # 🚨 DISABLED: Health check recording to prevent database connection spam
            # await self._record_health_check(
            #     'adaptive_strategy_updates',
            #     'error',
            #     {'error': str(e)}
            # )
        finally:
            # Always restore original database manager
            await self._restore_original_db_manager()
    
    def _run_data_and_trading_cycle(self):
        """Run combined data fetch + inference + trading cycle (XX:01)"""
        self.logger.info("🚀 Starting data fetch + inference + trading cycle")
        
        try:
            # Create a completely isolated event loop for this thread
            # This prevents conflicts with the main application's event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Create a new database manager for this thread's loop
            # This avoids conflicts with the main application's database connections
            from ..database.production_db import ProductionDBManager
            thread_db_manager = ProductionDBManager()
            loop.run_until_complete(thread_db_manager.initialize())
            
            try:
                # Run the async cycle in this isolated loop
                # Store the db_manager temporarily and use the thread's
                original_db_manager = self.db_manager
                self.db_manager = thread_db_manager
                
                loop.run_until_complete(self._run_data_and_trading_cycle_async())
                
                # Restore original db_manager
                self.db_manager = original_db_manager
            finally:
                # Clean up the thread's database connection
                loop.run_until_complete(thread_db_manager.close())
                # Clean up the loop
                loop.close()
                asyncio.set_event_loop(None)
            
        except Exception as e:
            self.logger.error(f"Error starting data and trading cycle: {e}")
            # Import traceback for better error logging
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
    
    async def _run_data_and_trading_cycle_async(self):
        """Async combined data fetch + inference + trading cycle"""
        cycle_start = datetime.utcnow()
        
        # Ensure we have a thread-local database manager if needed
        await self._ensure_thread_db_manager()
        
        try:
            self.logger.info("📥 Phase 1: Fresh data fetch (API + Database merge)")
            
            # 1. Fetch fresh OHLCV data (API freshness + database historical)
            ohlcv_success = await self._fetch_fresh_ohlcv_data()
            
            # 2. Fetch fresh social data (API freshness + database historical)  
            social_success = await self._fetch_fresh_social_data()
            
            if not ohlcv_success:
                self.logger.error("❌ OHLCV data fetch failed - aborting trading cycle")
                await self._record_vault_trading_cycle(
                    signals=None, results=[], status='failed', 
                    cycle_start=cycle_start, error='OHLCV data fetch failed'
                )
                return
            
            self.logger.info("🧠 Phase 2: LSTM inference + portfolio coordination")
            
            # 3. Run the existing inference and trading cycle
            await self.run_inference_and_trading_cycle()
            
        except Exception as e:
            self.logger.error(f"Data and trading cycle failed: {e}")
            await self._record_vault_trading_cycle(
                signals=None, results=[], status='failed',
                cycle_start=cycle_start, error=str(e)
            )
        finally:
            # Always restore original database manager
            await self._restore_original_db_manager()
    
    async def _fetch_fresh_ohlcv_data(self) -> bool:
        """
        Fetch fresh OHLCV data using optimized rate limits:
        - Rate limit: 1500 RPM (25 req/sec) - no delays needed
        - API: Last 48 hours (freshness buffer)
        - Database: Scripts automatically merge with existing historical data
        """
        try:
            success_count = 0
            error_count = 0
            
            for token_address in self.config.active_tokens:
                try:
                    # Build command using ACTUAL script parameters (optimized for 1500 RPM)
                    cmd = [
                        "python", str(self.historical_script),
                        "--token-address", token_address,
                        "--resolution", self.config.ohlcv_resolution,
                        "--days", str(self.config.ohlcv_lookback_hours // 24 + 1),  # Convert 48h to 3 days
                        "--max-workers", "5",  # Higher parallelism for 1500 RPM
                        "--delay", "0.1",  # Minimal delay (1500 RPM = 25 req/sec) 
                        "--batch-size", "2000"  # Larger batches for efficiency
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=300,  # 5 minute timeout per token
                        cwd=self.scripts_dir.parent.parent
                    )
                    
                    if result.returncode == 0:
                        success_count += 1
                        self.logger.debug(f"Fresh OHLCV data fetched for {token_address}")
                    else:
                        error_count += 1
                        self.logger.error(f"OHLCV fetch failed for {token_address}: {result.stderr}")
                        
                    # No delay needed between tokens (1500 RPM is very generous)
                    
                except subprocess.TimeoutExpired:
                    error_count += 1
                    self.logger.error(f"OHLCV fetch timeout for {token_address}")
                except Exception as e:
                    error_count += 1
                    self.logger.error(f"OHLCV fetch error for {token_address}: {e}")
            
            # Update statistics
            self.stats['ohlcv_runs'] += 1
            self.stats['last_ohlcv_run'] = datetime.utcnow()
            if error_count > 0:
                self.stats['total_errors'] += error_count
            
            success_rate = success_count / len(self.config.active_tokens) if self.config.active_tokens else 0
            self.logger.info(f"📊 Fresh OHLCV fetch: {success_count}/{len(self.config.active_tokens)} tokens successful ({success_rate:.1%})")
            
            # 🚨 DISABLED: Health check recording to prevent database connection spam
            # await self._record_health_check(
            #     'fresh_ohlcv_fetch',
            #     'healthy' if success_rate >= 0.8 else 'degraded',
            #     {
            #         'tokens_processed': len(self.config.active_tokens),
            #         'success_count': success_count,
            #         'error_count': error_count,
            #         'success_rate': success_rate,
            #         'lookback_hours': self.config.ohlcv_lookback_hours
            #     }
            # )
            
            return success_rate >= 0.5  # Require at least 50% success
            
        except Exception as e:
            self.logger.error(f"Fresh OHLCV fetch failed: {e}")
            # 🚨 DISABLED: Health check recording to prevent database connection spam
            # await self._record_health_check('fresh_ohlcv_fetch', 'error', {'error': str(e)})
            return False
    
    async def _fetch_fresh_social_data(self) -> bool:
        """
        Fetch fresh social data with proper rate limiting:
        - Rate limit: 10 RPM (1 req per 6 seconds) - need delays
        - API: Last 3 days (freshness buffer)  
        - Database: Scripts automatically merge with existing historical data
        """
        try:
            # Calculate delay for 10 RPM: 60 seconds / 10 requests = 6 seconds between requests
            # Add buffer for safety: 7 seconds between tokens
            tokens_count = len(self.config.active_tokens)
            estimated_time_minutes = (tokens_count * 7) / 60
            
            self.logger.info(f"🕒 Social data fetch will take ~{estimated_time_minutes:.1f} minutes for {tokens_count} tokens (10 RPM limit)")
            
            # Build command using ACTUAL script parameters (optimized for 10 RPM)
            cmd = [
                "python", str(self.social_script),
                "--days", str(self.config.social_lookback_days),  # 3 days API fetch
                "--interval", self.config.social_resolution,  # "1d" for daily
                "--batch-size", "25",  # Smaller batches for 10 RPM limit
                "--log-level", "INFO"  # Appropriate logging for scheduled runs
            ]
            # Note: No --symbol means fetch for ALL active tokens (script handles rate limiting internally)
            
            # Run with real-time output instead of capturing
            self.logger.info(f"Running social fetch command: {' '.join(cmd)}")
            
            # Run subprocess with proper output handling to prevent hanging
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,  # 5 minute timeout (should be enough even with rate limits)
                cwd=self.scripts_dir.parent.parent,
                # Add environment to ensure proper Python path
                env={**os.environ, 'PYTHONUNBUFFERED': '1'}
            )
            
            # Update statistics
            self.stats['social_runs'] += 1
            self.stats['last_social_run'] = datetime.utcnow()
            
            if result.returncode == 0:
                self.logger.info("📊 Fresh social data fetch completed successfully - 10 RPM")
                
                # 🚨 DISABLED: Health check recording to prevent database connection spam
                # await self._record_health_check(
                #     'fresh_social_fetch',
                #     'healthy',
                #     {
                #         'tokens_processed': len(self.config.active_tokens),
                #         'lookback_days': self.config.social_lookback_days,
                #         'interval': self.config.social_resolution,
                #         'rate_limit_rpm': 10,
                #         'estimated_duration_minutes': estimated_time_minutes
                #     }
                # )
                return True
            else:
                self.logger.error(f"Fresh social data fetch failed: {result.stderr}")
                self.stats['total_errors'] += 1
                
                # 🚨 DISABLED: Health check recording to prevent database connection spam
                # await self._record_health_check(
                #     'fresh_social_fetch',
                #     'error',
                #     {'error': result.stderr, 'rate_limit_rpm': 10}
                # )
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("Fresh social data fetch timeout (20 min limit)")
            self.stats['total_errors'] += 1
            
            # 🚨 DISABLED: Health check recording to prevent database connection spam
            # await self._record_health_check(
            #     'fresh_social_fetch',
            #     'error',
            #     {'error': 'Timeout after 20 minutes', 'rate_limit_rpm': 10}
            # )
            return False
            
        except Exception as e:
            self.logger.error(f"Fresh social data fetch failed: {e}")
            self.stats['total_errors'] += 1
            
            # 🚨 DISABLED: Health check recording to prevent database connection spam
            # await self._record_health_check(
            #     'fresh_social_fetch',
            #     'error',
            #     {'error': str(e), 'rate_limit_rpm': 10}
            # )
            return False

    def _run_inference_and_trading_cycle_wrapper(self):
        """Thread-safe wrapper for async trading cycle"""
        try:
            # Run the async method in the event loop
            asyncio.run(self.run_inference_and_trading_cycle())
        except Exception as e:
            self.logger.error(f"Trading cycle wrapper error: {e}")

    async def start_async(self):
        """Async version of start_scheduler for integration"""
        self.logger.info("🔄 Starting scheduler async...")
        try:
            self.logger.info("🔄 About to call initialize()...")
            await self.initialize()
            self.logger.info("🔄 Initialization complete, starting scheduler...")
            self.start_scheduler()
            self.logger.info("✅ Scheduler start_async complete")
        except Exception as e:
            self.logger.error(f"❌ Scheduler start_async failed: {e}")
            raise

    async def stop_async(self):
        """Async version of stop_scheduler for integration"""
        self.stop_scheduler()

    def get_enhanced_statistics(self) -> Dict[str, Any]:
        """Get enhanced statistics including vault trading metrics"""
        base_stats = self.get_statistics()
        
        # Add vault trading metrics
        base_stats.update({
            'vault_trading': {
                'total_cycles': self.stats['inference_trading_cycles'],
                'total_trades': self.stats['vault_trades_executed'],
                'last_cycle': self.stats['last_trading_cycle'].isoformat() if self.stats['last_trading_cycle'] else None,
                'avg_trades_per_cycle': (
                    self.stats['vault_trades_executed'] / max(1, self.stats['inference_trading_cycles'])
                ),
                'cycles_per_hour': (
                    self.stats['inference_trading_cycles'] / 
                    max(1, (datetime.utcnow() - self.stats['start_time']).total_seconds() / 3600)
                )
            }
        })
        
        return base_stats
    


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_inference_scheduler_instance: Optional[HourlyInferenceScheduler] = None


async def get_inference_scheduler(config: Optional[InferenceScheduleConfig] = None) -> HourlyInferenceScheduler:
    """Get singleton inference scheduler instance"""
    global _inference_scheduler_instance
    
    if _inference_scheduler_instance is None:
        _inference_scheduler_instance = HourlyInferenceScheduler(config)
        await _inference_scheduler_instance.initialize()
    
    return _inference_scheduler_instance


async def stop_inference_scheduler():
    """Stop inference scheduler instance"""
    global _inference_scheduler_instance
    
    if _inference_scheduler_instance:
        _inference_scheduler_instance.stop_scheduler()
        _inference_scheduler_instance = None 