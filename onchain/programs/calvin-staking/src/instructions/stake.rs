use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer, MintTo};
use anchor_spl::associated_token::AssociatedToken;

use crate::{constants::*, state::*, errors::*};

#[derive(Accounts)]
#[instruction(amount: u64)]
pub struct StakeCalvin<'info> {
    /// User staking CALVIN tokens
    #[account(mut)]
    pub user: Signer<'info>,

    /// Global staking configuration
    #[account(
        seeds = [STAKE_CONFIG_SEED],
        bump = stake_config.bump,
        constraint = !stake_config.paused @ StakingError::StakingPaused,
    )]
    pub stake_config: Account<'info, StakeConfig>,

    /// Stake vault account
    #[account(
        mut,
        seeds = [STAKE_VAULT_SEED],
        bump = stake_vault.bump,
    )]
    pub stake_vault: Account<'info, StakeVault>,

    /// User's stake account (created if it doesn't exist)
    #[account(
        init_if_needed,
        payer = user,
        space = UserStake::SIZE,
        seeds = [USER_STAKE_SEED, user.key().as_ref()],
        bump
    )]
    pub user_stake: Account<'info, UserStake>,

    /// User's CALVIN token account
    #[account(
        mut,
        constraint = user_calvin_token.mint == stake_config.calvin_mint @ StakingError::InvalidCalvinMint,
        constraint = user_calvin_token.owner == user.key(),
        constraint = user_calvin_token.amount >= amount @ StakingError::InsufficientStakedAmount,
    )]
    pub user_calvin_token: Account<'info, TokenAccount>,

    /// Stake vault's CALVIN token account (receives staked tokens)
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = calvin_mint,
        associated_token::authority = stake_vault,
    )]
    pub stake_vault_calvin_token: Account<'info, TokenAccount>,

    /// CALVIN token mint
    #[account(
        address = stake_config.calvin_mint,
    )]
    pub calvin_mint: Account<'info, Mint>,

    /// Global Vault Pass mint
    #[account(
        mut,
        address = stake_vault.vault_pass_mint,
    )]
    pub vault_pass_mint: Account<'info, Mint>,

    /// User's personal Vault Pass mint (one per user, non-transferable)
    #[account(
        init_if_needed,
        payer = user,
        mint::decimals = VAULT_PASS_DECIMALS,
        mint::authority = stake_config,
        mint::freeze_authority = stake_config,
        seeds = [VAULT_PASS_MINT_SEED, user.key().as_ref()],
        bump
    )]
    pub user_vault_pass_mint: Account<'info, Mint>,

    /// User's Vault Pass token account (holds their non-transferable tokens)
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = user_vault_pass_mint,
        associated_token::authority = user,
    )]
    pub user_vault_pass_token: Account<'info, TokenAccount>,

    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn stake_calvin(ctx: Context<StakeCalvin>, amount: u64) -> Result<()> {
    if amount == 0 {
        return Err(error!(StakingError::ZeroStakeAmount));
    }

    let user_stake = &mut ctx.accounts.user_stake;
    let stake_vault = &mut ctx.accounts.stake_vault;
    let stake_config = &ctx.accounts.stake_config;

    // Initialize user stake account if it's new
    if user_stake.user_authority == Pubkey::default() {
        user_stake.user_authority = ctx.accounts.user.key();
        user_stake.total_staked = 0;
        user_stake.vault_pass_mint = ctx.accounts.user_vault_pass_mint.key();
        user_stake.tier = DEFAULT_TIER;
        user_stake.last_stake_timestamp = Clock::get()?.unix_timestamp;
        user_stake.bump = ctx.bumps.user_stake;
    }

    // Transfer CALVIN tokens from user to stake vault
    token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_calvin_token.to_account_info(),
                to: ctx.accounts.stake_vault_calvin_token.to_account_info(),
                authority: ctx.accounts.user.to_account_info(),
            },
        ),
        amount,
    )?;

    // Update user's staked amount
    user_stake.total_staked = user_stake.total_staked
        .checked_add(amount)
        .ok_or(StakingError::ArithmeticError)?;

    // Update stake vault totals
    stake_vault.total_staked = stake_vault.total_staked
        .checked_add(amount)
        .ok_or(StakingError::ArithmeticError)?;

    // Calculate new tier based on total staked amount
    let new_tier = calculate_tier(user_stake.total_staked, &stake_config.tier_thresholds);
    user_stake.tier = new_tier;

    // Update timestamp
    user_stake.last_stake_timestamp = Clock::get()?.unix_timestamp;

    // Mint Vault Pass tokens to represent the user's staked amount
    // Convert from CALVIN decimals (6) to Vault Pass decimals (0)
    let vault_pass_amount = amount / 1_000_000; // Convert from micro-CALVIN to whole CALVIN
    
    let stake_config_seeds = &[
        STAKE_CONFIG_SEED,
        &[stake_config.bump],
    ];

    token::mint_to(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            MintTo {
                mint: ctx.accounts.user_vault_pass_mint.to_account_info(),
                to: ctx.accounts.user_vault_pass_token.to_account_info(),
                authority: ctx.accounts.stake_config.to_account_info(),
            },
            &[stake_config_seeds],
        ),
        vault_pass_amount, // Mint Vault Pass tokens equal to whole CALVIN amount
    )?;

    // Update total vault passes minted
    stake_vault.total_vault_passes = stake_vault.total_vault_passes
        .checked_add(vault_pass_amount)
        .ok_or(StakingError::ArithmeticError)?;

    // Emit stake event
    emit!(StakeEvent {
        user: ctx.accounts.user.key(),
        amount,
        new_total: user_stake.total_staked,
        tier: new_tier,
        vault_pass_mint: ctx.accounts.user_vault_pass_mint.key(),
    });

    msg!(
        "User {} staked {} CALVIN tokens. Total staked: {}, Tier: {}",
        ctx.accounts.user.key(),
        amount,
        user_stake.total_staked,
        new_tier
    );

    Ok(())
}

/// Calculate tier based on staked amount
fn calculate_tier(staked_amount: u64, thresholds: &[u64; 4]) -> u8 {
    if staked_amount >= thresholds[0] {
        VAULT_KEEPER_TIER
    } else if staked_amount >= thresholds[1] {
        TIER_2
    } else if staked_amount >= thresholds[2] {
        TIER_3
    } else {
        DEFAULT_TIER
    }
} 