use anchor_lang::prelude::*;
use crate::{state::*, ErrorCode};

#[derive(Accounts)]
pub struct PauseTrading<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
    
    pub system_program: Program<'info, System>,
}

pub fn pause_trading(ctx: Context<PauseTrading>) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    
    // Verify caller is emergency owner
    let current_owners = &vault.emergency_owners[..vault.emergency_owners_count as usize];
    require!(
        current_owners.contains(&ctx.accounts.authority.key()),
        ErrorCode::UnauthorizedOwner
    );
    
    // Only affects Calvin AI trades
    // Users can still deposit/withdraw normally
    vault.trading_paused = true;
    
    emit!(SecurityEvent {
        event_type: SecurityEventType::TradingPaused,
        severity: SecuritySeverity::High,
        vault: vault.key(),
        details: "Trading operations paused by emergency owner".to_string(),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!("Trading paused by emergency owner: {}", ctx.accounts.authority.key());
    
    Ok(())
} 