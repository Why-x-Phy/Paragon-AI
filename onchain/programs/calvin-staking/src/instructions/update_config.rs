use anchor_lang::prelude::*;

use crate::{constants::*, state::*, errors::*};

#[derive(Accounts)]
pub struct UpdateConfig<'info> {
    /// Admin authority who can update configuration
    #[account(mut)]
    pub admin: Signer<'info>,

    /// Global staking configuration
    #[account(
        mut,
        seeds = [STAKE_CONFIG_SEED],
        bump = stake_config.bump,
        constraint = stake_config.admin_authority == admin.key() @ StakingError::UnauthorizedAdmin,
    )]
    pub stake_config: Account<'info, StakeConfig>,
}

pub fn update_config(
    ctx: Context<UpdateConfig>,
    new_tier_thresholds: Option<[u64; 4]>,
    new_vault_program_id: Option<Pubkey>,
) -> Result<()> {
    let stake_config = &mut ctx.accounts.stake_config;

    // Update tier thresholds if provided
    if let Some(thresholds) = new_tier_thresholds {
        // Validate tier thresholds are in descending order
        if thresholds[0] < thresholds[1] 
            || thresholds[1] < thresholds[2] 
            || thresholds[2] < thresholds[3] {
            return Err(error!(StakingError::InvalidTierThresholds));
        }

        stake_config.tier_thresholds = thresholds;
        msg!(
            "Updated tier thresholds to: [{}, {}, {}, {}]",
            thresholds[0],
            thresholds[1],
            thresholds[2],
            thresholds[3]
        );
    }

    // Update vault program ID if provided
    if let Some(vault_program_id) = new_vault_program_id {
        stake_config.vault_program_id = vault_program_id;
        msg!("Updated vault program ID to: {}", vault_program_id);
    }

    // Emit config update event
    emit!(ConfigUpdateEvent {
        admin: ctx.accounts.admin.key(),
        new_tier_thresholds,
        new_vault_program_id,
    });

    msg!("Staking configuration updated by admin {}", ctx.accounts.admin.key());

    Ok(())
} 