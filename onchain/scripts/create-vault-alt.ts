import {
  Connection,
  Keypair,
  PublicKey,
  AddressLookupTableProgram,
  TransactionMessage,
  VersionedTransaction,
  ComputeBudgetProgram,
} from "@solana/web3.js";
import { getAssociatedTokenAddress, TOKEN_PROGRAM_ID } from "@solana/spl-token";
import * as fs from "fs";
import * as path from "path";

// Configuration
const MAINNET_RPC = "https://api.mainnet-beta.solana.com";
const VAULT_PROGRAM_ID = new PublicKey("tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z"); // Replace with actual program ID
const JUPITER_PROGRAM_ID = new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
const USDC_MINT = new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");

async function createVaultALT() {
  console.log("🚀 Creating Vault Address Lookup Table (ALT)...");
  
  // Initialize connection
  const connection = new Connection(MAINNET_RPC, "confirmed");
  
  // Load authority keypair (replace with your actual keypair loading logic)
  const authorityKeypair = loadKeypair(); // You'll need to implement this
  
  console.log(`📋 Authority: ${authorityKeypair.publicKey.toString()}`);
  
  try {
    // Step 1: Calculate static vault accounts
    const staticAccounts = await getStaticVaultAccounts();
    
    console.log("📊 Static accounts to add to ALT:");
    staticAccounts.forEach((account, index) => {
      console.log(`  ${index + 1}. ${account.toString()}`);
    });
    
    // Step 2: Create ALT
    console.log("\n🔨 Creating Address Lookup Table...");
    
    // Get the most recent slot possible - ALT creation is very sensitive to timing
    const currentSlot = await connection.getSlot("processed"); // Use "processed" for most recent
    console.log(`🕐 Using slot: ${currentSlot} (processed commitment)`);
    
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
          
          // Get a fresh slot and recreate the transaction
          const newerSlot = await connection.getSlot("processed");
          console.log(`🕐 Retrying with slot: ${newerSlot}`);
          
          const [newLookupTableInstruction, newLookupTableAddress] = 
            AddressLookupTableProgram.createLookupTable({
              authority: authorityKeypair.publicKey,
              payer: authorityKeypair.publicKey,
              recentSlot: newerSlot,
            });
          
          // Update addresses
          lookupTableAddress = newLookupTableAddress;
          
          // Recreate transaction with new slot
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
          
          // Small delay before retry
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
    
    // Step 4: Add accounts to ALT (in batches if needed)
    console.log("\n📝 Adding accounts to ALT...");
    
    const BATCH_SIZE = 20; // Max accounts per transaction
    const batches = [];
    for (let i = 0; i < staticAccounts.length; i += BATCH_SIZE) {
      batches.push(staticAccounts.slice(i, i + BATCH_SIZE));
    }
    
    for (let i = 0; i < batches.length; i++) {
      const batch = batches[i];
      console.log(`📦 Adding batch ${i + 1}/${batches.length} (${batch.length} accounts)...`);
      
      const addAccountsInstruction = AddressLookupTableProgram.extendLookupTable({
        payer: authorityKeypair.publicKey,
        authority: authorityKeypair.publicKey,
        lookupTable: lookupTableAddress,
        addresses: batch,
      });
      
      const addAccountsTransaction = new VersionedTransaction(
        new TransactionMessage({
          payerKey: authorityKeypair.publicKey,
          recentBlockhash: (await connection.getLatestBlockhash()).blockhash,
          instructions: [
            ComputeBudgetProgram.setComputeUnitLimit({ units: 300_000 }),
            addAccountsInstruction,
          ],
        }).compileToV0Message()
      );
      
      addAccountsTransaction.sign([authorityKeypair]);
      
      const addSignature = await connection.sendTransaction(addAccountsTransaction);
      console.log(`✅ Batch ${i + 1} added! Signature: ${addSignature}`);
      
      // Wait for confirmation before next batch
      await connection.confirmTransaction(addSignature, "confirmed");
      
      // Small delay to avoid rate limits
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    
    // Step 5: Save ALT address for future use
    const altConfig = {
      address: lookupTableAddress.toString(),
      authority: authorityKeypair.publicKey.toString(),
      accounts: staticAccounts.map(acc => acc.toString()),
      createdAt: new Date().toISOString(),
    };
    
    const configPath = path.join(__dirname, "../vault-alt-config.json");
    fs.writeFileSync(configPath, JSON.stringify(altConfig, null, 2));
    
    console.log("\n🎉 Vault ALT setup complete!");
    console.log(`📍 ALT Address: ${lookupTableAddress.toString()}`);
    console.log(`💾 Config saved to: ${configPath}`);
    console.log(`📊 Total accounts in ALT: ${staticAccounts.length}`);
    console.log(`💰 Transaction size savings: ${staticAccounts.length * 32} bytes per trade`);
    
  } catch (error) {
    console.error("❌ Error creating vault ALT:", error);
    throw error;
  }
}

async function getStaticVaultAccounts(): Promise<PublicKey[]> {
  // Calculate all static vault accounts that never change
  
  // 1. Vault PDA
  const [vaultPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault")],
    VAULT_PROGRAM_ID
  );
  
  // 2. Vault Authority PDA  
  const [vaultAuthorityPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault_authority")],
    VAULT_PROGRAM_ID
  );
  
  // 3. Vault USDC Token Account
  const vaultUsdcAccount = await getAssociatedTokenAddress(
    USDC_MINT,
    vaultAuthorityPda,
    true // allowOwnerOffCurve = true for PDAs
  );
  
  // 4. Treasury USDC Token Account (you'll need to get treasury address from config)
  const treasuryAddress = new PublicKey("2zGsubjG1i1VXem7ADkS1KAT6ryFTdPQboozPK5EufMQ"); 
  const treasuryUsdcAccount = await getAssociatedTokenAddress(
    USDC_MINT,
    treasuryAddress
  );
  
  // 5. Pyth Oracle Accounts - Using original hex codes from oracle_config.rs for accuracy
  const pythOracles = [];
  const oracleHexCodes = [
    "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a", // USDC
    "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a", // TRUMP
    "0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d", // RENDER
    "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996", // JUP
    "0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419", // BONK
    "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608", // FARTCOIN
    "0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a", // RAY
    "0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2", // JTO
    "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d0d719579ff", // PYTH
    "0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc", // WIF
    "0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b", // VIRTUAL
    "0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61", // PENGU
    "0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389", // W (WORMHOLE)
    "0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce", // POPCAT
    "0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a", // ATH
    "0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d", // MEW
    "0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a", // MNDE
    "0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a", // SPX (SPX6900)
    "0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c", // ORCA
  ];
  
  // Convert hex codes to PublicKey objects at runtime for accuracy
  for (let i = 0; i < oracleHexCodes.length; i++) {
    try {
      const hexStr = oracleHexCodes[i];
      const hexClean = hexStr.startsWith('0x') ? hexStr.slice(2) : hexStr;
      
      if (hexClean.length !== 64) {
        console.warn(`⚠️ Invalid hex length for oracle ${i}: ${hexClean.length}, expected 64`);
        continue;
      }
      
      // Convert hex to bytes
      const bytes = new Uint8Array(32);
      for (let j = 0; j < 32; j++) {
        const byteStr = hexClean.slice(j * 2, j * 2 + 2);
        bytes[j] = parseInt(byteStr, 16);
      }
      
      const pubkey = new PublicKey(bytes);
      pythOracles.push(pubkey);
      console.log(`✅ Oracle ${i}: ${pubkey.toString()}`);
    } catch (error) {
      console.warn(`⚠️ Failed to convert oracle hex ${i}: ${oracleHexCodes[i]} - ${error}`);
    }
  }
  
  // Static accounts that never change
  const staticAccounts = [
    vaultPda,                 // Vault PDA
    vaultUsdcAccount,         // Vault USDC token account
    vaultAuthorityPda,        // Vault authority PDA  
    TOKEN_PROGRAM_ID,         // Token program ID
    treasuryUsdcAccount,      // Treasury USDC token account
    JUPITER_PROGRAM_ID,       // Jupiter program ID
    ...pythOracles,           // All Pyth oracle accounts (19 oracles)
  ];
  
  return staticAccounts;
}

function loadKeypair(): Keypair {
  // Load your authority keypair here
  // This is just a placeholder - you'll need to implement based on your setup
  
  try {
    // Option 1: Load from file
    const keypairPath = path.join(process.env.HOME || "", ".config/solana/id.json");
    if (fs.existsSync(keypairPath)) {
      const keypairData = JSON.parse(fs.readFileSync(keypairPath, "utf8"));
      return Keypair.fromSecretKey(new Uint8Array(keypairData));
    }
    
    // Option 2: Load from environment variable
    if (process.env.CALVIN_AUTHORITY_PRIVATE_KEY) {
      const privateKeyArray = JSON.parse(process.env.CALVIN_AUTHORITY_PRIVATE_KEY);
      return Keypair.fromSecretKey(new Uint8Array(privateKeyArray));
    }
    
    throw new Error("No keypair found");
  } catch (error) {
    console.error("❌ Error loading keypair:", error);
    console.log("💡 Please ensure you have a keypair configured");
    throw error;
  }
}

// Run the script
if (require.main === module) {
  createVaultALT()
    .then(() => {
      console.log("✅ Script completed successfully");
      process.exit(0);
    })
    .catch((error) => {
      console.error("❌ Script failed:", error);
      process.exit(1);
    });
}

export { createVaultALT, getStaticVaultAccounts }; 