use anchor_lang::prelude::*;
use crate::{state::*, ErrorCode};

#[derive(Accounts)]
#[instruction(operation_id: u64)]
pub struct ExecuteEmergencyAction<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    
    #[account(
        mut,
        seeds = [b"pending-op", vault.key().as_ref(), &operation_id.to_le_bytes()],
        bump = pending_operation.bump,
        close = authority  // Close account and return rent to authority
    )]
    pub pending_operation: Account<'info, PendingOperation>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
}

pub fn execute_emergency_action(
    ctx: Context<ExecuteEmergencyAction>,
    operation_id: u64,
) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    let pending_operation = &ctx.accounts.pending_operation;
    
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
    
    // Check signatures threshold
    require!(
        pending_operation.signatures_count >= vault.required_signatures,
        ErrorCode::InsufficientSignatures
    );
    
    // Execute the operation based on type
    match pending_operation.operation_type {
        OperationType::PauseTrading => {
            vault.trading_paused = true;
        },
        OperationType::PauseDeposits => {
            vault.deposits_paused = true;
        },
        OperationType::PauseWithdrawals => {
            vault.withdrawals_paused = true;
        },
        OperationType::PauseAll => {
            vault.trading_paused = true;
            vault.deposits_paused = true;
            vault.withdrawals_paused = true;
        },
        OperationType::UnpauseTrading => {
            vault.trading_paused = false;
        },
        OperationType::UnpauseDeposits => {
            vault.deposits_paused = false;
        },
        OperationType::UnpauseWithdrawals => {
            vault.withdrawals_paused = false;
        },
        OperationType::UnpauseAll => {
            vault.trading_paused = false;
            vault.deposits_paused = false;
            vault.withdrawals_paused = false;
        },
        _ => {
            // Other operations require additional implementation
            return Err(error!(ErrorCode::UnsupportedOperation));
        },
    }
    
    emit!(SecurityEvent {
        event_type: SecurityEventType::EmergencyActionExecuted,
        severity: SecuritySeverity::Critical,
        vault: vault.key(),
        details: format!("Emergency action executed: {:?}", pending_operation.operation_type),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    emit!(crate::state::EmergencyActionEvent {
        vault: vault.key(),
        operation_id,
        action: crate::state::EmergencyAction::Executed,
        operation_type: pending_operation.operation_type,
        authority: ctx.accounts.authority.key(),
        signatures_count: pending_operation.signatures_count,
        required_signatures: vault.required_signatures,
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    // Account will be automatically closed due to the close constraint
    Ok(())
} 