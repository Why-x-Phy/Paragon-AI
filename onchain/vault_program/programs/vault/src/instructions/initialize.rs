use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};
use anchor_spl::associated_token::AssociatedToken;

use crate::{constants::*, state::*};

#[derive(Accounts)]
#[instruction(per_nft_cap: u64, jupiter_program_id: Pubkey)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub owner: Signer<'info>,
    
    /// The USDC mint
    pub usdc_mint: Account<'info, Mint>,
    
    /// The CALVIN token mint
    pub calvin_mint: Account<'info, Mint>,
    
    /// The vault account that holds the state
    #[account(
        init,
        payer = owner,
        space = Vault::SIZE,
        seeds = [VAULT_PDA_SEED],
        bump
    )]
    pub vault: Account<'info, Vault>,
    
    /// The vault's token account for holding USDC
    #[account(
        init_if_needed,
        payer = owner,
        associated_token::mint = usdc_mint,
        associated_token::authority = vault_authority,
    )]
    pub usdc_vault: Account<'info, TokenAccount>,
    
    /// The PDA that controls the vault's token accounts
    /// CHECK: This is a PDA that we derive
    #[account(
        seeds = [VAULT_AUTHORITY_PDA_SEED],
        bump
    )]
    pub vault_authority: UncheckedAccount<'info>,
    
    /// The mint for share tokens
    #[account(
        init,
        payer = owner,
        mint::decimals = usdc_mint.decimals,
        mint::authority = vault_authority,
        seeds = [SHARES_MINT_PDA_SEED],
        bump
    )]
    pub shares_mint: Account<'info, Mint>,
    
    /// The treasury that receives fees
    /// CHECK: This is just a pubkey that will receive fees
    pub treasury: UncheckedAccount<'info>,
    
    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn initialize(
    ctx: Context<Initialize>,
    per_nft_cap: u64,
    jupiter_program_id: Pubkey,
) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    
    // Initialize vault state
    vault.owner = ctx.accounts.owner.key();
    vault.shares_mint = ctx.accounts.shares_mint.key();
    vault.usdc_mint = ctx.accounts.usdc_mint.key();
    vault.usdc_vault = ctx.accounts.usdc_vault.key();
    vault.vault_authority = ctx.accounts.vault_authority.key();
    vault.calvin_mint = ctx.accounts.calvin_mint.key();
    vault.treasury = ctx.accounts.treasury.key();
    vault.per_nft_cap = per_nft_cap;
    vault.high_water_mark_nav = 0;
    vault.total_shares = 0;
    vault.paused = false;
    vault.jupiter_program_id = jupiter_program_id;
    
    // Store bumps for PDAs
    vault.vault_bump = *ctx.bumps.get("vault").unwrap();
    vault.shares_mint_bump = *ctx.bumps.get("shares_mint").unwrap();
    vault.authority_bump = *ctx.bumps.get("vault_authority").unwrap();
    
    msg!("Vault initialized with per_nft_cap: {}", per_nft_cap);
    
    Ok(())
} 