use anchor_lang::prelude::*;
use anchor_spl::token::{self, TokenAccount, Mint, Transfer};
// Updated to modern Pyth pull oracle SDK
use pyth_solana_receiver_sdk::price_update::PriceUpdateV2;
use std::str::FromStr;
use crate::errors::ErrorCode;
use crate::state::Vault;
use crate::constants::*;
// Oracle config functions are imported only where needed

// Oracle functions now use the proper oracle_config module
// All oracle mappings and functions are centralized in oracle_config.rs

/// Verify user's tier via CPI call to staking program and check deposit caps
pub fn verify_tier_and_check_cap(
    staking_program: &AccountInfo,
    _user: &Pubkey,  // Prefixed with _ to indicate intentionally unused (placeholder)
    current_deposits: u64,
    new_deposit: u64,
    _vault: &Vault,  // Prefixed with _ to indicate intentionally unused (placeholder)
    remaining_accounts: &[AccountInfo],
) -> Result<()> {
    // Get user's tier by reading their stake account directly
    // We expect remaining_accounts to contain:
    // [0] stake_config - the staking configuration account
    // [1] user_stake - the user's stake account
    
    let user_tier = if remaining_accounts.len() >= 2 {
        let stake_config_account = &remaining_accounts[0];
        let user_stake_account = &remaining_accounts[1];
        
        // Verify the accounts are owned by the staking program
        if *stake_config_account.owner != staking_program.key() || 
           *user_stake_account.owner != staking_program.key() {
            msg!("Invalid staking program account ownership");
            // Assume lowest tier for safety
            DEFAULT_TIER
        } else {
            // Parse the user_stake account to get the tier
            match user_stake_account.try_borrow_data() {
                Ok(data) => {
                    // UserStake structure: [discriminator(8), user_authority(32), total_staked(8), vault_pass_mint(32), tier(1), ...]
                    if data.len() >= 81 {
                        // Read the tier field (byte 80 - CORRECT POSITION!)
                        let tier = data[80];
                        msg!("Read tier {} from correct position 80", tier);
                        tier
                    } else {
                        msg!("Invalid user stake account size: {}", data.len());
                        DEFAULT_TIER
                    }
                }
                Err(_) => {
                    msg!("Failed to read user stake account");
                    DEFAULT_TIER
                }
            }
        }
    } else {
        msg!("Insufficient remaining accounts for tier verification");
        // Assume lowest tier for safety
        DEFAULT_TIER
    };
    
    let total_deposits_after = current_deposits
        .checked_add(new_deposit)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Check tier-based deposit caps
    match user_tier {
        VAULT_KEEPER_TIER => {
            // Unlimited deposits
            Ok(())
        },
        TIER_2 => {
            if total_deposits_after <= TIER_2_MAX_DEPOSIT {
                Ok(())
            } else {
                Err(error!(ErrorCode::DepositExceedsCap))
            }
        },
        TIER_3 => {
            if total_deposits_after <= TIER_3_MAX_DEPOSIT {
                Ok(())
            } else {
                Err(error!(ErrorCode::DepositExceedsCap))
            }
        },
        DEFAULT_TIER => {
            Err(error!(ErrorCode::NotQualifiedForDeposit))
        },
        _ => Err(error!(ErrorCode::NotQualifiedForDeposit)),
    }
}

/// Calculate current NAV in USDC using Pyth pull oracle model (PRIMARY METHOD)
/// 
/// 🔋 This is the primary NAV calculation method using Pyth pull oracles
/// Benefits: Higher precision, decentralized, modern oracle infrastructure, reliable feeds
/// 
/// remaining_accounts structure: 
/// Oracle accounts in groups of 3: [token_account, price_update_v2, token_mint]
/// The PriceUpdateV2 accounts must be created by fetching from Hermes API
pub fn current_nav_usdc(
    _vault: &Vault,
    usdc_token_account: &Account<TokenAccount>,
    remaining_accounts: &[AccountInfo],
) -> Result<u64> {
    msg!("Calculating NAV with {} remaining accounts", remaining_accounts.len());
    
    // Start with USDC balance (no conversion needed)
    let mut total_nav_usdc = usdc_token_account.amount;
    msg!("USDC balance: {}", total_nav_usdc);
    
    // When called from deposit instruction, remaining_accounts are already oracle-only
    // No need for further slicing
    if remaining_accounts.len() == 0 {
        msg!("No oracle accounts provided, returning USDC balance only");
        return Ok(total_nav_usdc);
    }
    
    let oracle_accounts = remaining_accounts;
    msg!("Processing {} oracle accounts", oracle_accounts.len());
    
    // Process oracle accounts in chunks of 3
    for (i, chunk) in oracle_accounts.chunks(3).enumerate() {
        if chunk.len() != 3 {
            msg!("Invalid chunk size {} at index {}", chunk.len(), i);
            return Err(ErrorCode::InvalidOracleAccounts.into());
        }
        
        let token_account_info = &chunk[0];
        let price_account_info = &chunk[1];
        let mint_account_info = &chunk[2];
        
        msg!("Processing token chunk {}", i);
        
        // Skip USDC to prevent double-counting (we already added USDC balance directly)
        let usdc_mint = match Pubkey::from_str("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v") {
            Ok(mint) => mint,
            Err(_) => return Err(ErrorCode::InvalidOracleAccount.into()),
        };
        
        if mint_account_info.key() == usdc_mint {
            msg!("Skipping USDC mint {} to prevent double-counting", mint_account_info.key());
            continue;
        }
        
        // Parse token account using standard SPL token deserialization
        let token_account = match TokenAccount::try_deserialize(
            &mut token_account_info.data.borrow().as_ref()
        ) {
            Ok(account) => account,
            Err(e) => {
                msg!("Failed to deserialize token account {}: {}", i, e);
                continue; // Skip invalid token accounts
            }
        };
        
        // Skip if no balance
        if token_account.amount == 0 {
            msg!("Token account {} has zero balance, skipping", i);
            continue;
        }
        
        // Parse mint account to get decimals
        let mint_account = match Mint::try_deserialize(
            &mut mint_account_info.data.borrow().as_ref()
        ) {
            Ok(mint) => mint,
            Err(e) => {
                msg!("Failed to deserialize mint account {}: {}", i, e);
                continue; // Skip invalid mint accounts
            }
        };
        
        // Parse Pyth PriceUpdateV2 account using the new pull oracle SDK
        let price_update_v2 = match PriceUpdateV2::try_deserialize(
            &mut price_account_info.data.borrow().as_ref()
        ) {
            Ok(update) => update,
            Err(e) => {
                msg!("Failed to deserialize PriceUpdateV2 account {}: {}", i, e);
                continue; // Skip invalid price update accounts
            }
        };
        
        // Validate price update account and extract price data
        let price_data = match validate_price_update(&price_update_v2) {
            Ok(data) => data,
            Err(e) => {
                msg!("Invalid price update data for token {}: {:?}", i, e);
                continue; // Skip invalid price data
            }
        };
        
        // Basic staleness check
        let current_time = Clock::get()?.unix_timestamp;
        if current_time - price_data.publish_time > MAX_PRICE_STALENESS_SECONDS {
            msg!("Price too stale for token {}: {} seconds old", i, current_time - price_data.publish_time);
            continue;
        }
        
        // Calculate value in USDC
        match calculate_token_value_usdc(
            token_account.amount,
            mint_account.decimals,
            price_data.price,
            price_data.exponent,
        ) {
            Ok(token_value_usdc) => {
                msg!("Token {} value: {} USDC", i, token_value_usdc);
                total_nav_usdc = total_nav_usdc
                    .checked_add(token_value_usdc)
                    .ok_or(ErrorCode::MathOverflow)?;
            }
            Err(e) => {
                msg!("Failed to calculate value for token {}: {:?}", i, e);
                continue;
            }
        }
    }
    
    msg!("Total NAV: {} USDC", total_nav_usdc);
    Ok(total_nav_usdc)
}

/// Calculate current NAV in USDC using Switchboard oracle accounts (DEPRECATED FALLBACK)
/// 
/// ⚠️ DEPRECATED: This method is kept for fallback compatibility only
/// Use current_nav_usdc() which now uses Pyth oracles for better reliability
/// 
/// remaining_accounts structure:
/// Oracle accounts in groups of 3: [token_account, switchboard_oracle, token_mint]
/// Unlike Pyth, Switchboard feeds are permanent on-chain accounts that can be read directly
pub fn current_nav_usdc_switchboard(
    _vault: &Vault,
    usdc_token_account: &Account<TokenAccount>,
    remaining_accounts: &[AccountInfo],
) -> Result<u64> {
    msg!("🔋 Calculating NAV with Switchboard feeds - {} remaining accounts", remaining_accounts.len());
    
    // Start with USDC balance (no conversion needed)
    let mut total_nav_usdc = usdc_token_account.amount;
    msg!("💵 USDC balance: {}", total_nav_usdc);
    
    // Process Switchboard accounts in chunks of 3: [token_account, switchboard_oracle, token_mint]
    if remaining_accounts.len() == 0 {
        msg!("No oracle accounts provided, returning USDC balance only");
        return Ok(total_nav_usdc);
    }
    
    let oracle_accounts = remaining_accounts;
    msg!("Processing {} oracle accounts", oracle_accounts.len());
    
    // Process oracle accounts in chunks of 3
    for (i, chunk) in oracle_accounts.chunks(3).enumerate() {
        if chunk.len() != 3 {
            msg!("Invalid chunk size {} at index {}", chunk.len(), i);
            return Err(ErrorCode::InvalidOracleAccounts.into());
        }
        
        let token_account_info = &chunk[0];
        let switchboard_oracle_info = &chunk[1]; // Switchboard feed instead of Pyth price update
        let mint_account_info = &chunk[2];
        
        msg!("📊 Processing token chunk {}", i);
        
        // Skip USDC to prevent double-counting (we already added USDC balance directly)
        let usdc_mint = match Pubkey::from_str("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v") {
            Ok(mint) => mint,
            Err(_) => return Err(ErrorCode::InvalidOracleAccount.into()),
        };
        
        if mint_account_info.key() == usdc_mint {
            msg!("Skipping USDC mint {} to prevent double-counting", mint_account_info.key());
            continue;
        }
        
        // Parse token account using standard SPL token deserialization
        let token_account = match TokenAccount::try_deserialize(
            &mut token_account_info.data.borrow().as_ref()
        ) {
            Ok(account) => account,
            Err(e) => {
                msg!("Failed to deserialize token account {}: {}", i, e);
                continue; // Skip invalid token accounts
            }
        };
        
        // Skip if no balance
        if token_account.amount == 0 {
            msg!("Token account {} has zero balance, skipping", i);
            continue;
        }
        
        // Parse mint account to get decimals
        let mint_account = match Mint::try_deserialize(
            &mut mint_account_info.data.borrow().as_ref()
        ) {
            Ok(mint) => mint,
            Err(e) => {
                msg!("Failed to deserialize mint account {}: {}", i, e);
                continue; // Skip invalid mint accounts
            }
        };
        
        // Get price from Switchboard feed
        let (price, exponent) = match get_switchboard_price(switchboard_oracle_info) {
            Ok(price_data) => price_data,
            Err(e) => {
                msg!("Failed to get Switchboard price for token {}: {:?}", i, e);
                continue; // Skip invalid price feeds
            }
        };
        
        // Calculate value in USDC
        match calculate_token_value_usdc(
            token_account.amount,
            mint_account.decimals,
            price,
            exponent,
        ) {
            Ok(token_value_usdc) => {
                msg!("💎 Token {} value: {} USDC", i, token_value_usdc);
                total_nav_usdc = total_nav_usdc
                    .checked_add(token_value_usdc)
                    .ok_or(ErrorCode::MathOverflow)?;
            }
            Err(e) => {
                msg!("Failed to calculate value for token {}: {:?}", i, e);
                continue;
            }
        }
    }
    
    msg!("💰 Total NAV: {} USDC", total_nav_usdc);
    Ok(total_nav_usdc)
}

/// Validate PriceUpdateV2 account and extract price data
fn validate_price_update(price_update: &PriceUpdateV2) -> Result<PriceData> {
    // Extract price data from the price message
    let price_message = &price_update.price_message;
    
    // Check that the price is positive
    if price_message.price <= 0 {
        return Err(ErrorCode::InvalidPriceData.into());
    }
    
    Ok(PriceData {
        price: price_message.price,
        exponent: price_message.exponent,
        publish_time: price_message.publish_time,
    })
}

/// Price data extracted from PriceUpdateV2
#[derive(Debug)]
struct PriceData {
    price: i64,
    exponent: i32,
    publish_time: i64,
}

/// Calculate the USDC value of a token amount given its price
fn calculate_token_value_usdc(
    token_amount: u64,
    token_decimals: u8,
    price: i64,
    price_expo: i32,
) -> Result<u64> {
    if price <= 0 {
        return Ok(0);
    }
    
    // Convert token amount to base units (remove decimals)
    let token_amount_scaled = token_amount as u128;
    let price_scaled = price as u128;
    
    // Calculate raw value: token_amount * price
    let raw_value = token_amount_scaled
        .checked_mul(price_scaled)
        .ok_or(ErrorCode::MathOverflow)?;
    
    // Apply price exponent (Pyth prices have negative exponents)
    let value_with_price_expo = if price_expo < 0 {
        raw_value / (10u128.pow((-price_expo) as u32))
    } else {
        raw_value * (10u128.pow(price_expo as u32))
    };
    
    // Convert to USDC units (6 decimals) from token decimals
    let usdc_decimals = 6u8;
    let value_usdc = if token_decimals > usdc_decimals {
        // Token has more decimals than USDC, so divide
        value_with_price_expo / (10u128.pow((token_decimals - usdc_decimals) as u32))
    } else if token_decimals < usdc_decimals {
        // Token has fewer decimals than USDC, so multiply  
        value_with_price_expo * (10u128.pow((usdc_decimals - token_decimals) as u32))
    } else {
        // Same decimals
        value_with_price_expo
    };
    
    // Ensure result fits in u64
    u64::try_from(value_usdc).map_err(|_| ErrorCode::MathOverflow.into())
}

/// Calculate the number of shares to mint for a deposit
pub fn calculate_shares_to_mint(
    deposit_amount: u64, 
    deposit_fee: u64,
    total_shares: u64, 
    vault_nav: u64
) -> Result<u64> {
    let amount_after_fee = deposit_amount.checked_sub(deposit_fee)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    if total_shares == 0 || vault_nav == 0 {
        // First deposit - one share per USDC (after fee)
        // Convert micro-USDC to USDC units (divide by 1,000,000)
        return Ok(amount_after_fee / 1_000_000);
    }
    
    // Calculate shares based on proportion of NAV using 128-bit arithmetic to prevent overflow
    let amount_after_fee_u128 = amount_after_fee as u128;
    let total_shares_u128 = total_shares as u128;
    let vault_nav_u128 = vault_nav as u128;
    
    let shares_u128 = amount_after_fee_u128
        .checked_mul(total_shares_u128)
        .ok_or(error!(ErrorCode::ArithmeticError))?
        .checked_div(vault_nav_u128)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Convert back to u64, checking for overflow
    let shares = u64::try_from(shares_u128)
        .map_err(|_| error!(ErrorCode::ArithmeticError))?;
    
    Ok(shares)
}

/// Calculate the amount of USDC to return for a withdrawal
pub fn calculate_usdc_to_withdraw(
    shares: u64,
    total_shares: u64,
    vault_nav: u64
) -> Result<u64> {
    if shares > total_shares {
        return Err(error!(ErrorCode::InsufficientShares));
    }
    
    // Use 128-bit arithmetic to prevent overflow
    let shares_u128 = shares as u128;
    let vault_nav_u128 = vault_nav as u128;
    let total_shares_u128 = total_shares as u128;
    
    let amount_u128 = shares_u128
        .checked_mul(vault_nav_u128)
        .ok_or(error!(ErrorCode::ArithmeticError))?
        .checked_div(total_shares_u128)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    // Convert back to u64, checking for overflow
    let amount = u64::try_from(amount_u128)
        .map_err(|_| error!(ErrorCode::ArithmeticError))?;
    
    Ok(amount)
}

/// Calculate the deposit fee
pub fn calculate_deposit_fee(amount: u64) -> Result<u64> {
    amount
        .checked_mul(DEPOSIT_FEE_BPS)
        .ok_or(error!(ErrorCode::ArithmeticError))?
        .checked_div(BPS_DIVISOR)
        .ok_or(error!(ErrorCode::ArithmeticError))
}

/// Calculate performance fee if NAV has increased beyond high water mark
pub fn calculate_performance_fee(
    current_nav: u64,
    high_water_mark: u64
) -> Result<u64> {
    if current_nav <= high_water_mark {
        return Ok(0);
    }
    
    let profit = current_nav
        .checked_sub(high_water_mark)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    profit
        .checked_mul(PERFORMANCE_FEE_BPS)
        .ok_or(error!(ErrorCode::ArithmeticError))?
        .checked_div(BPS_DIVISOR)
        .ok_or(error!(ErrorCode::ArithmeticError))
}

/// CPI to transfer tokens
pub fn transfer_tokens<'info>(
    token_program: AccountInfo<'info>,
    source: AccountInfo<'info>,
    destination: AccountInfo<'info>,
    authority: AccountInfo<'info>,
    amount: u64,
    signer_seeds: &[&[&[u8]]],
) -> Result<()> {
    let cpi_accounts = Transfer {
        from: source,
        to: destination,
        authority,
    };
    let cpi_ctx = CpiContext::new(token_program, cpi_accounts).with_signer(signer_seeds);
    token::transfer(cpi_ctx, amount)
}

/// Check if the vault has enough USDC liquidity
pub fn check_liquidity(
    _vault: &Vault,
    usdc_balance: u64,
    total_nav: u64,
) -> Result<bool> {
    // Calculate minimum required liquidity
    let min_liquidity = total_nav
        .checked_mul(LIQUIDITY_BUFFER_BPS)
        .ok_or(error!(ErrorCode::ArithmeticError))?
        .checked_div(BPS_DIVISOR)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
    Ok(usdc_balance >= min_liquidity)
}

/// Forward a transaction to Jupiter for token swaps
pub fn forward_jupiter<'a, 'b>(
    jupiter_program: AccountInfo<'a>,
    accounts: &[AccountInfo<'b>],
    data: Vec<u8>,
    signer_seeds: &[&[&[u8]]],
    vault_authority_key: &Pubkey,
) -> Result<()> {
    // **ENHANCED VALIDATION**: More detailed account validation
    if accounts.len() < 3 {
        msg!("❌ Insufficient accounts for Jupiter: {} (minimum: 3)", accounts.len());
        return Err(error!(ErrorCode::InsufficientAccounts));
    }
    
    // **CRITICAL DEBUG**: Log Jupiter CPI setup details
    msg!("🚀 Setting up Jupiter CPI:");
    msg!("  - Jupiter program: {}", jupiter_program.key());
    msg!("  - Accounts provided: {}", accounts.len());
    msg!("  - Instruction data: {} bytes", data.len());
    msg!("  - Vault authority: {}", vault_authority_key);
    
    // **FIX**: Capture data length before moving data
    let data_len = data.len();
    
    // Build AccountMeta array with proper authority handling
    let mut account_metas = Vec::new();
    let mut vault_authority_found = false;
    
    for (i, account) in accounts.iter().enumerate() {
        let account_meta = if account.key == vault_authority_key {
            vault_authority_found = true;
            // Vault authority will be the signer via PDA seeds
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: *account.key,
                is_signer: true,   // ✅ CRITICAL: Vault authority signs via CPI
                is_writable: account.is_writable,
            }
        } else {
            // All other accounts are not signers in CPI context
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: *account.key,
                is_signer: false,  // ✅ FIXED: Other accounts don't sign in CPI
                is_writable: account.is_writable,
            }
        };
        
        // **ENHANCED DEBUG**: Log each account being passed to Jupiter
        msg!("  Account[{}]: {} (signer: {}, writable: {})", 
             i, account.key, account_meta.is_signer, account_meta.is_writable);
        
        account_metas.push(account_meta);
    }
    
    // **CRITICAL FIX**: If vault authority not found in Jupiter accounts, we have a problem
    if !vault_authority_found {
        msg!("🚨 CRITICAL: Vault authority not found in Jupiter accounts!");
        msg!("   This means Jupiter transaction was not created with vault authority as signer");
        msg!("   Jupiter needs vault authority to be the payer/signer for the swap");
        return Err(error!(ErrorCode::InvalidAccountConfiguration));
    }
    
    // **CRITICAL VALIDATION**: Verify we have required account types
    let signers = account_metas.iter().filter(|acc| acc.is_signer).count();
    let writables = account_metas.iter().filter(|acc| acc.is_writable).count();
    
    msg!("📊 Jupiter account summary:");
    msg!("  - Total accounts: {}", account_metas.len());
    msg!("  - Signers: {}", signers);
    msg!("  - Writable: {}", writables);
    msg!("  - Vault authority present: {}", vault_authority_found);
    
    // **ADDITIONAL VALIDATION**: Ensure we have at least one signer
    if signers == 0 {
        msg!("🚨 ERROR: No signers found in Jupiter accounts!");
        msg!("   Jupiter requires vault authority as signer for swap execution");
        return Err(error!(ErrorCode::NoSignersFound));
    }
    
    // Create Jupiter instruction
    let jupiter_ix = anchor_lang::solana_program::instruction::Instruction {
        program_id: jupiter_program.key(),
        accounts: account_metas,
        data,
    };
    
    // **ENHANCED LOGGING**: Log instruction details
    msg!("🔧 Jupiter instruction created:");
    msg!("  - Program ID: {}", jupiter_ix.program_id);
    msg!("  - Account count: {}", jupiter_ix.accounts.len());
    msg!("  - Data length: {}", data_len);
    
    // Execute CPI with proper error handling
    msg!("🚀 Executing Jupiter CPI...");
    anchor_lang::solana_program::program::invoke_signed(
        &jupiter_ix,
        accounts,
        signer_seeds,
    ).map_err(|e| {
        // ✅ FIXED: Preserve actual error information with enhanced context
        msg!("❌ Jupiter CPI failed with error: {:?}", e);
        msg!("🔍 Error context:");
        msg!("  - Accounts provided: {}", accounts.len());
        msg!("  - Data length: {} bytes", data_len);
        msg!("  - Signer seeds: {} groups", signer_seeds.len());
        msg!("  - Vault authority found: {}", vault_authority_found);
        error!(ErrorCode::JupiterSwapFailed)
    })?;
    
    msg!("✅ Jupiter CPI completed successfully");
    Ok(())
}

/// Check Pyth price update staleness
pub fn check_price_staleness(
    price_update: &PriceUpdateV2,
) -> Result<()> {
    let current_timestamp = Clock::get()?.unix_timestamp;
    let price_timestamp = price_update.price_message.publish_time;
    
    // Check if price data is valid
    if price_update.price_message.price <= 0 {
        return Err(error!(ErrorCode::InvalidPriceData));
    }
    
    // Check price staleness
    let time_diff = current_timestamp.saturating_sub(price_timestamp);
    if time_diff > MAX_PRICE_STALENESS_SECONDS {
        return Err(error!(ErrorCode::PriceTooStale));
    }
    
    Ok(())
}

/// Processes the after-trade state, including updating the high water mark
pub fn after_trade(
    vault: &mut Vault,
    new_nav: u64,
) -> Result<()> {
    // Update high water mark if NAV has increased
    if new_nav > vault.high_water_mark_nav {
        // Calculate performance fee
        let fee = calculate_performance_fee(new_nav, vault.high_water_mark_nav)?;
        
        // Update high water mark to new NAV minus fee
        // This effectively "locks in" the fee at this point
        vault.high_water_mark_nav = new_nav.saturating_sub(fee);
    }
    
    Ok(())
}

// 🔒 CPI RATE LIMITING FUNCTIONS

/// Validate and track CPI calls to prevent spam attacks
/// Limits to 200 calls/hour per program for headroom
pub fn validate_and_track_cpi_call(
    vault: &mut Vault,
    program_id: &Pubkey,
    vault_key: &Pubkey,
) -> Result<()> {
    let current_time = Clock::get()?.unix_timestamp;
    
    // Find existing tracker for this program
    let mut tracker_found = false;
    for i in 0..vault.cpi_trackers_count as usize {
        if vault.cpi_call_counts[i].program_id == *program_id {
            let tracker = &mut vault.cpi_call_counts[i];
            
            // Reset counter if hour has passed (3600 seconds)
            if current_time - tracker.last_reset > 3600 {
                tracker.calls_per_hour = 0;
                tracker.last_reset = current_time;
            }
            
            // Check rate limit
            if tracker.calls_per_hour >= tracker.max_calls_per_hour {
                emit!(crate::state::SecurityEvent {
                    event_type: crate::state::SecurityEventType::RateLimitExceeded,
                    severity: crate::state::SecuritySeverity::High,
                    vault: *vault_key,
                    details: format!("CPI rate limit exceeded for program {}: {} calls/hour", 
                                   program_id, tracker.calls_per_hour),
                    timestamp: current_time,
                });
                return Err(error!(ErrorCode::CpiRateLimitExceeded));
            }
            
            tracker.calls_per_hour += 1;
            tracker_found = true;
            break;
        }
    }
    
    // Add new tracker if not found and space available
    if !tracker_found {
        if vault.cpi_trackers_count >= 2 {
            // Maximum trackers reached - this shouldn't happen in normal operation
            msg!("Maximum CPI trackers reached, cannot track new program: {}", program_id);
            return Err(error!(ErrorCode::CpiTrackingFailed));
        }
        
        let tracker_index = vault.cpi_trackers_count as usize;
        vault.cpi_call_counts[tracker_index] = crate::state::CpiCallTracker {
            program_id: *program_id,
            calls_per_hour: 1,
            last_reset: current_time,
            max_calls_per_hour: 200, // 200 calls/hour for headroom
        };
        vault.cpi_trackers_count += 1;
        
        msg!("Added new CPI tracker for program: {}", program_id);
    }
    
    Ok(())
}

/// Get CPI call statistics for monitoring
pub fn get_cpi_call_stats(vault: &Vault, program_id: &Pubkey) -> Option<(u32, u32, i64)> {
    for i in 0..vault.cpi_trackers_count as usize {
        if vault.cpi_call_counts[i].program_id == *program_id {
            let tracker = &vault.cpi_call_counts[i];
            return Some((
                tracker.calls_per_hour,
                tracker.max_calls_per_hour,
                tracker.last_reset,
            ));
        }
    }
    None
}

/// Reset CPI call counters (for emergency use only)
pub fn reset_cpi_counters(vault: &mut Vault) -> Result<()> {
    let current_time = Clock::get()?.unix_timestamp;
    
    for i in 0..vault.cpi_trackers_count as usize {
        vault.cpi_call_counts[i].calls_per_hour = 0;
        vault.cpi_call_counts[i].last_reset = current_time;
    }
    
    msg!("All CPI counters reset");
    Ok(())
}

/// Validate deposit amount for enhanced arithmetic safety
pub fn validate_deposit_amount(amount: u64) -> Result<()> {
    if amount == 0 {
        return Err(error!(ErrorCode::ZeroDeposit));
    }
    if amount > MAX_DEPOSIT_AMOUNT {
        return Err(error!(ErrorCode::DepositTooLarge));
    }
    Ok(())
}

// 🔒 SWITCHBOARD ORACLE INTEGRATION

/// Get validated price from Pyth primary oracle with Switchboard fallback
pub fn get_validated_price_with_fallback(
    token_mint: &Pubkey,
    primary_oracle: &AccountInfo,
    fallback_oracle: Option<&AccountInfo>,
) -> Result<(i64, i32)> {
    // Try primary oracle (Pyth) first
    match get_pyth_price(primary_oracle) {
        Ok((price, expo)) => {
            // Validate with Switchboard fallback if available
            if let Some(fallback) = fallback_oracle {
                if let Ok((fallback_price, fallback_expo)) = get_switchboard_price(fallback) {
                    // Check price deviation between oracles (max 5% difference)
                    if let Err(_) = validate_oracle_deviation(price, expo, fallback_price, fallback_expo) {
                        msg!("Oracle price deviation too high, using Pyth only");
                        // Still use Pyth price but log the deviation
                        emit!(crate::state::SecurityEvent {
                            event_type: crate::state::SecurityEventType::OracleFallbackTriggered,
                            severity: crate::state::SecuritySeverity::Medium,
                            vault: token_mint.key(), // Using token mint as identifier
                            details: format!("Oracle deviation detected: Pyth {} vs Switchboard {}", 
                                           price, fallback_price),
                            timestamp: Clock::get()?.unix_timestamp,
                        });
                    }
                }
            }
            Ok((price, expo))
        }
        Err(_) => {
            // Use Switchboard fallback if Pyth fails
            if let Some(fallback) = fallback_oracle {
                emit!(crate::state::SecurityEvent {
                    event_type: crate::state::SecurityEventType::OracleFallbackTriggered,
                    severity: crate::state::SecuritySeverity::High,
                    vault: token_mint.key(),
                    details: format!("Pyth oracle failed, using Switchboard fallback"),
                    timestamp: Clock::get()?.unix_timestamp,
                });
                get_switchboard_price(fallback)
            } else {
                Err(error!(ErrorCode::AllOraclesFailed))
            }
        }
    }
}

/// Parse Pyth price update using modern pull oracle SDK
pub fn get_pyth_price(price_account: &AccountInfo) -> Result<(i64, i32)> {
    let price_update_v2 = PriceUpdateV2::try_deserialize(
        &mut price_account.data.borrow().as_ref()
    ).map_err(|_| error!(ErrorCode::InvalidPriceData))?;
    
    // Check staleness
    check_price_staleness(&price_update_v2)?;
    
    // Check if price is valid
    if price_update_v2.price_message.price <= 0 {
        return Err(error!(ErrorCode::InvalidPriceData));
    }
    
    Ok((price_update_v2.price_message.price, price_update_v2.price_message.exponent))
}

/// Parse Switchboard price feed using official SDK
pub fn get_switchboard_price(feed_account: &AccountInfo) -> Result<(i64, i32)> {
    use switchboard_on_demand::on_demand::accounts::pull_feed::PullFeedAccountData;
    
    // Verify account is owned by Switchboard On-Demand program
    let switchboard_program_id = anchor_lang::prelude::Pubkey::from_str(SWITCHBOARD_MAINNET_PROGRAM_ID)
        .map_err(|_| error!(ErrorCode::InvalidSwitchboardProgram))?;
    
    if feed_account.owner != &switchboard_program_id {
        msg!("Invalid Switchboard feed owner: expected {}, got {}", 
             switchboard_program_id, feed_account.owner);
        return Err(error!(ErrorCode::InvalidSwitchboardFeed));
    }
    
    // Parse Switchboard feed account data
    let feed_data = feed_account.data.borrow();
    let feed = PullFeedAccountData::parse(feed_data)
        .map_err(|e| {
            msg!("Failed to parse Switchboard feed data: {:?}", e);
            error!(ErrorCode::InvalidSwitchboardFeed)
        })?;
    
    // Get the latest value with correct method signature
    // get_value(&Clock, max_staleness: u64, staleness_threshold: u32, min_responses: bool) 
    let clock = Clock::get()?;
    let max_staleness = SWITCHBOARD_STALENESS_SECONDS as u64; // Convert to u64
    let staleness_threshold = 30u32; // 30 second staleness threshold
    let min_responses = false; // Don't require minimum oracle responses (feeds are push-style)
    
    let price_decimal = feed.get_value(&clock, max_staleness, staleness_threshold, min_responses)
        .map_err(|e| {
            msg!("Switchboard feed get_value failed: {:?}", e);
            error!(ErrorCode::SwitchboardFeedStale)
        })?;
    
    // Convert Decimal to f64, then to fixed-point representation
    let price_f64: f64 = price_decimal.try_into()
        .map_err(|_| error!(ErrorCode::InvalidPriceData))?;
    
    // Convert to Pyth-compatible fixed-point format
    // Use 8 decimal places for price precision (similar to Pyth)
    let price_scaled = (price_f64 * 100_000_000.0) as i64;
    let exponent = -8i32; // 8 decimal places
    
    // Validate price is positive
    if price_scaled <= 0 {
        msg!("Invalid Switchboard price: {}", price_f64);
        return Err(error!(ErrorCode::InvalidPriceData));
    }
    
    msg!("Switchboard price: {} (scaled: {}, exp: {})", price_f64, price_scaled, exponent);
    
    Ok((price_scaled, exponent))
}

/// Validate price deviation between two oracle sources
pub fn validate_oracle_deviation(
    price1: i64,
    expo1: i32,
    price2: i64,
    expo2: i32,
) -> Result<()> {
    // Normalize prices to same exponent for comparison
    let (normalized_price1, normalized_price2) = if expo1 == expo2 {
        (price1, price2)
    } else if expo1 < expo2 {
        // price1 has smaller exponent (more precision), scale price2 up
        let scale_factor = 10i64.pow((expo1 - expo2) as u32);
        (price1, price2 * scale_factor)
    } else {
        // price2 has smaller exponent (more precision), scale price1 up
        let scale_factor = 10i64.pow((expo2 - expo1) as u32);
        (price1 * scale_factor, price2)
    };
    
    // Calculate percentage difference
    let avg_price = (normalized_price1 + normalized_price2) / 2;
    if avg_price == 0 {
        return Ok(()); // Both prices are zero, no deviation
    }
    
    let diff = (normalized_price1 - normalized_price2).abs();
    let deviation_pct = (diff * 100) / avg_price;
    
    // Allow max 5% deviation between oracle sources
    if deviation_pct > 5 {
        return Err(error!(ErrorCode::OracleDeviationTooHigh));
    }
    
    Ok(())
}


