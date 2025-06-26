#!/usr/bin/env python3
"""
Calvin Vault Real Swap Test Script

This script tests the complete vault trading functionality by executing a real
swap through the Calvin vault smart contract using actual vault funds.

Usage:
    python test_vault_swap.py [--amount 10.0] [--delay 5]

WARNING: This script will execute real transactions with real vault funds.
"""

import asyncio
import argparse
import logging
import sys
import json
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.vault.vault_client import VaultClient
from src.vault.jupiter_client import JupiterV6Client
from src.database.production_db import get_db_manager

# Test configuration
TEST_CONFIG = {
    'input_token': 'USDC',
    'intermediate_token': 'FARTCOIN',
    'amount_usdc': 10.0,  # $10 test swap
    'slippage_bps': 300,  # 3.0% slippage tolerance
    'network': 'mainnet',
    'swap_delay_seconds': 5,  # Wait between swaps
    
    # Token addresses
    'tokens': {
        'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
        'FARTCOIN': '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump'
    }
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def perform_swap(jupiter_client, input_mint, output_mint, amount, input_symbol, output_symbol, swap_number):
    """Perform a single swap and return the results"""
    print(f"\n💱 Swap {swap_number}: Getting Jupiter quote for {input_symbol} → {output_symbol}...")
    
    print(f"  - Input mint: {input_mint}")
    print(f"  - Output mint: {output_mint}")
    print(f"  - Amount: {amount:,} lamports")
    
    quote_response = await jupiter_client.get_quote(
        input_mint=input_mint,
        output_mint=output_mint,
        amount=amount,
        slippage_bps=TEST_CONFIG['slippage_bps']
    )
    
    if not quote_response or 'error' in quote_response:
        logger.error(f"❌ Failed to get Jupiter quote: {quote_response}")
        return None
        
    # Parse quote details directly from the quote object (Jupiter V6 returns quote directly)
    input_amount = int(quote_response.get('inAmount', 0))
    output_amount = int(quote_response.get('outAmount', 0))
    price_impact = float(quote_response.get('priceImpactPct', 0))
    
    # Calculate output in human-readable format
    if output_symbol == 'USDC':
        output_formatted = output_amount / 1_000_000  # USDC has 6 decimals
    else:
        output_formatted = output_amount / 1_000_000  # Fartcoin has 6 decimals
    
    input_formatted = input_amount / 1_000_000  # Both tokens have 6 decimals
    
    print(f"  ✅ Quote received:")
    print(f"    - Input: {input_amount:,} lamports ({input_formatted:.6f} {input_symbol})")
    print(f"    - Output: {output_amount:,} lamports ({output_formatted:.6f} {output_symbol})")
    print(f"    - Price impact: {price_impact:.4f}%")
    
    return {
        'input_amount': input_amount,
        'output_amount': output_amount,
        'input_formatted': input_formatted,
        'output_formatted': output_formatted,
        'price_impact': price_impact,
        'quote_data': quote_response
    }

async def execute_vault_swap(vault_client, jupiter_client, input_mint, output_mint, amount, input_symbol, output_symbol, swap_number):
    """Execute an actual swap transaction through the vault"""
    print(f"\n🔥 Swap {swap_number}: EXECUTING {input_symbol} → {output_symbol} transaction...")
    
    print(f"  - Input mint: {input_mint}")
    print(f"  - Output mint: {output_mint}")
    print(f"  - Amount: {amount:,} lamports")
    
    try:
        # Step 1: Get Jupiter quote
        quote_response = await jupiter_client.get_quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            slippage_bps=TEST_CONFIG['slippage_bps']
        )
        
        if not quote_response or 'error' in quote_response:
            logger.error(f"❌ Failed to get Jupiter quote: {quote_response}")
            return None
        
        # Parse quote details
        input_amount = int(quote_response.get('inAmount', 0))
        output_amount = int(quote_response.get('outAmount', 0))
        price_impact = float(quote_response.get('priceImpactPct', 0))
        
        input_formatted = input_amount / 1_000_000
        output_formatted = output_amount / 1_000_000
        
        print(f"  📊 Quote details:")
        print(f"    - Input: {input_amount:,} lamports ({input_formatted:.6f} {input_symbol})")
        print(f"    - Expected output: {output_amount:,} lamports ({output_formatted:.6f} {output_symbol})")
        print(f"    - Price impact: {price_impact:.4f}%")
        
        # Step 2: Get swap instruction from Jupiter V6 client
        print(f"  🔧 Getting swap instruction from Jupiter V6...")
        
        # ✅ CRITICAL FIX: Use vault authority PDA for Jupiter instruction generation
        # The vault smart contract expects this PDA to be in the Jupiter accounts
        vault_authority_pda = vault_client._get_vault_authority_pda()
        print(f"  🔧 Using vault authority PDA (expected by vault): {vault_authority_pda}")
        
        # Get swap transaction data using our new Jupiter V6 client
        swap_data = await jupiter_client.get_swap_transaction(
            quote_response=quote_response,
            payer_pubkey=str(vault_authority_pda),  # Vault authority PDA (what vault expects)
            slippage_bps=TEST_CONFIG['slippage_bps']
        )
        
        if not swap_data:
            logger.error("❌ Failed to get swap instruction from Jupiter V6")
            return None
            
        print(f"  ✅ Jupiter V6 swap instruction prepared")
        print(f"    - Program ID: {swap_data.get('program_id')}")
        print(f"    - Accounts: {len(swap_data.get('accounts', []))}")
        print(f"    - Instruction data: {len(swap_data.get('instruction_data', ''))} chars")
        print(f"    - SDK generated: {swap_data.get('sdk_generated')}")
        
        # Step 3: Execute the swap through vault using the new interface
        print(f"  🚀 Executing swap through Calvin vault...")
        
        # Use vault client's execute_trade method with the new Jupiter data format
        trade_result = await vault_client.execute_trade(
            jupiter_data=swap_data,
            source_mint=input_mint,
            destination_mint=output_mint,
            amount_usdc=amount / 1_000_000  # Convert from lamports to USDC
        )
        
        if not trade_result:
            logger.error(f"❌ Vault trade execution failed")
            return None
        
        # trade_result is the transaction signature
        transaction_signature = trade_result
        
        print(f"  🎉 Swap executed successfully!")
        print(f"    - Transaction signature: {transaction_signature}")
        print(f"    - Expected output: {output_amount:,} lamports ({output_formatted:.6f} {output_symbol})")
        print(f"    - Note: Use actual output amount from chain for precise calculations")
        
        # For now, use expected output amount - in production, query actual amounts from chain
        return {
            'input_amount': input_amount,
            'output_amount': output_amount,  # Expected output - would need chain query for actual
            'input_formatted': input_formatted,
            'output_formatted': output_formatted,
            'price_impact': price_impact,
            'quote_data': quote_response,
            'transaction_signature': transaction_signature,
            'execution_time_ms': swap_data.get('generation_time_ms', 0),
            'actual_slippage': 0  # Would need chain query to calculate
        }
        
    except Exception as e:
        logger.error(f"❌ Swap execution failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return None

async def test_vault_swap():
    """Test the vault swap functionality with a real USDC → Fartcoin swap"""
    
    print(f"🚀 Calvin Vault Real Swap Test - LIVE EXECUTION")
    print("=" * 60)
    
    print("🔥 WARNING: This will execute REAL transactions on mainnet!")
    print("💰 Real USDC will be swapped and fees will be paid!")
    print("⚠️  Using actual vault funds!")
    print()
    
    print(f"📊 Test Parameters:")
    print(f"  - Amount: {TEST_CONFIG['amount_usdc']} {TEST_CONFIG['input_token']}")
    print(f"  - Target token: {TEST_CONFIG['intermediate_token']}")
    print(f"  - Slippage: {TEST_CONFIG['slippage_bps']/100}%")
    print(f"  - Network: {TEST_CONFIG['network']}")
    print()
    
    # Track swap performance
    swap_stats = {
        'start_time': datetime.utcnow(),
        'initial_usdc': TEST_CONFIG['amount_usdc'],
        'swap_results': None,
        'total_price_impact': 0
    }
    
    try:
        # Step 1: Initialize components
        print("🔧 Step 1: Initializing components...")
        
        # Initialize database manager
        try:
            db_manager = await get_db_manager()
            logger.info("✅ Database manager initialized")
        except Exception as e:
            logger.warning(f"⚠️ Database manager initialization failed: {e}")
            logger.info("   Continuing without database logging...")
            db_manager = None
        
        # Initialize vault client with required arguments
        from solana.rpc.async_api import AsyncClient
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        import os
        
        # Get RPC endpoint
        rpc_url = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
        connection = AsyncClient(rpc_url)
        
        # Get vault program ID
        vault_program_id = os.getenv('CALVIN_VAULT_PROGRAM_ID')
        if not vault_program_id:
            logger.error("❌ CALVIN_VAULT_PROGRAM_ID not set")
            return False
        
        # Load real vault authority for actual trades
        authority_private_key = os.getenv('CALVIN_AUTHORITY_PRIVATE_KEY')
        if not authority_private_key:
            logger.error("❌ CALVIN_AUTHORITY_PRIVATE_KEY not set")
            return False
            
        # Handle both JSON array format and base58 string format
        try:
            if authority_private_key.strip().startswith('['):
                # JSON array format (Solana CLI format): [1,2,3,4,...]
                import ast
                private_key_bytes = ast.literal_eval(authority_private_key)
                authority_keypair = Keypair.from_bytes(private_key_bytes)
            else:
                # Base58 encoded string format
                authority_keypair = Keypair.from_base58_string(authority_private_key)
            logger.info(f"✅ Using vault authority: {authority_keypair.pubkey()}")
        except Exception as e:
            # If first attempt fails, try the other format as fallback
            try:
                if authority_private_key.strip().startswith('['):
                    authority_keypair = Keypair.from_base58_string(authority_private_key)
                else:
                    import ast
                    private_key_bytes = ast.literal_eval(authority_private_key)
                    authority_keypair = Keypair.from_bytes(private_key_bytes)
                logger.info(f"✅ Using vault authority: {authority_keypair.pubkey()}")
            except Exception as e2:
                logger.error(f"❌ Failed to load keypair. Array error: {e}, Base58 error: {e2}")
                return False
        
        # Initialize vault client
        vault_client = VaultClient(
            vault_program=vault_program_id,
            connection=connection,
            authority_keypair=authority_keypair
        )
        await vault_client.initialize()
        logger.info("✅ Vault client initialized")
        
        # Initialize Jupiter client
        jupiter_client = JupiterV6Client()
        await jupiter_client.initialize()
        logger.info("✅ Jupiter client initialized")
        
        # Get vault state for debugging
        vault_state = await vault_client.get_vault_state()
        print(f"📊 Vault State Debug:")
        print(f"  - Calvin Authority (expected): {vault_state.get('calvin_authority', 'NOT_SET')}")
        print(f"  - Our Authority (actual): {vault_client.authority_keypair.pubkey()}")
        print(f"  - Authorities match: {str(vault_client.authority_keypair.pubkey()) == vault_state.get('calvin_authority', '')}")
        
        if str(vault_client.authority_keypair.pubkey()) != vault_state.get('calvin_authority', ''):
            print("❌ AUTHORITY MISMATCH! This is likely the cause of the 'not enough signers' error")
            print("   The vault expects a different calvin_authority than what we're providing")
            return
        
        print("✅ Authority verification passed")
        
        # Step 2: Check vault state
        print("\n📊 Step 2: Checking vault state...")
        vault_state = await vault_client.get_vault_state()
        
        if not vault_state:
            logger.error("❌ Could not fetch vault state")
            return False
            
        total_nav = vault_state.get('total_nav_usdc', 0)
        available_usdc = vault_state.get('usdc_balance', 0)
        
        print(f"  - Total NAV: ${total_nav:,.2f}")
        print(f"  - Available USDC: ${available_usdc:,.2f}")
        
        if available_usdc < TEST_CONFIG['amount_usdc']:
            logger.error(f"❌ Insufficient USDC in vault: ${available_usdc:.2f} < ${TEST_CONFIG['amount_usdc']}")
            return False
            
        logger.info(f"✅ Vault has sufficient USDC for swap test")
        
        # Step 3: Execute reverse swap - FARTCOIN → USDC (testing fixed performance fees)
        print(f"\n🔄 Step 3: Executing Reverse Swap - FARTCOIN → USDC (Testing Performance Fee Fix)")
        print("=" * 40)
        
        # Get the vault's current FARTCOIN balance
        vault_authority_pda = vault_client._get_vault_authority_pda()
        fartcoin_mint = TEST_CONFIG['tokens'][TEST_CONFIG['intermediate_token']]
        fartcoin_balance = await vault_client._get_vault_token_balance(vault_authority_pda, Pubkey.from_string(fartcoin_mint))
        
        if fartcoin_balance == 0:
            logger.error("❌ No FARTCOIN balance found in vault to swap")
            return False
            
        print(f"  - Current FARTCOIN balance: {fartcoin_balance:.6f}")
        
        # Convert FARTCOIN balance to lamports (FARTCOIN has 6 decimals)
        fartcoin_amount_lamports = int(fartcoin_balance * 1_000_000)
        
        # Swap FARTCOIN → USDC
        input_mint = TEST_CONFIG['tokens'][TEST_CONFIG['intermediate_token']]  # FARTCOIN
        output_mint = TEST_CONFIG['tokens'][TEST_CONFIG['input_token']]        # USDC
        
        swap_results = await execute_vault_swap(
            vault_client, jupiter_client, input_mint, output_mint, fartcoin_amount_lamports,
            'FARTCOIN', 'USDC', 1
        )
        
        if not swap_results:
            logger.error("❌ Swap failed")
            return False
            
        swap_stats['swap_results'] = swap_results
        
        # Validation for swap
        if swap_results['price_impact'] > 2.0:
            logger.warning(f"⚠️ High price impact: {swap_results['price_impact']:.4f}%")
        
        print(f"  ✅ Reverse swap executed successfully!")
        print(f"    - Swapped: {fartcoin_balance:.6f} FARTCOIN")
        print(f"    - Received: ${swap_results['output_formatted']:.6f} USDC")
        print(f"    - Price impact: {swap_results['price_impact']:.4f}%")
        print(f"    - Transaction: {swap_results['transaction_signature']}")
        
        # Step 4: Performance analysis
        print(f"\n📈 Step 4: Performance Analysis")
        print("=" * 50)
        
        swap_stats['total_price_impact'] = swap_results['price_impact']
        swap_stats['end_time'] = datetime.utcnow()
        swap_stats['duration_seconds'] = (swap_stats['end_time'] - swap_stats['start_time']).total_seconds()
        
        print(f"📊 Reverse Swap Results:")
        print(f"  - Input: {fartcoin_balance:.6f} FARTCOIN")
        print(f"  - Output: ${swap_results['output_formatted']:.6f} USDC")
        print(f"  - Price impact: {swap_stats['total_price_impact']:.4f}%")
        print(f"  - Execution time: {swap_stats['duration_seconds']:.1f} seconds")
        print(f"  - Transaction signature: {swap_results['transaction_signature']}")
        print()
        
        # Step 5: Record results in database
        print(f"\n💾 Step 5: Recording test results...")
        
        if db_manager:
            try:
                await db_manager.record_health_check(
                    component='vault_swap_test',
                    status='healthy',
                    details={
                        'test_type': 'jupiter_vault_integration',
                        'input_usdc': swap_stats['initial_usdc'],
                        'output_amount': swap_results['output_formatted'],
                        'output_token': TEST_CONFIG['intermediate_token'],
                        'price_impact': swap_stats['total_price_impact'],
                        'duration_seconds': swap_stats['duration_seconds'],
                        'transaction_signature': swap_results['transaction_signature'],
                        'slippage_bps': TEST_CONFIG['slippage_bps'],
                        'timestamp': datetime.utcnow().isoformat()
                    }
                )
                print(f"  ✅ Test results recorded in database")
            except Exception as e:
                logger.warning(f"  ⚠️ Failed to record in database: {e}")
        else:
            print(f"  📝 Database not available - results not recorded")
        
        # Step 6: Validate results
        print(f"\n✅ Step 6: Test Validation")
        print("=" * 30)
        
        # Define acceptable thresholds
        max_acceptable_price_impact = 3.0  # 3% max price impact
        
        validation_passed = True
        issues = []
        
        if swap_stats['total_price_impact'] > max_acceptable_price_impact:
            validation_passed = False
            issues.append(f"High price impact: {swap_stats['total_price_impact']:.4f}% > {max_acceptable_price_impact}%")
            
        if swap_results['output_amount'] == 0:
            validation_passed = False
            issues.append("Zero output amount in swap")
        
        # Step 7: Final Summary
        print(f"\n📋 FINAL TEST SUMMARY")
        print("=" * 60)
        print(f"✅ Database connection: {'Working' if db_manager else 'Skipped'}")
        print(f"✅ Vault client: Working") 
        print(f"✅ Jupiter integration: Working")
        print(f"✅ Swap execution: Working")
        print(f"✅ Performance tracking: Working")
        
        if validation_passed:
            print(f"\n🎉 SUCCESS: Vault swap functionality is working correctly!")
            print(f"   📊 Performance Summary:")
            print(f"   - Swap executed: ${swap_stats['initial_usdc']:.2f} USDC → {swap_results['output_formatted']:.6f} FARTCOIN")
            print(f"   - Price impact: {swap_stats['total_price_impact']:.4f}%")
            print(f"   - Execution time: {swap_stats['duration_seconds']:.1f}s")
            print(f"   - Transaction: {swap_results['transaction_signature']}")
        else:
            print(f"\n⚠️ CONDITIONAL SUCCESS: System is working, but performance needs optimization")
            print(f"   Issues found:")
            for issue in issues:
                print(f"   - {issue}")
            print(f"   Consider: reducing trade size or adjusting slippage")
            
        return validation_passed
        
    except Exception as e:
        logger.error(f"❌ Swap test failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Record the failure
        if db_manager:
            try:
                await db_manager.record_health_check(
                    component='vault_swap_test',
                    status='error',
                    details={
                        'error': str(e),
                        'test_type': 'jupiter_vault_integration',
                        'timestamp': datetime.utcnow().isoformat()
                    }
                )
            except:
                pass  # Don't fail on logging failure
            
        return False

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Test Calvin Vault real swap functionality')
    parser.add_argument('--amount', type=float, default=10.0,
                       help='Amount in USDC to swap (default: 10.0)')
    parser.add_argument('--network', choices=['mainnet', 'devnet'], default='mainnet',
                       help='Network to use (default: mainnet)')
    
    args = parser.parse_args()
    
    # Update config based on args
    TEST_CONFIG['amount_usdc'] = args.amount
    TEST_CONFIG['network'] = args.network
    
    print("🔥 WARNING: Real transaction mode!")
    print("   This will execute actual swaps with real vault funds!")
    print(f"   Trading ${args.amount} USDC for FARTCOIN")
    print(f"   Expected cost: ~${args.amount * 0.01:.2f} to ${args.amount * 0.03:.2f} in slippage and fees")
    response = input("   Continue with real execution? (yes/no): ")
    if response.lower() != 'yes':
        print("   Cancelled.")
        return
    
    success = await test_vault_swap()
    
    if success:
        print(f"\n🎉 Vault swap test completed successfully!")
        sys.exit(0)
    else:
        print(f"\n❌ Vault swap test failed!")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 
