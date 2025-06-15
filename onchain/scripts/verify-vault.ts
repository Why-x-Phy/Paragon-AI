import * as anchor from "@coral-xyz/anchor";
import { Connection, PublicKey } from "@solana/web3.js";
import { getAssociatedTokenAddressSync } from "@solana/spl-token";
import fs from 'fs';

// Program IDs
const VAULT_PROGRAM_ID = new PublicKey("2nLsDVW67Qw5LXGvaTzUQ7xRxytY52APWJAz2c7aqqyJ");
const STAKING_PROGRAM_ID = new PublicKey("GocZdo1RPcsQnbiQrFp6Ybgd3bWUp48Jd4wytN3QN3Vw");
const USDC_MINT = new PublicKey("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU");
const CALVIN_MINT = new PublicKey("CrWbUJ4kMgduYDVRK8bDXhNBHr8cScixi79nGdGejnb1");

async function verifyVault() {
  console.log("🔍 Verifying Calvin Vault State...");
  
  // Set up connection
  const connection = new Connection("https://api.devnet.solana.com", "confirmed");
  
  // Load authority keypair for reference
  const authorityPath = "/home/lincolnb/.config/solana/id.json";
  const authorityKeypair = anchor.web3.Keypair.fromSecretKey(
    new Uint8Array(JSON.parse(fs.readFileSync(authorityPath, "utf8")))
  );
  
  console.log("Authority:", authorityKeypair.publicKey.toBase58());
  
  // Calculate all the PDAs
  const [vault] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault")],
    VAULT_PROGRAM_ID
  );
  
  const [vaultAuthority] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault_authority")],
    VAULT_PROGRAM_ID
  );
  
  const [sharesMint] = PublicKey.findProgramAddressSync(
    [Buffer.from("shares_mint")],
    VAULT_PROGRAM_ID
  );
  
  const usdcVault = getAssociatedTokenAddressSync(
    USDC_MINT,
    vaultAuthority,
    true // allowOwnerOffCurve
  );
  
  console.log("\n📍 Expected PDA Addresses:");
  console.log("🔹 Vault PDA:", vault.toBase58());
  console.log("🔹 Vault Authority:", vaultAuthority.toBase58());
  console.log("🔹 Shares Mint:", sharesMint.toBase58());
  console.log("🔹 USDC Vault:", usdcVault.toBase58());
  
  // Check vault account
  try {
    console.log("\n🔍 Checking Vault Account...");
    const vaultInfo = await connection.getAccountInfo(vault);
    
    if (!vaultInfo) {
      console.log("❌ Vault account does not exist!");
      return;
    }
    
    console.log("✅ Vault account exists");
    console.log("📊 Data length:", vaultInfo.data.length, "bytes");
    console.log("💰 SOL balance:", vaultInfo.lamports / 1e9);
    console.log("👤 Owner:", vaultInfo.owner.toBase58());
    
    // Verify owner is the vault program
    if (vaultInfo.owner.equals(VAULT_PROGRAM_ID)) {
      console.log("✅ Vault owned by correct program");
    } else {
      console.log("❌ Vault owned by wrong program!");
      console.log("   Expected:", VAULT_PROGRAM_ID.toBase58());
      console.log("   Actual:  ", vaultInfo.owner.toBase58());
    }
    
         // Check if vault data looks reasonable (basic validation)
     console.log("\n📋 Basic Vault Data Check:");
     
     // Expected size for a properly initialized vault account
     const expectedSize = 8 + // discriminator
       32 + // emergency_owner
       32 + // calvin_authority  
       32 + // staking_program_id
       32 + // shares_mint
       32 + // usdc_mint
       32 + // usdc_vault
       32 + // vault_authority
       1 + // vault_bump
       1 + // shares_mint_bump
       1 + // authority_bump
       32 + // calvin_mint
       32 + // treasury
       8 + // per_nft_cap
       8 + // high_water_mark_nav
       8 + // total_shares
       1 + // paused
       32 + // jupiter_program_id
       64; // reserved
     
     console.log("🔹 Expected size:", expectedSize, "bytes");
     console.log("🔹 Actual size:", vaultInfo.data.length, "bytes");
     
     if (vaultInfo.data.length === expectedSize) {
       console.log("✅ Vault data size matches expected structure");
     } else if (vaultInfo.data.length === 420) {
       console.log("⚠️ Vault has 420 bytes - this was the corrupted size");
       console.log("   But if initialization succeeded, it should be properly structured now");
     } else {
       console.log("❌ Unexpected vault data size");
     }
     
     // Check if the first 8 bytes look like a discriminator
     const discriminator = vaultInfo.data.slice(0, 8);
     console.log("🔹 Discriminator (first 8 bytes):", Array.from(discriminator).map(b => b.toString(16).padStart(2, '0')).join(''));
     
     // A properly initialized account should have a non-zero discriminator
     const hasValidDiscriminator = discriminator.some(byte => byte !== 0);
     if (hasValidDiscriminator) {
       console.log("✅ Vault has valid discriminator (not all zeros)");
     } else {
       console.log("❌ Vault discriminator is all zeros - may be uninitialized");
     }
    
  } catch (error) {
    console.log("❌ Error checking vault account:", error);
  }
  
  // Check shares mint
  try {
    console.log("\n🔍 Checking Shares Mint...");
    const sharesMintInfo = await connection.getAccountInfo(sharesMint);
    
    if (sharesMintInfo) {
      console.log("✅ Shares mint exists");
      console.log("📊 Data length:", sharesMintInfo.data.length, "bytes");
      console.log("👤 Owner:", sharesMintInfo.owner.toBase58());
    } else {
      console.log("❌ Shares mint does not exist!");
    }
  } catch (error) {
    console.log("❌ Error checking shares mint:", error);
  }
  
  // Check USDC vault token account
  try {
    console.log("\n🔍 Checking USDC Vault Token Account...");
    const usdcVaultInfo = await connection.getAccountInfo(usdcVault);
    
    if (usdcVaultInfo) {
      console.log("✅ USDC vault token account exists");
      console.log("📊 Data length:", usdcVaultInfo.data.length, "bytes");
      console.log("👤 Owner:", usdcVaultInfo.owner.toBase58());
      
      // Try to get token account info
      try {
        const tokenAccountInfo = await connection.getParsedAccountInfo(usdcVault);
        if (tokenAccountInfo.value?.data && 'parsed' in tokenAccountInfo.value.data) {
          const parsed = tokenAccountInfo.value.data.parsed;
          console.log("💰 USDC Balance:", parsed.info.tokenAmount.uiAmount);
          console.log("🔹 Mint:", parsed.info.mint);
          console.log("🔹 Owner:", parsed.info.owner);
        }
      } catch (e) {
        console.log("⚠️ Could not parse token account data");
      }
    } else {
      console.log("❌ USDC vault token account does not exist!");
    }
  } catch (error) {
    console.log("❌ Error checking USDC vault:", error);
  }
  
  console.log("\n🎯 Verification Summary:");
  console.log("The vault should be ready for deposits if all checks passed!");
}

// Run the verification
verifyVault()
  .then(() => {
    console.log("✅ Verification complete");
    process.exit(0);
  })
  .catch((error) => {
    console.error("❌ Verification failed:", error);
    process.exit(1);
  }); 