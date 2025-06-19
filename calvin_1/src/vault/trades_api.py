"""
Simple Trades API - Just the essentials for live trades display
"""

from typing import List, Dict, Any
from datetime import datetime, timedelta

from ..database.production_db import get_db_manager
from ..utils.logger import log

logger = log

class SimpleTradesAPI:
    """Simple API for live trades display"""
    
    def __init__(self):
        self.db_manager = None
    
    async def initialize(self):
        """Initialize database connection"""
        self.db_manager = await get_db_manager()
    
    async def get_live_trades(self, limit: int = 30) -> Dict[str, Any]:
        """
        Get recent trades with profit/loss calculation and running win rate
        
        Returns:
            Dict with trades list and win rate stats
        """
        try:
            if not self.db_manager:
                await self.initialize()
            
            # Query recent trades with profit/loss calculation
            query = """
            WITH trade_pnl AS (
                SELECT 
                    t.trade_id,
                    t.trade_type,
                    t.value_usdc,
                    t.fee_usdc,
                    t.execution_time,
                    t.tx_hash,
                    tok.symbol,
                    t.price as entry_price,
                    
                    -- Calculate P&L by comparing with current/exit price
                    CASE 
                        WHEN t.trade_type = 'buy' THEN
                            -- For buys, profit = (current_price - entry_price) * quantity - fees
                            COALESCE(
                                (SELECT (latest.close - t.price) * t.quantity - t.fee_usdc
                                 FROM ohlcv latest 
                                 WHERE latest.token_id = t.token_id 
                                 AND latest.resolution = '1m'
                                 ORDER BY latest.time DESC LIMIT 1), 
                                0
                            )
                        WHEN t.trade_type = 'sell' THEN
                            -- For sells, profit = trade_value - fees (already realized)
                            t.value_usdc - t.fee_usdc
                        ELSE 0
                    END as pnl_usdc,
                    
                    -- Mark as profitable if P&L > 0
                    CASE 
                        WHEN t.trade_type = 'sell' THEN (t.value_usdc - t.fee_usdc) > 0
                        ELSE (
                            SELECT (latest.close - t.price) * t.quantity > t.fee_usdc
                            FROM ohlcv latest 
                            WHERE latest.token_id = t.token_id 
                            AND latest.resolution = '1m'
                            ORDER BY latest.time DESC LIMIT 1
                        )
                    END as is_profitable,
                    
                    ROW_NUMBER() OVER (ORDER BY t.execution_time DESC) as trade_rank
                    
                FROM trades t
                INNER JOIN tokens tok ON t.token_id = tok.token_id
                WHERE t.execution_time >= NOW() - INTERVAL '24 hours'
                ORDER BY t.execution_time DESC
                LIMIT $1
            ),
            running_stats AS (
                SELECT 
                    *,
                    -- Calculate running win rate
                    (COUNT(*) FILTER (WHERE is_profitable) OVER (
                        ORDER BY trade_rank 
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::FLOAT / 
                    COUNT(*) OVER (
                        ORDER BY trade_rank 
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) * 100) as running_win_rate
                FROM trade_pnl
            )
            SELECT * FROM running_stats
            ORDER BY execution_time DESC
            """
            
            async with self.db_manager.pg_pool.acquire() as conn:
                rows = await conn.fetch(query, limit)
                
                trades = []
                current_win_rate = 0
                
                for row in rows:
                    pnl = float(row['pnl_usdc']) if row['pnl_usdc'] else 0
                    
                    trade = {
                        'id': row['trade_id'],
                        'time': row['execution_time'].strftime('%H:%M:%S') if row['execution_time'] else '',
                        'trade': f"{row['trade_type'].upper()} {row['symbol']}",
                        'amount': f"${float(row['value_usdc']):.0f}" if row['value_usdc'] else '$0',
                        'pnl': pnl,
                        'pnl_formatted': f"${pnl:+.2f}" if pnl != 0 else "pending",
                        'is_profitable': row['is_profitable'],
                        'win_rate': float(row['running_win_rate']) if row['running_win_rate'] else 0,
                        'tx_hash': row['tx_hash']
                    }
                    trades.append(trade)
                
                # Get overall stats
                if trades:
                    current_win_rate = trades[0]['win_rate']  # Most recent win rate
                
                total_pnl = sum(t['pnl'] for t in trades if t['pnl'] != 0)
                
                result = {
                    'trades': trades,
                    'stats': {
                        'total_trades': len(trades),
                        'current_win_rate': current_win_rate,
                        'total_pnl': total_pnl,
                        'profitable_trades': sum(1 for t in trades if t['is_profitable']),
                    }
                }
                
                logger.debug(f"✅ Retrieved {len(trades)} trades, {current_win_rate:.1f}% win rate")
                return result
                
        except Exception as e:
            logger.error(f"❌ Failed to get live trades: {e}")
            return {'trades': [], 'stats': {'total_trades': 0, 'current_win_rate': 0, 'total_pnl': 0, 'profitable_trades': 0}}

# Global instance
simple_trades_api = SimpleTradesAPI()
