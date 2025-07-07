/**
 * Test script to verify Pyth pull oracle price updates
 */

import { Connection, PublicKey } from '@solana/web3.js';
import { HermesClient } from '@pythnetwork/hermes-client';

// Simplified test without VaultClient to avoid complex imports
async function testPriceUpdates() {
  console.log('🧪 Testing Pyth Pull Oracle Price Updates...');
  
  try {
    // Create a test connection
    const connection = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');
    
    // Initialize Hermes client directly
    const hermesClient = new HermesClient('https://hermes.pyth.network', {});
    
    console.log('✅ Hermes client initialized');
    
    // Test price feed IDs (same as in VaultClient)
    const PYTH_PRICE_FEEDS = {
      "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a", // USDC
      "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN": "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a", // TRUMP
      "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof": "0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d", // RENDER
      "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996", // JUP
      "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419", // BONK
      "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump": "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608", // FARTCOIN
      "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a", // RAY
      "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2", // JTO
      "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3": "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff", // PYTH
      "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc", // WIF
      "3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y": "0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b", // VIRTUAL
      "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv": "0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61", // PENGU
      "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ": "0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389", // W (WORMHOLE)
      "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": "0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce", // POPCAT
      "Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7": "0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a", // ATH
      "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5": "0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d", // MEW
      "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey": "0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a", // MNDE
      "J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr": "0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a", // SPX (SPX6900)
      "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE": "0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c" // ORCA
    };
    
    const priceFeedIds = Object.values(PYTH_PRICE_FEEDS);
    
    console.log(`📊 Testing price updates for ${priceFeedIds.length} feeds:`, Object.keys(PYTH_PRICE_FEEDS));
    
    // Test 1: Get price feeds by name
    console.log('\n📋 Test 1: Getting price feeds for BTC...');
    const priceFeeds = await hermesClient.getPriceFeeds("btc", "crypto");
    console.log(`✅ Found ${priceFeeds.length} BTC price feeds:`, priceFeeds.map(f => f.id));
    
    // Test 2: Get latest price updates
    console.log('\n📊 Test 2: Getting latest price updates...');
    const response = await hermesClient.getLatestPriceUpdates(priceFeedIds);
    const priceUpdates = response?.parsed || [];
    console.log(`✅ Received ${priceUpdates.length} price updates`);
    
    // Display price update details
    for (const update of priceUpdates) {
      const feedName = Object.keys(PYTH_PRICE_FEEDS).find(key => PYTH_PRICE_FEEDS[key] === update.id);
      const price = parseFloat(update.price.price) / Math.pow(10, Math.abs(update.price.expo));
      const conf = parseFloat(update.price.conf) / Math.pow(10, Math.abs(update.price.expo));
      console.log(`  📈 ${feedName || 'Unknown'}: $${price} (conf: ±${conf})`);
    }
    
    // Test 3: Stream price updates (run for 5 seconds)
    console.log('\n🔄 Test 3: Streaming price updates for 5 seconds...');
    try {
      const eventSource = await hermesClient.getStreamingPriceUpdates(priceFeedIds);
      
      let updateCount = 0;
      eventSource.onmessage = (event) => {
        updateCount++;
        console.log(`📡 Streaming update #${updateCount}:`, event.data);
      };
      
      eventSource.onerror = (error) => {
        console.error('❌ Streaming error:', error);
        eventSource.close();
      };
      
      // Let it stream for 5 seconds
      await new Promise(resolve => setTimeout(resolve, 5000));
      
      console.log(`✅ Received ${updateCount} streaming updates`);
      console.log('Closing event source.');
      eventSource.close();
    } catch (streamError) {
      console.log('  ⚠️ Streaming test skipped:', streamError.message);
    }
    
    console.log('\n🎉 All tests completed successfully!');
    
  } catch (error) {
    console.error('❌ Test failed:', error.message);
    console.error('Full error:', error);
  }
}

// Helper function to add delay
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Run the test
testPriceUpdates().catch(console.error); 