use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, MintTo, FreezeAccount, ThawAccount};
use anchor_spl::associated_token::AssociatedToken;

use crate::{constants::*, state::*, errors::ErrorCode};

#[derive(Accounts)]
#[instruction(shares_to_mint: u64)]
pub struct AdminMintShares<'info> {
    /// Only the emergency owner can mint shares directly
    #[account(mut)]
    pub authority: Signer<'info>,
    
    /// The vault account
    #[account(
        mut,
        constraint = vault.emergency_owner == authority.key() @ ErrorCode::UnauthorizedOwner,
    )]
    pub vault: Box<Account<'info, Vault>>,
    
    /// The recipient's public key
    /// CHECK: This is the user who will receive the shares
    pub recipient: UncheckedAccount<'info>,
    
    /// User's vault position account (tracks deposits)
    #[account(
        init_if_needed,
        payer = authority,
        space = UserPosition::SIZE,
        seeds = [USER_POSITION_PDA_SEED, recipient.key().as_ref(), vault.key().as_ref()],
        bump
    )]
    pub user_position: Box<Account<'info, UserPosition>>,
    
    /// The share token mint
    #[account(
        mut,
        address = vault.shares_mint,
    )]
    pub shares_mint: Account<'info, Mint>,
    
    /// The recipient's share token account (will be frozen after minting)
    #[account(
        init_if_needed,
        payer = authority,
        associated_token::mint = shares_mint,
        associated_token::authority = recipient,
    )]
    pub recipient_shares_token: Account<'info, TokenAccount>,
    
    /// The vault's authority PDA
    /// CHECK: This is a PDA that we derive and verify using seeds
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

pub fn admin_mint_shares(ctx: Context<AdminMintShares>, shares_to_mint: u64, reason: String) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    let user_position = &mut ctx.accounts.user_position;
    let recipient = &ctx.accounts.recipient;
    
    // Validate shares amount
    require!(shares_to_mint > 0, ErrorCode::InvalidAmount);
    
    // Initialize user position if it's new
    if user_position.user_authority == Pubkey::default() {
        user_position.user_authority = recipient.key();
        user_position.vault = vault.key();
        user_position.total_deposits_usdc = 0;
        user_position.last_deposit_timestamp = Clock::get()?.unix_timestamp;
        user_position.bump = ctx.bumps.user_position;
    }
    
    // Mint share tokens to recipient
    let vault_authority_seeds = &[
        &VAULT_AUTHORITY_PDA_SEED[..],
        &[vault.authority_bump],
    ];
    
    // Check if account is frozen before minting (for users who already have shares)
    let mut was_already_frozen = false;
    
    // Try to mint - if it fails due to frozen account, unfreeze first
    let mint_result = token::mint_to(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            MintTo {
                mint: ctx.accounts.shares_mint.to_account_info(),
                to: ctx.accounts.recipient_shares_token.to_account_info(),
                authority: ctx.accounts.vault_authority.to_account_info(),
            },
            &[vault_authority_seeds],
        ),
        shares_to_mint,
    );
    
    if let Err(e) = mint_result {
        // Check if the error is because account is frozen
        let error_code = e.to_string();
        if error_code.contains("0x11") || error_code.contains("frozen") {
            was_already_frozen = true;
            
            // Unfreeze the account temporarily
            token::thaw_account(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    ThawAccount {
                        account: ctx.accounts.recipient_shares_token.to_account_info(),
                        mint: ctx.accounts.shares_mint.to_account_info(),
                        authority: ctx.accounts.vault_authority.to_account_info(),
                    },
                    &[vault_authority_seeds],
                ),
            )?;
            
            // Now try minting again
            token::mint_to(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    MintTo {
                        mint: ctx.accounts.shares_mint.to_account_info(),
                        to: ctx.accounts.recipient_shares_token.to_account_info(),
                        authority: ctx.accounts.vault_authority.to_account_info(),
                    },
                    &[vault_authority_seeds],
                ),
                shares_to_mint,
            )?;
        } else {
            // Different error, propagate it
            return Err(e.into());
        }
    }
    
    // Freeze recipient's share token account to make shares non-transferable
    // Always freeze after minting (whether it was already frozen or not)
    let freeze_result = token::freeze_account(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            FreezeAccount {
                account: ctx.accounts.recipient_shares_token.to_account_info(),
                mint: ctx.accounts.shares_mint.to_account_info(),
                authority: ctx.accounts.vault_authority.to_account_info(),
            },
            &[vault_authority_seeds],
        ),
    );
    
    // If freeze fails and account wasn't already frozen, it's an error
    if freeze_result.is_err() && !was_already_frozen {
        return Err(freeze_result.unwrap_err().into());
    }
    
    // Update vault state
    vault.total_shares = vault.total_shares
        .checked_add(shares_to_mint)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Emit admin mint event
    emit!(AdminMintEvent {
        authority: ctx.accounts.authority.key(),
        recipient: recipient.key(),
        vault: vault.key(),
        shares_minted: shares_to_mint,
        reason: reason.clone(),
        total_shares: vault.total_shares,
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    // Emit security event for audit trail
    emit!(SecurityEvent {
        event_type: SecurityEventType::EmergencyActionExecuted,
        severity: SecuritySeverity::High,
        vault: vault.key(),
        details: format!(
            "Admin minted {} shares to {} for reason: {}", 
            shares_to_mint, 
            recipient.key(), 
            reason
        ),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!(
        "🔒 Admin minted {} shares to {} (frozen). Total shares: {}",
        shares_to_mint,
        recipient.key(),
        vault.total_shares
    );
    msg!("Reason: {}", reason);
    
    Ok(())
}

// Event emitted when admin mints shares
#[event]
pub struct AdminMintEvent {
    pub authority: Pubkey,
    pub recipient: Pubkey,
    pub vault: Pubkey,
    pub shares_minted: u64,
    pub reason: String,
    pub total_shares: u64,
    pub timestamp: i64,
} 