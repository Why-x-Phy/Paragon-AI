#!/usr/bin/env python3
"""
Test Enhanced Database Integration

Verifies that all the new vault trading database enhancements are working correctly.
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add calvin_1 to path
current_dir = Path(__file__).resolve().parent
calvin_dir = current_dir / "calvin_1"
sys.path.insert(0, str(calvin_dir))

from src.database.production_db import get_db_manager, TradeData, PortfolioCycleData, JupiterOperationData, EmergencyEventData
from src.utils.logger import log

logger = log

async def test_enhanced_database():
    """Test all enhanced database functionality"""
    
    print("🧪 Testing Enhanced Database Integration...")
    
    try:
        # Initialize database manager
        db_manager = await get_db_manager()
        await db_manager.health_check()
        print("✅ Database connection established")
        
        # Test 1: Enhanced Trade Recording
        print("\n📊 Test 1: Enhanced Trade Recording")
        
        # Get a token ID for testing
        token_info = await db_manager.get_token_by_symbol("BONK")
        if not token_info:
            print("❌ No BONK token found in database")
            return
        
        token_id = token_info['token_id']
        
        # Create enhanced trade data
        trade_data = TradeData(
            token_id=token_id,
            trade_type='buy',
            price=0.000025,
            quantity=1000000,
            value_usdc=25.0,
            fee_usdc=0.25,
            slippage_bps=100,
            dex_name='jupiter',
            tx_hash='test_tx_' + str(int(datetime.now().timestamp())),
            execution_time=datetime.utcnow(),
            # Enhanced vault-specific fields
            signal_confidence=0.85,
            model_version='BONK_lstm_20250528',
            signal_strength='STRONG',
            predicted_change_pct=5.2,
            cycle_timestamp=datetime.utcnow(),
            jupiter_operation_id=None  # Will be set after Jupiter operation
        )
        
        trade_id = await db_manager.record_trade(trade_data)
        print(f"✅ Enhanced trade recorded with ID: {trade_id}")
        
        # Test 2: Portfolio Cycle Recording
        print("\n🎯 Test 2: Portfolio Cycle Recording")
        
        cycle_data = PortfolioCycleData(
            cycle_timestamp=datetime.utcnow(),
            # Cycle metrics - CORRECTED FIELD NAMES
            tokens_analyzed=15,
            signals_generated=8,
            buy_signals=3,
            sell_signals=2,
            trades_executed=2,
            # Portfolio risk assessment - CORRECTED FIELD NAMES
            portfolio_risk_score=65.0,  # 0-100 scale
            max_position_size_pct=15.0,
            diversification_score=85.0,  # 0-100 scale
            correlation_risk=25.0,  # 0-100 scale
            # Performance metrics - CORRECTED FIELD NAMES
            total_portfolio_value_usdc=10000.0,
            available_cash_usdc=2000.0,
            execution_priority='HIGH',
            # Execution timing - CORRECTED FIELD NAMES
            data_fetch_duration_ms=1200,
            inference_duration_ms=3400,
            signal_processing_duration_ms=800,
            trade_execution_duration_ms=2100,
            total_cycle_duration_ms=45500,  # 45.5 seconds in ms
            # Status and metadata - CORRECTED FIELD NAMES
            cycle_status='completed',
            error_message=None
        )
        
        cycle_id = await db_manager.record_portfolio_cycle(cycle_data)
        print(f"✅ Portfolio cycle recorded with ID: {cycle_id}")
        
        # Test 3: Jupiter Operation Recording
        print("\n🪐 Test 3: Jupiter Operation Recording")
        
        jupiter_data = JupiterOperationData(
            operation_timestamp=datetime.utcnow(),  # CORRECTED: was 'operation_time'
            operation_type='quote',
            input_mint='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            output_mint='DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # BONK
            input_amount=25000000,  # 25 USDC in micro-USDC
            output_amount=1000000,  # 1M BONK
            slippage_bps=100,
            # Execution results - NEW FIELDS
            actual_output_amount=995000,  # Slightly less due to slippage
            price_impact_pct=0.05,
            fee_amount=25000,  # Fee in input token (USDC)
            fee_mint='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            # Route information - CORRECTED FIELD NAMES
            route_plan={'swaps': [{'percent': 100, 'swapInfo': {'ammKey': 'jupiter'}}]},
            market_infos={'markets': ['orca', 'raydium']},
            # Execution details - CORRECTED FIELD NAMES
            tx_hash=None,  # No tx for quotes
            success=True,
            error_message=None,
            # Performance metrics - CORRECTED FIELD NAMES
            quote_response_time_ms=250,
            swap_execution_time_ms=None  # No swap for quotes
        )
        
        jupiter_id = await db_manager.record_jupiter_operation(jupiter_data)
        print(f"✅ Jupiter operation recorded with ID: {jupiter_id}")
        
        # Update trade with Jupiter operation ID
        await db_manager.update_trade_jupiter_operation(trade_id, jupiter_id)
        print(f"✅ Trade {trade_id} linked to Jupiter operation {jupiter_id}")
        
        # Test 4: Emergency Event Recording
        print("\n🚨 Test 4: Emergency Event Recording")
        
        emergency_data = EmergencyEventData(
            event_timestamp=datetime.utcnow(),  # CORRECTED: was 'event_time'
            event_type='stop_loss',
            severity='HIGH',  # NEW REQUIRED FIELD
            token_id=token_id,
            # Trigger conditions - CORRECTED FIELD NAMES
            trigger_condition={  # NEW REQUIRED FIELD
                'trigger_type': 'price',
                'trigger_value': 0.000020,
                'threshold_value': 0.000019
            },
            current_metrics={'position_size': 1000000, 'current_price': 0.000020},
            threshold_breached={'stop_loss_price': 0.000019},
            # Response actions - CORRECTED FIELD NAMES
            action_taken='exit_position',
            positions_affected=1,
            total_value_affected_usdc=240.0,  # CORRECTED: was 'position_pnl'
            # Execution results - NEW FIELDS
            action_successful=True,
            execution_time_ms=1500,
            tx_hashes=['emergency_tx_' + str(int(datetime.now().timestamp()))],  # CORRECTED: was 'tx_signature'
            # Recovery information - NEW FIELDS
            resolved_timestamp=None,
            resolution_method=None
        )
        
        emergency_id = await db_manager.record_emergency_event(emergency_data)
        print(f"✅ Emergency event recorded with ID: {emergency_id}")
        
        # Test 5: Query Recent Data
        print("\n📈 Test 5: Query Recent Data")
        
        # Query recent portfolio cycles
        recent_cycles = await db_manager.get_recent_portfolio_cycles(limit=5)
        print(f"✅ Retrieved {len(recent_cycles)} recent portfolio cycles")
        
        # Query recent Jupiter operations
        recent_jupiter = await db_manager.get_recent_jupiter_operations(limit=5)
        print(f"✅ Retrieved {len(recent_jupiter)} recent Jupiter operations")
        
        # Query recent emergency events
        recent_emergencies = await db_manager.get_recent_emergency_events(limit=5)
        print(f"✅ Retrieved {len(recent_emergencies)} recent emergency events")
        
        # Test 6: Performance Summary
        print("\n📊 Test 6: Performance Summary")
        
        # Get trading performance for the last hour
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        
        performance = await db_manager.get_trading_performance_summary(start_time, end_time)
        print(f"✅ Trading performance summary: {performance}")
        
        print("\n🎉 All Enhanced Database Tests Passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_enhanced_database()) 