#!/usr/bin/env node

import { Connection, PublicKey } from '@solana/web3.js';
import { CrossbarClient } from '@switchboard-xyz/common';
import { PullFeed, ON_DEMAND_MAINNET_PID } from '@switchboard-xyz/on-demand';
import { AnchorProvider, Program } from '@coral-xyz/anchor';

// Same oracle feeds as vault client
const ORACLE_FEEDS = {
  "USDC": "aHTvxuDvCRRnmJDDR1JkfLa4SpCNsgC4vDeLMEcN3zY",
  "SOL": "E8TLLh5jkYDvSXfAES7qe3s8Cfjj4hyvjksuvUHe8NEw",
  "BONK": "7GCiue6chgGuk6BvaurQNWD1Ervho8zEdcNWt5ZCYQhu",
  "JUP": "2F9M59yYc28WMrAymNWceaBEk8ZmDAjUAKULp8seAJF3",
};

async function checkOracleFunding() {
  console.log('🔍 Checking Switchboard Oracle Feed Funding Status');
  console.log('=' .repeat(60));
  
  const connection = new Connection("https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d", "confirmed");
  const crossbar = new CrossbarClient('https://crossbar.switchboard.xyz');
  
  // Mock wallet for program initialization
  const mockWallet = {
    publicKey: new PublicKey("11111111111111111111111111111111"),
    signAllTransactions: async (txs) => txs,
    signTransaction: async (tx) => tx,
  };
  
  const provider = new AnchorProvider(connection, mockWallet, AnchorProvider.defaultOptions());
  
  try {
    const switchboardProgram = await Program.at(ON_DEMAND_MAINNET_PID, provider);
    
    for (const [symbol, feedAddress] of Object.entries(ORACLE_FEEDS)) {
      console.log(`\n📊 Checking ${symbol} feed: ${feedAddress}`);
      
      try {
        // 1. Check if feed account exists
        const feedPubkey = new PublicKey(feedAddress);
        const accountInfo = await connection.getAccountInfo(feedPubkey);
        
        if (!accountInfo) {
          console.log(`  ❌ Feed account not found`);
          continue;
        }
        
        console.log(`  ✅ Feed account exists (${accountInfo.data.length} bytes)`);
        
        // 2. Try to create a PullFeed instance
        const pullFeed = new PullFeed(switchboardProgram, feedPubkey);
        console.log(`  ✅ PullFeed instance created`);
        
        // 3. Check if we can get simulation data
        try {
          const simResults = await crossbar.simulateSolanaFeeds("mainnet", [feedAddress]);
          if (simResults && simResults[0] && simResults[0].results && simResults[0].results.length > 0) {
            const price = simResults[0].results[0];
            console.log(`  ✅ Simulation works: $${price}`);
          } else {
            console.log(`  ⚠️  Simulation returned no results`);
          }
        } catch (simError) {
          console.log(`  ⚠️  Simulation failed: ${simError.message}`);
        }
        
        // 4. Try to get update instruction (this is what's failing)
        try {
          console.log(`  🔄 Testing fetchUpdateIx...`);
          
          const updateData = await pullFeed.fetchUpdateIx({
            crossbarClient: crossbar,
            chain: 'solana',
            network: 'mainnet',
          });
          
          if (updateData && updateData.pullIx) {
            console.log(`  ✅ fetchUpdateIx SUCCESS - update instruction created`);
            console.log(`     - Number of successful oracles: ${updateData.numSuccess || 'unknown'}`);
            console.log(`     - Lookup tables: ${updateData.luts?.length || 0}`);
          } else {
            console.log(`  ❌ fetchUpdateIx FAILED - no update instruction`);
            console.log(`     - This means the feed likely needs funding or has no active oracles`);
          }
          
        } catch (fetchError) {
          console.log(`  ❌ fetchUpdateIx ERROR: ${fetchError.message}`);
          
          // Check for specific error messages
          if (fetchError.message.includes('minSampleSize')) {
            console.log(`     🔍 Issue: Feed configuration problem (minSampleSize)`);
          } else if (fetchError.message.includes('lease')) {
            console.log(`     🔍 Issue: Lease contract not funded`);
          } else if (fetchError.message.includes('oracle')) {
            console.log(`     🔍 Issue: Oracle network problem`);
          }
        }
        
      } catch (error) {
        console.log(`  ❌ Error checking ${symbol}: ${error.message}`);
      }
    }
    
    console.log('\n' + '=' .repeat(60));
    console.log('🎯 DIAGNOSIS:');
    console.log('If fetchUpdateIx is failing for all feeds, this means:');
    console.log('  1. Feeds need funding in their lease contracts, OR');
    console.log('  2. Oracle network is not active for these feeds, OR');
    console.log('  3. Configuration issue with the feeds');
    console.log('\n💡 SOLUTION:');
    console.log('For now, you may need to:');
    console.log('  1. Use a different set of Switchboard feeds that are properly funded');
    console.log('  2. Fund the lease contracts yourself (expensive)');
    console.log('  3. Fall back to Pyth oracles for price updates');
    console.log('  4. Contact Switchboard team about feed status');
    
  } catch (error) {
    console.error('❌ Failed to check oracle funding:', error);
  }
}

checkOracleFunding().catch(console.error); 