use anchor_lang::prelude::*;
use crate::{state::*, ErrorCode};

#[derive(Accounts)]
pub struct PauseDeposits<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
    
    pub system_program: Program<'info, System>,
}

pub fn pause_deposits(ctx: Context<PauseDeposits>) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    
    // Verify caller is emergency owner
    let current_owners = &vault.emergency_owners[..vault.emergency_owners_count as usize];
    require!(
        current_owners.contains(&ctx.accounts.authority.key()),
        ErrorCode::UnauthorizedOwner
    );
    
    // Only affects new deposits
    // Trading and withdrawals continue
    vault.deposits_paused = true;
    
    emit!(SecurityEvent {
        event_type: SecurityEventType::DepositsPaused,
        severity: SecuritySeverity::Medium,
        vault: vault.key(),
        details: "Deposit operations paused by emergency owner".to_string(),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!("Deposits paused by emergency owner: {}", ctx.accounts.authority.key());
    
    Ok(())
} 