use anchor_lang::prelude::*;
use crate::{state::*, ErrorCode};

#[derive(Accounts)]
pub struct PauseWithdrawals<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
    
    pub system_program: Program<'info, System>,
}

pub fn pause_withdrawals(ctx: Context<PauseWithdrawals>) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    
    // Verify caller is emergency owner
    let current_owners = &vault.emergency_owners[..vault.emergency_owners_count as usize];
    require!(
        current_owners.contains(&ctx.accounts.authority.key()),
        ErrorCode::UnauthorizedOwner
    );
    
    // Only affects withdrawals - extreme emergency only
    // Trading and deposits continue
    vault.withdrawals_paused = true;
    
    emit!(SecurityEvent {
        event_type: SecurityEventType::WithdrawalsPaused,
        severity: SecuritySeverity::Critical,
        vault: vault.key(),
        details: "Withdrawal operations paused by emergency owner - EXTREME EMERGENCY".to_string(),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!("⚠️  WITHDRAWALS PAUSED - EXTREME EMERGENCY ⚠️");
    msg!("Paused by emergency owner: {}", ctx.accounts.authority.key());
    
    Ok(())
} 