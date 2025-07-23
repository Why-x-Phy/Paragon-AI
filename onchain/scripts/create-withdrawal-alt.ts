/**
 * Create Withdrawal Address Lookup Table (ALT)
 * 
 * This ALT contains all oracle accounts needed for vault withdrawals
 * to solve the "Transaction too large" issue when the vault holds many tokens.
 */

import { 
  Connection, 
  PublicKey, 
  Keypair,
  TransactionMessage,
  VersionedTransaction,
  AddressLookupTableProgram,
  ComputeBudgetProgram
} from '@solana/web3.js';
import { TOKEN_PROGRAM_ID, getAssociatedTokenAddress } from '@solana/spl-token';
import * as fs from 'fs';
import * as path from 'path';

// Oracle configuration - must match oracle_config.rs exactly
const PYTH_PRICE_FEEDS = {
  'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': '0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a', // USDC
  'So11111111111111111111111111111111111111112': '0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d', // SOL
  '6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN': '0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a', // TRUMP
  'rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof': '0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d', // RENDER
  'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': '0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996', // JUP
  'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': '0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419', // BONK
  '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump': '0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608', // FARTCOIN
  '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R': '0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a', // RAY
  'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL': '0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2', // JTO
  'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3': '0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff', // PYTH
  'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': '0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc', // WIF
  '3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y': '0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b', // VIRTUAL
  '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv': '0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61', // PENGU
  '85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ': '0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389', // W (WORMHOLE)
  '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr': '0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce', // POPCAT
  'Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7': '0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a', // ATH
  'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5': '0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d', // MEW
  'MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey': '0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a', // MNDE
  'J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr': '0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a', // SPX
  'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE': '0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c', // ORCA
};

const RPC_ENDPOINT = process.env.SOLANA_RPC_URL || 'https://api.mainnet-beta.solana.com';
const COMMITMENT = 'processed'; // Use processed for most recent data

async function createWithdrawalALT() {
  console.log('🚀 Creating Withdrawal Address Lookup Table (ALT)...');
  
  // Load authority keypair
  const authorityKeyPath = path.join(__dirname, '..', 'calvin-ai-authority.json');
  const authorityKeyData = JSON.parse(fs.readFileSync(authorityKeyPath, 'utf8'));
  const authorityKeypair = Keypair.fromSecretKey(new Uint8Array(authorityKeyData));
  
  console.log('👤 Authority:', authorityKeypair.publicKey.toString());
  
  // Create connection
  const connection = new Connection(RPC_ENDPOINT, COMMITMENT);
  
  // Get vault authority PDA (where vault token accounts are held)
  const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault_authority")],
    new PublicKey("tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z") // Vault program ID
  );
  
  console.log('🏦 Vault Authority PDA:', vaultAuthorityPDA.toString());
  
  // Step 1: Create the ALT
  console.log('\n📋 Step 1: Creating ALT...');
  
  // Get the most recent slot possible - ALT creation is very sensitive to timing
  const currentSlot = await connection.getSlot("processed"); // Use "processed" for most recent
  console.log(`🕐 Using slot: ${currentSlot} (processed commitment)`);
  
  let [lookupTableInstruction, lookupTableAddress] = AddressLookupTableProgram.createLookupTable({
    authority: authorityKeypair.publicKey,
    payer: authorityKeypair.publicKey,
    recentSlot: currentSlot,
  });
  
  console.log('📍 ALT Address:', lookupTableAddress.toString());
  
  // Send create ALT transaction with retry logic
  let createSignature;
  let retries = 3;
  
  while (retries > 0) {
    try {
      console.log(`🚀 Attempting to create ALT (${4 - retries}/3)...`);
      
      // Create transaction with fresh blockhash
      const createAltTransaction = new VersionedTransaction(
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
        
        // Get a fresh slot and recreate the instruction
        const newerSlot = await connection.getSlot("processed");
        console.log(`🕐 Retrying with slot: ${newerSlot}`);
        
        const [newLookupTableInstruction, newLookupTableAddress] = 
          AddressLookupTableProgram.createLookupTable({
            authority: authorityKeypair.publicKey,
            payer: authorityKeypair.publicKey,
            recentSlot: newerSlot,
          });
        
        // Update for retry
        lookupTableInstruction = newLookupTableInstruction;
        lookupTableAddress = newLookupTableAddress;
        console.log('📍 New ALT Address:', lookupTableAddress.toString());
        
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
  await connection.confirmTransaction(createSignature, COMMITMENT);
  console.log('✅ ALT creation confirmed');
  
  // Step 2: Build oracle accounts for all tokens
  console.log('\n🔮 Step 2: Building oracle accounts...');
  const oracleAccounts: PublicKey[] = [];
  
  for (const [tokenMint, pythFeedId] of Object.entries(PYTH_PRICE_FEEDS)) {
    try {
      console.log(`📊 Processing ${tokenMint.slice(0, 8)}...`);
      
      // Get vault's token account for this mint
      const tokenAccount = await getAssociatedTokenAddress(
        new PublicKey(tokenMint),
        vaultAuthorityPDA,
        true // allowOwnerOffCurve = true for PDA
      );
      
      // Get Pyth price account
      const priceAccount = new PublicKey(Buffer.from(pythFeedId.slice(2), 'hex'));
      
      // Add oracle account group: [token_account, price_account, mint_account]
      oracleAccounts.push(
        tokenAccount,    // Vault's token account
        priceAccount,    // Pyth price oracle
        new PublicKey(tokenMint) // Token mint
      );
      
      console.log(`  ✅ Token Account: ${tokenAccount.toString()}`);
      console.log(`  ✅ Price Account: ${priceAccount.toString()}`);
      console.log(`  ✅ Mint Account: ${tokenMint}`);
      
    } catch (error) {
      console.warn(`⚠️ Failed to process ${tokenMint}:`, error.message);
      continue;
    }
  }
  
  console.log(`\n📦 Total oracle accounts: ${oracleAccounts.length} (${oracleAccounts.length / 3} token groups)`);
  
  // Step 3: Add accounts to ALT in batches
  console.log('\n📝 Step 3: Adding oracle accounts to ALT...');
  
  const BATCH_SIZE = 20; // Max accounts per transaction
  const batches: PublicKey[][] = [];
  for (let i = 0; i < oracleAccounts.length; i += BATCH_SIZE) {
    batches.push(oracleAccounts.slice(i, i + BATCH_SIZE));
  }
  
  for (let i = 0; i < batches.length; i++) {
    const batch = batches[i];
    console.log(`📦 Adding batch ${i + 1}/${batches.length} (${batch.length} accounts)...`);
    
    const extendInstruction = AddressLookupTableProgram.extendLookupTable({
      payer: authorityKeypair.publicKey,
      authority: authorityKeypair.publicKey,
      lookupTable: lookupTableAddress,
      addresses: batch,
    });
    
    const extendTransaction = new VersionedTransaction(
      new TransactionMessage({
        payerKey: authorityKeypair.publicKey,
        recentBlockhash: (await connection.getLatestBlockhash()).blockhash,
        instructions: [
          ComputeBudgetProgram.setComputeUnitLimit({ units: 300_000 }),
          extendInstruction,
        ],
      }).compileToV0Message()
    );
    
    extendTransaction.sign([authorityKeypair]);
    const extendSignature = await connection.sendTransaction(extendTransaction);
    console.log(`✅ Batch ${i + 1} signature: ${extendSignature}`);
    
    // Wait for confirmation before next batch
    await connection.confirmTransaction(extendSignature, COMMITMENT);
    
    // Small delay to avoid rate limits
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  
  // Step 4: Verify ALT was created correctly
  console.log('\n🔍 Step 4: Verifying ALT...');
  await new Promise(resolve => setTimeout(resolve, 2000)); // Wait for propagation
  
  const altAccount = await connection.getAddressLookupTable(lookupTableAddress);
  if (altAccount.value) {
    console.log('✅ ALT verified successfully!');
    console.log(`📊 ALT contains ${altAccount.value.state.addresses.length} addresses`);
    console.log(`🔮 Oracle accounts stored: ${altAccount.value.state.addresses.length} (${altAccount.value.state.addresses.length / 3} token groups)`);
  } else {
    console.error('❌ ALT verification failed');
    process.exit(1);
  }
  
  // Step 5: Save ALT address to environment file
  console.log('\n💾 Step 5: Saving ALT address...');
  const envFile = path.join(__dirname, '..', '..', 'frontend', '.env.local');
  let envContent = '';
  
  try {
    if (fs.existsSync(envFile)) {
      envContent = fs.readFileSync(envFile, 'utf8');
    }
  } catch (error) {
    console.log('📝 Creating new .env.local file');
  }
  
  // Update or add WITHDRAWAL_ALT
  const altLine = `NEXT_PUBLIC_WITHDRAWAL_ALT=${lookupTableAddress.toString()}`;
  
  if (envContent.includes('NEXT_PUBLIC_WITHDRAWAL_ALT=')) {
    // Replace existing line
    envContent = envContent.replace(
      /NEXT_PUBLIC_WITHDRAWAL_ALT=.*/,
      altLine
    );
  } else {
    // Add new line
    envContent += `\n${altLine}\n`;
  }
  
  fs.writeFileSync(envFile, envContent);
  console.log(`✅ ALT address saved to ${envFile}`);
  
  console.log('\n🎉 Withdrawal ALT creation complete!');
  console.log('📋 Summary:');
  console.log(`   ALT Address: ${lookupTableAddress.toString()}`);
  console.log(`   Oracle Accounts: ${oracleAccounts.length}`);
  console.log(`   Token Groups: ${oracleAccounts.length / 3}`);
  console.log('');
  console.log('🔧 Next steps:');
  console.log('   1. The ALT address has been saved to frontend/.env.local');
  console.log('   2. Restart your frontend to pick up the new environment variable');
  console.log('   3. Withdrawals will now use ALT optimization automatically');
  console.log('');
  console.log('💡 To test: Try withdrawing with a vault that holds many tokens');
}

// Run the script
createWithdrawalALT().catch(console.error); 