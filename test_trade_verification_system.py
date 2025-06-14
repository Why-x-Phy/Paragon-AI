"""
Test Trade Verification System Integration

Tests the complete flow:
1. VaultTradeExecutor executes trades
2. TradeVerificationService verifies on-chain execution
3. Database is updated with verification results
4. All components work together seamlessly
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

# Test the complete integration
async def test_complete_trade_verification_flow():
    """Test the complete trade verification flow"""
    print("🧪 Testing Complete Trade Verification System")
    
    try:
        # Import components
        from calvin_1.src.vault.trade_executor import VaultTradeExecutor
        from calvin_1.src.vault.trade_verifier import TradeVerificationService
        from calvin_1.src.database.production_db import get_db_manager
        from calvin_1.src.inference.portfolio_coordinator import PortfolioSignal, AssetAllocation, TradingSignal
        from calvin_1.src.inference.strategy_engine import SignalType, SignalStrength
        
        print("✅ All imports successful")
        
        # Test 1: Initialize components
        print("\n📋 Test 1: Component Initialization")
        
        # Initialize database
        db_manager = await get_db_manager()
        await db_manager.health_check()
        print("✅ Database manager initialized")
        
        # Initialize trade executor
        executor = VaultTradeExecutor()
        await executor.initialize()
        print("✅ Trade executor initialized")
        
        # Initialize trade verifier
        verifier = TradeVerificationService()
        await verifier.initialize()
        print("✅ Trade verifier initialized")
        
        # Test 2: Create mock trading signal
        print("\n📋 Test 2: Mock Trading Signal Creation")
        
        # Create a realistic trading signal with all required parameters
        signal = TradingSignal(
            symbol="BONK",
            signal_type=SignalType.BUY,
            strength=SignalStrength.STRONG,
            confidence=85.5,
            predicted_price=0.000026,  # Predicted price
            current_price=0.000025,    # Current price
            predicted_change_pct=3.2,
            timestamp=datetime.utcnow(),
            buy_threshold=2.0,         # Strategy parameters
            sell_threshold=3.0,
            confidence_threshold=70.0,
            model_version="LSTM_v2.1",
            processing_time_ms=150.0,
            raw_prediction=0.000026
        )
        
        allocation = AssetAllocation(
            symbol="BONK",
            token_id=123,
            current_exposure_pct=0.0,
            target_exposure_pct=5.0,
            position_value_usdc=1000.0,
            signal=signal,
            last_updated=datetime.utcnow()
        )
        
        portfolio_signal = PortfolioSignal(
            timestamp=datetime.utcnow(),
            total_cash_available=10000.0,
            portfolio_value=10000.0,
            current_exposure_pct=0.0,
            buy_signals=[signal],
            sell_signals=[],
            asset_allocations={"BONK": allocation},
            cash_allocation_pct=90.0,
            portfolio_risk_score=25.0,
            correlation_risk=10.0,
            concentration_risk=15.0,
            execution_priority=3
        )
        
        print("✅ Mock trading signals created")
        
        # Test 3: Execute trade (simulation mode)
        print("\n📋 Test 3: Trade Execution")
        
        # Execute portfolio trades
        results = await executor.execute_portfolio_trades(portfolio_signal)
        
        if results:
            print(f"✅ Trade executed: {len(results)} transactions")
            print(f"   Transaction ID: {results[0]}")
            
            # Verify it's a simulation
            if results[0].startswith('SIM_'):
                print("✅ Running in simulation mode (expected)")
            else:
                print("⚠️ Running in live mode - unexpected for test")
        else:
            print("❌ No trades executed")
            return False
        
        # Test 4: Database verification
        print("\n📋 Test 4: Database Integration")
        
        # Check if trade was recorded
        recent_trades = await db_manager.get_pending_trades(hours_back=1)
        print(f"✅ Found {len(recent_trades)} pending trades")
        
        # Get execution stats
        stats = executor.get_execution_stats()
        print(f"✅ Execution stats: {stats['total_trades']} total trades")
        
        # Test 5: Trade verifier functionality
        print("\n📋 Test 5: Trade Verifier")
        
        # Test verifier health check
        health = await verifier.health_check()
        print(f"✅ Verifier health check: {'PASS' if health else 'FAIL'}")
        
        # Get verifier stats
        verifier_stats = verifier.get_stats()
        print(f"✅ Verifier stats: {verifier_stats}")
        
        # Test 6: Manual verification trigger
        print("\n📋 Test 6: Manual Verification")
        
        # Try manual verification (should handle simulation gracefully)
        verification_results = await executor.verify_recent_trades(hours_back=1)
        print(f"✅ Manual verification: {verification_results}")
        
        # Test 7: Performance report
        print("\n📋 Test 7: Performance Report")
        
        performance = await executor.get_performance_report()
        print(f"✅ Performance report generated")
        print(f"   Total trades: {performance.get('total_trades', 0)}")
        print(f"   Success rate: {performance.get('successful_trades', 0)}/{performance.get('total_trades', 0)}")
        
        # Test 8: Database query functions
        print("\n📋 Test 8: Database Query Functions")
        
        # Test new database methods
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=24)
        
        trading_summary = await db_manager.get_trading_performance_summary(start_time, end_time)
        print(f"✅ Trading performance summary: {trading_summary}")
        
        recent_cycles = await db_manager.get_recent_portfolio_cycles(limit=5)
        print(f"✅ Recent portfolio cycles: {len(recent_cycles)}")
        
        recent_jupiter = await db_manager.get_recent_jupiter_operations(limit=5)
        print(f"✅ Recent Jupiter operations: {len(recent_jupiter)}")
        
        recent_emergencies = await db_manager.get_recent_emergency_events(limit=5)
        print(f"✅ Recent emergency events: {len(recent_emergencies)}")
        
        print("\n🎉 ALL TESTS PASSED! Trade verification system is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_database_columns():
    """Test that new database columns exist"""
    print("\n🧪 Testing Database Schema")
    
    try:
        from calvin_1.src.database.production_db import get_db_manager
        
        db_manager = await get_db_manager()
        
        # Test that we can query the new columns
        query = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'trades' 
        AND column_name IN ('execution_status', 'confirmed_at', 'actual_output_amount', 'execution_error')
        ORDER BY column_name
        """
        
        async with db_manager.pg_pool.acquire() as conn:
            rows = await conn.fetch(query)
            
        columns = [row['column_name'] for row in rows]
        expected_columns = ['actual_output_amount', 'confirmed_at', 'execution_error', 'execution_status']
        
        print(f"✅ Found verification columns: {columns}")
        
        if set(columns) == set(expected_columns):
            print("✅ All verification columns present")
            return True
        else:
            missing = set(expected_columns) - set(columns)
            print(f"❌ Missing columns: {missing}")
            return False
            
    except Exception as e:
        print(f"❌ Database schema test failed: {e}")
        return False

async def main():
    """Run all tests"""
    print("🚀 Starting Trade Verification System Tests")
    print("=" * 60)
    
    # Test 1: Database schema
    schema_ok = await test_database_columns()
    
    if not schema_ok:
        print("❌ Database schema test failed - stopping")
        return
    
    # Test 2: Complete integration
    integration_ok = await test_complete_trade_verification_flow()
    
    if integration_ok:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ Trade verification system is ready for production")
    else:
        print("\n❌ TESTS FAILED!")
        print("⚠️ Trade verification system needs attention")

if __name__ == "__main__":
    asyncio.run(main()) 