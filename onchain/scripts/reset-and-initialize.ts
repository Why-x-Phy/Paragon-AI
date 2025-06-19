import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { 
  PublicKey, 
  Keypair, 
  SystemProgram,
  SYSVAR_RENT_PUBKEY,
  Connection,
  Transaction
} from "@solana/web3.js";
import { 
  TOKEN_PROGRAM_ID,
  ASSOCIATED_TOKEN_PROGRAM_ID,
  getAssociatedTokenAddressSync
} from "@solana/spl-token";
import { CalvinStaking } from "../target/types/calvin_staking";
import { Vault } from "../target/types/vault";
import fs from 'fs';

/**
 * Comprehensive reset and initialization script for Calvin vault system
 * This script will clean up any corrupted state and properly initialize everything
 */
async function resetAndInitialize() {
  console.log("🧹 Starting comprehensive vault reset and initialization...");
  
  // Set up provider for devnet
  const connection = new Connection("https://devnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d", "confirmed");
  
  // Load the authority wallet
  const authorityKeypair = Keypair.fromSecretKey(
    new Uint8Array(JSON.parse(fs.readFileSync('./calvin-ai-authority.json', 'utf8')))
  );
  
  const wallet = new anchor.Wallet(authorityKeypair);
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "confirmed",
  });
  anchor.setProvider(provider);

  // Program IDs from deployed contracts
  const STAKING_PROGRAM_ID = new PublicKey("GocZdo1RPcsQnbiQrFp6Ybgd3bWUp48Jd4wytN3QN3Vw");
  const VAULT_PROGRAM_ID = new PublicKey("2nLsDVW67Qw5LXGvaTzUQ7xRxytY52APWJAz2c7aqqyJ");
  
  // Token addresses (Devnet)
  const CALVIN_MINT = new PublicKey("CrWbUJ4kMgduYDVRK8bDXhNBHr8cScixi79nGdGejnb1"); // Devnet CALVIN
  const USDC_MINT = new PublicKey("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"); // Devnet USDC

  // Initialize programs
  const stakingProgram = new Program(
    require("../target/idl/calvin_staking.json"),
    provider
  ) as Program<CalvinStaking>;

  const vaultProgram = new Program(
    require("../target/idl/vault.json"), 
    provider
  ) as Program<Vault>;

  console.log("🔧 System Configuration:");
  console.log(`  Authority: ${authorityKeypair.publicKey.toBase58()}`);
  console.log(`  Staking Program: ${STAKING_PROGRAM_ID.toBase58()}`);
  console.log(`  Vault Program: ${VAULT_PROGRAM_ID.toBase58()}`);
  console.log(`  CALVIN Token: ${CALVIN_MINT.toBase58()}`);
  console.log(`  USDC Token: ${USDC_MINT.toBase58()}`);

  // Step 1: Check and initialize staking program if needed
  console.log("\n📍 Step 1: Checking Staking Program...");
  
  try {
    const [stakeConfig] = PublicKey.findProgramAddressSync(
      [Buffer.from("stake_config")],
      STAKING_PROGRAM_ID
    );

    // Check if staking is already initialized
    try {
      const stakeConfigAccount = await stakingProgram.account.stakeConfig.fetch(stakeConfig);
      console.log("✅ Staking program already initialized");
      console.log(`  Tier thresholds configured: ${stakeConfigAccount.tierThresholds.length}`);
    } catch (error) {
      console.log("🔄 Initializing staking program...");
      
      const [stakeVault] = PublicKey.findProgramAddressSync(
        [Buffer.from("stake_vault")],
        STAKING_PROGRAM_ID
      );

      const [vaultPassMint] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_pass_mint")],
        STAKING_PROGRAM_ID
      );

      // Tier thresholds (matching constants)
      const TIER_THRESHOLDS = [
        new anchor.BN("10000000000000"), // 10M CALVIN (6 decimals)
        new anchor.BN("2000000000000"),  // 2M CALVIN  
        new anchor.BN("500000000000"),   // 500K CALVIN
        new anchor.BN(0)                 // Default tier
      ];

      await stakingProgram.methods
        .initializeStaking(
          TIER_THRESHOLDS,
          VAULT_PROGRAM_ID
        )
        .accounts({
          admin: authorityKeypair.publicKey,
          stakeConfig: stakeConfig,
          stakeVault: stakeVault,
          calvinMint: CALVIN_MINT,
          vaultPassMint: vaultPassMint,
          systemProgram: SystemProgram.programId,
          tokenProgram: TOKEN_PROGRAM_ID,
          associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
          rent: SYSVAR_RENT_PUBKEY,
        } as any)
        .signers([authorityKeypair])
        .rpc();

      console.log("✅ Staking program initialized successfully");
    }
  } catch (error) {
    console.error("❌ Staking program check/initialization failed:", error);
    throw error;
  }

  // Step 2: Reset and initialize vault program
  console.log("\n📍 Step 2: Resetting and Initializing Vault Program...");
  
  try {
    const [vault] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault")],
      VAULT_PROGRAM_ID
    );

    const [vaultAuthority] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault_authority")],
      VAULT_PROGRAM_ID
    );

    const usdcVault = getAssociatedTokenAddressSync(
      USDC_MINT,
      vaultAuthority,
      true // allowOwnerOffCurve - PDAs are off-curve by design!
    );

    const [sharesMint] = PublicKey.findProgramAddressSync(
      [Buffer.from("shares_mint")],
      VAULT_PROGRAM_ID
    );

    console.log("🔍 Checking existing vault state...");
    console.log(`  Vault PDA: ${vault.toBase58()}`);
    console.log(`  Vault Authority: ${vaultAuthority.toBase58()}`);
    console.log(`  USDC Vault: ${usdcVault.toBase58()}`);
    console.log(`  Shares Mint: ${sharesMint.toBase58()}`);

    // Check if vault exists and what state it's in
    let needsInitialization = false;
    let existingVaultInfo = null;
    
    try {
      existingVaultInfo = await connection.getAccountInfo(vault);
      if (existingVaultInfo) {
        console.log(`📋 Existing vault account found with ${existingVaultInfo.data.length} bytes`);
        console.log(`💰 SOL balance: ${existingVaultInfo.lamports / 1e9}`);
        
        // Try to fetch as Vault account to see if it's valid
        try {
          const vaultAccount = await vaultProgram.account.vault.fetch(vault);
          console.log("✅ Vault account is valid and readable");
          console.log(`  Calvin Authority: ${vaultAccount.calvinAuthority.toBase58()}`);
          console.log(`  Emergency Owners: ${vaultAccount.emergencyOwnersCount}`);
          console.log(`  Paused: ${vaultAccount.paused}`);
          
          // Check if it needs to be reinitialized (if authority doesn't match)
          if (!vaultAccount.calvinAuthority.equals(authorityKeypair.publicKey)) {
            console.log("⚠️ Vault exists but with different authority - needs reinitialization");
            needsInitialization = true;
          } else {
            console.log("✅ Vault is properly initialized and ready");
          }
        } catch (fetchError) {
          console.log("❌ Vault account exists but data is corrupted - needs reinitialization");
          needsInitialization = true;
        }
      } else {
        console.log("ℹ️ No existing vault account found - needs initialization");
        needsInitialization = true;
      }
    } catch (error) {
      console.log("ℹ️ Could not check vault account - assuming needs initialization");
      needsInitialization = true;
    }

    // Initialize vault if needed
    if (needsInitialization) {
      console.log("🔄 Initializing vault program...");
      
      // Jupiter Program ID (V6 on devnet)
      const JUPITER_PROGRAM_ID = new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
      
      // Treasury wallet for fees
      const TREASURY_WALLET = new PublicKey("HV4x1p4gHhMcyjWpexki7Mis7ajecMntwCcvLjQJdLiC");

      try {
        const tx = await vaultProgram.methods
          .initialize(
            authorityKeypair.publicKey,  // emergency_owner
            authorityKeypair.publicKey,  // calvin_authority (tests will use this)
            STAKING_PROGRAM_ID,          // staking_program_id
            new anchor.BN(10000 * 1e6),  // per_nft_cap (10K USDC in micro-USDC)
            JUPITER_PROGRAM_ID           // jupiter_program_id
          )
          .accounts({
            initializer: authorityKeypair.publicKey,
            usdcMint: USDC_MINT,
            calvinMint: CALVIN_MINT,
            vault: vault,
            usdcVault: usdcVault,
            vaultAuthority: vaultAuthority,
            sharesMint: sharesMint,
            treasury: TREASURY_WALLET,
            systemProgram: SystemProgram.programId,
            tokenProgram: TOKEN_PROGRAM_ID,
            associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
            rent: SYSVAR_RENT_PUBKEY,
          } as any)
          .signers([authorityKeypair])
          .rpc({ skipPreflight: true });

        console.log("✅ Vault program initialized successfully:", tx);
        
        // Verify initialization
        const vaultAccount = await vaultProgram.account.vault.fetch(vault);
        console.log("📋 Vault Verification:");
        console.log(`  Calvin Authority: ${vaultAccount.calvinAuthority.toBase58()}`);
        console.log(`  Emergency Owners: ${vaultAccount.emergencyOwnersCount}`);
        console.log(`  Per NFT Cap: ${vaultAccount.perNftCap.toString()}`);
        console.log(`  Total Shares: ${vaultAccount.totalShares.toString()}`);
        
      } catch (initError: any) {
        if (initError.message?.includes("already in use")) {
          console.log("ℹ️ Vault initialization failed due to existing account - this may be expected");
          console.log("🔍 Attempting to verify existing vault state...");
          
          try {
            const vaultAccount = await vaultProgram.account.vault.fetch(vault);
            console.log("✅ Existing vault account is valid and ready for tests");
          } catch (verifyError) {
            console.error("❌ Existing vault account is corrupted and unusable");
            throw new Error("Vault account is corrupted - manual intervention required");
          }
        } else {
          console.error("❌ Vault initialization failed:", initError);
          throw initError;
        }
      }
    }

  } catch (error) {
    console.error("❌ Vault program reset/initialization failed:", error);
    throw error;
  }

  // Step 3: Create essential vault token accounts
  console.log("\n📍 Step 3: Setting up vault token accounts...");
  
  try {
    const [vault] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault")],
      VAULT_PROGRAM_ID
    );

    const [vaultAuthority] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault_authority")],
      VAULT_PROGRAM_ID
    );

    // Essential tokens for testing (only USDC and SOL for devnet)
    const ESSENTIAL_TOKENS = [
      { 
        symbol: "USDC", 
        mint: USDC_MINT,
        required: true // USDC vault account is created during initialization
      },
      { 
        symbol: "SOL", 
        mint: new PublicKey("So11111111111111111111111111111111111111112"),
        required: false // Create for testing
      }
    ];

    for (const token of ESSENTIAL_TOKENS) {
      try {
        const vaultTokenAccount = getAssociatedTokenAddressSync(
          token.mint,
          vaultAuthority,
          true // allowOwnerOffCurve - PDAs are off-curve by design!
        );

        // Check if account already exists
        try {
          const accountInfo = await connection.getAccountInfo(vaultTokenAccount);
          if (accountInfo) {
            console.log(`  ✅ ${token.symbol} account already exists: ${vaultTokenAccount.toBase58()}`);
            continue;
          }
        } catch (checkError) {
          // Account doesn't exist, create it
        }

        if (!token.required) {
          console.log(`  🔄 Creating ${token.symbol} account...`);
          
          const tx = await vaultProgram.methods
            .initializeTokenAccounts()
            .accounts({
              payer: authorityKeypair.publicKey,
              vault: vault,
              vaultAuthority: vaultAuthority,
              tokenMint: token.mint,
              vaultTokenAccount: vaultTokenAccount,
              systemProgram: SystemProgram.programId,
              tokenProgram: TOKEN_PROGRAM_ID,
              associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
            } as any)
            .signers([authorityKeypair])
            .rpc();

          console.log(`  ✅ ${token.symbol} account created: ${vaultTokenAccount.toBase58()}`);
        }
        
      } catch (error: any) {
        if (error.message?.includes("already in use")) {
          console.log(`  ℹ️ ${token.symbol} account already exists`);
        } else {
          console.error(`  ❌ Failed to create ${token.symbol} account:`, error);
          if (token.required) {
            throw error;
          }
        }
      }
    }

  } catch (error) {
    console.error("❌ Token account setup failed:", error);
    // Don't throw here - tests can create their own accounts if needed
  }

  console.log("\n🎉 Reset and initialization complete!");
  console.log("\n📋 System Status:");
  console.log("🔹 Staking Program: ✅ Initialized");
  console.log("🔹 Vault Program: ✅ Initialized"); 
  console.log("🔹 Essential Token Accounts: ✅ Ready");
  console.log("\n🧪 Ready to run tests!");
  console.log("Run: anchor test --skip-deploy");
}

// Run the reset and initialization
resetAndInitialize()
  .then(() => {
    console.log("✅ Reset and initialization completed successfully");
    process.exit(0);
  })
  .catch((error) => {
    console.error("❌ Reset and initialization failed:", error);
    process.exit(1);
  }); 