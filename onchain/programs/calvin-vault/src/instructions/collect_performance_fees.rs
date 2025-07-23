use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

use crate::{constants::*, state::*, utils, errors::ErrorCode};

#[derive(Accounts)]
pub struct CollectPerformanceFees<'info> {
    /// Authority that can collect fees (either emergency owner or Calvin AI)
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account
    #[account(
        mut,
        constraint = authority.key() == vault.emergency_owner || authority.key() == vault.calvin_authority @ ErrorCode::UnauthorizedCalvin,
    )]
    pub vault: Box<Account<'info, Vault>>,
    
    /// The vault's USDC token account
    #[account(
        mut,
        constraint = vault_usdc_token.mint == vault.usdc_mint,
        constraint = vault_usdc_token.owner == vault_authority.key(),
    )]
    pub vault_usdc_token: Account<'info, TokenAccount>,
    
    /// The treasury's USDC account for fees
    #[account(
        mut,
        constraint = treasury_usdc_token.mint == vault.usdc_mint,
        constraint = treasury_usdc_token.owner == vault.treasury,
    )]
    pub treasury_usdc_token: Account<'info, TokenAccount>,
    
    /// The vault's authority PDA
    /// CHECK: This is a PDA that we derive and verify using seeds
    #[account(
        seeds = [VAULT_AUTHORITY_PDA_SEED],
        bump = vault.authority_bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,
    
    pub token_program: Program<'info, Token>,
}

pub fn collect_performance_fees(ctx: Context<CollectPerformanceFees>) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    let vault_key = vault.key();
    
    // 🔒 REENTRANCY PROTECTION
    if vault.reentrancy_guard {
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::ReentrancyAttempt,
            severity: crate::state::SecuritySeverity::Critical,
            vault: vault_key,
            details: format!("Reentrancy attempt detected in collect_performance_fees by {}", ctx.accounts.authority.key()),
            timestamp: Clock::get()?.unix_timestamp,
        });
        return Err(error!(ErrorCode::ReentrancyDetected));
    }
    vault.reentrancy_guard = true;
    
    // Check if cached NAV is fresh
    let current_time = Clock::get()?.unix_timestamp;
    let nav_age = current_time.saturating_sub(vault.nav_last_updated);
    
    if nav_age > MAX_NAV_STALENESS_SECONDS {
        vault.reentrancy_guard = false;
        msg!("⚠️ Cached NAV is stale ({} seconds old). Please call calculate_nav first.", nav_age);
        return Err(error!(ErrorCode::StaleNav));
    }
    
    // Calculate performance fee based on cached NAV
    let current_nav = vault.cached_nav;
    
    if current_nav <= vault.high_water_mark_nav {
        vault.reentrancy_guard = false;
        msg!("No performance fees to collect - NAV below high water mark");
        return Ok(());
    }
    
    let performance_fee = utils::calculate_performance_fee(
        current_nav,
        vault.high_water_mark_nav
    )?;
    
    if performance_fee == 0 {
        vault.reentrancy_guard = false;
        msg!("No performance fees to collect");
        return Ok(());
    }
    
    // Check if vault has enough USDC to pay the fee
    if performance_fee > ctx.accounts.vault_usdc_token.amount {
        vault.reentrancy_guard = false;
        msg!("Insufficient USDC in vault to pay performance fees");
        return Err(error!(ErrorCode::InsufficientLiquidity));
    }
    
    // Prepare vault authority seeds for signing
    let vault_authority_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[vault.authority_bump],
    ];
    
    // Transfer performance fee to treasury
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
    
    // Update high water mark to current NAV minus fee
    vault.high_water_mark_nav = current_nav.saturating_sub(performance_fee);
    
    // Update cached NAV to reflect the fee collection
    vault.cached_nav = vault.cached_nav.saturating_sub(performance_fee);
    
    // 🔒 CLEAR REENTRANCY GUARD
    vault.reentrancy_guard = false;
    
    // Emit performance fee collected event
    emit!(PerformanceFeeCollected {
        vault: vault_key,
        fee_amount: performance_fee,
        new_high_water_mark: vault.high_water_mark_nav,
        timestamp: current_time,
        authority: ctx.accounts.authority.key(),
    });
    
    msg!(
        "💰 Performance fee collected: {} USDC. New HWM: {}",
        performance_fee,
        vault.high_water_mark_nav
    );
    
    Ok(())
}

/// Event emitted when performance fees are collected
#[event]
pub struct PerformanceFeeCollected {
    pub vault: Pubkey,
    pub fee_amount: u64,
    pub new_high_water_mark: u64,
    pub timestamp: i64,
    pub authority: Pubkey,
} 