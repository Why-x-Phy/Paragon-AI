const { Connection, PublicKey } = require('@solana/web3.js');
const { AnchorProvider, Program } = require('@coral-xyz/anchor');

async function checkVaultState() {
  try {
    console.log('🔍 Checking Calvin Vault State...');
    
    const connection = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');
    
    // Import the IDL
    const vaultIdl = require('./lib/vault.json');
    const vaultProgramId = new PublicKey('tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z');
    
    // Create a minimal provider for read-only operations
    const provider = {
      connection,
      publicKey: PublicKey.default,
    };
    
    const vaultProgram = new Program(vaultIdl, vaultProgramId, provider);
    
    // Derive vault PDA
    const usdcMint = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
    const [vaultPDA] = PublicKey.findProgramAddressSync(
      [Buffer.from('vault'), usdcMint.toBuffer()],
      vaultProgramId
    );
    
    console.log('📍 Vault PDA:', vaultPDA.toString());
    
    // Fetch vault account
    const vault = await vaultProgram.account.vault.fetch(vaultPDA);
    
    console.log('\n📊 Current Vault State:');
    console.log('  - Total Shares:', vault.totalShares.toString());
    console.log('  - Shares Mint:', vault.sharesMint.toString());
    console.log('  - USDC Mint:', vault.usdcMint.toString());
    console.log('  - Treasury:', vault.treasury.toString());
    console.log('  - Authority Bump:', vault.authorityBump);
    console.log('  - Paused:', vault.paused);
    console.log('  - Deposits Paused:', vault.depositsPaused);
    console.log('  - High Water Mark NAV:', vault.highWaterMarkNav.toString());
    console.log('  - Reentrancy Guard:', vault.reentrancyGuard);
    
    // Calculate current share price
    const navMicroUsdc = 401425000; // Known NAV from user
    const totalShares = parseInt(vault.totalShares.toString());
    
    console.log('\n💰 Share Price Analysis:');
    console.log('  - Current NAV (micro-USDC):', navMicroUsdc);
    console.log('  - Total Shares:', totalShares);
    
    if (totalShares > 0) {
      const sharePrice = Math.floor(navMicroUsdc / totalShares);
      const sharePriceUsdc = sharePrice / 1000000;
      
      console.log('  - Share Price (micro-USDC):', sharePrice);
      console.log('  - Share Price (USDC):', sharePriceUsdc.toFixed(6));
      
      // Check bounds
      const MIN_SHARE_PRICE = 100000; // 0.1 USDC
      const MAX_SHARE_PRICE = 1000000000; // 1000 USDC
      
      console.log('  - Min allowed (micro-USDC):', MIN_SHARE_PRICE, '(0.1 USDC)');
      console.log('  - Max allowed (micro-USDC):', MAX_SHARE_PRICE, '(1000 USDC)');
      
      if (sharePrice < MIN_SHARE_PRICE) {
        console.log('  ❌ Share price TOO LOW:', sharePrice, '<', MIN_SHARE_PRICE);
      } else if (sharePrice > MAX_SHARE_PRICE) {
        console.log('  ❌ Share price TOO HIGH:', sharePrice, '>', MAX_SHARE_PRICE);
      } else {
        console.log('  ✅ Share price within bounds');
      }
    } else {
      console.log('  ℹ️ No shares issued yet (first deposit)');
    }
    
    // Check vault authority's USDC balance
    const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
      [Buffer.from('vault_authority')],
      vaultProgramId
    );
    
    console.log('\n🏦 Vault Authority Analysis:');
    console.log('  - Vault Authority PDA:', vaultAuthorityPDA.toString());
    
    // Get vault's USDC token account
    const { getAssociatedTokenAddress } = require('@solana/spl-token');
    const vaultUsdcAccount = await getAssociatedTokenAddress(usdcMint, vaultAuthorityPDA, true);
    
    try {
      const vaultUsdcBalance = await connection.getTokenAccountBalance(vaultUsdcAccount);
      console.log('  - USDC Token Account:', vaultUsdcAccount.toString());
      console.log('  - USDC Balance:', vaultUsdcBalance.value.uiAmount, 'USDC');
      console.log('  - USDC Balance (raw):', vaultUsdcBalance.value.amount);
    } catch (e) {
      console.log('  - USDC Token Account: Not found or empty');
    }
    
  } catch (error) {
    console.error('❌ Error checking vault state:', error.message);
    if (error.logs) {
      console.error('📋 Error logs:', error.logs);
    }
  }
}

checkVaultState(); 