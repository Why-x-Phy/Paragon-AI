const { HermesClient } = require('@pythnetwork/hermes-client');

// Test proper Pyth SDK usage with HermesClient
async function testPythSDKUsage() {
    console.log('Testing proper Pyth SDK usage with HermesClient...\n');
    
    // Price feed IDs from your oracle_config.rs (these are CORRECT!)
    const PRICE_FEED_IDS = [
        "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a", // USDC
        "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a", // TRUMP
        "0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d", // RENDER
        "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996", // JUP
        "0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419", // BONK
        "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608", // FARTCOIN
        "0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc", // WIF
        // Add more as needed
    ];

    const connection = new HermesClient("https://hermes.pyth.network", {});
    
    try {
        console.log('=== Fetching Price Feeds ===');
        
        // Get latest price updates for all your price feeds
        const priceUpdates = await connection.getLatestPriceUpdates(PRICE_FEED_IDS);
        console.log('✓ Successfully fetched price updates');
        console.log(`Number of price updates: ${priceUpdates.length}`);
        
        // You can also fetch price feeds for specific assets
        console.log('\n=== Fetching Specific Price Feeds ===');
        const btcPriceFeeds = await connection.getPriceFeeds("btc", "crypto");
        console.log('BTC price feeds:', btcPriceFeeds.slice(0, 2)); // Show first 2
        
        console.log('\n=== Integration Flow ===');
        console.log('1. ✓ Use HermesClient to fetch price updates');
        console.log('2. → Pass priceUpdates to your Solana program');
        console.log('3. → Verify and use prices in your NAV calculation');
        
        // Example of what you'd do next:
        console.log('\n=== Next Steps for Solana Integration ===');
        console.log('// In your TypeScript client:');
        console.log('const priceUpdates = await hermesClient.getLatestPriceUpdates(priceIds);');
        console.log('// Then pass priceUpdates to your Solana instruction');
        console.log('await program.methods.calculateNav().accounts({');
        console.log('  // ... your accounts');
        console.log('}).instruction();');
        
    } catch (error) {
        console.error('Error fetching price updates:', error);
    }
}

// Correct approach comparison
function showCorrectApproach() {
    console.log('\n=== CORRECT APPROACH (using HermesClient) ===');
    console.log('✓ Use HermesClient from @pythnetwork/hermes-client');
    console.log('✓ Your hex price feed IDs are CORRECT as-is');
    console.log('✓ Fetch price updates with getLatestPriceUpdates()');
    console.log('✓ Pass price updates to your Solana program');
    console.log('✓ No manual hex-to-pubkey conversion needed');
    
    console.log('\n=== TypeScript Example ===');
    console.log(`
import { HermesClient } from '@pythnetwork/hermes-client';

const hermesClient = new HermesClient("https://hermes.pyth.network", {});

const priceIds = [
  "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a", // USDC
  "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a", // TRUMP
  // ... more price IDs
];

// Get latest price updates
const priceUpdates = await hermesClient.getLatestPriceUpdates(priceIds);

// Use in your Solana program
await program.methods
  .calculateNav()
  .accounts({
    // your accounts
  })
  .rpc();
    `);
}

// Required packages for TypeScript
console.log('=== REQUIRED NPM PACKAGES (TypeScript) ===');
console.log('npm install @pythnetwork/hermes-client');
console.log('npm install @pythnetwork/pyth-solana-receiver');  // For Solana-specific operations

showCorrectApproach();
testPythSDKUsage(); 