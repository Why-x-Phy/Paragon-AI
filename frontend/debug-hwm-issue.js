const { Connection, PublicKey } = require('@solana/web3.js');
const { TOKEN_PROGRAM_ID } = require('@solana/spl-token');

// PYTH_PRICE_FEEDS from VaultClient
const PYTH_PRICE_FEEDS = {
  'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': '0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a', // USDC
  'So11111111111111111111111111111111111111112': '0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d', // SOL
  '6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN': '0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a', // TRUMP
  'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': '0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419', // BONK
  'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': '0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996', // JUP
  '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R': '0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a', // RAY
  'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': '0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc', // WIF
  'Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7': '0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a', // ATH
  '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump': '0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608', // FARTCOIN
  'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL': '0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2', // JTO
  'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5': '0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d', // MEW
  'MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey': '0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a', // MNDE
  'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE': '0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c', // ORCA
  'rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof': '0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d', // RENDER
  'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3': '0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff', // PYTH
  '3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y': '0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b', // VIRTUAL
  '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv': '0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61', // PENGU
  '85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ': '0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389', // W (WORMHOLE)
  '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr': '0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce', // POPCAT
  'J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr': '0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a', // SPX
};

const TOKEN_MINT_TO_SYMBOL = {
  'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC',
  'So11111111111111111111111111111111111111112': 'SOL',
  '6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN': 'TRUMP',
  'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': 'BONK',
  'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': 'JUP',
  '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R': 'RAY',
  'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': 'WIF',
  'Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7': 'ATH',
  '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump': 'FARTCOIN',
  'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL': 'JTO',
  'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5': 'MEW',
  'MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey': 'MNDE',
  'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE': 'ORCA',
  'rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof': 'RENDER',
  'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3': 'PYTH',
  '3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y': 'VIRTUAL',
  '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv': 'PENGU',
  '85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ': 'W',
  '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr': 'POPCAT',
  'J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr': 'SPX',
};

async function debugHwmIssue() {
  console.log('🔍 Debugging HWM Update Issue');
  console.log('=====================================');
  
  const connection = new Connection('https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d', 'confirmed');
  
  // Calvin Vault Program ID (mainnet)
  const vaultProgramId = new PublicKey('tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z');
  
  try {
    // Get vault authority PDA
    const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault_authority")],
      vaultProgramId
    );
    console.log('📍 Vault Authority PDA:', vaultAuthorityPDA.toString());
    
    // Get all token accounts owned by vault authority
    const tokenAccounts = await connection.getParsedTokenAccountsByOwner(
      vaultAuthorityPDA,
      { programId: TOKEN_PROGRAM_ID }
    );

    console.log(`\n🔍 Found ${tokenAccounts.value.length} token accounts for vault authority`);
    
    let totalValueUsd = 0;
    let tokensWithValue = [];
    let oracleAccountsNeeded = [];
    
    for (const tokenAccount of tokenAccounts.value) {
      const accountInfo = tokenAccount.account.data.parsed.info;
      const tokenMint = accountInfo.mint;
      const tokenBalance = parseInt(accountInfo.tokenAmount.amount);
      const decimals = accountInfo.tokenAmount.decimals;
      const uiAmount = accountInfo.tokenAmount.uiAmount;
      
      const symbol = TOKEN_MINT_TO_SYMBOL[tokenMint] || 'UNKNOWN';
      
      console.log(`\n📊 Token: ${symbol} (${tokenMint.slice(0,8)}...)`);
      console.log(`   Balance: ${uiAmount} ${symbol}`);
      
      // Skip tokens with zero balance
      if (tokenBalance === 0) {
        console.log('   ⏭️ Skipping zero balance');
        continue;
      }
      
      // Check if we have a Pyth feed for this token
      const pythFeedId = PYTH_PRICE_FEEDS[tokenMint];
      if (!pythFeedId) {
        console.log('   ⚠️ No Pyth feed found - this token cannot be valued!');
        continue;
      }
      
      console.log(`   ✅ Pyth feed: ${pythFeedId.slice(0,10)}...`);
      
      // Add to oracle accounts needed
      oracleAccountsNeeded.push({
        symbol,
        tokenAccount: tokenAccount.pubkey,
        mint: tokenMint,
        feedId: pythFeedId,
        balance: uiAmount
      });
      
      tokensWithValue.push({
        symbol,
        balance: uiAmount,
        mint: tokenMint
      });
    }
    
    console.log('\n🎯 ANALYSIS:');
    console.log('=====================================');
    console.log(`Total tokens with non-zero balance: ${tokensWithValue.length}`);
    console.log(`Oracle accounts needed for full NAV: ${oracleAccountsNeeded.length * 3} (${oracleAccountsNeeded.length} groups of 3)`);
    
    if (tokensWithValue.length > 0) {
      console.log('\n📋 Tokens requiring oracle accounts:');
      tokensWithValue.forEach((token, i) => {
        console.log(`  ${i + 1}. ${token.symbol}: ${token.balance}`);
      });
    }
    
    console.log('\n🚨 THE PROBLEM:');
    console.log('=====================================');
    console.log('1. Vault currently holds multiple tokens with value');
    console.log('2. HWM was set when vault had full portfolio valuation');
    console.log('3. During deposits, if no new price updates are needed,');
    console.log('   frontend uses "simple transaction" with NO oracle accounts');
    console.log('4. Smart contract only sees USDC balance (~$49,664)');
    console.log('5. NAV calculation is incomplete, so HWM is not updated');
    
    console.log('\n💡 THE SOLUTION:');
    console.log('=====================================');
    console.log('1. Always pass oracle accounts for ALL vault holdings');
    console.log('2. Even if no new price updates needed, include existing tokens');
    console.log('3. This ensures NAV calculation includes full portfolio value');
    console.log('4. HWM will be updated correctly when NAV > current HWM');
    
    console.log('\n🔧 REQUIRED ORACLE ACCOUNTS FOR DEPOSITS:');
    console.log('=====================================');
    oracleAccountsNeeded.forEach((oracle, i) => {
      console.log(`Group ${i + 1} (${oracle.symbol}):`);
      console.log(`  [${i * 3}] Token Account: ${oracle.tokenAccount.toString()}`);
      console.log(`  [${i * 3 + 1}] Price Account: (derived from ${oracle.feedId.slice(0,10)}...)`);
      console.log(`  [${i * 3 + 2}] Mint Account:  ${oracle.mint}`);
    });
    
    console.log(`\nTotal remaining accounts needed: ${2 + (oracleAccountsNeeded.length * 3)}`);
    console.log('  - 2 staking accounts (stake_config, user_stake)');
    console.log(`  - ${oracleAccountsNeeded.length * 3} oracle accounts (${oracleAccountsNeeded.length} groups of 3)`);
    
  } catch (error) {
    console.error('❌ Debug failed:', error);
  }
}

debugHwmIssue(); 