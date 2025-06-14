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
import logging
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
from ..config import get_config


@dataclass
class InferenceScheduleConfig:
    """Configuration for inference data scheduling"""
    # OHLCV data settings
    ohlcv_interval_minutes: int = 60  # Fetch every hour
    ohlcv_lookback_hours: int = 24   # Get last 24 hours of data
    ohlcv_resolution: str = "1H"     # Hourly resolution for inference
    
    # Social data settings - UPDATED for Phase 3.2
    social_interval_minutes: int = 60   # CHANGED: Fetch every hour (was 180) for model feature consistency
    social_lookback_days: int = 7      # Get last week of social data
    social_resolution: str = "1d"      # Daily social data
    
    # Token management
    active_tokens: List[str] = field(default_factory=list)  # Token addresses
    
    # Infrastructure settings
    max_retries: int = 3
    retry_delay_minutes: int = 5
    health_check_interval_minutes: int = 15
    
    # NEW: Trading execution settings
    min_viable_tokens: int = 5  # Minimum tokens ready for inference to trigger trading


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
        self.logger = logging.getLogger(__name__)
        
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
        
    async def initialize(self):
        """Initialize the inference scheduler"""
        try:
            # Initialize database manager if not provided
            if self.db_manager is None:
                self.db_manager = await get_db_manager()
            
            # Load active tokens if not configured
            if not self.config.active_tokens:
                await self._load_active_tokens()
            
            self.logger.info(f"Inference scheduler initialized for {len(self.config.active_tokens)} tokens")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize inference scheduler: {e}")
            raise
    
    async def _load_active_tokens(self):
        """Load active token addresses from database"""
        try:
            query = "SELECT address FROM tokens WHERE is_active = true"
            
            async with self.db_manager.pg_pool.acquire() as conn:
                rows = await conn.fetch(query)
            
            self.config.active_tokens = [row['address'] for row in rows]
            
            self.logger.info(f"Loaded {len(self.config.active_tokens)} active tokens")
            
        except Exception as e:
            self.logger.error(f"Failed to load active tokens: {e}")
            # Fallback to default tokens
            self.config.active_tokens = [
                'So11111111111111111111111111111111111111112',  # SOL
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC  
                'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # BONK
                'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',  # JUP
            ]
    
    def start_scheduler(self):
        """Start the enhanced inference data scheduler with vault trading"""
        if self.is_running:
            self.logger.warning("Inference scheduler already running")
            return
            
        try:
            self.is_running = True
            self.stop_event.clear()
            
            # UPDATED: Schedule complete inference + trading cycle instead of just OHLCV
            schedule.every(self.config.ohlcv_interval_minutes).minutes.do(
                self._run_inference_and_trading_cycle_wrapper
            )
            
            # UPDATED: Social data now fetched every hour (same as OHLCV)
            schedule.every(self.config.social_interval_minutes).minutes.do(
                self._run_social_fetch
            )
            
            # Health checks remain the same
            schedule.every(self.config.health_check_interval_minutes).minutes.do(
                self._run_health_check
            )
            
            # Run initial cycle
            self._run_inference_and_trading_cycle_wrapper()
            
            # Start scheduler thread
            self.scheduler_thread = threading.Thread(target=self._scheduler_loop)
            self.scheduler_thread.daemon = True
            self.scheduler_thread.start()
            
            self.logger.info(f"🚀 Enhanced inference scheduler started with vault trading")
            self.logger.info(f"⏰ OHLCV + Trading: {self.config.ohlcv_interval_minutes}min")
            self.logger.info(f"📊 Social data: {self.config.social_interval_minutes}min (hourly for model features)")
            self.logger.info(f"🔍 Health checks: {self.config.health_check_interval_minutes}min")
            
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
        """Run OHLCV data fetch for all tokens"""
        self.logger.info("Starting scheduled OHLCV data fetch")
        
        try:
            success_count = 0
            error_count = 0
            
            for token_address in self.config.active_tokens:
                try:
                    # Build command for fetch_historical_data.py
                    cmd = [
                        "python", str(self.historical_script),
                        "--token-address", token_address,
                        "--resolution", self.config.ohlcv_resolution,
                        "--days", str(self.config.ohlcv_lookback_hours // 24 + 1),  # Convert hours to days
                        "--max-workers", "1"  # Conservative for scheduled runs
                    ]
                    
                    # Run the script
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=300,  # 5 minute timeout per token
                        cwd=self.scripts_dir.parent.parent  # Run from project root
                    )
                    
                    if result.returncode == 0:
                        success_count += 1
                        self.logger.debug(f"OHLCV fetch successful for {token_address}")
                    else:
                        error_count += 1
                        self.logger.error(f"OHLCV fetch failed for {token_address}: {result.stderr}")
                        
                    # Small delay between tokens
                    time.sleep(2)
                    
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
            
            self.logger.info(f"OHLCV fetch completed: {success_count} success, {error_count} errors")
            
            # Record health check
            asyncio.create_task(self._record_health_check(
                'ohlcv_scheduler',
                'healthy' if error_count == 0 else 'degraded',
                {
                    'tokens_processed': len(self.config.active_tokens),
                    'success_count': success_count,
                    'error_count': error_count
                }
            ))
            
        except Exception as e:
            self.logger.error(f"Error in OHLCV fetch run: {e}")
            self.stats['total_errors'] += 1
            
            asyncio.create_task(self._record_health_check(
                'ohlcv_scheduler',
                'error',
                {'error': str(e)}
            ))
    
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
                
                asyncio.create_task(self._record_health_check(
                    'social_scheduler',
                    'healthy',
                    {'tokens_processed': len(self.config.active_tokens)}
                ))
            else:
                self.logger.error(f"Social data fetch failed: {result.stderr}")
                self.stats['total_errors'] += 1
                
                asyncio.create_task(self._record_health_check(
                    'social_scheduler',
                    'error',
                    {'error': result.stderr}
                ))
                
        except subprocess.TimeoutExpired:
            self.logger.error("Social data fetch timeout")
            self.stats['total_errors'] += 1
            
            asyncio.create_task(self._record_health_check(
                'social_scheduler',
                'error',
                {'error': 'Timeout after 10 minutes'}
            ))
            
        except Exception as e:
            self.logger.error(f"Error in social fetch run: {e}")
            self.stats['total_errors'] += 1
            
            asyncio.create_task(self._record_health_check(
                'social_scheduler',
                'error',
                {'error': str(e)}
            ))
    
    def _run_health_check(self):
        """Run periodic health check"""
        try:
            asyncio.create_task(self._perform_health_check())
        except Exception as e:
            self.logger.error(f"Error in health check: {e}")
    
    async def _record_health_check(self, component: str, status: str, details: Dict):
        """Record health check to database"""
        try:
            if self.db_manager:
                await self.db_manager.record_health_check(component, status, details)
        except Exception as e:
            self.logger.error(f"Failed to record health check: {e}")
    
    async def _perform_health_check(self):
        """ENHANCED: Perform comprehensive health check with Redis cache monitoring"""
        try:
            health_info = {
                'scheduler_uptime_minutes': (datetime.utcnow() - self.stats['start_time']).total_seconds() / 60,
                'is_running': self.is_running,
                'ohlcv_runs': self.stats['ohlcv_runs'],
                'social_runs': self.stats['social_runs'],
                'total_errors': self.stats['total_errors']
            }
            
            # Check if last runs are recent enough
            status = 'healthy'
            now = datetime.utcnow()
            
            if self.stats['last_ohlcv_run']:
                ohlcv_age_minutes = (now - self.stats['last_ohlcv_run']).total_seconds() / 60
                health_info['last_ohlcv_age_minutes'] = ohlcv_age_minutes
                
                if ohlcv_age_minutes > self.config.ohlcv_interval_minutes * 2:
                    status = 'degraded'
            
            if self.stats['last_social_run']:
                social_age_minutes = (now - self.stats['last_social_run']).total_seconds() / 60
                health_info['last_social_age_minutes'] = social_age_minutes
                
                if social_age_minutes > self.config.social_interval_minutes * 2:
                    status = 'degraded'
            
            # ENHANCED: Add cache performance metrics with environment configuration
            try:
                from ..config.config import get_config
                env_config = get_config()
                
                cache_metrics = await self.get_cache_performance_metrics()
                cache_hit_rate_target = int(env_config.get('CACHE_HIT_RATE_TARGET', 70))
                cache_memory_limit_mb = int(env_config.get('FEATURE_CACHE_MAX_SIZE_MB', 100))
                
                health_info.update({
                    'cache_health': cache_metrics,
                    'cache_hit_rate_target': cache_hit_rate_target,
                    'cache_memory_limit_mb': cache_memory_limit_mb,
                    'cache_monitoring_enabled': env_config.get('CACHE_MONITORING_ENABLED', 'true').lower() == 'true'
                })
                
                # Determine health status based on cache performance
                cache_memory_mb = cache_metrics.get('redis_memory_used_mb', 0)
                cache_limit_mb = cache_memory_limit_mb
                
                # Check memory usage threshold (90% of limit)
                if cache_memory_mb > cache_limit_mb * 0.9:
                    status = 'degraded'
                    health_info['cache_warnings'] = health_info.get('cache_warnings', [])
                    health_info['cache_warnings'].append(f'High memory usage: {cache_memory_mb:.1f}MB / {cache_limit_mb}MB')
                
                # Check cache efficiency (if monitoring enabled)
                if health_info['cache_monitoring_enabled']:
                    cache_efficiency = cache_metrics.get('cache_efficiency_score', 0)
                    if cache_efficiency < 0.7:
                        if status == 'healthy':
                            status = 'degraded'
                        health_info['cache_warnings'] = health_info.get('cache_warnings', [])
                        health_info['cache_warnings'].append(f'Low cache efficiency: {cache_efficiency:.2f}')
                
            except Exception as cache_error:
                health_info['cache_health_error'] = str(cache_error)
                self.logger.error(f"Cache health monitoring failed: {cache_error}")
            
            await self._record_health_check('inference_scheduler_enhanced', status, health_info)
            
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
                resolution='1h'
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
            async with self.db_manager.redis_pipeline() as pipe:
                cache_keys = [f"batch_inference:{token}" for token in tokens_to_process]
                for key in cache_keys:
                    pipe.get(key)
                
                cache_results = await pipe.execute()
                
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
                    resolution='1h'
                )
                processing_time = time.time() - processing_start
                
                # PHASE 3: Cache new results using pipeline
                cache_write_start = time.time()
                async with self.db_manager.redis_pipeline() as pipe:
                    for token_address, data in new_results.items():
                        if data.get('ready_for_inference', False):
                            cache_key = f"batch_inference:{token_address}"
                            pipe.setex(
                                cache_key,
                                3600,  # 1 hour TTL
                                json.dumps(data, default=str)
                            )
                    await pipe.execute()
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
            from ..config.config import get_config
            env_config = get_config()
            
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
            from ..config.config import get_config
            env_config = get_config()
            
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
            from ..config.config import get_config
            env_config = get_config()
            
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
        
        try:
            self.logger.info("🚀 Starting inference and trading cycle")
            
            # 1. Prepare inference data (EXISTING FUNCTIONALITY)
            self.logger.info("📊 Preparing batch inference data...")
            inference_data = await self.prepare_batch_inference_data()
            ready_tokens = [addr for addr, data in inference_data.items() 
                           if data.get('ready_for_inference', False)]
            
            if len(ready_tokens) < self.config.min_viable_tokens:
                self.logger.warning(f"⚠️ Insufficient tokens ready for inference: {len(ready_tokens)}/{self.config.min_viable_tokens}")
                await self._record_vault_trading_cycle(None, [], "insufficient_tokens", cycle_start_time)
                return
            
            self.logger.info(f"✅ {len(ready_tokens)} tokens ready for inference")
            
            # 2. Generate portfolio signals (EXISTING INTEGRATION)
            self.logger.info("🧠 Generating portfolio signals...")
            from ..inference.portfolio_coordinator import generate_portfolio_signals
            portfolio_signals = await generate_portfolio_signals()
            
            if not portfolio_signals:
                self.logger.info("📊 No portfolio signals generated")
                await self._record_vault_trading_cycle(None, [], "no_signals", cycle_start_time)
                return
            
            self.logger.info(f"📈 Portfolio signals generated: {len(portfolio_signals.buy_signals)} buy, {len(portfolio_signals.sell_signals)} sell")
            
            # 3. Execute vault trades (NEW FUNCTIONALITY)
            trade_results = []
            if portfolio_signals.buy_signals:
                self.logger.info("💰 Executing vault trades...")
                
                try:
                    from ..vault.trade_executor import VaultTradeExecutor
                    executor = VaultTradeExecutor()
                    await executor.initialize()
                    
                    trade_results = await executor.execute_portfolio_trades(portfolio_signals)
                    
                    self.logger.info(f"✅ Executed {len(trade_results)} vault trades")
                    if trade_results:
                        self.logger.info(f"🔗 Trade signatures: {trade_results[:3]}{'...' if len(trade_results) > 3 else ''}")
                        
                except ImportError:
                    self.logger.warning("⚠️ VaultTradeExecutor not available - running in data-only mode")
                    trade_results = []
                except Exception as e:
                    self.logger.error(f"❌ Vault trade execution failed: {e}")
                    trade_results = []
            else:
                self.logger.info("📊 No buy signals to execute")
            
            # 4. Record successful trading cycle in database
            await self._record_vault_trading_cycle(portfolio_signals, trade_results, "completed", cycle_start_time)
            
            # Update statistics
            self.stats['inference_trading_cycles'] += 1
            self.stats['vault_trades_executed'] += len(trade_results)
            self.stats['last_trading_cycle'] = cycle_start_time
            
            cycle_duration = (datetime.utcnow() - cycle_start_time).total_seconds()
            self.logger.info(f"🏁 Inference and trading cycle completed in {cycle_duration:.1f}s")
            
        except Exception as e:
            self.logger.error(f"❌ Inference and trading cycle failed: {e}")
            
            # Record error for monitoring
            await self._record_health_check('trading_cycle', 'error', {'error': str(e)})
            await self._record_vault_trading_cycle(None, [], "error", cycle_start_time, str(e))

    async def _record_vault_trading_cycle(self, signals, results: List[str], status: str, 
                                        cycle_start: datetime, error: str = None):
        """
        Record trading cycle results in TimescaleDB using enhanced portfolio_cycles table
        
        Args:
            signals: PortfolioSignal object or None
            results: List of transaction signatures
            status: Cycle status ('completed', 'no_signals', 'insufficient_tokens', 'error')
            cycle_start: Cycle start timestamp
            error: Error message if status is 'error'
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
                correlation_risk=None,  # TODO: Calculate correlation risk
                # Performance metrics - CORRECTED FIELD NAMES
                total_portfolio_value_usdc=portfolio_value,
                available_cash_usdc=None,  # TODO: Get from vault state
                execution_priority=getattr(signals, 'execution_priority', None) if signals else None,
                # Execution timing - CORRECTED FIELD NAMES
                data_fetch_duration_ms=None,  # TODO: Track timing
                inference_duration_ms=None,   # TODO: Track timing
                signal_processing_duration_ms=None,  # TODO: Track timing
                trade_execution_duration_ms=None,    # TODO: Track timing
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
            
            await self._record_health_check('vault_trading_cycle', 
                                           'healthy' if status == 'completed' else 'degraded', 
                                           cycle_summary)
            
            # Record individual trade executions for monitoring
            if results:
                for i, tx_sig in enumerate(results):
                    trade_data = {
                        'cycle_timestamp': cycle_start,
                        'trade_index': i,
                        'transaction_signature': tx_sig,
                        'status': 'executed'
                    }
                    await self._record_health_check('vault_trade_execution', 'healthy', trade_data)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to record trading cycle: {e}")
            # Fallback to basic health check recording
            try:
                await self._record_health_check('vault_trading_cycle', 'error', {
                    'timestamp': cycle_start,
                    'status': status,
                    'error': str(e),
                    'original_error': error
                })
            except Exception as fallback_error:
                self.logger.error(f"❌ Fallback recording also failed: {fallback_error}")

    def _run_inference_and_trading_cycle_wrapper(self):
        """Thread-safe wrapper for async trading cycle"""
        try:
            # Run the async method in the event loop
            asyncio.create_task(self.run_inference_and_trading_cycle())
        except Exception as e:
            self.logger.error(f"Trading cycle wrapper error: {e}")

    async def start_async(self):
        """Async version of start_scheduler for integration"""
        await self.initialize()
        self.start_scheduler()

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