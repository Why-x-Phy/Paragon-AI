#!/usr/bin/env python3
"""
Test Jupiter V6 Client Implementation

Quick test to validate our Jupiter client works correctly with real API calls.
This will test the same tokens we validated earlier: FARTCOIN and MNDE.

Usage: python test_jupiter_client.py
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from calvin_1.src.vault.jupiter_client import JupiterV6Client
from calvin_1.src.utils.logger import log

logger = log

# Test token mints (from our previous testing)
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
FARTCOIN_MINT = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"  # FARTCOIN
MNDE_MINT = "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey"  # MNDE (low market cap)

async def test_jupiter_quotes():
    """Test Jupiter quote functionality"""
    print("🧪 Testing Jupiter V6 Client...")
    
    client = JupiterV6Client()
    
    try:
        await client.initialize()
        print("✅ Jupiter client initialized successfully")
        
        # Test 1: Health check
        print("\n📋 Running health check...")
        health_ok = await client.health_check()
        print(f"Health check result: {'✅ PASS' if health_ok else '❌ FAIL'}")
        
        # Test 2: FARTCOIN quote (good liquidity)
        print("\n💰 Testing FARTCOIN quote ($1000 USDC)...")
        fartcoin_quote = await client.get_quote(
            input_mint=USDC_MINT,
            output_mint=FARTCOIN_MINT,
            amount=1000_000_000,  # $1000 USDC (6 decimals)
            slippage_bps=100  # 1%
        )
        
        if fartcoin_quote:
            print("✅ FARTCOIN quote successful:")
            print(f"   Input: ${int(fartcoin_quote['inAmount']) / 1e6:.2f} USDC")
            print(f"   Output: {int(fartcoin_quote['outAmount']) / 1e6:.0f} FARTCOIN tokens")
            print(f"   Price Impact: {float(fartcoin_quote['priceImpactPct']):.4f}%")
            print(f"   Route Plan: {len(fartcoin_quote['routePlan'])} steps")
        else:
            print("❌ FARTCOIN quote failed")
        
        # Test 3: MNDE quote (lower liquidity)
        print("\n💎 Testing MNDE quote ($1000 USDC)...")
        mnde_quote = await client.get_quote(
            input_mint=USDC_MINT,
            output_mint=MNDE_MINT,
            amount=1000_000_000,  # $1000 USDC (6 decimals)
            slippage_bps=100  # 1%
        )
        
        if mnde_quote:
            print("✅ MNDE quote successful:")
            print(f"   Input: ${int(mnde_quote['inAmount']) / 1e6:.2f} USDC")
            print(f"   Output: {int(mnde_quote['outAmount']) / 1e9:.2f} MNDE tokens")  # MNDE has 9 decimals
            print(f"   Price Impact: {float(mnde_quote['priceImpactPct']):.4f}%")
            print(f"   Route Plan: {len(mnde_quote['routePlan'])} steps")
        else:
            print("❌ MNDE quote failed")
        
        # Test 4: Try to get swap transaction (will fail without proper authority)
        if fartcoin_quote:
            print("\n🔗 Testing swap transaction creation...")
            try:
                swap_data = await client.get_swap_transaction(fartcoin_quote)
                if swap_data:
                    print("✅ Swap transaction created successfully")
                    print(f"   Transaction data length: {len(swap_data)} bytes")
                else:
                    print("❌ Swap transaction creation failed (expected - no authority configured)")
            except Exception as e:
                print(f"❌ Swap transaction error (expected): {e}")
        
        # Test 5: Performance stats
        print("\n📊 Performance Statistics:")
        stats = client.get_stats()
        print(f"   Total Requests: {stats['total_requests']}")
        print(f"   Success Rate: {stats['success_rate']:.1%}")
        print(f"   Avg Response Time: {stats['avg_response_time_ms']:.1f}ms")
        print(f"   Session Active: {stats['session_active']}")
        
        print("\n🎉 Jupiter client tests completed!")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        
    finally:
        await client.close()
        print("🔌 Jupiter client session closed")

async def main():
    """Main test function"""
    print("=" * 60)
    print("🚀 Calvin AI - Jupiter V6 Client Test")
    print("=" * 60)
    
    await test_jupiter_quotes()
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")

if __name__ == "__main__":
    asyncio.run(main()) 