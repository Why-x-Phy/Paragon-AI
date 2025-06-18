use anchor_lang::prelude::*;
use crate::{state::*, ErrorCode};

#[derive(Accounts)]
pub struct PauseAll<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
    
    pub system_program: Program<'info, System>,
}

pub fn pause_all(ctx: Context<PauseAll>) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    
    // Verify caller is emergency owner
    let current_owners = &vault.emergency_owners[..vault.emergency_owners_count as usize];
    require!(
        current_owners.contains(&ctx.accounts.authority.key()),
        ErrorCode::UnauthorizedOwner
    );
    
    // Emergency pause everything (extreme cases only)
    vault.trading_paused = true;
    vault.deposits_paused = true;
    vault.withdrawals_paused = true;
    
    emit!(SecurityEvent {
        event_type: SecurityEventType::AllOperationsPaused,
        severity: SecuritySeverity::Critical,
        vault: vault.key(),
        details: "ALL OPERATIONS PAUSED - CRITICAL EMERGENCY".to_string(),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!("🚨 ALL OPERATIONS PAUSED - CRITICAL EMERGENCY 🚨");
    msg!("Paused by emergency owner: {}", ctx.accounts.authority.key());
    msg!("Trading: PAUSED");
    msg!("Deposits: PAUSED");
    msg!("Withdrawals: PAUSED");
    
    Ok(())
} 