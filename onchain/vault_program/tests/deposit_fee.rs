#![cfg(test)]

use vault::constants::*;

mod utils {
    pub fn calculate_deposit_fee(amount: u64, fee_bps: u64, bps_divisor: u64) -> u64 {
        amount.checked_mul(fee_bps).unwrap().checked_div(bps_divisor).unwrap()
    }
}

#[test]
fn test_deposit_fee() {
    // Test with various amounts to ensure the 2.5% fee is calculated correctly
    
    // Test with 100 USDC (6 decimal places)
    let amount = 100_000_000; // 100 USDC with 6 decimals
    let expected_fee = 2_500_000; // 2.5 USDC
    let actual_fee = utils::calculate_deposit_fee(amount, DEPOSIT_FEE_BPS, BPS_DIVISOR);
    assert_eq!(actual_fee, expected_fee, "Fee should be 2.5% of 100 USDC");
    
    // Test with 1000 USDC
    let amount = 1_000_000_000; // 1000 USDC with 6 decimals
    let expected_fee = 25_000_000; // 25 USDC
    let actual_fee = utils::calculate_deposit_fee(amount, DEPOSIT_FEE_BPS, BPS_DIVISOR);
    assert_eq!(actual_fee, expected_fee, "Fee should be 2.5% of 1000 USDC");
    
    // Test with odd amount that doesn't divide evenly
    let amount = 123_456_789; // 123.456789 USDC
    let expected_fee = 3_086_420; // 3.08642 USDC
    let actual_fee = utils::calculate_deposit_fee(amount, DEPOSIT_FEE_BPS, BPS_DIVISOR);
    assert_eq!(actual_fee, expected_fee, "Fee should be 2.5% of 123.456789 USDC");
    
    // Test with smallest possible USDC amount (1 lamport)
    let amount = 1;
    let expected_fee = 0; // Fee rounds down to 0 for tiny amounts
    let actual_fee = utils::calculate_deposit_fee(amount, DEPOSIT_FEE_BPS, BPS_DIVISOR);
    assert_eq!(actual_fee, expected_fee, "Fee should be 0 for 1 lamport due to integer division");
    
    // Test with amount that produces the smallest non-zero fee
    let amount = 40; // Need at least 40 to get a non-zero fee with 2.5%
    let expected_fee = 1;
    let actual_fee = utils::calculate_deposit_fee(amount, DEPOSIT_FEE_BPS, BPS_DIVISOR);
    assert_eq!(actual_fee, expected_fee, "Fee should be 1 lamport for 40 lamports");
    
    println!("All deposit fee tests passed!");
} 