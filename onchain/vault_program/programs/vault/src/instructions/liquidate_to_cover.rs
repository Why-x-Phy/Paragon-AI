use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};

use crate::{constants::*, state::*, utils, ErrorCode};

#[derive(Accounts)]
pub struct LiquidateToCover<'info> {
    /// Only Calvin AI can execute liquidations
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    
    /// The vault's USDC token account
    #[account(
        mut,
        constraint = vault_usdc_token.mint == vault.usdc_mint,
        constraint = vault_usdc_token.owner == vault_authority.key(),
    )]
    pub vault_usdc_token: Account<'info, TokenAccount>,
    
    /// The token mint to liquidate (sell for USDC)
    pub token_mint: Account<'info, Mint>,
    
    /// The vault's token account holding the asset to liquidate
    #[account(
        mut,
        constraint = token_account.mint == token_mint.key(),
        constraint = token_account.owner == vault_authority.key(),
    )]
    pub token_account: Account<'info, TokenAccount>,
    
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

pub fn liquidate_to_cover(ctx: Context<LiquidateToCover>, data: Vec<u8>) -> Result<()> {
    // Get accounts
    let vault = &mut ctx.accounts.vault;
    
    // Only Calvin AI can execute liquidations
    // In a production environment, you would have a more robust verification
    // This is a simplified implementation for demonstration
    if ctx.accounts.authority.key() != vault.owner {
        return Err(error!(ErrorCode::UnauthorizedCalvin));
    }
    
    // Get amount to liquidate (from the token account)
    let amount_in = ctx.accounts.token_account.amount;
    
    // Record USDC balance before swap
    let usdc_balance_before = ctx.accounts.vault_usdc_token.amount;
    
    // Get all accounts to pass to Jupiter
    let mut accounts = vec![
        ctx.accounts.jupiter_program.to_account_info(),
        ctx.accounts.token_account.to_account_info(),
        ctx.accounts.vault_usdc_token.to_account_info(),
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
    
    // Forward liquidation to Jupiter (sell token for USDC)
    utils::forward_jupiter(
        ctx.accounts.jupiter_program.to_account_info(),
        &accounts,
        data,
        &[vault_authority_seeds],
    )?;
    
    // Calculate USDC received
    let usdc_balance_after = ctx.accounts.vault_usdc_token.reload()?;
    let usdc_received = usdc_balance_after.amount
        .checked_sub(usdc_balance_before)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Get current NAV after liquidation
    let new_nav = utils::current_nav_usdc(
        vault,
        &usdc_balance_after,
        &[ctx.accounts.token_account.clone()],
        &[],  // Price accounts would go here in a real implementation
        &[ctx.accounts.token_mint.key()],
    )?;
    
    // Update vault state
    utils::after_trade(vault, new_nav)?;
    
    // Emit liquidation event
    emit!(state::Liquidate {
        vault: vault.key(),
        token_mint: ctx.accounts.token_mint.key(),
        amount: amount_in,
        usdc_received,
    });
    
    msg!(
        "Liquidated {} of token mint {} for {} USDC",
        amount_in,
        ctx.accounts.token_mint.key(),
        usdc_received
    );
    
    Ok(())
} 