import pkg from '@switchboard-xyz/on-demand';
const { CrossbarClient, PullFeed } = pkg;
import { Connection, PublicKey } from '@solana/web3.js';

async function testOracleAvailability() {
  console.log('🔍 Testing Switchboard Oracle Availability Across Multiple Feeds');
  console.log('============================================================');
  
  const connection = new Connection('https://api.mainnet-beta.solana.com');
  const crossbarClient = new CrossbarClient('https://crossbar.switchboard.xyz');
  
  // Test a few different feeds
  const testFeeds = [
    { name: 'ATH', address: '3wadb2fsPkDNpQazr5VFa9A2BoLcEWMrPcPHNACFBDvt' },
    { name: 'USDC', address: '8F7VKK7ZtL3moBzV4QSkzPZo2xSUx15K6wv1G1QZQDix' },
    { name: 'SOL', address: '9BHh6RVPCt7ijv6K5MukZjeCUBtamHQXhRUr1TeudgUL' },
    { name: 'BONK', address: '68FbNAyrhME3DrSRSyKjuTFdQZ5b4erzK6uJQ3RTkitn' },
    { name: 'JUP', address: 'G8oxFvUWzVYE3saje8Z9JuBrn1qf4puwKQkbNU6PU4su' }
  ];
  
  let workingFeeds = 0;
  let failedFeeds = 0;
  
  for (const feed of testFeeds) {
    console.log(`\n📊 Testing ${feed.name} feed: ${feed.address}`);
    
    try {
      // Check if account exists
      const accountInfo = await connection.getAccountInfo(new PublicKey(feed.address));
      if (!accountInfo) {
        console.log(`❌ ${feed.name}: Account not found`);
        failedFeeds++;
        continue;
      }
      
      console.log(`✅ ${feed.name}: Account exists (${accountInfo.data.length} bytes)`);
      
      // Test simulation
      try {
        const simulation = await crossbarClient.simulateFeeds([feed.address]);
        console.log(`✅ ${feed.name}: Simulation successful - $${simulation[0]?.toFixed(8)}`);
      } catch (simError) {
        console.log(`❌ ${feed.name}: Simulation failed - ${simError.message}`);
        failedFeeds++;
        continue;
      }
      
      // Try to get oracle responses (this is where it might fail)
      try {
        const feedPubkey = new PublicKey(feed.address);
        const pullFeed = new PullFeed(connection, feedPubkey);
        
        const updateResult = await pullFeed.fetchUpdateIx(crossbarClient, 'solana', 'mainnet');
        console.log(`✅ ${feed.name}: Oracle update check successful`);
        console.log(`   - Instructions: ${updateResult[0]?.length || 0}`);
        console.log(`   - Oracle responses: ${updateResult[1]?.length || 0}`);
        console.log(`   - Num success: ${updateResult[2] || 0}`);
        workingFeeds++;
      } catch (updateError) {
        console.log(`❌ ${feed.name}: Oracle update failed - ${updateError.message}`);
        if (updateError.response?.data) {
          console.log(`   Server response: ${updateError.response.data}`);
        }
        failedFeeds++;
      }
      
    } catch (error) {
      console.log(`❌ ${feed.name}: General error - ${error.message}`);
      failedFeeds++;
    }
  }
  
  console.log('\n============================================================');
  console.log('🎯 ORACLE AVAILABILITY SUMMARY:');
  console.log(`✅ Working feeds: ${workingFeeds}`);
  console.log(`❌ Failed feeds: ${failedFeeds}`);
  console.log(`📊 Success rate: ${((workingFeeds / testFeeds.length) * 100).toFixed(1)}%`);
  
  if (failedFeeds > workingFeeds) {
    console.log('\n🚨 CRITICAL: More feeds are failing than working!');
    console.log('This indicates a systemic oracle availability issue.');
    console.log('Recommendation: Consider switching to Pyth oracles or implementing fallback mechanisms.');
  }
}

testOracleAvailability().catch(console.error); 