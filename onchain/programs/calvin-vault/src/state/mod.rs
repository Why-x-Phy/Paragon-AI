use anchor_lang::prelude::*;
use anchor_spl::token::TokenAccount;

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
    
    /// Reserved space for future upgrades
    pub reserved: [u8; 64],
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
        64; // reserved
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
    pub amount: u64,
    pub shares: u64,
    pub fee: u64,
}

/// Event emitted when a withdrawal is made
#[event]
pub struct Withdraw {
    pub user: Pubkey,
    pub amount: u64,
    pub shares: u64,
}

/// Event emitted when a trade is executed
#[event]
pub struct Trade {
    pub vault: Pubkey,
    pub source_mint: Pubkey,
    pub destination_mint: Pubkey,
    pub amount_in: u64,
    pub amount_out: u64,
}

/// Event emitted when a position is liquidated to cover withdrawals
#[event]
pub struct Liquidate {
    pub vault: Pubkey,
    pub token_mint: Pubkey,
    pub amount: u64,
    pub usdc_received: u64,
}
