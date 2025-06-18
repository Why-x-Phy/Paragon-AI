use anchor_lang::prelude::*;
use crate::{state::*, ErrorCode};

#[derive(Accounts)]
#[instruction(operation_id: u64)]
pub struct ApproveEmergencyAction<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    
    #[account(
        mut,
        seeds = [b"pending-op", vault.key().as_ref(), &operation_id.to_le_bytes()],
        bump = pending_operation.bump
    )]
    pub pending_operation: Account<'info, PendingOperation>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
    
    pub system_program: Program<'info, System>,
}

pub fn approve_emergency_action(
    ctx: Context<ApproveEmergencyAction>,
    operation_id: u64,
) -> Result<()> {
    let vault = &ctx.accounts.vault;
    let pending_operation = &mut ctx.accounts.pending_operation;
    
    // Verify approver is emergency owner
    require!(
        vault.emergency_owners[..vault.emergency_owners_count as usize]
            .contains(&ctx.accounts.authority.key()),
        ErrorCode::UnauthorizedOwner
    );
    
    // Verify operation ID matches
    require!(
        pending_operation.operation_id == operation_id,
        ErrorCode::OperationNotFound
    );
    
    // Check expiration
    require!(
        Clock::get()?.unix_timestamp <= pending_operation.expires_at,
        ErrorCode::OperationExpired
    );
    
    // Check if already signed by this authority
    let authority_key = ctx.accounts.authority.key();
    let existing_signatures = &pending_operation.signatures[..pending_operation.signatures_count as usize];
    
    if !existing_signatures.contains(&authority_key) {
        // Add signature
        let signature_index = pending_operation.signatures_count as usize;
        require!(
            signature_index < 5,
            ErrorCode::TooManySignatures
        );
        
        pending_operation.signatures[signature_index] = authority_key;
        pending_operation.signatures_count += 1;
        
        emit!(SecurityEvent {
            event_type: SecurityEventType::EmergencyActionApproved,
            severity: SecuritySeverity::High,
            vault: vault.key(),
            details: format!("Emergency action {} approved by {}", operation_id, authority_key),
            timestamp: Clock::get()?.unix_timestamp,
        });
        
        emit!(crate::state::EmergencyActionEvent {
            vault: vault.key(),
            operation_id,
            action: crate::state::EmergencyAction::Approved,
            operation_type: pending_operation.operation_type,
            authority: authority_key,
            signatures_count: pending_operation.signatures_count,
            required_signatures: vault.required_signatures,
            timestamp: Clock::get()?.unix_timestamp,
        });
        
        msg!("Emergency action {} approved by {}", operation_id, authority_key);
        msg!("Signatures: {}/{}", pending_operation.signatures_count, vault.required_signatures);
    } else {
        msg!("Authority {} has already approved operation {}", authority_key, operation_id);
    }
    
    Ok(())
} 