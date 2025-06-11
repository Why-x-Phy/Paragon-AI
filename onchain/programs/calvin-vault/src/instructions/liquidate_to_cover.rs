use anchor_lang::prelude::*;
use anchor_spl::token::{Token, TokenAccount, Mint};

use crate::{state::*, constants::*, utils, ErrorCode};

#[derive(Accounts)]
pub struct LiquidateToCover<'info> {
    /// Only Calvin AI can execute liquidations
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

    /// The token mint being liquidated
    pub source_mint: Account<'info, Mint>,

    /// The vault's token account to liquidate from
    #[account(
        mut,
        constraint = source_token_account.mint == source_mint.key(),
        constraint = source_token_account.owner == vault_authority.key(),
    )]
    pub source_token_account: Account<'info, TokenAccount>,

    /// PDA authority for the vault
    /// CHECK: PDA authority
    #[account(
        seeds = [VAULT_AUTHORITY_PDA_SEED],
        bump = vault.authority_bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,

    /// Jupiter program for swaps
    /// CHECK: Verified against vault config
    #[account(address = vault.jupiter_program_id)]
    pub jupiter_program: UncheckedAccount<'info>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,

    /// Additional accounts forwarded to Jupiter
    /// CHECK: Accounts are forwarded to Jupiter program and validated by Jupiter's CPI constraints
    #[account(mut)]
    pub remaining_accounts: UncheckedAccount<'info>,
}

pub fn liquidate_to_cover(ctx: Context<LiquidateToCover>, data: Vec<u8>) -> Result<()> {
    // Reuse trade logic to perform the swap into USDC
    // Prepare account infos for Jupiter
    let mut accounts = vec![
        ctx.accounts.jupiter_program.to_account_info(),
        ctx.accounts.source_token_account.to_account_info(),
        ctx.accounts.vault_usdc_token.to_account_info(),
        ctx.accounts.vault_authority.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
        ctx.accounts.system_program.to_account_info(),
        ctx.accounts.rent.to_account_info(),
    ];
    accounts.push(ctx.accounts.remaining_accounts.to_account_info());

    // Signer seeds for vault authority
    let signer_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[ctx.accounts.vault.authority_bump],
    ];

    utils::forward_jupiter(
        ctx.accounts.jupiter_program.to_account_info(),
        &accounts,
        data,
        &[signer_seeds],
        &ctx.accounts.vault_authority.key(),  // ✅ FIXED: Pass vault authority key
    )?;

    Ok(())
}
 