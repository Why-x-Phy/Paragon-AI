use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, MintTo, Transfer, FreezeAccount};
use anchor_spl::associated_token::AssociatedToken;

use crate::{constants::*, state::*, utils, ErrorCode};

#[derive(Accounts)]
#[instruction(amount: u64)]
pub struct Deposit<'info> {
    #[account(mut)]
    pub user: Signer<'info>,
    
    /// The vault account 
    #[account(
        mut,
        constraint = !vault.paused @ ErrorCode::VaultPaused,
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
    let user_position = &mut ctx.accounts.user_position;
    let user = &ctx.accounts.user;
    
    // Initialize user position if it's new
    if user_position.user_authority == Pubkey::default() {
        user_position.user_authority = user.key();
        user_position.vault = vault.key();
        user_position.total_deposits_usdc = 0;
        user_position.last_deposit_timestamp = Clock::get()?.unix_timestamp;
        user_position.bump = ctx.bumps.user_position;
    }
    
    // Verify user's tier and check deposit caps via staking program
    utils::verify_tier_and_check_cap(
        &ctx.accounts.staking_program.to_account_info(),
        &user.key(),
        user_position.total_deposits_usdc,
        amount,
        vault,
        &ctx.remaining_accounts,
    )?;
    
    // Calculate deposit fee
    let deposit_fee = utils::calculate_deposit_fee(amount)?;
    
    // Get current NAV (for calculating shares)
    let vault_nav = utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        &[],  // Only USDC for a simple implementation
        &[],  // No price accounts needed for now
        &[],  // No token mints needed for now
    )?;
    
    // Calculate shares to mint
    let shares_to_mint = utils::calculate_shares_to_mint(
        amount,
        deposit_fee,
        vault.total_shares,
        vault_nav,
    )?;
    
    // Transfer deposit fee to treasury
    token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_usdc_token.to_account_info(),
                to: ctx.accounts.treasury_usdc_token.to_account_info(),
                authority: user.to_account_info(),
            },
        ),
        deposit_fee,
    )?;
    
    // Transfer remaining amount to vault
    let amount_after_fee = amount.checked_sub(deposit_fee).unwrap();
    token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_usdc_token.to_account_info(),
                to: ctx.accounts.vault_usdc_token.to_account_info(),
                authority: user.to_account_info(),
            },
        ),
        amount_after_fee,
    )?;
    
    // Mint share tokens to user
    let vault_authority_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[vault.authority_bump],
    ];
    
    token::mint_to(
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
    )?;
    
    // 🔒 CRITICAL: Freeze user's share token account to make shares non-transferable
    token::freeze_account(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            FreezeAccount {
                account: ctx.accounts.user_shares_token.to_account_info(),
                mint: ctx.accounts.shares_mint.to_account_info(),
                authority: ctx.accounts.vault_authority.to_account_info(),
            },
            &[vault_authority_seeds],
        ),
    )?;
    
    // Update vault state
    vault.total_shares = vault.total_shares
        .checked_add(shares_to_mint)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Update user position
    user_position.total_deposits_usdc = user_position.total_deposits_usdc
        .checked_add(amount)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    user_position.last_deposit_timestamp = Clock::get()?.unix_timestamp;
    
    // Emit deposit event
    emit!(crate::state::Deposit {
        user: user.key(),
        amount,
        shares: shares_to_mint,
        fee: deposit_fee,
    });
    
    msg!(
        "Deposited {} USDC with fee {}, minted {} shares (frozen). Total shares: {}",
        amount_after_fee,
        deposit_fee,
        shares_to_mint,
        vault.total_shares
    );
    
    Ok(())
} 