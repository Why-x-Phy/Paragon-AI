import { PublicKey } from "@solana/web3.js";

/**
 * 🔧 MAINNET CONFIGURATION 🔧
 * CRITICAL: Set these addresses correctly before initialization
 */
export const MAINNET_CONFIG = {
  // 🤖 Calvin AI Authority - The wallet that executes trades
  // This should be your backend trading system's wallet
  CALVIN_AUTHORITY: new PublicKey("REPLACE_WITH_CALVIN_AI_WALLET_ADDRESS"),
  
  // 💰 Treasury - Where fees are collected
  // This should be your fee collection wallet
  TREASURY: new PublicKey("REPLACE_WITH_TREASURY_WALLET_ADDRESS"),
  
  // 🥩 Tier thresholds for staking (in CALVIN tokens with 6 decimals)
  TIER_THRESHOLDS: [
    10_000_000_000_000, // 10M CALVIN - Vault Keeper (unlimited deposits)
    2_000_000_000_000,  // 2M CALVIN - Tier 2 (5K USDC cap)
    500_000_000_000,    // 500K CALVIN - Tier 3 (1K USDC cap)
    0,                  // 0 CALVIN - Default (no vault access)
  ],
  
  // 💵 Per NFT cap for NFT holders (5K USDC)
  PER_NFT_CAP: 500_000_000, // 500 USDC with 6 decimals
};

/**
 * Validates that all required addresses are set
 */
export function validateConfig() {
  const errors: string[] = [];
  
  if (MAINNET_CONFIG.CALVIN_AUTHORITY.toBase58() === "REPLACE_WITH_CALVIN_AI_WALLET_ADDRESS") {
    errors.push("❌ CALVIN_AUTHORITY not set! Replace with actual Calvin AI trading wallet address");
  }
  
  if (MAINNET_CONFIG.TREASURY.toBase58() === "REPLACE_WITH_TREASURY_WALLET_ADDRESS") {
    errors.push("❌ TREASURY not set! Replace with actual treasury wallet address");
  }
  
  if (errors.length > 0) {
    console.error("🚨 CONFIGURATION ERRORS:");
    errors.forEach(error => console.error(error));
    console.error("\n💡 Edit onchain/scripts/mainnet-config.ts to fix these issues");
    return false;
  }
  
  console.log("✅ Configuration validated successfully");
  return true;
}

/**
 * Display current configuration for verification
 */
export function displayConfig() {
  console.log("🔧 CURRENT MAINNET CONFIGURATION:");
  console.log(`  🤖 Calvin AI Authority: ${MAINNET_CONFIG.CALVIN_AUTHORITY.toBase58()}`);
  console.log(`  💰 Treasury: ${MAINNET_CONFIG.TREASURY.toBase58()}`);
  console.log(`  🥩 Tier Thresholds: ${MAINNET_CONFIG.TIER_THRESHOLDS.map(t => `${t / 1_000_000} CALVIN`).join(', ')}`);
  console.log(`  💵 Per NFT Cap: ${MAINNET_CONFIG.PER_NFT_CAP / 1_000_000} USDC`);
} 