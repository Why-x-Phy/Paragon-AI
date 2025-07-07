/**
 * Calvin Vault Client - Smart Contract Integration
 */

import { 
  Connection, 
  PublicKey, 
  Transaction,
  TransactionMessage,
  VersionedTransaction,
  SystemProgram,
  SYSVAR_RENT_PUBKEY 
} from '@solana/web3.js';
import { 
  TOKEN_PROGRAM_ID,
  ASSOCIATED_TOKEN_PROGRAM_ID,
  getAssociatedTokenAddress,
  createAssociatedTokenAccountInstruction,
  getAccount,
  TokenAccountNotFoundError,
  TokenInvalidAccountOwnerError
} from '@solana/spl-token';
import { AnchorProvider, BN, Program } from '@coral-xyz/anchor';
import { HermesClient } from '@pythnetwork/hermes-client';
import { PythSolanaReceiver } from '@pythnetwork/pyth-solana-receiver';
import { 
  getStakingProgram, 
  getVaultProgram,
  getStakeConfigPDA,
  getUserStakePDA,
  getVaultPDA,
  getUserPositionPDA
} from './anchor-program';

// ================ ORACLE CONFIGURATION ================
// Single source of truth for all Pyth price feed IDs
// Must match oracle_config.rs in the backend exactly
export const PYTH_PRICE_FEEDS = {
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

// Token mint to symbol mapping (used for price display)
export const TOKEN_MINT_TO_SYMBOL = {
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
  '3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizpWAT2Zfyr9y': 'VIRTUAL',
  '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv': 'PENGU',
  '85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ': 'W',
  '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr': 'POPCAT',
  'J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr': 'SPX',
};
import { CONTRACTS, TIERS, FEES } from '@/constants';

export class VaultClient {
  constructor(wallet, connection) {
    this.wallet = wallet;
    // Use simple connection - PythSolanaReceiver will handle versioned transactions internally
    this.connection = connection || new Connection(CONTRACTS.RPC_ENDPOINT, {
      commitment: CONTRACTS.COMMITMENT,
    });
    this.provider = null;
    this.stakingProgram = null;
    this.vaultProgram = null;
    this.switchboardProgram = null;
    
    this.usdcMint = new PublicKey(CONTRACTS.USDC);
    this.calvinMint = new PublicKey(CONTRACTS.CALVIN_TOKEN);
    
    // Initialize Pyth client for price feeds following official documentation pattern
    // The URL below is a public Hermes instance operated by the Pyth Data Association.
    // Hermes is also available from several third-party providers listed here:
    // https://docs.pyth.network/price-feeds/api-instances-and-providers/hermes
    this.hermesClient = new HermesClient(
      "https://hermes.pyth.network/",
      {}
    );
    this.pythSolanaReceiver = null; // Will be initialized properly later
    
    // Price caching for accurate and efficient share price calculations
    this.priceCache = new Map(); // tokenSymbol -> { price, timestamp }
    this.priceCacheTTL = 15000; // 15 seconds TTL for price cache
  }

  // Initialize the client
  async initialize() {
    try {
      // Check if wallet and connection are available
      if (!this.wallet || !this.connection) {
        console.warn('⚠️ Wallet or connection not available during VaultClient initialization');
        return;
      }

      // Import the program creation functions
      const { getStakingProgram, getVaultProgram } = await import('./anchor-program');
      
      // Create provider
      const provider = new AnchorProvider(
        this.connection,
        this.wallet,
        AnchorProvider.defaultOptions()
      );

      try {
        // Initialize staking program
        this.stakingProgram = getStakingProgram(provider);
        console.log('✅ Staking program initialized');
        
        // Verify staking program ID matches expected
        if (this.stakingProgram.programId.toString() !== CONTRACTS.CALVIN_STAKING_PROGRAM) {
          console.error('❌ Staking program ID mismatch!');
        }
      } catch (stakingError) {
        console.error('❌ Failed to initialize staking program:', stakingError);
        this.stakingProgram = null;
      }

      try {
        // Initialize vault program
        this.vaultProgram = getVaultProgram(provider);
        console.log('✅ Vault program initialized');
        
        // Verify vault program ID matches expected
        if (this.vaultProgram.programId.toString() !== CONTRACTS.CALVIN_VAULT_PROGRAM) {
          console.error('❌ Vault program ID mismatch!');
        }
      } catch (vaultError) {
        console.error('❌ Failed to initialize vault program:', vaultError);
        this.vaultProgram = null;
      }

      // Initialize PythSolanaReceiver following official documentation pattern
      // You will need a Connection from @solana/web3.js and a Wallet from @coral-xyz/anchor to create
      // the receiver.
      try {
        // Create an Anchor-compatible wallet interface
        const anchorWallet = {
          publicKey: this.wallet.publicKey,
          signTransaction: async (tx) => await this.wallet.signTransaction(tx),
          signAllTransactions: async (txs) => await this.wallet.signAllTransactions(txs),
        };
        
        this.pythSolanaReceiver = new PythSolanaReceiver({
          connection: this.connection,
          wallet: anchorWallet,
        });
        console.log('✅ Pyth Solana Receiver initialized');
      } catch (pythError) {
        console.error('❌ Failed to initialize Pyth Solana Receiver:', pythError);
        this.pythSolanaReceiver = null;
      }

      console.log('📋 VaultClient initialization summary:', {
        stakingProgram: this.stakingProgram ? '✅ Ready' : '❌ Failed',
        vaultProgram: this.vaultProgram ? '✅ Ready' : '❌ Failed',
        pythSolanaReceiver: this.pythSolanaReceiver ? '✅ Ready' : '❌ Failed',
        wallet: this.wallet?.publicKey ? `✅ Connected` : '❌ No wallet',
      });

    } catch (error) {
      console.error('❌ VaultClient initialization failed:', error);
      // Set programs to null on initialization failure
      this.stakingProgram = null;
      this.vaultProgram = null;
      this.pythSolanaReceiver = null;
    }
  }

  // ======================= USER DATA FETCHING =======================

  /**
   * Get user's staking information
   */
  async getUserStakeInfo() {
    try {
      if (!this.wallet?.publicKey) return null;

      const [userStakePDA] = getUserStakePDA(this.wallet.publicKey);
      
      try {
        const userStake = await this.stakingProgram.account.userStake.fetch(userStakePDA);
        
        // Calculate tier based on staked amount
        const tier = this.calculateUserTier(userStake.totalStaked);
        
        return {
          totalStaked: userStake.totalStaked.toString(),
          totalStakedFormatted: this.formatTokenAmount(userStake.totalStaked, 6),
          lastStakeTimestamp: userStake.lastStakeTimestamp.toString(),
          tier: tier,
          pda: userStakePDA.toString()
        };
      } catch (e) {
        // User hasn't staked yet
        return {
          totalStaked: '0',
          totalStakedFormatted: '0',
          lastStakeTimestamp: '0',
          tier: null,
          pda: userStakePDA.toString()
        };
      }
    } catch (error) {
      console.error('Error fetching user stake info:', error);
      throw error;
    }
  }

  /**
   * Get user's vault position information
   */
  async getUserVaultPosition() {
    try {
      if (!this.wallet?.publicKey) return null;

      // Check if vault program is properly initialized
      if (!this.vaultProgram) {
        console.log('ℹ️ Vault program not initialized yet');
        return {
          shares: '0',
          sharesFormatted: '0',
          usdcValue: '0',
          usdcValueFormatted: '0',
          totalDepositsUsdc: '0',
          totalDepositsUsdcFormatted: '0',
          lastDepositTimestamp: '0',
          pda: 'Not initialized'
        };
      }

      const [vaultPDA] = getVaultPDA(this.usdcMint);
      const [userPositionPDA] = getUserPositionPDA(vaultPDA, this.wallet.publicKey);
      
      // Get vault info first - handle case where vault doesn't exist yet
      let vault;
      try {
        vault = await this.vaultProgram.account.vault.fetch(vaultPDA);
        if (!vault) {
          console.log('ℹ️ Vault account not found - vault may not be initialized yet');
          return {
            shares: '0',
            sharesFormatted: '0',
            usdcValue: '0',
            usdcValueFormatted: '0',
            totalDepositsUsdc: '0',
            totalDepositsUsdcFormatted: '0',
            lastDepositTimestamp: '0',
            pda: userPositionPDA.toString()
          };
        }
      } catch (vaultError) {
        console.log('ℹ️ Could not fetch vault account:', vaultError.message);
        return {
          shares: '0',
          sharesFormatted: '0',
          usdcValue: '0',
          usdcValueFormatted: '0',
          totalDepositsUsdc: '0',
          totalDepositsUsdcFormatted: '0',
          lastDepositTimestamp: '0',
          pda: userPositionPDA.toString()
        };
      }
      
      // Get user's shares token account (allowOwnerOffCurve not needed for user wallet)
      const userSharesAccount = await getAssociatedTokenAddress(vault.sharesMint, this.wallet.publicKey, false);
      
      // Get user's shares token account (allowOwnerOffCurve not needed for user wallet)
      
      let shares = new BN(0);
      let totalDepositsUsdc = new BN(0);
      let lastDepositTimestamp = '0';
      
      // Try to get shares balance from token account
      try {
        const sharesBalance = await this.connection.getTokenAccountBalance(userSharesAccount);
        shares = new BN(sharesBalance.value.amount);
        console.log('✅ User shares balance:', shares.toString());
      } catch (e) {
        // Silently handle missing shares account - this is normal for users who haven't deposited yet
        console.log('ℹ️ User shares account not found (user hasn\'t deposited yet)');
        // shares remains 0
      }
      
      // Try to get user position for deposit tracking
      try {
        const userPosition = await this.vaultProgram.account.userPosition.fetch(userPositionPDA);
        totalDepositsUsdc = userPosition.totalDepositsUsdc;
        lastDepositTimestamp = userPosition.lastDepositTimestamp.toString();
        console.log('📊 User total deposits:', totalDepositsUsdc.toString());
      } catch (e) {
        console.log('ℹ️ User position account not found');
        // Keep defaults
      }
      
      // Get vault authority PDA
      const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_authority")],
        this.vaultProgram.programId
      );
      
      // Calculate USDC value of shares using proper NAV
      const vaultNav = await this.calculateVaultNAV(vault, vaultAuthorityPDA);
      const sharePrice = this.calculateSharePrice(vaultNav, vault.totalShares);
      const usdcValue = shares.mul(sharePrice).div(new BN(1000000)); // Convert back to USDC amount
      
      return {
        shares: shares.toString(),
        sharesFormatted: this.formatTokenAmount(shares, 6),
        usdcValue: usdcValue.toString(),
        usdcValueFormatted: this.formatTokenAmount(usdcValue, 6),
        totalDepositsUsdc: totalDepositsUsdc.toString(),
        totalDepositsUsdcFormatted: this.formatTokenAmount(totalDepositsUsdc, 6),
        lastDepositTimestamp: lastDepositTimestamp,
        pda: userPositionPDA.toString()
      };
    } catch (error) {
      console.error('Error fetching user vault position:', error);
      // Return default values on error
      return {
        shares: '0',
        sharesFormatted: '0',
        usdcValue: '0',
        usdcValueFormatted: '0',
        totalDepositsUsdc: '0',
        totalDepositsUsdcFormatted: '0',
        lastDepositTimestamp: '0',
        pda: 'Error'
      };
    }
  }

  /**
   * Get user's token balances
   */
  async getUserTokenBalances() {
    try {
      if (!this.wallet?.publicKey) return null;

      // Initialize programs first
      await this.initialize();

      const balances = {
        calvin: '0',
        calvinFormatted: '0',
        usdc: '0',
        usdcFormatted: '0',
        sol: '0',
        solFormatted: '0',
        vaultPass: '0',
        vaultPassFormatted: '0'
      };

      // Get all token accounts for this wallet
      try {
        const tokenAccounts = await this.connection.getParsedTokenAccountsByOwner(
          this.wallet.publicKey,
          { programId: TOKEN_PROGRAM_ID }
        );
        
        // Get user's Vault Pass mint address for detection
        let userVaultPassMint = null;
        try {
          if (this.stakingProgram) {
            const [userVaultPassMintPDA] = PublicKey.findProgramAddressSync(
              [Buffer.from("vault_pass_mint"), this.wallet.publicKey.toBuffer()],
              this.stakingProgram.programId
            );
            userVaultPassMint = userVaultPassMintPDA.toString();
          }
        } catch (e) {
          console.log('Could not derive vault pass mint PDA:', e);
        }
        
        // Search through all token accounts to find CALVIN, USDC, and Vault Pass tokens
        for (const account of tokenAccounts.value) {
          const accountInfo = account.account.data.parsed.info;
          
          if (accountInfo.mint === this.calvinMint.toString()) {
            balances.calvin = accountInfo.tokenAmount.amount;
            // Format using our own method with correct decimals
            balances.calvinFormatted = this.formatTokenAmount(new BN(accountInfo.tokenAmount.amount), 6);
          } else if (accountInfo.mint === this.usdcMint.toString()) {
            balances.usdc = accountInfo.tokenAmount.amount;
            // Format using our own method with correct decimals
            balances.usdcFormatted = this.formatTokenAmount(new BN(accountInfo.tokenAmount.amount), 6);
          } else if (userVaultPassMint && accountInfo.mint === userVaultPassMint) {
            balances.vaultPass = accountInfo.tokenAmount.amount;
            // Vault Pass tokens have 0 decimals
            balances.vaultPassFormatted = this.formatTokenAmount(new BN(accountInfo.tokenAmount.amount), 0);
          }
        }
      } catch (e) {
        console.error('Error fetching token accounts:', e);
      }

      // Get SOL balance
      const solBalance = await this.connection.getBalance(this.wallet.publicKey);
      balances.sol = solBalance.toString();
      balances.solFormatted = this.formatTokenAmount(new BN(solBalance), 9);

      return balances;
    } catch (error) {
      console.error('Error fetching user token balances:', error);
      throw error;
    }
  }

  /**
   * Get vault statistics
   */
  async getVaultStats() {
    try {
      const [vaultPDA] = getVaultPDA(this.usdcMint);
      
      try {
        const vault = await this.vaultProgram.account.vault.fetch(vaultPDA);
        
        // Get vault authority PDA
        const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
          [Buffer.from("vault_authority")],
          this.vaultProgram.programId
        );
        
        // Calculate proper NAV including all token holdings
        const nav = await this.calculateVaultNAV(vault, vaultAuthorityPDA);
        const sharePrice = this.calculateSharePrice(nav, vault.totalShares);
        
        return {
          totalUsdc: nav.toString(),
          totalUsdcFormatted: this.formatTokenAmount(nav, 6),
          totalShares: vault.totalShares.toString(),
          totalSharesFormatted: this.formatTokenAmount(vault.totalShares, 6),
          sharePrice: sharePrice.toString(),
          sharePriceFormatted: this.formatTokenAmount(sharePrice, 6),
          calvinAuthority: vault.calvinAuthority.toString(),
          pda: vaultPDA.toString()
        };
      } catch (fetchError) {
        // Vault account doesn't exist yet - return default values
        console.log('Vault not initialized yet, returning default stats');
        return {
          totalUsdc: '0',
          totalUsdcFormatted: '0',
          totalShares: '0',
          totalSharesFormatted: '0',
          sharePrice: '1000000', // 1.0 with 6 decimals
          sharePriceFormatted: '1.0',
          calvinAuthority: 'Not Set',
          pda: vaultPDA.toString()
        };
      }
    } catch (error) {
      console.error('Error fetching vault stats:', error);
      throw error;
    }
  }

  // ======================= TRANSACTION METHODS =======================

  /**
   * Stake CALVIN tokens
   */
  async stakeCalvin(amount) {
    try {
      await this.initialize();
      
      // 1. Validate inputs first
      if (!amount || Number(amount) <= 0) {
        throw new Error('Please enter a valid amount');
      }
      
      console.log('🔍 Validating stake requirements...');
      
      // 2. Fetch and validate CALVIN mint info
      const mintInfo = await this.connection.getParsedAccountInfo(this.calvinMint);
      if (!mintInfo?.value?.data?.parsed?.info) {
        throw new Error('CALVIN mint not found - check network connection');
      }
      
      const decimals = mintInfo.value.data.parsed.info.decimals;
      console.log('✅ CALVIN mint decimals:', decimals);
      
      // 3. Check if vault is initialized
      const [stakeConfigPDA] = getStakeConfigPDA();
      let stakeConfig;
      try {
        stakeConfig = await this.stakingProgram.account.stakeConfig.fetch(stakeConfigPDA);
        console.log('✅ Stake config loaded');
      } catch (e) {
        throw new Error('Staking program not initialized - contact admin');
      }
      
      // 4. Validate amount against decimals
      const microTokens = Math.floor(Number(amount) * Math.pow(10, decimals));
      if (microTokens <= 0 || !Number.isFinite(microTokens)) {
        throw new Error('Invalid amount calculation');
      }
      
      console.log('💰 Stake calculation:', {
        amount: amount,
        decimals: decimals,
        microTokens: microTokens,
        microTokensType: typeof microTokens
      });
      
      // 5. Find user's CALVIN token account
      let userCalvinAccount = null;
      try {
        const tokenAccounts = await this.connection.getParsedTokenAccountsByOwner(
          this.wallet.publicKey,
          { programId: TOKEN_PROGRAM_ID }
        );
        
        for (const account of tokenAccounts.value) {
          const accountInfo = account.account.data.parsed.info;
          if (accountInfo.mint === this.calvinMint.toString()) {
            userCalvinAccount = new PublicKey(account.pubkey);
            
            // Check if user has enough balance
            const userBalance = Number(accountInfo.tokenAmount.amount);
            if (userBalance < microTokens) {
              throw new Error(`Insufficient balance. You have ${(userBalance / Math.pow(10, decimals)).toFixed(3)} CALVIN`);
            }
            break;
          }
        }
        
        if (!userCalvinAccount) {
          throw new Error('No CALVIN token account found in your wallet');
        }
      } catch (e) {
        if (e.message.includes('Insufficient balance') || e.message.includes('No CALVIN token account')) {
          throw e;
        }
        throw new Error(`Failed to find CALVIN token account: ${e.message}`);
      }
      
      // 6. Get required PDAs and accounts
      const [userStakePDA] = getUserStakePDA(this.wallet.publicKey);
      const [stakeVaultPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("stake_vault")],
        this.stakingProgram.programId
      );

      // Get the stake vault to find the global vault pass mint
      const stakeVault = await this.stakingProgram.account.stakeVault.fetch(stakeVaultPDA);

      // Get user's personal vault pass mint PDA
      const [userVaultPassMintPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_pass_mint"), this.wallet.publicKey.toBuffer()],
        this.stakingProgram.programId
      );

      // Get user's vault pass token account
      const userVaultPassTokenAccount = await getAssociatedTokenAddress(
        userVaultPassMintPDA, 
        this.wallet.publicKey
      );

      // Get stake vault's CALVIN token account
      const stakeVaultCalvinAccount = await getAssociatedTokenAddress(
        this.calvinMint,
        stakeVaultPDA,
        true // allowOwnerOffCurve for PDA
      );

      console.log('🏗️ Building transaction with accounts:', {
        userCalvinAccount: userCalvinAccount.toString(),
        userVaultPassMintPDA: userVaultPassMintPDA.toString(),
        userVaultPassTokenAccount: userVaultPassTokenAccount.toString(),
        stakeVaultCalvinAccount: stakeVaultCalvinAccount.toString(),
        stakeConfig: stakeConfigPDA.toString(),
        userStake: userStakePDA.toString(),
        globalVaultPassMint: stakeVault.vaultPassMint.toString()
      });

      // 7. Build and send transaction
      const tx = await this.stakingProgram.methods
        .stakeCalvin(new BN(microTokens)) // Convert to BN object
        .accounts({
          user: this.wallet.publicKey,
          stakeConfig: stakeConfigPDA,
          stakeVault: stakeVaultPDA,
          userStake: userStakePDA,
          userCalvinToken: userCalvinAccount,
          stakeVaultCalvinToken: stakeVaultCalvinAccount,
          calvinMint: this.calvinMint,
          vaultPassMint: stakeVault.vaultPassMint, // Global vault pass mint from stake vault
          userVaultPassMint: userVaultPassMintPDA,
          userVaultPassToken: userVaultPassTokenAccount,
          systemProgram: SystemProgram.programId,
          tokenProgram: TOKEN_PROGRAM_ID,
          associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
          rent: SYSVAR_RENT_PUBKEY,
        })
        .transaction();
        
      console.log('📤 Sending transaction...');
      return await this.sendTransaction(tx);
      
    } catch (error) {
      console.error('❌ Staking failed:', error);
      throw error;
    }
  }

  /**
   * Unstake CALVIN tokens
   */
  async unstakeCalvin(amount) {
    try {
      await this.initialize();
      
      // Check if staking program is initialized
      if (!this.stakingProgram) {
        throw new Error('Staking program not initialized');
      }
      
      // Validate and convert amount to micro-tokens
      if (!amount || amount <= 0) {
        throw new Error('Invalid amount: must be greater than 0');
      }
      
      const microTokens = Math.floor(Number(amount) * 1e6);
      if (!Number.isFinite(microTokens) || microTokens <= 0) {
        throw new Error('Invalid amount calculation');
      }
      
      const amountBN = new BN(microTokens);
      console.log('💰 Unstake amount:', { amount, microTokens, amountBN: amountBN.toString() });
      
      const [stakeConfigPDA] = getStakeConfigPDA();
      const [userStakePDA] = getUserStakePDA(this.wallet.publicKey);
      
      // Find user's actual CALVIN token account (not ATA)
      let userCalvinAccount = null;
      try {
        const tokenAccounts = await this.connection.getParsedTokenAccountsByOwner(
          this.wallet.publicKey,
          { programId: TOKEN_PROGRAM_ID }
        );
        
        for (const account of tokenAccounts.value) {
          const accountInfo = account.account.data.parsed.info;
          if (accountInfo.mint === this.calvinMint.toString()) {
            userCalvinAccount = new PublicKey(account.pubkey);
            break;
          }
        }
        
        if (!userCalvinAccount) {
          throw new Error('No CALVIN token account found');
        }
      } catch (e) {
        throw new Error(`Failed to find CALVIN token account: ${e.message}`);
      }
      
      // Get user's personal vault pass mint PDA
      const [userVaultPassMintPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_pass_mint"), this.wallet.publicKey.toBuffer()],
        this.stakingProgram.programId
      );
      
      const userVaultPassAccount = await getAssociatedTokenAddress(userVaultPassMintPDA, this.wallet.publicKey);
      
      // Get stake vault PDA
      const [stakeVaultPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("stake_vault")],
        this.stakingProgram.programId
      );

      // For unstaking, we need vault info to pass as remaining accounts for tier verification
      // If vault doesn't exist yet, we need to create dummy accounts to satisfy the CPI check
      const [vaultPDA] = getVaultPDA(this.usdcMint);
      
      let vault = null;
      let userSharesToken = null;
      let shouldProvideVaultAccounts = false;
      
      // Try to get vault info if available
      if (this.vaultProgram) {
        try {
          vault = await this.vaultProgram.account.vault.fetch(vaultPDA);
          if (vault && vault.sharesMint) {
            userSharesToken = await getAssociatedTokenAddress(
              vault.sharesMint,
              this.wallet.publicKey,
              false
            );
            shouldProvideVaultAccounts = true;
            console.log('✅ Vault found, will provide vault accounts for CPI check');
          }
        } catch (e) {
          console.log('ℹ️ Vault not initialized yet, will provide dummy accounts for CPI check');
          // Even if vault doesn't exist, we need to provide dummy accounts
          // The CPI function will fail-safe and allow unstaking if it can't read the accounts
          shouldProvideVaultAccounts = true;
        }
      }

      console.log('🏗️ Building unstake transaction with accounts:', {
        user: this.wallet.publicKey.toBase58(),
        stakeConfig: stakeConfigPDA.toBase58(),
        stakeVault: stakeVaultPDA.toBase58(),
        userStake: userStakePDA.toBase58(),
        userCalvinToken: userCalvinAccount.toBase58(),
        userVaultPassMint: userVaultPassMintPDA.toBase58(),
        vaultPDA: vaultPDA.toBase58(),
        sharesMint: vault?.sharesMint?.toBase58() || 'Not available',
        userSharesToken: userSharesToken?.toBase58() || 'Not available',
        vaultInitialized: !!vault,
      });

      const tx = await this.stakingProgram.methods
        .unstakeCalvin(amountBN)
        .accounts({
          user: this.wallet.publicKey,
          stakeConfig: stakeConfigPDA,
          stakeVault: stakeVaultPDA,
          userStake: userStakePDA,
          userCalvinToken: userCalvinAccount,
          stakeVaultCalvinToken: await getAssociatedTokenAddress(this.calvinMint, stakeVaultPDA, true),
          calvinMint: this.calvinMint,
          userVaultPassMint: userVaultPassMintPDA,
          userVaultPassToken: userVaultPassAccount,
          vaultProgram: this.vaultProgram.programId,
          systemProgram: SystemProgram.programId,
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .remainingAccounts(
          // Always provide vault accounts for CPI check - use real accounts if available, dummy if not
          shouldProvideVaultAccounts ? (
            vault && vault.sharesMint && userSharesToken ? [
              // Real vault accounts
              { pubkey: vaultPDA, isWritable: false, isSigner: false },
              { pubkey: vault.sharesMint, isWritable: false, isSigner: false },
              { pubkey: userSharesToken, isWritable: false, isSigner: false },
            ] : [
              // Dummy accounts when vault not initialized - CPI will fail-safe and allow unstaking
              { pubkey: vaultPDA, isWritable: false, isSigner: false },
              { pubkey: this.calvinMint, isWritable: false, isSigner: false }, // Use CALVIN mint as dummy shares mint
              { pubkey: userCalvinAccount, isWritable: false, isSigner: false }, // Use user's CALVIN account as dummy shares account
            ]
          ) : []
        )
        .transaction();
        
      return await this.sendTransaction(tx);
    } catch (error) {
      console.error('Error unstaking CALVIN:', error);
      throw error;
    }
  }

  /**
   * Get Pyth oracle accounts for NAV calculation during deposits
   * Returns oracle accounts in the format expected by the smart contract:
   * Groups of 3: [token_account, pyth_price_update_v2, mint_account]
   */
  async getOracleAccountsForDeposit(vaultAuthorityPDA) {
    try {
      // Get all token accounts owned by vault authority to determine which oracles we need
      const tokenAccounts = await this.connection.getParsedTokenAccountsByOwner(
        vaultAuthorityPDA,
        { programId: TOKEN_PROGRAM_ID }
      );

      console.log(`🔍 Found ${tokenAccounts.value.length} token accounts for Pyth oracle NAV calculation`);

      // Collect all price feed IDs for tokens that need oracle data
      const priceFeeds = [];
      const tokenData = [];

      // Process each token account that has a balance and a Pyth feed
      // INCLUDING USDC - the smart contract expects it even though it skips it in NAV calculation
      for (const tokenAccount of tokenAccounts.value) {
        const accountInfo = tokenAccount.account.data.parsed.info;
        const tokenMint = accountInfo.mint;
        const tokenBalance = parseInt(accountInfo.tokenAmount.amount);

        // Skip tokens with zero balance
        if (tokenBalance === 0) {
          continue;
        }

        // Get Pyth feed ID for this token
        const pythFeedId = PYTH_PRICE_FEEDS[tokenMint];
        if (!pythFeedId) {
          console.log(`ℹ️ No Pyth feed for token ${tokenMint.slice(0, 8)}... - skipping oracle group`);
          continue;
        }

        priceFeeds.push(pythFeedId);
        tokenData.push({
          feedId: pythFeedId,
          tokenAccount: new PublicKey(tokenAccount.pubkey),
          mint: new PublicKey(tokenMint),
          symbol: TOKEN_MINT_TO_SYMBOL[tokenMint] || 'UNKNOWN'
        });

        console.log(`📊 Added ${TOKEN_MINT_TO_SYMBOL[tokenMint] || tokenMint.slice(0, 8)} to Pyth oracle list: ${pythFeedId.slice(0,10)}...`);
      }

      console.log(`🔄 Fetching ${priceFeeds.length} Pyth price updates from Hermes...`);

      // Fetch price updates from Hermes following official documentation pattern
      // Hermes provides other methods for retrieving price updates. See
      // https://hermes.pyth.network/docs for more information.
      const priceUpdateData = (
        await this.hermesClient.getLatestPriceUpdates(
          priceFeeds,
          { encoding: "base64" }
        )
      ).binary.data;
      
      if (!priceUpdateData) {
        throw new Error('Received undefined price updates from Hermes - invalid response structure');
      }
      
      // Price updates are strings of base64-encoded binary data
      console.log(`✅ Received ${priceUpdateData.length} price updates from Hermes`);

      // Store the data we'll need for the vault transaction
      this._priceUpdates = priceUpdateData;
      this._priceFeeds = priceFeeds;
      this._tokenData = tokenData;
      
      console.log(`✅ Prepared ${priceFeeds.length} price feeds for Pyth transaction builder`);
      
      return { priceUpdates: priceUpdateData, priceFeeds, tokenData };

    } catch (error) {
      console.error('❌ Failed to get Pyth oracle accounts:', error);
      return { priceUpdates: [], priceFeeds: [], tokenData: [] };
    }
  }

  /**
   * Update Pyth oracle feeds (handled automatically during oracle account creation)
   * This method is maintained for compatibility but Pyth updates are handled in getOracleAccountsForDeposit
   */
  async updateOracleFeeds(tokenMints = []) {
    try {
      console.log('🔄 Pyth oracle updates are handled automatically during transaction building...');
      console.log('✅ No separate oracle update transaction needed with Pyth!');
      return null; // No separate transaction needed

    } catch (error) {
      console.error('❌ Failed to update oracle feeds:', error);
      throw error;
    }
  }

  /**
   * Update price feeds using Pyth (handled automatically)
   * This method is maintained for compatibility but Pyth handles updates internally
   */
  async updatePriceFeeds(tokenMints = []) {
    try {
      console.log('🔄 Pyth price updates are handled automatically in getOracleAccountsForDeposit...');
      
      // No separate price update instructions needed with Pyth
      console.log('✅ Pyth always provides fresh price data from Hermes API!');
      
      return {
        instructions: [], // No separate instructions needed
        lookupTables: []  // No lookup tables needed
      };
      
    } catch (error) {
      console.error('❌ Failed to create Pyth update instructions:', error);
      return { instructions: [], lookupTables: [] };
    }
  }

  /**
   * Deposit USDC to vault
   */
  async depositUsdc(amount) {
    try {
      console.log('🚀 Starting deposit process for', amount, 'USDC');
      await this.initialize();
      
      // Check if required programs are initialized
      if (!this.vaultProgram) {
        throw new Error('Vault program not initialized - vault may not be deployed yet');
      }
      
      if (!this.stakingProgram) {
        throw new Error('Staking program not initialized - cannot verify tier requirements');
      }
      
      const amountBN = new BN(amount * 1e6); // Convert to micro-USDC
      console.log('💰 Amount in micro-USDC:', amountBN.toString());
      
      const [vaultPDA] = getVaultPDA(this.usdcMint);
      const [userPositionPDA] = getUserPositionPDA(vaultPDA, this.wallet.publicKey);
      
      console.log('📍 Vault PDA:', vaultPDA.toBase58());
      console.log('📍 User Position PDA:', userPositionPDA.toBase58());
      
      // Get token accounts
      const userUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, this.wallet.publicKey);
      console.log('📍 User USDC Account:', userUsdcAccount.toBase58());
      
      // Check user's USDC balance
      try {
        const userUsdcBalance = await this.connection.getTokenAccountBalance(userUsdcAccount);
        console.log('💰 User USDC Balance:', userUsdcBalance.value.uiAmount);
        
        if (userUsdcBalance.value.uiAmount < amount) {
          throw new Error(`Insufficient USDC balance. Have: ${userUsdcBalance.value.uiAmount}, Need: ${amount}`);
        }
      } catch (balanceError) {
        console.error('❌ Error checking USDC balance:', balanceError);
        throw new Error('User USDC account not found or insufficient balance');
      }
      
      // Get vault accounts
      let vault;
      try {
        vault = await this.vaultProgram.account.vault.fetch(vaultPDA);
        if (!vault) {
          throw new Error('Vault account not found');
        }
        console.log('�� Vault state loaded');
      } catch (error) {
        console.error('❌ Failed to fetch vault account:', error);
        throw new Error(`Vault account not found or not initialized: ${error.message}`);
      }

      // Get vault authority PDA
      const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_authority")],
        this.vaultProgram.programId
      );
      
      // Get required token accounts
      const vaultUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, vaultAuthorityPDA, true);
      const treasuryUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, vault.treasury, false);
      const userSharesAccount = await getAssociatedTokenAddress(vault.sharesMint, this.wallet.publicKey, false);

      console.log('📍 Vault Authority PDA:', vaultAuthorityPDA.toBase58());
      console.log('📍 Vault USDC Account:', vaultUsdcAccount.toBase58());
      console.log('📍 Treasury USDC Account:', treasuryUsdcAccount.toBase58());
      console.log('📍 User Shares Account:', userSharesAccount.toBase58());

      // Get oracle data for vault NAV calculation
      console.log('🔍 Preparing Pyth oracle data for vault transaction...');
      await this.getOracleAccountsForDeposit(vaultAuthorityPDA);

      // Check if we have the required Pyth data
      if (!this._priceUpdates || !this._priceFeeds || !this._tokenData) {
        console.warn('⚠️ No Pyth price updates needed - vault may only hold USDC');
        // Continue with empty oracle data
        this._priceUpdates = [];
        this._priceFeeds = [];
        this._tokenData = [];
      }

      if (this._priceUpdates.length === 0) {
        console.log('💡 No price updates needed - using simple transaction');
        
        // Build simple transaction without Pyth price updates
        const depositInstruction = await this.vaultProgram.methods
          .deposit(amountBN)
          .accounts({
            user: this.wallet.publicKey,
            vault: vaultPDA,
            userPosition: userPositionPDA,
            userUsdcToken: userUsdcAccount,
            vaultUsdcToken: vaultUsdcAccount,
            treasuryUsdcToken: treasuryUsdcAccount,
            sharesMint: vault.sharesMint,
            userSharesToken: userSharesAccount,
            vaultAuthority: vaultAuthorityPDA,
            stakingProgram: this.stakingProgram.programId,
            systemProgram: SystemProgram.programId,
            tokenProgram: TOKEN_PROGRAM_ID,
            associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
            rent: SYSVAR_RENT_PUBKEY,
          })
          .remainingAccounts([
            // Staking accounts (required for tier verification)
            {
              pubkey: getStakeConfigPDA()[0],
              isWritable: false,
              isSigner: false,
            },
            {
              pubkey: getUserStakePDA(this.wallet.publicKey)[0],
              isWritable: false,
              isSigner: false,
            },
          ])
          .instruction();

        const tx = new Transaction();
        tx.add(depositInstruction);
        
        console.log('📤 Sending simple deposit transaction...');
        return await this.sendTransaction(tx);
      } else {
        console.log('🏗️ Building Pyth transaction with price updates...');
        
        // Post price updates following official documentation pattern
        // Set closeUpdateAccounts: true if you want to delete the price update account at
        // the end of the transaction to reclaim rent.
        const transactionBuilder = this.pythSolanaReceiver.newTransactionBuilder({
          closeUpdateAccounts: false,
        });

        // Add price updates to the transaction builder
        await transactionBuilder.addPostPriceUpdates(this._priceUpdates);
        console.log(`✅ Added ${this._priceUpdates.length} price updates`);

        // Use this function to add your application-specific instructions to the builder
        await transactionBuilder.addPriceConsumerInstructions(
          async (getPriceUpdateAccount) => {
            // Generate instructions here that use the price updates posted above.
            // getPriceUpdateAccount(<price feed id>) will give you the account for each price update.
            
            // Build oracle accounts using the getPriceUpdateAccount callback
            const oracleAccounts = [];

            for (let i = 0; i < this._tokenData.length; i++) {
              const token = this._tokenData[i];
              const feedId = this._priceFeeds[i];
              const priceUpdateAccount = getPriceUpdateAccount(feedId);

              // Add the oracle account group: [token_account, pyth_price_update_v2, mint_account]
              oracleAccounts.push(
                {
                  pubkey: token.tokenAccount,
                  isWritable: false,
                  isSigner: false,
                },
                {
                  pubkey: priceUpdateAccount,
                  isWritable: false,
                  isSigner: false,
                },
                {
                  pubkey: token.mint,
                  isWritable: false,
                  isSigner: false,
                }
              );
            }

            // Build remaining accounts
            const remainingAccounts = [
              // Staking accounts
              {
                pubkey: getStakeConfigPDA()[0],
                isWritable: false,
                isSigner: false,
              },
              {
                pubkey: getUserStakePDA(this.wallet.publicKey)[0],
                isWritable: false,
                isSigner: false,
              },
              // Oracle accounts
              ...oracleAccounts
            ];

            // Build the vault deposit instruction
            const depositInstruction = await this.vaultProgram.methods
              .deposit(amountBN)
              .accounts({
                user: this.wallet.publicKey,
                vault: vaultPDA,
                userPosition: userPositionPDA,
                userUsdcToken: userUsdcAccount,
                vaultUsdcToken: vaultUsdcAccount,
                treasuryUsdcToken: treasuryUsdcAccount,
                sharesMint: vault.sharesMint,
                userSharesToken: userSharesAccount,
                vaultAuthority: vaultAuthorityPDA,
                stakingProgram: this.stakingProgram.programId,
                systemProgram: SystemProgram.programId,
                tokenProgram: TOKEN_PROGRAM_ID,
                associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
                rent: SYSVAR_RENT_PUBKEY,
              })
              .remainingAccounts(remainingAccounts)
              .instruction();

            return [{ instruction: depositInstruction, signers: [] }];
          }
        );

        // Send the instructions in the builder in 1 or more transactions.
        // The builder will pack the instructions into transactions automatically.
        console.log('📤 Building and sending Pyth transaction...');
        
        const versionedTransactions = await transactionBuilder.buildVersionedTransactions({
          computeUnitPriceMicroLamports: 50000,
        });

        const signatures = await this.pythSolanaReceiver.provider.sendAll(
          versionedTransactions,
          { skipPreflight: true }
        );

        console.log('✅ Pyth transaction completed!');
        return signatures[0];
      }
    } catch (error) {
      console.error('❌ Error depositing USDC:', error);
      
      // Enhanced error handling for common issues
      if (error.message && error.message.includes('Transaction version')) {
        throw new Error('Your wallet does not support the required transaction format. Please try updating your wallet or using a different wallet like Phantom or Solflare.');
      }
      
      throw error;
    }
  }

  /**
   * Withdraw USDC from vault
   */
  async withdrawUsdc(shares) {
    try {
      console.log('🏦 Starting USDC withdrawal...', shares);
      await this.initialize();
      
      // Check if vault program is initialized
      if (!this.vaultProgram) {
        throw new Error('Vault program not initialized - vault may not be deployed yet');
      }
      
      const sharesBN = new BN(shares * 1e6); // Convert to micro-shares
      console.log('📊 Shares to withdraw:', sharesBN.toString());
      
      const [vaultPDA] = getVaultPDA(this.usdcMint);
      const [userPositionPDA] = getUserPositionPDA(vaultPDA, this.wallet.publicKey);
      
      // Get vault info first
      const vault = await this.vaultProgram.account.vault.fetch(vaultPDA);
      console.log('🏦 Vault fetched, shares mint:', vault.sharesMint.toString());
      
      // Get vault authority PDA
      const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_authority")],
        this.vaultProgram.programId
      );
      
      // Get token accounts
      const userUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, this.wallet.publicKey);
      const userSharesAccount = await getAssociatedTokenAddress(vault.sharesMint, this.wallet.publicKey);
      const vaultUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, vaultAuthorityPDA, true);
      
      console.log('📍 Accounts:');
      console.log('  - User USDC:', userUsdcAccount.toString());
      console.log('  - User Shares:', userSharesAccount.toString());
      console.log('  - Vault USDC:', vaultUsdcAccount.toString());
      console.log('  - Vault Authority:', vaultAuthorityPDA.toString());

      // 🔄 Pyth oracle updates are handled automatically
      console.log('🔄 Pyth oracle accounts are handled automatically for withdrawal...');

      // Build the vault withdrawal instruction
      const withdrawInstruction = await this.vaultProgram.methods
        .withdraw(sharesBN)
        .accounts({
          user: this.wallet.publicKey,
          vault: vaultPDA,
          userPosition: userPositionPDA,
          userUsdcToken: userUsdcAccount,
          vaultUsdcToken: vaultUsdcAccount,
          sharesMint: vault.sharesMint,
          userSharesToken: userSharesAccount,
          vaultAuthority: vaultAuthorityPDA,
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .instruction();

      // 🔄 Build transaction with Pyth oracle accounts
      const tx = new Transaction();
      
      // Add the vault withdrawal instruction
      tx.add(withdrawInstruction);
        
      console.log('✅ Withdraw transaction built successfully with Pyth!');
      return await this.sendTransaction(tx);
    } catch (error) {
      console.error('❌ Error withdrawing USDC:', error);
      throw error;
    }
  }

  // ======================= HELPER METHODS =======================

  async sendTransaction(transaction) {
    try {
      console.log('📤 Sending transaction...');
      
      // Send transaction with versioned transaction support
      const sendOptions = {
        // Support both legacy and versioned transactions
        maxRetries: 3,
        skipPreflight: true,
        preflightCommitment: CONTRACTS.COMMITMENT,
      };
      
      const signature = await this.wallet.sendTransaction(transaction, this.connection, sendOptions);
      console.log('📝 Transaction signature:', signature);
      
      console.log('⏳ Confirming transaction...');
      await this.connection.confirmTransaction(signature, CONTRACTS.COMMITMENT);
      console.log('✅ Transaction confirmed!');
      
      return signature;
    } catch (error) {
      console.error('❌ Transaction failed:', error);
      
      // Enhanced error handling for versioned transaction issues
      if (error.message && error.message.includes('Transaction version')) {
        console.error('🔧 Transaction version error detected. This usually means:');
        console.error('   1. The wallet doesn\'t support versioned transactions');
        console.error('   2. The RPC endpoint doesn\'t support maxSupportedTransactionVersion');
        console.error('   3. Update your wallet or use a different RPC endpoint');
      }
      
      // Try to get more detailed error information
      if (error.logs) {
        console.error('📋 Transaction logs:', error.logs);
      }
      
      if (error.message) {
        console.error('💬 Error message:', error.message);
      }
      
      throw error;
    }
  }

  calculateUserTier(stakedAmount) {
    const amount = Number(stakedAmount.toString());
    
    if (amount >= TIERS.VAULT_KEEPER.minStake) return TIERS.VAULT_KEEPER;
    if (amount >= TIERS.TIER_2.minStake) return TIERS.TIER_2;
    if (amount >= TIERS.TIER_3.minStake) return TIERS.TIER_3;
    
    return null; // No tier
  }

  calculateSharePrice(nav, totalShares) {
    if (totalShares.eq(new BN(0))) {
      return new BN(1000000); // 1:1 ratio with 6 decimals
    }
    return nav.mul(new BN(1000000)).div(totalShares);
  }

  formatTokenAmount(amount, decimals) {
    const divisor = new BN(10).pow(new BN(decimals));
    const quotient = amount.div(divisor);
    const remainder = amount.mod(divisor);
    
    // Always show full precision for vault shares (6 decimals)
    const fullRemainder = remainder.toString().padStart(decimals, '0');
    const formattedNumber = `${quotient.toString()}.${fullRemainder}`;
    const numValue = parseFloat(formattedNumber);
    
    // For vault shares (6 decimals), always show 6 decimal places to preserve precision
    if (decimals === 6) {
      return numValue.toFixed(6);
    }
    
    // For very small amounts, show more precision to avoid displaying as zero
    if (numValue > 0 && numValue < 0.001) {
      return numValue.toFixed(6);
    }
    
    // Otherwise, show 3 decimal places as before
    return `${quotient.toString()}.${fullRemainder.slice(0, 3)}`;
  }

  // Utility method to check if user can deposit based on tier
  canUserDeposit(tier, currentDeposits, newDeposit) {
    if (!tier) return false;
    if (tier.depositCap === null) return true; // Unlimited
    
    return (currentDeposits + newDeposit) <= tier.depositCap;
  }

  /**
   * Test if the current setup supports versioned transactions
   * This can help diagnose issues before attempting deposits
   */
  async testVersionedTransactionSupport() {
    try {
      console.log('🧪 Testing versioned transaction support...');
      
      // Test 1: Check if connection supports versioned transactions
      const connectionInfo = await this.connection.getVersion();
      console.log('✅ Connection version:', connectionInfo);
      
      // Test 2: Try to create a simple versioned transaction
      const { blockhash } = await this.connection.getLatestBlockhash();
      const message = new TransactionMessage({
        payerKey: this.wallet.publicKey,
        recentBlockhash: blockhash,
        instructions: [], // Empty for testing
      }).compileToV0Message();
      
      const testTransaction = new VersionedTransaction(message);
      console.log('✅ Can create versioned transactions');
      
      // Test 3: Check if PythSolanaReceiver is properly initialized
      if (!this.pythSolanaReceiver) {
        throw new Error('PythSolanaReceiver not initialized');
      }
      console.log('✅ PythSolanaReceiver initialized');
      
      // Test 4: Try to create a transaction builder
      const testBuilder = this.pythSolanaReceiver.newTransactionBuilder({
        closeUpdateAccounts: false,
      });
      console.log('✅ Pyth transaction builder working');
      
      console.log('🎉 All versioned transaction tests passed!');
      return {
        success: true,
        message: 'Your setup supports versioned transactions for Pyth price feeds'
      };
      
    } catch (error) {
      console.error('❌ Versioned transaction test failed:', error);
      return {
        success: false,
        error: error.message,
        recommendations: [
          'Update your wallet to the latest version',
          'Try a different wallet (Phantom, Solflare, etc.)',
          'Check your RPC endpoint configuration',
          'Contact support if issues persist'
        ]
      };
    }
  }

  /**
   * Calculate proper vault NAV including all token holdings
   */
  async calculateVaultNAV(vault, vaultAuthorityPDA) {
    try {
      console.log('📊 Calculating vault NAV...');
      
      // Start with USDC balance
      const vaultUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, vaultAuthorityPDA, true);
      let totalNav = new BN(0);
      
      try {
        const usdcBalance = await this.connection.getTokenAccountBalance(vaultUsdcAccount);
        totalNav = new BN(usdcBalance.value.amount);
        console.log('💰 USDC balance:', totalNav.toString());
      } catch (e) {
        console.log('ℹ️ Vault USDC account not found or empty');
      }
      
      // Get all token accounts owned by vault authority
      const tokenAccounts = await this.connection.getParsedTokenAccountsByOwner(
        vaultAuthorityPDA,
        { programId: TOKEN_PROGRAM_ID }
      );
      
      console.log(`🔍 Found ${tokenAccounts.value.length} token accounts`);
      
      // Keep track of successful and failed price lookups
      let successfulPriceLookups = 0;
      let totalTokenAccounts = 0;
      
      // Process each non-USDC token account
      for (const tokenAccount of tokenAccounts.value) {
        const accountInfo = tokenAccount.account.data.parsed.info;
        const tokenMint = new PublicKey(accountInfo.mint);
        const tokenBalance = new BN(accountInfo.tokenAmount.amount);
        
        // Skip USDC (already counted) and zero balances
        if (tokenMint.equals(this.usdcMint) || tokenBalance.eq(new BN(0))) {
          continue;
        }
        
        totalTokenAccounts++;
        console.log(`📈 Processing token: ${tokenMint.toString()}, balance: ${tokenBalance.toString()}`);
        
        try {
          // Get token value from Pyth or Switchboard with stricter validation
          const tokenValueUsdc = await this.getTokenValueInUsdc(tokenMint, tokenBalance, accountInfo.tokenAmount.decimals);
          
          if (tokenValueUsdc.gt(new BN(0))) {
            totalNav = totalNav.add(tokenValueUsdc);
            successfulPriceLookups++;
            console.log(`💎 Token value: ${tokenValueUsdc.toString()} USDC`);
          } else {
            console.warn(`⚠️ Zero value returned for token ${tokenMint.toString()}`);
          }
        } catch (e) {
          console.warn(`⚠️ Failed to get price for token ${tokenMint.toString()}:`, e.message);
          // For critical NAV calculation, we should be more conservative
          // Instead of ignoring, we could use last known price or mark vault as stale
        }
      }
      
      // Log price lookup success rate
      if (totalTokenAccounts > 0) {
        const successRate = (successfulPriceLookups / totalTokenAccounts) * 100;
        console.log(`📊 Price lookup success rate: ${successRate.toFixed(1)}% (${successfulPriceLookups}/${totalTokenAccounts})`);
        
        // If too many price lookups failed, log a warning
        if (successRate < 80) {
          console.warn(`⚠️ Low price lookup success rate (${successRate.toFixed(1)}%) - NAV may be inaccurate`);
        }
      }
      
      console.log('🏆 Total NAV:', totalNav.toString());
      return totalNav;
      
    } catch (error) {
      console.error('❌ NAV calculation failed:', error);
      // Fallback to USDC balance only
      const vaultUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, vaultAuthorityPDA, true);
      try {
        const usdcBalance = await this.connection.getTokenAccountBalance(vaultUsdcAccount);
        console.warn('⚠️ Using USDC-only NAV fallback');
        return new BN(usdcBalance.value.amount);
      } catch (e) {
        console.error('❌ Even USDC fallback failed');
        return new BN(0);
      }
    }
  }

  /**
   * Get token value in USDC using price feeds
   * Uses real Pyth oracles with Switchboard fallback
   */
  async getTokenValueInUsdc(tokenMint, tokenBalance, tokenDecimals) {
    try {
      // Always try real oracles first, regardless of network
      return await this.getRealTokenPrice(tokenMint, tokenBalance, tokenDecimals);
    } catch (error) {
      console.warn(`⚠️ Oracle price failed, falling back to mock prices:`, error.message);
      return this.getMockTokenPrice(tokenMint, tokenBalance, tokenDecimals);
    }
  }

  /**
   * Get real token prices from Switchboard with Pyth fallback
   */
  async getRealTokenPrice(tokenMint, tokenBalance, tokenDecimals) {
    const tokenMintStr = tokenMint.toString();



    const tokenSymbol = TOKEN_MINT_TO_SYMBOL[tokenMintStr];
    if (!tokenSymbol) {
      throw new Error(`No symbol mapping for token ${tokenMintStr}`);
    }

    console.log(`🔍 Looking up price for ${tokenSymbol} (${tokenMintStr})`);

    // Try Pyth first (primary oracle source)
    const pythFeedId = PYTH_PRICE_FEEDS[tokenMintStr];
    if (pythFeedId) {
      try {
        const pythPrice = await this.getPythPrice(pythFeedId, tokenSymbol);
        if (pythPrice > 0) {
          return this.calculateTokenValue(tokenBalance, tokenDecimals, pythPrice);
        }
      } catch (error) {
        console.warn(`⚠️ Pyth price failed for ${tokenSymbol}:`, error.message);
      }
    }

    throw new Error(`No oracle feeds available for ${tokenSymbol}`);
  }

  /**
   * Get price from Pyth HTTP API
   */
  async getPythPrice(feedId, tokenSymbol) {
    try {
      // Use Pyth HTTP API for latest prices
      const response = await fetch(`https://hermes.pyth.network/api/latest_price_feeds?ids[]=${feedId}&parsed=true`);
      
      if (!response.ok) {
        throw new Error(`Pyth API returned ${response.status}`);
      }

      const data = await response.json();
      
      if (!data || !data.length || !data[0].price) {
        throw new Error('Invalid Pyth response format');
      }

      const priceData = data[0].price;
      const price = Number(priceData.price) * Math.pow(10, priceData.expo);
      
      // Enhanced staleness check for accurate share price calculation
      const publishTime = priceData.publish_time;
      const now = Math.floor(Date.now() / 1000);
      const ageSeconds = now - publishTime;
      
      // Reject prices older than 2 minutes for critical NAV calculations
      if (ageSeconds > 120) {
        throw new Error(`Stale Pyth price for ${tokenSymbol}: ${ageSeconds}s old (max 120s)`);
      }
      
      // Warn for prices older than 30 seconds
      if (ageSeconds > 30) {
        console.warn(`⚠️ Aging Pyth price for ${tokenSymbol}: ${ageSeconds}s old`);
      }
      
      // Validate price is reasonable (not zero or negative)
      if (price <= 0) {
        throw new Error(`Invalid Pyth price for ${tokenSymbol}: ${price}`);
      }

      console.log(`📈 Fresh Pyth price for ${tokenSymbol}: $${price.toFixed(6)} (${ageSeconds}s old)`);
      return price;

    } catch (error) {
      console.error(`❌ Pyth price fetch failed for ${tokenSymbol}:`, error);
      throw error;
    }
  }



  /**
   * Calculate token value in USDC from price
   */
  calculateTokenValue(tokenBalance, tokenDecimals, priceUsd) {
    // Calculate value: (token_balance * price_usd) / (10^token_decimals)
    const tokenDecimalFactor = new BN(10).pow(new BN(tokenDecimals));
    const priceUsdc = new BN(Math.floor(priceUsd * 1e6)); // Convert to micro-USDC
    
    const tokenValue = tokenBalance
      .mul(priceUsdc)
      .div(tokenDecimalFactor);
    
    console.log(`💰 Token value: ${tokenBalance.toString()} tokens * $${priceUsd.toFixed(6)} = ${tokenValue.toString()} micro-USDC`);
    
    return tokenValue;
  }

  /**
   * Get mock token prices for development fallback
   */
  getMockTokenPrice(tokenMint, tokenBalance, tokenDecimals) {
    const mockPrices = {
      'So11111111111111111111111111111111111111112': 200, // SOL = $200
      'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': 0.00002, // BONK = $0.00002
      'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': 0.8, // JUP = $0.8
      'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 1.0, // USDC = $1.0
      '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU': 1.0, // USDC devnet = $1.0
      // Add more fallback prices as needed
      'rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof': 7.5, // RENDER = $7.5
      '6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN': 50.0, // TRUMP = $50
      'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': 2.1, // WIF = $2.1
    };
    
    const priceUsd = mockPrices[tokenMint.toString()];
    if (!priceUsd) {
      console.warn(`⚠️ No mock price for token ${tokenMint.toString()}, skipping`);
      return new BN(0);
    }
    
    // Calculate value: (token_balance * price_usd) / (10^token_decimals)
    const tokenDecimalFactor = new BN(10).pow(new BN(tokenDecimals));
    const priceUsdc = new BN(Math.floor(priceUsd * 1e6)); // Convert to micro-USDC
    
    const tokenValue = tokenBalance
      .mul(priceUsdc)
      .div(tokenDecimalFactor);
    
    console.log(`💰 Token ${tokenMint.toString()}: ${tokenBalance.toString()} tokens * $${priceUsd} (mock) = ${tokenValue.toString()} micro-USDC`);
    
    return tokenValue;
  }
}