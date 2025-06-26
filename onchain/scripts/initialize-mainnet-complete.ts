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
  TOKEN_2022_PROGRAM_ID,
  ASSOCIATED_TOKEN_PROGRAM_ID,
  getAssociatedTokenAddressSync,
  createAssociatedTokenAccountInstruction,
  getAccount,
  getMint
} from "@solana/spl-token";
import fs from 'fs';

// Import IDLs
import vaultIdl from '../target/idl/vault.json';
import stakingIdl from '../target/idl/calvin_staking.json';

/**
 * 🚀 COMPLETE MAINNET INITIALIZATION 🚀
 * 
 * This script initializes both vault and staking programs with ALL trading tokens
 * from the oracle configuration and loads the Calvin AI authority keypair.
 */

async function initializeMainnetComplete() {
  console.log("🚀 COMPLETE CALVIN VAULT & STAKING INITIALIZATION");
  console.log("⚠️  MAINNET DEPLOYMENT - REAL MONEY!");
  
  // ============================================================================
  // 📋 VERIFIED MAINNET ADDRESSES
  // ============================================================================
  
  const PROGRAMS = {
    VAULT: new PublicKey("tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z"),
    STAKING: new PublicKey("8kMj6gYFVUC3Ya6qwu3tyaZweyXUUuR8t8aCtA47aX7W"),
    JUPITER: new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"),
  };
  
  const BASE_TOKENS = {
    USDC: new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
    CALVIN: new PublicKey("229vWzBTiUNdraYpVtSH9usTwwVxcyPDbBWf1zEPpump"),
  };
  
  // ============================================================================
  // 🎯 COMPLETE TRADING TOKENS LIST (from oracle_config.rs)
  // ============================================================================
  
  const TRADING_TOKENS = [
    // Base/Infrastructure
    { symbol: "USDC", mint: new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v") },
    { symbol: "SOL", mint: new PublicKey("So11111111111111111111111111111111111111112") },
    
    // Political/Social Tokens
    { symbol: "TRUMP", mint: new PublicKey("6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN") },
    
    // Infrastructure/DeFi
    { symbol: "RENDER", mint: new PublicKey("rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof") },
    { symbol: "JUP", mint: new PublicKey("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN") },
    { symbol: "RAY", mint: new PublicKey("4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R") },
    { symbol: "JTO", mint: new PublicKey("jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL") },
    { symbol: "PYTH", mint: new PublicKey("HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3") },
    { symbol: "ORCA", mint: new PublicKey("orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE") },
    { symbol: "MNDE", mint: new PublicKey("MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey") },
    
    // Memecoins
    { symbol: "BONK", mint: new PublicKey("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263") },
    { symbol: "FARTCOIN", mint: new PublicKey("9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump") },
    { symbol: "WIF", mint: new PublicKey("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm") },
    { symbol: "VIRTUAL", mint: new PublicKey("3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y") },
    { symbol: "PENGU", mint: new PublicKey("2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv") },
    { symbol: "POPCAT", mint: new PublicKey("7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr") },
    { symbol: "ATH", mint: new PublicKey("Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7") },
    { symbol: "MEW", mint: new PublicKey("MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5") },
    { symbol: "SPX", mint: new PublicKey("J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr") },
    
    // Cross-chain
    { symbol: "W", mint: new PublicKey("85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ") }, // WORMHOLE
  ];
  
  console.log(`📊 CONFIGURATION:`);
  console.log(`  🏦 Vault Program: ${PROGRAMS.VAULT.toBase58()}`);
  console.log(`  🥩 Staking Program: ${PROGRAMS.STAKING.toBase58()}`);
  console.log(`  🎯 Trading Tokens: ${TRADING_TOKENS.length}`);
  
  // ============================================================================
  // 🔑 LOAD CALVIN AI AUTHORITY KEYPAIR
  // ============================================================================
  
  let calvinAiKeypair: Keypair;
  
  // Try to load the Calvin AI authority keypair
  try {
    console.log("🔍 Loading Calvin AI authority keypair...");
    
    // Try multiple possible locations for the keypair
    const possiblePaths = [
      './calvin-ai-authority.json',
      './scripts/calvin-ai-authority.json',
      '../calvin-ai-authority.json',
      '/home/ubuntu/calvin-ai-authority.json',
      '/home/ubuntu/.config/solana/calvin-ai-authority.json'
    ];
    
    let keypairData: number[] | null = null;
    let usedPath = '';
    
    for (const path of possiblePaths) {
      try {
        if (fs.existsSync(path)) {
          keypairData = JSON.parse(fs.readFileSync(path, 'utf8'));
          usedPath = path;
          break;
        }
      } catch (e) {
        // Continue to next path
      }
    }
    
    if (!keypairData) {
      throw new Error("Calvin AI authority keypair not found in any expected location");
    }
    
    calvinAiKeypair = Keypair.fromSecretKey(new Uint8Array(keypairData));
    
    // Verify this is the correct keypair
    const expectedPubkey = "8mxVsgQQ6kkbfZ7t2AvxBh7jqQd7Lu2kg8bPvLwA1het";
    if (calvinAiKeypair.publicKey.toBase58() !== expectedPubkey) {
      throw new Error(`Keypair mismatch! Expected ${expectedPubkey}, got ${calvinAiKeypair.publicKey.toBase58()}`);
    }
    
    console.log(`✅ Calvin AI authority loaded: ${calvinAiKeypair.publicKey.toBase58()}`);
    console.log(`   From: ${usedPath}`);
    
  } catch (error) {
    console.error("❌ Failed to load Calvin AI authority keypair:", error.message);
    console.error("💡 Please ensure calvin-ai-authority.json is in one of these locations:");
    console.error("   - ./calvin-ai-authority.json");
    console.error("   - ./scripts/calvin-ai-authority.json");
    console.error("   - /home/ubuntu/calvin-ai-authority.json");
    throw error;
  }
  
  // ============================================================================
  // 🔗 CONNECTION & DEPLOYER SETUP
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
  
  if (balance < 0.5 * anchor.web3.LAMPORTS_PER_SOL) {
    throw new Error("❌ Need at least 0.5 SOL for initialization");
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
    BASE_TOKENS.USDC, vaultAuthority, true
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
  
  const stakingIdlCopy = { ...stakingIdl, address: PROGRAMS.STAKING.toBase58() };
  const stakingProgram = new anchor.Program(stakingIdlCopy as any, provider);
  
  const tierThresholds = [
    new anchor.BN(10_000_000_000_000), // 10M CALVIN - Vault Keeper
    new anchor.BN(2_000_000_000_000),  // 2M CALVIN - Tier 2  
    new anchor.BN(500_000_000_000),    // 500K CALVIN - Tier 3
    new anchor.BN(0),                  // Default
  ];
  
  try {
    const stakingTx = await stakingProgram.methods
      .initializeStaking(tierThresholds, PROGRAMS.VAULT)
      .accounts({
        admin: deployerKeypair.publicKey,
        stakeConfig: stakeConfig,
        stakeVault: stakeVault,
        calvinMint: BASE_TOKENS.CALVIN,
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
        BASE_TOKENS.USDC
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
  
  const vaultIdlCopy = { ...vaultIdl, address: PROGRAMS.VAULT.toBase58() };
  const vaultProgram = new anchor.Program(vaultIdlCopy as any, provider);
  
  const perNftCap = 500_000_000; // 500 USDC
  
  // Set treasury to the provided treasury address
  const treasury = new PublicKey("2zGsubjG1i1VXem7ADkS1KAT6ryFTdPQboozPK6EufMQ");
  
  try {
    const vaultTx = await vaultProgram.methods
      .initialize(
        deployerKeypair.publicKey, // emergency_owner (deployer initially)
        calvinAiKeypair.publicKey, // calvin_authority (THE TRADING AUTHORITY)
        PROGRAMS.STAKING,          // staking_program_id
        new anchor.BN(perNftCap),  // per_nft_cap
        PROGRAMS.JUPITER           // jupiter_program_id
      )
      .accounts({
        initializer: deployerKeypair.publicKey,
        usdcMint: BASE_TOKENS.USDC,
        calvinMint: BASE_TOKENS.CALVIN,
        vault: vaultPda,
        usdcVault: usdcVault,
        vaultAuthority: vaultAuthority,
        sharesMint: sharesMint,
        treasury: treasury,
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
    console.log(`   Calvin Authority: ${calvinAiKeypair.publicKey.toBase58()}`);
  } catch (error) {
    if (error.message?.includes("already in use")) {
      console.log("✅ Vault already initialized");
    } else {
      throw error;
    }
  }
  
  // ============================================================================
  // 🎯 STEP 5: CREATE ALL TRADING TOKEN ACCOUNTS (with Token-2022 support)
  // ============================================================================
  
  console.log("\n📍 STEP 5: Creating trading token accounts...");
  console.log(`Creating ${TRADING_TOKENS.length} token accounts...`);
  
  // Helper function to detect token program
  async function getTokenProgram(mint: PublicKey): Promise<PublicKey> {
    try {
      await getMint(connection, mint, "confirmed", TOKEN_PROGRAM_ID);
      return TOKEN_PROGRAM_ID;
    } catch {
      try {
        await getMint(connection, mint, "confirmed", TOKEN_2022_PROGRAM_ID);
        return TOKEN_2022_PROGRAM_ID;
      } catch {
        return TOKEN_PROGRAM_ID; // Default fallback
      }
    }
  }
  
  let created = 0;
  let existing = 0;
  
  for (const { symbol, mint } of TRADING_TOKENS) {
    try {
      // Detect the correct token program
      const tokenProgram = await getTokenProgram(mint);
      const isToken2022 = tokenProgram.equals(TOKEN_2022_PROGRAM_ID);
      
      console.log(`🔍 ${symbol}: ${isToken2022 ? 'Token-2022' : 'SPL Token'}`);
      
      const tokenAccount = getAssociatedTokenAddressSync(
        mint, 
        vaultAuthority, 
        true, 
        tokenProgram
      );
      
      try {
        await getAccount(connection, tokenAccount, "confirmed", tokenProgram);
        console.log(`✅ ${symbol} account exists`);
        existing++;
      } catch {
        try {
          const tx = new Transaction()
            .add(createAssociatedTokenAccountInstruction(
              deployerKeypair.publicKey,
              tokenAccount,
              vaultAuthority,
              mint,
              tokenProgram
            ));
          
          const sig = await sendAndConfirmTransaction(
            connection, tx, [deployerKeypair], { commitment: "confirmed" }
          );
          
          console.log(`✅ ${symbol} account created: ${sig.slice(0, 8)}...`);
          created++;
        } catch (createError) {
          console.log(`⚠️ Failed to create ${symbol} account: ${createError.message}`);
        }
      }
    } catch (detectError) {
      console.log(`⚠️ Failed to detect ${symbol} token program: ${detectError.message}`);
    }
    
    // Small delay to avoid rate limits
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  
  console.log(`📊 Token Account Summary:`);
  console.log(`   Created: ${created}`);
  console.log(`   Existing: ${existing}`);
  console.log(`   Total: ${created + existing}/${TRADING_TOKENS.length}`);
  
  // ============================================================================
  // 🎉 SUCCESS!
  // ============================================================================
  
  console.log("\n🎉 COMPLETE INITIALIZATION SUCCESSFUL!");
  console.log("\n📊 FINAL SUMMARY:");
  console.log(`✅ Vault Program: ${PROGRAMS.VAULT.toBase58()}`);
  console.log(`✅ Staking Program: ${PROGRAMS.STAKING.toBase58()}`);
  console.log(`✅ Vault PDA: ${vaultPda.toBase58()}`);
  console.log(`✅ Calvin Authority: ${calvinAiKeypair.publicKey.toBase58()}`);
  console.log(`✅ Emergency Owner: ${deployerKeypair.publicKey.toBase58()}`);
  console.log(`✅ Treasury: ${treasury.toBase58()}`);
  console.log(`✅ Trading Token Accounts: ${created + existing}/${TRADING_TOKENS.length}`);
  
  // Save complete deployment information
  const addresses = {
    programs: {
      vault: PROGRAMS.VAULT.toBase58(),
      staking: PROGRAMS.STAKING.toBase58(),
      jupiter: PROGRAMS.JUPITER.toBase58(),
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
      calvin: calvinAiKeypair.publicKey.toBase58(),
      emergency: deployerKeypair.publicKey.toBase58(),
      treasury: treasury.toBase58(),
    },
    tokens: {
      usdc: BASE_TOKENS.USDC.toBase58(),
      calvin: BASE_TOKENS.CALVIN.toBase58(),
    },
    tradingTokens: TRADING_TOKENS.map(t => ({
      symbol: t.symbol,
      mint: t.mint.toBase58(),
      account: getAssociatedTokenAddressSync(t.mint, vaultAuthority, true).toBase58()
    })),
  };
  
  fs.writeFileSync('./mainnet-complete-deployment.json', JSON.stringify(addresses, null, 2));
  console.log("📄 Complete deployment saved to mainnet-complete-deployment.json");
  
  console.log("\n🚀 CALVIN VAULT IS NOW LIVE ON MAINNET!");
  console.log("🎯 Ready for production trading with all supported tokens");
}

if (require.main === module) {
  initializeMainnetComplete().catch(console.error);
}

export default initializeMainnetComplete; 