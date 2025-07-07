import {
  Connection,
  PublicKey,
} from "@solana/web3.js";
import * as fs from "fs";
import * as path from "path";

// Switchboard feed addresses from oracle_config.rs
const SWITCHBOARD_FEEDS = {
  "TRUMP": "9wcBMATS8bGLQ2UcRuYjsRAD7TPqB1CMhqfueBx78Uj2",
  "WIF": "8GqzQoqqKzJoNaWZtf2udVGV3Fn74W9DQayYu1S1zvkt", 
  "ATH": "21JapEAFu8r8SAAQjB2fURfjiosnTHAFFm4S27qe4vVF",
  "BONK": "7GCiue6chgGuk6BvaurQNWD1Ervho8zEdcNWt5ZCYQhu",
  "FARTCOIN": "EE8Uyquv38j2JmyCiPprCNUxDBTrzpCXqR4hL3RGDUGh",
  "JTO": "E9fHVUZnvT4i8H3jQLb6g2tSpcagunJpjwCGNTYxwKSE",
  "JUP": "2F9M59yYc28WMrAymNWceaBEk8ZmDAjUAKULp8seAJF3",
  "MEW": "7Eev1vbsrgEmiRbVjyyFL8nqRKQt7jNPVtxiS4C6ewns",
  "MNDE": "CwtLbG7w71oCasCMYR8KARZYEVJK5x1GXdoYpqjctp7E",
  "ORCA": "BFWHemmj4ZtvqQVsWrGrFrL2U8tz7Lzq8nhy1KRMVezL",
  "PENGU": "DAG9yMr4FbTVd41Jojw6X589EHiPgR375SP5AdAAW7tH",
  "POPCAT": "5FWVcePyDK5jF6ZqFgmEMyu9qu5qdsswwvMd7GvRmfFW",
  "PYTH": "72ukr6M31f9cCzxvZT4Ba7AGyWSFLQGHjXU6WUzN4xD7",
  "RAY": "AJkAFiXdbMonys8rTXZBrRnuUiLcDFdkyoPuvrVKXhex",
  "RENDER": "B6xHth4K3fj3KK1TASXtHfbAReShYW3EihgwSKvhsugz",
  "SPX": "8m5YKLgnftRTcVXJLk7bV37xc2qrWR9TkXq4TY3FP3pz",
  "VIRTUAL": "34aJFwk2jTKmB2C6zWnT641ABCQv1P2ghrob57i1gFdg",
  "W": "DwjV47HwtHW5YR1CPndw3Fq1QMeYyvYA7jYXhMtcUCte",
  "SOL": "E8TLLh5jkYDvSXfAES7qe3s8Cfjj4hyvjksuvUHe8NEw",
  "USDC": "aHTvxuDvCRRnmJDDR1JkfLa4SpCNsgC4vDeLMEcN3zY",
};

const MAINNET_RPC = "https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d";

async function testSwitchboardFeeds() {
  console.log("🔍 Testing Switchboard Oracle Feeds");
  console.log("=" .repeat(50));
  
  const connection = new Connection(MAINNET_RPC, "confirmed");
  
  // Switchboard Program IDs
  const SWITCHBOARD_ON_DEMAND_ID = "SBondMDrcV3K4kxZR1HNVT7osZxAHVHgYXL5Ze1oMUv"; // On-Demand (newer)
  const SWITCHBOARD_V2_ID = "SW1TCH7qEPTdLsDHRgPuMQjbQxKdH2aBStViMFnt64f";      // Legacy V2
  
  let successCount = 0;
  let totalCount = 0;
  const results: { symbol: string; status: string; details: string }[] = [];
  
  for (const [symbol, address] of Object.entries(SWITCHBOARD_FEEDS)) {
    totalCount++;
    try {
      console.log(`\n📊 Testing ${symbol} feed: ${address}`);
      
      const feedPubkey = new PublicKey(address);
      const accountInfo = await connection.getAccountInfo(feedPubkey);
      
      if (!accountInfo) {
        console.log(`  ❌ Account not found for ${symbol}`);
        results.push({ symbol, status: "❌ NOT_FOUND", details: "Account does not exist" });
        continue;
      }
      
      console.log(`  ✅ Account found`);
      console.log(`  - Owner: ${accountInfo.owner.toString()}`);
      console.log(`  - Data length: ${accountInfo.data.length} bytes`);
      console.log(`  - Lamports: ${accountInfo.lamports}`);
      
      // Check if owner matches expected Switchboard program IDs
      const ownerStr = accountInfo.owner.toString();
      let programType = "";
      let isValidSwitchboard = false;
      
      if (ownerStr === SWITCHBOARD_ON_DEMAND_ID) {
        programType = "On-Demand";
        isValidSwitchboard = true;
      } else if (ownerStr === SWITCHBOARD_V2_ID) {
        programType = "V2 (Legacy)";
        isValidSwitchboard = true;
      }
      
      if (isValidSwitchboard) {
        console.log(`  ✅ Valid Switchboard ${programType} program owner`);
        successCount++;
        
        // Basic data analysis
        const isLikelyValidFeed = accountInfo.data.length > 100 && accountInfo.lamports > 0;
        console.log(`  - Valid feed structure: ${isLikelyValidFeed ? "✅" : "⚠️"}`);
        
        // Try to read some basic structure
        const dataView = new DataView(accountInfo.data.buffer);
        try {
          // Read first few bytes to see if it looks like Switchboard data
          const firstBytes = Array.from(accountInfo.data.slice(0, 8))
            .map(b => b.toString(16).padStart(2, '0'))
            .join(' ');
          console.log(`  - Data header: ${firstBytes}`);
          console.log(`  - Program type: Switchboard ${programType}`);
          
          results.push({ 
            symbol, 
            status: `✅ VALID (${programType})`, 
            details: `${accountInfo.data.length} bytes, ${accountInfo.lamports} lamports` 
          });
        } catch (parseError) {
          console.log(`  ⚠️  Could not parse data structure: ${parseError}`);
          results.push({ 
            symbol, 
            status: "⚠️ UNPARSEABLE", 
            details: `${programType} account exists but data format unclear` 
          });
        }
      } else {
        console.log(`  ❌ Unexpected owner. Expected Switchboard On-Demand or V2`);
        console.log(`  ❌ Expected: ${SWITCHBOARD_ON_DEMAND_ID} (On-Demand)`);
        console.log(`  ❌ Expected: ${SWITCHBOARD_V2_ID} (V2 Legacy)`);
        console.log(`  ❌ Actual:   ${ownerStr}`);
        results.push({ 
          symbol, 
          status: "❌ WRONG_OWNER", 
          details: `Owner: ${ownerStr}` 
        });
      }
      
    } catch (error) {
      console.log(`  ❌ Error testing ${symbol}: ${error}`);
      results.push({ 
        symbol, 
        status: "❌ ERROR", 
        details: error.toString() 
      });
    }
  }
  
  console.log("\n" + "=".repeat(50));
  console.log("📋 SUMMARY REPORT");
  console.log("=" .repeat(50));
  console.log(`✅ Valid Switchboard feeds: ${successCount}/${totalCount}`);
  console.log(`📈 Success rate: ${((successCount / totalCount) * 100).toFixed(1)}%`);
  
  console.log("\n📊 Detailed Results:");
  results.forEach(result => {
    console.log(`  ${result.status} ${result.symbol.padEnd(12)} - ${result.details}`);
  });
  
  console.log("\n🏁 Switchboard feed test completed");
  return { successCount, totalCount, results };
}

// Enhanced test with actual price parsing (requires switchboard SDK)
async function testSwitchboardParsing() {
  console.log("\n🔬 Testing Switchboard Price Parsing");
  console.log("=" .repeat(50));
  
  // Note: This would require the actual switchboard SDK
  // For now, we'll just verify account structure
  
  console.log("⚠️  Price parsing test requires switchboard SDK integration");
  console.log("This test verified account existence and ownership");
  console.log("Next step: Add switchboard-on-demand dependency and implement parsing");
}

async function main() {
  try {
    console.log("🚀 Calvin AI Vault - Switchboard Oracle Test");
    console.log("=" .repeat(60));
    console.log(`📅 Test started at: ${new Date().toISOString()}`);
    console.log(`🌐 RPC Endpoint: ${MAINNET_RPC.split('?')[0]}...`);
    console.log(`📊 Testing ${Object.keys(SWITCHBOARD_FEEDS).length} Switchboard feeds\n`);
    
    const testResult = await testSwitchboardFeeds();
    await testSwitchboardParsing();
    
    console.log("\n" + "=".repeat(60));
    console.log("🎯 FINAL RESULTS");
    console.log("=" .repeat(60));
    
    if (testResult.successCount === testResult.totalCount) {
      console.log("🎉 ALL TESTS PASSED! Your Switchboard feeds are ready for integration.");
      
      // Check which program types were found
      const onDemandCount = testResult.results.filter(r => r.status.includes("On-Demand")).length;
      const v2Count = testResult.results.filter(r => r.status.includes("V2")).length;
      
      if (onDemandCount > 0 && v2Count === 0) {
        console.log("✅ All feeds are Switchboard On-Demand - Perfect!");
        console.log("📦 Next step: Add 'switchboard-on-demand' crate to your Rust program");
      } else if (v2Count > 0 && onDemandCount === 0) {
        console.log("⚠️  All feeds are legacy Switchboard V2");
        console.log("📦 Consider upgrading to On-Demand feeds or use 'switchboard-v2' crate");
      } else if (onDemandCount > 0 && v2Count > 0) {
        console.log(`⚠️  Mixed feed types: ${onDemandCount} On-Demand, ${v2Count} V2 Legacy`);
        console.log("🔧 Consider standardizing on On-Demand feeds for best performance");
      }
    } else if (testResult.successCount > 0) {
      console.log(`⚠️  PARTIAL SUCCESS: ${testResult.successCount}/${testResult.totalCount} feeds are valid`);
      console.log("🔧 Some feeds may need attention before full integration");
    } else {
      console.log("❌ NO VALID FEEDS FOUND! Please check your Switchboard feed addresses");
      console.log("🔍 Verify addresses in oracle_config.rs match actual Switchboard feeds");
    }
    
    console.log("\n📝 Test completed successfully");
    
  } catch (error) {
    console.error("\n❌ Test failed with error:", error);
    console.error("🔧 Please check your RPC connection and feed addresses");
    process.exit(1);
  }
}

main(); 