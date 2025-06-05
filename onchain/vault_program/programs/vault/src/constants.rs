/// Constants for the vault program

// Fee constants (in basis points)
pub const DEPOSIT_FEE_BPS: u64 = 250; // 2.5% deposit fee
pub const PERFORMANCE_FEE_BPS: u64 = 750; // 7.5% performance fee
pub const BPS_DIVISOR: u64 = 10_000; // Basis points divisor (100%)

// Staking tiers
pub const WHALE_TIER_MIN_STAKE: u64 = 10_000_000; // 10M CALVIN tokens
pub const NFT_TIER_MIN_STAKE: u64 = 500_000; // 0.5M CALVIN tokens

// Seed prefixes for PDAs
pub const VAULT_PDA_SEED: &[u8] = b"vault";
pub const STAKER_PDA_SEED: &[u8] = b"staker";
pub const SHARES_MINT_PDA_SEED: &[u8] = b"shares_mint";
pub const VAULT_AUTHORITY_PDA_SEED: &[u8] = b"vault_authority";

// Other constants
pub const LIQUIDITY_BUFFER_BPS: u64 = 1000; // 10% minimum USDC liquidity buffer
pub const MAX_PRICE_STALENESS_SECONDS: i64 = 60; // Max staleness for price oracle (60 seconds)
