import * as anchor from "@coral-xyz/anchor";
import { 
  PublicKey, 
  Keypair, 
  SystemProgram,
  Connection,
  ComputeBudgetProgram
} from "@solana/web3.js";
import fs from 'fs';

// Import IDLs
import vaultIdl from '../target/idl/vault.json';

/**
 * 🎯 WHITELIST ALL TRADING TOKENS WITH ORACLES
 * 
 * This script whitelists all 20 trading tokens with their Pyth oracle accounts
 */

// Helper function to convert hex string to Pubkey
function hexToPubkey(hexStr: string): PublicKey {
  const hex = hexStr.replace('0x', '');
  if (hex.length !== 64) {
    throw new Error(`Invalid hex length: ${hex.length}`);
  }
  
  const bytes = new Uint8Array(32);
  for (let i = 0; i < 32; i++) {
    bytes[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  
  return new PublicKey(bytes);
}

async function whitelistAllTokens() {
  console.log("🎯 WHITELISTING ALL TRADING TOKENS WITH ORACLES");
  console.log("⚠️  MAINNET - REAL MONEY!");
  
  // ============================================================================
  // 📋 PROGRAM ADDRESSES
  // ============================================================================
  
  const PROGRAMS = {
    VAULT: new PublicKey("tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z"),
  };
  
  // ============================================================================
  // 🎯 ALL 20 TRADING TOKENS WITH ORACLES
  // ============================================================================
  
  const TRADING_TOKENS_WITH_ORACLES = [
    {
      symbol: "USDC",
      mint: new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
      pythOracle: hexToPubkey("0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a"),
      maxAllocationBps: 10000, // 100% (base currency for deposits)
    },
    {
      symbol: "SOL",
      mint: new PublicKey("So11111111111111111111111111111111111111112"),
      pythOracle: hexToPubkey("0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d"), // SOL/USD
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "TRUMP",
      mint: new PublicKey("6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN"),
      pythOracle: hexToPubkey("0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "RENDER",
      mint: new PublicKey("rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof"),
      pythOracle: hexToPubkey("0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "JUP",
      mint: new PublicKey("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"),
      pythOracle: hexToPubkey("0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "RAY",
      mint: new PublicKey("4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"),
      pythOracle: hexToPubkey("0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "JTO",
      mint: new PublicKey("jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL"),
      pythOracle: hexToPubkey("0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "PYTH",
      mint: new PublicKey("HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3"),
      pythOracle: hexToPubkey("0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d0d719579ff"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "ORCA",
      mint: new PublicKey("orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE"),
      pythOracle: hexToPubkey("0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "MNDE",
      mint: new PublicKey("MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey"),
      pythOracle: hexToPubkey("0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "BONK",
      mint: new PublicKey("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"),
      pythOracle: hexToPubkey("0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "FARTCOIN",
      mint: new PublicKey("9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"),
      pythOracle: hexToPubkey("0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "WIF",
      mint: new PublicKey("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"),
      pythOracle: hexToPubkey("0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "VIRTUAL",
      mint: new PublicKey("BUjZjAS2vbbb65g7Z1Ca9ZRVYoJscURG5L3AkVXHP2ac"),
      pythOracle: hexToPubkey("0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "PENGU",
      mint: new PublicKey("2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv"),
      pythOracle: hexToPubkey("0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "POPCAT",
      mint: new PublicKey("7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"),
      pythOracle: hexToPubkey("0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "ATH",
      mint: new PublicKey("ATHdb8YvGvBVhgJB3PaMU5sCdAUHkhkN42jdYWK4h2xQ"),
      pythOracle: hexToPubkey("0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "MEW",
      mint: new PublicKey("MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5"),
      pythOracle: hexToPubkey("0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "SPX",
      mint: new PublicKey("AUKyeqDfN8p6B93X9gYCnCpdJUfvxU6ZWEmAy2VKqm3w"),
      pythOracle: hexToPubkey("0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a"),
      maxAllocationBps: 2500, // 25%
    },
    {
      symbol: "W",
      mint: new PublicKey("85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ"),
      pythOracle: hexToPubkey("0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389"),
      maxAllocationBps: 2500, // 25%
    },
  ];
  
  console.log(`📊 Whitelisting ${TRADING_TOKENS_WITH_ORACLES.length} tokens with oracles`);
  console.log(`💰 USDC: 100% allocation (base currency)`);
  console.log(`🎯 Others: 25% max allocation each`);
  
  // ============================================================================
  // 🔗 CONNECTION & SETUP
  // ============================================================================
  
  const connection = new Connection(
    "https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d",
    "confirmed"
  );
  
  const deployerKeypair = Keypair.fromSecretKey(
    new Uint8Array(JSON.parse(fs.readFileSync('/home/ubuntu/.config/solana/id.json', 'utf8')))
  );
  
  console.log(`🔑 Emergency Owner: ${deployerKeypair.publicKey.toBase58()}`);
  
  const balance = await connection.getBalance(deployerKeypair.publicKey);
  console.log(`💰 Balance: ${balance / anchor.web3.LAMPORTS_PER_SOL} SOL`);
  
  const provider = new anchor.AnchorProvider(
    connection,
    new anchor.Wallet(deployerKeypair),
    { commitment: "confirmed" }
  );
  anchor.setProvider(provider);
  
  // ============================================================================
  // 🧮 PDA DERIVATIONS
  // ============================================================================
  
  const [vaultPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault")], PROGRAMS.VAULT
  );
  
  console.log(`🏦 Vault: ${vaultPda.toBase58()}`);
  
  // ============================================================================
  // 🎯 WHITELIST ALL TOKENS
  // ============================================================================
  
  const vaultIdlCopy = { ...vaultIdl, address: PROGRAMS.VAULT.toBase58() };
  const vaultProgram = new anchor.Program(vaultIdlCopy as any, provider);
  
  let whitelisted = 0;
  let existing = 0;
  let failed = 0;
  
  console.log("\n🚀 Starting token whitelisting...\n");
  
  for (const token of TRADING_TOKENS_WITH_ORACLES) {
    console.log(`🔍 Processing ${token.symbol} (${token.maxAllocationBps/100}% max)...`);
    
    // Derive token whitelist PDA
    const [tokenWhitelist] = PublicKey.findProgramAddressSync(
      [
        Buffer.from("token_whitelist"),
        vaultPda.toBuffer(),
        token.mint.toBuffer()
      ],
      PROGRAMS.VAULT
    );
    
    try {
      const tx = await vaultProgram.methods
        .addWhitelistedToken(
          token.mint,
          token.symbol,
          token.pythOracle,
          null, // No Switchboard oracle for now
          token.maxAllocationBps
        )
        .accounts({
          authority: deployerKeypair.publicKey,
          vault: vaultPda,
          tokenWhitelist: tokenWhitelist,
          tokenMint: token.mint,
          pythOracleAccount: token.pythOracle,
          switchboardOracleAccount: null,
          systemProgram: SystemProgram.programId,
        })
        .preInstructions([
          ComputeBudgetProgram.setComputeUnitLimit({ units: 200_000 })
        ])
        .rpc({ commitment: "confirmed" });
      
      console.log(`✅ ${token.symbol} whitelisted: ${tx.slice(0, 8)}...`);
      whitelisted++;
      
    } catch (error) {
      if (error.message?.includes("already in use") || error.message?.includes("already initialized")) {
        console.log(`✅ ${token.symbol} already whitelisted`);
        existing++;
      } else {
        console.log(`❌ Failed to whitelist ${token.symbol}: ${error.message}`);
        failed++;
      }
    }
    
    // Small delay to avoid rate limits
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  
  console.log(`\n📊 WHITELIST SUMMARY:`);
  console.log(`   ✅ Newly whitelisted: ${whitelisted}`);
  console.log(`   ✅ Already existing: ${existing}`);
  console.log(`   ❌ Failed: ${failed}`);
  console.log(`   📊 Total success: ${whitelisted + existing}/${TRADING_TOKENS_WITH_ORACLES.length}`);
  
  if (whitelisted + existing === TRADING_TOKENS_WITH_ORACLES.length) {
    console.log("\n🎉 ALL TOKENS SUCCESSFULLY WHITELISTED!");
    console.log("🚀 Calvin Vault is now FULLY READY for production trading!");
    console.log("💰 Users can deposit USDC and AI can trade across all 20 tokens!");
  } else {
    console.log(`\n⚠️  ${failed} tokens failed to whitelist. Check errors above.`);
  }
}

if (require.main === module) {
  whitelistAllTokens().catch(console.error);
}

export default whitelistAllTokens;
