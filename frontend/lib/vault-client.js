/**
 * Calvin Vault Client - Smart Contract Integration
 */

import { 
  Connection, 
  PublicKey, 
  Transaction,
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
import { AnchorProvider, BN } from '@coral-xyz/anchor';
import { 
  getStakingProgram, 
  getVaultProgram,
  getStakeConfigPDA,
  getUserStakePDA,
  getVaultPDA,
  getUserPositionPDA
} from './anchor-program';
import { CONTRACTS, TIERS, FEES } from '@/constants';

export class VaultClient {
  constructor(wallet, connection) {
    this.wallet = wallet;
    this.connection = connection || new Connection(CONTRACTS.RPC_ENDPOINT, CONTRACTS.COMMITMENT);
    this.provider = null;
    this.stakingProgram = null;
    this.vaultProgram = null;
    
    this.usdcMint = new PublicKey(CONTRACTS.USDC);
    this.calvinMint = new PublicKey(CONTRACTS.CALVIN_TOKEN);
    
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
        console.log('✅ Staking program initialized with ID:', this.stakingProgram.programId.toString());
        
        // Verify staking program ID matches expected (no hardcoding)
        if (this.stakingProgram.programId.toString() !== CONTRACTS.CALVIN_STAKING_PROGRAM) {
          console.error('❌ Staking program ID mismatch!', {
            expected: CONTRACTS.CALVIN_STAKING_PROGRAM,
            actual: this.stakingProgram.programId.toString()
          });
        }
      } catch (stakingError) {
        console.error('❌ Failed to initialize staking program:', stakingError);
        this.stakingProgram = null;
      }

      try {
        // Initialize vault program
        this.vaultProgram = getVaultProgram(provider);
        console.log('✅ Vault program initialized with ID:', this.vaultProgram.programId.toString());
        
        // Verify vault program ID matches expected (no hardcoding)
        if (this.vaultProgram.programId.toString() !== CONTRACTS.CALVIN_VAULT_PROGRAM) {
          console.error('❌ Vault program ID mismatch!', {
            expected: CONTRACTS.CALVIN_VAULT_PROGRAM,
            actual: this.vaultProgram.programId.toString()
          });
        }
      } catch (vaultError) {
        console.error('❌ Failed to initialize vault program:', vaultError);
        this.vaultProgram = null;
      }

      // Test program connectivity
      if (this.vaultProgram) {
        try {
          // Try to get program account info to test connectivity
          const programAccount = await this.connection.getAccountInfo(this.vaultProgram.programId);
          if (!programAccount) {
            console.error('❌ Vault program account not found on network');
            this.vaultProgram = null;
          } else {
            console.log('✅ Vault program verified on network');
          }
        } catch (connectivityError) {
          console.error('❌ Failed to verify vault program connectivity:', connectivityError);
        }
      }

      if (this.stakingProgram) {
        try {
          // Try to get program account info to test connectivity
          const programAccount = await this.connection.getAccountInfo(this.stakingProgram.programId);
          if (!programAccount) {
            console.error('❌ Staking program account not found on network');
            this.stakingProgram = null;
          } else {
            console.log('✅ Staking program verified on network');
          }
        } catch (connectivityError) {
          console.error('❌ Failed to verify staking program connectivity:', connectivityError);
        }
      }

      console.log('📋 VaultClient initialization summary:', {
        stakingProgram: this.stakingProgram ? '✅ Ready' : '❌ Failed',
        vaultProgram: this.vaultProgram ? '✅ Ready' : '❌ Failed',
        wallet: this.wallet?.publicKey ? `✅ ${this.wallet.publicKey.toString().slice(0, 8)}...` : '❌ No wallet',
        network: this.connection.rpcEndpoint
      });

    } catch (error) {
      console.error('❌ VaultClient initialization failed:', error);
      // Set programs to null on initialization failure
      this.stakingProgram = null;
      this.vaultProgram = null;
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
   * Get oracle accounts for NAV calculation during deposits
   * Returns oracle accounts in the format expected by the smart contract:
   * Groups of 3: [token_account, price_account, mint_account]
   */
  async getOracleAccountsForDeposit(vaultAuthorityPDA) {
    try {
      // Token mint to Pyth price feed mapping (from oracle_config.rs)
      const PYTH_PRICE_FEEDS = {
        'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': '0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a', // USDC
        '6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN': '0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a', // TRUMP
        'rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof': '0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d', // RENDER
        'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': '0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996', // JUP
        'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': '0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419', // BONK
        '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump': '0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608', // FARTCOIN
        '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R': '0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a', // RAY
        'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL': '0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2', // JTO
        'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3': '0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d0d719579ff', // PYTH
        'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': '0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc', // WIF
        '3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y': '0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b', // VIRTUAL
        '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv': '0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61', // PENGU
        '85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ': '0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389', // W
        '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr': '0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce', // POPCAT
        'Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7': '0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a', // ATH
        'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5': '0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d', // MEW
        'MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey': '0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a', // MNDE
        'J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr': '0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a', // SPX
        'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE': '0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c', // ORCA
      };

      // Get all token accounts owned by vault authority to determine which oracles we need
      const tokenAccounts = await this.connection.getParsedTokenAccountsByOwner(
        vaultAuthorityPDA,
        { programId: TOKEN_PROGRAM_ID }
      );

      console.log(`🔍 Found ${tokenAccounts.value.length} token accounts for oracle NAV calculation`);

      const oracleAccounts = [];

      // Always include USDC oracle accounts to satisfy smart contract requirements
      // Use the vault's main USDC account (from instruction accounts) as the token account
      const usdcMint = this.usdcMint.toString();
      const usdcFeedId = PYTH_PRICE_FEEDS[usdcMint];
      
      if (usdcFeedId) {
        try {
          // Get vault authority PDA and its USDC token account
          const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
            [Buffer.from("vault_authority")],
            this.vaultProgram.programId
          );
          
          // Use the vault's main USDC account (even if it doesn't exist yet)
          const { getAssociatedTokenAddress } = await import('@solana/spl-token');
          const vaultUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, vaultAuthorityPDA, true);
          
          const feedIdBytes = Buffer.from(usdcFeedId.slice(2), 'hex');
          const priceAccountPubkey = new PublicKey(feedIdBytes);

          // Add USDC oracle group - always include this for contract compliance
          oracleAccounts.push(
            {
              pubkey: vaultUsdcAccount, // Use vault's main USDC account
              isWritable: false,
              isSigner: false,
            },
            {
              pubkey: priceAccountPubkey,
              isWritable: false,
              isSigner: false,
            },
            {
              pubkey: new PublicKey(usdcMint),
              isWritable: false,
              isSigner: false,
            }
          );

          console.log(`📊 Added USDC oracle group: token=${vaultUsdcAccount.toString().slice(0,8)}..., price=${priceAccountPubkey.toString().slice(0,8)}..., mint=${usdcMint.slice(0,8)}...`);
          console.log(`🔢 Oracle accounts length after USDC: ${oracleAccounts.length}`);
        } catch (error) {
          console.warn(`⚠️ Failed to add USDC oracle accounts:`, error);
          console.log(`🔢 Oracle accounts length after USDC error: ${oracleAccounts.length}`);
        }
      }

      // Process each non-USDC token account that has a balance
      for (const tokenAccount of tokenAccounts.value) {
        const accountInfo = tokenAccount.account.data.parsed.info;
        const tokenMint = accountInfo.mint;
        const tokenBalance = parseInt(accountInfo.tokenAmount.amount);

        // Skip tokens with zero balance
        if (tokenBalance === 0) {
          continue;
        }

        // Skip USDC (already handled above)
        if (tokenMint === this.usdcMint.toString()) {
          continue;
        }

        // Get Pyth price feed ID for this token
        const pythFeedId = PYTH_PRICE_FEEDS[tokenMint];
        if (!pythFeedId) {
          console.warn(`⚠️ No Pyth feed found for token ${tokenMint}`);
          continue;
        }

        try {
          // Convert hex feed ID to Pubkey (same as test script that worked)
          const feedIdBytes = Buffer.from(pythFeedId.slice(2), 'hex'); // Remove 0x prefix
          const priceAccountPubkey = new PublicKey(feedIdBytes);

          // Add the oracle account group: [token_account, price_account, mint_account]
          oracleAccounts.push(
            {
              pubkey: new PublicKey(tokenAccount.pubkey),
              isWritable: false,
              isSigner: false,
            },
            {
              pubkey: priceAccountPubkey,
              isWritable: false,
              isSigner: false,
            },
            {
              pubkey: new PublicKey(tokenMint),
              isWritable: false,
              isSigner: false,
            }
          );

          console.log(`📊 Added oracle group for ${tokenMint}: token=${tokenAccount.pubkey.slice(0,8)}..., price=${priceAccountPubkey.toString().slice(0,8)}..., mint=${tokenMint.slice(0,8)}...`);

        } catch (error) {
          console.warn(`⚠️ Failed to create oracle accounts for token ${tokenMint}:`, error);
        }
      }

      console.log(`✅ Prepared ${oracleAccounts.length / 3} oracle groups (${oracleAccounts.length} total accounts) for NAV calculation`);
      console.log(`🔍 Oracle accounts details:`, oracleAccounts.map((acc, i) => `[${i}] ${acc.pubkey.toString().slice(0,8)}...`));
      
      // 🔍 DEBUG: Detailed oracle account structure
      console.log('🔍 Detailed oracle account structure:');
      for (let i = 0; i < oracleAccounts.length; i += 3) {
        const group = Math.floor(i / 3);
        if (i + 2 < oracleAccounts.length) {
          console.log(`  Group ${group}:`);
          console.log(`    [${i}] Token: ${oracleAccounts[i].pubkey.toString()}`);
          console.log(`    [${i+1}] Price: ${oracleAccounts[i+1].pubkey.toString()}`);
          console.log(`    [${i+2}] Mint: ${oracleAccounts[i+2].pubkey.toString()}`);
        }
      }
      
      return oracleAccounts;

    } catch (error) {
      console.error('❌ Failed to get oracle accounts:', error);
      return []; // Return empty array if oracle setup fails
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
        console.log('📋 Vault state loaded:', {
          sharesMint: vault.sharesMint.toBase58(),
          treasury: vault.treasury.toBase58(),
          paused: vault.paused
        });
      } catch (error) {
        console.error('❌ Failed to fetch vault account:', error);
        throw new Error(`Vault account not found or not initialized: ${error.message}`);
      }

      // Get vault authority PDA
      const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_authority")],
        this.vaultProgram.programId
      );
      console.log('📍 Vault Authority PDA:', vaultAuthorityPDA.toBase58());
      
      // Vault USDC account is an ATA owned by vault authority
      const vaultUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, vaultAuthorityPDA, true);
      console.log('📍 Vault USDC Account:', vaultUsdcAccount.toBase58());
      
      // Treasury USDC account (owned by treasury wallet from vault state)
      const treasuryUsdcAccount = await getAssociatedTokenAddress(this.usdcMint, vault.treasury, false);
      console.log('📍 Treasury USDC Account:', treasuryUsdcAccount.toBase58());
      
      // User shares account (will be created and frozen by the instruction)
      const userSharesAccount = await getAssociatedTokenAddress(vault.sharesMint, this.wallet.publicKey, false);
      console.log('📍 User Shares Account:', userSharesAccount.toBase58());

      // 🚨 CRITICAL FIX: Get oracle accounts for NAV calculation
      console.log('🔍 Getting oracle accounts for NAV calculation...');
      const oracleAccounts = await this.getOracleAccountsForDeposit(vaultAuthorityPDA);

      console.log('🏗️ Building transaction with accounts:', {
        user: this.wallet.publicKey.toBase58(),
        vault: vaultPDA.toBase58(),
        userPosition: userPositionPDA.toBase58(),
        userUsdcToken: userUsdcAccount.toBase58(),
        vaultUsdcToken: vaultUsdcAccount.toBase58(),
        treasuryUsdcToken: treasuryUsdcAccount.toBase58(),
        sharesMint: vault.sharesMint.toBase58(),
        userSharesToken: userSharesAccount.toBase58(),
        vaultAuthority: vaultAuthorityPDA.toBase58(),
        stakingProgram: this.stakingProgram.programId.toBase58(),
        oracleAccountsCount: oracleAccounts.length,
      });

      // Build remaining accounts: [staking_accounts, oracle_accounts]
      const remainingAccounts = [
        // Staking accounts (required for tier verification)
        {
          pubkey: getStakeConfigPDA()[0],      // stake_config
          isWritable: false,
          isSigner: false,
        },
        {
          pubkey: getUserStakePDA(this.wallet.publicKey)[0], // user_stake
          isWritable: false,
          isSigner: false,
        },
        // Oracle accounts (required for NAV calculation)
        ...oracleAccounts
      ];

      console.log(`📊 Total remaining accounts: ${remainingAccounts.length} (2 staking + ${oracleAccounts.length} oracle)`);
      
      // 🔍 DEBUG: Log exact remaining accounts structure
      console.log('🔍 Remaining accounts breakdown:');
      remainingAccounts.forEach((acc, i) => {
        console.log(`  [${i}] ${acc.pubkey.toString().slice(0,8)}... (writable: ${acc.isWritable}, signer: ${acc.isSigner})`);
      });
      
      // 🔍 DEBUG: Verify oracle accounts are in groups of 3
      if (oracleAccounts.length > 0) {
        console.log('🔍 Oracle accounts verification:');
        console.log(`  - Oracle accounts length: ${oracleAccounts.length}`);
        console.log(`  - Should be divisible by 3: ${oracleAccounts.length % 3 === 0}`);
        console.log(`  - Number of oracle groups: ${Math.floor(oracleAccounts.length / 3)}`);
        
        for (let i = 0; i < oracleAccounts.length; i += 3) {
          const group = Math.floor(i / 3);
          if (i + 2 < oracleAccounts.length) {
            console.log(`  - Group ${group}: token=${oracleAccounts[i].pubkey.toString().slice(0,8)}..., price=${oracleAccounts[i+1].pubkey.toString().slice(0,8)}..., mint=${oracleAccounts[i+2].pubkey.toString().slice(0,8)}...`);
          }
        }
      }

      const tx = await this.vaultProgram.methods
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
        .transaction();
        
      console.log('✅ Transaction built successfully with oracle accounts');
        
      return await this.sendTransaction(tx);
    } catch (error) {
      console.error('Error depositing USDC:', error);
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

      const tx = await this.vaultProgram.methods
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
        .transaction();
        
      console.log('✅ Withdraw transaction built successfully');
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
      const signature = await this.wallet.sendTransaction(transaction, this.connection);
      console.log('📝 Transaction signature:', signature);
      
      console.log('⏳ Confirming transaction...');
      await this.connection.confirmTransaction(signature, CONTRACTS.COMMITMENT);
      console.log('✅ Transaction confirmed!');
      
      return signature;
    } catch (error) {
      console.error('❌ Transaction failed:', error);
      
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
    
    // For very small amounts, show more precision to avoid displaying as zero
    const fullRemainder = remainder.toString().padStart(decimals, '0');
    const formattedNumber = `${quotient.toString()}.${fullRemainder}`;
    const numValue = parseFloat(formattedNumber);
    
    // If the number is very small but not zero, show at least 6 decimal places
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
   * Get real token prices from Pyth with Switchboard fallback
   */
  async getRealTokenPrice(tokenMint, tokenBalance, tokenDecimals) {
    const tokenMintStr = tokenMint.toString();
    
    // Token mint to symbol mapping from oracle_config.rs
    const TOKEN_MINT_TO_SYMBOL = {
      'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC',
      '6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN': 'TRUMP',
      'rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof': 'RENDER',
      'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': 'JUP',
      'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': 'BONK',
      '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump': 'FARTCOIN',
      '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R': 'RAY',
      'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL': 'JTO',
      'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3': 'PYTH',
      'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': 'WIF',
      '3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizpWAT2Zfyr9y': 'VIRTUAL',
      '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv': 'PENGU',
      '85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ': 'W',
      '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr': 'POPCAT',
      'Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7': 'ATH',
      'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5': 'MEW',
      'MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey': 'MNDE',
      'J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr': 'SPX',
      'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE': 'ORCA',
      'So11111111111111111111111111111111111111112': 'SOL', // Native SOL
    };

    // Pyth price feed IDs from oracle_config.rs
    const PYTH_PRICE_FEEDS = {
      'USDC': '0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a',
      'TRUMP': '0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a',
      'RENDER': '0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d',
      'JUP': '0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996',
      'BONK': '0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419',
      'FARTCOIN': '0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608',
      'RAY': '0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a',
      'JTO': '0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2',
      'PYTH': '0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d0d719579ff',
      'WIF': '0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc',
      'VIRTUAL': '0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b',
      'PENGU': '0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61',
      'W': '0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389',
      'POPCAT': '0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce',
      'ATH': '0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a',
      'MEW': '0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d',
      'MNDE': '0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a',
      'SPX': '0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a',
      'ORCA': '0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c',
      'SOL': '0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d', // SOL/USD
    };

    // Switchboard feeds as fallback
    const SWITCHBOARD_FEEDS = {
      'TRUMP': '9wcBMATS8bGLQ2UcRuYjsRAD7TPqB1CMhqfueBx78Uj2',
      'WIF': '8GqzQoqqKzJoNaWZtf2udVGV3Fn74W9DQayYu1S1zvkt',
      'ATH': '21JapEAFu8r8SAAQjB2fURfjiosnTHAFFm4S27qe4vVF',
      'BONK': '7GCiue6chgGuk6BvaurQNWD1Ervho8zEdcNWt5CXqR4hL3RGDUGh',
      'FARTCOIN': 'EE8Uyquv38j2JmyCiPprCNUxDBTrzpCXqR4hL3RGDUGh',
      'JTO': 'E9fHVUZnvT4i8H3jQLb6g2tSpcagunJpjwCGNTYxwKSE',
      'JUP': '2F9M59yYc28WMrAymNWceaBEk8ZmDAjUAKULp8seAJF3',
      'MEW': '7Eev1vbsrgEmiRbVjyyFL8nqRKQt7jNPVtxiS4C6ewns',
      'MNDE': 'CwtLbG7w71oCasCMYR8KARZYEVJK5x1GXdoYpqjctp7E',
      'ORCA': 'BFWHemmj4ZtvqQVsWrGrFrL2U8tz7Lzq8nhy1KRMVezL',
      'PENGU': 'DAG9yMr4FbTVd41Jojw6X589EHiPgR375SP5AdAAW7tH',
      'POPCAT': '5FWVcePyDK5jF6ZqFgmEMyu9qu5qdsswwvMd7GvRmfFW',
      'PYTH': '72ukr6M31f9cCzxvZT4Ba7AGyWSFLQGHjXU6WUzN4xD7',
      'RAY': 'AJkAFiXdbMonys8rTXZBrRnuUiLcDFdkyoPuvrVKXhex',
      'RENDER': 'B6xHth4K3fj3KK1TASXtHfbAReShYW3EihgwSKvhsugz',
      'SPX': '8m5YKLgnftRTcVXJLk7bV37xc2qrWR9TkXq4TY3FP3pz',
      'VIRTUAL': '34aJFwk2jTKmB2C6zWnT641ABCQv1P2ghrob57i1gFdg',
      'W': 'DwjV47HwtHW5YR1CPndw3Fq1QMeYyvYA7jYXhMtcUCte',
      'SOL': 'E8TLLh5jkYDvSXfAES7qe3s8Cfjj4hyvjksuvUHe8NEw',
      'USDC': 'aHTvxuDvCRRnmJDDR1JkfLa4SpCNsgC4vDeLMEcN3zY',
    };

    const tokenSymbol = TOKEN_MINT_TO_SYMBOL[tokenMintStr];
    if (!tokenSymbol) {
      throw new Error(`No symbol mapping for token ${tokenMintStr}`);
    }

    console.log(`🔍 Looking up price for ${tokenSymbol} (${tokenMintStr})`);

    // Try Pyth first
    const pythFeedId = PYTH_PRICE_FEEDS[tokenSymbol];
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

    // Fallback to Switchboard
    const switchboardFeed = SWITCHBOARD_FEEDS[tokenSymbol];
    if (switchboardFeed) {
      try {
        const switchboardPrice = await this.getSwitchboardPrice(switchboardFeed, tokenSymbol);
        if (switchboardPrice > 0) {
          return this.calculateTokenValue(tokenBalance, tokenDecimals, switchboardPrice);
        }
      } catch (error) {
        console.warn(`⚠️ Switchboard price failed for ${tokenSymbol}:`, error.message);
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
   * Get price from Switchboard on-chain data
   */
  async getSwitchboardPrice(feedAddress, tokenSymbol) {
    try {
      // Get account data from Switchboard feed
      const feedPubkey = new PublicKey(feedAddress);
      const accountInfo = await this.connection.getAccountInfo(feedPubkey);
      
      if (!accountInfo) {
        throw new Error('Switchboard feed account not found');
      }

      // Parse Switchboard aggregator data (simplified)
      // Note: This is a basic implementation - full Switchboard parsing would need their SDK
      const data = accountInfo.data;
      
      // Switchboard stores price as i128 in little-endian format at offset 114
      // This is a simplified extraction - production should use @switchboard-xyz/solana.js
      if (data.length < 130) {
        throw new Error('Invalid Switchboard account data');
      }

      // Extract price value (simplified - this may need adjustment based on Switchboard format)
      const priceBytes = data.slice(114, 130);
      let price = 0;
      
      // Convert little-endian bytes to number (simplified)
      for (let i = 0; i < 8; i++) {
        price += priceBytes[i] * Math.pow(256, i);
      }
      
      // Switchboard typically uses 9 decimal places for USD prices
      price = price / 1e9;
      
      console.log(`📊 Switchboard price for ${tokenSymbol}: $${price.toFixed(6)}`);
      return price;

    } catch (error) {
      console.error(`❌ Switchboard price fetch failed for ${tokenSymbol}:`, error);
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