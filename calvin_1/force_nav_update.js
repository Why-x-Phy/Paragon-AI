#!/usr/bin/env node

/**
 * Force NAV Update Script
 * 
 * This script forces an immediate NAV update regardless of staleness.
 * Used after trades to ensure fresh NAV before collecting performance fees.
 */

const { NAVRefreshService } = require('./nav_refresh_service.js');
const { Keypair } = require('@solana/web3.js');
const fs = require('fs');

async function main() {
    try {
        // Load configuration
        const keypairPath = process.env.CALVIN_KEYPAIR_PATH || '/home/ubuntu/CalvinAI-2/onchain/calvin-ai-authority.json';
        const rpcUrl = process.env.SOLANA_RPC_URL || 'https://api.mainnet-beta.solana.com';
        
        // Load keypair
        const keypairData = JSON.parse(fs.readFileSync(keypairPath, 'utf8'));
        const keypair = Keypair.fromSecretKey(new Uint8Array(keypairData));
        
        // Create service with high staleness threshold to force update
        const service = new NAVRefreshService(
            rpcUrl,
            keypair,
            5,     // refresh interval (not used here)
            999    // staleness threshold set to 999 minutes to force update
        );
        
        console.log('🔄 Forcing NAV update...');
        
        // Directly call refreshNAV to force update
        await service.refreshNAV();
        
        console.log('✅ NAV update complete');
        process.exit(0);
        
    } catch (error) {
        console.error('❌ Error:', error.message);
        process.exit(1);
    }
}

// Run if called directly
if (require.main === module) {
    main();
} 