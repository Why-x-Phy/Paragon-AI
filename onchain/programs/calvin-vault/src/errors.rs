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

    #[msg("Invalid oracle accounts - expected groups of 3")]
    InvalidOracleAccounts,

    #[msg("Math operation overflow")]
    MathOverflow,

    #[msg("Insufficient accounts provided")]
    InsufficientAccounts,

    #[msg("Too many tokens - maximum 25 supported")]
    TooManyTokens,

    #[msg("Reentrancy detected - operation already in progress")]
    ReentrancyDetected,

    #[msg("Insufficient signatures for emergency action")]
    InsufficientSignatures,

    #[msg("Emergency operation has expired")]
    OperationExpired,

    #[msg("Emergency operation not found")]
    OperationNotFound,

    #[msg("Unsupported operation type")]
    UnsupportedOperation,

    #[msg("Operation already signed by this owner")]
    AlreadySigned,

    #[msg("Maximum emergency owners reached (5)")]
    TooManyEmergencyOwners,

    #[msg("Cannot remove the last emergency owner")]
    CannotRemoveLastOwner,

    #[msg("Emergency owner not found")]
    EmergencyOwnerNotFound,

    #[msg("Emergency owner already exists")]
    EmergencyOwnerAlreadyExists,

    #[msg("Owner already exists in emergency owners list")]
    OwnerAlreadyExists,

    #[msg("Too many owners - maximum 3 allowed")]
    TooManyOwners,

    #[msg("Too many signatures collected")]
    TooManySignatures,

    #[msg("Too many pending operations - maximum 1 allowed")]
    TooManyPendingOperations,

    #[msg("All oracles failed to provide valid price")]
    AllOraclesFailed,

    #[msg("Oracle price deviation too high between sources")]
    OracleDeviationTooHigh,

    #[msg("Invalid Switchboard feed account")]
    InvalidSwitchboardFeed,

    #[msg("Switchboard feed data is stale")]
    SwitchboardFeedStale,

    #[msg("Switchboard program ownership validation failed")]
    InvalidSwitchboardProgram,

    #[msg("Deposit amount is zero")]
    ZeroDeposit,

    #[msg("Deposit amount exceeds maximum allowed")]
    DepositTooLarge,

    #[msg("Vault NAV exceeds maximum allowed")]
    NavTooHigh,

    #[msg("Share price is out of safe bounds")]
    SharePriceOutOfBounds,

    #[msg("Invalid amount - must be positive")]
    InvalidAmount,

    #[msg("Calculation result exceeds safe limits")]
    CalculationOverflow,

    #[msg("Token is not whitelisted for trading")]
    TokenNotWhitelisted,

    #[msg("Token allocation exceeds maximum allowed percentage")]
    TokenAllocationExceeded,

    #[msg("Maximum whitelisted tokens reached")]
    MaxWhitelistedTokensReached,

    #[msg("Token is already whitelisted")]
    TokenAlreadyWhitelisted,

    #[msg("Token whitelist entry not found")]
    TokenWhitelistNotFound,

    #[msg("Invalid token symbol - must be 1-10 characters")]
    InvalidTokenSymbol,

    #[msg("Invalid allocation percentage - must be 1-10000 basis points")]
    InvalidAllocationPercentage,

    #[msg("Trading operations are paused")]
    TradingPaused,

    #[msg("Deposit operations are paused")]
    DepositsPaused,

    #[msg("Withdrawal operations are paused")]
    WithdrawalsPaused,

    #[msg("All vault operations are paused")]
    AllOperationsPaused,

    #[msg("CPI call rate limit exceeded")]
    CpiRateLimitExceeded,

    #[msg("CPI call tracking failed")]
    CpiTrackingFailed,

    #[msg("Invalid required signatures count")]
    InvalidRequiredSignatures,

    #[msg("Invalid operation parameters")]
    InvalidOperationParams,

    #[msg("Operation parameters too large")]
    OperationParamsTooLarge,

    #[msg("Invalid vault authority")]
    InvalidVaultAuthority,

    #[msg("Invalid token whitelist account")]
    InvalidTokenWhitelistAccount,

    #[msg("Invalid pending operation account")]
    InvalidPendingOperationAccount,

    #[msg("Security constraint violation")]
    SecurityConstraintViolation,

    #[msg("Invalid security configuration")]
    InvalidSecurityConfiguration,

    #[msg("Security feature not enabled")]
    SecurityFeatureNotEnabled,
}

// Re-export for easier use in other modules
pub use VaultError as ErrorCode; 