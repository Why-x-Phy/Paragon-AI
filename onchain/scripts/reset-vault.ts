import * as anchor from "@coral-xyz/anchor";
import { Connection, PublicKey, SystemProgram, Transaction, sendAndConfirmTransaction } from "@solana/web3.js";
import { TOKEN_PROGRAM_ID } from "@solana/spl-token";
import fs from 'fs';

// Program IDs
const VAULT_PROGRAM_ID = new PublicKey("2nLsDVW67Qw5LXGvaTzUQ7xRxytY52APWJAz2c7aqqyJ");
const USDC_MINT = new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");

async function resetVault() {
  console.log("🧹 Resetting corrupted vault account...");
  
  // Set up connection and authority
  const connection = new Connection("https://api.devnet.solana.com", "confirmed");
  
  // Load authority keypair
  const authorityPath = "/home/lincolnb/.config/solana/id.json";
  const authorityKeypair = anchor.web3.Keypair.fromSecretKey(
    new Uint8Array(JSON.parse(fs.readFileSync(authorityPath, "utf8")))
  );
  
  console.log("Authority:", authorityKeypair.publicKey.toBase58());
  
  // Calculate the existing corrupted vault PDA (using old seeds)
  const [oldVault] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault"), Buffer.from("v2")], // OLD INCORRECT SEEDS
    VAULT_PROGRAM_ID
  );
  
  // Calculate the correct vault PDA (using correct seeds)
  const [newVault] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault")], // CORRECT SEEDS
    VAULT_PROGRAM_ID
  );
  
  console.log("Old corrupted vault PDA:", oldVault.toBase58());
  console.log("New correct vault PDA:", newVault.toBase58());
  
  // Check if old vault exists and has incorrect data
  try {
    const oldVaultInfo = await connection.getAccountInfo(oldVault);
    if (oldVaultInfo) {
      console.log(`📋 Old vault account exists with ${oldVaultInfo.data.length} bytes`);
      console.log("💰 SOL balance:", oldVaultInfo.lamports / 1e9);
      
      if (oldVaultInfo.data.length === 420) {
        console.log("⚠️ This appears to be the corrupted vault account (420 bytes)");
        
        // We can't directly close this account since it belongs to the program
        // Instead, we'll let the initialize instruction handle it
        console.log("ℹ️ The initialize instruction should overwrite this account");
      }
    } else {
      console.log("ℹ️ Old vault account doesn't exist");
    }
  } catch (error) {
    console.log("ℹ️ Could not fetch old vault account info");
  }
  
  // Check if new vault exists
  try {
    const newVaultInfo = await connection.getAccountInfo(newVault);
    if (newVaultInfo) {
      console.log(`📋 New vault account already exists with ${newVaultInfo.data.length} bytes`);
      console.log("💰 SOL balance:", newVaultInfo.lamports / 1e9);
      
      // This shouldn't exist yet, but if it does, we need to close it first
      console.log("⚠️ New vault account already exists - may need manual intervention");
    } else {
      console.log("✅ New vault PDA is clean and ready for initialization");
    }
  } catch (error) {
    console.log("ℹ️ Could not fetch new vault account info");
  }
  
  console.log("\n🎯 Ready to run initialize script with correct seeds");
  console.log("Run: npx ts-node scripts/initialize-devnet.ts");
}

// Run the reset
resetVault()
  .then(() => {
    console.log("✅ Reset analysis complete");
    process.exit(0);
  })
  .catch((error) => {
    console.error("❌ Reset failed:", error);
    process.exit(1);
  }); 