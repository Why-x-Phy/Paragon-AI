use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token};
use anchor_spl::associated_token::AssociatedToken;

use crate::{constants::*, state::*, errors::*};

#[derive(Accounts)]
#[instruction(tier_thresholds: [u64; 4], vault_program_id: Pubkey)]
pub struct InitializeStaking<'info> {
    /// Admin who is initializing the staking program
    #[account(mut)]
    pub admin: Signer<'info>,

    /// Global staking configuration account
    #[account(
        init,
        payer = admin,
        space = StakeConfig::SIZE,
        seeds = [STAKE_CONFIG_SEED],
        bump
    )]
    pub stake_config: Account<'info, StakeConfig>,

    /// Stake vault that will hold all staked CALVIN tokens
    #[account(
        init,
        payer = admin,
        space = StakeVault::SIZE,
        seeds = [STAKE_VAULT_SEED],
        bump
    )]
    pub stake_vault: Account<'info, StakeVault>,

    /// CALVIN token mint
    pub calvin_mint: Account<'info, Mint>,

    /// Global Vault Pass mint for this staking pool
    #[account(
        init,
        payer = admin,
        mint::decimals = VAULT_PASS_DECIMALS,
        mint::authority = stake_config,
        mint::freeze_authority = stake_config,
        seeds = [VAULT_PASS_MINT_SEED],
        bump
    )]
    pub vault_pass_mint: Account<'info, Mint>,

    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn initialize_staking(
    ctx: Context<InitializeStaking>,
    tier_thresholds: [u64; 4],
    vault_program_id: Pubkey,
) -> Result<()> {
    // Validate tier thresholds are in descending order
    if tier_thresholds[0] < tier_thresholds[1] 
        || tier_thresholds[1] < tier_thresholds[2] 
        || tier_thresholds[2] < tier_thresholds[3] {
        return Err(error!(StakingError::InvalidTierThresholds));
    }

    let stake_config = &mut ctx.accounts.stake_config;
    let stake_vault = &mut ctx.accounts.stake_vault;

    // Initialize stake configuration
    stake_config.admin_authority = ctx.accounts.admin.key();
    stake_config.vault_program_id = vault_program_id;
    stake_config.tier_thresholds = tier_thresholds;
    stake_config.paused = false;
    stake_config.calvin_mint = ctx.accounts.calvin_mint.key();
    stake_config.bump = *ctx.bumps.get("stake_config").unwrap();

    // Initialize stake vault
    stake_vault.total_staked = 0;
    stake_vault.total_vault_passes = 0;
    stake_vault.calvin_mint = ctx.accounts.calvin_mint.key();
    stake_vault.vault_pass_mint = ctx.accounts.vault_pass_mint.key();
    stake_vault.bump = *ctx.bumps.get("stake_vault").unwrap();

    msg!(
        "Calvin Staking Program initialized with tier thresholds: [{}, {}, {}, {}]",
        tier_thresholds[0],
        tier_thresholds[1], 
        tier_thresholds[2],
        tier_thresholds[3]
    );

    msg!("Vault program ID: {}", vault_program_id);
    msg!("CALVIN mint: {}", ctx.accounts.calvin_mint.key());
    msg!("Vault Pass mint: {}", ctx.accounts.vault_pass_mint.key());

    Ok(())
} 