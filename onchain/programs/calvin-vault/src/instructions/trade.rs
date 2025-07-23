use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};

use crate::{constants::*, state::*, utils, errors::ErrorCode};

#[derive(Accounts)]
pub struct Trade<'info> {
    /// Only Calvin AI can execute trades
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account
    #[account(
        mut,
        constraint = !vault.paused @ ErrorCode::VaultPaused,
        constraint = !vault.trading_paused @ ErrorCode::TradingPaused,
    )]
    pub vault: Box<Account<'info, Vault>>,
    
    /// The vault's USDC token account
    #[account(
        mut,
        constraint = vault_usdc_token.mint == vault.usdc_mint,
        constraint = vault_usdc_token.owner == vault_authority.key(),
    )]
    pub vault_usdc_token: Account<'info, TokenAccount>,
    
    /// The source token mint (what we're trading from)
    pub source_mint: Account<'info, Mint>,
    
    /// The destination token mint (what we're trading to)
    pub destination_mint: Account<'info, Mint>,
    
    /// The vault's source token account
    #[account(
        mut,
        constraint = source_token_account.mint == source_mint.key(),
        constraint = source_token_account.owner == vault_authority.key(),
    )]
    pub source_token_account: Account<'info, TokenAccount>,
    
    /// The vault's destination token account
    #[account(
        mut,
        constraint = destination_token_account.mint == destination_mint.key(),
        constraint = destination_token_account.owner == vault_authority.key(),
    )]
    pub destination_token_account: Account<'info, TokenAccount>,
    
    /// The vault's authority PDA
    /// CHECK: This is a PDA that we derive and verify using seeds
    #[account(
        seeds = [VAULT_AUTHORITY_PDA_SEED],
        bump = vault.authority_bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,
    
    /// Source token whitelist entry (validates source token is whitelisted)
    #[account(
        seeds = [TOKEN_WHITELIST_PDA_SEED, vault.key().as_ref(), source_mint.key().as_ref()],
        bump = source_token_whitelist.bump,
        constraint = source_token_whitelist.vault == vault.key() @ ErrorCode::TokenNotWhitelisted,
        constraint = source_token_whitelist.mint == source_mint.key() @ ErrorCode::TokenNotWhitelisted,
        constraint = source_token_whitelist.is_active @ ErrorCode::TokenNotWhitelisted,
    )]
    pub source_token_whitelist: Box<Account<'info, TokenWhitelist>>,
    
    /// Destination token whitelist entry (validates destination token is whitelisted)
    #[account(
        seeds = [TOKEN_WHITELIST_PDA_SEED, vault.key().as_ref(), destination_mint.key().as_ref()],
        bump = destination_token_whitelist.bump,
        constraint = destination_token_whitelist.vault == vault.key() @ ErrorCode::TokenNotWhitelisted,
        constraint = destination_token_whitelist.mint == destination_mint.key() @ ErrorCode::TokenNotWhitelisted,
        constraint = destination_token_whitelist.is_active @ ErrorCode::TokenNotWhitelisted,
    )]
    pub destination_token_whitelist: Box<Account<'info, TokenWhitelist>>,
    
    /// The Jupiter program
    /// CHECK: This is the Jupiter program ID, verified against the vault's config
    #[account(
        address = vault.jupiter_program_id,
    )]
    pub jupiter_program: UncheckedAccount<'info>,
    
    /// The token program
    pub token_program: Program<'info, Token>,
    
    /// The treasury's USDC account for performance fees
    #[account(
        mut,
        constraint = treasury_usdc_token.mint == vault.usdc_mint,
        constraint = treasury_usdc_token.owner == vault.treasury,
    )]
    pub treasury_usdc_token: Account<'info, TokenAccount>,
    
    // Note: remaining_accounts are passed through to Jupiter for swap execution
}

pub fn trade(ctx: Context<Trade>, data: Vec<u8>) -> Result<()> {
    // Get accounts
    let vault = &mut ctx.accounts.vault;
    let vault_key = vault.key(); // Get vault key before mutable operations
    
    // 🔒 REENTRANCY PROTECTION
    if vault.reentrancy_guard {
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::ReentrancyAttempt,
            severity: crate::state::SecuritySeverity::Critical,
            vault: vault_key,
            details: format!("Reentrancy attempt detected in trade by Calvin AI"),
            timestamp: Clock::get()?.unix_timestamp,
        });
        return Err(error!(ErrorCode::ReentrancyDetected));
    }
    vault.reentrancy_guard = true;
    
    // 🔒 AUTHORIZATION CHECK
    if ctx.accounts.authority.key() != vault.calvin_authority {
        vault.reentrancy_guard = false;
        return Err(error!(ErrorCode::UnauthorizedCalvin));
    }
    
    // 🔒 CPI RATE LIMITING
    if let Err(e) = utils::validate_and_track_cpi_call(vault, &ctx.accounts.jupiter_program.key(), &vault_key) {
        vault.reentrancy_guard = false;
        return Err(e);
    }
    
    // 🔒 TOKEN WHITELISTING VALIDATION
    // Token whitelist validation ensures only whitelisted tokens can be traded
    // (enforced by account constraints on source_token_whitelist and destination_token_whitelist).
    // Price validation now happens through the cached NAV system via calculate_nav instruction.
    
    // Record source balance before swap to calculate actual swap amount
    let source_balance_before = ctx.accounts.source_token_account.amount;
    
    // 🔒 VALIDATE TRADE AMOUNT
    if source_balance_before == 0 {
        vault.reentrancy_guard = false;
        return Err(error!(ErrorCode::InvalidAmount));
    }
    
    // Record destination balance before swap
    let destination_balance_before = ctx.accounts.destination_token_account.amount;
    
    // Check if cached NAV is fresh enough for pre-trade validation
    let current_time = Clock::get()?.unix_timestamp;
    let nav_age = current_time.saturating_sub(vault.nav_last_updated);
    
    if nav_age > crate::constants::MAX_NAV_STALENESS_SECONDS {
        vault.reentrancy_guard = false;
        msg!("⚠️ Cached NAV is stale ({} seconds old). Please call calculate_nav first.", nav_age);
        return Err(error!(ErrorCode::StaleNav));
    }
    
    // Use cached NAV for pre-trade validation
    let pre_trade_nav = vault.cached_nav;
    
    // Prepare vault authority seeds for signing
    let vault_authority_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[vault.authority_bump],
    ];
    
    // Execute Jupiter swap using all remaining accounts
    // Since we don't need oracle accounts anymore, all remaining accounts are for Jupiter
    utils::forward_jupiter(
        ctx.accounts.jupiter_program.to_account_info(),
        &ctx.remaining_accounts,
        data.clone(),
        &[vault_authority_seeds],
        &vault.vault_authority,
    )?;
    
    let destination_balance_after = ctx.accounts.destination_token_account.amount;
    let amount_out = destination_balance_after
        .checked_sub(destination_balance_before)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Calculate actual amount swapped from source token
    let source_balance_after = ctx.accounts.source_token_account.amount;
    let amount_in = source_balance_before
        .checked_sub(source_balance_after)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Note: After this trade, the cached NAV will be stale and needs to be recalculated
    // by calling calculate_nav instruction before the next deposit/withdraw/trade
    
    // Update vault state - we can't update high water mark here since we don't have fresh NAV
    // High water mark will be updated when calculate_nav is called next
    
    // 🎯 COLLECT PERFORMANCE FEES ONLY ON PROFITABLE USDC EXITS
    // Performance fees should only be collected when:
    // 1. Selling tokens FOR USDC (destination mint is USDC)
    // 2. NAV increases above high water mark (profitable trade)
    // Since we're using cached NAV, we'll need to handle performance fees differently
    // The frontend should call calculate_nav after trades and then collect fees if needed
    let is_selling_for_usdc = ctx.accounts.destination_mint.key() == vault.usdc_mint;
    
    if is_selling_for_usdc {
        msg!("💰 USDC sale completed. Call calculate_nav to update NAV and check for performance fees.");
    }
    
    // 🔒 CLEAR REENTRANCY GUARD BEFORE EMITTING EVENTS
    vault.reentrancy_guard = false;
    
    // Get token symbols for logging
    let source_symbol = get_token_symbol(&ctx.accounts.source_token_whitelist.symbol);
    let dest_symbol = get_token_symbol(&ctx.accounts.destination_token_whitelist.symbol);
    
    // Emit trade event with actual trade impact
    emit!(crate::state::Trade {
        vault: vault_key,
        source_mint: ctx.accounts.source_mint.key(),
        destination_mint: ctx.accounts.destination_mint.key(),
        amount_in,
        amount_out,
        timestamp: Clock::get()?.unix_timestamp,
        calvin_authority: ctx.accounts.authority.key(),
    });
    
    msg!(
        "🔒 Secure trade: {} {} → {} {} (whitelisted tokens only)",
        amount_in,
        source_symbol,
        amount_out,
        dest_symbol
    );
    
    Ok(())
}

/// Helper function to convert fixed-size symbol array to string
fn get_token_symbol(symbol_bytes: &[u8; 10]) -> String {
    let symbol_end = symbol_bytes.iter().position(|&b| b == 0).unwrap_or(symbol_bytes.len());
    String::from_utf8_lossy(&symbol_bytes[..symbol_end]).to_string()
} 