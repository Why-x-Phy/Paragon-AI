import * as anchor from "@coral-xyz/anchor";
import { Connection, PublicKey, SystemProgram, Transaction, sendAndConfirmTransaction } from "@solana/web3.js";
import { TOKEN_PROGRAM_ID } from "@solana/spl-token";
import fs from 'fs';

// ✅ CORRECT Program IDs for devnet
const STAKING_PROGRAM_ID = new PublicKey("BMeQT4VD9X4RFYT8MAmofKJk14dFyFrBWqJJzTeNgGtW");
const VAULT_PROGRAM_ID = new PublicKey("7rky4NGhHtUREVJLKnAKwapDBmzCMbEno6VDcFZXyWxA");
const USDC_MINT = new PublicKey("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU");

async function resetVault() {
  console.log("🧹 Analyzing vault account state...");
  
  // Set up connection and authority
  const connection = new Connection("https://devnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d", "confirmed");
  
  // Load authority keypair
  const authorityPath = "./devnet-test.json";
  const authorityKeypair = anchor.web3.Keypair.fromSecretKey(
    new Uint8Array(JSON.parse(fs.readFileSync(authorityPath, "utf8")))
  );
  
  console.log("Authority:", authorityKeypair.publicKey.toBase58());
  console.log("Vault Program:", VAULT_PROGRAM_ID.toBase58());
  console.log("Staking Program:", STAKING_PROGRAM_ID.toBase58());
  
  // ✅ Calculate PDAs with CORRECT seeds
  const [vault] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault"), USDC_MINT.toBuffer()], // CORRECT: vault + usdc_mint
    VAULT_PROGRAM_ID
  );
  
  const [vaultConfig] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault-config"), USDC_MINT.toBuffer()], // CORRECT: vault-config + usdc_mint
    VAULT_PROGRAM_ID
  );
  
  const [stakeConfig] = PublicKey.findProgramAddressSync(
    [Buffer.from("stake_config")], // CORRECT: stake_config
    STAKING_PROGRAM_ID
  );
  
  console.log("\n📍 PDA Addresses:");
  console.log("Vault PDA:", vault.toBase58());
  console.log("Vault Config PDA:", vaultConfig.toBase58());
  console.log("Stake Config PDA:", stakeConfig.toBase58());
  
  // Check vault account state
  try {
    const vaultInfo = await connection.getAccountInfo(vault);
    if (vaultInfo) {
      console.log(`\n📋 Vault account exists:`);
      console.log(`   Data length: ${vaultInfo.data.length} bytes`);
      console.log(`   SOL balance: ${vaultInfo.lamports / 1e9} SOL`);
      console.log(`   Owner: ${vaultInfo.owner.toBase58()}`);
      
      // Check if it's owned by our vault program
      if (vaultInfo.owner.equals(VAULT_PROGRAM_ID)) {
        console.log("✅ Owned by vault program");
        
        // Try to deserialize to see if it's corrupted
        try {
          // We can't actually deserialize without the IDL, but we can check data length
          if (vaultInfo.data.length > 0) {
            console.log("⚠️ Account has data - may be corrupted from old deployment");
            console.log("💡 This account needs to be reinitialized");
          }
        } catch (error) {
          console.log("❌ Account data appears corrupted");
        }
      } else {
        console.log("❌ Owned by different program:", vaultInfo.owner.toBase58());
      }
    } else {
      console.log("\n✅ Vault account doesn't exist - ready for fresh initialization");
    }
  } catch (error) {
    console.log("\n❌ Could not fetch vault account info:", error.message);
  }
  
  // Check vault config account state
  try {
    const vaultConfigInfo = await connection.getAccountInfo(vaultConfig);
    if (vaultConfigInfo) {
      console.log(`\n📋 Vault Config account exists:`);
      console.log(`   Data length: ${vaultConfigInfo.data.length} bytes`);
      console.log(`   SOL balance: ${vaultConfigInfo.lamports / 1e9} SOL`);
      console.log(`   Owner: ${vaultConfigInfo.owner.toBase58()}`);
    } else {
      console.log("\n✅ Vault Config account doesn't exist - ready for fresh initialization");
    }
  } catch (error) {
    console.log("\n❌ Could not fetch vault config account info:", error.message);
  }
  
  // Check stake config account state
  try {
    const stakeConfigInfo = await connection.getAccountInfo(stakeConfig);
    if (stakeConfigInfo) {
      console.log(`\n📋 Stake Config account exists:`);
      console.log(`   Data length: ${stakeConfigInfo.data.length} bytes`);
      console.log(`   SOL balance: ${stakeConfigInfo.lamports / 1e9} SOL`);
      console.log(`   Owner: ${stakeConfigInfo.owner.toBase58()}`);
    } else {
      console.log("\n✅ Stake Config account doesn't exist - ready for fresh initialization");
    }
  } catch (error) {
    console.log("\n❌ Could not fetch stake config account info:", error.message);
  }
  
  console.log("\n🎯 RECOMMENDATIONS:");
  console.log("1. If accounts exist with data, they may have old structure");
  console.log("2. Run the initialize script - it should handle reinitialization");
  console.log("3. If initialization fails, accounts may need manual closure");
  console.log("\n▶️ Next step: npx ts-node scripts/initialize-devnet.ts");
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