// Test script to simulate vault arithmetic calculations
// This mimics the Rust calculations to check for overflow

// JavaScript's Number.MAX_SAFE_INTEGER is 2^53 - 1 = 9,007,199,254,740,991
// Rust u64 max is 2^64 - 1 = 18,446,744,073,709,551,615
const U64_MAX = BigInt("18446744073709551615");
const U128_MAX = BigInt("340282366920938463463374607431768211455");

// Simulate current vault state (approximate values)
const CURRENT_VAULT_NAV = 10_000_000_000n; // 10k USDC in micro-USDC
const CURRENT_TOTAL_SHARES = 10_000_000n;   // Existing shares (10 USDC worth at 1:1)

// New deposit
const DEPOSIT_AMOUNT = 10_000_000_000n;     // 10k USDC in micro-USDC
const DEPOSIT_FEE_BPS = 250n;               // 2.5%
const BPS_DIVISOR = 10_000n;

function calculateDepositFee(amount) {
    return (amount * DEPOSIT_FEE_BPS) / BPS_DIVISOR;
}

function calculateSharesOld(depositAmount, depositFee, totalShares, vaultNav) {
    console.log("\n=== OLD CALCULATION (u64 arithmetic) ===");
    
    const amountAfterFee = depositAmount - depositFee;
    console.log(`Amount after fee: ${amountAfterFee}`);
    console.log(`Total shares: ${totalShares}`);
    console.log(`Vault NAV: ${vaultNav}`);
    
    // This is where overflow happens in u64
    const multiplication = amountAfterFee * totalShares;
    console.log(`Multiplication (amount * shares): ${multiplication}`);
    console.log(`Is multiplication > u64 max? ${multiplication > U64_MAX}`);
    
    if (multiplication > U64_MAX) {
        console.log("❌ OVERFLOW! This would fail in Rust u64");
        return null;
    }
    
    const shares = multiplication / vaultNav;
    console.log(`Final shares: ${shares}`);
    return shares;
}

function calculateSharesNew(depositAmount, depositFee, totalShares, vaultNav) {
    console.log("\n=== NEW CALCULATION (u128 arithmetic) ===");
    
    const amountAfterFee = depositAmount - depositFee;
    console.log(`Amount after fee: ${amountAfterFee}`);
    
    // Using u128 arithmetic
    const multiplication = amountAfterFee * totalShares;
    console.log(`Multiplication (amount * shares): ${multiplication}`);
    console.log(`Is multiplication > u128 max? ${multiplication > U128_MAX}`);
    
    if (multiplication > U128_MAX) {
        console.log("❌ OVERFLOW! This would fail even in Rust u128");
        return null;
    }
    
    const shares = multiplication / vaultNav;
    console.log(`Final shares: ${shares}`);
    console.log("✅ SUCCESS! No overflow with u128");
    return shares;
}

function testScenario(description, depositAmount, vaultNav, totalShares) {
    console.log(`\n🧪 TESTING: ${description}`);
    console.log(`Deposit: ${depositAmount / 1_000_000n} USDC`);
    console.log(`Vault NAV: ${vaultNav / 1_000_000n} USDC`);
    console.log(`Total Shares: ${totalShares}`);
    
    const depositFee = calculateDepositFee(depositAmount);
    console.log(`Deposit fee: ${depositFee / 1_000_000n} USDC`);
    
    calculateSharesOld(depositAmount, depositFee, totalShares, vaultNav);
    calculateSharesNew(depositAmount, depositFee, totalShares, vaultNav);
}

// Test current scenario
testScenario(
    "Current 10k deposit scenario",
    10_000_000_000n,  // 10k USDC
    20_000_000_000n,  // 20k USDC total NAV (10k existing + 10k new)
    10_000_000n       // 10M shares (from first deposit)
);

// Test extreme scenario
testScenario(
    "Extreme scenario (1M USDC deposit, 100M shares)",
    1_000_000_000_000n,  // 1M USDC
    1_000_000_000_000n,  // 1M USDC NAV
    100_000_000_000_000n // 100M shares
);

// Test what would break u64
const problematicAmount = 10_000_000_000n;  // 10k USDC
const problematicShares = 2_000_000_000n;   // 2B shares
const problematicNav = 1_000_000_000n;      // 1k USDC NAV

testScenario(
    "Scenario that breaks u64",
    problematicAmount,
    problematicNav,
    problematicShares
); 