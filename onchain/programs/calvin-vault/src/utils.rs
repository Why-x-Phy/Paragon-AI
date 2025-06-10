use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};
use pyth_sdk_solana::state::{PriceAccount, PriceStatus};

use crate::{constants::*, state::*, ErrorCode};

/// Verify user's tier via CPI call to staking program and check deposit caps
pub fn verify_tier_and_check_cap(
    staking_program: &AccountInfo,
    user: &Pubkey,
    current_deposits: u64,
    new_deposit: u64,
    vault: &Vault,
    remaining_accounts: &[AccountInfo],
) -> Result<()> {
    // TODO: Implement actual CPI call to staking program's verify_tier instruction
    // For now, we'll do a simplified check that allows all deposits
    // This should be replaced with proper CPI integration
    
    // Placeholder: assume user is tier 3 for now
    let user_tier = TIER_3;
    
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

/// Calculates the current total value of the vault in USDC
/// This function uses Pyth oracle prices to calculate the total value of all tokens in the vault
pub fn current_nav_usdc<'info>(
    vault: &Vault,
    usdc_vault: &Account<'info, TokenAccount>,
    token_accounts: &[Account<'info, TokenAccount>],
    price_accounts: &[AccountInfo<'info>],
    token_mints: &[Pubkey],
) -> Result<u64> {
    let mut total_nav = usdc_vault.amount; // Start with USDC balance
    
    // Skip the first account if it's the USDC account (already counted)
    for (i, token_account) in token_accounts.iter().enumerate() {
        // Skip if this is the USDC account
        if token_account.mint == vault.usdc_mint {
            continue;
        }
        
        // Only process accounts with non-zero balances
        if token_account.amount == 0 {
            continue;
        }
        
        // Get the corresponding price account and mint
        if i >= price_accounts.len() || i >= token_mints.len() {
            // If we don't have a price for this token, we skip it
            // In a real implementation, we might want to return an error or handle this differently
            continue;
        }
        
        // Parse the price account
        let price_account_info = &price_accounts[i];
        // Borrow the account data separately so the reference lives long enough
        let price_data = price_account_info.data.borrow();
        let price_feed = match pyth_sdk_solana::state::load_price_account(&price_data) {
            Ok(feed) => feed,
            Err(_) => {
                // Skip invalid price feeds
                continue;
            }
        };
        
        // Check price staleness
        if check_price_staleness(&price_feed).is_err() {
            // Skip stale prices
            continue;
        }
        
        // Get token decimals
        // In a real implementation, you would query the mint for this information
        // For simplicity, we assume all tokens have 6 decimals like USDC
        // This should be replaced with actual mint queries in production
        let token_decimals = 6u8; 
        let token_decimal_factor = 10u64.pow(token_decimals as u32);
        
        // Calculate USDC value of this token position
        let token_balance = token_account.amount;
        
        // Get price from Pyth (as a fixed-point number)
        let price = price_feed.agg.price;
        
        // Convert price to USDC terms (Pyth prices are in USD, assuming 1 USDC = $1)
        // Pyth prices are in the format 10^(exponent), so we need to adjust
        let price_in_usdc = price
            .checked_mul(10i64.pow(price_feed.expo.unsigned_abs()))
            .ok_or(error!(ErrorCode::ArithmeticError))?;
        
        // Calculate token value in USDC
        // token_value = token_balance * price_in_usdc / token_decimal_factor
        let token_value = token_balance
            .checked_mul(price_in_usdc as u64)
            .ok_or(error!(ErrorCode::ArithmeticError))?
            .checked_div(token_decimal_factor)
            .ok_or(error!(ErrorCode::ArithmeticError))?;
        
        // Add to total NAV
        total_nav = total_nav
            .checked_add(token_value)
            .ok_or(error!(ErrorCode::ArithmeticError))?;
    }
    
    Ok(total_nav)
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
    vault: &Vault,
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
pub fn forward_jupiter<'info>(
    jupiter_program: AccountInfo<'info>,
    accounts: &[AccountInfo<'info>],
    data: Vec<u8>,
    signer_seeds: &[&[&[u8]]],
) -> Result<()> {
    let ix = anchor_lang::solana_program::instruction::Instruction {
        program_id: jupiter_program.key(),
        accounts: accounts.iter().map(|a| anchor_lang::solana_program::instruction::AccountMeta {
            pubkey: *a.key,
            is_signer: a.is_signer,
            is_writable: a.is_writable,
        }).collect(),
        data,
    };
    
    anchor_lang::solana_program::program::invoke_signed(
        &ix,
        accounts,
        signer_seeds,
    ).map_err(|_| error!(ErrorCode::JupiterSwapFailed))
}

/// Check Pyth price feed staleness
pub fn check_price_staleness(
    price_feed: &PriceAccount,
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
