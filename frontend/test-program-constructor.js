/**
 * Test script to debug Anchor Program constructor issues
 * Run with: node test-program-constructor.js
 */

const { PublicKey, Connection } = require('@solana/web3.js');
const { Program, AnchorProvider } = require('@coral-xyz/anchor');

// Import the IDLs
const CalvinStakingIDL = require('../onchain/target/idl/calvin_staking.json');
const CalvinVaultIDL = require('../onchain/target/idl/vault.json');

console.log('🔍 Testing Anchor Program Constructor Compatibility...\n');

// Test IDL structure
console.log('📋 IDL Structure Analysis:');
console.log('Staking IDL:', {
  hasAddress: !!CalvinStakingIDL?.address,
  address: CalvinStakingIDL?.address,
  hasMetadata: !!CalvinStakingIDL?.metadata,
  hasInstructions: !!CalvinStakingIDL?.instructions,
  instructionCount: CalvinStakingIDL?.instructions?.length || 0,
  anchorVersion: CalvinStakingIDL?.metadata?.spec
});

console.log('Vault IDL:', {
  hasAddress: !!CalvinVaultIDL?.address,
  address: CalvinVaultIDL?.address,
  hasMetadata: !!CalvinVaultIDL?.metadata,
  hasInstructions: !!CalvinVaultIDL?.instructions,
  instructionCount: CalvinVaultIDL?.instructions?.length || 0,
  anchorVersion: CalvinVaultIDL?.metadata?.spec
});

// Test with a minimal provider (no wallet needed for testing constructor)
console.log('\n🔧 Testing Program Constructor...');

try {
  const connection = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');
  
  // Test without provider first (should work in newer Anchor versions)
  console.log('Testing Staking Program constructor...');
  const stakingProgram = new Program(CalvinStakingIDL);
  console.log('✅ Staking Program created:', {
    hasProgramId: !!stakingProgram?.programId,
    programId: stakingProgram?.programId?.toString(),
    hasIdl: !!stakingProgram?.idl,
    hasMethods: !!stakingProgram?.methods
  });
  
  console.log('Testing Vault Program constructor...');
  const vaultProgram = new Program(CalvinVaultIDL);
  console.log('✅ Vault Program created:', {
    hasProgramId: !!vaultProgram?.programId,
    programId: vaultProgram?.programId?.toString(),
    hasIdl: !!vaultProgram?.idl,
    hasMethods: !!vaultProgram?.methods
  });
  
} catch (error) {
  console.error('❌ Program constructor failed:', error.message);
  console.error('Stack:', error.stack);
}

console.log('\n🔍 Checking for potential type mismatches...');

// Check if there are any type-related issues in the IDL
const sampleInstruction = CalvinVaultIDL?.instructions?.[0];
if (sampleInstruction) {
  console.log('Sample instruction args:', sampleInstruction.args);
  console.log('Sample instruction accounts:', sampleInstruction.accounts?.slice(0, 3));
}

console.log('\n✅ Test completed!'); 