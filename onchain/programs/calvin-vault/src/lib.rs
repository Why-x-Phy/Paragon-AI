use anchor_lang::prelude::*;
// Removed unused token imports - we use them in specific instruction files

// Import modules
pub mod constants;
pub mod state;
pub mod utils;
pub mod instructions;
pub mod errors;
pub mod oracle_config;

use instructions::*;
use errors::ErrorCode;

// Program ID will be set during deployment
declare_id!("Evdjoh1AHQb6Ls1n7Td7buAiDA5ty7Ec8NCYt8eWEXFp");

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

    /// Initialize a token account for trading (called after vault init)
    pub fn initialize_token_accounts(
        ctx: Context<InitializeTokenAccounts>,
    ) -> Result<()> {
        instructions::initialize_token_accounts(ctx)
    }

    // 🔒 NEW SECURITY INSTRUCTIONS

    /// Add a token to the whitelist (emergency owners only)
    pub fn add_whitelisted_token(
        ctx: Context<AddWhitelistedToken>,
        mint: Pubkey,
        symbol: String,
        pyth_oracle: Pubkey,
        switchboard_oracle: Option<Pubkey>,
        max_allocation_bps: u16,
    ) -> Result<()> {
        instructions::add_whitelisted_token(ctx, mint, symbol, pyth_oracle, switchboard_oracle, max_allocation_bps)
    }

    /// Remove a token from the whitelist (emergency owners only)
    pub fn remove_whitelisted_token(
        ctx: Context<RemoveWhitelistedToken>,
        mint: Pubkey,
    ) -> Result<()> {
        instructions::remove_whitelisted_token(ctx, mint)
    }

    /// Add an emergency owner for multisig (current owners only)
    pub fn add_emergency_owner(
        ctx: Context<AddEmergencyOwner>,
        new_owner: Pubkey,
        new_required_signatures: u8,
    ) -> Result<()> {
        instructions::add_emergency_owner(ctx, new_owner, new_required_signatures)
    }

    /// Propose an emergency action (emergency owners only)
    pub fn propose_emergency_action(
        ctx: Context<ProposeEmergencyAction>,
        operation_type: state::OperationType,
        params: Vec<u8>,
    ) -> Result<()> {
        instructions::propose_emergency_action(ctx, operation_type, params)
    }

    /// Approve an emergency action (emergency owners only)
    pub fn approve_emergency_action(
        ctx: Context<ApproveEmergencyAction>,
        operation_id: u64,
    ) -> Result<()> {
        instructions::approve_emergency_action(ctx, operation_id)
    }

    /// Execute an approved emergency action (anyone can execute once threshold reached)
    pub fn execute_emergency_action(
        ctx: Context<ExecuteEmergencyAction>,
        operation_id: u64,
    ) -> Result<()> {
        instructions::execute_emergency_action(ctx, operation_id)
    }

    /// Enhanced pause controls - pause trading only
    pub fn pause_trading(
        ctx: Context<PauseTrading>,
    ) -> Result<()> {
        instructions::pause_trading(ctx)
    }

    /// Enhanced pause controls - pause deposits only
    pub fn pause_deposits(
        ctx: Context<PauseDeposits>,
    ) -> Result<()> {
        instructions::pause_deposits(ctx)
    }

    /// Enhanced pause controls - pause withdrawals (emergency only)
    pub fn pause_withdrawals(
        ctx: Context<PauseWithdrawals>,
    ) -> Result<()> {
        instructions::pause_withdrawals(ctx)
    }

    /// Enhanced pause controls - pause all operations
    pub fn pause_all(
        ctx: Context<PauseAll>,
    ) -> Result<()> {
        instructions::pause_all(ctx)
    }
} 