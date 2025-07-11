"""
Clean up duplicate backfill trades before re-running
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database.production_db import ProductionDBManager
from src.utils.logger import log_manager

logger = log_manager.get_logger("clean_backfill")


async def clean_backfill_trades():
    """Delete backfill trades to start fresh"""
    db_manager = ProductionDBManager()
    await db_manager.initialize()
    
    try:
        # Delete all BACKFILL trades
        query = """
        DELETE FROM trades 
        WHERE tx_hash LIKE 'BACKFILL_%'
        RETURNING trade_id, tx_hash
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            deleted_rows = await conn.fetch(query)
        
        if deleted_rows:
            logger.info(f"Deleted {len(deleted_rows)} backfill trades:")
            for row in deleted_rows:
                logger.info(f"  - Trade ID: {row['trade_id']}, TX: {row['tx_hash']}")
        else:
            logger.info("No backfill trades found to delete")
            
    except Exception as e:
        logger.error(f"Failed to clean backfill trades: {e}")
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(clean_backfill_trades()) 