use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount};

// Import modules
pub mod constants;
pub mod state;
pub mod utils;
pub mod instructions;
pub mod errors;

use instructions::*;

// This should be replaced with the actual program ID during deployment
declare_id!("Eehx8tDgRctoJbTEdXRp85hCW55nH62g5Eiy7yAn7KDg");

/// The main vault program
#[program]
pub mod vault {
    use super::*;

    /// Initialize a new vault
    pub fn initialize(
        ctx: Context<Initialize>,
        emergency_owner: Pubkey,
        calvin_authority: Pubkey,
        staking_program_id: Pubkey,
        per_nft_cap: u64,
        jupiter_program_id: Pubkey,
    ) -> Result<()> {
        instructions::initialize(ctx, emergency_owner, calvin_authority, staking_program_id, per_nft_cap, jupiter_program_id)
    }

    /// Deposit USDC into the vault
    pub fn deposit(
        ctx: Context<Deposit>,
        amount: u64,
    ) -> Result<()> {
        instructions::deposit(ctx, amount)
    }

    /// Withdraw USDC from the vault
    pub fn withdraw(
        ctx: Context<Withdraw>,
        shares: u64,
    ) -> Result<()> {
        instructions::withdraw(ctx, shares)
    }

    /// Execute a trade using Jupiter
    pub fn trade(
        ctx: Context<Trade>,
        data: Vec<u8>,
    ) -> Result<()> {
        instructions::trade(ctx, data)
    }

    /// Liquidate a position to cover withdrawal liquidity needs
    pub fn liquidate_to_cover(
        ctx: Context<LiquidateToCover>,
        data: Vec<u8>,
    ) -> Result<()> {
        instructions::liquidate_to_cover(ctx, data)
    }

    /// Pause or unpause the vault
    pub fn set_pause_status(
        ctx: Context<SetPauseStatus>,
        paused: bool,
    ) -> Result<()> {
        instructions::set_pause_status(ctx, paused)
    }

    /// Update vault configuration
    pub fn update_config(
        ctx: Context<UpdateConfig>,
        new_treasury: Option<Pubkey>,
        new_jupiter_program_id: Option<Pubkey>,
        new_per_nft_cap: Option<u64>,
    ) -> Result<()> {
        instructions::update_config(ctx, new_treasury, new_jupiter_program_id, new_per_nft_cap)
    }

    /// Get user's vault share balance (CPI-callable from staking program)
    pub fn get_user_vault_shares(
        ctx: Context<GetUserVaultShares>,
    ) -> Result<u64> {
        instructions::get_user_vault_shares(ctx)
    }
}

/// Error codes for the vault program
#[error_code]
pub enum ErrorCode {
    #[msg("Arithmetic error")]
    ArithmeticError,

    #[msg("Not qualified for deposit - insufficient stake or NFTs")]
    NotQualifiedForDeposit,

    #[msg("Deposit exceeds cap for your tier")]
    DepositExceedsCap,

    #[msg("Insufficient shares for withdrawal")]
    InsufficientShares,

    #[msg("Insufficient liquidity for withdrawal")]
    InsufficientLiquidity,

    #[msg("Vault is paused")]
    VaultPaused,

    #[msg("Invalid price type from Pyth")]
    InvalidPriceType,

    #[msg("Price is not in trading status from Pyth")]
    PriceNotTrading,

    #[msg("Price is too stale from Pyth")]
    PriceTooStale,

    #[msg("Jupiter swap failed")]
    JupiterSwapFailed,

    #[msg("Only the vault owner can perform this action")]
    UnauthorizedOwner,

    #[msg("Only Calvin AI can perform this action")]
    UnauthorizedCalvin,

    #[msg("Insufficient accounts provided for Jupiter swap")]
    InsufficientAccounts,
} 