use anchor_lang::prelude::*;
use crate::{state::*, ErrorCode};

#[derive(Accounts)]
#[instruction(operation_type: OperationType)]
pub struct ProposeEmergencyAction<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    
    #[account(
        init,
        payer = authority,
        space = PendingOperation::SIZE,
        seeds = [b"pending-op", vault.key().as_ref(), &vault.next_operation_id.to_le_bytes()],
        bump
    )]
    pub pending_operation: Account<'info, PendingOperation>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
    
    pub system_program: Program<'info, System>,
}

pub fn propose_emergency_action(
    ctx: Context<ProposeEmergencyAction>,
    operation_type: OperationType,
    params: Vec<u8>,
) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    let pending_operation = &mut ctx.accounts.pending_operation;
    
    // Verify proposer is emergency owner
    require!(
        vault.emergency_owners[..vault.emergency_owners_count as usize]
            .contains(&ctx.accounts.authority.key()),
        ErrorCode::UnauthorizedOwner
    );
    
    // Create the pending operation in separate account
    pending_operation.operation_id = vault.next_operation_id;
    pending_operation.operation_type = operation_type;
    pending_operation.signatures = [Pubkey::default(); 5];
    pending_operation.signatures[0] = ctx.accounts.authority.key();
    pending_operation.signatures_count = 1;
    pending_operation.proposer = ctx.accounts.authority.key();
    pending_operation.created_at = Clock::get()?.unix_timestamp;
    pending_operation.expires_at = Clock::get()?.unix_timestamp + (7 * 24 * 60 * 60); // 7 days
    
    // Store parameters (truncate if too long)
    let params_len = std::cmp::min(params.len(), 128);
    pending_operation.params[..params_len].copy_from_slice(&params[..params_len]);
    pending_operation.params_len = params_len as u8;
    pending_operation.vault = vault.key();
    pending_operation.bump = ctx.bumps.pending_operation;
    
    // Increment operation ID for next operation
    vault.next_operation_id += 1;
    
    emit!(SecurityEvent {
        event_type: SecurityEventType::EmergencyActionProposed,
        severity: SecuritySeverity::High,
        vault: vault.key(),
        details: format!("Emergency action proposed: {:?}", operation_type),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    emit!(crate::state::EmergencyActionEvent {
        vault: vault.key(),
        operation_id: vault.next_operation_id - 1,
        action: crate::state::EmergencyAction::Proposed,
        operation_type,
        authority: ctx.accounts.authority.key(),
        signatures_count: 1,
        required_signatures: vault.required_signatures,
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    Ok(())
} 