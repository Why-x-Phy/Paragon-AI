import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { PublicKey, Keypair } from "@solana/web3.js";
import { CalvinStaking } from "../target/types/calvin_staking";

// Load the staking program IDL
const stakingIdl = require("../target/idl/calvin_staking.json");

async function fixTierThresholds() {
  console.log("🔧 Fixing corrupted tier thresholds...");
  
  // Configure the client to use the mainnet cluster
  const connection = new anchor.web3.Connection("https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d");
  
  // Load admin wallet from Solana CLI config
  const fs = require('fs');
  const adminKeypairData = JSON.parse(fs.readFileSync('/home/ubuntu/.config/solana/id.json', 'utf8'));
  const adminKeypair = anchor.web3.Keypair.fromSecretKey(new Uint8Array(adminKeypairData));
  
  console.log("Admin pubkey:", adminKeypair.publicKey.toString());
  
  const wallet = new anchor.Wallet(adminKeypair);
  const provider = new anchor.AnchorProvider(connection, wallet, {});
  anchor.setProvider(provider);

  // Create program instance
  const stakingProgramId = new PublicKey("8kMj6gYFVUC3Ya6qwu3tyaZweyXUUuR8t8aCtA47aX7W");
  const stakingProgram = new Program(stakingIdl, provider) as Program<CalvinStaking>;
  
  // Derive stake config PDA
  const [stakeConfigPDA] = PublicKey.findProgramAddressSync(
    [Buffer.from("stake_config")],
    stakingProgramId
  );
  
  console.log("Stake Config PDA:", stakeConfigPDA.toString());
  
  // Get current config
  try {
    const currentConfig = await stakingProgram.account.stakeConfig.fetch(stakeConfigPDA);
    console.log("Current tier thresholds:", currentConfig.tierThresholds.map(t => t.toString()));
  } catch (e) {
    console.error("Failed to fetch current config:", e);
  }
  
  // Correct tier thresholds (in micro-CALVIN, 6 decimals)
  const correctTierThresholds: [anchor.BN, anchor.BN, anchor.BN, anchor.BN] = [
    new anchor.BN("10000000000000"), // 10M CALVIN - Vault Keeper
    new anchor.BN("2000000000000"),  // 2M CALVIN - Tier 2
    new anchor.BN("500000000000"),   // 500K CALVIN - Tier 3  
    new anchor.BN("0")               // 0 CALVIN - Default
  ];
  
  console.log("Setting correct tier thresholds:");
  console.log("  Vault Keeper (Tier 0):", (Number(correctTierThresholds[0]) / 1e6).toLocaleString(), "CALVIN");
  console.log("  Tier 2:", (Number(correctTierThresholds[1]) / 1e6).toLocaleString(), "CALVIN");
  console.log("  Tier 3:", (Number(correctTierThresholds[2]) / 1e6).toLocaleString(), "CALVIN");
  console.log("  Default:", (Number(correctTierThresholds[3]) / 1e6).toLocaleString(), "CALVIN");
  
  try {
    // Call update_config instruction
    const tx = await stakingProgram.methods
      .updateConfig(
        correctTierThresholds, // new_tier_thresholds
        null                   // new_vault_program_id (no change)
      )
      .accountsPartial({
        admin: adminKeypair.publicKey,
        stakeConfig: stakeConfigPDA,
      })
      .rpc();
      
    console.log("✅ Transaction successful!");
    console.log("Transaction signature:", tx);
    
    // Verify the fix
    const updatedConfig = await stakingProgram.account.stakeConfig.fetch(stakeConfigPDA);
    console.log("\n✅ Updated tier thresholds:");
    updatedConfig.tierThresholds.forEach((threshold, i) => {
      const tierNames = ["Vault Keeper", "Tier 2", "Tier 3", "Default"];
      console.log(`  ${tierNames[i]}: ${(Number(threshold) / 1e6).toLocaleString()} CALVIN`);
    });
    
    console.log("\n🎉 Tier thresholds fixed! Now users can stake/unstake properly.");
    
  } catch (error) {
    console.error("❌ Failed to update config:", error);
    throw error;
  }
}

// Run the fix
fixTierThresholds()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  }); 