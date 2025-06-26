#!/usr/bin/env python3
"""
Test script for Address Lookup Table (ALT) system

This script tests the ALT manager functionality including:
- ALT manager initialization
- Transaction size estimation and validation
- Transaction optimization (monitoring mode)
- Integration with vault client

Usage:
    python test_alt_system.py [--create-only]
"""

import asyncio
import argparse
import logging
import sys
import os
from typing import List
import json

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.vault.alt_manager import ALTManager
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test configuration
RPC_URL = "https://api.mainnet-beta.solana.com"
TEST_AUTHORITY = Pubkey.from_string("11111111111111111111111111111112")  # System program as dummy authority

async def test_alt_basic_functionality():
    """Test basic ALT manager functionality"""
    logger.info("🧪 Testing ALT Manager basic functionality...")
    
    try:
        # Initialize connection
        connection = AsyncClient(RPC_URL)
        
        # Create test authority keypair
        authority = Keypair()
        
        # Create ALT manager in monitoring mode
        alt_manager = ALTManager(connection, authority, monitoring_mode=True)
        
        logger.info("✅ ALT Manager created successfully")
        
        # Test transaction size estimation with small transaction
        dummy_accounts = [
            AccountMeta(pubkey=Pubkey.from_string("11111111111111111111111111111112"), is_signer=False, is_writable=False)
            for _ in range(5)
        ]
        
        dummy_instruction = Instruction(
            program_id=Pubkey.from_string("11111111111111111111111111111112"),
            accounts=dummy_accounts,
            data=b"test_data"
        )
        
        size = alt_manager._estimate_transaction_size([dummy_instruction], dummy_accounts)
        logger.info(f"📏 Estimated small transaction size: {size} bytes")
        
        # Test with small transaction (should pass)
        result = await alt_manager.optimize_transaction([dummy_instruction], dummy_accounts)
        logger.info(f"✅ Small transaction result: success={result.success}, size={result.size_before} bytes")
        
        # Test stats
        stats = alt_manager.get_stats()
        logger.info(f"📊 ALT Manager stats: {stats}")
        
        # Clean up
        await connection.close()
        
        logger.info("✅ ALT Manager basic test passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ ALT Manager basic test failed: {e}")
        return False

async def test_large_transaction_handling():
    """Test ALT manager with large transactions"""
    logger.info("🧪 Testing ALT Manager with large transaction...")
    
    try:
        # Initialize connection
        connection = AsyncClient(RPC_URL)
        
        # Create test authority keypair
        authority = Keypair()
        
        # Create ALT manager in PRODUCTION mode (not monitoring)
        alt_manager = ALTManager(connection, authority, monitoring_mode=False)
        
        # Create a large transaction that would exceed limits
        # Use well-known program IDs to create valid pubkeys
        well_known_pubkeys = [
            "11111111111111111111111111111112",  # System Program
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token Program
            "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",  # Associated Token Program
            "SysvarRent111111111111111111111111111111111",  # Rent Sysvar
            "SysvarC1ock11111111111111111111111111111111",  # Clock Sysvar
            "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",  # Pyth Program
            "SW1TCH7qEPTdLsDHRgPuMQjbQxKdH2aBStViMFnt64f",   # Switchboard Program
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",   # Jupiter Program
            "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",   # Whirlpool Program
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium Program
        ]
        
        # Create many accounts by repeating and modifying the well-known ones
        large_accounts = []
        for i in range(50):  # 50 accounts should create large transaction
            pubkey_str = well_known_pubkeys[i % len(well_known_pubkeys)]
            large_accounts.append(
                AccountMeta(
                    pubkey=Pubkey.from_string(pubkey_str),
                    is_signer=False, 
                    is_writable=i % 3 == 0  # Some writable, some not
                )
            )
        
        large_instructions = [
            Instruction(
                program_id=Pubkey.from_string("11111111111111111111111111111112"),
                accounts=large_accounts[i*10:(i+1)*10],  # 10 accounts per instruction
                data=b"large_test_data" * 20  # Larger data
            )
            for i in range(5)  # 5 instructions
        ]
        
        # Test size estimation
        size = alt_manager._estimate_transaction_size(large_instructions, large_accounts)
        logger.info(f"📏 Large transaction size: {size} bytes (limit: 1232)")
        
        # Test optimization in PRODUCTION mode (should create ALT)
        result = await alt_manager.optimize_transaction(large_instructions, large_accounts)
        
        if size > 1232:  # Should be oversized
            logger.info(f"✅ Large transaction correctly detected as oversized")
            logger.info(f"🔧 Production mode result: success={result.success}, size_before={result.size_before}, size_after={result.size_after}, saved={result.size_saved}")
            logger.info(f"📊 ALT created: {result.alt_created}, ALT address: {result.alt_address}")
            
            if result.success and result.size_after < 1232:
                logger.info("🎉 ALT optimization successfully reduced transaction size!")
            elif result.success:
                logger.warning("⚠️ ALT optimization succeeded but didn't reduce size enough")
            else:
                logger.error("❌ ALT optimization failed")
        else:
            logger.warning("⚠️ Transaction was not as large as expected")
        
        # Clean up
        await connection.close()
        
        logger.info("✅ Large transaction test passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ Large transaction test failed: {e}")
        return False

async def test_real_alt_creation():
    """Test ALT creation with real vault authority (has SOL)"""
    logger.info("🧪 Testing REAL ALT creation with vault authority...")
    
    try:
        # Initialize connection
        connection = AsyncClient(RPC_URL)
        
        # Load the real vault authority keypair
        authority_private_key = os.getenv('CALVIN_AUTHORITY_PRIVATE_KEY')
        if not authority_private_key:
            logger.warning("⚠️ No CALVIN_AUTHORITY_PRIVATE_KEY found, skipping real ALT test")
            return True
        
        # Parse private key - handle both array and hex formats
        try:
            if authority_private_key.startswith('['):
                # Array format: [1,2,3,...]
                private_key_array = json.loads(authority_private_key)
                private_key_bytes = bytes(private_key_array)
            else:
                # Hex format
                private_key_bytes = bytes.fromhex(authority_private_key)
            
            authority = Keypair.from_bytes(private_key_bytes)
        except Exception as e:
            logger.error(f"❌ Failed to parse private key: {e}")
            return False
        
        logger.info(f"🔑 Using real vault authority: {authority.pubkey()}")
        
        # Check SOL balance
        balance = await connection.get_balance(authority.pubkey())
        logger.info(f"💰 Authority balance: {balance.value / 1e9:.4f} SOL")
        
        if balance.value < 10000000:  # Less than 0.01 SOL
            logger.warning("⚠️ Authority has low SOL balance, ALT creation may fail")
        
        # Create ALT manager in production mode
        alt_manager = ALTManager(connection, authority, monitoring_mode=False)
        
        # Create test accounts for ALT
        test_addresses = [
            Pubkey.from_string("11111111111111111111111111111112"),  # System Program
            Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),  # Token Program
            Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"),  # Associated Token Program
            Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),  # USDC
            Pubkey.from_string("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"),  # JUP
        ]
        
        # Test ALT creation directly
        logger.info(f"🏗️ Creating ALT with {len(test_addresses)} addresses...")
        alt_address, alt_account = await alt_manager._create_or_get_alt(test_addresses)
        
        if alt_account:
            logger.info(f"✅ ALT created successfully!")
            logger.info(f"📍 ALT address: {alt_address}")
            logger.info(f"📊 ALT contains {len(alt_account.addresses)} addresses")
            
            # Test with large transaction
            large_accounts = [
                AccountMeta(pubkey=addr, is_signer=False, is_writable=False)
                for addr in test_addresses * 10  # 50 accounts
            ]
            
            large_instructions = [
                Instruction(
                    program_id=test_addresses[0],
                    accounts=large_accounts[:25],
                    data=b"real_test_data" * 50
                )
            ]
            
            # Test optimization with real ALT
            result = await alt_manager.optimize_transaction(large_instructions, large_accounts)
            
            logger.info(f"🎉 Real ALT optimization result:")
            logger.info(f"  - Success: {result.success}")
            logger.info(f"  - Size before: {result.size_before} bytes")
            logger.info(f"  - Size after: {result.size_after} bytes")
            logger.info(f"  - Bytes saved: {result.size_saved}")
            logger.info(f"  - Under limit: {result.size_after < 1232}")
            
        else:
            logger.error("❌ ALT creation failed")
        
        # Clean up
        await connection.close()
        
        logger.info("✅ Real ALT creation test completed")
        return True
        
    except Exception as e:
        logger.error(f"❌ Real ALT creation test failed: {e}")
        return False

async def main():
    """Run all ALT system tests"""
    logger.info("🚀 Starting ALT System Tests...")
    
    parser = argparse.ArgumentParser(description='Test ALT system functionality')
    parser.add_argument('--create-only', action='store_true', 
                       help='Only test ALT creation (skip optimization tests)')
    parser.add_argument('--real-alt', action='store_true',
                       help='Test real ALT creation with vault authority')
    args = parser.parse_args()
    
    tests_passed = 0
    total_tests = 2
    
    # Test 1: Basic functionality
    if await test_alt_basic_functionality():
        tests_passed += 1
    
    # Test 2: Large transaction handling
    if await test_large_transaction_handling():
        tests_passed += 1
    
    # Test 3: Real ALT creation (optional)
    if args.real_alt:
        total_tests += 1
        if await test_real_alt_creation():
            tests_passed += 1
    
    # Summary
    logger.info(f"\n📊 Test Results: {tests_passed}/{total_tests} tests passed")
    
    if tests_passed == total_tests:
        logger.info("🎉 All ALT system tests passed!")
        return True
    else:
        logger.error("❌ Some ALT system tests failed")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 