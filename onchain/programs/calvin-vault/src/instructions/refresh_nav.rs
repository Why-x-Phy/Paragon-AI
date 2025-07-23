use anchor_lang::prelude::*;
use anchor_spl::token::{TokenAccount};

use crate::{state::*, utils, errors::ErrorCode};

#[derive(Accounts)]
pub struct RefreshNav<'info> {
    /// Anyone can refresh the NAV - no special authority required
    #[account(mut)]
    pub payer: Signer<'info>,
    
    /// The vault account to update NAV for
    #[account(mut)]
    pub vault: Box<Account<'info, Vault>>,
    
    /// The vault's USDC token account
    #[account(
        constraint = vault_usdc_token.mint == vault.usdc_mint,
        constraint = vault_usdc_token.owner == vault.vault_authority,
    )]
    pub vault_usdc_token: Account<'info, TokenAccount>,
    
    /// System program for any fees
    pub system_program: Program<'info, System>,
}

pub fn refresh_nav(ctx: Context<RefreshNav>) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    let vault_key = vault.key();
    
    // Check if vault is paused
    if vault.paused {
        return Err(error!(ErrorCode::VaultPaused));
    }
    
    // Check if NAV was updated recently (prevent spam)
    let current_time = Clock::get()?.unix_timestamp;
    let time_since_last_update = current_time.saturating_sub(vault.nav_last_updated);
    
    // Allow refresh only if NAV is older than 30 seconds (prevent spam)
    const MIN_UPDATE_INTERVAL: i64 = 30;
    if time_since_last_update < MIN_UPDATE_INTERVAL {
        msg!("NAV was updated {} seconds ago, minimum interval is {} seconds", 
             time_since_last_update, MIN_UPDATE_INTERVAL);
        return Err(error!(ErrorCode::NavTooFresh));
    }
    
    // 🔒 REENTRANCY PROTECTION
    if vault.reentrancy_guard {
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::ReentrancyAttempt,
            severity: crate::state::SecuritySeverity::Critical,
            vault: vault_key,
            details: format!("Reentrancy attempt detected in refresh_nav by {}", ctx.accounts.payer.key()),
            timestamp: current_time,
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
            msg!("Failed to calculate NAV: {:?}", e);
            return Err(e);
        }
    };
    
    // Update cached NAV and timestamp
    vault.cached_nav = current_nav;
    vault.nav_last_updated = current_time;
    
    // Clear reentrancy guard
    vault.reentrancy_guard = false;
    
    // Emit event
    emit!(NavRefreshed {
        vault: vault_key,
        new_nav: current_nav,
        refreshed_by: ctx.accounts.payer.key(),
        timestamp: current_time,
    });
    
    msg!("✅ NAV refreshed by {}: ${} (updated from {} seconds ago)", 
         ctx.accounts.payer.key(), 
         current_nav as f64 / 1e6,
         time_since_last_update);
    
    Ok(())
}

/// Event emitted when NAV is refreshed
#[event]
pub struct NavRefreshed {
    pub vault: Pubkey,
    pub new_nav: u64,
    pub refreshed_by: Pubkey,
    pub timestamp: i64,
} 