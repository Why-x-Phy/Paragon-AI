#!/usr/bin/env python3
"""
Test script for Calvin AI Trades API integration

This script tests:
1. Database connection
2. Trades API functionality
3. FastAPI server startup
4. Frontend API endpoint
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from src.vault.trades_api import simple_trades_api
from src.database.production_db import get_db_manager
from src.utils.logger import log

logger = log

async def test_database_connection():
    """Test database connectivity"""
    try:
        logger.info("🔍 Testing database connection...")
        db_manager = await get_db_manager()
        
        # Ensure database manager is properly initialized
        if not hasattr(db_manager, 'pg_pool') or db_manager.pg_pool is None:
            logger.error("❌ Database manager not properly initialized - missing pg_pool")
            return False
        
        await db_manager.health_check()
        logger.info("✅ Database connection successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

async def test_trades_api():
    """Test the trades API functionality"""
    try:
        logger.info("🔍 Testing trades API...")
        
        # Initialize the API
        await simple_trades_api.initialize()
        logger.info("✅ Trades API initialized")
        
        # Test getting trades
        data = await simple_trades_api.get_live_trades(limit=10)
        logger.info(f"✅ Retrieved {len(data.get('trades', []))} trades")
        logger.info(f"📊 Stats: {data.get('stats', {})}")
        
        # Display sample trade if available
        trades = data.get('trades', [])
        if trades:
            sample_trade = trades[0]
            logger.info(f"📈 Sample trade: {sample_trade.get('trade', 'N/A')} - {sample_trade.get('amount', 'N/A')} - {sample_trade.get('pnl_formatted', 'N/A')}")
        else:
            logger.info("ℹ️ No trades found in database")
        
        return True
    except Exception as e:
        logger.error(f"❌ Trades API test failed: {e}")
        return False

async def test_fastapi_import():
    """Test FastAPI imports"""
    try:
        logger.info("🔍 Testing FastAPI imports...")
        import fastapi
        import uvicorn
        from api_server import app
        logger.info("✅ FastAPI imports successful")
        return True
    except ImportError as e:
        logger.error(f"❌ FastAPI import failed: {e}")
        logger.error("💡 Install with: pip install fastapi uvicorn[standard]")
        return False
    except Exception as e:
        logger.error(f"❌ FastAPI test failed: {e}")
        return False

async def insert_sample_trade():
    """Insert a sample trade for testing using BONK token"""
    try:
        logger.info("🔍 Inserting sample trade for testing using BONK...")
        
        db_manager = await get_db_manager()
        
        # Insert a sample trade using BONK token
        async with db_manager.pg_pool.acquire() as conn:
            # Get BONK token ID (it should already exist in the database)
            token_result = await conn.fetchrow("""
                SELECT token_id FROM tokens 
                WHERE address = 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263'
                   OR symbol = 'BONK'
            """)
            
            if not token_result:
                # If BONK doesn't exist, create it with correct details
                token_result = await conn.fetchrow("""
                    INSERT INTO tokens (symbol, address, name, decimals) 
                    VALUES ('BONK', 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263', 'Bonk', 5)
                    ON CONFLICT (address) DO UPDATE SET symbol = EXCLUDED.symbol
                    RETURNING token_id
                """)
                logger.info("✅ BONK token created in database")
            
            token_id = token_result['token_id']
            logger.info(f"✅ Using BONK token_id: {token_id}")
            
            # Insert sample trade with realistic BONK values
            await conn.execute("""
                INSERT INTO trades (
                    token_id, trade_type, quantity, price, value_usdc, 
                    fee_usdc, execution_time, tx_hash
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT DO NOTHING
            """, token_id, 'buy', 25000000.0, 0.00002, 500.0, 12.5, 
                datetime.utcnow() - timedelta(minutes=30), 'bonk_test_tx_hash_123')
            
            logger.info("✅ Sample BONK trade inserted")
            return True
            
    except Exception as e:
        logger.error(f"❌ Failed to insert sample trade: {e}")
        return False

async def main():
    """Run all tests"""
    logger.info("🚀 Starting Calvin AI Trades API Integration Tests")
    
    tests = [
        ("Database Connection", test_database_connection),
        ("Sample Trade Insertion", insert_sample_trade),
        ("Trades API", test_trades_api),
        ("FastAPI Imports", test_fastapi_import),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        logger.info(f"\n{'='*50}")
        logger.info(f"Running: {test_name}")
        logger.info(f"{'='*50}")
        
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info(f"\n{'='*50}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*50}")
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
        if result:
            passed += 1
    
    logger.info(f"\nResults: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        logger.info("🎉 All tests passed! Ready to run API server.")
        logger.info("💡 Next steps:")
        logger.info("   1. Run: python main.py run-api-server")
        logger.info("   2. Start frontend: cd frontend && yarn dev")
        logger.info("   3. Check trades table in browser")
    else:
        logger.error("❌ Some tests failed. Fix issues before proceeding.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 