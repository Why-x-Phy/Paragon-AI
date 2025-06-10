use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};

use crate::{constants::*, state::*, utils, ErrorCode};

#[derive(Accounts)]
pub struct Trade<'info> {
    /// Only Calvin AI can execute trades
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account
    #[account(
        mut,
        constraint = !vault.paused @ ErrorCode::VaultPaused,
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
    
    /// The Jupiter program
    /// CHECK: This is the Jupiter program ID, verified against the vault's config
    #[account(
        address = vault.jupiter_program_id,
    )]
    pub jupiter_program: UncheckedAccount<'info>,
    
    /// The token program
    pub token_program: Program<'info, Token>,
    
    /// The system program
    pub system_program: Program<'info, System>,
    
    /// The rent sysvar
    pub rent: Sysvar<'info, Rent>,
    
    /// All remaining accounts are passed to Jupiter as is
    /// CHECK: These are verified by the Jupiter program
    #[account(mut)]
    pub remaining_accounts: UncheckedAccount<'info>,
}

pub fn trade(ctx: Context<Trade>, data: Vec<u8>) -> Result<()> {
    // Get accounts
    let vault = &mut ctx.accounts.vault;
    
    // Only Calvin AI can execute trades
    if ctx.accounts.authority.key() != vault.calvin_authority {
        return Err(error!(ErrorCode::UnauthorizedCalvin));
    }
    
    // Get amount to trade (from the source token account)
    let amount_in = ctx.accounts.source_token_account.amount;
    
    // Record destination balance before swap
    let destination_balance_before = ctx.accounts.destination_token_account.amount;
    
    // Get all accounts to pass to Jupiter
    let mut accounts = vec![
        ctx.accounts.jupiter_program.to_account_info(),
        ctx.accounts.source_token_account.to_account_info(),
        ctx.accounts.destination_token_account.to_account_info(),
        ctx.accounts.vault_authority.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
        ctx.accounts.system_program.to_account_info(),
        ctx.accounts.rent.to_account_info(),
    ];
    
    // Add remaining accounts
    accounts.push(ctx.accounts.remaining_accounts.to_account_info());
    
    // Prepare vault authority seeds for signing
    let vault_authority_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[vault.authority_bump],
    ];
    
    // Forward trade to Jupiter
    utils::forward_jupiter(
        ctx.accounts.jupiter_program.to_account_info(),
        &accounts,
        data,
        &[vault_authority_seeds],
    )?;
    
    // Calculate amount received (reload the account to get updated balance)
    ctx.accounts.destination_token_account.reload()?;
    let destination_balance_after = ctx.accounts.destination_token_account.amount;
    let amount_out = destination_balance_after
        .checked_sub(destination_balance_before)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Get current NAV including the new token positions
    let new_nav = utils::current_nav_usdc(
        vault,
        &ctx.accounts.vault_usdc_token,
        &[
            ctx.accounts.source_token_account.clone(),
            ctx.accounts.destination_token_account.clone(),
        ],
        &[],  // Price accounts would go here in a real implementation
        &[
            ctx.accounts.source_mint.key(),
            ctx.accounts.destination_mint.key(),
        ],
    )?;
    
    // Update vault state (high water mark, etc.)
    utils::after_trade(vault, new_nav)?;
    
    // Emit trade event
    emit!(state::Trade {
        vault: vault.key(),
        source_mint: ctx.accounts.source_mint.key(),
        destination_mint: ctx.accounts.destination_mint.key(),
        amount_in,
        amount_out,
    });
    
    msg!(
        "Traded {} of mint {} for {} of mint {}",
        amount_in,
        ctx.accounts.source_mint.key(),
        amount_out,
        ctx.accounts.destination_mint.key()
    );
    
    Ok(())
} 