"""
Check what trades are actually in the database
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.production_db import ProductionDBManager
from src.utils.logger import log_manager
from datetime import datetime

logger = log_manager.get_logger("check_trades")


async def check_trades():
    """Display all trades in the database"""
    db_manager = ProductionDBManager()
    await db_manager.initialize()
    
    try:
        # Query all trades with token info
        query = """
        SELECT 
            t.trade_id,
            tok.symbol,
            t.trade_type,
            t.price,
            t.quantity,
            t.value_usdc,
            t.fee_usdc,
            t.tx_hash,
            t.execution_time,
            t.signal_confidence,
            t.model_version,
            t.predicted_change_pct,
            -- Calculate current P&L
            CASE 
                WHEN t.trade_type = 'buy' THEN
                    (SELECT (latest.close - t.price) * t.quantity
                     FROM ohlcv latest 
                     WHERE latest.token_id = t.token_id 
                     AND latest.resolution = '1H'
                     ORDER BY latest.time DESC LIMIT 1)
                ELSE 0
            END as unrealized_pnl,
            -- Get current price
            (SELECT latest.close
             FROM ohlcv latest 
             WHERE latest.token_id = t.token_id 
             AND latest.resolution = '1H'
             ORDER BY latest.time DESC LIMIT 1) as current_price
        FROM trades t
        JOIN tokens tok ON t.token_id = tok.token_id
        ORDER BY t.trade_id
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            trades = await conn.fetch(query)
        
        if not trades:
            logger.info("No trades found in database")
            return
        
        logger.info(f"\n{'='*120}")
        logger.info(f"Found {len(trades)} trades in database:")
        logger.info(f"{'='*120}\n")
        
        total_value = 0
        total_pnl = 0
        
        for trade in trades:
            logger.info(f"Trade ID: {trade['trade_id']}")
            logger.info(f"  Symbol: {trade['symbol']} ({trade['trade_type'].upper()})")
            logger.info(f"  Quantity: {trade['quantity']:.6f}")
            logger.info(f"  Entry Price: ${trade['price']:.6f}")
            logger.info(f"  Current Price: ${trade['current_price']:.6f}" if trade['current_price'] else "  Current Price: N/A")
            logger.info(f"  Trade Value: ${trade['value_usdc']:.2f}")
            logger.info(f"  Fee: ${trade['fee_usdc']:.2f}")
            
            if trade['unrealized_pnl'] is not None:
                pnl_pct = (trade['unrealized_pnl'] / trade['value_usdc']) * 100 if trade['value_usdc'] > 0 else 0
                logger.info(f"  Unrealized P&L: ${trade['unrealized_pnl']:.2f} ({pnl_pct:+.2f}%)")
                total_pnl += trade['unrealized_pnl']
            
            logger.info(f"  TX Hash: {trade['tx_hash']}")
            logger.info(f"  Execution Time: {trade['execution_time']}")
            logger.info(f"  Model: {trade['model_version']} (Confidence: {trade['signal_confidence']:.1f}%)")
            logger.info(f"  Predicted Change: {trade['predicted_change_pct']:.2f}%")
            logger.info("")
            
            total_value += trade['value_usdc']
        
        logger.info(f"{'='*120}")
        logger.info(f"SUMMARY:")
        logger.info(f"  Total Trade Value: ${total_value:,.2f}")
        logger.info(f"  Total Unrealized P&L: ${total_pnl:,.2f} ({(total_pnl/total_value)*100:+.2f}%)" if total_value > 0 else "  Total Unrealized P&L: $0.00")
        logger.info(f"{'='*120}\n")
        
    except Exception as e:
        logger.error(f"Failed to check trades: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(check_trades()) 