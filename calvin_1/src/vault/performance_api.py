"""
Simple Performance API - Portfolio performance statistics for live dashboard display
"""

from typing import Dict, Any
from datetime import datetime, timedelta
import asyncio
import json

from ..database.production_db import get_db_manager
from ..utils.logger import log
from ..vault.vault_client import VaultClient
from ..config.config import config
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair

logger = log

class SimplePerformanceAPI:
    """Simple API for live portfolio performance display"""
    
    def __init__(self):
        self.db_manager = None
        self.vault_client = None
        self._vault_nav_cache = {}
        self._cache_duration = 60  # Cache NAV for 60 seconds
    
    async def initialize(self):
        """Initialize database connection and vault client"""
        self.db_manager = await get_db_manager()
        
        # Initialize vault client
        try:
            # Get RPC URL from config
            rpc_url = config.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
            
            # Create dummy wallet for read-only operations
            dummy_wallet = type('MockWallet', (), {
                'publicKey': Keypair().pubkey(),
                'connected': False,
                'signTransaction': lambda x: None,
                'signAllTransactions': lambda x: None
            })()
            
            # Create connection
            connection = AsyncClient(rpc_url, commitment='confirmed')
            
            # Initialize vault client
            self.vault_client = VaultClient(dummy_wallet, connection)
            await self.vault_client.initialize()
            
            logger.info("✅ Vault client initialized for performance API")
        except Exception as e:
            logger.error(f"❌ Failed to initialize vault client: {e}")
            self.vault_client = None
    
    async def get_live_performance(self) -> Dict[str, Any]:
        """
        Get current portfolio performance statistics
        
        Returns:
            Dict with performance metrics for different time periods
        """
        try:
            if not self.db_manager:
                await self.initialize()
            
            # Get current NAV from vault
            current_nav = await self._get_current_nav_from_vault()
            
            # Store current NAV snapshot for future comparisons
            await self._store_nav_snapshot(current_nav)
            
            # Calculate performance for different time periods
            performance_stats = {
                "24h": await self._calculate_nav_based_return(hours_back=24, current_nav=current_nav),
                "7d": await self._calculate_nav_based_return(hours_back=168, current_nav=current_nav),
                "30d": await self._calculate_nav_based_return(hours_back=720, current_nav=current_nav),
                "ytd": await self._calculate_nav_based_return_ytd(current_nav=current_nav)
            }
            
            # Get trading statistics from the last 24h
            performance_24h = await self._get_portfolio_performance(hours_back=24)
            
            result = {
                'timestamp': datetime.utcnow().isoformat(),
                'performance': performance_stats,
                'stats': {
                    'total_trades_24h': performance_24h.get('trading', {}).get('total_trades', 0),
                    'win_rate_24h': await self._get_win_rate(hours_back=24),
                    'avg_portfolio_value': current_nav,
                    'risk_score': performance_24h.get('portfolio_metrics', {}).get('avg_risk_score', 0)
                },
                'nav': {
                    'current': current_nav,
                    'currency': 'USDC'
                }
            }
            
            logger.debug(f"✅ Retrieved live performance data with NAV: ${current_nav:,.2f}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to get live performance: {e}")
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'performance': {
                    "24h": 0.0,
                    "7d": 0.0,
                    "30d": 0.0,
                    "ytd": 0.0
                },
                'stats': {
                    'total_trades_24h': 0,
                    'win_rate_24h': 0.0,
                    'avg_portfolio_value': 0,
                    'risk_score': 0
                },
                'nav': {
                    'current': 0,
                    'currency': 'USDC'
                }
            }
    
    async def _get_portfolio_performance(self, hours_back: int) -> Dict[str, Any]:
        """Get portfolio performance using the database function"""
        try:
            async with self.db_manager.pg_pool.acquire() as conn:
                result = await conn.fetchval(
                    "SELECT get_portfolio_performance_summary($1)",
                    hours_back
                )
                # Parse JSON string to dictionary
                if result:
                    if isinstance(result, str):
                        import json
                        return json.loads(result)
                    else:
                        return result  # Already a dict
                return {}
        except Exception as e:
            logger.error(f"❌ Failed to get portfolio performance for {hours_back}h: {e}")
            return {}
    
    async def _get_portfolio_performance_ytd(self) -> Dict[str, Any]:
        """Get year-to-date portfolio performance"""
        try:
            # Calculate hours from start of year to now
            now = datetime.utcnow()
            start_of_year = datetime(now.year, 1, 1)
            hours_since_year_start = int((now - start_of_year).total_seconds() / 3600)
            
            return await self._get_portfolio_performance(hours_since_year_start)
        except Exception as e:
            logger.error(f"❌ Failed to get YTD performance: {e}")
            return {}
    
    async def _get_historical_portfolio_value(self, hours_back: int) -> float:
        """Get historical portfolio value"""
        try:
            query = """
                SELECT available_cash_usdc
                FROM portfolio_cycles 
                WHERE cycle_timestamp <= NOW() - INTERVAL '%s hours'
                AND available_cash_usdc IS NOT NULL
                ORDER BY cycle_timestamp DESC
                LIMIT 1
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                result = await conn.fetchval(query % hours_back)
                return float(result) if result else 0.0
                
        except Exception as e:
            logger.error(f"❌ Failed to get historical portfolio value: {e}")
            return 0.0
    
    async def _get_trading_pnl(self, hours_back: int) -> float:
        """Calculate P&L from trades in the time period"""
        try:
            query = """
                WITH trade_pnl AS (
                    SELECT 
                        t.trade_type,
                        t.value_usdc,
                        t.fee_usdc,
                        t.token_id,
                        t.price as trade_price,
                        t.quantity,
                        -- For sells, calculate P&L based on average buy price
                        CASE 
                            WHEN t.trade_type = 'sell' THEN
                                (t.value_usdc - t.fee_usdc) - 
                                COALESCE((
                                    SELECT AVG(buy.price * t.quantity)
                                    FROM trades buy
                                    WHERE buy.token_id = t.token_id
                                    AND buy.trade_type = 'buy'
                                    AND buy.execution_time < t.execution_time
                                    AND buy.cycle_timestamp IS NOT NULL
                                ), t.value_usdc)
                            ELSE 0
                        END as realized_pnl
                    FROM trades t
                    WHERE t.execution_time >= NOW() - INTERVAL '%s hours'
                    AND t.cycle_timestamp IS NOT NULL
                )
                SELECT 
                    COALESCE(SUM(realized_pnl), 0) as total_pnl
                FROM trade_pnl
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                result = await conn.fetchval(query % hours_back)
                return float(result) if result else 0.0
                
        except Exception as e:
            logger.error(f"❌ Failed to get trading P&L: {e}")
            return 0.0
    
    async def _calculate_percentage_return_from_pnl(self, hours_back: int) -> float:
        """Calculate percentage return based on trading P&L"""
        try:
            # Get P&L for the period
            pnl = await self._get_trading_pnl(hours_back)
            
            # Get average portfolio value for the period (as base)
            query = """
                SELECT AVG(available_cash_usdc) as avg_value
                FROM portfolio_cycles 
                WHERE cycle_timestamp >= NOW() - INTERVAL '%s hours'
                AND available_cash_usdc IS NOT NULL
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                avg_portfolio_value = await conn.fetchval(query % hours_back)
                avg_portfolio_value = float(avg_portfolio_value) if avg_portfolio_value else 100000.0
            
            if avg_portfolio_value > 0:
                return_pct = (pnl / avg_portfolio_value) * 100
                return round(return_pct, 2)
            
            return 0.0
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate P&L-based return: {e}")
            return 0.0

    async def _calculate_percentage_return(self, performance_data: Dict[str, Any], hours_back: int) -> float:
        """Calculate percentage return from portfolio performance data"""
        try:
            # Get current and historical portfolio values
            current_value = await self._get_current_portfolio_value()
            historical_value = await self._get_historical_portfolio_value(hours_back)
            
            # Check if we have valid historical data
            if historical_value and historical_value > 0:
                # Check if we have data old enough
                query = """
                    SELECT MIN(cycle_timestamp) as earliest
                    FROM portfolio_cycles 
                    WHERE available_cash_usdc IS NOT NULL
                """
                async with self.db_manager.pg_pool.acquire() as conn:
                    earliest_data = await conn.fetchval(query)
                    
                if earliest_data:
                    hours_of_data = (datetime.utcnow() - earliest_data.replace(tzinfo=None)).total_seconds() / 3600
                    
                    # Calculate return using available data
                    return_pct = ((current_value - historical_value) / historical_value) * 100
                    
                    if hours_of_data >= hours_back:
                        logger.debug(f"Calculated {hours_back}h return: {return_pct:.2f}% (${historical_value:,.2f} -> ${current_value:,.2f})")
                    else:
                        logger.debug(f"Calculated return since inception ({hours_of_data:.1f}h) for {hours_back}h period: {return_pct:.2f}% (${historical_value:,.2f} -> ${current_value:,.2f})")
                    
                    return round(return_pct, 2)
            
            # If no valid historical data, try to get earliest available
            query = """
                SELECT available_cash_usdc
                FROM portfolio_cycles 
                WHERE available_cash_usdc IS NOT NULL
                ORDER BY cycle_timestamp ASC
                LIMIT 1
            """
            async with self.db_manager.pg_pool.acquire() as conn:
                earliest_value = await conn.fetchval(query)
                
            if earliest_value and earliest_value > 0 and current_value > 0:
                return_pct = ((current_value - float(earliest_value)) / float(earliest_value)) * 100
                logger.debug(f"Using earliest available data for return: {return_pct:.2f}% (${float(earliest_value):,.2f} -> ${current_value:,.2f})")
                return round(return_pct, 2)
            
            return 0.0
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate percentage return: {e}")
            return 0.0
    
    async def _calculate_percentage_return_ytd(self) -> float:
        """Calculate year-to-date percentage return"""
        try:
            now = datetime.utcnow()
            start_of_year = datetime(now.year, 1, 1)
            hours_since_year_start = int((now - start_of_year).total_seconds() / 3600)
            
            # Check if we have data from the start of the year
            query = """
                SELECT MIN(cycle_timestamp) as earliest
                FROM portfolio_cycles 
                WHERE available_cash_usdc IS NOT NULL
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                earliest_data = await conn.fetchval(query)
                
                if earliest_data:
                    # Check if our data goes back to start of year
                    if earliest_data.replace(tzinfo=None) > start_of_year:
                        logger.debug(f"Using data from inception ({earliest_data}) for YTD return (requested from {start_of_year})")
                        # Use return from inception instead
                        return await self._calculate_percentage_return({}, 99999)  # Large number to get earliest data
            
            return await self._calculate_percentage_return({}, hours_since_year_start)
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate YTD return: {e}")
            return 0.0
    
    async def _get_current_portfolio_value(self) -> float:
        """Get current total portfolio value"""
        try:
            query = """
                SELECT COALESCE(AVG(available_cash_usdc), 0) as current_value
                FROM portfolio_cycles 
                WHERE cycle_timestamp >= NOW() - INTERVAL '1 hour'
                AND available_cash_usdc IS NOT NULL
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                result = await conn.fetchval(query)
                return float(result) if result else 0.0
                
        except Exception as e:
            logger.error(f"❌ Failed to get current portfolio value: {e}")
            return 0.0
    
    
    async def _get_win_rate(self, hours_back: int) -> float:
        """Get win rate for the specified time period"""
        try:
            query = """
                WITH trade_outcomes AS (
                    SELECT 
                        t.*,
                        CASE 
                            WHEN t.trade_type = 'sell' THEN 
                                CASE WHEN (t.value_usdc - t.fee_usdc) > 0 THEN true ELSE false END
                            ELSE 
                                -- For buy trades, check if current price is higher than entry price
                                CASE WHEN EXISTS (
                                    SELECT 1 FROM ohlcv o 
                                    WHERE o.token_id = t.token_id 
                                    AND o.resolution = '1m'
                                    AND o.close > t.price
                                    ORDER BY o.time DESC LIMIT 1
                                ) THEN true ELSE false END
                        END as is_profitable
                    FROM trades t
                    WHERE t.execution_time >= NOW() - INTERVAL '%s hours'
                    AND t.cycle_timestamp IS NOT NULL  -- Only vault trades
                )
                SELECT 
                    CASE 
                        WHEN COUNT(*) > 0 THEN 
                            (COUNT(*) FILTER (WHERE is_profitable = true)::FLOAT / COUNT(*)) * 100
                        ELSE 0 
                    END as win_rate
                FROM trade_outcomes
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                result = await conn.fetchval(query % hours_back)
                return round(float(result), 1) if result else 0.0
                
        except Exception as e:
            logger.error(f"❌ Failed to get win rate: {e}")
            return 0.0

    async def _get_current_nav_from_vault(self) -> float:
        """Get current NAV directly from the vault smart contract"""
        try:
            # Check cache first
            cache_key = 'current_nav'
            if cache_key in self._vault_nav_cache:
                cached_time, cached_value = self._vault_nav_cache[cache_key]
                if (datetime.utcnow() - cached_time).total_seconds() < self._cache_duration:
                    return cached_value
            
            if not self.vault_client:
                logger.warning("Vault client not initialized, falling back to database")
                # Try to get the most recent available_cash_usdc as proxy for NAV
                query = """
                    SELECT available_cash_usdc
                    FROM portfolio_cycles 
                    WHERE available_cash_usdc IS NOT NULL
                    ORDER BY cycle_timestamp DESC
                    LIMIT 1
                """
                async with self.db_manager.pg_pool.acquire() as conn:
                    latest_cash = await conn.fetchval(query)
                    if latest_cash:
                        return float(latest_cash)
                return await self._get_current_portfolio_value()
            
            # Get vault state which includes NAV
            vault_state = await self.vault_client.get_vault_state()
            
            # Extract NAV (total value locked)
            nav_usdc = vault_state.get('total_nav_usdc', 0)
            
            # If NAV is 0, try to get it from other fields
            if nav_usdc == 0:
                nav_usdc = vault_state.get('total_value_locked_usdc', 0)
            
            # Convert from lamports if needed (USDC has 6 decimals)
            if nav_usdc > 1e9:  # Likely in lamports
                nav_usdc = nav_usdc / 1e6
            
            # If still 0, use available_cash_usdc from latest portfolio cycle
            if nav_usdc == 0:
                query = """
                    SELECT available_cash_usdc
                    FROM portfolio_cycles 
                    WHERE available_cash_usdc IS NOT NULL
                    ORDER BY cycle_timestamp DESC
                    LIMIT 1
                """
                async with self.db_manager.pg_pool.acquire() as conn:
                    latest_cash = await conn.fetchval(query)
                    if latest_cash:
                        nav_usdc = float(latest_cash)
                        logger.info(f"Using available_cash_usdc as NAV proxy: ${nav_usdc:,.2f}")
            
            # Cache the value
            self._vault_nav_cache[cache_key] = (datetime.utcnow(), nav_usdc)
            
            logger.debug(f"✅ Got NAV from vault: ${nav_usdc:,.2f}")
            return nav_usdc
            
        except Exception as e:
            logger.error(f"❌ Failed to get NAV from vault: {e}")
            # Fallback to database method
            return await self._get_current_portfolio_value()
    
    async def _store_nav_snapshot(self, nav_usdc: float):
        """Store NAV snapshot for historical comparison"""
        try:
            # Create table if it doesn't exist
            async with self.db_manager.pg_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS nav_snapshots (
                        snapshot_time TIMESTAMPTZ PRIMARY KEY DEFAULT NOW(),
                        nav_usdc DECIMAL(20,8) NOT NULL,
                        source VARCHAR(50) DEFAULT 'vault'
                    )
                """)
                
                # Insert snapshot (but not too frequently)
                await conn.execute("""
                    INSERT INTO nav_snapshots (nav_usdc)
                    SELECT $1
                    WHERE NOT EXISTS (
                        SELECT 1 FROM nav_snapshots 
                        WHERE snapshot_time > NOW() - INTERVAL '5 minutes'
                    )
                """, nav_usdc)
                
        except Exception as e:
            logger.error(f"Failed to store NAV snapshot: {e}")
    
    async def _calculate_nav_based_return(self, hours_back: int, current_nav: float) -> float:
        """Calculate percentage return based on NAV changes"""
        try:
            async with self.db_manager.pg_pool.acquire() as conn:
                # First check if we have data old enough
                query = """
                    SELECT MIN(cycle_timestamp) as earliest
                    FROM portfolio_cycles 
                    WHERE available_cash_usdc IS NOT NULL
                """
                
                earliest_data = await conn.fetchval(query)
                
                if earliest_data:
                    hours_of_data = (datetime.utcnow() - earliest_data.replace(tzinfo=None)).total_seconds() / 3600
                    
                    # If we don't have enough data, use the earliest data we have
                    if hours_of_data < hours_back:
                        logger.debug(f"Not enough data for {hours_back}h return (only have {hours_of_data:.1f}h), using earliest available data")
                        # Get the earliest value we have
                        query = """
                            SELECT available_cash_usdc
                            FROM portfolio_cycles 
                            WHERE available_cash_usdc IS NOT NULL
                            ORDER BY cycle_timestamp ASC
                            LIMIT 1
                        """
                        
                        earliest_cash = await conn.fetchval(query)
                        
                        if earliest_cash and earliest_cash > 0:
                            return_pct = ((current_nav - float(earliest_cash)) / float(earliest_cash)) * 100
                            logger.debug(f"Calculated return since inception ({hours_of_data:.1f}h): {return_pct:.2f}% (${float(earliest_cash):,.2f} -> ${current_nav:,.2f})")
                            return round(return_pct, 2)
                        return 0.0
                
                # Try NAV snapshots first
                query = """
                    SELECT nav_usdc
                    FROM nav_snapshots 
                    WHERE snapshot_time <= NOW() - INTERVAL '%s hours'
                    ORDER BY snapshot_time DESC
                    LIMIT 1
                """
                
                historical_nav = await conn.fetchval(query % hours_back)
                
                if historical_nav and historical_nav > 0:
                    return_pct = ((current_nav - float(historical_nav)) / float(historical_nav)) * 100
                    return round(return_pct, 2)
                else:
                    # Fallback: Use available_cash_usdc from portfolio_cycles
                    query = """
                        SELECT available_cash_usdc
                        FROM portfolio_cycles 
                        WHERE cycle_timestamp <= NOW() - INTERVAL '%s hours'
                        AND available_cash_usdc IS NOT NULL
                        ORDER BY cycle_timestamp DESC
                        LIMIT 1
                    """
                    
                    historical_cash = await conn.fetchval(query % hours_back)
                    
                    if historical_cash and historical_cash > 0:
                        # Use cash values to calculate return
                        return_pct = ((current_nav - float(historical_cash)) / float(historical_cash)) * 100
                        logger.debug(f"Calculated {hours_back}h NAV return: {return_pct:.2f}% (${float(historical_cash):,.2f} -> ${current_nav:,.2f})")
                        return round(return_pct, 2)
                    
                    return 0.0
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate NAV-based return: {e}")
            return 0.0
    
    async def _calculate_nav_based_return_ytd(self, current_nav: float) -> float:
        """Calculate year-to-date percentage return based on NAV"""
        try:
            now = datetime.utcnow()
            start_of_year = datetime(now.year, 1, 1)
            
            # Check if we have data from the start of the year
            query = """
                SELECT MIN(cycle_timestamp) as earliest
                FROM portfolio_cycles 
                WHERE available_cash_usdc IS NOT NULL
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                earliest_data = await conn.fetchval(query)
                
                if earliest_data:
                    # Check if our data goes back to start of year
                    if earliest_data.replace(tzinfo=None) > start_of_year:
                        logger.debug(f"Using data from inception ({earliest_data}) for YTD NAV return (requested from {start_of_year})")
                        # Use return from inception instead
                        hours_since_year_start = 99999  # Large number to get earliest data
                    else:
                        hours_since_year_start = int((now - start_of_year).total_seconds() / 3600)
                else:
                    hours_since_year_start = int((now - start_of_year).total_seconds() / 3600)
                    
            return await self._calculate_nav_based_return(hours_since_year_start, current_nav)
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate YTD NAV return: {e}")
            return 0.0

# Global instance
simple_performance_api = SimplePerformanceAPI() 