use anchor_lang::prelude::*;

use crate::{constants::*, state::*, ErrorCode};

#[derive(Accounts)]
pub struct SetPauseStatus<'info> {
    /// Only the vault owner can pause/unpause the vault
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account
    #[account(
        mut,
        constraint = vault.owner == authority.key() @ ErrorCode::UnauthorizedOwner,
    )]
    pub vault: Account<'info, Vault>,
}

pub fn set_pause_status(ctx: Context<SetPauseStatus>, paused: bool) -> Result<()> {
    // Get vault account
    let vault = &mut ctx.accounts.vault;
    
    // Set pause status
    vault.paused = paused;
    
    msg!("Vault {} status set to: {}", vault.key(), if paused { "PAUSED" } else { "ACTIVE" });
    
    Ok(())
} 