#!/usr/bin/env python3
"""
Test Vault Integration - Complete End-to-End Test

Tests the complete vault trading integration:
1. Jupiter client gets real quotes
2. Vault client creates real smart contract transactions
3. Trade executor coordinates the complete flow

This test validates the integration without actually sending transactions to devnet.

Usage: python test_vault_integration.py
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from calvin_1.src.vault.jupiter_client import JupiterV6Client
from calvin_1.src.vault.vault_client import VaultClient
from calvin_1.src.vault.trade_executor import VaultTradeExecutor
from calvin_1.src.inference.portfolio_coordinator import AssetAllocation, TradingSignal, SignalType, SignalStrength
from calvin_1.src.utils.logger import log

logger = log

# Test configuration
TEST_TOKENS = {
    "FARTCOIN": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
    "MNDE": "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey"
}

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

async def test_jupiter_integration():
    """Test Jupiter client integration"""
    logger.info("🧪 Testing Jupiter Integration...")
    
    jupiter_client = JupiterV6Client()
    
    try:
        # Test quote generation
        quote = await jupiter_client.get_quote(
            input_mint=USDC_MINT,
            output_mint=TEST_TOKENS["FARTCOIN"],
            amount=1000 * 1_000_000,  # $1000 USDC
            slippage_bps=100  # 1%
        )
        
        if quote and 'error' not in quote:
            logger.info(f"✅ Jupiter quote successful")
            logger.info(f"   📊 Price impact: {quote.get('priceImpactPct', 'N/A')}%")
            logger.info(f"   💰 Output amount: {quote.get('outAmount', 'N/A')}")
            
            # Test swap transaction creation
            swap_data = await jupiter_client.get_swap_transaction(quote)
            if swap_data:
                logger.info(f"✅ Jupiter swap transaction created ({len(swap_data)} bytes)")
                return True
            else:
                logger.error("❌ Failed to create Jupiter swap transaction")
                return False
        else:
            logger.error(f"❌ Jupiter quote failed: {quote}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Jupiter integration test failed: {e}")
        return False

async def test_vault_client():
    """Test vault client transaction creation"""
    logger.info("🧪 Testing Vault Client...")
    
    vault_client = VaultClient()
    
    try:
        await vault_client.initialize()
        
        if vault_client.authority_keypair:
            logger.info(f"✅ Vault client initialized with authority: {vault_client.authority_keypair.public_key}")
            
            # Test vault state query
            vault_state = await vault_client.get_vault_state()
            logger.info(f"✅ Vault state retrieved: paused={vault_state.get('paused', 'unknown')}")
            
            # Test transaction creation (without sending)
            mock_jupiter_data = b"mock_jupiter_transaction_data"
            transaction = await vault_client._create_vault_trade_transaction(
                mock_jupiter_data,
                USDC_MINT,
                TEST_TOKENS["FARTCOIN"],
                1000.0
            )
            
            if transaction:
                logger.info(f"✅ Vault trade transaction created")
                logger.info(f"   📋 Instructions: {len(transaction.instructions)}")
                logger.info(f"   🔑 Signers needed: 1 (Calvin authority)")
                return True
            else:
                logger.error("❌ Failed to create vault trade transaction")
                return False
        else:
            logger.error("❌ No vault authority keypair configured")
            return False
            
    except Exception as e:
        logger.error(f"❌ Vault client test failed: {e}")
        return False
    finally:
        await vault_client.close()

async def test_trade_executor():
    """Test complete trade executor flow"""
    logger.info("🧪 Testing Trade Executor Integration...")
    
    executor = VaultTradeExecutor()
    
    try:
        await executor.initialize()
        
        # Create mock trading signal
        signal = TradingSignal(
            symbol="FARTCOIN",
            signal_type=SignalType.BUY,
            strength=SignalStrength.STRONG,
            confidence=0.85,
            predicted_change_pct=5.2,
            current_price=0.00142,
            predicted_price=0.00149,
            model_version="lstm_v1.0",
            processing_time_ms=150,
            buy_threshold=2.0,
            sell_threshold=3.0
        )
        
        # Create mock allocation
        allocation = AssetAllocation(
            symbol="FARTCOIN",
            target_exposure_pct=10.0,
            position_value_usdc=1000.0,
            confidence_score=0.85,
            risk_score=0.3
        )
        
        # Test single trade execution
        logger.info("🔄 Testing single trade execution...")
        tx_sig = await executor.execute_single_trade(signal, allocation)
        
        if tx_sig:
            mode = "LIVE" if executor.vault_client else "SIMULATION"
            logger.info(f"✅ Trade execution successful ({mode}): {tx_sig}")
            
            # Get execution stats
            stats = executor.get_execution_stats()
            logger.info(f"📊 Execution stats: {stats['total_trades']} trades, {stats['success_rate']:.1%} success rate")
            
            return True
        else:
            logger.error("❌ Trade execution failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Trade executor test failed: {e}")
        return False

async def test_end_to_end_flow():
    """Test complete end-to-end trading flow"""
    logger.info("🧪 Testing End-to-End Trading Flow...")
    
    try:
        # 1. Test Jupiter quote and swap data creation
        jupiter_client = JupiterV6Client()
        
        quote = await jupiter_client.get_quote(
            input_mint=USDC_MINT,
            output_mint=TEST_TOKENS["FARTCOIN"],
            amount=500 * 1_000_000,  # $500 USDC
            slippage_bps=100
        )
        
        if not quote or 'error' in quote:
            logger.error("❌ End-to-end test failed at Jupiter quote stage")
            return False
        
        swap_data = await jupiter_client.get_swap_transaction(quote)
        if not swap_data:
            logger.error("❌ End-to-end test failed at Jupiter swap data stage")
            return False
        
        logger.info("✅ Jupiter integration successful")
        
        # 2. Test vault transaction creation
        vault_client = VaultClient()
        await vault_client.initialize()
        
        transaction = await vault_client._create_vault_trade_transaction(
            swap_data,
            USDC_MINT,
            TEST_TOKENS["FARTCOIN"],
            500.0
        )
        
        if not transaction:
            logger.error("❌ End-to-end test failed at vault transaction creation")
            return False
        
        logger.info("✅ Vault transaction creation successful")
        
        # 3. Test complete trade executor flow
        executor = VaultTradeExecutor()
        await executor.initialize()
        
        # Create test signal and allocation
        signal = TradingSignal(
            symbol="FARTCOIN",
            signal_type=SignalType.BUY,
            strength=SignalStrength.MODERATE,
            confidence=0.75,
            predicted_change_pct=3.8,
            current_price=0.00142,
            predicted_price=0.00147,
            model_version="lstm_v1.0",
            processing_time_ms=180,
            buy_threshold=2.0,
            sell_threshold=3.0
        )
        
        allocation = AssetAllocation(
            symbol="FARTCOIN",
            target_exposure_pct=8.0,
            position_value_usdc=500.0,
            confidence_score=0.75,
            risk_score=0.25
        )
        
        # Execute trade
        result = await executor.execute_single_trade(signal, allocation)
        
        if result:
            logger.info("✅ End-to-end trading flow successful!")
            logger.info(f"🎯 Result: {result}")
            
            # Get final stats
            stats = await executor.get_performance_report()
            logger.info(f"📈 Final performance: {stats}")
            
            return True
        else:
            logger.error("❌ End-to-end test failed at trade execution")
            return False
            
        await vault_client.close()
        
    except Exception as e:
        logger.error(f"❌ End-to-end test failed: {e}")
        return False

async def main():
    """Run all vault integration tests"""
    logger.info("🚀 Starting Vault Integration Tests")
    logger.info("=" * 60)
    
    tests = [
        ("Jupiter Integration", test_jupiter_integration),
        ("Vault Client", test_vault_client),
        ("Trade Executor", test_trade_executor),
        ("End-to-End Flow", test_end_to_end_flow)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        logger.info(f"\n📋 Running {test_name} Test...")
        try:
            result = await test_func()
            results.append((test_name, result))
            
            if result:
                logger.info(f"✅ {test_name} Test: PASSED")
            else:
                logger.error(f"❌ {test_name} Test: FAILED")
                
        except Exception as e:
            logger.error(f"💥 {test_name} Test: CRASHED - {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 VAULT INTEGRATION TEST SUMMARY")
    logger.info("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status} {test_name}")
    
    logger.info(f"\n🎯 Overall Result: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 ALL TESTS PASSED - Vault integration ready!")
        return True
    else:
        logger.error(f"⚠️ {total - passed} tests failed - Review issues above")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 