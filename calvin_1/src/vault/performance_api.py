"""
Simple Performance API - Portfolio performance statistics for live dashboard display
"""

from typing import Dict, Any
from datetime import datetime, timedelta
import asyncio

from ..database.production_db import get_db_manager
from ..utils.logger import log

logger = log

class SimplePerformanceAPI:
    """Simple API for live portfolio performance display"""
    
    def __init__(self):
        self.db_manager = None
    
    async def initialize(self):
        """Initialize database connection"""
        self.db_manager = await get_db_manager()
    
    async def get_live_performance(self) -> Dict[str, Any]:
        """
        Get current portfolio performance statistics
        
        Returns:
            Dict with performance metrics for different time periods
        """
        try:
            if not self.db_manager:
                await self.initialize()
            
            # Get performance metrics for different time periods
            performance_24h = await self._get_portfolio_performance(hours_back=24)
            performance_7d = await self._get_portfolio_performance(hours_back=168)  # 7 days
            performance_30d = await self._get_portfolio_performance(hours_back=720)  # 30 days
            performance_ytd = await self._get_portfolio_performance_ytd()
            
            # Calculate percentage returns
            performance_stats = {
                "24h": await self._calculate_percentage_return(performance_24h, hours_back=24),
                "7d": await self._calculate_percentage_return(performance_7d, hours_back=168),
                "30d": await self._calculate_percentage_return(performance_30d, hours_back=720),
                "ytd": await self._calculate_percentage_return_ytd()
            }
            
            result = {
                'timestamp': datetime.utcnow().isoformat(),
                'performance': performance_stats,
                'stats': {
                    'total_trades_24h': performance_24h.get('trading', {}).get('total_trades', 0),
                    'win_rate_24h': await self._get_win_rate(hours_back=24),
                    'avg_portfolio_value': performance_24h.get('portfolio_metrics', {}).get('avg_portfolio_value', 0),
                    'risk_score': performance_24h.get('portfolio_metrics', {}).get('avg_risk_score', 0)
                }
            }
            
            logger.debug(f"✅ Retrieved live performance data")
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
    
    async def _calculate_percentage_return(self, performance_data: Dict[str, Any], hours_back: int) -> float:
        """Calculate percentage return from portfolio performance data"""
        try:
            if not performance_data:
                return 0.0
            
            # Get current and historical portfolio values
            current_value = await self._get_current_portfolio_value()
            historical_value = await self._get_historical_portfolio_value(hours_back)
            
            if historical_value and historical_value > 0:
                return_pct = ((current_value - historical_value) / historical_value) * 100
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
            
            return await self._calculate_percentage_return({}, hours_since_year_start)
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate YTD return: {e}")
            return 0.0
    
    async def _get_current_portfolio_value(self) -> float:
        """Get current total portfolio value"""
        try:
            query = """
                SELECT COALESCE(AVG(total_portfolio_value_usdc), 0) as current_value
                FROM portfolio_cycles 
                WHERE cycle_timestamp >= NOW() - INTERVAL '1 hour'
                AND total_portfolio_value_usdc IS NOT NULL
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                result = await conn.fetchval(query)
                return float(result) if result else 0.0
                
        except Exception as e:
            logger.error(f"❌ Failed to get current portfolio value: {e}")
            return 0.0
    
    async def _get_historical_portfolio_value(self, hours_back: int) -> float:
        """Get historical portfolio value"""
        try:
            query = """
                SELECT total_portfolio_value_usdc
                FROM portfolio_cycles 
                WHERE cycle_timestamp <= NOW() - INTERVAL '%s hours'
                AND total_portfolio_value_usdc IS NOT NULL
                ORDER BY cycle_timestamp DESC
                LIMIT 1
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                result = await conn.fetchval(query % hours_back)
                return float(result) if result else 0.0
                
        except Exception as e:
            logger.error(f"❌ Failed to get historical portfolio value: {e}")
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

# Global instance
simple_performance_api = SimplePerformanceAPI() 