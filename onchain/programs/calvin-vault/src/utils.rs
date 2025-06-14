use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};
use pyth_sdk_solana::state::{PriceAccount, PriceStatus};

use crate::{constants::*, state::*, ErrorCode};

// Oracle configuration functions
// Note: This would be better as a separate module, but for now we'll include the logic here

/// Get oracle pubkey for a specific token mint
pub fn get_oracle_for_token_mint(token_mint: &Pubkey) -> Option<Pubkey> {
    // Token mint to symbol mapping
    let token_mint_str = token_mint.to_string();
    
    let symbol = match token_mint_str.as_str() {
        "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU" => "USDC", // Devnet USDC
        "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN" => "TRUMP",
        "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof" => "RENDER",
        "JUPyiwrYJFskUPiHa7hc8VUtAeFoSYbKedZNsD7c" => "JUP",
        "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263" => "BONK",
        "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump" => "FARTCOIN",
        "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R" => "RAY",
        "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL" => "JTO",
        "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3npgxbkkTs8LG" => "PYTH",
        "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm" => "WIF",
        "BUjZjAS2vbbb65g7Z1Ca9ZRVYoJscURG5L3AkVXHP2ac" => "VIRTUAL",
        "3Bmj7x4udgJhKa43EYRcmNq2JLkgz7eAayFn8qYhyXKV" => "PENGU",
        "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ" => "W",
        "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr" => "POPCAT",
        "ATHdb8YvGvBVhgJB3PaMU5sCdAUHkhkN42jdYWK4h2xQ" => "ATH",
        "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5" => "MEW",
        "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey" => "MNDE",
        "AUKyeqDfN8p6B93X9gYCnCpdJUfvxU6ZWEmAy2VKqm3w" => "SPX",
        "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE" => "ORCA",
        _ => return None,
    };
    
    // Convert hex string to Pubkey for the given symbol
    let hex_str = match symbol {
        "USDC" => "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
        "TRUMP" => "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a",
        "RENDER" => "0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d",
        "JUP" => "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996",
        "BONK" => "0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419",
        "FARTCOIN" => "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608",
        "RAY" => "0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a",
        "JTO" => "0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2",
        "PYTH" => "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d0d719579ff",
        "WIF" => "0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc",
        "VIRTUAL" => "0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b",
        "PENGU" => "0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61",
        "W" => "0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389",
        "POPCAT" => "0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce",
        "ATH" => "0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a",
        "MEW" => "0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d",
        "MNDE" => "0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a",
        "SPX" => "0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a",
        "ORCA" => "0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c",
        _ => return None,
    };
    
    // Convert hex string to pubkey
    hex_string_to_pubkey(hex_str).ok()
}

/// Convert hex string to Pubkey
fn hex_string_to_pubkey(hex_str: &str) -> Result<Pubkey> {
    let hex_clean = hex_str.strip_prefix("0x").unwrap_or(hex_str);
    
    // Decode hex string to bytes
    let mut bytes = [0u8; 32];
    if hex_clean.len() != 64 {
        return Err(error!(ErrorCode::InvalidOracleAccount));
    }
    
    for i in 0..32 {
        let byte_str = &hex_clean[i*2..i*2+2];
        bytes[i] = u8::from_str_radix(byte_str, 16)
            .map_err(|_| error!(ErrorCode::InvalidOracleAccount))?;
    }
    
    Ok(Pubkey::from(bytes))
}

/// Verify user's tier via CPI call to staking program and check deposit caps
pub fn verify_tier_and_check_cap(
    staking_program: &AccountInfo,
    user: &Pubkey,
    current_deposits: u64,
    new_deposit: u64,
    vault: &Vault,
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

/// Calculates the current total value of the vault in USDC using Pyth oracle prices
/// Updated to use oracle configuration and properly validate price accounts
pub fn current_nav_usdc<'info>(
    vault: &Vault,
    usdc_vault: &Account<'info, TokenAccount>,
    token_accounts: &[Account<'info, TokenAccount>],
    price_accounts: &[AccountInfo<'info>],
    token_mints: &[Pubkey],
) -> Result<u64> {
    msg!("Calculating NAV with {} token accounts and {} price accounts", 
         token_accounts.len(), price_accounts.len());
    
    let mut total_nav = usdc_vault.amount; // Start with USDC balance
    msg!("Starting NAV with USDC balance: {}", total_nav);
    
    // Process each token account
    for (i, token_account) in token_accounts.iter().enumerate() {
        // Skip if this is the USDC account (already counted)
        if token_account.mint == vault.usdc_mint {
            msg!("Skipping USDC account (already counted)");
            continue;
        }
        
        // Only process accounts with non-zero balances
        if token_account.amount == 0 {
            msg!("Skipping token with zero balance: {}", token_account.mint);
            continue;
        }
        
        // Find the oracle account for this token mint
        let token_mint = &token_account.mint;
        let oracle_pubkey = match get_oracle_for_token_mint(token_mint) {
            Some(oracle) => oracle,
            None => {
                msg!("No oracle found for token mint: {}, skipping", token_mint);
                continue;
            }
        };
        
        // Find the corresponding price account in remaining_accounts
        let price_account_info = match price_accounts.iter()
            .find(|acc| acc.key() == oracle_pubkey) {
            Some(acc) => acc,
            None => {
                msg!("Oracle account not provided for token: {}, expected: {}", 
                     token_mint, oracle_pubkey);
                continue;
            }
        };
        
        // Parse the price account
        let price_data = price_account_info.data.borrow();
        let price_feed = match pyth_sdk_solana::state::load_price_account(&price_data) {
            Ok(feed) => feed,
            Err(e) => {
                msg!("Failed to parse price account for {}: {:?}", token_mint, e);
                continue;
            }
        };
        
        // Check price staleness
        if check_price_staleness(&price_feed).is_err() {
            msg!("Stale price for token: {}, skipping", token_mint);
            continue;
        }
        
        // Get token decimals (hardcoded for now, should query mint in production)
        let token_decimals = match get_token_decimals(token_mint) {
            Some(decimals) => decimals,
            None => {
                msg!("Unknown decimals for token: {}, assuming 9", token_mint);
                9u8 // Most Solana tokens have 9 decimals
            }
        };
        let token_decimal_factor = 10u64.pow(token_decimals as u32);
        
        // Calculate USDC value of this token position
        let token_balance = token_account.amount;
        let price = price_feed.agg.price;
        let price_expo = price_feed.expo;
        
        msg!("Processing token: {} with balance: {}, price: {}, expo: {}", 
             token_mint, token_balance, price, price_expo);
        
        // Convert price to proper decimal format
        // Pyth prices are in the format price * 10^expo
        let (price_in_usdc, overflow) = if price_expo >= 0 {
            // Positive exponent: multiply
            price.checked_mul(10i64.pow(price_expo as u32))
                .map(|p| (p as u64, false))
                .unwrap_or((0, true))
                 } else {
             // Negative exponent: divide
             ((price / 10i64.pow(price_expo.unsigned_abs())) as u64, false)
         };
        
        if overflow || price_in_usdc == 0 {
            msg!("Price overflow or zero for token: {}, skipping", token_mint);
            continue;
        }
        
        // Calculate token value in USDC
        // For proper calculation: token_value = (token_balance * price_in_usdc) / token_decimal_factor
        let token_value = match token_balance
            .checked_mul(price_in_usdc)
            .and_then(|v| v.checked_div(token_decimal_factor)) {
            Some(value) => value,
            None => {
                msg!("Arithmetic overflow calculating value for token: {}", token_mint);
                continue;
            }
        };
        
        msg!("Token {} value: {} USDC", token_mint, token_value);
        
        // Add to total NAV
        total_nav = match total_nav.checked_add(token_value) {
            Some(new_nav) => new_nav,
            None => {
                msg!("NAV overflow when adding token value");
                return Err(error!(ErrorCode::ArithmeticError));
            }
        };
    }
    
    msg!("Final NAV: {} USDC", total_nav);
    Ok(total_nav)
}

/// Get token decimals for known tokens (hardcoded for now)
/// In production, this should query the mint account
fn get_token_decimals(token_mint: &Pubkey) -> Option<u8> {
    let token_mint_str = token_mint.to_string();
    
    // Known token decimals
    match token_mint_str.as_str() {
        "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU" => Some(6), // USDC (Devnet)
        "So11111111111111111111111111111111111111112" => Some(9),  // SOL
        "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263" => Some(5), // BONK
        "JUPyiwrYJFskUPiHa7hc8VUtAeFoSYbKedZNsD7c" => Some(6),    // JUP
        _ => None, // Default to querying mint (not implemented here)
    }
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
