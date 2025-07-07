const { Connection, PublicKey } = require('@solana/web3.js');
const { Program, AnchorProvider } = require('@coral-xyz/anchor');

// Import the IDL like the frontend does
const CalvinVaultIDL = require('../onchain/target/idl/vault.json');

// Constants (using mainnet as per frontend)
const VAULT_PROGRAM_ID = 'tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z';
const USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const RPC_ENDPOINT = 'https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d';

// Mock wallet for read-only operations
class MockWallet {
  constructor() {
    this.publicKey = PublicKey.default;
  }
  
  async signTransaction(tx) {
    throw new Error('Mock wallet cannot sign transactions');
  }
  
  async signAllTransactions(txs) {
    throw new Error('Mock wallet cannot sign transactions');
  }
}

async function checkVaultState() {
  try {
    console.log('🔍 Querying Calvin Vault State...\n');
    
    // Setup connection with versioned transaction support (like frontend)
    const connection = new Connection(RPC_ENDPOINT, {
      commitment: 'confirmed',
      maxSupportedTransactionVersion: 0,
    });
    
    // Create mock wallet and provider
    const wallet = new MockWallet();
    const provider = new AnchorProvider(connection, wallet, {
      commitment: 'confirmed',
    });
    
    // Create program instance (like frontend)
    const program = new Program(CalvinVaultIDL, provider);
    
    console.log('📍 Program ID:', program.programId.toString());
    console.log('📍 Expected:', VAULT_PROGRAM_ID);
    console.log('📍 Match:', program.programId.toString() === VAULT_PROGRAM_ID);
    
    // Derive vault PDA (like frontend)
    const [vaultPDA] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault")],
      program.programId
    );
    
    console.log('\n📍 Vault PDA:', vaultPDA.toBase58());
    
    // Fetch vault account
    console.log('📡 Fetching vault account...');
    const vault = await program.account.vault.fetch(vaultPDA);
    
    // Format amounts (divide by 1e6 for USDC, shares are already in proper format)
    const formatUsdc = (amount) => {
      if (typeof amount === 'object' && amount.toNumber) {
        return (amount.toNumber() / 1e6).toFixed(2);
      }
      return (Number(amount) / 1e6).toFixed(2);
    };
    
    const formatShares = (amount) => {
      if (typeof amount === 'object' && amount.toNumber) {
        return (amount.toNumber() / 1e6).toFixed(6);
      }
      return (Number(amount) / 1e6).toFixed(6);
    };
    
    console.log('\n📊 VAULT STATE:');
    console.log('=====================================');
    console.log(`Total Shares: ${formatShares(vault.totalShares)}`);
    console.log(`High Water Mark (HWM): $${formatUsdc(vault.highWaterMarkNav)}`);
    console.log(`Performance Fee BPS: ${vault.performanceFeeBps} (${vault.performanceFeeBps / 100}%)`);
    console.log(`Management Fee BPS: ${vault.managementFeeBps} (${vault.managementFeeBps / 100}%)`);
    console.log(`Deposit Fee BPS: ${vault.depositFeeBps} (${vault.depositFeeBps / 100}%)`);
    console.log(`Withdrawal Fee BPS: ${vault.withdrawalFeeBps} (${vault.withdrawalFeeBps / 100}%)`);
    console.log(`Calvin Authority: ${vault.calvinAuthority.toBase58()}`);
    console.log(`Treasury: ${vault.treasury.toBase58()}`);
    console.log(`Paused: ${vault.paused}`);
    console.log(`Deposits Paused: ${vault.depositsPaused}`);
    console.log(`Withdrawals Paused: ${vault.withdrawalsPaused}`);
    
    // Get vault authority PDA for checking token accounts
    const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault_authority")],
      program.programId
    );
    
    console.log(`\n🔑 Vault Authority PDA: ${vaultAuthorityPDA.toBase58()}`);
    
    // Get vault's USDC balance
    const vaultUsdcAddress = await connection.getTokenAccountsByOwner(
      vaultAuthorityPDA,
      { mint: new PublicKey(USDC_MINT) }
    );
    
    if (vaultUsdcAddress.value.length > 0) {
      const usdcAccount = await connection.getTokenAccountBalance(vaultUsdcAddress.value[0].pubkey);
      const usdcBalance = parseFloat(usdcAccount.value.amount) / 1e6;
      console.log(`\n💰 Vault USDC Balance: $${usdcBalance.toFixed(2)}`);
      console.log(`📍 USDC Token Account: ${vaultUsdcAddress.value[0].pubkey.toBase58()}`);
      
      // Calculate share price
      const totalShares = typeof vault.totalShares === 'object' ? vault.totalShares.toNumber() : Number(vault.totalShares);
      if (totalShares > 0) {
        const sharePrice = (parseFloat(usdcAccount.value.amount) / totalShares);
        console.log(`📈 Current Share Price: $${sharePrice.toFixed(6)}`);
        console.log(`   (1 share = $${sharePrice.toFixed(6)})`);
        
        // Compare with HWM
        const hwmUsdc = typeof vault.highWaterMarkNav === 'object' ? vault.highWaterMarkNav.toNumber() : Number(vault.highWaterMarkNav);
        const hwmSharePrice = hwmUsdc / 1e6;
        console.log(`📊 HWM Share Price: $${hwmSharePrice.toFixed(6)}`);
        console.log(`📊 Performance vs HWM: ${sharePrice > hwmSharePrice ? '🟢 ABOVE' : '🔴 BELOW'} (${((sharePrice - hwmSharePrice) / hwmSharePrice * 100).toFixed(2)}%)`);
      }
    } else {
      console.log('\n⚠️ No USDC token account found for vault authority');
    }
    
    console.log('\n✅ Vault state query complete!');
    
  } catch (error) {
    console.error('❌ Error querying vault state:', error);
    if (error.message.includes('Account does not exist')) {
      console.error('💡 This might mean the vault PDA is incorrect or the account was not initialized');
    }
  }
}

// Run the check
checkVaultState(); 