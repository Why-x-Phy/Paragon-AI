use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};
use anchor_spl::associated_token::AssociatedToken;

use crate::{constants::*, state::*};

#[derive(Accounts)]
#[instruction(emergency_owner: Pubkey, calvin_authority: Pubkey, staking_program_id: Pubkey, per_nft_cap: u64, jupiter_program_id: Pubkey)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub initializer: Signer<'info>,
    
    /// The USDC mint
    pub usdc_mint: Account<'info, Mint>,
    
    /// The CALVIN token mint
    pub calvin_mint: Account<'info, Mint>,
    
    /// The vault account that holds the state
    #[account(
        init,
        payer = initializer,
        space = Vault::SIZE,
        seeds = [VAULT_PDA_SEED],
        bump
    )]
    pub vault: Account<'info, Vault>,
    
    /// The vault's token account for holding USDC
    #[account(
        init_if_needed,
        payer = initializer,
        associated_token::mint = usdc_mint,
        associated_token::authority = vault_authority,
    )]
    pub usdc_vault: Account<'info, TokenAccount>,
    
    /// The PDA that controls the vault's token accounts
    /// CHECK: This is a PDA that we derive
    #[account(
        seeds = [VAULT_AUTHORITY_PDA_SEED],
        bump
    )]
    pub vault_authority: UncheckedAccount<'info>,
    
    /// The mint for share tokens
    #[account(
        init,
        payer = initializer,
        mint::decimals = usdc_mint.decimals,
        mint::authority = vault_authority,
        mint::freeze_authority = vault_authority,
        seeds = [SHARES_MINT_PDA_SEED],
        bump
    )]
    pub shares_mint: Account<'info, Mint>,
    
    /// The treasury that receives fees
    /// CHECK: This is just a pubkey that will receive fees
    pub treasury: UncheckedAccount<'info>,
    
    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn initialize(
    ctx: Context<Initialize>,
    emergency_owner: Pubkey,
    calvin_authority: Pubkey,
    staking_program_id: Pubkey,
    per_nft_cap: u64,
    jupiter_program_id: Pubkey,
) -> Result<()> {
    let vault = &mut ctx.accounts.vault;
    
    // Initialize basic vault state
    vault.emergency_owner = emergency_owner;
    vault.calvin_authority = calvin_authority;
    vault.staking_program_id = staking_program_id;
    vault.shares_mint = ctx.accounts.shares_mint.key();
    vault.usdc_mint = ctx.accounts.usdc_mint.key();
    vault.usdc_vault = ctx.accounts.usdc_vault.key();
    vault.vault_authority = ctx.accounts.vault_authority.key();
    vault.calvin_mint = ctx.accounts.calvin_mint.key();
    vault.treasury = ctx.accounts.treasury.key();
    vault.per_nft_cap = per_nft_cap;
    vault.high_water_mark_nav = 0;
    vault.total_shares = 0;
    vault.paused = false;
    vault.jupiter_program_id = jupiter_program_id;
    
    // Initialize cached NAV fields
    vault.cached_nav = 0;
    vault.nav_last_updated = Clock::get()?.unix_timestamp;
    
    // Store bumps for PDAs
    vault.vault_bump = ctx.bumps.vault;
    vault.shares_mint_bump = ctx.bumps.shares_mint;
    vault.authority_bump = ctx.bumps.vault_authority;
    
    // 🔒 Initialize security features with safe defaults
    vault.reentrancy_guard = false;
    
    // Start with no granular pauses (all operations enabled)
    vault.trading_paused = false;
    vault.deposits_paused = false;
    vault.withdrawals_paused = false;
    
    // Initialize multisig with single owner for deployment compatibility
    vault.emergency_owners = [Pubkey::default(); 2];
    vault.emergency_owners[0] = emergency_owner; // Set first owner
    vault.emergency_owners_count = 1;            // Only one owner initially
    vault.required_signatures = 1;               // Single signature required initially
    vault.next_operation_id = 1;                 // Start operation IDs at 1
    
    // 🔒 Initialize CPI rate limiting with empty trackers
    vault.cpi_call_counts = [crate::state::CpiCallTracker {
        program_id: Pubkey::default(),
        calls_per_hour: 0,
        last_reset: 0,
        max_calls_per_hour: 200,
    }; 2];
    vault.cpi_trackers_count = 0; // No trackers initially
    
    // Reserved space removed for stack size optimization
    // vault.reserved = [0u8; 0];
    
    // Emit security event for vault initialization
    emit!(crate::state::SecurityEvent {
        event_type: crate::state::SecurityEventType::EmergencyActionExecuted,
        severity: crate::state::SecuritySeverity::Medium,
        vault: vault.key(),
        details: format!("Vault initialized with emergency owner: {}", emergency_owner),
        timestamp: Clock::get()?.unix_timestamp,
    });
    
    msg!("🔒 Enhanced Vault initialized:");
    msg!("  Emergency owner: {}", emergency_owner);
    msg!("  Calvin authority: {}", calvin_authority);
    msg!("  Staking program: {}", staking_program_id);
    msg!("  Per NFT cap: {}", per_nft_cap);
    msg!("  Security features: ENABLED");
    msg!("  Multisig owners: 1 (can be expanded to 3)");
    msg!("  Required signatures: 1 (can be increased)");
    
    Ok(())
} 