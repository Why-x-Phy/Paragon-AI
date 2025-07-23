use anchor_lang::prelude::*;
use anchor_spl::token::{TokenAccount};

use crate::{state::*, utils, errors::ErrorCode};

#[derive(Accounts)]
pub struct CalculateNav<'info> {
    /// Authority that can update NAV (either emergency owner or Calvin AI)
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account to update NAV for
    #[account(
        mut,
        constraint = authority.key() == vault.emergency_owner || authority.key() == vault.calvin_authority @ ErrorCode::UnauthorizedCalvin,
    )]
    pub vault: Box<Account<'info, Vault>>,
    
    /// The vault's USDC token account
    #[account(
        constraint = vault_usdc_token.mint == vault.usdc_mint,
        constraint = vault_usdc_token.owner == vault.vault_authority,
    )]
    pub vault_usdc_token: Account<'info, TokenAccount>,
}

pub fn calculate_nav(ctx: Context<CalculateNav>) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    let vault_key = vault.key();
    
    // 🔒 REENTRANCY PROTECTION
    if vault.reentrancy_guard {
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::ReentrancyAttempt,
            severity: crate::state::SecuritySeverity::Critical,
            vault: vault_key,
            details: format!("Reentrancy attempt detected in calculate_nav by {}", ctx.accounts.authority.key()),
            timestamp: Clock::get()?.unix_timestamp,
        });
        return Err(error!(ErrorCode::ReentrancyDetected));
    }
    vault.reentrancy_guard = true;
    
    // Calculate current NAV using all oracle accounts passed in remaining_accounts
    // remaining_accounts should contain oracle accounts in groups of 3: [token_account, price_update_v2, token_mint]
    let current_nav = match utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        &ctx.remaining_accounts,
    ) {
        Ok(nav) => nav,
        Err(e) => {
            vault.reentrancy_guard = false;
            return Err(e);
        }
    };
    
    // 🔒 VALIDATE NAV BOUNDS
    if current_nav > crate::constants::MAX_TOTAL_NAV {
        vault.reentrancy_guard = false;
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::ArithmeticSafetyViolation,
            severity: crate::state::SecuritySeverity::High,
            vault: vault_key,
            details: format!("Calculated NAV {} exceeds maximum {}", current_nav, crate::constants::MAX_TOTAL_NAV),
            timestamp: Clock::get()?.unix_timestamp,
        });
        return Err(error!(ErrorCode::NavTooHigh));
    }
    
    // Update cached NAV and timestamp
    let current_timestamp = Clock::get()?.unix_timestamp;
    vault.cached_nav = current_nav;
    vault.nav_last_updated = current_timestamp;
    
    // 🔒 CLEAR REENTRANCY GUARD
    vault.reentrancy_guard = false;
    
    // Emit NAV update event
    emit!(NavUpdated {
        vault: vault_key,
        nav: current_nav,
        timestamp: current_timestamp,
        authority: ctx.accounts.authority.key(),
    });
    
    msg!(
        "📊 NAV updated: {} USDC at timestamp {} by {}",
        current_nav,
        current_timestamp,
        ctx.accounts.authority.key()
    );
    
    Ok(())
}

/// Event emitted when NAV is updated
#[event]
pub struct NavUpdated {
    pub vault: Pubkey,
    pub nav: u64,
    pub timestamp: i64,
    pub authority: Pubkey,
} 