#!/usr/bin/env python3
"""
Record POPCAT Sell Trade in Database

This script records the successful POPCAT → USDC swap in the trades database
with all proper trade details and verification.
"""

import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "calvin_1"))

# Change to the calvin_1 directory to fix relative imports
os.chdir(project_root / "calvin_1")

from src.database.production_db import get_db_manager, TradeData
from src.utils.logger import log

logger = log

async def record_popcat_trade():
    """Record the POPCAT sell trade in the database"""
    
    print("📊 Recording POPCAT Sell Trade in Database")
    print("=" * 50)
    
    # Trade details from the successful swap
    trade_details = {
        'transaction_signature': '64myfzj3BGZPsWYFtN3ZwktBMH7ZzaRHuAWheH9yw4uNuvv8EvTAmodMknZU2X3Qqaed4aCBhYuGS1i5q4XxpuR4',
        'symbol': 'POPCAT',
        'trade_type': 'sell',
        'quantity': 10748871.950444,
        'price_per_token': 4102.098213 / 10748871.950444,  # Calculate price per token
        'total_value_usdc': 4102.098213,
        'price_impact_pct': 0.0010,
        'slippage_bps': 300,  # 3% slippage tolerance used
        'execution_time': datetime.utcnow(),
        'dex_name': 'jupiter',
        'processing_time_ms': 33800,  # 33.8 seconds
        'signal_confidence': 56.0,  # From the logs: 0.56 confidence
        'predicted_change_pct': -2.802,  # From the logs: -2.802% prediction
        'model_version': 'production',
        'signal_strength': 'STRONG',
        'cycle_timestamp': datetime.utcnow()
    }
    
    print(f"📋 Trade Details:")
    print(f"  - Symbol: {trade_details['symbol']}")
    print(f"  - Type: {trade_details['trade_type'].upper()}")
    print(f"  - Quantity: {trade_details['quantity']:,.6f} tokens")
    print(f"  - Price per token: ${trade_details['price_per_token']:.8f}")
    print(f"  - Total value: ${trade_details['total_value_usdc']:.2f}")
    print(f"  - Price impact: {trade_details['price_impact_pct']:.4f}%")
    print(f"  - Transaction: {trade_details['transaction_signature']}")
    print()
    
    try:
        # Initialize database manager
        db_manager = await get_db_manager()
        logger.info("✅ Database manager initialized")
        
        # Get POPCAT token ID from database
        popcat_token_id = None
        for token in db_manager._token_cache.values():
            if token.symbol.upper() == 'POPCAT':
                popcat_token_id = token.token_id
                break
        
        if not popcat_token_id:
            logger.error("❌ POPCAT token not found in database cache")
            return False
        
        print(f"✅ Found POPCAT token ID: {popcat_token_id}")
        
        # Create TradeData object
        trade_data = TradeData(
            token_id=popcat_token_id,
            trade_type=trade_details['trade_type'],
            price=trade_details['price_per_token'],
            quantity=trade_details['quantity'],
            value_usdc=trade_details['total_value_usdc'],
            fee_usdc=0.0,  # Jupiter fees are included in the price impact
            tx_hash=trade_details['transaction_signature'],
            execution_time=trade_details['execution_time'],
            slippage_bps=trade_details['slippage_bps'],
            dex_name=trade_details['dex_name'],
            processing_time_ms=trade_details['processing_time_ms'],
            
            # Vault-specific fields
            signal_confidence=trade_details['signal_confidence'],
            model_version=trade_details['model_version'],
            signal_strength=trade_details['signal_strength'],
            predicted_change_pct=trade_details['predicted_change_pct'],
            cycle_timestamp=trade_details['cycle_timestamp'],
            jupiter_operation_id=None  # Not available for manual recording
        )
        
        print("💾 Recording trade in database...")
        
        # Record the trade
        trade_id = await db_manager.record_trade(trade_data)
        
        if trade_id:
            print(f"✅ Trade recorded successfully!")
            print(f"  - Trade ID: {trade_id}")
            print(f"  - Token: POPCAT")
            print(f"  - Type: SELL")
            print(f"  - Value: ${trade_details['total_value_usdc']:.2f}")
            print(f"  - Status: Confirmed (transaction already executed)")
            
            # Update trade status to confirmed since we know it executed successfully
            try:
                await db_manager.update_trade_status(trade_id, 'confirmed')
                print(f"✅ Trade status updated to 'confirmed'")
            except Exception as e:
                logger.warning(f"⚠️ Could not update trade status: {e}")
            
            # Get trade statistics
            try:
                from datetime import timedelta
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(hours=1)
                
                stats = await db_manager.get_trading_performance_summary(start_time, end_time)
                
                print(f"\n📊 Recent Trading Performance:")
                print(f"  - Total trades (1h): {stats.get('total_trades', 0)}")
                print(f"  - Total volume (1h): ${stats.get('total_volume_usdc', 0):.2f}")
                print(f"  - Average trade size: ${stats.get('avg_trade_size_usdc', 0):.2f}")
                print(f"  - Success rate: {stats.get('success_rate', 0):.1%}")
                
            except Exception as e:
                logger.warning(f"⚠️ Could not get trading stats: {e}")
            
            return True
            
        else:
            logger.error("❌ Failed to record trade in database")
            return False
            
    except Exception as e:
        logger.error(f"❌ Failed to record POPCAT trade: {e}")
        import traceback
        traceback.print_exc()
        return False

async def verify_trade_in_database():
    """Verify the trade was recorded correctly"""
    
    print("\n🔍 Verifying Trade in Database")
    print("=" * 40)
    
    try:
        db_manager = await get_db_manager()
        
        # Query recent trades for POPCAT
        query = """
        SELECT t.trade_id, t.trade_type, t.quantity, t.value_usdc, t.price, 
               t.tx_hash, t.execution_time, t.signal_confidence, tk.symbol
        FROM trades t
        JOIN tokens tk ON t.token_id = tk.token_id
        WHERE tk.symbol = 'POPCAT' 
        AND t.execution_time > NOW() - INTERVAL '1 hour'
        ORDER BY t.execution_time DESC
        LIMIT 5
        """
        
        async with db_manager.pool.acquire() as conn:
            rows = await conn.fetch(query)
            
            if rows:
                print(f"✅ Found {len(rows)} recent POPCAT trades:")
                for row in rows:
                    print(f"  - Trade {row['trade_id']}: {row['trade_type'].upper()} {row['quantity']:,.2f} POPCAT")
                    print(f"    Value: ${row['value_usdc']:.2f}, Price: ${row['price']:.8f}")
                    print(f"    TX: {row['tx_hash'][:12]}...")
                    print(f"    Time: {row['execution_time']}")
                    print(f"    Confidence: {row['signal_confidence']:.1f}%")
                    print()
                    
                return True
            else:
                print("❌ No recent POPCAT trades found in database")
                return False
                
    except Exception as e:
        logger.error(f"❌ Failed to verify trade: {e}")
        return False

async def main():
    """Main entry point"""
    
    print("🚀 POPCAT Trade Database Recording")
    print("=" * 60)
    print("This script will record the successful POPCAT → USDC swap")
    print("in the trades database with proper trade details.")
    print()
    
    # Record the trade
    success = await record_popcat_trade()
    
    if success:
        # Verify it was recorded correctly
        await verify_trade_in_database()
        
        print("\n🎉 POPCAT trade successfully recorded in database!")
        print("✅ The trade is now part of the official trading history")
        print("✅ Portfolio performance metrics will include this trade")
        print("✅ Trade verification and reporting systems will track this")
        
        return 0
    else:
        print("\n❌ Failed to record POPCAT trade in database")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 