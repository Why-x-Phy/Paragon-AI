use anchor_lang::prelude::*;

use crate::{constants::*, state::*, errors::ErrorCode};

#[derive(Accounts)]
#[instruction(mint: Pubkey, symbol: String, pyth_oracle: Pubkey, switchboard_oracle: Option<Pubkey>, max_allocation_bps: u16)]
pub struct AddWhitelistedToken<'info> {
    /// Emergency owner who can manage token whitelist
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account
    #[account(
        mut,
        constraint = is_emergency_owner(&vault, &authority.key()) @ ErrorCode::UnauthorizedOwner,
    )]
    pub vault: Account<'info, Vault>,
    
    /// Token whitelist account to create
    #[account(
        init,
        payer = authority,
        space = TokenWhitelist::SIZE,
        seeds = [TOKEN_WHITELIST_PDA_SEED, vault.key().as_ref(), mint.as_ref()],
        bump
    )]
    pub token_whitelist: Account<'info, TokenWhitelist>,
    
    /// The token mint to whitelist
    /// CHECK: We validate this is a valid mint by requiring it exists
    pub token_mint: UncheckedAccount<'info>,
    
    /// Primary Pyth oracle account
    /// CHECK: Validated by oracle functions when used
    pub pyth_oracle_account: UncheckedAccount<'info>,
    
    /// Optional Switchboard oracle account
    /// CHECK: Validated by oracle functions when used
    pub switchboard_oracle_account: Option<UncheckedAccount<'info>>,
    
    pub system_program: Program<'info, System>,
}

pub fn add_whitelisted_token(
    ctx: Context<AddWhitelistedToken>,
    mint: Pubkey,
    symbol: String,
    pyth_oracle: Pubkey,
    switchboard_oracle: Option<Pubkey>,
    max_allocation_bps: u16,
) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    let token_whitelist = &mut ctx.accounts.token_whitelist;
    
    // 🔒 VALIDATE INPUT PARAMETERS
    
    // Validate symbol length
    if symbol.is_empty() || symbol.len() > MAX_TOKEN_SYMBOL_LEN {
        return Err(error!(ErrorCode::InvalidTokenSymbol));
    }
    
    // Validate allocation percentage
    if max_allocation_bps < MIN_ALLOCATION_BPS || max_allocation_bps > MAX_ALLOCATION_BPS {
        return Err(error!(ErrorCode::InvalidAllocationPercentage));
    }
    
    // Validate mint matches the account provided
    if mint != ctx.accounts.token_mint.key() {
        return Err(error!(ErrorCode::InvalidTokenWhitelistAccount));
    }
    
    // Validate oracle accounts match
    if pyth_oracle != ctx.accounts.pyth_oracle_account.key() {
        return Err(error!(ErrorCode::InvalidOracleAccount));
    }
    
    if let (Some(sb_oracle), Some(sb_account)) = (switchboard_oracle, &ctx.accounts.switchboard_oracle_account) {
        if sb_oracle != sb_account.key() {
            return Err(error!(ErrorCode::InvalidSwitchboardFeed));
        }
    }
    
    // 🔒 INITIALIZE TOKEN WHITELIST ENTRY
    
    token_whitelist.vault = vault.key();
    token_whitelist.mint = mint;
    
    // Convert symbol to fixed-size array (pad with zeros)
    let mut symbol_bytes = [0u8; MAX_TOKEN_SYMBOL_LEN];
    let symbol_slice = symbol.as_bytes();
    let copy_len = symbol_slice.len().min(MAX_TOKEN_SYMBOL_LEN);
    symbol_bytes[..copy_len].copy_from_slice(&symbol_slice[..copy_len]);
    token_whitelist.symbol = symbol_bytes;
    
    token_whitelist.pyth_oracle = pyth_oracle;
    token_whitelist.switchboard_oracle = switchboard_oracle;
    token_whitelist.max_allocation_bps = max_allocation_bps;
    token_whitelist.is_active = true;
    token_whitelist.added_timestamp = Clock::get()?.unix_timestamp;
    token_whitelist.bump = ctx.bumps.token_whitelist;
    token_whitelist.reserved = [0u8; 32];
    
    // 🔒 EMIT SECURITY EVENT
    emit!(crate::state::SecurityEvent {
        event_type: crate::state::SecurityEventType::EmergencyActionExecuted,
        severity: crate::state::SecuritySeverity::Medium,
        vault: vault.key(),
        details: format!("Token {} ({}) added to whitelist with {}% max allocation", 
                        symbol, mint, max_allocation_bps as f64 / 100.0),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    let symbol_str = String::from_utf8(symbol_bytes.iter().cloned().collect::<Vec<_>>()).unwrap();
    emit!(crate::state::TokenWhitelistEvent {
        vault: vault.key(),
        token_mint: mint,
        action: crate::state::WhitelistAction::Added,
        symbol: symbol_str,
        pyth_oracle,
        switchboard_oracle,
        max_allocation_bps,
        timestamp: Clock::get()?.unix_timestamp,
        authority: ctx.accounts.authority.key(),
    });
    
    msg!("🔒 Token whitelisted: {} ({}) with max allocation {}%", 
         symbol, mint, max_allocation_bps as f64 / 100.0);
    msg!("  Pyth oracle: {}", pyth_oracle);
    if let Some(sb_oracle) = switchboard_oracle {
        msg!("  Switchboard oracle: {}", sb_oracle);
    }
    
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