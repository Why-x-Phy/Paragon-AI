/**
 * Test script to debug Anchor Program constructor in frontend context
 * Run with: node test-frontend-program.js
 */

const { PublicKey, Connection, Keypair } = require('@solana/web3.js');
const { Program, AnchorProvider } = require('@coral-xyz/anchor');

// Import the IDLs
const CalvinStakingIDL = require('../onchain/target/idl/calvin_staking.json');
const CalvinVaultIDL = require('../onchain/target/idl/vault.json');

console.log('🔍 Testing Frontend Program Constructor...\n');

// Simulate frontend environment with mock wallet
class MockWallet {
  constructor() {
    this.keypair = Keypair.generate();
    this.publicKey = this.keypair.publicKey;
  }

  async signTransaction(transaction) {
    transaction.partialSign(this.keypair);
    return transaction;
  }

  async signAllTransactions(transactions) {
    return transactions.map(tx => {
      tx.partialSign(this.keypair);
      return tx;
    });
  }
}

try {
  // Create connection and mock wallet
  const connection = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');
  const wallet = new MockWallet();
  
  console.log('📋 Testing with provider...');
  
  // Test with provider (this is how frontend should work)
  const provider = new AnchorProvider(connection, wallet, {});
  
  console.log('Creating Staking Program with provider...');
  const stakingProgram = new Program(CalvinStakingIDL, provider);
  console.log('✅ Staking Program created successfully:', {
    hasProgramId: !!stakingProgram?.programId,
    programId: stakingProgram?.programId?.toString(),
    matches: stakingProgram?.programId?.toString() === CalvinStakingIDL.address
  });
  
  console.log('Creating Vault Program with provider...');
  const vaultProgram = new Program(CalvinVaultIDL, provider);
  console.log('✅ Vault Program created successfully:', {
    hasProgramId: !!vaultProgram?.programId,
    programId: vaultProgram?.programId?.toString(),
    matches: vaultProgram?.programId?.toString() === CalvinVaultIDL.address
  });

  // Test edge cases
  console.log('\n🔍 Testing edge cases...');
  
  // Test with null provider
  try {
    console.log('Testing with null provider...');
    const nullProgram = new Program(CalvinVaultIDL, null);
    console.log('⚠️ Unexpectedly succeeded with null provider');
  } catch (e) {
    console.log('✅ Correctly failed with null provider:', e.message);
  }
  
  // Test with undefined provider
  try {
    console.log('Testing with undefined provider...');
    const undefinedProgram = new Program(CalvinVaultIDL, undefined);
    console.log('⚠️ Unexpectedly succeeded with undefined provider');
  } catch (e) {
    console.log('✅ Correctly failed with undefined provider:', e.message);
  }

} catch (error) {
  console.error('❌ Test failed:', error.message);
  console.error('Stack:', error.stack);
}

console.log('\n✅ Frontend test completed!'); 