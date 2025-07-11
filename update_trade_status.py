#!/usr/bin/env python3
"""
Update POPCAT Trade Status to Successful
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "calvin_1"))

# Change to the calvin_1 directory to fix relative imports
os.chdir(project_root / "calvin_1")

from src.database.production_db import get_db_manager

async def update_popcat_trade_status():
    """Update POPCAT trade status to successful"""
    
    print("🔄 Updating POPCAT Trade Status to Confirmed")
    print("=" * 50)
    
    try:
        db_manager = await get_db_manager()
        print("✅ Database manager initialized")
        
        # Update trade ID 19 to confirmed
        trade_id = 19
        
        # Direct SQL update since the method might have issues
        query = """
        UPDATE trades 
        SET execution_status = 'confirmed', 
            confirmed_at = NOW()
        WHERE trade_id = $1
        RETURNING trade_id, execution_status, confirmed_at
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            result = await conn.fetchrow(query, trade_id)
            
            if result:
                print(f"✅ Trade {result['trade_id']} execution_status updated to '{result['execution_status']}'")
                print(f"   Confirmed at: {result['confirmed_at']}")
                
                # Verify the update
                verify_query = """
                SELECT t.trade_id, t.execution_status, t.confirmed_at, t.value_usdc, t.tx_hash, tk.symbol
                FROM trades t
                JOIN tokens tk ON t.token_id = tk.token_id
                WHERE t.trade_id = $1
                """
                
                verify_result = await conn.fetchrow(verify_query, trade_id)
                
                if verify_result:
                    print(f"\n📊 Trade Verification:")
                    print(f"  - Trade ID: {verify_result['trade_id']}")
                    print(f"  - Symbol: {verify_result['symbol']}")
                    print(f"  - Execution Status: {verify_result['execution_status']}")
                    print(f"  - Confirmed At: {verify_result['confirmed_at']}")
                    print(f"  - Value: ${verify_result['value_usdc']:.2f}")
                    print(f"  - TX: {verify_result['tx_hash'][:12]}...")
                    
                    return True
                else:
                    print("❌ Could not verify trade update")
                    return False
            else:
                print("❌ No trade found with ID 19")
                return False
                
    except Exception as e:
        print(f"❌ Failed to update trade status: {e}")
        return False

async def main():
    success = await update_popcat_trade_status()
    
    if success:
        print("\n🎉 POPCAT trade status successfully updated to 'confirmed'!")
        return 0
    else:
        print("\n❌ Failed to update trade status")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 