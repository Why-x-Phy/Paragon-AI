use anchor_lang::prelude::*;

/// Custom error codes for the Calvin Vault Program
#[error_code]
pub enum VaultError {
    #[msg("Arithmetic error occurred")]
    ArithmeticError,

    #[msg("Deposit exceeds tier cap limit")]
    DepositExceedsCap,

    #[msg("User not qualified for deposit (insufficient tier)")]
    NotQualifiedForDeposit,

    #[msg("Invalid price type from oracle")]
    InvalidPriceType,

    #[msg("Insufficient shares for withdrawal")]
    InsufficientShares,

    #[msg("Jupiter swap operation failed")]
    JupiterSwapFailed,

    #[msg("Price oracle not trading")]
    PriceNotTrading,

    #[msg("Price data too stale")]
    PriceTooStale,

    #[msg("Vault is currently paused")]
    VaultPaused,

    #[msg("Unauthorized: only emergency owner can perform this action")]
    UnauthorizedOwner,

    #[msg("Unauthorized: only Calvin trading authority can execute trades")]
    UnauthorizedCalvin,

    #[msg("Insufficient liquidity in vault for withdrawal")]
    InsufficientLiquidity,

    #[msg("Invalid tier configuration")]
    InvalidTierConfiguration,

    #[msg("Invalid staking program provided")]
    InvalidStakingProgram,

    #[msg("CPI call to staking program failed")]
    StakingCpiCallFailed,

    #[msg("Invalid vault configuration")]
    InvalidVaultConfiguration,

    #[msg("Token account is frozen (non-transferable)")]
    TokenAccountFrozen,

    #[msg("Invalid mint authority")]
    InvalidMintAuthority,

    #[msg("Account initialization failed")]
    AccountInitializationFailed,

    #[msg("Invalid oracle account provided")]
    InvalidOracleAccount,

    #[msg("Oracle not found for token")]
    OracleNotFound,

    #[msg("Stale oracle price data")]
    StaleOraclePrice,

    #[msg("Invalid price data from oracle")]
    InvalidPriceData,
} 