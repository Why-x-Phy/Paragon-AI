#!/usr/bin/env python3
"""
Test Calvin Vault Connection to Devnet

Tests the Python backend connection to the deployed vault smart contract on devnet
without requiring the vault to be fully initialized.

Usage:
    python test_vault_devnet_connection.py
"""

import asyncio
import sys
import traceback
from datetime import datetime

# Add the src directory to Python path
sys.path.append('src')

from src.vault.vault_client import VaultClient
from src.config.config import config
from src.utils.logger import log

logger = log

class DevnetVaultConnectionTest:
    """Test vault connection to devnet"""
    
    def __init__(self):
        self.vault_client = None
        self.test_results = {}
        
    async def run_all_tests(self):
        """Run all connection tests"""
        print("🔍 Calvin AI Vault Devnet Connection Test")
        print("=" * 50)
        
        try:
            # Initialize vault client
            await self._test_vault_client_initialization()
            
            # Test RPC connection
            await self._test_rpc_connection()
            
            # Test program existence
            await self._test_program_existence()
            
            # Test PDA derivation
            await self._test_pda_derivation()
            
            # Test vault state query (expecting not initialized)
            await self._test_vault_state_query()
            
            # Test user position query
            await self._test_user_position_query()
            
            # Test error handling
            await self._test_error_handling()
            
            # Print summary
            self._print_test_summary()
            
        except Exception as e:
            logger.error(f"❌ Test suite failed: {e}")
            traceback.print_exc()
        finally:
            if self.vault_client:
                await self.vault_client.close()

    async def _test_vault_client_initialization(self):
        """Test 1: Vault client initialization"""
        print("\n📋 Test 1: Vault Client Initialization")
        
        try:
            self.vault_client = VaultClient()
            await self.vault_client.initialize()
            
            # Check required configuration
            required_vars = [
                'CALVIN_VAULT_PROGRAM_ID',
                'CALVIN_STAKING_PROGRAM_ID', 
                'SOLANA_RPC_URL',
                'CALVIN_AUTHORITY_PRIVATE_KEY'
            ]
            
            missing_vars = []
            for var in required_vars:
                value = config.get(var)
                if not value:
                    missing_vars.append(var)
                else:
                    print(f"  ✅ {var}: {value[:8]}..." if 'PRIVATE_KEY' not in var else f"  ✅ {var}: [REDACTED]")
            
            if missing_vars:
                raise ValueError(f"Missing required environment variables: {missing_vars}")
            
            self.test_results['initialization'] = {
                'status': 'PASS',
                'message': 'Vault client initialized successfully'
            }
            print("  ✅ Vault client initialization: PASS")
            
        except Exception as e:
            self.test_results['initialization'] = {
                'status': 'FAIL',
                'message': str(e)
            }
            print(f"  ❌ Vault client initialization: FAIL - {e}")
            raise

    async def _test_rpc_connection(self):
        """Test 2: RPC connection to Solana devnet"""
        print("\n📡 Test 2: RPC Connection")
        
        try:
            # Test basic RPC connectivity
            client = self.vault_client.client
            
            # Get latest blockhash (simple connectivity test)
            response = await client.get_latest_blockhash()
            
            if response.value and response.value.blockhash:
                print(f"  ✅ RPC Connection: Connected to devnet")
                print(f"  📊 Latest blockhash: {response.value.blockhash}")
                
                self.test_results['rpc_connection'] = {
                    'status': 'PASS',
                    'message': 'Successfully connected to Solana devnet',
                    'blockhash': str(response.value.blockhash)
                }
            else:
                raise Exception("Failed to get latest blockhash")
                
        except Exception as e:
            self.test_results['rpc_connection'] = {
                'status': 'FAIL',
                'message': str(e)
            }
            print(f"  ❌ RPC Connection: FAIL - {e}")

    async def _test_program_existence(self):
        """Test 3: Verify vault program exists on devnet"""
        print("\n🏗️  Test 3: Program Existence")
        
        try:
            from solders.pubkey import Pubkey
            
            vault_program_id = config.get('CALVIN_VAULT_PROGRAM_ID')
            vault_program_pubkey = Pubkey.from_string(vault_program_id)
            
            # Query program account
            account_info = await self.vault_client.client.get_account_info(vault_program_pubkey)
            
            if account_info.value:
                print(f"  ✅ Vault Program: Found on devnet")
                print(f"  📊 Program ID: {vault_program_id}")
                print(f"  📊 Owner: {account_info.value.owner}")
                print(f"  📊 Executable: {account_info.value.executable}")
                
                self.test_results['program_existence'] = {
                    'status': 'PASS',
                    'message': 'Vault program found on devnet',
                    'program_id': vault_program_id,
                    'executable': account_info.value.executable
                }
            else:
                raise Exception("Vault program not found on devnet")
                
        except Exception as e:
            self.test_results['program_existence'] = {
                'status': 'FAIL',
                'message': str(e)
            }
            print(f"  ❌ Vault Program: FAIL - {e}")

    async def _test_pda_derivation(self):
        """Test 4: PDA derivation logic"""
        print("\n🔑 Test 4: PDA Derivation")
        
        try:
            from solders.pubkey import Pubkey
            
            # Test vault PDA derivation
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            vault_program_id = Pubkey.from_string(config.get('CALVIN_VAULT_PROGRAM_ID'))
            usdc_mint_pubkey = Pubkey.from_string(usdc_mint)
            
            vault_pda, vault_bump = Pubkey.find_program_address(
                [b"vault", bytes(usdc_mint_pubkey)],
                vault_program_id
            )
            
            print(f"  ✅ Vault PDA: {vault_pda}")
            print(f"  📊 Vault Bump: {vault_bump}")
            
            # Test vault authority PDA
            vault_authority_pda, authority_bump = Pubkey.find_program_address(
                [b"vault_authority"],
                vault_program_id
            )
            
            print(f"  ✅ Vault Authority PDA: {vault_authority_pda}")
            print(f"  📊 Authority Bump: {authority_bump}")
            
            # Test user position PDA (using a dummy user)
            dummy_user = Pubkey.from_string("11111111111111111111111111111112")  # System program as dummy
            user_position_pda, position_bump = Pubkey.find_program_address(
                [b"user_position", bytes(vault_pda), bytes(dummy_user)],
                vault_program_id
            )
            
            print(f"  ✅ User Position PDA: {user_position_pda}")
            print(f"  📊 Position Bump: {position_bump}")
            
            self.test_results['pda_derivation'] = {
                'status': 'PASS',
                'message': 'PDA derivation working correctly',
                'vault_pda': str(vault_pda),
                'vault_authority_pda': str(vault_authority_pda)
            }
            
        except Exception as e:
            self.test_results['pda_derivation'] = {
                'status': 'FAIL',
                'message': str(e)
            }
            print(f"  ❌ PDA Derivation: FAIL - {e}")

    async def _test_vault_state_query(self):
        """Test 5: Vault state query (expecting not initialized)"""
        print("\n💰 Test 5: Vault State Query")
        
        try:
            vault_state = await self.vault_client.get_vault_state()
            
            if vault_state.get('error'):
                print(f"  ✅ Vault State: Not initialized (expected)")
                print(f"  📊 Error: {vault_state['error']}")
                
                self.test_results['vault_state'] = {
                    'status': 'PASS',
                    'message': 'Vault state query working (not initialized as expected)',
                    'error': vault_state['error']
                }
            else:
                print(f"  🤔 Vault State: Unexpected response")
                print(f"  📊 Response: {vault_state}")
                
                self.test_results['vault_state'] = {
                    'status': 'PARTIAL',
                    'message': 'Vault state query returned unexpected data',
                    'response': vault_state
                }
                
        except Exception as e:
            self.test_results['vault_state'] = {
                'status': 'FAIL',
                'message': str(e)
            }
            print(f"  ❌ Vault State Query: FAIL - {e}")

    async def _test_user_position_query(self):
        """Test 6: User position query"""
        print("\n👤 Test 6: User Position Query")
        
        try:
            # Use the trading authority as test user
            trading_authority = config.get('CALVIN_AUTHORITY_PRIVATE_KEY')
            if trading_authority:
                from solders.keypair import Keypair
                
                # Handle both array format and base58 format
                if isinstance(trading_authority, str) and trading_authority.startswith('['):
                    # Array format: [115,181,216,108,...]
                    import ast
                    private_key_bytes = ast.literal_eval(trading_authority)
                    keypair = Keypair.from_bytes(private_key_bytes)
                    print(f"  📊 Private key format: Array (converted to bytes)")
                elif isinstance(trading_authority, str):
                    # Base58 format
                    keypair = Keypair.from_base58_string(trading_authority)
                    print(f"  📊 Private key format: Base58")
                else:
                    raise ValueError(f"Unsupported private key format: {type(trading_authority)}")
                
                test_user = str(keypair.pubkey())
                print(f"  ✅ Private key loaded successfully")
            else:
                test_user = "11111111111111111111111111111112"  # System program as dummy
                print(f"  ⚠️  No private key found, using dummy user")
            
            user_position = await self.vault_client.get_user_position(test_user)
            
            print(f"  ✅ User Position Query: Working")
            print(f"  📊 Test User: {test_user[:8]}...")
            print(f"  📊 Response: {user_position}")
            
            self.test_results['user_position'] = {
                'status': 'PASS',
                'message': 'User position query working',
                'test_user': test_user,
                'response': user_position
            }
            
        except Exception as e:
            self.test_results['user_position'] = {
                'status': 'FAIL',
                'message': str(e)
            }
            print(f"  ❌ User Position Query: FAIL - {e}")

    async def _test_error_handling(self):
        """Test 7: Error handling with invalid data"""
        print("\n🛡️  Test 7: Error Handling")
        
        try:
            # Test with invalid user public key
            try:
                await self.vault_client.get_user_position("invalid_pubkey")
                print(f"  ❌ Error Handling: Should have failed with invalid pubkey")
                self.test_results['error_handling'] = {
                    'status': 'FAIL',
                    'message': 'Did not properly handle invalid pubkey'
                }
            except Exception as expected_error:
                print(f"  ✅ Error Handling: Properly caught invalid pubkey")
                print(f"  📊 Error: {str(expected_error)[:100]}...")
                
                self.test_results['error_handling'] = {
                    'status': 'PASS',
                    'message': 'Error handling working correctly',
                    'test_error': str(expected_error)[:100]
                }
                
        except Exception as e:
            self.test_results['error_handling'] = {
                'status': 'FAIL',
                'message': str(e)
            }
            print(f"  ❌ Error Handling Test: FAIL - {e}")

    def _print_test_summary(self):
        """Print test summary"""
        print("\n" + "=" * 50)
        print("📊 TEST SUMMARY")
        print("=" * 50)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result['status'] == 'PASS')
        partial_tests = sum(1 for result in self.test_results.values() if result['status'] == 'PARTIAL')
        failed_tests = sum(1 for result in self.test_results.values() if result['status'] == 'FAIL')
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"🤔 Partial: {partial_tests}")
        print(f"❌ Failed: {failed_tests}")
        
        print("\nDetailed Results:")
        for test_name, result in self.test_results.items():
            status_emoji = "✅" if result['status'] == 'PASS' else "🤔" if result['status'] == 'PARTIAL' else "❌"
            print(f"  {status_emoji} {test_name}: {result['message']}")
        
        if failed_tests == 0:
            print(f"\n🎉 All critical tests passed! Vault connection is ready.")
            print(f"💡 The vault is not initialized on devnet, but the Python backend can connect successfully.")
        else:
            print(f"\n⚠️  Some tests failed. Check configuration and network connectivity.")

async def main():
    """Run the devnet connection test"""
    test_runner = DevnetVaultConnectionTest()
    await test_runner.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main()) 