use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, TokenAccount};

use crate::{constants::*, state::*};

#[derive(Accounts)]
pub struct GetUserVaultShares<'info> {
    /// User whose vault shares we're checking
    /// CHECK: This is just a pubkey for share balance lookup
    pub user: UncheckedAccount<'info>,

    /// The vault account
    #[account(
        seeds = [VAULT_PDA_SEED],
        bump = vault.vault_bump,
    )]
    pub vault: Account<'info, Vault>,

    /// The vault's share token mint
    #[account(
        address = vault.shares_mint,
    )]
    pub shares_mint: Account<'info, Mint>,

    /// The user's share token account
    #[account(
        constraint = user_shares_token.mint == vault.shares_mint,
        constraint = user_shares_token.owner == user.key(),
    )]
    pub user_shares_token: Account<'info, TokenAccount>,
}

/// Returns the user's vault share balance
/// This instruction is callable via CPI from the staking program
/// to enforce the critical constraint: users cannot unstake CALVIN if they have vault shares
pub fn get_user_vault_shares(ctx: Context<GetUserVaultShares>) -> Result<u64> {
    let user_shares_token = &ctx.accounts.user_shares_token;
    let share_balance = user_shares_token.amount;

    msg!(
        "User {} has {} vault shares",
        ctx.accounts.user.key(),
        share_balance
    );

    Ok(share_balance)
} 