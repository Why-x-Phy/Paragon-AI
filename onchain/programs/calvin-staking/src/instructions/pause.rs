use anchor_lang::prelude::*;

use crate::{constants::*, state::*, errors::*};

#[derive(Accounts)]
pub struct PauseStaking<'info> {
    /// Admin authority who can pause/unpause staking
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

pub fn pause_staking(ctx: Context<PauseStaking>, paused: bool) -> Result<()> {
    let stake_config = &mut ctx.accounts.stake_config;
    
    stake_config.paused = paused;

    // Emit pause event
    emit!(PauseEvent {
        paused,
        timestamp: Clock::get()?.unix_timestamp,
    });

    msg!(
        "Staking program {} by admin {}",
        if paused { "PAUSED" } else { "UNPAUSED" },
        ctx.accounts.admin.key()
    );

    Ok(())
} 