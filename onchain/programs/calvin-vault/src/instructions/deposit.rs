use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, MintTo, Transfer, FreezeAccount};
use anchor_spl::associated_token::AssociatedToken;

use crate::{constants::*, state::*, utils, errors::ErrorCode};

#[derive(Accounts)]
#[instruction(amount: u64)]
pub struct Deposit<'info> {
    #[account(mut)]
    pub user: Signer<'info>,
    
    /// The vault account 
    #[account(
        mut,
        constraint = !vault.paused @ ErrorCode::VaultPaused,
        constraint = !vault.deposits_paused @ ErrorCode::DepositsPaused,
    )]
    pub vault: Account<'info, Vault>,
    
    /// User's vault position account (tracks deposits for tier caps)
    #[account(
        init_if_needed,
        payer = user,
        space = UserPosition::SIZE,
        seeds = [USER_POSITION_PDA_SEED, user.key().as_ref(), vault.key().as_ref()],
        bump
    )]
    pub user_position: Account<'info, UserPosition>,
    
    /// The user's USDC token account
    #[account(
        mut,
        constraint = user_usdc_token.mint == vault.usdc_mint,
        constraint = user_usdc_token.owner == user.key(),
    )]
    pub user_usdc_token: Account<'info, TokenAccount>,
    
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
    
    /// The share token mint
    #[account(
        mut,
        address = vault.shares_mint,
    )]
    pub shares_mint: Account<'info, Mint>,
    
    /// The user's share token account (will be frozen after minting)
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = shares_mint,
        associated_token::authority = user,
    )]
    pub user_shares_token: Account<'info, TokenAccount>,
    
    /// The vault's authority PDA
    /// CHECK: This is a PDA that we derive and verify using seeds
    #[account(
        seeds = [VAULT_AUTHORITY_PDA_SEED],
        bump = vault.authority_bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,
    
    /// Staking program for CPI tier verification
    /// CHECK: This should be the Calvin staking program ID
    pub staking_program: UncheckedAccount<'info>,
    
    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn deposit(ctx: Context<Deposit>, amount: u64) -> Result<()> {
    // Get accounts
    let vault = &mut ctx.accounts.vault;
    let vault_key = vault.key(); // Get vault key before mutable operations
    let user = &ctx.accounts.user;
    let user_position = &mut ctx.accounts.user_position;
    
    // 🔒 REENTRANCY PROTECTION
    if vault.reentrancy_guard {
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::ReentrancyAttempt,
            severity: crate::state::SecuritySeverity::Critical,
            vault: vault_key,
            details: format!("Reentrancy attempt detected in deposit by user {}", user.key()),
            timestamp: Clock::get()?.unix_timestamp,
        });
        return Err(error!(ErrorCode::ReentrancyDetected));
    }
    vault.reentrancy_guard = true;
    
    // 🔒 PAUSE CHECKS - Allow granular control
    if vault.deposits_paused {
        vault.reentrancy_guard = false;
        return Err(error!(ErrorCode::DepositsPaused));
    }
    
    // 🔒 ENHANCED ARITHMETIC SAFETY
    if let Err(e) = utils::validate_deposit_amount(amount) {
        vault.reentrancy_guard = false;
        return Err(e);
    }
    
    // Initialize user position if it's new
    if user_position.user_authority == Pubkey::default() {
        user_position.user_authority = user.key();
        user_position.vault = vault_key;
        user_position.total_deposits_usdc = 0;
        user_position.last_deposit_timestamp = Clock::get()?.unix_timestamp;
        user_position.bump = ctx.bumps.user_position;
    }
    
    // 🔒 CPI RATE LIMITING for staking program calls
    if let Err(e) = utils::validate_and_track_cpi_call(vault, &ctx.accounts.staking_program.key(), &vault_key) {
        vault.reentrancy_guard = false;
        return Err(e);
    }
    
    // Verify user's tier and check deposit caps via staking program
    if let Err(e) = utils::verify_tier_and_check_cap(
        &ctx.accounts.staking_program.to_account_info(),
        &user.key(),
        user_position.total_deposits_usdc,
        amount,
        vault,
        &ctx.remaining_accounts,
    ) {
        vault.reentrancy_guard = false;
        return Err(e);
    }
    
    // Calculate deposit fee
    let deposit_fee = match utils::calculate_deposit_fee(amount) {
        Ok(fee) => fee,
        Err(e) => {
            vault.reentrancy_guard = false;
            return Err(e);
        }
    };
    
    // Get current NAV (for calculating shares)
    // remaining_accounts format: [0] stake_config, [1] user_stake, [2+] vault token accounts, price accounts, mint accounts
    // Skip staking accounts (first 2) and pass the rest to utility function for parsing
    let nav_parsing_accounts = &ctx.remaining_accounts[2..];
    
    let vault_nav = match utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        nav_parsing_accounts,
    ) {
        Ok(nav) => nav,
        Err(e) => {
            vault.reentrancy_guard = false;
            return Err(e);
        }
    };
    
    // 🔒 VALIDATE NAV BOUNDS
    if vault_nav > MAX_TOTAL_NAV {
        vault.reentrancy_guard = false;
        emit!(crate::state::SecurityEvent {
            event_type: crate::state::SecurityEventType::ArithmeticSafetyViolation,
            severity: crate::state::SecuritySeverity::High,
            vault: vault_key,
            details: format!("Vault NAV {} exceeds maximum {}", vault_nav, MAX_TOTAL_NAV),
            timestamp: Clock::get()?.unix_timestamp,
        });
        return Err(error!(ErrorCode::NavTooHigh));
    }
    
    // Calculate shares to mint
    let shares_to_mint = match utils::calculate_shares_to_mint(
        amount,
        deposit_fee,
        vault.total_shares,
        vault_nav,
    ) {
        Ok(shares) => shares,
        Err(e) => {
            vault.reentrancy_guard = false;
            return Err(e);
        }
    };
    
    // 🔒 VALIDATE SHARE PRICE BOUNDS
    if vault.total_shares > 0 && vault_nav > 0 {
        let share_price = vault_nav.checked_div(vault.total_shares).unwrap_or(0);
        if share_price < MIN_SHARE_PRICE || share_price > MAX_SHARE_PRICE {
            vault.reentrancy_guard = false;
            emit!(crate::state::SecurityEvent {
                event_type: crate::state::SecurityEventType::ArithmeticSafetyViolation,
                severity: crate::state::SecuritySeverity::High,
                vault: vault_key,
                details: format!("Share price {} out of bounds [{}, {}]", share_price, MIN_SHARE_PRICE, MAX_SHARE_PRICE),
                timestamp: Clock::get()?.unix_timestamp,
            });
            return Err(error!(ErrorCode::SharePriceOutOfBounds));
        }
    }
    
    // Transfer deposit fee to treasury
    if let Err(e) = token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_usdc_token.to_account_info(),
                to: ctx.accounts.treasury_usdc_token.to_account_info(),
                authority: user.to_account_info(),
            },
        ),
        deposit_fee,
    ) {
        vault.reentrancy_guard = false;
        return Err(e.into());
    }
    
    // Transfer remaining amount to vault
    let amount_after_fee = amount.checked_sub(deposit_fee).unwrap();
    if let Err(e) = token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_usdc_token.to_account_info(),
                to: ctx.accounts.vault_usdc_token.to_account_info(),
                authority: user.to_account_info(),
            },
        ),
        amount_after_fee,
    ) {
        vault.reentrancy_guard = false;
        return Err(e.into());
    }
    
    // Mint share tokens to user
    let vault_authority_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[vault.authority_bump],
    ];
    
    if let Err(e) = token::mint_to(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            MintTo {
                mint: ctx.accounts.shares_mint.to_account_info(),
                to: ctx.accounts.user_shares_token.to_account_info(),
                authority: ctx.accounts.vault_authority.to_account_info(),
            },
            &[vault_authority_seeds],
        ),
        shares_to_mint,
    ) {
        vault.reentrancy_guard = false;
        return Err(e.into());
    }
    
    // 🔒 CRITICAL: Freeze user's share token account to make shares non-transferable
    if let Err(e) = token::freeze_account(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            FreezeAccount {
                account: ctx.accounts.user_shares_token.to_account_info(),
                mint: ctx.accounts.shares_mint.to_account_info(),
                authority: ctx.accounts.vault_authority.to_account_info(),
            },
            &[vault_authority_seeds],
        ),
    ) {
        vault.reentrancy_guard = false;
        return Err(e.into());
    }
    
    // Update vault state
    vault.total_shares = vault.total_shares
        .checked_add(shares_to_mint)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Update user position
    user_position.total_deposits_usdc = user_position.total_deposits_usdc
        .checked_add(amount)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    user_position.last_deposit_timestamp = Clock::get()?.unix_timestamp;
    
    // 🔒 CLEAR REENTRANCY GUARD BEFORE EMITTING EVENTS
    vault.reentrancy_guard = false;
    
    // Emit deposit event
    emit!(crate::state::Deposit {
        user: user.key(),
        vault: vault_key,
        amount,
        shares: shares_to_mint,
        fee: deposit_fee,
        user_tier: 2, // Default tier 2 - actual tier validation happens in verify_tier_and_check_cap
        share_price: if vault.total_shares > 0 { vault_nav / vault.total_shares } else { 1_000_000 }, // 1 USDC default
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!(
        "🔒 Secure deposit: {} USDC with fee {}, minted {} shares (frozen). Total shares: {}",
        amount_after_fee,
        deposit_fee,
        shares_to_mint,
        vault.total_shares
    );
    
    Ok(())
} 