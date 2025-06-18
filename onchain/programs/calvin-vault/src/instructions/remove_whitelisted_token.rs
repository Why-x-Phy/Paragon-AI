use anchor_lang::prelude::*;

use crate::{constants::*, state::*, errors::ErrorCode};

#[derive(Accounts)]
#[instruction(mint: Pubkey)]
pub struct RemoveWhitelistedToken<'info> {
    /// Emergency owner who can manage token whitelist
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account
    #[account(
        mut,
        constraint = is_emergency_owner(&vault, &authority.key()) @ ErrorCode::UnauthorizedOwner,
    )]
    pub vault: Account<'info, Vault>,
    
    /// Token whitelist account to remove
    #[account(
        mut,
        close = authority,
        seeds = [TOKEN_WHITELIST_PDA_SEED, vault.key().as_ref(), mint.as_ref()],
        bump = token_whitelist.bump,
        constraint = token_whitelist.vault == vault.key() @ ErrorCode::InvalidTokenWhitelistAccount,
        constraint = token_whitelist.mint == mint @ ErrorCode::InvalidTokenWhitelistAccount,
    )]
    pub token_whitelist: Account<'info, TokenWhitelist>,
}

pub fn remove_whitelisted_token(
    ctx: Context<RemoveWhitelistedToken>,
    mint: Pubkey,
) -> Result<()> {
    let vault = &ctx.accounts.vault;
    let token_whitelist = &ctx.accounts.token_whitelist;
    
    // Get token symbol for logging (convert from fixed-size array)
    let symbol_bytes = &token_whitelist.symbol;
    let symbol_end = symbol_bytes.iter().position(|&b| b == 0).unwrap_or(symbol_bytes.len());
    let symbol = String::from_utf8_lossy(&symbol_bytes[..symbol_end]);
    
    // 🔒 EMIT SECURITY EVENT
    emit!(crate::state::SecurityEvent {
        event_type: crate::state::SecurityEventType::EmergencyActionExecuted,
        severity: crate::state::SecuritySeverity::Medium,
        vault: vault.key(),
        details: format!("Token {} ({}) removed from whitelist", symbol, mint),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!("🔒 Token removed from whitelist: {} ({})", symbol, mint);
    msg!("  Account will be closed and rent returned to authority");
    
    // Note: The account is automatically closed due to the close = authority constraint
    // This returns the rent to the authority and removes the whitelist entry
    
    Ok(())
}

/// Helper function to check if a pubkey is an emergency owner
fn is_emergency_owner(vault: &Vault, authority: &Pubkey) -> bool {
    // Check if authority is in the emergency owners array
    for i in 0..vault.emergency_owners_count as usize {
        if vault.emergency_owners[i] == *authority {
            return true;
        }
    }
    false
} 