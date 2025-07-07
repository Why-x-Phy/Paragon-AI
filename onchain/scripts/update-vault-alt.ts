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
const VAULT_PROGRAM_ID = new PublicKey("tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z");
const JUPITER_PROGRAM_ID = new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
const USDC_MINT = new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");

// Load keypair function (you'll need to implement this)
function loadKeypair(): Keypair {
  // Load your Calvin AI authority keypair
  const secretKey = JSON.parse(fs.readFileSync("calvin-ai-authority.json", "utf8"));
  return Keypair.fromSecretKey(new Uint8Array(secretKey));
}

async function updateVaultALT() {
  console.log("🔄 UPDATING Vault Address Lookup Table (ALT)...");
  console.log("📝 Removing obsolete oracle accounts from pull oracle migration");
  
  // Initialize connection
  const connection = new Connection(MAINNET_RPC, "confirmed");
  
  // Load authority keypair
  const authorityKeypair = loadKeypair();
  console.log(`📋 Authority: ${authorityKeypair.publicKey.toString()}`);
  
  try {
    // Load current ALT config
    const currentConfigPath = path.join(__dirname, "../vault-alt-config.json");
    const currentConfig = JSON.parse(fs.readFileSync(currentConfigPath, "utf8"));
    const currentAltAddress = new PublicKey(currentConfig.address);
    
    console.log(`📍 Current ALT: ${currentAltAddress.toString()}`);
    console.log(`📊 Current accounts: ${currentConfig.accounts.length}`);
    
    // Step 1: Calculate new optimized static accounts (NO oracle accounts)
    const newStaticAccounts = await getOptimizedStaticAccounts();
    
    console.log("\n📊 NEW OPTIMIZED ALT ACCOUNTS:");
    console.log(`  - Previous accounts: ${currentConfig.accounts.length}`);
    console.log(`  - New accounts: ${newStaticAccounts.length}`);
    console.log(`  - Removed: ${currentConfig.accounts.length - newStaticAccounts.length} obsolete oracle accounts`);
    console.log(`  - Space freed: ${(currentConfig.accounts.length - newStaticAccounts.length) * 32} bytes`);
    
    newStaticAccounts.forEach((account, index) => {
      console.log(`  ${index + 1}. ${account.toString()}`);
    });
    
    // Step 2: Create a new ALT (we'll replace the old one)
    console.log("\n🔨 Creating new optimized ALT...");
    
    const currentSlot = await connection.getSlot("processed");
    console.log(`🕐 Using slot: ${currentSlot}`);
    
    let [lookupTableInstruction, newAltAddress] = 
      AddressLookupTableProgram.createLookupTable({
        authority: authorityKeypair.publicKey,
        payer: authorityKeypair.publicKey,
        recentSlot: currentSlot,
      });
    
    console.log(`📍 New ALT Address: ${newAltAddress.toString()}`);
    
    // Step 3: Create new ALT
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
        console.log(`🚀 Creating new ALT (${4 - retries}/3)...`);
        createSignature = await connection.sendTransaction(createAltTransaction, {
          skipPreflight: false,
          preflightCommitment: "processed"
        });
        console.log(`✅ New ALT created! Signature: ${createSignature}`);
        break;
      } catch (error: any) {
        retries--;
        if (error.message?.includes("not a recent slot") && retries > 0) {
          console.log(`⚠️ Slot too old, retrying with newer slot...`);
          
          const newerSlot = await connection.getSlot("processed");
          console.log(`🕐 Retrying with slot: ${newerSlot}`);
          
          const [newInstruction, newerAddress] = 
            AddressLookupTableProgram.createLookupTable({
              authority: authorityKeypair.publicKey,
              payer: authorityKeypair.publicKey,
              recentSlot: newerSlot,
            });
          
          newAltAddress = newerAddress;
          
          createAltTransaction = new VersionedTransaction(
            new TransactionMessage({
              payerKey: authorityKeypair.publicKey,
              recentBlockhash: (await connection.getLatestBlockhash()).blockhash,
              instructions: [
                ComputeBudgetProgram.setComputeUnitLimit({ units: 300_000 }),
                newInstruction,
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
      throw new Error("Failed to create new ALT after 3 retries");
    }
    
    // Wait for confirmation
    await connection.confirmTransaction(createSignature, "confirmed");
    console.log("✅ New ALT creation confirmed");
    
    // Step 4: Add optimized accounts to new ALT
    console.log("\n📝 Adding optimized accounts to new ALT...");
    
    const BATCH_SIZE = 20;
    const batches = [];
    for (let i = 0; i < newStaticAccounts.length; i += BATCH_SIZE) {
      batches.push(newStaticAccounts.slice(i, i + BATCH_SIZE));
    }
    
    for (let i = 0; i < batches.length; i++) {
      const batch = batches[i];
      console.log(`📦 Adding batch ${i + 1}/${batches.length} (${batch.length} accounts)...`);
      
      const addAccountsInstruction = AddressLookupTableProgram.extendLookupTable({
        payer: authorityKeypair.publicKey,
        authority: authorityKeypair.publicKey,
        lookupTable: newAltAddress,
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
      
      await connection.confirmTransaction(addSignature, "confirmed");
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    
    // Step 5: Save new ALT config and backup old one
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const backupPath = path.join(__dirname, `../vault-alt-config-backup-${timestamp}.json`);
    
    // Backup old config
    fs.writeFileSync(backupPath, JSON.stringify(currentConfig, null, 2));
    console.log(`💾 Old ALT config backed up to: ${backupPath}`);
    
    // Save new config
    const newAltConfig = {
      address: newAltAddress.toString(),
      authority: authorityKeypair.publicKey.toString(),
      accounts: newStaticAccounts.map(acc => acc.toString()),
      createdAt: new Date().toISOString(),
      migration: {
        from: currentAltAddress.toString(),
        reason: "Removed obsolete oracle accounts after pull oracle migration",
        accountsRemoved: currentConfig.accounts.length - newStaticAccounts.length,
        bytesFreed: (currentConfig.accounts.length - newStaticAccounts.length) * 32
      }
    };
    
    const configPath = path.join(__dirname, "../vault-alt-config.json");
    fs.writeFileSync(configPath, JSON.stringify(newAltConfig, null, 2));
    
    console.log("\n🎉 ALT Update Complete!");
    console.log(`📍 New ALT Address: ${newAltAddress.toString()}`);
    console.log(`📍 Old ALT Address: ${currentAltAddress.toString()} (backed up)`);
    console.log(`💾 Config saved to: ${configPath}`);
    console.log(`📊 Optimization Summary:`);
    console.log(`  - Accounts: ${currentConfig.accounts.length} → ${newStaticAccounts.length}`);
    console.log(`  - Removed: ${currentConfig.accounts.length - newStaticAccounts.length} obsolete oracle accounts`);
    console.log(`  - Space freed: ${(currentConfig.accounts.length - newStaticAccounts.length) * 32} bytes`);
    console.log(`  - Transaction size savings: ${newStaticAccounts.length * 32} bytes per trade`);
    
    console.log("\n⚠️ IMPORTANT: Update your vault client configuration!");
    console.log("Update VAULT_ALT_ADDRESS in your environment to:");
    console.log(newAltAddress.toString());
    
  } catch (error) {
    console.error("❌ Error updating vault ALT:", error);
    throw error;
  }
}

async function getOptimizedStaticAccounts(): Promise<PublicKey[]> {
  // Calculate optimized static vault accounts (NO oracle accounts!)
  
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
  
  // 4. Treasury USDC Token Account
  const treasuryAddress = new PublicKey("2zGsubjG1i1VXem7ADkS1KAT6ryFTdPQboozPK5EufMQ"); 
  const treasuryUsdcAccount = await getAssociatedTokenAddress(
    USDC_MINT,
    treasuryAddress
  );
  
  // 5. Switchboard oracle accounts (from oracle_config.rs) - frequently referenced for NAV calculations  
  const SWITCHBOARD_ORACLE_ACCOUNTS = [
    new PublicKey("D9jeEiEr4PkDCM7eNCtDbpiBkp6KkBav7DcgEsPiEius"), // TRUMP
    new PublicKey("9m1Ys7ga7jchMYRGXz1u5sUvjXbS15RBX6iRsmEJrQCC"), // WIF
    new PublicKey("3wadb2fsPkDNpQazr5VFa9A2BoLcEWMrPcPHNACFBDvt"), // ATH
    new PublicKey("68FbNAyrhME3DrSRSyKjuTFdQZ5b4erzK6uJQ3RTkitn"), // BONK
    new PublicKey("GWvcdLtk2tx5pMecRV6e2fg27QGB8vqHbC1YNvtpjCdV"), // FARTCOIN
    new PublicKey("Dp9sZHXjiyTd1atN2pKswWVnP9Q9ZkP3euqvoNv2yv8f"), // JTO
    new PublicKey("G8oxFvUWzVYE3saje8Z9JuBrn1qf4puwKQkbNU6PU4su"), // JUP
    new PublicKey("34muAMwQGCzXpjPnTuQqhdLfVPraitpRyFd9ZYXJejCU"), // MEW
    new PublicKey("GnqWo8LEiShqYeFHsA8i6n8UJMmz9hv8M19XMgj9aMkL"), // MNDE
    new PublicKey("627A7kdEbVPGq7azuk43a8ebgJ5eipwMgwTVNBX9K8aU"), // ORCA
    new PublicKey("B3R37cUYMvRd35KZrYsJxZDs6VuwAMZ7mBQgt3dHTVPt"), // PENGU
    new PublicKey("52jh55TNJpUguy8e9kGRE5HxPXvnhDM9QjAmojmzqzXr"), // POPCAT
    new PublicKey("EbT9BxSXKi6Stn8EGwq1mZZfGW3oyUY7iRcT9uVbY9g7"), // PYTH
    new PublicKey("8UP4XCJePyWvYUMhRUzVj1YSmuvMgb4hAqU713FFRaGN"), // RAY
    new PublicKey("7z7En3AsXyV9xG99KNhEKS5tTnsRM5ViCwtcjtJ8NQ9r"), // RENDER
    new PublicKey("4W492CojQZzWopVjHPqSyAKW5KSbusyPnvQuNNxjvn19"), // SPX
    new PublicKey("4daWXka1pSo1xvuYMTirCp378GgxhRoqr5vFK26dB9Zw"), // VIRTUAL
    new PublicKey("98YY8drz4bLD2jTXcQcqJibbtBYmARuoPyAgVq61Y66E"), // W
    new PublicKey("9BHh6RVPCt7ijv6K5MukZjeCUBtamHQXhRUr1TeudgUL"), // SOL
    new PublicKey("8F7VKK7ZtL3moBzV4QSkzPZo2xSUx15K6wv1G1QZQDix"), // USDC
  ];

  // 6. ALL Core Trading Token Mints (from TRACKED_TOKENS and oracle config)
  const ALL_CORE_TOKEN_MINTS = [
    // Base tokens
    new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"), // USDC
    new PublicKey("So11111111111111111111111111111111111111112"),   // SOL
    new PublicKey("229vWzBTiUNdraYpVtSH9usTwwVxcyPDbBWf1zEPpump"), // CALVIN
    
    // Political/Meme tokens
    new PublicKey("6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN"), // TRUMP
    new PublicKey("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"), // BONK
    new PublicKey("9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"), // FARTCOIN
    new PublicKey("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"), // WIF
    new PublicKey("3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y"), // VIRTUAL
    new PublicKey("2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv"), // PENGU
    new PublicKey("7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"), // POPCAT
    new PublicKey("Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7"), // ATH
    new PublicKey("MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5"), // MEW
    new PublicKey("J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr"), // SPX (SPX6900)
    new PublicKey("85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ"), // W (WORMHOLE)
    
    // DeFi Infrastructure tokens
    new PublicKey("rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof"), // RENDER
    new PublicKey("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"), // JUP
    new PublicKey("4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"), // RAY
    new PublicKey("jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL"), // JTO
    new PublicKey("HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3"), // PYTH
    new PublicKey("orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE"), // ORCA
    new PublicKey("MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey"), // MNDE
  ];
  
  // Optimized static accounts (NO oracle accounts)
  const optimizedAccounts = [
    // Core vault infrastructure (6 accounts)
    vaultPda,                 // Vault PDA
    vaultUsdcAccount,         // Vault USDC token account
    vaultAuthorityPda,        // Vault authority PDA  
    TOKEN_PROGRAM_ID,         // Token program ID
    treasuryUsdcAccount,      // Treasury USDC token account
    JUPITER_PROGRAM_ID,       // Jupiter program ID
    
      // All core trading token mints - frequently referenced
  ...ALL_CORE_TOKEN_MINTS,
  
  // Switchboard oracle accounts - frequently referenced for NAV calculations
  ...SWITCHBOARD_ORACLE_ACCOUNTS,
];
  
  console.log("\n📊 Optimized ALT Structure:");
  console.log(`  - Vault infrastructure: 6 accounts`);
  console.log(`  - Core token mints: ${ALL_CORE_TOKEN_MINTS.length} accounts`);
  console.log(`  - Switchboard oracle accounts: ${SWITCHBOARD_ORACLE_ACCOUNTS.length} accounts`);
  console.log(`  - Total: ${optimizedAccounts.length} accounts`);
  console.log(`  - Bytes saved per oracle reference: 32 bytes`);
  console.log(`  - Potential NAV calculation savings: ${SWITCHBOARD_ORACLE_ACCOUNTS.length * 32} bytes`);
  
  return optimizedAccounts;
}

// Run the script
if (require.main === module) {
  updateVaultALT()
    .then(() => {
      console.log("✅ ALT update completed successfully");
      process.exit(0);
    })
    .catch((error) => {
      console.error("❌ ALT update failed:", error);
      process.exit(1);
    });
}

export { updateVaultALT, getOptimizedStaticAccounts }; 