use anchor_lang::prelude::*;
use anchor_spl::token::{self, TokenAccount, Mint, Transfer};
use pyth_sdk_solana::state::{PriceStatus};
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
                    // UserStake structure: [user_authority(32), total_staked(8), tier(1), ...]
                    if data.len() >= 41 {
                        // Read the tier field (byte 40)
                        data[40]
                    } else {
                        msg!("Invalid user stake account size");
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

/// Calculate the current NAV in USDC using oracle price feeds
/// 
/// remaining_accounts structure:
/// [0..1] - Staking program accounts (stake_config, user_stake) 
/// [2..] - Oracle data in groups of 3: [token_account, price_account, mint_account]
pub fn current_nav_usdc(
    _vault: &Vault,
    usdc_token_account: &Account<TokenAccount>,
    remaining_accounts: &[AccountInfo],
) -> Result<u64> {
    msg!("Calculating NAV with {} remaining accounts", remaining_accounts.len());
    
    // Start with USDC balance (no conversion needed)
    let mut total_nav_usdc = usdc_token_account.amount;
    msg!("USDC balance: {}", total_nav_usdc);
    
    // Skip first 2 accounts (staking program accounts)
    if remaining_accounts.len() < 2 {
        msg!("No oracle accounts provided, returning USDC balance only");
        return Ok(total_nav_usdc);
    }
    
    let oracle_accounts = &remaining_accounts[2..];
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
        
        // Parse Pyth price feed using the raw account data approach
        let price_account_data = price_account_info.data.borrow();
        let price_feed: &pyth_sdk_solana::state::SolanaPriceAccount = match pyth_sdk_solana::state::load_price_account(&price_account_data) {
            Ok(feed) => feed,
            Err(e) => {
                msg!("Failed to load price account {}: {:?}", i, e);
                continue; // Skip invalid price feeds
            }
        };
        
        // Check price status and staleness
        if price_feed.agg.status != PriceStatus::Trading {
            msg!("Price not trading for token {}", i);
            continue;
        }
        
        // Basic staleness check
        let current_time = Clock::get()?.unix_timestamp;
        let price_time = price_feed.timestamp;
        if current_time - price_time > MAX_PRICE_STALENESS_SECONDS {
            msg!("Price too stale for token {}", i);
            continue;
        }
        
        // Calculate value in USDC
        match calculate_token_value_usdc(
            token_account.amount,
            mint_account.decimals,
            price_feed.agg.price,
            price_feed.expo,
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
        return Ok(amount_after_fee);
    }
    
    // Calculate shares based on proportion of NAV
    let shares = amount_after_fee
        .checked_mul(total_shares)
        .ok_or(error!(ErrorCode::ArithmeticError))?
        .checked_div(vault_nav)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
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
    
    let amount = shares
        .checked_mul(vault_nav)
        .ok_or(error!(ErrorCode::ArithmeticError))?
        .checked_div(total_shares)
        .ok_or(error!(ErrorCode::ArithmeticError))?;
    
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
    // Validate minimum required accounts
    if accounts.len() < 3 {
        return Err(error!(ErrorCode::InsufficientAccounts));
    }
    
    // Build AccountMeta array with proper authority handling
    let mut account_metas = Vec::new();
    
    for account in accounts.iter() {
        let account_meta = if account.key == vault_authority_key {
            // Vault authority will be the signer via PDA seeds
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: *account.key,
                is_signer: true,   // ✅ FIXED: Vault authority signs via CPI
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
        account_metas.push(account_meta);
    }
    
    // Create Jupiter instruction
    let jupiter_ix = anchor_lang::solana_program::instruction::Instruction {
        program_id: jupiter_program.key(),
        accounts: account_metas,
        data,
    };
    
    // Execute CPI with proper error handling
    anchor_lang::solana_program::program::invoke_signed(
        &jupiter_ix,
        accounts,
        signer_seeds,
    ).map_err(|e| {
        // ✅ FIXED: Preserve actual error information
        msg!("Jupiter CPI failed: {:?}", e);
        error!(ErrorCode::JupiterSwapFailed)
    })
}

/// Check Pyth price feed staleness
pub fn check_price_staleness(
    price_feed: &pyth_sdk_solana::state::SolanaPriceAccount,
) -> Result<()> {
    let current_timestamp = Clock::get()?.unix_timestamp;
    let price_timestamp = price_feed.timestamp;
    
    // Check if price is valid - use agg.status instead of ptype
    if price_feed.agg.status != PriceStatus::Trading {
        return Err(error!(ErrorCode::PriceNotTrading));
    }
    
    // Check if price data is valid
    if price_feed.agg.price == 0 {
        return Err(error!(ErrorCode::InvalidPriceType));
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

/// Parse Pyth price feed
pub fn get_pyth_price(price_account: &AccountInfo) -> Result<(i64, i32)> {
    let price_account_data = price_account.data.borrow();
    let price_feed: &pyth_sdk_solana::state::SolanaPriceAccount = pyth_sdk_solana::state::load_price_account(&price_account_data)
        .map_err(|_| error!(ErrorCode::InvalidPriceData))?;
    
    // Check price status and staleness
    if price_feed.agg.status != PriceStatus::Trading {
        return Err(error!(ErrorCode::PriceNotTrading));
    }
    
    // Check staleness
    let current_time = Clock::get()?.unix_timestamp;
    if current_time - price_feed.timestamp > MAX_PRICE_STALENESS_SECONDS {
        return Err(error!(ErrorCode::PriceTooStale));
    }
    
    Ok((price_feed.agg.price, price_feed.expo))
}

/// Parse Switchboard price feed using official SDK
pub fn get_switchboard_price(feed_account: &AccountInfo) -> Result<(i64, i32)> {
    use switchboard_on_demand::on_demand::accounts::pull_feed::PullFeedAccountData;
    
    // Parse Switchboard feed account data
    let feed_data = feed_account.data.borrow();
    let feed = PullFeedAccountData::parse(feed_data)
        .map_err(|_| error!(ErrorCode::InvalidSwitchboardFeed))?;
    
    // Get the latest value using the get_value method with proper parameters
    // Based on switchboard-on-demand 0.3.8, we need to provide Clock and max_staleness
    let clock = Clock::get()?;
    let max_staleness_slots = (SWITCHBOARD_STALENESS_SECONDS / 400) as u64; // ~400ms per slot
    
    // Use get_value method which is the correct approach for switchboard-on-demand
    // Method signature: get_value(&Clock, max_staleness_slots: u64, min_samples: u32, use_cached: bool)
    let decimal_value = feed.get_value(&clock, max_staleness_slots, 1, true)
        .map_err(|_| error!(ErrorCode::SwitchboardFeedStale))?;
    
    // Convert SwitchboardDecimal to i64 price and i32 exponent
    // SwitchboardDecimal stores value as mantissa * 10^(-scale)
    let mantissa = decimal_value.mantissa();
    let scale = decimal_value.scale();
    
    // Convert to Pyth-compatible format (price, expo)
    // Keep the original scale to preserve token-specific decimal precision
    let price_i64 = i64::try_from(mantissa)
        .map_err(|_| error!(ErrorCode::InvalidPriceData))?;
    
    // Switchboard scale is positive (decimal places), Pyth expo is negative
    let expo = -(scale as i32);
    
    Ok((price_i64, expo))
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


