const { Connection, PublicKey } = require('@solana/web3.js');
const { getAssociatedTokenAddress, TOKEN_PROGRAM_ID } = require('@solana/spl-token');

async function debugDepositOracle() {
  console.log('🧪 Debugging deposit oracle accounts...');
  
  const connection = new Connection('https://mainnet.helius-rpc.com/?api-key=4b71b7b4-b7e8-4d4b-8c8b-6b7b5b7b5b7b');
  
  // Calvin Vault Program ID (mainnet)
  const vaultProgramId = new PublicKey('tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z');
  const usdcMint = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
  
  try {
    // Get vault authority PDA (same as frontend)
    const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault_authority")],
      vaultProgramId
    );
    console.log('📍 Vault Authority PDA:', vaultAuthorityPDA.toString());
    
    // Get vault's main USDC account (same as frontend)
    const vaultUsdcAccount = await getAssociatedTokenAddress(usdcMint, vaultAuthorityPDA, true);
    console.log('📍 Vault USDC Account:', vaultUsdcAccount.toString());
    
    // USDC Pyth feed
    const usdcFeedId = '0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a';
    const feedIdBytes = Buffer.from(usdcFeedId.slice(2), 'hex');
    const priceAccountPubkey = new PublicKey(feedIdBytes);
    console.log('📍 USDC Price Account:', priceAccountPubkey.toString());
    
    // Build oracle accounts array (same as frontend)
    const oracleAccounts = [
      {
        pubkey: vaultUsdcAccount,
        isWritable: false,
        isSigner: false,
      },
      {
        pubkey: priceAccountPubkey,
        isWritable: false,
        isSigner: false,
      },
      {
        pubkey: usdcMint,
        isWritable: false,
        isSigner: false,
      }
    ];
    
    console.log('✅ Oracle accounts generated:');
    oracleAccounts.forEach((account, index) => {
      console.log(`  [${index}] ${account.pubkey.toString()} (writable: ${account.isWritable}, signer: ${account.isSigner})`);
    });
    
    // Build staking accounts (dummy)
    const stakeConfigPDA = new PublicKey('11111111111111111111111111111111'); // placeholder
    const userStakePDA = new PublicKey('22222222222222222222222222222222'); // placeholder
    
    const remainingAccounts = [
      // Staking accounts
      { pubkey: stakeConfigPDA, isWritable: false, isSigner: false },
      { pubkey: userStakePDA, isWritable: false, isSigner: false },
      // Oracle accounts
      ...oracleAccounts
    ];
    
    console.log('✅ Complete remaining accounts structure:');
    console.log('  - Total count:', remainingAccounts.length);
    console.log('  - Staking accounts: 2');
    console.log('  - Oracle accounts: 3');
    console.log('  - Oracle groups: 1');
    
    remainingAccounts.forEach((account, index) => {
      const type = index < 2 ? 'STAKING' : 'ORACLE';
      console.log(`  [${index}] ${type}: ${account.pubkey.toString().slice(0,8)}...`);
    });
    
    console.log('🎯 Expected smart contract behavior:');
    console.log('  - Receives 5 remaining accounts');
    console.log('  - Slices to get oracle accounts: remaining_accounts[2..] = 3 accounts');
    console.log('  - Processes 1 oracle group (3 accounts each)');
    console.log('  - Should succeed with NAV calculation');
    
  } catch (error) {
    console.error('❌ Debug failed:', error);
  }
}

debugDepositOracle(); 