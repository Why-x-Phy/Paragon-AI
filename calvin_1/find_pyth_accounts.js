const { Connection, PublicKey } = require('@solana/web3.js');
const { PythHttpClient, getPythProgramKeyForCluster } = require('@pythnetwork/client');

async function findPythAccounts() {
    // Connect to Pythnet (Pyth's own blockchain)
    const connection = new Connection('https://pythnet.rpcpool.com/');
    const pythClient = new PythHttpClient(connection, getPythProgramKeyForCluster('pythnet'));
    
    // Price Feed IDs we want to look up
    const PRICE_FEED_IDS = {
        "TRUMP": "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a",
        "FARTCOIN": "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608",
        "VIRTUAL": "0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b",
        "PENGU": "0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61",
        "POPCAT": "0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce",
        "ATH": "0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a",
        "MEW": "0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d",
        "SPX": "0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a",
    };
    
    try {
        // Get all price data accounts
        const data = await pythClient.getData();
        
        console.log("=== PYTH ACCOUNT LOOKUP ===\n");
        
        for (const [symbol, priceId] of Object.entries(PRICE_FEED_IDS)) {
            console.log(`Looking for ${symbol} (${priceId})...`);
            
            // Find the price account by Price Feed ID
            const priceData = data.productPrice.get(priceId);
            if (priceData) {
                console.log(`✅ Found price feed for ${symbol}`);
                console.log(`   Price: $${priceData.price} ±$${priceData.confidence}`);
                console.log(`   Product Account: ${priceData.productAccountKey?.toBase58() || 'N/A'}`);
                console.log(`   Price Account: ${priceData.priceAccountKey?.toBase58() || 'N/A'}`);
            } else {
                console.log(`❌ Not found on Solana mainnet`);
            }
            console.log("");
        }
        
    } catch (error) {
        console.error("Error:", error.message);
    }
}

// Remove this function since it's imported from @pythnetwork/client

findPythAccounts().catch(console.error); 