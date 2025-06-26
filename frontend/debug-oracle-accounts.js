const { Connection, PublicKey } = require('@solana/web3.js');
const { TOKEN_PROGRAM_ID } = require('@solana/spl-token');

async function debugOracleAccounts() {
  console.log('🧪 Debugging oracle accounts...');
  
  const connection = new Connection('https://api.mainnet-beta.solana.com');
  const vaultAuthorityPDA = new PublicKey('6tMyF1Q5GScmXCJGSgpsKQtMPSPgkREwWuWWNspcmV8U');
  const usdcMint = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
  
  try {
    // Get all token accounts owned by vault authority
    const tokenAccounts = await connection.getParsedTokenAccountsByOwner(
      vaultAuthorityPDA,
      { programId: TOKEN_PROGRAM_ID }
    );

    console.log(`🔍 Found ${tokenAccounts.value.length} token accounts for vault authority`);
    
    // Look for USDC token account
    const usdcTokenAccount = tokenAccounts.value.find(account => 
      account.account.data.parsed.info.mint === usdcMint.toString()
    );
    
    if (usdcTokenAccount) {
      console.log('✅ USDC token account found:');
      console.log('  - Address:', usdcTokenAccount.pubkey);
      console.log('  - Balance:', usdcTokenAccount.account.data.parsed.info.tokenAmount.uiAmount, 'USDC');
      
      // Test oracle account creation
      const usdcFeedId = '0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a';
      const feedIdBytes = Buffer.from(usdcFeedId.slice(2), 'hex');
      const priceAccountPubkey = new PublicKey(feedIdBytes);
      
      console.log('✅ Oracle accounts would be:');
      console.log('  [0] Token Account:', usdcTokenAccount.pubkey);
      console.log('  [1] Price Account:', priceAccountPubkey.toString());
      console.log('  [2] Mint Account:', usdcMint.toString());
      console.log('✅ Total oracle accounts: 3 (correct group size)');
      
    } else {
      console.log('❌ USDC token account NOT found!');
      console.log('Available token accounts:');
      tokenAccounts.value.forEach((account, index) => {
        const info = account.account.data.parsed.info;
        console.log(`  [${index}] ${info.mint} (${info.tokenAmount.uiAmount} tokens)`);
      });
    }
    
  } catch (error) {
    console.error('❌ Debug failed:', error);
  }
}

debugOracleAccounts(); 