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
    
    // Record source balance before swap to calculate actual swap amount
    let source_balance_before = ctx.accounts.source_token_account.amount;
    
    // 🔒 VALIDATE TRADE AMOUNT
    if source_balance_before == 0 {
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
    
    // Split remaining_accounts into oracle accounts and Jupiter accounts
    // The vault expects oracle accounts in groups of 3: [token_account, price_oracle, token_mint]
    // followed by Jupiter accounts for the swap
    // We need to determine how many oracle groups are provided
    
    // **IMPROVED LOGIC**: Dynamically determine oracle count based on actual remaining accounts
    // The vault client sends oracle accounts in groups of 3, followed by Jupiter accounts
    // Look for a pattern where we have oracle account groups followed by Jupiter accounts
    
    let oracle_count = {
        let total_remaining = ctx.remaining_accounts.len();
        
        // **CRITICAL FIX**: Be more flexible with oracle account detection
        // The client might send different numbers of oracle accounts based on available tokens
        if total_remaining >= 21 {
            // Standard case: 6 oracle accounts (2 tokens × 3) + 15 Jupiter accounts = 21 total
            6
        } else if total_remaining >= 18 {
            // Alternative case: 6 oracle accounts + fewer Jupiter accounts
            6  
        } else if total_remaining >= 15 {
            // Minimal case: No oracle accounts, just Jupiter accounts
            0
        } else if total_remaining >= 12 {
            // Legacy case: 12 oracle accounts (4 tokens × 3) but fewer Jupiter accounts
            // This might be from older client logic
            12.min(total_remaining - 3) // Ensure at least 3 Jupiter accounts remain
    } else {
            // Very few accounts - assume all are Jupiter accounts
            0
        }
    };
    
    // **SAFETY CHECK**: Ensure we don't split beyond array bounds
    let safe_oracle_count = oracle_count.min(ctx.remaining_accounts.len());
    
    let (oracle_accounts, jupiter_accounts) = ctx.remaining_accounts.split_at(safe_oracle_count);
    
    // **ENHANCED LOGGING**: Log account distribution for debugging
    msg!("Calculating NAV with {} remaining accounts", ctx.remaining_accounts.len());
    msg!("Oracle accounts: {}, Jupiter accounts: {}", oracle_accounts.len(), jupiter_accounts.len());
    
    // **CRITICAL CHECK**: Ensure Jupiter has enough accounts to execute
    if jupiter_accounts.len() < 10 {
        msg!("⚠️ Warning: Jupiter received only {} accounts, may cause execution failure", jupiter_accounts.len());
    }
    
    // Calculate pre-trade NAV
    let pre_trade_nav = utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        oracle_accounts,
    )?;
    
    // Execute Jupiter swap using only the Jupiter accounts
    utils::forward_jupiter(
        ctx.accounts.jupiter_program.to_account_info(),
        jupiter_accounts,  // Only Jupiter accounts, not oracle accounts
        data.clone(),
        &[vault_authority_seeds],
        &vault.vault_authority,
    )?;
    
    // Calculate post-trade NAV
    let post_trade_nav = utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        oracle_accounts,
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
    
    // Get current NAV including the new token positions with actual price feeds
    // Prepare remaining accounts for NAV calculation - ONLY oracle accounts in groups of 3
    let nav_remaining_accounts = vec![
        // Oracle data in groups of 3: [token_account, price_account, mint_account]
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
    
    // 🎯 COLLECT PERFORMANCE FEES ONLY ON PROFITABLE USDC EXITS
    // Performance fees should only be collected when:
    // 1. Selling tokens FOR USDC (destination mint is USDC)
    // 2. NAV increases above high water mark (profitable trade)
    let is_selling_for_usdc = ctx.accounts.destination_mint.key() == vault.usdc_mint;
    
    if is_selling_for_usdc && post_trade_nav > vault.high_water_mark_nav {
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
            
            msg!("💰 Performance fee collected: {} USDC (profitable sale)", performance_fee);
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