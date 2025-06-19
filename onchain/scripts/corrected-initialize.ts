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
 * CORRECTED initialization script for Calvin vault system
 * Uses the NEW program IDs and correct wallet path
 */
async function correctInitialization() {
  console.log("🧹 Starting CORRECTED vault initialization...");
  
  // Set up provider for devnet
  const connection = new Connection("https://devnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d", "confirmed");
  
  // Load the correct authority wallet (from Anchor.toml)
  const authorityKeypair = Keypair.fromSecretKey(
    new Uint8Array(JSON.parse(fs.readFileSync('./devnet-test.json', 'utf8')))
  );
  
  const wallet = new anchor.Wallet(authorityKeypair);
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "confirmed",
  });
  anchor.setProvider(provider);

  // NEW Program IDs from Anchor.toml devnet section
  const STAKING_PROGRAM_ID = new PublicKey("2rBVK9Q4WYV7Nx7n12KmwGQdBHikc1yBwRrVBqh8zrBf");
  const VAULT_PROGRAM_ID = new PublicKey("3vAVNaMLmjTcLAnWtj7Pj6bJ2KjZ1xBuMXDQhPsEVete");
  
  // Token addresses (Devnet)
  const CALVIN_MINT = new PublicKey("229vWzBTiUNdraYpVtSH9usTwwVxcyPDbBWf1zEPpump"); // Real CALVIN token
  const USDC_MINT = new PublicKey("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"); // Devnet USDC

  // Initialize programs with correct IDL names
  const stakingProgram = new Program(
    require("../target/idl/calvin_staking.json"),
    provider
  ) as Program<CalvinStaking>;

  const vaultProgram = new Program(
    require("../target/idl/calvin_vault.json"), 
    provider
  ) as Program<Vault>;

  console.log("🔧 CORRECTED System Configuration:");
  console.log(`  Authority: ${authorityKeypair.publicKey.toBase58()}`);
  console.log(`  NEW Staking Program: ${STAKING_PROGRAM_ID.toBase58()}`);
  console.log(`  NEW Vault Program: ${VAULT_PROGRAM_ID.toBase58()}`);
  console.log(`  CALVIN Token: ${CALVIN_MINT.toBase58()}`);
  console.log(`  USDC Token: ${USDC_MINT.toBase58()}`);

  // Step 1: Initialize staking program
  console.log("\n📍 Step 1: Initializing NEW Staking Program...");
  
  try {
    const [stakeConfig] = PublicKey.findProgramAddressSync(
      [Buffer.from("stake_config")],
      STAKING_PROGRAM_ID
    );

    const [stakeVault] = PublicKey.findProgramAddressSync(
      [Buffer.from("stake_vault")],
      STAKING_PROGRAM_ID
    );

    const [vaultPassMint] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault_pass_mint")],
      STAKING_PROGRAM_ID
    );

    console.log(`  Stake Config: ${stakeConfig.toBase58()}`);
    console.log(`  Stake Vault: ${stakeVault.toBase58()}`);
    console.log(`  Vault Pass Mint: ${vaultPassMint.toBase58()}`);

    // Check if already initialized
    try {
      const stakeConfigAccount = await stakingProgram.account.stakeConfig.fetch(stakeConfig);
      console.log("✅ Staking program already initialized");
      console.log(`  Tier thresholds: ${stakeConfigAccount.tierThresholds.length}`);
    } catch (error) {
      console.log("🔄 Initializing NEW staking program...");
      
      // Tier thresholds (with 6 decimals for CALVIN)
      const TIER_THRESHOLDS = [
        new anchor.BN("10000000000000"), // 10M CALVIN
        new anchor.BN("2000000000000"),  // 2M CALVIN  
        new anchor.BN("500000000000"),   // 500K CALVIN
        new anchor.BN(0)                 // Default tier
      ];

      const tx = await stakingProgram.methods
        .initializeStaking(
          TIER_THRESHOLDS,
          VAULT_PROGRAM_ID
        )
        .accounts({
          admin: authorityKeypair.publicKey,
          stake_config: stakeConfig,
          stake_vault: stakeVault,
          calvin_mint: CALVIN_MINT,
          vault_pass_mint: vaultPassMint,
          system_program: SystemProgram.programId,
          token_program: TOKEN_PROGRAM_ID,
          associated_token_program: ASSOCIATED_TOKEN_PROGRAM_ID,
          rent: SYSVAR_RENT_PUBKEY,
        })
        .signers([authorityKeypair])
        .rpc();

      console.log("✅ NEW Staking program initialized successfully:", tx);
    }
  } catch (error) {
    console.error("❌ Staking program initialization failed:", error);
    throw error;
  }

  // Step 2: Initialize vault program
  console.log("\n📍 Step 2: Initializing NEW Vault Program...");
  
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
      true
    );

    const [sharesMint] = PublicKey.findProgramAddressSync(
      [Buffer.from("shares_mint")],
      VAULT_PROGRAM_ID
    );

    console.log(`  Vault: ${vault.toBase58()}`);
    console.log(`  Vault Authority: ${vaultAuthority.toBase58()}`);
    console.log(`  USDC Vault: ${usdcVault.toBase58()}`);
    console.log(`  Shares Mint: ${sharesMint.toBase58()}`);

    // Check if already initialized
    try {
      const vaultAccount = await vaultProgram.account.vault.fetch(vault);
      console.log("✅ Vault program already initialized");
      console.log(`  Calvin Authority: ${vaultAccount.calvinAuthority.toBase58()}`);
      console.log(`  Emergency Owners: ${vaultAccount.emergencyOwnersCount}`);
    } catch (error) {
      console.log("🔄 Initializing NEW vault program...");
      
      // Jupiter Program ID (V6 on devnet)
      const JUPITER_PROGRAM_ID = new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
      
      // Treasury wallet for fees
      const TREASURY_WALLET = authorityKeypair.publicKey; // Use deployer as treasury for testing

      const tx = await vaultProgram.methods
        .initialize(
          authorityKeypair.publicKey,  // emergency_owner
          authorityKeypair.publicKey,  // calvin_authority
          STAKING_PROGRAM_ID,          // staking_program_id
          new anchor.BN(10000 * 1e6),  // per_nft_cap (10K USDC)
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
        })
        .signers([authorityKeypair])
        .rpc();

      console.log("✅ NEW Vault program initialized successfully:", tx);
      
      // Verify initialization
      const vaultAccount = await vaultProgram.account.vault.fetch(vault);
      console.log("📋 Vault Verification:");
      console.log(`  Calvin Authority: ${vaultAccount.calvinAuthority.toBase58()}`);
      console.log(`  Emergency Owners: ${vaultAccount.emergencyOwnersCount}`);
      console.log(`  Per NFT Cap: ${vaultAccount.perNftCap.toString()}`);
    }
  } catch (error) {
    console.error("❌ Vault program initialization failed:", error);
    throw error;
  }

  console.log("\n🎉 CORRECTED initialization complete!");
  console.log("\n📋 System Status:");
  console.log(`🔹 NEW Staking Program (${STAKING_PROGRAM_ID.toBase58()}): ✅ Ready`);
  console.log(`🔹 NEW Vault Program (${VAULT_PROGRAM_ID.toBase58()}): ✅ Ready`);
  console.log("\n🧪 Ready for testing!");
}

// Run the corrected initialization
correctInitialization()
  .then(() => {
    console.log("✅ CORRECTED initialization completed successfully");
    process.exit(0);
  })
  .catch((error) => {
    console.error("❌ CORRECTED initialization failed:", error);
    process.exit(1);
  }); 