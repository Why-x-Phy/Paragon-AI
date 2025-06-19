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
    pub vault: Account<'info, Vault>,
    
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
    pub source_token_whitelist: Account<'info, TokenWhitelist>,
    
    /// Destination token whitelist entry (validates destination token is whitelisted)
    #[account(
        seeds = [TOKEN_WHITELIST_PDA_SEED, vault.key().as_ref(), destination_mint.key().as_ref()],
        bump = destination_token_whitelist.bump,
        constraint = destination_token_whitelist.vault == vault.key() @ ErrorCode::TokenNotWhitelisted,
        constraint = destination_token_whitelist.mint == destination_mint.key() @ ErrorCode::TokenNotWhitelisted,
        constraint = destination_token_whitelist.is_active @ ErrorCode::TokenNotWhitelisted,
    )]
    pub destination_token_whitelist: Account<'info, TokenWhitelist>,
    
    /// Price oracle account for source token (Pyth price feed)
    /// CHECK: Validated by utils::current_nav_usdc function
    pub source_price_account: UncheckedAccount<'info>,
    
    /// Price oracle account for destination token (Pyth price feed)
    /// CHECK: Validated by utils::current_nav_usdc function
    pub destination_price_account: UncheckedAccount<'info>,
    
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
    
    // Note: remaining_accounts are accessed via ctx.remaining_accounts (Anchor built-in)
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
    // Validate oracle accounts match whitelist entries
    if ctx.accounts.source_token_whitelist.pyth_oracle != ctx.accounts.source_price_account.key() {
        vault.reentrancy_guard = false;
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::TokenWhitelistViolation,
            severity: crate::state::SecuritySeverity::High,
            vault: vault_key,
            details: format!("Source token oracle mismatch: expected {}, got {}", 
                           ctx.accounts.source_token_whitelist.pyth_oracle, 
                           ctx.accounts.source_price_account.key()),
            timestamp: Clock::get()?.unix_timestamp,
        });
        return Err(error!(ErrorCode::InvalidOracleAccount));
    }
    
    if ctx.accounts.destination_token_whitelist.pyth_oracle != ctx.accounts.destination_price_account.key() {
        vault.reentrancy_guard = false;
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::TokenWhitelistViolation,
            severity: crate::state::SecuritySeverity::High,
            vault: vault_key,
            details: format!("Destination token oracle mismatch: expected {}, got {}", 
                           ctx.accounts.destination_token_whitelist.pyth_oracle, 
                           ctx.accounts.destination_price_account.key()),
            timestamp: Clock::get()?.unix_timestamp,
        });
        return Err(error!(ErrorCode::InvalidOracleAccount));
    }
    
    // Get amount to trade (from the source token account)
    let amount_in = ctx.accounts.source_token_account.amount;
    
    // 🔒 VALIDATE TRADE AMOUNT
    if amount_in == 0 {
        vault.reentrancy_guard = false;
        return Err(error!(ErrorCode::InvalidAmount));
    }
    
    // Record destination balance before swap
    let destination_balance_before = ctx.accounts.destination_token_account.amount;
    
    // Note: We'll pass ctx.remaining_accounts directly to forward_jupiter
    // Jupiter needs the remaining accounts to be passed as a slice
    
    // Prepare vault authority seeds for signing
    let vault_authority_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[vault.authority_bump],
    ];
    
    // Calculate pre-trade NAV for comparison
    let pre_trade_nav = utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        ctx.remaining_accounts,
    )?;
    
    // Execute Jupiter swap
    utils::forward_jupiter(
        ctx.accounts.jupiter_program.to_account_info(),
        ctx.remaining_accounts,
        data.clone(),
        &[vault_authority_seeds],
        &vault.vault_authority,
    )?;
    
    // Calculate post-trade NAV
    let post_trade_nav = utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        ctx.remaining_accounts,
    )?;
    
    let destination_balance_after = ctx.accounts.destination_token_account.amount;
    let amount_out = destination_balance_after
        .checked_sub(destination_balance_before)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Get current NAV including the new token positions with actual price feeds
    // Prepare remaining accounts for NAV calculation
    let nav_remaining_accounts = vec![
        // First 2 accounts are placeholders for staking program accounts
        ctx.accounts.vault_authority.to_account_info(), // placeholder
        ctx.accounts.vault_authority.to_account_info(), // placeholder
        // Then oracle data in groups of 3: [token_account, price_account, mint_account]
        ctx.accounts.source_token_account.to_account_info(),
        ctx.accounts.source_price_account.to_account_info(),
        ctx.accounts.source_mint.to_account_info(),
        ctx.accounts.destination_token_account.to_account_info(),
        ctx.accounts.destination_price_account.to_account_info(),
        ctx.accounts.destination_mint.to_account_info(),
    ];
    
    let new_nav = match utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        &nav_remaining_accounts,
    ) {
        Ok(nav) => nav,
        Err(e) => {
            vault.reentrancy_guard = false;
            return Err(e);
        }
    };
    
    // 🔒 VALIDATE NAV BOUNDS
    if new_nav > MAX_TOTAL_NAV {
        vault.reentrancy_guard = false;
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::ArithmeticSafetyViolation,
            severity: crate::state::SecuritySeverity::High,
            vault: vault_key,
            details: format!("Post-trade NAV {} exceeds maximum {}", new_nav, MAX_TOTAL_NAV),
            timestamp: Clock::get()?.unix_timestamp,
        });
        return Err(error!(ErrorCode::NavTooHigh));
    }
    
    // Update vault state (high water mark, etc.)
    if let Err(e) = utils::after_trade(vault, new_nav) {
        vault.reentrancy_guard = false;
        return Err(e);
    }
    
    // 🎯 COLLECT PERFORMANCE FEES IMMEDIATELY ON PROFITS
    if post_trade_nav > vault.high_water_mark_nav {
        let performance_fee = utils::calculate_performance_fee(
            post_trade_nav, 
            vault.high_water_mark_nav
        )?;
        
        if performance_fee > 0 {
            token::transfer(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    Transfer {
                        from: ctx.accounts.vault_usdc_token.to_account_info(),
                        to: ctx.accounts.treasury_usdc_token.to_account_info(),
                        authority: ctx.accounts.vault_authority.to_account_info(),
                    },
                    &[vault_authority_seeds],
                ),
                performance_fee,
            )?;
            
            vault.high_water_mark_nav = post_trade_nav.saturating_sub(performance_fee);
        }
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
        amount_in: data.len() as u64, // Use data length as proxy for trade size
        amount_out: post_trade_nav.saturating_sub(pre_trade_nav), // NAV change
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