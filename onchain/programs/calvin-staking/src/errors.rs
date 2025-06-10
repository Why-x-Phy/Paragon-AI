use anchor_lang::prelude::*;

/// Custom error codes for the Calvin Staking Program
#[error_code]
pub enum StakingError {
    #[msg("Arithmetic error occurred")]
    ArithmeticError,

    #[msg("Cannot unstake CALVIN: user has vault shares that must be withdrawn first")]
    MustWithdrawVaultSharesFirst,

    #[msg("Staking is currently paused")]
    StakingPaused,

    #[msg("Insufficient staked amount for this operation")]
    InsufficientStakedAmount,

    #[msg("Invalid tier threshold configuration")]
    InvalidTierThresholds,

    #[msg("Unauthorized: only admin can perform this action")]
    UnauthorizedAdmin,

    #[msg("Invalid vault program ID")]
    InvalidVaultProgramId,

    #[msg("Cannot stake zero tokens")]
    ZeroStakeAmount,

    #[msg("Cannot unstake zero tokens")]
    ZeroUnstakeAmount,

    #[msg("User has no staked tokens")]
    NoStakedTokens,

    #[msg("Invalid CALVIN token mint")]
    InvalidCalvinMint,

    #[msg("Vault Pass token transfer is not allowed (non-transferable)")]
    VaultPassNotTransferable,

    #[msg("CPI call to vault program failed")]
    VaultCpiCallFailed,

    #[msg("Invalid tier calculation")]
    InvalidTierCalculation,

    #[msg("Account initialization failed")]
    AccountInitializationFailed,
} 