const fetch = require('cross-fetch');

// Configuration - Using the new Jupiter API endpoints
const JUPITER_API_BASE = 'https://lite-api.jup.ag/swap/v1';

async function getQuote(inputMint, outputMint, amount, slippageBps = 100) {
    try {
        const url = `${JUPITER_API_BASE}/quote?` + new URLSearchParams({
            inputMint,
            outputMint,
            amount: amount.toString(),
            slippageBps: slippageBps.toString(),
            onlyDirectRoutes: 'true',  // ✅ OPTIMIZATION: Force direct routes for fewer accounts
            // ✅ CRITICAL: Don't use asLegacyTransaction to get proper versioned transaction format
            asLegacyTransaction: 'false'
        });

        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`Quote API error: ${response.status} ${response.statusText}`);
        }

        const quoteData = await response.json();
        
        if (!quoteData.inAmount || !quoteData.outAmount) {
            throw new Error('Invalid quote response: missing required fields');
        }

        return quoteData;
    } catch (error) {
        throw new Error(`Failed to get quote: ${error.message}`);
    }
}

async function getSwapInstruction(quoteResponse, userPublicKey) {
    try {
        // ✅ CRITICAL FIX: Use the /swap-instructions endpoint to get proper instruction format
        // This generates the correct SharedAccountsRoute format automatically
        const response = await fetch(`${JUPITER_API_BASE}/swap-instructions`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                quoteResponse,
                userPublicKey,
                wrapAndUnwrapSol: true,
                // ✅ CRITICAL: Don't request legacy transaction format
                // This ensures we get the newer SharedAccountsRoute format
                asLegacyTransaction: false,
                computeUnitPriceMicroLamports: 'auto'
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Swap API error: ${response.status} ${response.statusText} - ${errorText}`);
        }

        const instructionsData = await response.json();
        
        if (instructionsData.error) {
            throw new Error(`Swap instruction error: ${instructionsData.error}`);
        }

        // Extract the main swap instruction from the response
        const swapInstruction = instructionsData.swapInstruction;
        
        if (!swapInstruction) {
            throw new Error('No swap instruction in response');
        }

        // ✅ The Jupiter API automatically returns the correct format
        // Return in the format expected by our Python client
        return {
            programId: swapInstruction.programId,
            data: swapInstruction.data,
            accounts: swapInstruction.accounts,
            routeInfo: {
                inAmount: quoteResponse.inAmount,
                outAmount: quoteResponse.outAmount,
                priceImpactPct: quoteResponse.priceImpactPct || '0',
                marketInfos: quoteResponse.marketInfos || []
            },
            instructionType: 'SharedAccountsRoute_API',  // Modern API format
            // Include additional instruction data if available
            setupInstructions: instructionsData.setupInstructions || [],
            cleanupInstruction: instructionsData.cleanupInstruction,
            computeBudgetInstructions: instructionsData.computeBudgetInstructions || [],
            addressLookupTableAddresses: instructionsData.addressLookupTableAddresses || []
        };

    } catch (error) {
        throw new Error(`Failed to get swap instruction: ${error.message}`);
    }
}

// CLI interface
async function main() {
    const args = process.argv.slice(2);
    
    // Check for help flag
    if (args.includes('--help') || args.includes('-h')) {
        console.log('Usage: node jupiter_instruction_generator.js <inputMint> <outputMint> <amount> <userPublicKey> [slippageBps] [--quote-only]');
        console.log('');
        console.log('Arguments:');
        console.log('  inputMint     - Input token mint address (e.g., USDC)');
        console.log('  outputMint    - Output token mint address (e.g., target token)');
        console.log('  amount        - Amount in smallest token units');
        console.log('  userPublicKey - User/vault authority public key');
        console.log('  slippageBps   - Slippage tolerance in basis points (default: 100)');
        console.log('');
        console.log('Flags:');
        console.log('  --quote-only  - Only return quote data, not full instruction');
        console.log('');
        console.log('Example: node jupiter_instruction_generator.js EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump 10000000 6tMyF1Q5GScmXCJGSgpsKQtMPSPgkREwWuWWNspcmV8U 100');
        process.exit(0);
    }
    
    // Extract flags and arguments
    const quoteOnly = args.includes('--quote-only');
    const nonFlagArgs = args.filter(arg => !arg.startsWith('--'));
    
    if (nonFlagArgs.length < 4) {
        console.error('Error: Missing required arguments');
        console.error('Usage: node jupiter_instruction_generator.js <inputMint> <outputMint> <amount> <userPublicKey> [slippageBps] [--quote-only]');
        console.error('Use --help for more information');
        process.exit(1);
    }

    const [inputMint, outputMint, amount, userPublicKey, slippageBps = '100'] = nonFlagArgs;

    try {
        // Get quote from Jupiter API
        const quote = await getQuote(inputMint, outputMint, parseInt(amount), parseInt(slippageBps));
        
        if (quoteOnly) {
            // Return only quote data
            console.log(JSON.stringify(quote));
        } else {
            // Get full swap instruction
            const instruction = await getSwapInstruction(quote, userPublicKey);
            console.log(JSON.stringify(instruction));
        }

    } catch (error) {
        console.error(`❌ Error: ${error.message}`);
        process.exit(1);
    }
}

// Export for programmatic use
module.exports = { getQuote, getSwapInstruction };

// Run if called directly
if (require.main === module) {
    main();
} 