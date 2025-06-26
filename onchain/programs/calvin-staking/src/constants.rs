/// Constants for the Calvin Staking Program

// Default tier thresholds (in CALVIN tokens with 6 decimals)
pub const VAULT_KEEPER_MIN_STAKE: u64 = 10_000_000_000_000; // 10M CALVIN tokens
pub const TIER_2_MIN_STAKE: u64 = 2_000_000_000_000;       // 2M CALVIN tokens  
pub const TIER_3_MIN_STAKE: u64 = 500_000_000_000;         // 500K CALVIN tokens
pub const DEFAULT_TIER_MIN_STAKE: u64 = 0;                 // 0 CALVIN tokens

// Default tier thresholds array
pub const DEFAULT_TIER_THRESHOLDS: [u64; 4] = [
    VAULT_KEEPER_MIN_STAKE,
    TIER_2_MIN_STAKE,
    TIER_3_MIN_STAKE,
    DEFAULT_TIER_MIN_STAKE,
];

// Tier indices
pub const VAULT_KEEPER_TIER: u8 = 0;
pub const TIER_2: u8 = 1;
pub const TIER_3: u8 = 2;
pub const DEFAULT_TIER: u8 = 3;

// PDA seed prefixes
pub const STAKE_CONFIG_SEED: &[u8] = b"stake_config";
pub const STAKE_VAULT_SEED: &[u8] = b"stake_vault";
pub const USER_STAKE_SEED: &[u8] = b"user_stake";
pub const VAULT_PASS_MINT_SEED: &[u8] = b"vault_pass_mint";

// CALVIN token details
pub const CALVIN_TOKEN_DECIMALS: u8 = 6;
pub const CALVIN_TOKEN_ADDRESS: &str = "229vWzBTiUNdraYpVtSH9usTwwVxcyPDbBWf1zEPpump";

// Vault Pass token details
pub const VAULT_PASS_DECIMALS: u8 = 0; // Non-divisible tokens 