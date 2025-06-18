use anchor_lang::prelude::*;
use crate::{state::*, ErrorCode};

#[derive(Accounts)]
pub struct AddEmergencyOwner<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
    
    pub system_program: Program<'info, System>,
}

pub fn add_emergency_owner(
    ctx: Context<AddEmergencyOwner>,
    new_owner: Pubkey,
    new_required_signatures: u8,
) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    
    // Verify current owner is calling (check again in function body)
    let current_owners = &vault.emergency_owners[..vault.emergency_owners_count as usize];
    require!(
        current_owners.contains(&ctx.accounts.authority.key()),
        ErrorCode::UnauthorizedOwner
    );
    
    // Check if owner already exists
    let current_owners = &vault.emergency_owners[..vault.emergency_owners_count as usize];
    require!(
        !current_owners.contains(&new_owner),
        ErrorCode::OwnerAlreadyExists
    );
    
    // Check maximum owners limit (prevent state bloat)
    require!(
        vault.emergency_owners_count < 3,
        ErrorCode::TooManyOwners
    );
    
    // Add new owner
    let owner_index = vault.emergency_owners_count as usize;
    vault.emergency_owners[owner_index] = new_owner;
    vault.emergency_owners_count += 1;
    vault.required_signatures = new_required_signatures;
    
    // Emit security event
    emit!(SecurityEvent {
        event_type: SecurityEventType::EmergencyOwnerAdded,
        severity: SecuritySeverity::High,
        vault: vault.key(),
        details: format!("New emergency owner added: {}", new_owner),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!("Emergency owner added: {}", new_owner);
    msg!("Required signatures updated to: {}", new_required_signatures);
    
    Ok(())
} 