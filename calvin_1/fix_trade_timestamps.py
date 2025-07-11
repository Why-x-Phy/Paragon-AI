#!/usr/bin/env python3
"""
Fix trade timestamps - delete wrong ones and re-record with correct timestamps
"""

import asyncio
import sys
import os
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.production_db import get_db_manager, TradeData

async def fix_trade_timestamps():
    """Delete wrong trades and re-record with correct timestamps"""
    try:
        print("🔧 Fixing trade timestamps...")
        
        # Get database manager
        db_manager = await get_db_manager()
        
        # Delete the wrongly timestamped trades (trade IDs 9 and 10)
        print("🗑️ Deleting wrongly timestamped trades...")
        
        delete_query = """
        DELETE FROM trades 
        WHERE trade_id IN (9, 10) 
        AND execution_time < '2025-07-01'  -- Safety check
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            result = await conn.execute(delete_query)
            print(f"✅ Deleted {result.split()[-1]} wrongly timestamped trades")
        
        # Now record with correct timestamps
        print("📝 Recording trades with correct timestamps...")
        
        # Trade data with CORRECT timestamps
        CORRECT_TRADES = [
            {
                "tx_hash": "2VHjUHBjMK6pc7HgERkgXeVzeTR2fhbhzhF7uP4r3GHnuvwvhHYkodtXSZr9q2jiQ7sThrkaNBjBzULBa4iECtu",
                "timestamp": datetime(2025, 7, 11, 0, 6, 54),  # CORRECT: July 11, 2025
                "token_symbol": "PENGU",
                "usdc_amount": 3999.998786,
                "token_amount": 207549.3,
                "price": 3999.998786 / 207549.3
            },
            {
                "tx_hash": "3XhDQ1bkBBYUUdmRyWEPYbzKhNcB4Y4RWMWtigaAmYosjmz3rPN4qqCaUt22s85CdpWy9S2MawTitb4ENUKD9Y6E", 
                "timestamp": datetime(2025, 7, 11, 0, 7, 52),  # CORRECT: July 11, 2025
                "token_symbol": "POPCAT",
                "usdc_amount": 4000.0,
                "token_amount": 10748.871950444,
                "price": 4000.0 / 10748.871950444
            }
        ]
        
        trades_added = 0
        
        for i, trade_info in enumerate(CORRECT_TRADES):
            print(f"Recording trade {i+1}/2: {trade_info['tx_hash'][:12]}... with correct timestamp")
            
            # Get token info from cache
            token_info = None
            for token in db_manager._token_cache.values():
                if token.symbol.upper() == trade_info['token_symbol'].upper():
                    token_info = token
                    break
            
            if not token_info:
                print(f"❌ Token {trade_info['token_symbol']} not found in cache")
                continue
            
            # Create trade data with CORRECT timestamp
            trade_data = TradeData(
                token_id=token_info.token_id,
                trade_type='buy',
                price=trade_info['price'],
                quantity=trade_info['token_amount'],
                value_usdc=trade_info['usdc_amount'],
                fee_usdc=0.0,
                tx_hash=trade_info['tx_hash'],
                execution_time=trade_info['timestamp'],  # CORRECT timestamp
                slippage_bps=100,
                dex_name='jupiter',
                processing_time_ms=None,
                
                # Vault-specific fields
                signal_confidence=85.0,
                model_version="v1.0",
                signal_strength="STRONG",
                predicted_change_pct=None,
                cycle_timestamp=trade_info['timestamp'],  # CORRECT timestamp
                jupiter_operation_id=None
            )
            
            # Record in database
            trade_id = await db_manager.record_trade(trade_data)
            print(f"✅ Recorded trade {trade_id}: {trade_info['token_symbol']} - ${trade_info['usdc_amount']:,.2f}")
            print(f"   Timestamp: {trade_info['timestamp']}")
            print(f"   TX: {trade_info['tx_hash']}")
            trades_added += 1
        
        print(f"✅ Successfully fixed and recorded {trades_added}/2 trades")
        
        # Verify they show up in recent trades
        print("\n🔍 Verifying trades appear in recent queries...")
        
        verify_query = """
        SELECT trade_id, execution_time, trade_type, value_usdc, 
               (SELECT symbol FROM tokens WHERE token_id = t.token_id) as symbol
        FROM trades t 
        WHERE execution_time >= NOW() - INTERVAL '1 hour'
        ORDER BY execution_time DESC
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            rows = await conn.fetch(verify_query)
            
        print(f"📊 Found {len(rows)} recent trades:")
        for row in rows:
            print(f"  - ID {row['trade_id']}: {row['trade_type']} {row['symbol']} ${row['value_usdc']} at {row['execution_time']}")
        
        return trades_added == 2
        
    except Exception as e:
        print(f"❌ Failed to fix trade timestamps: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(fix_trade_timestamps())
    if success:
        print("\n✅ Trade timestamps fixed successfully")
    else:
        print("\n❌ Failed to fix trade timestamps") 