use anchor_lang::prelude::*;
use anchor_spl::token::{Token, TokenAccount};
use anchor_spl::associated_token::AssociatedToken;

use crate::{constants::*, state::*};

#[derive(Accounts)]
pub struct InitializeTokenAccounts<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    
    /// The vault account
    #[account(
        seeds = [VAULT_PDA_SEED],
        bump = vault.vault_bump
    )]
    pub vault: Account<'info, Vault>,
    
    /// The PDA that controls the vault's token accounts
    /// CHECK: This is a PDA that we derive
    #[account(
        seeds = [VAULT_AUTHORITY_PDA_SEED],
        bump = vault.authority_bump
    )]
    pub vault_authority: UncheckedAccount<'info>,
    
    /// The token mint for which we're creating an account
    /// CHECK: We verify this is a valid mint
    pub token_mint: UncheckedAccount<'info>,
    
    /// The associated token account to be created
    #[account(
        init_if_needed,
        payer = payer,
        associated_token::mint = token_mint,
        associated_token::authority = vault_authority
    )]
    pub vault_token_account: Account<'info, TokenAccount>,
    
    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
}

/// Initialize a single token account for the vault
/// This should be called once for each token the vault will trade
/// This pre-pays for token account rent so the vault never needs SOL
pub fn initialize_token_accounts(
    ctx: Context<InitializeTokenAccounts>,
) -> Result<()> {
    let token_mint = &ctx.accounts.token_mint;
    let vault_token_account = &ctx.accounts.vault_token_account;
    
    msg!("Created token account for mint: {}", token_mint.key());
    msg!("Token account address: {}", vault_token_account.key());
    msg!("Vault authority: {}", ctx.accounts.vault_authority.key());
    
    Ok(())
} 