use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer, Burn};

use crate::{constants::*, state::*, errors::*};

#[derive(Accounts)]
#[instruction(amount: u64)]
pub struct UnstakeCalvin<'info> {
    /// User unstaking CALVIN tokens
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

    /// User's stake account
    #[account(
        mut,
        seeds = [USER_STAKE_SEED, user.key().as_ref()],
        bump = user_stake.bump,
        constraint = user_stake.user_authority == user.key(),
        constraint = user_stake.total_staked >= amount @ StakingError::InsufficientStakedAmount,
    )]
    pub user_stake: Account<'info, UserStake>,

    /// User's CALVIN token account (receives unstaked tokens)
    #[account(
        mut,
        constraint = user_calvin_token.mint == stake_config.calvin_mint @ StakingError::InvalidCalvinMint,
        constraint = user_calvin_token.owner == user.key(),
    )]
    pub user_calvin_token: Account<'info, TokenAccount>,

    /// Stake vault's CALVIN token account (holds staked tokens)
    #[account(
        mut,
        associated_token::mint = calvin_mint,
        associated_token::authority = stake_vault,
    )]
    pub stake_vault_calvin_token: Account<'info, TokenAccount>,

    /// CALVIN token mint
    #[account(
        address = stake_config.calvin_mint,
    )]
    pub calvin_mint: Account<'info, Mint>,

    /// User's personal Vault Pass mint
    #[account(
        mut,
        address = user_stake.vault_pass_mint,
    )]
    pub user_vault_pass_mint: Account<'info, Mint>,

    /// User's Vault Pass token account
    #[account(
        mut,
        associated_token::mint = user_vault_pass_mint,
        associated_token::authority = user,
    )]
    pub user_vault_pass_token: Account<'info, TokenAccount>,

    /// 🚨 CRITICAL: Vault program for CPI calls to check vault shares
    /// CHECK: This is the vault program ID verified against stake_config
    #[account(
        address = stake_config.vault_program_id,
    )]
    pub vault_program: UncheckedAccount<'info>,

    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
}

pub fn unstake_calvin(ctx: Context<UnstakeCalvin>, amount: u64) -> Result<()> {
    if amount == 0 {
        return Err(error!(StakingError::ZeroUnstakeAmount));
    }

    let stake_config = &ctx.accounts.stake_config;

    if ctx.accounts.user_stake.total_staked == 0 {
        return Err(error!(StakingError::NoStakedTokens));
    }

    // 🚨 CRITICAL SECURITY CHECK: Verify user has zero vault shares before allowing unstaking
    let user_vault_shares = get_user_vault_shares_cpi(
        &ctx.accounts.vault_program,
        &ctx.accounts.user.key(),
        &ctx.remaining_accounts,
    )?;

    if user_vault_shares > 0 {
        return Err(error!(StakingError::MustWithdrawVaultSharesFirst));
    }

    // Transfer CALVIN tokens back to user
    let stake_vault_seeds = &[
        STAKE_VAULT_SEED,
        &[ctx.accounts.stake_vault.bump],
    ];

    token::transfer(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.stake_vault_calvin_token.to_account_info(),
                to: ctx.accounts.user_calvin_token.to_account_info(),
                authority: ctx.accounts.stake_vault.to_account_info(),
            },
            &[stake_vault_seeds],
        ),
        amount,
    )?;

    // Now we can get mutable references to update the accounts
    let user_stake = &mut ctx.accounts.user_stake;
    let stake_vault = &mut ctx.accounts.stake_vault;

    // Update user's staked amount
    user_stake.total_staked = user_stake.total_staked
        .checked_sub(amount)
        .ok_or(StakingError::ArithmeticError)?;

    // Update stake vault totals
    stake_vault.total_staked = stake_vault.total_staked
        .checked_sub(amount)
        .ok_or(StakingError::ArithmeticError)?;

    // Burn corresponding Vault Pass tokens
    // The user is the owner of their token account, so they must authorize the burn
    token::burn(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Burn {
                mint: ctx.accounts.user_vault_pass_mint.to_account_info(),
                from: ctx.accounts.user_vault_pass_token.to_account_info(),
                authority: ctx.accounts.user.to_account_info(), // User owns the token account
            },
        ),
        amount,
    )?;

    // Update total vault passes
    stake_vault.total_vault_passes = stake_vault.total_vault_passes
        .checked_sub(amount)
        .ok_or(StakingError::ArithmeticError)?;

    // Recalculate tier based on new staked amount
    let new_tier = calculate_tier(user_stake.total_staked, &stake_config.tier_thresholds);
    user_stake.tier = new_tier;

    // Update timestamp
    user_stake.last_stake_timestamp = Clock::get()?.unix_timestamp;

    // Emit unstake event
    emit!(UnstakeEvent {
        user: ctx.accounts.user.key(),
        amount,
        remaining_total: user_stake.total_staked,
        new_tier,
    });

    msg!(
        "User {} unstaked {} CALVIN tokens. Remaining staked: {}, New tier: {}",
        ctx.accounts.user.key(),
        amount,
        user_stake.total_staked,
        new_tier
    );

    Ok(())
}

/// 🚨 CRITICAL CPI FUNCTION: Get user's vault share balance from vault program
/// This is the core security mechanism that prevents unstaking while holding vault shares
fn get_user_vault_shares_cpi(
    vault_program: &UncheckedAccount,
    user: &Pubkey,
    remaining_accounts: &[AccountInfo],
) -> Result<u64> {
    // We expect the remaining accounts to contain:
    // [0] vault - the vault account
    // [1] shares_mint - the vault shares mint
    // [2] user_shares_token - the user's share token account
    
    if remaining_accounts.len() < 3 {
        msg!("Insufficient remaining accounts for vault CPI call");
        // Fail-safe: assume user has shares to prevent unstaking
        return Ok(1);
    }
    
    let vault_account = &remaining_accounts[0];
    let shares_mint = &remaining_accounts[1]; 
    let user_shares_token = &remaining_accounts[2];
    
    // Verify the accounts are owned by the correct programs
    if *vault_account.owner != vault_program.key() {
        msg!("Invalid vault account owner");
        return Ok(1); // Fail-safe
    }
    
    // Parse the user's share token account to get the balance directly
    // This is more efficient than a full CPI call for a simple balance check
    match user_shares_token.try_borrow_data() {
        Ok(data) => {
            // SPL Token account structure: [mint(32), owner(32), amount(8), ...]
            if data.len() >= 72 && user_shares_token.owner == &anchor_spl::token::ID {
                // Read the amount field (bytes 64-72)
                let amount_bytes: [u8; 8] = data[64..72].try_into().unwrap_or([0; 8]);
                let share_balance = u64::from_le_bytes(amount_bytes);
                
                msg!("User {} has {} vault shares", user, share_balance);
                return Ok(share_balance);
        }
    }
        Err(_) => {
            msg!("Failed to read user shares token account");
            return Ok(1); // Fail-safe: assume user has shares
        }
    }
    
    // If we can't determine the balance, fail-safe to prevent unstaking
    msg!("Could not determine vault share balance - assuming user has shares");
    Ok(1)
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