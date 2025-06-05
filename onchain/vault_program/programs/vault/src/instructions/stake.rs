use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};
use anchor_spl::associated_token::AssociatedToken;

use crate::{constants::*, state::*};

#[derive(Accounts)]
#[instruction(amount: u64, nft_count: u8)]
pub struct Stake<'info> {
    #[account(mut)]
    pub user: Signer<'info>,
    
    /// The vault account
    pub vault: Account<'info, Vault>,
    
    /// The staker account that tracks the user's staked tokens
    #[account(
        init_if_needed,
        payer = user,
        space = Staker::SIZE,
        seeds = [STAKER_PDA_SEED, user.key().as_ref(), vault.key().as_ref()],
        bump,
    )]
    pub staker: Account<'info, Staker>,
    
    /// The user's token account for CALVIN
    #[account(
        mut,
        constraint = user_calvin_token.mint == vault.calvin_mint,
        constraint = user_calvin_token.owner == user.key(),
    )]
    pub user_calvin_token: Account<'info, TokenAccount>,
    
    /// The token account that will hold the staked CALVIN tokens
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = calvin_mint,
        associated_token::authority = vault_authority,
    )]
    pub stake_account: Account<'info, TokenAccount>,
    
    /// The CALVIN token mint
    #[account(
        address = vault.calvin_mint,
    )]
    pub calvin_mint: Account<'info, Mint>,
    
    /// The USDC token mint
    #[account(
        address = vault.usdc_mint,
    )]
    pub usdc_mint: Account<'info, Mint>,
    
    /// The user's USDC token account
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = usdc_mint,
        associated_token::authority = user,
    )]
    pub user_usdc_token: Account<'info, TokenAccount>,
    
    /// The share token mint
    #[account(
        address = vault.shares_mint,
    )]
    pub shares_mint: Account<'info, Mint>,
    
    /// The user's share token account
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = shares_mint,
        associated_token::authority = user,
    )]
    pub user_shares_token: Account<'info, TokenAccount>,
    
    /// The vault's authority PDA
    /// CHECK: This is a PDA verified using seeds
    #[account(
        seeds = [VAULT_AUTHORITY_PDA_SEED],
        bump = vault.authority_bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,
    
    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn stake(ctx: Context<Stake>, amount: u64, nft_count: u8) -> Result<()> {
    let staker = &mut ctx.accounts.staker;
    let vault = &ctx.accounts.vault;
    let user = &ctx.accounts.user;
    
    // Initialize staker account if it's new
    if staker.bump == 0 {
        staker.user = user.key();
        staker.vault = vault.key();
        staker.bump = *ctx.bumps.get("staker").unwrap();
        staker.shares_account = ctx.accounts.user_shares_token.key();
        staker.usdc_account = ctx.accounts.user_usdc_token.key();
        staker.stake_account = ctx.accounts.stake_account.key();
        staker.total_deposits = 0;
    }
    
    // Transfer CALVIN tokens to the stake account
    anchor_spl::token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            anchor_spl::token::Transfer {
                from: ctx.accounts.user_calvin_token.to_account_info(),
                to: ctx.accounts.stake_account.to_account_info(),
                authority: user.to_account_info(),
            },
        ),
        amount,
    )?;
    
    // Update staker's staked amount and NFT count
    staker.staked_amount = ctx.accounts.stake_account.amount;
    staker.nft_count = nft_count;
    
    msg!("User staked {} CALVIN tokens with {} NFTs", amount, nft_count);
    
    Ok(())
} 