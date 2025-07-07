// Test Pyth integration in frontend environment
console.log('🚀 Testing Pyth in Frontend Environment...\n');

async function testPythFrontend() {
  try {
    console.log('1️⃣ Testing imports...');
    
    // Test if packages can be imported without errors
    const { HermesClient } = await import('@pythnetwork/hermes-client');
    console.log('   ✅ HermesClient imported successfully');
    
    const { PythSolanaReceiver } = await import('@pythnetwork/pyth-solana-receiver');
    console.log('   ✅ PythSolanaReceiver imported successfully');
    
    console.log('\n2️⃣ Testing basic functionality...');
    
    const hermesClient = new HermesClient('https://hermes.pyth.network');
    console.log('   ✅ HermesClient created');
    
    // Test a quick price fetch
    const priceIds = ['0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a']; // TRUMP/USD
    const priceUpdates = await hermesClient.getLatestPriceUpdates(priceIds);
    console.log('   ✅ Price fetched successfully');
    console.log(`   📊 Got ${priceUpdates.binary.data.length} price update(s)`);
    
    console.log('\n🎉 SUCCESS! Pyth works perfectly in frontend!');
    console.log('✨ You can now integrate directly without a separate service!');
    
  } catch (error) {
    console.error('❌ Error:', error.message);
    console.error('Stack:', error.stack);
  }
}

testPythFrontend(); 