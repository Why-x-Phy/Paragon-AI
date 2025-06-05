use anchor_lang::prelude::*;

/// Global configuration for the staking program
#[account]
pub struct StakeConfig {
    /// Program admin authority
    pub admin_authority: Pubkey,
    
    /// Vault program ID for CPI calls
    pub vault_program_id: Pubkey,
    
    /// Tier thresholds [Vault Keeper, Tier-2, Tier-3, Default]
    pub tier_thresholds: [u64; 4],
    
    /// Whether staking is paused
    pub paused: bool,
    
    /// CALVIN token mint address
    pub calvin_mint: Pubkey,
    
    /// Bump seed for this account
    pub bump: u8,
    
    /// Reserved space for future upgrades
    pub reserved: [u8; 128],
}

impl StakeConfig {
    pub const SIZE: usize = 8 + // discriminator
        32 + // admin_authority
        32 + // vault_program_id
        32 + // tier_thresholds (4 * 8)
        1 + // paused
        32 + // calvin_mint
        1 + // bump
        128; // reserved
}

/// Vault that holds all staked CALVIN tokens
#[account]
pub struct StakeVault {
    /// Total CALVIN tokens staked across all users
    pub total_staked: u64,
    
    /// Total Vault Pass tokens minted
    pub total_vault_passes: u64,
    
    /// CALVIN token mint
    pub calvin_mint: Pubkey,
    
    /// Vault Pass mint for this staking pool
    pub vault_pass_mint: Pubkey,
    
    /// Bump seed for this account
    pub bump: u8,
    
    /// Reserved space for future upgrades
    pub reserved: [u8; 64],
}

impl StakeVault {
    pub const SIZE: usize = 8 + // discriminator
        8 + // total_staked
        8 + // total_vault_passes
        32 + // calvin_mint
        32 + // vault_pass_mint
        1 + // bump
        64; // reserved
}

/// Individual user's staking information
#[account]
pub struct UserStake {
    /// User's wallet address
    pub user_authority: Pubkey,
    
    /// Amount of CALVIN tokens staked by this user
    pub total_staked: u64,
    
    /// User's Vault Pass mint (one per user)
    pub vault_pass_mint: Pubkey,
    
    /// Current tier (0=Vault Keeper, 1=Tier-2, 2=Tier-3, 3=Default)
    pub tier: u8,
    
    /// Timestamp of last stake action
    pub last_stake_timestamp: i64,
    
    /// Bump seed for this account
    pub bump: u8,
    
    /// Reserved space for future upgrades
    pub reserved: [u8; 32],
}

impl UserStake {
    pub const SIZE: usize = 8 + // discriminator
        32 + // user_authority
        8 + // total_staked
        32 + // vault_pass_mint
        1 + // tier
        8 + // last_stake_timestamp
        1 + // bump
        32; // reserved
}

/// Events emitted by the staking program

/// Emitted when CALVIN tokens are staked
#[event]
pub struct StakeEvent {
    pub user: Pubkey,
    pub amount: u64,
    pub new_total: u64,
    pub tier: u8,
    pub vault_pass_mint: Pubkey,
}

/// Emitted when CALVIN tokens are unstaked
#[event]
pub struct UnstakeEvent {
    pub user: Pubkey,
    pub amount: u64,
    pub remaining_total: u64,
    pub new_tier: u8,
}

/// Emitted when staking is paused/unpaused
#[event]
pub struct PauseEvent {
    pub paused: bool,
    pub timestamp: i64,
}

/// Emitted when configuration is updated
#[event]
pub struct ConfigUpdateEvent {
    pub admin: Pubkey,
    pub new_tier_thresholds: Option<[u64; 4]>,
    pub new_vault_program_id: Option<Pubkey>,
} 