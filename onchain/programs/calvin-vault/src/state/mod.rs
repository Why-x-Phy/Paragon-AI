use anchor_lang::prelude::*;

/// The main vault account
#[account]
pub struct Vault {
    /// Emergency owner (project founder) - can pause, update config, emergency controls
    pub emergency_owner: Pubkey,
    
    /// Calvin AI trading authority - only entity that can execute trades
    pub calvin_authority: Pubkey,
    
    /// Staking program ID for CPI calls
    pub staking_program_id: Pubkey,
    
    /// The mint for share tokens
    pub shares_mint: Pubkey,
    
    /// The mint for USDC
    pub usdc_mint: Pubkey,
    
    /// The vault's USDC token account
    pub usdc_vault: Pubkey,
    
    /// The PDA that has authority over the vault's token accounts
    pub vault_authority: Pubkey,
    
    /// The vault's bump seed
    pub vault_bump: u8,
    
    /// The shares mint's bump seed
    pub shares_mint_bump: u8,
    
    /// The vault authority's bump seed
    pub authority_bump: u8,
    
    /// The mint for CALVIN tokens
    pub calvin_mint: Pubkey,
    
    /// The treasury address to receive fees
    pub treasury: Pubkey,
    
    /// The maximum amount of USDC per NFT for NFT tier stakers
    pub per_nft_cap: u64,
    
    /// The high-water mark of the vault's NAV (for performance fee calculation)
    pub high_water_mark_nav: u64,
    
    /// The total number of share tokens minted
    pub total_shares: u64,
    
    /// Whether the vault is paused (no deposits or trades)
    pub paused: bool,
    
    /// The Jupiter router program ID for swaps
    pub jupiter_program_id: Pubkey,
    
    /// Reentrancy protection flag
    pub reentrancy_guard: bool,
    
    /// Granular pause controls
    pub trading_paused: bool,     // Calvin AI trades only
    pub deposits_paused: bool,    // New user deposits
    pub withdrawals_paused: bool, // User withdrawals (extreme emergency only)
    
    /// Emergency multisig support (fixed size for efficiency)
    pub emergency_owners: [Pubkey; 2],  // Max 2 emergency owners (reduced for stack size)
    pub emergency_owners_count: u8,     // Actual number of owners (0-2)
    pub required_signatures: u8,        // Required signatures for emergency actions
    
    /// Next operation ID for multisig operations
    pub next_operation_id: u64,
    
    /// 🔒 CPI Rate Limiting (fixed size for efficiency)
    pub cpi_call_counts: [CpiCallTracker; 2], // Track up to 2 programs (Jupiter, Staking)
    pub cpi_trackers_count: u8,               // Actual number of trackers (0-2)
    
    // Note: Pending operations moved to separate accounts for stack size optimization
}

impl Vault {
    pub const SIZE: usize = 8 + // discriminator
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
        // Security enhancement fields
        1 + // reentrancy_guard
        1 + // trading_paused
        1 + // deposits_paused
        1 + // withdrawals_paused
        (32 * 2) + // emergency_owners (fixed array)
        1 + // emergency_owners_count
        1 + // required_signatures
        8 + // next_operation_id
        // 🔒 CPI Rate Limiting fields
        (76 * 2) + // cpi_call_counts (CpiCallTracker * 2)
        1; // cpi_trackers_count
        // 0; // reserved (removed for stack size)
}

/// Token whitelist entry (separate account for space efficiency)
#[account]
pub struct TokenWhitelist {
    /// The vault this whitelist entry belongs to
    pub vault: Pubkey,
    
    /// Token mint address
    pub mint: Pubkey,
    
    /// Token symbol (max 10 characters for efficiency)
    pub symbol: [u8; 10],
    
    /// Primary Pyth oracle
    pub pyth_oracle: Pubkey,
    
    /// Fallback Switchboard oracle (optional)
    pub switchboard_oracle: Option<Pubkey>,
    
    /// Maximum allocation in basis points (e.g., 2000 = 20%)
    pub max_allocation_bps: u16,
    
    /// Whether this token is active for trading
    pub is_active: bool,
    
    /// When this token was added to whitelist
    pub added_timestamp: i64,
    
    /// Bump seed for this account
    pub bump: u8,
    
    /// Reserved space
    pub reserved: [u8; 32],
}

impl TokenWhitelist {
    pub const SIZE: usize = 8 + // discriminator
        32 + // vault
        32 + // mint
        10 + // symbol (fixed size)
        32 + // pyth_oracle
        (1 + 32) + // switchboard_oracle (Option<Pubkey>)
        2 + // max_allocation_bps
        1 + // is_active
        8 + // added_timestamp
        1 + // bump
        32; // reserved
}

/// User's vault position tracking
#[account]
pub struct UserPosition {
    /// The user this position belongs to
    pub user_authority: Pubkey,
    
    /// The vault this position is associated with
    pub vault: Pubkey,
    
    /// Total USDC deposits made by this user (for tier cap calculations)
    pub total_deposits_usdc: u64,
    
    /// Timestamp of last deposit
    pub last_deposit_timestamp: i64,
    
    /// Bump seed for this account
    pub bump: u8,
    
    /// Reserved space for future upgrades
    pub reserved: [u8; 64],
}

impl UserPosition {
    pub const SIZE: usize = 8 + // discriminator
        32 + // user_authority
        32 + // vault
        8 + // total_deposits_usdc
        8 + // last_deposit_timestamp
        1 + // bump
        64; // reserved
}

/// Simplified pending operation data (stored within Vault account)
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, Copy)]
pub struct PendingOperationData {
    /// Unique operation ID
    pub operation_id: u64,
    
    /// Type of emergency operation
    pub operation_type: OperationType,
    
    /// Signatures collected so far (fixed size for efficiency)
    pub signatures: [Pubkey; 3],
    pub signatures_count: u8,
    
    /// Who proposed this operation
    pub proposer: Pubkey,
    
    /// When this operation was created
    pub created_at: i64,
    
    /// When this operation expires (7 days)
    pub expires_at: i64,
    
    /// Simple parameters (for basic operations)
    pub param_u64: u64,
    pub param_pubkey: Pubkey,
}

/// Pending emergency operation for multisig approval (separate account - not used currently)
#[account]
pub struct PendingOperation {
    /// Unique operation ID
    pub operation_id: u64,
    
    /// Type of emergency operation
    pub operation_type: OperationType,
    
    /// Signatures collected so far (fixed size for efficiency)
    pub signatures: [Pubkey; 5],
    pub signatures_count: u8,
    
    /// Who proposed this operation
    pub proposer: Pubkey,
    
    /// When this operation was created
    pub created_at: i64,
    
    /// When this operation expires (7 days)
    pub expires_at: i64,
    
    /// Serialized parameters for the operation (fixed size)
    pub params: [u8; 128],
    pub params_len: u8,
    
    /// Associated vault
    pub vault: Pubkey,
    
    /// Bump seed
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, Copy)]
pub enum OperationType {
    PauseTrading,
    PauseDeposits,
    PauseWithdrawals,
    PauseAll,
    UnpauseTrading,
    UnpauseDeposits,
    UnpauseWithdrawals,
    UnpauseAll,
    UpdateConfig,
    AddEmergencyOwner,
    RemoveEmergencyOwner,
    AddWhitelistedToken,
    RemoveWhitelistedToken,
    UpdateWhitelistedToken,
}

impl PendingOperation {
    pub const SIZE: usize = 8 + // discriminator
        8 + // operation_id
        (1 + 32) + // operation_type (enum + largest variant)
        (32 * 5) + // signatures (fixed array)
        1 + // signatures_count
        32 + // proposer
        8 + // created_at
        8 + // expires_at
        128 + // params (fixed size)
        1 + // params_len
        32 + // vault
        1; // bump
}

/// Event emitted when the vault needs liquidity
#[event]
pub struct NeedLiquidity {
    pub vault: Pubkey,
    pub required_amount: u64,
}

/// Event emitted when a deposit is made
#[event]
pub struct Deposit {
    pub user: Pubkey,
    pub vault: Pubkey,
    pub amount: u64,
    pub shares: u64,
    pub fee: u64,
    pub user_tier: u8,
    pub share_price: u64,
    pub timestamp: i64,
}

/// Event emitted when a withdrawal is made
#[event]
pub struct Withdraw {
    pub user: Pubkey,
    pub vault: Pubkey,
    pub amount: u64,
    pub shares: u64,
    pub timestamp: i64,
}

/// Event emitted when a trade is executed
#[event]
pub struct Trade {
    pub vault: Pubkey,
    pub source_mint: Pubkey,
    pub destination_mint: Pubkey,
    pub amount_in: u64,
    pub amount_out: u64,
    pub timestamp: i64,
    pub calvin_authority: Pubkey,
}

/// Event emitted when a position is liquidated to cover withdrawals
#[event]
pub struct Liquidate {
    pub vault: Pubkey,
    pub token_mint: Pubkey,
    pub amount: u64,
    pub usdc_received: u64,
    pub timestamp: i64,
}

/// 🔒 SECURITY EVENTS
#[event]
pub struct SecurityEvent {
    pub event_type: SecurityEventType,
    pub severity: SecuritySeverity,
    pub vault: Pubkey,
    pub details: String,
    pub timestamp: i64,
}

#[derive(AnchorSerialize, AnchorDeserialize)]
pub enum SecurityEventType {
    ReentrancyAttempt,
    UnauthorizedAccess,
    OracleFallbackTriggered,
    RateLimitExceeded,
    EmergencyActionProposed,
    EmergencyActionApproved,
    EmergencyActionExecuted,
    EmergencyOwnerAdded,
    TradingPaused,
    DepositsPaused,
    WithdrawalsPaused,
    AllOperationsPaused,
    TokenWhitelistViolation,
    ArithmeticSafetyViolation,
}

#[derive(AnchorSerialize, AnchorDeserialize)]
pub enum SecuritySeverity {
    Low,
    Medium,
    High,
    Critical,
}

/// 🔒 CPI Call Rate Limiting Tracker
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, Copy)]
pub struct CpiCallTracker {
    /// Program ID being tracked
    pub program_id: Pubkey,
    
    /// Number of calls in current hour
    pub calls_per_hour: u32,
    
    /// Timestamp of last reset (start of current hour)
    pub last_reset: i64,
    
    /// Maximum allowed calls per hour (default: 200 for headroom)
    pub max_calls_per_hour: u32,
}

/// 🔒 TOKEN WHITELIST EVENTS
#[event]
pub struct TokenWhitelistEvent {
    pub vault: Pubkey,
    pub token_mint: Pubkey,
    pub action: WhitelistAction,
    pub symbol: String,
    pub pyth_oracle: Pubkey,
    pub switchboard_oracle: Option<Pubkey>,
    pub max_allocation_bps: u16,
    pub timestamp: i64,
    pub authority: Pubkey,
}

/// 🔒 EMERGENCY ACTION EVENTS
#[event]
pub struct EmergencyActionEvent {
    pub vault: Pubkey,
    pub operation_id: u64,
    pub action: EmergencyAction,
    pub operation_type: OperationType,
    pub authority: Pubkey,
    pub signatures_count: u8,
    pub required_signatures: u8,
    pub timestamp: i64,
}

/// 🔒 WHITELIST ACTION TYPES
#[derive(AnchorSerialize, AnchorDeserialize)]
pub enum WhitelistAction {
    Added,
    Removed,
    Updated,
}

/// 🔒 EMERGENCY ACTION TYPES  
#[derive(AnchorSerialize, AnchorDeserialize)]
pub enum EmergencyAction {
    Proposed,
    Approved,
    Executed,
    Expired,
}
