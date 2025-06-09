use anchor_lang::prelude::*;

use crate::{constants::*, state::*, ErrorCode};

#[derive(Accounts)]
pub struct UpdateConfig<'info> {
    /// Only the emergency owner can update vault configuration
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account
    #[account(
        mut,
        constraint = vault.emergency_owner == authority.key() @ ErrorCode::UnauthorizedOwner,
    )]
    pub vault: Account<'info, Vault>,
}

pub fn update_config(
    ctx: Context<UpdateConfig>,
    new_treasury: Option<Pubkey>,
    new_jupiter_program_id: Option<Pubkey>,
    new_per_nft_cap: Option<u64>,
) -> Result<()> {
    // Get vault account
    let vault = &mut ctx.accounts.vault;
    
    // Update treasury if provided
    if let Some(treasury) = new_treasury {
        vault.treasury = treasury;
        msg!("Updated treasury to {}", treasury);
    }
    
    // Update Jupiter program ID if provided
    if let Some(jupiter_program_id) = new_jupiter_program_id {
        vault.jupiter_program_id = jupiter_program_id;
        msg!("Updated Jupiter program ID to {}", jupiter_program_id);
    }
    
    // Update per-NFT cap if provided
    if let Some(per_nft_cap) = new_per_nft_cap {
        vault.per_nft_cap = per_nft_cap;
        msg!("Updated per-NFT cap to {}", per_nft_cap);
    }
    
    msg!("Vault configuration updated");
    
    Ok(())
} 