import * as anchor from "@coral-xyz/anchor";
import { 
  PublicKey, 
  Keypair, 
  SystemProgram,
  SYSVAR_RENT_PUBKEY,
  Connection,
  Transaction,
  sendAndConfirmTransaction,
  ComputeBudgetProgram
} from "@solana/web3.js";
import { 
  TOKEN_PROGRAM_ID,
  ASSOCIATED_TOKEN_PROGRAM_ID,
  getAssociatedTokenAddressSync,
  createAssociatedTokenAccountInstruction,
  getAccount
} from "@solana/spl-token";
import fs from 'fs';

// Import IDLs
import vaultIdl from '../target/idl/vault.json';
import stakingIdl from '../target/idl/calvin_staking.json';

/**
 * 🚀 FINAL MAINNET INITIALIZATION SCRIPT 🚀
 * 
 * CRITICAL CHECKLIST BEFORE RUNNING:
 * ✅ Programs verified on mainnet
 * ✅ Wallet has sufficient SOL (>5 SOL recommended)
 * ✅ Authority addresses configured correctly
 * ✅ This script tested on devnet/localnet first
 */

async function initializeMainnet() {
  console.log("🚀 INITIALIZING CALVIN VAULT & STAKING ON MAINNET");
  console.log("⚠️  REAL MONEY - PROCEED WITH EXTREME CAUTION!");
  
  // ============================================================================
  // 📋 VERIFIED MAINNET CONFIGURATION
  // ============================================================================
  
  const PROGRAMS = {
    VAULT: new PublicKey("tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z"),
    STAKING: new PublicKey("8kMj6gYFVUC3Ya6qwu3tyaZweyXUUuR8t8aCtA47aX7W"),
    JUPITER: new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"),
  };
  
  const TOKENS = {
    USDC: new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
    CALVIN: new PublicKey("229vWzBTiUNdraYpVtSH9usTwwVxcyPDbBWf1zEPpump"),
  };
  
  // 🚨 CRITICAL: REPLACE THESE ADDRESSES BEFORE RUNNING
  const AUTHORITIES = {
    // The wallet that will execute trades (your Calvin AI backend)
    CALVIN_AI: new PublicKey("REPLACE_WITH_CALVIN_AI_WALLET_ADDRESS"),
    // Where fees are collected
    TREASURY: new PublicKey("REPLACE_WITH_TREASURY_WALLET_ADDRESS"),
  };
  
  // Validate critical addresses are set
  if (AUTHORITIES.CALVIN_AI.toBase58() === "REPLACE_WITH_CALVIN_AI_WALLET_ADDRESS") {
    throw new Error("❌ CALVIN_AI authority not set! Edit the script first.");
  }
  
  if (AUTHORITIES.TREASURY.toBase58() === "REPLACE_WITH_TREASURY_WALLET_ADDRESS") {
    throw new Error("❌ TREASURY address not set! Edit the script first.");
  }
  
  console.log("📋 CONFIGURATION:");
  console.log(`  🏦 Vault Program: ${PROGRAMS.VAULT.toBase58()}`);
  console.log(`  🥩 Staking Program: ${PROGRAMS.STAKING.toBase58()}`);
  console.log(`  🤖 Calvin AI: ${AUTHORITIES.CALVIN_AI.toBase58()}`);
  console.log(`  💰 Treasury: ${AUTHORITIES.TREASURY.toBase58()}`);
  
  // ============================================================================
  // 🔗 CONNECTION & WALLET SETUP
  // ============================================================================
  
  const connection = new Connection(
    "https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d",
    "confirmed"
  );
  
  const deployerKeypair = Keypair.fromSecretKey(
    new Uint8Array(JSON.parse(fs.readFileSync('/home/ubuntu/.config/solana/id.json', 'utf8')))
  );
  
  console.log(`🔑 Deployer: ${deployerKeypair.publicKey.toBase58()}`);
  
  const balance = await connection.getBalance(deployerKeypair.publicKey);
  console.log(`💰 Balance: ${balance / anchor.web3.LAMPORTS_PER_SOL} SOL`);
  
  if (balance < 5 * anchor.web3.LAMPORTS_PER_SOL) {
    throw new Error("❌ Need at least 5 SOL for initialization");
  }
  
  const provider = new anchor.AnchorProvider(
    connection,
    new anchor.Wallet(deployerKeypair),
    { commitment: "confirmed" }
  );
  anchor.setProvider(provider);
  
  // ============================================================================
  // 🧮 PDA DERIVATIONS
  // ============================================================================
  
  const [vaultPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault")], PROGRAMS.VAULT
  );
  
  const [vaultAuthority] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault_authority")], PROGRAMS.VAULT
  );
  
  const [sharesMint] = PublicKey.findProgramAddressSync(
    [Buffer.from("shares_mint")], PROGRAMS.VAULT
  );
  
  const [stakeConfig] = PublicKey.findProgramAddressSync(
    [Buffer.from("stake_config")], PROGRAMS.STAKING
  );
  
  const [stakeVault] = PublicKey.findProgramAddressSync(
    [Buffer.from("stake_vault")], PROGRAMS.STAKING
  );
  
  const [vaultPassMint] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault_pass_mint")], PROGRAMS.STAKING
  );
  
  const usdcVault = getAssociatedTokenAddressSync(
    TOKENS.USDC, vaultAuthority, true
  );
  
  console.log("\n🧮 DERIVED ADDRESSES:");
  console.log(`  Vault: ${vaultPda.toBase58()}`);
  console.log(`  Vault Authority: ${vaultAuthority.toBase58()}`);
  console.log(`  Shares Mint: ${sharesMint.toBase58()}`);
  console.log(`  USDC Vault: ${usdcVault.toBase58()}`);
  console.log(`  Stake Config: ${stakeConfig.toBase58()}`);
  console.log(`  Vault Pass Mint: ${vaultPassMint.toBase58()}`);
  
  // ============================================================================
  // 🔍 STEP 1: VERIFY PROGRAMS
  // ============================================================================
  
  console.log("\n📍 STEP 1: Verifying programs...");
  
  const [vaultInfo, stakingInfo] = await Promise.all([
    connection.getAccountInfo(PROGRAMS.VAULT),
    connection.getAccountInfo(PROGRAMS.STAKING)
  ]);
  
  if (!vaultInfo || !stakingInfo) {
    throw new Error("❌ Programs not found on mainnet");
  }
  
  console.log("✅ Programs verified");
  
  // ============================================================================
  // 🥩 STEP 2: INITIALIZE STAKING
  // ============================================================================
  
  console.log("\n📍 STEP 2: Initializing staking...");
  
  const stakingProgram = new anchor.Program(stakingIdl as any, PROGRAMS.STAKING, provider);
  
  const tierThresholds = [
    10_000_000_000_000, // 10M CALVIN - Vault Keeper
    2_000_000_000_000,  // 2M CALVIN - Tier 2  
    500_000_000_000,    // 500K CALVIN - Tier 3
    0,                  // Default
  ];
  
  try {
    const stakingTx = await stakingProgram.methods
      .initializeStaking(tierThresholds, PROGRAMS.VAULT)
      .accounts({
        admin: deployerKeypair.publicKey,
        stakeConfig: stakeConfig,
        stakeVault: stakeVault,
        calvinMint: TOKENS.CALVIN,
        vaultPassMint: vaultPassMint,
        systemProgram: SystemProgram.programId,
        tokenProgram: TOKEN_PROGRAM_ID,
        associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .preInstructions([
        ComputeBudgetProgram.setComputeUnitLimit({ units: 400_000 })
      ])
      .rpc({ commitment: "confirmed" });
    
    console.log(`✅ Staking initialized: ${stakingTx}`);
  } catch (error) {
    if (error.message?.includes("already in use")) {
      console.log("✅ Staking already initialized");
    } else {
      throw error;
    }
  }
  
  // ============================================================================
  // 🏦 STEP 3: CREATE USDC VAULT ACCOUNT
  // ============================================================================
  
  console.log("\n📍 STEP 3: Creating USDC vault...");
  
  try {
    await getAccount(connection, usdcVault);
    console.log("✅ USDC vault already exists");
  } catch {
    const createUsdcTx = new Transaction()
      .add(createAssociatedTokenAccountInstruction(
        deployerKeypair.publicKey,
        usdcVault,
        vaultAuthority,
        TOKENS.USDC
      ));
    
    const sig = await sendAndConfirmTransaction(
      connection, createUsdcTx, [deployerKeypair], { commitment: "confirmed" }
    );
    
    console.log(`✅ USDC vault created: ${sig}`);
  }
  
  // ============================================================================
  // 🏛️ STEP 4: INITIALIZE VAULT
  // ============================================================================
  
  console.log("\n📍 STEP 4: Initializing vault...");
  
  const vaultProgram = new anchor.Program(vaultIdl as any, PROGRAMS.VAULT, provider);
  
  const perNftCap = 500_000_000; // 500 USDC
  
  try {
    const vaultTx = await vaultProgram.methods
      .initialize(
        deployerKeypair.publicKey, // emergency_owner
        AUTHORITIES.CALVIN_AI,     // calvin_authority
        PROGRAMS.STAKING,          // staking_program_id
        new anchor.BN(perNftCap),  // per_nft_cap
        PROGRAMS.JUPITER           // jupiter_program_id
      )
      .accounts({
        initializer: deployerKeypair.publicKey,
        usdcMint: TOKENS.USDC,
        calvinMint: TOKENS.CALVIN,
        vault: vaultPda,
        usdcVault: usdcVault,
        vaultAuthority: vaultAuthority,
        sharesMint: sharesMint,
        treasury: AUTHORITIES.TREASURY,
        systemProgram: SystemProgram.programId,
        tokenProgram: TOKEN_PROGRAM_ID,
        associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .preInstructions([
        ComputeBudgetProgram.setComputeUnitLimit({ units: 400_000 })
      ])
      .rpc({ commitment: "confirmed" });
    
    console.log(`✅ Vault initialized: ${vaultTx}`);
  } catch (error) {
    if (error.message?.includes("already in use")) {
      console.log("✅ Vault already initialized");
    } else {
      throw error;
    }
  }
  
  // ============================================================================
  // 🎯 STEP 5: CREATE TRADING TOKEN ACCOUNTS
  // ============================================================================
  
  console.log("\n📍 STEP 5: Creating trading token accounts...");
  
  const tradingTokens = [
    { symbol: "BONK", mint: new PublicKey("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263") },
    { symbol: "WIF", mint: new PublicKey("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm") },
    { symbol: "JUP", mint: new PublicKey("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN") },
    { symbol: "RAY", mint: new PublicKey("4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R") },
    { symbol: "RENDER", mint: new PublicKey("rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof") },
    { symbol: "SOL", mint: new PublicKey("So11111111111111111111111111111111111111112") },
  ];
  
  for (const { symbol, mint } of tradingTokens) {
    const tokenAccount = getAssociatedTokenAddressSync(mint, vaultAuthority, true);
    
    try {
      await getAccount(connection, tokenAccount);
      console.log(`✅ ${symbol} account exists`);
    } catch {
      const tx = new Transaction()
        .add(createAssociatedTokenAccountInstruction(
          deployerKeypair.publicKey, tokenAccount, vaultAuthority, mint
        ));
      
      const sig = await sendAndConfirmTransaction(
        connection, tx, [deployerKeypair], { commitment: "confirmed" }
      );
      
      console.log(`✅ ${symbol} account created: ${sig.slice(0, 8)}...`);
    }
  }
  
  // ============================================================================
  // 🎉 SUCCESS!
  // ============================================================================
  
  console.log("\n🎉 INITIALIZATION COMPLETE!");
  console.log("\n📊 SUMMARY:");
  console.log(`✅ Vault Program: ${PROGRAMS.VAULT.toBase58()}`);
  console.log(`✅ Staking Program: ${PROGRAMS.STAKING.toBase58()}`);
  console.log(`✅ Vault PDA: ${vaultPda.toBase58()}`);
  console.log(`✅ Calvin Authority: ${AUTHORITIES.CALVIN_AI.toBase58()}`);
  console.log(`✅ Treasury: ${AUTHORITIES.TREASURY.toBase58()}`);
  
  // Save addresses
  const addresses = {
    programs: {
      vault: PROGRAMS.VAULT.toBase58(),
      staking: PROGRAMS.STAKING.toBase58(),
    },
    accounts: {
      vault: vaultPda.toBase58(),
      vaultAuthority: vaultAuthority.toBase58(),
      sharesMint: sharesMint.toBase58(),
      usdcVault: usdcVault.toBase58(),
      stakeConfig: stakeConfig.toBase58(),
      vaultPassMint: vaultPassMint.toBase58(),
    },
    authorities: {
      calvin: AUTHORITIES.CALVIN_AI.toBase58(),
      treasury: AUTHORITIES.TREASURY.toBase58(),
      emergency: deployerKeypair.publicKey.toBase58(),
    },
  };
  
  fs.writeFileSync('./mainnet-deployment.json', JSON.stringify(addresses, null, 2));
  console.log("📄 Deployment saved to mainnet-deployment.json");
  
  console.log("\n🚀 READY FOR PRODUCTION!");
}

if (require.main === module) {
  initializeMainnet().catch(console.error);
}

export default initializeMainnet; 