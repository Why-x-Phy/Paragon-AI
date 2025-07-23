#!/usr/bin/env node

/**
 * NAV Refresh Service for Calvin AI Vault
 * 
 * This service automatically refreshes the vault's NAV at regular intervals
 * to ensure accurate pricing for deposits/withdrawals/trades.
 * 
 * Uses the same JavaScript/Pyth SDK pattern as the frontend for reliability.
 */

const { Connection, Keypair, PublicKey, ComputeBudgetProgram } = require('@solana/web3.js');
const { Program, AnchorProvider, Wallet } = require('@coral-xyz/anchor');
const { HermesClient } = require('@pythnetwork/hermes-client');
const { PythSolanaReceiver } = require('@pythnetwork/pyth-solana-receiver');
const { getAssociatedTokenAddress } = require('@solana/spl-token');
const bs58 = require('bs58');
const fs = require('fs');
const path = require('path');

// Default Configuration
const DEFAULT_CONFIG = {
    RPC_URL: process.env.SOLANA_RPC_URL || 'https://api.mainnet-beta.solana.com',
    KEYPAIR_PATH: process.env.CALVIN_KEYPAIR_PATH || '/home/ubuntu/CalvinAI-2/onchain/calvin-ai-authority.json',
    REFRESH_INTERVAL_MINUTES: 5,
    STALENESS_THRESHOLD_MINUTES: 4
};

// Token to Pyth feed ID mapping (same as Python/frontend)
const TOKEN_ORACLE_HEX_MAPPING = {
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
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE": "0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c", // ORCA
};

// Constants
const USDC_MINT = new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");
const TOKEN_PROGRAM_ID = new PublicKey("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");

class NAVRefreshService {
    constructor(rpcUrl, authorityKeypair, refreshIntervalMinutes = 5, stalenessThresholdMinutes = 4) {
        this.connection = new Connection(rpcUrl, 'confirmed');
        this.authorityKeypair = authorityKeypair;
        this.refreshIntervalMinutes = refreshIntervalMinutes;
        this.stalenessThresholdMinutes = stalenessThresholdMinutes;
        this.running = false;
        
        // Initialize Anchor provider and program
        const wallet = new Wallet(authorityKeypair);
        this.provider = new AnchorProvider(this.connection, wallet, {
            commitment: 'confirmed',
            skipPreflight: false,
        });
        
        // Load IDL and initialize program
        const idlPath = path.join(__dirname, '..', 'onchain', 'target', 'idl', 'vault.json');
        const idl = JSON.parse(fs.readFileSync(idlPath, 'utf8'));
        this.program = new Program(idl, this.provider);
        
        // Initialize Pyth
        this.hermesClient = new HermesClient('https://hermes.pyth.network');
        this.pythReceiver = new PythSolanaReceiver({
            connection: this.connection,
            wallet: wallet,
        });
    }
    
    async getVaultPDA() {
        const [vaultPDA] = PublicKey.findProgramAddressSync(
            [Buffer.from("vault")],
            this.program.programId
        );
        return vaultPDA;
    }
    
    async getVaultAuthorityPDA() {
        const [vaultAuthorityPDA] = PublicKey.findProgramAddressSync(
            [Buffer.from("vault_authority")],
            this.program.programId
        );
        return vaultAuthorityPDA;
    }
    
    async checkNAVStaleness() {
        try {
            const vaultPDA = await this.getVaultPDA();
            const vault = await this.program.account.vault.fetch(vaultPDA);
            
            const currentTime = Math.floor(Date.now() / 1000);
            const navAge = currentTime - vault.navLastUpdated.toNumber();
            const isStale = navAge > (this.stalenessThresholdMinutes * 60);
            
            console.log(`📊 NAV age: ${Math.floor(navAge / 60)} minutes (stale: ${isStale})`);
            
            return {
                isStale,
                navAge,
                currentNAV: vault.cachedNav.toNumber(),
                lastUpdated: vault.navLastUpdated.toNumber()
            };
        } catch (error) {
            console.error('❌ Error checking NAV staleness:', error);
            throw error;
        }
    }
    
    async getVaultTokenHoldings(vaultAuthorityPDA) {
        const tokenAccounts = await this.connection.getParsedTokenAccountsByOwner(
            vaultAuthorityPDA,
            { programId: TOKEN_PROGRAM_ID }
        );
        
        const holdings = [];
        const priceFeeds = [];
        
        for (const account of tokenAccounts.value) {
            const tokenData = account.account.data.parsed.info;
            const balance = parseFloat(tokenData.tokenAmount.uiAmount);
            
            if (balance > 0) {
                const mint = new PublicKey(tokenData.mint);
                const mintStr = mint.toString();
                
                // Skip USDC - no oracle needed
                if (mintStr === USDC_MINT.toString()) {
                    continue;
                }
                
                // Only include tokens with known price feeds
                if (TOKEN_ORACLE_HEX_MAPPING[mintStr]) {
                    holdings.push({
                        mint,
                        tokenAccount: account.pubkey,
                        balance,
                        feedId: TOKEN_ORACLE_HEX_MAPPING[mintStr]
                    });
                    priceFeeds.push(TOKEN_ORACLE_HEX_MAPPING[mintStr]);
                }
            }
        }
        
        return { holdings, priceFeeds };
    }
    
    async refreshNAV() {
        try {
            console.log('🔄 Refreshing vault NAV...');
            
            const vaultPDA = await this.getVaultPDA();
            const vaultAuthorityPDA = await this.getVaultAuthorityPDA();
            const vaultUsdcAccount = await getAssociatedTokenAddress(USDC_MINT, vaultAuthorityPDA, true);
            
            // Get token holdings and price feeds
            const { holdings, priceFeeds } = await this.getVaultTokenHoldings(vaultAuthorityPDA);
            
            console.log(`📊 Found ${holdings.length} non-USDC tokens with balances`);
            
            if (priceFeeds.length === 0) {
                // No non-USDC holdings, just call calculate_nav without oracle accounts
                const tx = await this.program.methods
                    .calculateNav()
                    .accounts({
                        authority: this.authorityKeypair.publicKey,
                        vault: vaultPDA,
                        vaultUsdcToken: vaultUsdcAccount,
                    })
                    .rpc();
                
                console.log('✅ NAV refreshed (USDC only):', tx);
                return tx;
            }
            
            // CRITICAL: Limit oracle accounts to prevent transaction size issues
            // Solana has limits on transaction size and compute units
            // We'll process only the top holdings by value
            const MAX_ORACLE_ACCOUNTS = 8; // Max 5 tokens at a time to stay within limits
            
            if (holdings.length > MAX_ORACLE_ACCOUNTS) {
                console.log(`⚠️ Too many tokens (${holdings.length}). Processing only top ${MAX_ORACLE_ACCOUNTS} holdings.`);
                
                // Sort holdings by balance (descending) to prioritize largest positions
                holdings.sort((a, b) => {
                    // Just compare the balance values directly
                    // No need for BigInt conversion since we're just sorting
                    return b.balance - a.balance;
                });
                
                // Keep only top holdings
                holdings.splice(MAX_ORACLE_ACCOUNTS);
                
                // Update priceFeeds to match
                const topFeedIds = holdings.map(h => h.feedId);
                priceFeeds.splice(0, priceFeeds.length, ...topFeedIds);
                
                console.log(`📊 Processing top ${holdings.length} holdings:`);
                holdings.forEach((h, i) => {
                    console.log(`  ${i + 1}. Balance: ${h.balance.toFixed(2)}`);
                });
            }
            
            // Create a fresh PythSolanaReceiver instance for each update
            // This prevents caching issues between runs
            const wallet = new Wallet(this.authorityKeypair);
            const anchorWallet = {
                publicKey: wallet.publicKey,
                signTransaction: async (tx) => await wallet.signTransaction(tx),
                signAllTransactions: async (txs) => await wallet.signAllTransactions(txs),
            };
            
            const freshPythReceiver = new PythSolanaReceiver({
                connection: this.connection,
                wallet: anchorWallet,
            });
            
            // Small delay to avoid race conditions with Pyth oracle
            await new Promise(resolve => setTimeout(resolve, 500));
            
            // Fetch price updates from Hermes
            console.log(`🔍 Fetching ${priceFeeds.length} price updates from Pyth...`);
            const priceUpdateResponse = await this.hermesClient.getLatestPriceUpdates(
                priceFeeds,
                { encoding: "base64" }
            );
            const priceUpdateData = priceUpdateResponse.binary.data;
            
            console.log(`📦 Received ${priceUpdateData.length} price updates`);
            
            // Create transaction builder with fresh instance
            const transactionBuilder = freshPythReceiver.newTransactionBuilder({
                closeUpdateAccounts: true, // Close after NAV calculation
            });
            
            // Add price updates
            await transactionBuilder.addPostPartiallyVerifiedPriceUpdates(priceUpdateData);
            
            // Add NAV calculation instruction
            await transactionBuilder.addPriceConsumerInstructions(
                async (getPriceUpdateAccount) => {
                    // Build oracle remaining accounts
                    const remainingAccounts = [];
                    
                    for (const holding of holdings) {
                        const priceUpdateAccount = getPriceUpdateAccount(holding.feedId);
                        
                        // Add oracle group: [token_account, price_oracle, mint]
                        remainingAccounts.push(
                            { pubkey: holding.tokenAccount, isWritable: false, isSigner: false },
                            { pubkey: priceUpdateAccount, isWritable: false, isSigner: false },
                            { pubkey: holding.mint, isWritable: false, isSigner: false }
                        );
                    }
                    
                    // Build calculate NAV instruction
                    const calculateNavIx = await this.program.methods
                        .calculateNav()
                        .accounts({
                            authority: this.authorityKeypair.publicKey,
                            vault: vaultPDA,
                            vaultUsdcToken: vaultUsdcAccount,
                        })
                        .remainingAccounts(remainingAccounts)
                        .instruction();
                    
                    return [{ instruction: calculateNavIx, signers: [] }];
                }
            );
            
            // Build and send transactions with increased compute units
            const versionedTransactions = await transactionBuilder.buildVersionedTransactions({
                computeUnitPriceMicroLamports: 600000, // Increased priority fee
                computeUnitLimit: 1400000, // Max compute units
            });
            
            // Send all transactions
            // Skip preflight to avoid simulation errors with Pyth oracle accounts
            const signatures = await freshPythReceiver.provider.sendAll(
                versionedTransactions,
                { skipPreflight: true }
            );
            
            console.log('✅ NAV refreshed successfully!');
            for (let i = 0; i < signatures.length; i++) {
                console.log(`   Transaction ${i + 1}: ${signatures[i]}`);
            }
            
            return signatures[signatures.length - 1]; // Return last signature (NAV calculation)
            
        } catch (error) {
            console.error('❌ Error refreshing NAV:', error);
            throw error;
        }
    }
    
    async runOnce() {
        try {
            const staleness = await this.checkNAVStaleness();
            
            if (staleness.isStale) {
                console.log('🚨 NAV is stale, refreshing...');
                
                // Try up to 3 times with exponential backoff
                let lastError = null;
                for (let attempt = 1; attempt <= 3; attempt++) {
                    try {
                        await this.refreshNAV();
                        
                        // Wait for confirmation before checking
                        console.log('⏳ Waiting for confirmation...');
                        await new Promise(resolve => setTimeout(resolve, 2000));
                        
                        // Verify update
                        const newStaleness = await this.checkNAVStaleness();
                        console.log(`✅ NAV updated. New NAV: $${(newStaleness.currentNAV / 1e6).toLocaleString()}`);
                        return; // Success, exit
                    } catch (error) {
                        lastError = error;
                        console.error(`❌ Attempt ${attempt}/3 failed:`, error.message);
                        
                        if (attempt < 3) {
                            const delay = attempt * 5000; // 5s, 10s
                            console.log(`⏳ Waiting ${delay/1000}s before retry...`);
                            await new Promise(resolve => setTimeout(resolve, delay));
                        }
                    }
                }
                
                console.error('❌ All attempts failed. Will try again next cycle.');
                console.error('Last error:', lastError);
                
            } else {
                console.log(`✅ NAV is fresh (${Math.floor(staleness.navAge / 60)} minutes old)`);
            }
        } catch (error) {
            console.error('❌ Error in runOnce:', error);
            // Don't throw - allow service to continue
        }
    }
    
    async start() {
        console.log(`🚀 Starting NAV refresh service...`);
        console.log(`   Authority: ${this.authorityKeypair.publicKey.toString()}`);
        console.log(`   Refresh interval: ${this.refreshIntervalMinutes} minutes`);
        console.log(`   Staleness threshold: ${this.stalenessThresholdMinutes} minutes`);
        
        this.running = true;
        
        // Run immediately
        await this.runOnce();
        
        // Set up interval
        this.intervalId = setInterval(async () => {
            if (this.running) {
                await this.runOnce();
            }
        }, 60 * 1000); // Check every minute
        
        // Handle graceful shutdown
        process.on('SIGINT', () => this.stop());
        process.on('SIGTERM', () => this.stop());
    }
    
    stop() {
        console.log('\n🛑 Stopping NAV refresh service...');
        this.running = false;
        if (this.intervalId) {
            clearInterval(this.intervalId);
        }
        process.exit(0);
    }
}

// Main function
async function main() {
    try {
        // Parse command line arguments with defaults
        const args = process.argv.slice(2);
        
        // Use defaults if no arguments provided
        const rpcUrl = args[0] || DEFAULT_CONFIG.RPC_URL;
        const keypairPath = args[1] || DEFAULT_CONFIG.KEYPAIR_PATH;
        const refreshInterval = args[2] ? parseInt(args[2]) : DEFAULT_CONFIG.REFRESH_INTERVAL_MINUTES;
        const stalenessThreshold = args[3] ? parseInt(args[3]) : DEFAULT_CONFIG.STALENESS_THRESHOLD_MINUTES;
        
        console.log('🔧 Configuration:');
        console.log(`   RPC URL: ${rpcUrl}`);
        console.log(`   Keypair: ${keypairPath}`);
        console.log(`   Refresh interval: ${refreshInterval} minutes`);
        console.log(`   Staleness threshold: ${stalenessThreshold} minutes`);
        console.log('');
        
        // Check if keypair exists
        if (!fs.existsSync(keypairPath)) {
            console.error(`❌ Keypair file not found: ${keypairPath}`);
            console.error('');
            console.error('Please ensure Calvin authority keypair exists at the specified path.');
            console.error('You can override defaults with command line arguments:');
            console.error('  node nav_refresh_service.js <rpc_url> <keypair_path> [refresh_minutes] [staleness_minutes]');
            process.exit(1);
        }
        
        // Load authority keypair
        const keypairData = JSON.parse(fs.readFileSync(keypairPath, 'utf8'));
        const authorityKeypair = Keypair.fromSecretKey(new Uint8Array(keypairData));
        
        // Create and start service
        const service = new NAVRefreshService(
            rpcUrl,
            authorityKeypair,
            refreshInterval,
            stalenessThreshold
        );
        
        await service.start();
        
    } catch (error) {
        console.error('❌ Failed to start service:', error);
        process.exit(1);
    }
}

// Run if called directly
if (require.main === module) {
    main();
}

module.exports = { NAVRefreshService }; 