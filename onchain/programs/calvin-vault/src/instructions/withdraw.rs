use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Burn, Transfer, ThawAccount, FreezeAccount};

use crate::{constants::*, state::*, utils, ErrorCode};

#[derive(Accounts)]
#[instruction(shares: u64)]
pub struct Withdraw<'info> {
    #[account(mut)]
    pub user: Signer<'info>,
    
    /// The vault account
    #[account(mut)]
    pub vault: Box<Account<'info, Vault>>,
    
    /// User's vault position account
    #[account(
        mut,
        seeds = [USER_POSITION_PDA_SEED, user.key().as_ref(), vault.key().as_ref()],
        bump = user_position.bump,
        constraint = user_position.user_authority == user.key(),
        constraint = user_position.vault == vault.key(),
    )]
    pub user_position: Box<Account<'info, UserPosition>>,
    
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
    
    /// The user's share token account (frozen, needs to be thawed for burning)
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
    let user_position = &mut ctx.accounts.user_position;
    let user = &ctx.accounts.user;
    
        // Get current NAV (for calculating withdrawal amount)
    // nav_accounts format: groups of 3 [token_account, price_account, mint_account, ...]
    
    let vault_nav = utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        &ctx.remaining_accounts,
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
    
    let vault_authority_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[vault.authority_bump],
    ];
    
    // 🎯 ADJUST HIGH WATER MARK PROPORTIONALLY
    if vault.total_shares > 0 {
        let remaining_shares = vault.total_shares.saturating_sub(shares);
        vault.high_water_mark_nav = vault.high_water_mark_nav
            .saturating_mul(remaining_shares)
            .saturating_div(vault.total_shares);
    }
    
    // Thaw the user's share account temporarily to allow burning
    token::thaw_account(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            ThawAccount {
                account: ctx.accounts.user_shares_token.to_account_info(),
                mint: ctx.accounts.shares_mint.to_account_info(),
                authority: ctx.accounts.vault_authority.to_account_info(),
            },
            &[vault_authority_seeds],
        ),
    )?;
    
    // Burn share tokens
    token::burn(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Burn {
                mint: ctx.accounts.shares_mint.to_account_info(),
                from: ctx.accounts.user_shares_token.to_account_info(),
                authority: ctx.accounts.user.to_account_info(),
            },
        ),
        shares,
    )?;
    
    // Re-freeze the account if there are remaining shares
    let remaining_shares = ctx.accounts.user_shares_token.amount - shares;
    if remaining_shares > 0 {
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
    }
    
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
    
    // Update user position to reflect partial withdrawal
    let usdc_withdrawn_ratio = shares as f64 / (ctx.accounts.user_shares_token.amount as f64);
    let deposits_to_reduce = (user_position.total_deposits_usdc as f64 * usdc_withdrawn_ratio) as u64;
    user_position.total_deposits_usdc = user_position.total_deposits_usdc
        .checked_sub(deposits_to_reduce)
        .unwrap_or(0);
    
    // Emit withdraw event
    emit!(crate::state::Withdraw {
        user: user.key(),
        vault: vault.key(),
        amount: usdc_amount,
        shares,
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!(
        "Withdrawn {} USDC by burning {} shares. Remaining shares: {}",
        usdc_amount,
        shares,
        vault.total_shares
    );
    
    Ok(())
} 