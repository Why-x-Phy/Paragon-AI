#!/usr/bin/env node

/**
 * Pyth Oracle Account Generator for Calvin AI Vault
 * 
 * This script creates PriceUpdateV2 accounts needed for vault trade instructions.
 * It's called from Python and returns the oracle account addresses.
 * 
 * Usage: node pyth_oracle_generator.js <price_feed_ids_json> <rpc_url> <payer_private_key_base58>
 */

const { Connection, Keypair, PublicKey } = require('@solana/web3.js');
const { HermesClient } = require('@pythnetwork/hermes-client');
const { PythSolanaReceiver } = require('@pythnetwork/pyth-solana-receiver');
const bs58 = require('bs58');

// Token to Pyth feed ID mapping (same as in Python)
const TOKEN_ORACLE_HEX_MAPPING = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a", // USDC
    "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN": "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a", // TRUMP
    "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof": "0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d", // RENDER
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996", // JUP
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419", // BONK
    "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump": "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608", // FARTCOIN
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a", // RAY
    "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2", // JTO
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3npgxbkkTs8LG": "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d0d719579ff", // PYTH
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc", // WIF
    "3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y": "0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b", // VIRTUAL
    "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv": "0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61", // PENGU
    "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ": "0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389", // W (WORMHOLE)
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": "0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce", // POPCAT
    "Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7": "0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a", // ATH
    "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5": "0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d", // MEW
    "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey": "0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a", // MNDE
    "J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr": "0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a", // SPX (SPX6900)
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE": "0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c", // ORCA
};

async function createPriceUpdateAccounts(tokenMints, rpcUrl, payerPrivateKey) {
    try {
        // Initialize connection and payer
        const connection = new Connection(rpcUrl, 'confirmed');
        
        // Handle both base58 and JSON array formats for private key
        let payer;
        if (payerPrivateKey.startsWith('[') && payerPrivateKey.endsWith(']')) {
            // JSON array format like [1, 2, 3, ...]
            const keyArray = JSON.parse(payerPrivateKey);
            console.log(`🔑 Parsed key array with ${keyArray.length} bytes`);
            
            if (keyArray.length === 32) {
                // 32-byte private key seed
                const seed = new Uint8Array(keyArray);
                payer = Keypair.fromSeed(seed);
            } else if (keyArray.length === 64) {
                // Full 64-byte keypair
                const secretKey = new Uint8Array(keyArray);
                payer = Keypair.fromSecretKey(secretKey);
            } else {
                throw new Error(`Invalid key array length: ${keyArray.length}. Expected 32 bytes (seed) or 64 bytes (full keypair).`);
            }
        } else {
            // Base58 format - assume it's a full secret key
            const secretKey = bs58.decode(payerPrivateKey);
            payer = Keypair.fromSecretKey(secretKey);
        }
        
        // Initialize Hermes client to fetch price updates
        const hermesClient = new HermesClient("https://hermes.pyth.network/", {});
        
        // Initialize Pyth receiver to post price updates
        // Create a proper wallet interface
        const wallet = {
            publicKey: payer.publicKey,
            signTransaction: async (tx) => {
                tx.sign([payer]);
                return tx;
            },
            signAllTransactions: async (txs) => {
                txs.forEach(tx => tx.sign([payer]));
                return txs;
            }
        };
        
        const pythReceiver = new PythSolanaReceiver({ connection, wallet });
        
        // Get price feed IDs for the tokens
        const priceFeedIds = [];
        for (const mint of tokenMints) {
            const feedId = TOKEN_ORACLE_HEX_MAPPING[mint];
            if (feedId) {
                priceFeedIds.push(feedId);
            } else {
                console.error(`No Pyth feed ID found for token: ${mint}`);
            }
        }
        
        if (priceFeedIds.length === 0) {
            throw new Error('No valid price feed IDs found');
        }
        
        console.log(`Creating oracle accounts for ${priceFeedIds.length} price feeds...`);
        
        // Step 1: Fetch price updates from Hermes
        const priceUpdateResponse = await hermesClient.getLatestPriceUpdates(
            priceFeedIds,
            { encoding: "base64" }
        );
        const priceUpdateData = priceUpdateResponse.binary.data;
        
        console.log(`✅ Fetched ${priceUpdateData.length} price updates from Hermes`);
        
        // Step 2: Create transaction builder to post price updates
        const transactionBuilder = pythReceiver.newTransactionBuilder({
            closeUpdateAccounts: false, // Keep accounts open for vault to use
        });
        
        // Add price update posting instructions
        await transactionBuilder.addPostPriceUpdates(priceUpdateData);
        
        // Step 3: Build and send transactions
        const transactions = await transactionBuilder.buildVersionedTransactions({
            computeUnitPriceMicroLamports: 50000,
        });
        
        console.log(`✅ Built ${transactions.length} transactions for price updates`);
        
        // Send transactions using the Pyth receiver's provider
        console.log(`📤 Sending ${transactions.length} transactions...`);
        
        // Use the Pyth receiver's provider to send transactions
        const signatures = await pythReceiver.provider.sendAll(transactions, { skipPreflight: true });
        
        console.log(`✅ All transactions sent successfully!`);
        for (let i = 0; i < signatures.length; i++) {
            console.log(`✅ Transaction ${i + 1} confirmed: ${signatures[i]}`);
        }
        
        // Step 4: Get the created price update accounts
        // Create a new transaction builder to access the getPriceUpdateAccount function
        const queryBuilder = pythReceiver.newTransactionBuilder({
            closeUpdateAccounts: false,
        });
        
        // Add the same price updates to get access to the account addresses
        await queryBuilder.addPostPriceUpdates(priceUpdateData);
        
        const result = {};
        
        // Use the query builder's callback to get the price update accounts
        await queryBuilder.addPriceConsumerInstructions(
            async (getPriceUpdateAccount) => {
                // This callback gives us access to the getPriceUpdateAccount function
                for (let i = 0; i < tokenMints.length && i < priceFeedIds.length; i++) {
                    const account = getPriceUpdateAccount(priceFeedIds[i]);
                    result[tokenMints[i]] = account.toString();
                }
                return []; // No additional instructions needed
            }
        );
        
        console.log('✅ Successfully created oracle accounts:');
        console.log(JSON.stringify(result, null, 2));
        
        return result;
        
    } catch (error) {
        console.error('❌ Error creating oracle accounts:', error);
        throw error;
    }
}

async function main() {
    // Parse command line arguments
    const args = process.argv.slice(2);
    
    if (args.length !== 3) {
        console.error('Usage: node pyth_oracle_generator.js <token_mints_json> <rpc_url> <payer_private_key_base58>');
        console.error('Example: node pyth_oracle_generator.js \'["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"]\' https://api.mainnet-beta.solana.com YOUR_PRIVATE_KEY_BASE58');
        process.exit(1);
    }
    
    const [tokenMintsJson, rpcUrl, payerPrivateKey] = args;
    
    try {
        // Parse token mints
        const tokenMints = JSON.parse(tokenMintsJson);
        
        if (!Array.isArray(tokenMints)) {
            throw new Error('Token mints must be an array');
        }
        
        // Create oracle accounts
        const oracleAccounts = await createPriceUpdateAccounts(tokenMints, rpcUrl, payerPrivateKey);
        
        // Output result as JSON for Python to parse
        console.log('ORACLE_ACCOUNTS_RESULT:');
        console.log(JSON.stringify(oracleAccounts));
        
    } catch (error) {
        console.error('❌ Script failed:', error.message);
        process.exit(1);
    }
}

// Run if called directly
if (require.main === module) {
    main().catch(error => {
        console.error('❌ Unhandled error:', error);
        process.exit(1);
    });
}

module.exports = { createPriceUpdateAccounts }; 