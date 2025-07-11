"""
Clear ALL trades from the database to start fresh
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.production_db import ProductionDBManager
from src.utils.logger import log_manager

logger = log_manager.get_logger("clear_trades")


async def clear_all_trades():
    """Delete ALL trades from the database"""
    db_manager = ProductionDBManager()
    await db_manager.initialize()
    
    try:
        # First, let's see what trades exist
        query_check = """
        SELECT trade_id, tx_hash, symbol, trade_type, value_usdc, execution_time
        FROM trades t
        JOIN tokens tok ON t.token_id = tok.token_id
        ORDER BY trade_id
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            existing_trades = await conn.fetch(query_check)
        
        if existing_trades:
            logger.info(f"Found {len(existing_trades)} trades in database:")
            for trade in existing_trades:
                logger.info(f"  - ID: {trade['trade_id']}, {trade['symbol']}, ${trade['value_usdc']:.2f}, TX: {trade['tx_hash'][:20]}...")
        
        # Now delete ALL trades
        query_delete = """
        DELETE FROM trades 
        RETURNING trade_id, tx_hash
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            deleted_rows = await conn.fetch(query_delete)
        
        if deleted_rows:
            logger.info(f"\n✅ Deleted {len(deleted_rows)} trades")
        else:
            logger.info("\n✅ No trades to delete")
            
    except Exception as e:
        logger.error(f"Failed to clear trades: {e}")
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(clear_all_trades()) 