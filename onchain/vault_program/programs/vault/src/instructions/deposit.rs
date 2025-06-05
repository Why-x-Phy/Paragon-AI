use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, MintTo, Transfer};

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
    
    /// The user's staker account
    #[account(
        mut,
        seeds = [STAKER_PDA_SEED, user.key().as_ref(), vault.key().as_ref()],
        bump = staker.bump,
        constraint = staker.user == user.key(),
        constraint = staker.vault == vault.key(),
    )]
    pub staker: Account<'info, Staker>,
    
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
    
    /// The user's share token account
    #[account(
        mut,
        constraint = user_shares_token.mint == vault.shares_mint,
        constraint = user_shares_token.owner == user.key(),
    )]
    pub user_shares_token: Account<'info, TokenAccount>,
    
    /// The vault's authority PDA
    /// CHECK: This is a PDA that we derive and verify using seeds
    #[account(
        seeds = [VAULT_AUTHORITY_PDA_SEED],
        bump = vault.authority_bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,
    
    pub token_program: Program<'info, Token>,
}

pub fn deposit(ctx: Context<Deposit>, amount: u64) -> Result<()> {
    // Get accounts
    let vault = &mut ctx.accounts.vault;
    let staker = &mut ctx.accounts.staker;
    let user = &ctx.accounts.user;
    
    // Check that the user meets the deposit cap requirements
    utils::check_tier_cap(staker, vault, amount)?;
    
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
    
    // Update vault state
    vault.total_shares = vault.total_shares
        .checked_add(shares_to_mint)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Update staker's total deposits
    staker.total_deposits = staker.total_deposits
        .checked_add(amount)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Emit deposit event
    emit!(state::Deposit {
        user: user.key(),
        amount,
        shares: shares_to_mint,
        fee: deposit_fee,
    });
    
    msg!(
        "Deposited {} USDC with fee {}, minted {} shares. Total shares: {}",
        amount_after_fee,
        deposit_fee,
        shares_to_mint,
        vault.total_shares
    );
    
    Ok(())
} 