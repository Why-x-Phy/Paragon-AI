use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Burn, Transfer};

use crate::{constants::*, state::*, utils, ErrorCode};

#[derive(Accounts)]
#[instruction(shares: u64)]
pub struct Withdraw<'info> {
    #[account(mut)]
    pub user: Signer<'info>,
    
    /// The vault account
    #[account(mut)]
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
        constraint = user_shares_token.amount >= shares @ ErrorCode::InsufficientShares,
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

pub fn withdraw(ctx: Context<Withdraw>, shares: u64) -> Result<()> {
    // Get accounts
    let vault = &mut ctx.accounts.vault;
    let staker = &mut ctx.accounts.staker;
    let user = &ctx.accounts.user;
    
    // Get current NAV (for calculating withdrawal amount)
    let vault_nav = utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        &[],  // Only USDC for a simple implementation
        &[],  // No price accounts needed for now
        &[],  // No token mints needed for now
    )?;
    
    // Calculate USDC amount to withdraw
    let usdc_amount = utils::calculate_usdc_to_withdraw(shares, vault.total_shares, vault_nav)?;
    
    // Check if the vault has enough USDC liquidity
    if usdc_amount > ctx.accounts.vault_usdc_token.amount {
        // If not enough liquidity, emit NeedLiquidity event and return error
        emit!(NeedLiquidity {
            vault: vault.key(),
            required_amount: usdc_amount,
        });
        return Err(error!(ErrorCode::InsufficientLiquidity));
    }
    
    // Burn share tokens
    let vault_authority_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[vault.authority_bump],
    ];
    
    token::burn(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Burn {
                mint: ctx.accounts.shares_mint.to_account_info(),
                from: ctx.accounts.user_shares_token.to_account_info(),
                authority: ctx.accounts.user.to_account_info(),
            },
            &[],
        ),
        shares,
    )?;
    
    // Transfer USDC from vault to user
    token::transfer(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.vault_usdc_token.to_account_info(),
                to: ctx.accounts.user_usdc_token.to_account_info(),
                authority: ctx.accounts.vault_authority.to_account_info(),
            },
            &[vault_authority_seeds],
        ),
        usdc_amount,
    )?;
    
    // Update vault state
    vault.total_shares = vault.total_shares
        .checked_sub(shares)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Emit withdraw event
    emit!(state::Withdraw {
        user: user.key(),
        amount: usdc_amount,
        shares,
    });
    
    msg!(
        "Withdrawn {} USDC by burning {} shares. Remaining shares: {}",
        usdc_amount,
        shares,
        vault.total_shares
    );
    
    Ok(())
} 