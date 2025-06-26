/**
 * Test script to verify oracle account derivation for deposits
 */

import { Connection, PublicKey } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID } from '@solana/spl-token';

// Test oracle account derivation
async function testOracleAccounts() {
  console.log('🧪 Testing Oracle Account Derivation...');
  
  const connection = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');
  
  // Vault authority PDA (actual mainnet deployment)
  const vaultProgramId = new PublicKey('tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z'); // Calvin Vault Program
  const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault_authority")],
    vaultProgramId
  );
  
  console.log('📍 Vault Authority PDA:', vaultAuthorityPDA.toBase58());
  
  // Token mint to Pyth price feed mapping
  const PYTH_PRICE_FEEDS = {
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': '0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a', // USDC
    'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': '0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419', // BONK
    'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': '0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996', // JUP
  };
  
  try {
    // Get token accounts for vault authority
    const tokenAccounts = await connection.getParsedTokenAccountsByOwner(
      vaultAuthorityPDA,
      { programId: TOKEN_PROGRAM_ID }
    );
    
    console.log(`🔍 Found ${tokenAccounts.value.length} token accounts`);
    
    const oracleGroups = [];
    
    for (const tokenAccount of tokenAccounts.value) {
      const accountInfo = tokenAccount.account.data.parsed.info;
      const tokenMint = accountInfo.mint;
      const tokenBalance = parseInt(accountInfo.tokenAmount.amount);
      
      console.log(`📊 Token: ${tokenMint}, Balance: ${tokenBalance}`);
      
      if (tokenBalance === 0) {
        console.log('  ⏭️ Skipping zero balance');
        continue;
      }
      
      const pythFeedId = PYTH_PRICE_FEEDS[tokenMint];
      if (!pythFeedId) {
        console.log('  ⚠️ No Pyth feed found');
        continue;
      }
      
      try {
        // Convert hex feed ID to Pubkey
        const feedIdBytes = Buffer.from(pythFeedId.slice(2), 'hex');
        const priceAccountPubkey = new PublicKey(feedIdBytes);
        
        console.log(`  ✅ Oracle Group:`);
        console.log(`    Token Account: ${tokenAccount.pubkey}`);
        console.log(`    Price Account: ${priceAccountPubkey.toString()}`);
        console.log(`    Mint Account:  ${tokenMint}`);
        
        oracleGroups.push({
          tokenAccount: tokenAccount.pubkey,
          priceAccount: priceAccountPubkey.toString(),
          mintAccount: tokenMint,
        });
        
      } catch (error) {
        console.log(`  ❌ Failed to create oracle accounts: ${error.message}`);
      }
    }
    
    console.log(`\n🎯 Summary: ${oracleGroups.length} oracle groups created`);
    console.log(`📊 Total accounts needed: ${oracleGroups.length * 3} (3 per group)`);
    
    // Test Pyth price account validity
    console.log('\n🔍 Testing Pyth price account validity...');
    for (const group of oracleGroups.slice(0, 2)) { // Test first 2 groups
      try {
        const priceAccountInfo = await connection.getAccountInfo(new PublicKey(group.priceAccount));
        if (priceAccountInfo) {
          console.log(`✅ Price account ${group.priceAccount.slice(0,8)}... exists (${priceAccountInfo.data.length} bytes)`);
        } else {
          console.log(`❌ Price account ${group.priceAccount.slice(0,8)}... not found`);
        }
      } catch (error) {
        console.log(`❌ Error checking price account: ${error.message}`);
      }
    }
    
  } catch (error) {
    console.error('❌ Test failed:', error);
  }
}

// Run the test
testOracleAccounts().catch(console.error); 