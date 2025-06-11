use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, MintTo, Burn, Transfer};

// Import modules
pub mod constants;
pub mod state;
pub mod instructions;
pub mod errors;

use instructions::*;
use state::*;
use errors::*;

// Program ID will be set during deployment
declare_id!("qUKhRct5LW3e9Zwn1e7DvKscsSwVv2S952D7nx39Ach");

/// Calvin Staking Program
/// Manages CALVIN token staking and non-transferable Vault Pass token distribution
#[program]
pub mod calvin_staking {
    use super::*;

    /// Initialize the staking program with configuration
    pub fn initialize_staking(
        ctx: Context<InitializeStaking>,
        tier_thresholds: [u64; 4], // [Vault Keeper, Tier-2, Tier-3, Default]
        vault_program_id: Pubkey,
    ) -> Result<()> {
        instructions::initialize_staking(ctx, tier_thresholds, vault_program_id)
    }

    /// Stake CALVIN tokens and receive Vault Pass tokens
    pub fn stake_calvin(
        ctx: Context<StakeCalvin>,
        amount: u64,
    ) -> Result<()> {
        instructions::stake_calvin(ctx, amount)
    }

    /// Unstake CALVIN tokens - CRITICAL: Must check vault shares via CPI
    pub fn unstake_calvin(
        ctx: Context<UnstakeCalvin>,
        amount: u64,
    ) -> Result<()> {
        instructions::unstake_calvin(ctx, amount)
    }

    /// Verify user's tier - Called via CPI from vault program
    pub fn verify_tier(
        ctx: Context<VerifyTier>,
    ) -> Result<u8> {
        instructions::verify_tier(ctx)
    }

    /// Pause or unpause staking operations
    pub fn pause_staking(
        ctx: Context<PauseStaking>,
        paused: bool,
    ) -> Result<()> {
        instructions::pause_staking(ctx, paused)
    }

    /// Update staking configuration
    pub fn update_config(
        ctx: Context<UpdateConfig>,
        new_tier_thresholds: Option<[u64; 4]>,
        new_vault_program_id: Option<Pubkey>,
    ) -> Result<()> {
        instructions::update_config(ctx, new_tier_thresholds, new_vault_program_id)
    }
} 