import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { 
  PublicKey, 
  Keypair, 
  SystemProgram,
  SYSVAR_RENT_PUBKEY 
} from "@solana/web3.js";
import { 
  TOKEN_PROGRAM_ID,
  ASSOCIATED_TOKEN_PROGRAM_ID,
  getAssociatedTokenAddressSync
} from "@solana/spl-token";
import { CalvinStaking } from "../target/types/calvin_staking";
import { Vault } from "../target/types/vault";

/**
 * Initialize Calvin Staking and Vault programs on Devnet
 */
async function initializePrograms() {
  // Set up provider for devnet
  const connection = new anchor.web3.Connection("https://devnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d", "confirmed");
  
  // Load the authority wallet (you'll need to provide this)
  const authorityKeypair = Keypair.fromSecretKey(
    new Uint8Array(JSON.parse(require('fs').readFileSync('./calvin-ai-authority.json', 'utf8')))
  );
  
  const wallet = new anchor.Wallet(authorityKeypair);
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "confirmed",
  });
  anchor.setProvider(provider);

  // Program IDs from your deployed contracts
  const STAKING_PROGRAM_ID = new PublicKey("FH8te8ebpGLRUc32pZHj4q6DUwzt3KykQYZyA4NQPsod");
  const VAULT_PROGRAM_ID = new PublicKey("Evdjoh1AHQb6Ls1n7Td7buAiDA5ty7Ec8NCYt8eWEXFp");
  
  // Token addresses (Devnet)
  const CALVIN_MINT = new PublicKey("CrWbUJ4kMgduYDVRK8bDXhNBHr8cScixi79nGdGejnb1"); // Devnet CALVIN
  const USDC_MINT = new PublicKey("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"); // Devnet USDC

  // Initialize programs
  const stakingProgram = new Program(
    require("../target/idl/calvin_staking.json"),
    provider
  );

  const vaultProgram = new Program(
    require("../target/idl/vault.json"),
    provider
  );

  console.log("🚀 Initializing Calvin programs on Devnet...");
  console.log("Authority:", authorityKeypair.publicKey.toBase58());

  // Step 1: Initialize Staking Program
  try {
    console.log("\n📍 Step 1: Initializing Staking Program...");
    
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

    // Tier thresholds (matching your constants)
    const TIER_THRESHOLDS = [
      new anchor.BN("10000000000000"), // 10M CALVIN (6 decimals)
      new anchor.BN("2000000000000"),  // 2M CALVIN  
      new anchor.BN("500000000000"),   // 500K CALVIN
      new anchor.BN(0)                 // Default tier
    ];

    const tx1 = await stakingProgram.methods
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
      })
      .signers([authorityKeypair])
      .rpc();

    console.log("✅ Staking program initialized:", tx1);
    console.log("📍 Stake Config PDA:", stakeConfig.toBase58());
    console.log("📍 Vault Pass Mint:", vaultPassMint.toBase58());

  } catch (error: any) {
    if (error.message?.includes("already in use")) {
      console.log("ℹ️ Staking program already initialized");
    } else {
      console.error("❌ Staking initialization failed:", error);
      throw error;
    }
  }

  // Step 2: Initialize Vault Program
  try {
    console.log("\n📍 Step 2: Initializing Vault Program...");
    
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
      true  // allowOwnerOffCurve - PDAs are off-curve by design!
    );

    const [sharesMint] = PublicKey.findProgramAddressSync(
      [Buffer.from("shares_mint")],
      VAULT_PROGRAM_ID
    );

    // Jupiter Program ID (V6 on devnet)
    const JUPITER_PROGRAM_ID = new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
    
    // Treasury wallet for fees
    const TREASURY_WALLET = new PublicKey("HV4x1p4gHhMcyjWpexki7Mis7ajecMntwCcvLjQJdLiC");

    const tx2 = await vaultProgram.methods
      .initialize(
        authorityKeypair.publicKey,  // emergency_owner
        authorityKeypair.publicKey,  // calvin_authority (you can change this later)
        STAKING_PROGRAM_ID,          // staking_program_id
        new anchor.BN(1000 * 1e6),   // per_nft_cap (1000 USDC default)
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

    console.log("✅ Vault program initialized:", tx2);
    console.log("📍 Vault PDA:", vault.toBase58());
    console.log("📍 Shares Mint:", sharesMint.toBase58());

  } catch (error: any) {
    if (error.message?.includes("already in use")) {
      console.log("ℹ️ Vault program already initialized");
    } else {
      console.error("❌ Vault initialization failed:", error);
      throw error;
    }
  }

  // Step 3: Initialize vault token accounts for trading
  try {
    console.log("\n📍 Step 3: Creating vault token accounts for trading...");
    
    const [vault] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault")],
      VAULT_PROGRAM_ID
    );

    const [vaultAuthority] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault_authority")],
      VAULT_PROGRAM_ID
    );

    // Trading tokens to create accounts for (DEVNET ONLY - these tokens exist on devnet)
    const TRADING_TOKENS = [
      { symbol: "USDC", mint: USDC_MINT }, // ✅ USDC exists on devnet
      { symbol: "SOL", mint: new PublicKey("So11111111111111111111111111111111111111112") }, // ✅ SOL exists everywhere
      // Note: JUP and BONK mainnet addresses don't exist on devnet
      // We'll add devnet-specific tokens later or create test tokens
    ];

    for (const token of TRADING_TOKENS) {
      try {
        console.log(`  Creating account for ${token.symbol}...`);
        
        const vaultTokenAccount = getAssociatedTokenAddressSync(
          token.mint,
          vaultAuthority,
          true  // allowOwnerOffCurve - PDAs are off-curve by design!
        );

        const tx3 = await vaultProgram.methods
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
          })
          .signers([authorityKeypair])
          .rpc();

        console.log(`  ✅ ${token.symbol} account created:`, vaultTokenAccount.toBase58());
        
      } catch (error: any) {
        if (error.message?.includes("already in use")) {
          console.log(`  ℹ️ ${token.symbol} account already exists`);
        } else {
          console.error(`  ❌ Failed to create ${token.symbol} account:`, error);
        }
      }
    }

  } catch (error) {
    console.error("❌ Token account creation failed:", error);
  }

  console.log("\n🎉 Initialization complete!");
  console.log("\n📋 Important Addresses:");
  console.log("🔹 Staking Program:", STAKING_PROGRAM_ID.toBase58());
  console.log("🔹 Vault Program:", VAULT_PROGRAM_ID.toBase58());
  console.log("🔹 CALVIN Token:", CALVIN_MINT.toBase58());
  console.log("🔹 USDC Token:", USDC_MINT.toBase58());
}

// Run the initialization
initializePrograms()
  .then(() => {
    console.log("✅ Successfully initialized programs");
    process.exit(0);
  })
  .catch((error) => {
    console.error("❌ Initialization failed:", error);
    process.exit(1);
  }); 