import {
  Connection,
  Keypair,
  PublicKey,
  AddressLookupTableProgram,
  TransactionMessage,
  VersionedTransaction,
  ComputeBudgetProgram,
  SystemProgram,
  SYSVAR_RENT_PUBKEY,
} from "@solana/web3.js";
import { getAssociatedTokenAddress, TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID } from "@solana/spl-token";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";

// Configuration
const MAINNET_RPC = "https://api.mainnet-beta.solana.com";
const VAULT_PROGRAM_ID = new PublicKey("tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z");
const STAKING_PROGRAM_ID = new PublicKey("8kMj6gYFVUC3Ya6qwu3tyaZweyXUUuR8t8aCtA47aX7W"); 
const USDC_MINT = new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");
const CALVIN_MINT = new PublicKey("229vWzBTiUNdraYpVtSH9usTwwVxcyPDbBWf1zEPpump");

// PDAs and constants - matching the smart contract constants.rs
const VAULT_PDA_SEED = Buffer.from("vault");
const VAULT_AUTHORITY_PDA_SEED = Buffer.from("vault_authority");
const SHARES_MINT_PDA_SEED = Buffer.from("shares_mint");
const STAKE_CONFIG_SEED = Buffer.from("stake_config");

// Load keypair from Solana CLI config
function loadSolanaConfigKeypair(): Keypair {
  try {
    // Get Solana config path
    const configPath = path.join(os.homedir(), ".config", "solana", "cli", "config.yml");
    const configContent = fs.readFileSync(configPath, "utf8");
    
    // Extract keypair path from config
    const keypairPathMatch = configContent.match(/keypair_path:\s*(.+)/);
    if (!keypairPathMatch) {
      throw new Error("Keypair path not found in Solana config");
    }
    
    let keypairPath = keypairPathMatch[1].trim();
    // Expand ~ to home directory
    if (keypairPath.startsWith("~")) {
      keypairPath = path.join(os.homedir(), keypairPath.slice(1));
    }
    
    console.log("Loading keypair from:", keypairPath);
    const keypairData = JSON.parse(fs.readFileSync(keypairPath, "utf8"));
    return Keypair.fromSecretKey(new Uint8Array(keypairData));
  } catch (error) {
    console.error("Failed to load Solana config keypair:", error);
    throw new Error("Please ensure you have a valid Solana CLI config with a keypair set");
  }
}

async function getDepositStaticAccounts(): Promise<PublicKey[]> {
  console.log("📊 Calculating static accounts for deposit instruction...");
  
  const staticAccounts: PublicKey[] = [];
  
  // 1. Vault PDA - derived with just VAULT_PDA_SEED, no mint
  const [vaultPda] = PublicKey.findProgramAddressSync(
    [VAULT_PDA_SEED],
    VAULT_PROGRAM_ID
  );
  staticAccounts.push(vaultPda);
  console.log("  1. Vault PDA:", vaultPda.toString());
  
  // 2. Vault Authority PDA - derived with just VAULT_AUTHORITY_PDA_SEED
  const [vaultAuthorityPda] = PublicKey.findProgramAddressSync(
    [VAULT_AUTHORITY_PDA_SEED],
    VAULT_PROGRAM_ID
  );
  staticAccounts.push(vaultAuthorityPda);
  console.log("  2. Vault Authority PDA:", vaultAuthorityPda.toString());
  
  // 3. Shares Mint PDA - derived with just SHARES_MINT_PDA_SEED
  const [sharesMintPda] = PublicKey.findProgramAddressSync(
    [SHARES_MINT_PDA_SEED],
    VAULT_PROGRAM_ID
  );
  staticAccounts.push(sharesMintPda);
  console.log("  3. Shares Mint PDA:", sharesMintPda.toString());
  
  // 4. Vault's USDC token account
  const vaultUsdcToken = await getAssociatedTokenAddress(
    USDC_MINT,
    vaultAuthorityPda,
    true // allowOwnerOffCurve for PDA
  );
  staticAccounts.push(vaultUsdcToken);
  console.log("  4. Vault USDC Token:", vaultUsdcToken.toString());
  
  // 5. Treasury address (updated from your change)
  const treasury = new PublicKey("2zGsubjG1i1VXem7ADkS1KAT6ryFTdPQboozPK6EufMQ");
  staticAccounts.push(treasury);
  console.log("  5. Treasury:", treasury.toString());
  
  // 6. Treasury's USDC token account
  const treasuryUsdcToken = await getAssociatedTokenAddress(
    USDC_MINT,
    treasury
  );
  staticAccounts.push(treasuryUsdcToken);
  console.log("  6. Treasury USDC Token:", treasuryUsdcToken.toString());
  
  // 7. Staking program ID
  staticAccounts.push(STAKING_PROGRAM_ID);
  console.log("  7. Staking Program:", STAKING_PROGRAM_ID.toString());
  
  // 8. Stake Config PDA (from staking program)
  const [stakeConfigPda] = PublicKey.findProgramAddressSync(
    [STAKE_CONFIG_SEED],
    STAKING_PROGRAM_ID
  );
  staticAccounts.push(stakeConfigPda);
  console.log("  8. Stake Config PDA:", stakeConfigPda.toString());
  
  // 9. System Program
  staticAccounts.push(SystemProgram.programId);
  console.log("  9. System Program:", SystemProgram.programId.toString());
  
  // 10. Token Program
  staticAccounts.push(TOKEN_PROGRAM_ID);
  console.log(" 10. Token Program:", TOKEN_PROGRAM_ID.toString());
  
  // 11. Associated Token Program
  staticAccounts.push(ASSOCIATED_TOKEN_PROGRAM_ID);
  console.log(" 11. Associated Token Program:", ASSOCIATED_TOKEN_PROGRAM_ID.toString());
  
  // 12. Rent Sysvar
  staticAccounts.push(SYSVAR_RENT_PUBKEY);
  console.log(" 12. Rent Sysvar:", SYSVAR_RENT_PUBKEY.toString());
  
  // 13. USDC Mint
  staticAccounts.push(USDC_MINT);
  console.log(" 13. USDC Mint:", USDC_MINT.toString());
  
  // 14. CALVIN Mint
  staticAccounts.push(CALVIN_MINT);
  console.log(" 14. CALVIN Mint:", CALVIN_MINT.toString());
  
  // 15. Vault Program ID
  staticAccounts.push(VAULT_PROGRAM_ID);
  console.log(" 15. Vault Program ID:", VAULT_PROGRAM_ID.toString());
  
  // NOTE: User-specific accounts like userPosition, userUsdcToken, userSharesToken, 
  // and userStake CANNOT be in the ALT as they change per user
  
  return staticAccounts;
}

async function createDepositALT() {
  console.log("🚀 Creating Deposit-specific Address Lookup Table (ALT)...");
  
  // Initialize connection
  const connection = new Connection(MAINNET_RPC, "confirmed");
  
  // Load authority keypair from Solana config
  const authorityKeypair = loadSolanaConfigKeypair();
  console.log(`📋 Authority: ${authorityKeypair.publicKey.toString()}`);
  
  try {
    // Step 1: Calculate static deposit accounts
    const staticAccounts = await getDepositStaticAccounts();
    
    console.log(`\n📊 Total static accounts for deposit: ${staticAccounts.length}`);
    console.log(`💰 Transaction size savings: ~${staticAccounts.length * 31} bytes per deposit`);
    
    // Step 2: Create ALT
    console.log("\n🔨 Creating Address Lookup Table...");
    
    // Get recent slot with retry logic
    let currentSlot = await connection.getSlot("processed");
    console.log(`🕐 Using slot: ${currentSlot}`);
    
    let [lookupTableInstruction, lookupTableAddress] = 
      AddressLookupTableProgram.createLookupTable({
        authority: authorityKeypair.publicKey,
        payer: authorityKeypair.publicKey,
        recentSlot: currentSlot,
      });
    
    console.log(`📍 ALT Address: ${lookupTableAddress.toString()}`);
    
    // Step 3: Create transaction to create ALT
    let createAltTransaction = new VersionedTransaction(
      new TransactionMessage({
        payerKey: authorityKeypair.publicKey,
        recentBlockhash: (await connection.getLatestBlockhash()).blockhash,
        instructions: [
          ComputeBudgetProgram.setComputeUnitLimit({ units: 300_000 }),
          lookupTableInstruction,
        ],
      }).compileToV0Message()
    );
    
    createAltTransaction.sign([authorityKeypair]);
    
    // Send create ALT transaction with retry logic
    let createSignature;
    let retries = 3;
    
    while (retries > 0) {
      try {
        console.log(`🚀 Attempting to create ALT (${4 - retries}/3)...`);
        createSignature = await connection.sendTransaction(createAltTransaction, {
          skipPreflight: false,
          preflightCommitment: "processed"
        });
        console.log(`✅ ALT created! Signature: ${createSignature}`);
        break;
      } catch (error: any) {
        retries--;
        if (error.message?.includes("not a recent slot") && retries > 0) {
          console.log(`⚠️ Slot too old, retrying with newer slot...`);
          
          // Get a fresh slot and recreate
          const newerSlot = await connection.getSlot("processed");
          console.log(`🕐 Retrying with slot: ${newerSlot}`);
          
          const [newLookupTableInstruction, newLookupTableAddress] = 
            AddressLookupTableProgram.createLookupTable({
              authority: authorityKeypair.publicKey,
              payer: authorityKeypair.publicKey,
              recentSlot: newerSlot,
            });
          
          lookupTableAddress = newLookupTableAddress;
          
          createAltTransaction = new VersionedTransaction(
            new TransactionMessage({
              payerKey: authorityKeypair.publicKey,
              recentBlockhash: (await connection.getLatestBlockhash()).blockhash,
              instructions: [
                ComputeBudgetProgram.setComputeUnitLimit({ units: 300_000 }),
                newLookupTableInstruction,
              ],
            }).compileToV0Message()
          );
          
          createAltTransaction.sign([authorityKeypair]);
          
          await new Promise(resolve => setTimeout(resolve, 1000));
        } else {
          throw error;
        }
      }
    }
    
    if (!createSignature) {
      throw new Error("Failed to create ALT after 3 retries");
    }
    
    // Wait for confirmation
    await connection.confirmTransaction(createSignature, "confirmed");
    console.log("✅ ALT creation confirmed");
    
    // Step 4: Add accounts to ALT
    console.log("\n📝 Adding accounts to ALT...");
    
    const addAccountsInstruction = AddressLookupTableProgram.extendLookupTable({
      payer: authorityKeypair.publicKey,
      authority: authorityKeypair.publicKey,
      lookupTable: lookupTableAddress,
      addresses: staticAccounts,
    });
    
    const addAccountsTransaction = new VersionedTransaction(
      new TransactionMessage({
        payerKey: authorityKeypair.publicKey,
        recentBlockhash: (await connection.getLatestBlockhash()).blockhash,
        instructions: [
          ComputeBudgetProgram.setComputeUnitLimit({ units: 400_000 }),
          addAccountsInstruction,
        ],
      }).compileToV0Message()
    );
    
    addAccountsTransaction.sign([authorityKeypair]);
    
    const addSignature = await connection.sendTransaction(addAccountsTransaction);
    console.log(`✅ Accounts added! Signature: ${addSignature}`);
    
    await connection.confirmTransaction(addSignature, "confirmed");
    
    // Step 5: Save ALT configuration
    const altConfig = {
      address: lookupTableAddress.toString(),
      authority: authorityKeypair.publicKey.toString(),
      accounts: staticAccounts.map(acc => acc.toString()),
      purpose: "deposit",
      createdAt: new Date().toISOString(),
    };
    
    const configPath = path.join(__dirname, "../deposit-alt-config.json");
    fs.writeFileSync(configPath, JSON.stringify(altConfig, null, 2));
    
    console.log("\n🎉 Deposit ALT setup complete!");
    console.log(`📍 ALT Address: ${lookupTableAddress.toString()}`);
    console.log(`💾 Config saved to: ${configPath}`);
    console.log(`📊 Total accounts in ALT: ${staticAccounts.length}`);
    console.log(`💰 Transaction size savings: ~${staticAccounts.length * 31} bytes per deposit`);
    
    // Calculate estimated transaction size after ALT
    const baseTransactionSize = 300; // Base transaction overhead
    const perAccountSize = 32; // Size per account without ALT
    const perAccountSizeWithALT = 1; // Size per account with ALT
    
    const sizeWithoutALT = baseTransactionSize + (staticAccounts.length * perAccountSize);
    const sizeWithALT = baseTransactionSize + (staticAccounts.length * perAccountSizeWithALT) + 32; // +32 for ALT address
    
    console.log(`\n📏 Transaction size comparison:`);
    console.log(`  Without ALT: ${sizeWithoutALT} bytes`);
    console.log(`  With ALT: ${sizeWithALT} bytes`);
    console.log(`  Reduction: ${Math.round((1 - sizeWithALT/sizeWithoutALT) * 100)}%`);
    
  } catch (error) {
    console.error("❌ Error creating deposit ALT:", error);
    throw error;
  }
}

// Run the script
createDepositALT().catch(console.error); 