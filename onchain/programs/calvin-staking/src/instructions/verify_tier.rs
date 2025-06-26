use anchor_lang::prelude::*;

use crate::{constants::*, state::*};

#[derive(Accounts)]
pub struct VerifyTier<'info> {
    /// User whose tier is being verified
    /// CHECK: This is just a pubkey for tier lookup
    pub user: UncheckedAccount<'info>,

    /// Global staking configuration
    #[account(
        seeds = [STAKE_CONFIG_SEED],
        bump = stake_config.bump,
    )]
    pub stake_config: Account<'info, StakeConfig>,

    /// User's stake account
    #[account(
        seeds = [USER_STAKE_SEED, user.key().as_ref()],
        bump = user_stake.bump,
        constraint = user_stake.user_authority == user.key(),
    )]
    pub user_stake: Account<'info, UserStake>,
}

pub fn verify_tier(ctx: Context<VerifyTier>) -> Result<u8> {
    let user_stake = &ctx.accounts.user_stake;
    let stake_config = &ctx.accounts.stake_config;

    // Recalculate tier to ensure it's current
    let current_tier = calculate_tier(user_stake.total_staked, &stake_config.tier_thresholds);

    msg!(
        "User {} has tier {} with {} CALVIN staked",
        ctx.accounts.user.key(),
        current_tier,
        user_stake.total_staked
    );

    Ok(current_tier)
}

/// Calculate tier based on staked amount
fn calculate_tier(staked_amount: u64, thresholds: &[u64; 4]) -> u8 {
    if staked_amount >= thresholds[0] {
        VAULT_KEEPER_TIER
    } else if staked_amount >= thresholds[1] {
        TIER_2
    } else if staked_amount >= thresholds[2] {
        TIER_3
    } else {
        DEFAULT_TIER
    }
} 