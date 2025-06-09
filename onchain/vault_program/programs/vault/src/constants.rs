/// Constants for the vault program

// Fee constants (in basis points)
pub const DEPOSIT_FEE_BPS: u64 = 250; // 2.5% deposit fee
pub const PERFORMANCE_FEE_BPS: u64 = 750; // 7.5% performance fee
pub const BPS_DIVISOR: u64 = 10_000; // Basis points divisor (100%)

// Tier constants (these should match the staking program)
pub const VAULT_KEEPER_TIER: u8 = 0; // Unlimited deposits
pub const TIER_2: u8 = 1; // Medium cap
pub const TIER_3: u8 = 2; // Entry cap  
pub const DEFAULT_TIER: u8 = 3; // No access

// Tier deposit caps (in USDC with 6 decimals)
pub const TIER_2_MAX_DEPOSIT: u64 = 50_000_000_000; // 50K USDC
pub const TIER_3_MAX_DEPOSIT: u64 = 10_000_000_000; // 10K USDC

// Seed prefixes for PDAs
pub const VAULT_PDA_SEED: &[u8] = b"vault";
pub const SHARES_MINT_PDA_SEED: &[u8] = b"shares_mint";
pub const VAULT_AUTHORITY_PDA_SEED: &[u8] = b"vault_authority";
pub const USER_POSITION_PDA_SEED: &[u8] = b"user_position";

// Other constants
pub const LIQUIDITY_BUFFER_BPS: u64 = 1000; // 10% minimum USDC liquidity buffer
pub const MAX_PRICE_STALENESS_SECONDS: i64 = 60; // Max staleness for price oracle (60 seconds)
