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
pub const TIER_2_MAX_DEPOSIT: u64 = 5_000_000_000; // 5K USDC
pub const TIER_3_MAX_DEPOSIT: u64 = 1_000_000_000; // 1K USDC

// Seed prefixes for PDAs
pub const VAULT_PDA_SEED: &[u8] = b"vault";
pub const SHARES_MINT_PDA_SEED: &[u8] = b"shares_mint";
pub const VAULT_AUTHORITY_PDA_SEED: &[u8] = b"vault_authority";
pub const USER_POSITION_PDA_SEED: &[u8] = b"user_position";
pub const TOKEN_WHITELIST_PDA_SEED: &[u8] = b"token_whitelist";
pub const PENDING_OPERATION_PDA_SEED: &[u8] = b"pending_operation";

// Oracle and liquidity constants
pub const LIQUIDITY_BUFFER_BPS: u64 = 1000; // 10% minimum USDC liquidity buffer
pub const MAX_PRICE_STALENESS_SECONDS: i64 = 60; // Max staleness for price oracle (60 seconds)

// 🔒 ENHANCED SECURITY CONSTANTS

// Arithmetic Safety Limits
pub const MAX_DEPOSIT_AMOUNT: u64 = 1_000_000_000_000; // 1M USDC max single deposit
pub const MAX_TOTAL_NAV: u64 = 100_000_000_000_000;   // 100M USDC max total NAV
pub const MIN_SHARE_PRICE: u64 = 0;                   // No minimum share price restriction
pub const MAX_SHARE_PRICE: u64 = 1_000_000_000;       // 1,000 USDC maximum share price (allows for 1000x returns!)
pub const MAX_ALLOCATION_BPS: u16 = 10_000;           // 100% maximum allocation

// Multisig Configuration
pub const MAX_EMERGENCY_OWNERS: usize = 5;            // Maximum emergency owners
pub const MIN_REQUIRED_SIGNATURES: u8 = 1;            // Minimum required signatures
pub const MAX_REQUIRED_SIGNATURES: u8 = 5;            // Maximum required signatures
pub const OPERATION_EXPIRY_SECONDS: i64 = 7 * 24 * 60 * 60; // 7 days operation expiry
pub const MAX_OPERATION_PARAMS_LEN: usize = 128;      // Maximum operation parameters length

// Token Whitelist Configuration
pub const MAX_WHITELISTED_TOKENS: usize = 25;         // Maximum whitelisted tokens
pub const MAX_TOKEN_SYMBOL_LEN: usize = 10;           // Maximum token symbol length
pub const MIN_ALLOCATION_BPS: u16 = 100;              // 1% minimum allocation
pub const DEFAULT_MAX_ALLOCATION_BPS: u16 = 2000;     // 20% default max allocation

// Oracle Security Configuration
pub const MAX_ORACLE_DEVIATION_BPS: u64 = 500;       // 5% maximum price deviation between oracles
pub const SWITCHBOARD_STALENESS_SECONDS: i64 = 300;   // 5 minutes max staleness for Switchboard feeds
pub const ORACLE_FALLBACK_TIMEOUT_SECONDS: i64 = 10;  // 10 seconds timeout for oracle fallback

// CPI Rate Limiting
pub const MAX_CPI_CALLS_PER_HOUR: u32 = 200;         // Maximum CPI calls per hour
pub const CPI_RATE_LIMIT_WINDOW_SECONDS: i64 = 3600; // 1 hour rate limit window

// Switchboard Program IDs
pub const SWITCHBOARD_MAINNET_PROGRAM_ID: &str = "SBondMDrcV3K4kxZR1HNVT7osZxAHVHgYXL5Ze1oMUv";
pub const SWITCHBOARD_DEVNET_PROGRAM_ID: &str = "Aio4gaXjXzJNVLtzwtNVmSqGKpANtXhybbkhtAC94ji2";

// Security Event Configuration
pub const MAX_SECURITY_EVENT_DETAILS_LEN: usize = 256; // Maximum security event details length

// Emergency Operation Types (for parameter validation)
pub const EMERGENCY_PAUSE_PARAMS_LEN: usize = 1;      // Boolean pause flag
pub const ADD_OWNER_PARAMS_LEN: usize = 33;           // Pubkey + u8 required signatures
pub const REMOVE_OWNER_PARAMS_LEN: usize = 32;        // Pubkey only
pub const TOKEN_WHITELIST_PARAMS_LEN: usize = 77;     // Mint + Oracle + Allocation + Symbol


