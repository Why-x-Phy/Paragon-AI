import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { PublicKey, SystemProgram, SYSVAR_RENT_PUBKEY } from "@solana/web3.js";
import { 
    TOKEN_PROGRAM_ID, 
    ASSOCIATED_TOKEN_PROGRAM_ID,
    getAssociatedTokenAddressSync
} from "@solana/spl-token";
import { readFileSync } from "fs";
import * as os from 'os';
import * as path from 'path';

// Load IDL
const idlPath = path.join(__dirname, '../target/idl/vault.json');
const idl = JSON.parse(readFileSync(idlPath, 'utf8'));

// Constants
const VAULT_PROGRAM_ID = new PublicKey("tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z");

// PDAs
const [vaultPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault")],
    VAULT_PROGRAM_ID
);

const [vaultAuthority] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault_authority")],
    VAULT_PROGRAM_ID
);

const [sharesMint] = PublicKey.findProgramAddressSync(
    [Buffer.from("shares_mint")],
    VAULT_PROGRAM_ID
);

async function adminMintShares() {
    console.log("🔐 Admin Mint Shares Script");
    console.log("========================\n");

    // Setup
    const connection = new anchor.web3.Connection(
        process.env.RPC_URL || "https://api.mainnet-beta.solana.com",
        "confirmed"
    );

    // Load authority keypair (emergency owner)
    const authorityKeypath = path.join(os.homedir(), '.config/solana/id.json');
    const authorityKeypair = anchor.web3.Keypair.fromSecretKey(
        Buffer.from(JSON.parse(readFileSync(authorityKeypath, 'utf-8')))
    );
    console.log("Authority:", authorityKeypair.publicKey.toString());

    const provider = new anchor.AnchorProvider(
        connection, 
        new anchor.Wallet(authorityKeypair),
        { commitment: "confirmed" }
    );
    anchor.setProvider(provider);

    const program = new Program(idl, provider);

    // ============================================================
    // CONFIGURATION - MODIFY THESE VALUES
    // ============================================================
    
    // The recipient's wallet address (the user who needs compensation)
    const RECIPIENT = new PublicKey("573sGNd7Wrp8YVQ24VaRPGJ61qUCEecYZFBiZ8MmhJF9");
    
    // Number of shares to mint
    // Calculate this based on:
    // 1. How much USDC they should have received
    // 2. Current NAV per share
    // Example: If they should have received 1000 USDC and NAV per share is 1.2 USDC, 
    // then shares = 1000 / 1.2 = 833.33 shares
    const SHARES_TO_MINT = new anchor.BN(6_605_000_000); // 6605 shares (6 decimals) - TEST AMOUNT
    
    // Reason for minting (for audit trail)
    const REASON = "Compensation for withdrawal NAV calculation bug before fix";
    
    // ============================================================

    console.log("Recipient:", RECIPIENT.toString());
    console.log("Shares to mint:", SHARES_TO_MINT.toString());
    console.log("Reason:", REASON);
    console.log("");

    // Derive PDAs
    const [userPosition] = PublicKey.findProgramAddressSync(
        [Buffer.from("user_position"), RECIPIENT.toBuffer(), vaultPda.toBuffer()],
        VAULT_PROGRAM_ID
    );

    const recipientSharesToken = getAssociatedTokenAddressSync(
        sharesMint,
        RECIPIENT,
        true
    );

    // Fetch current vault state
    // @ts-ignore - TypeScript doesn't recognize the account types from IDL
    const vault = await program.account.vault.fetch(vaultPda);
    console.log("Current total shares:", vault.totalShares.toString());
    console.log("Current cached NAV:", vault.cachedNav.toString());
    
    if (vault.totalShares.gt(new anchor.BN(0)) && vault.cachedNav.gt(new anchor.BN(0))) {
        const navPerShare = vault.cachedNav.mul(new anchor.BN(1_000_000)).div(vault.totalShares);
        console.log("NAV per share:", navPerShare.toString(), "(in micro-USDC)");
        console.log("NAV per share (USDC):", navPerShare.toNumber() / 1_000_000);
    }
    console.log("");

    // Check if user already has shares
    try {
        const shareBalance = await connection.getTokenAccountBalance(recipientSharesToken);
        console.log("User's current shares:", shareBalance.value.amount);
    } catch (e) {
        console.log("User has no share token account yet (will be created)");
    }

    console.log("\n🚀 Executing admin mint shares...");

    try {
        const tx = await program.methods
            .adminMintShares(SHARES_TO_MINT, REASON)
            .accounts({
                authority: authorityKeypair.publicKey,
                vault: vaultPda,
                recipient: RECIPIENT,
                userPosition: userPosition,
                sharesMint: sharesMint,
                recipientSharesToken: recipientSharesToken,
                vaultAuthority: vaultAuthority,
                systemProgram: SystemProgram.programId,
                tokenProgram: TOKEN_PROGRAM_ID,
                associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
                rent: SYSVAR_RENT_PUBKEY,
            })
            .signers([authorityKeypair])
            .rpc();

        console.log("✅ Transaction successful:", tx);
        
        // Fetch updated state
        // @ts-ignore - TypeScript doesn't recognize the account types from IDL
        const updatedVault = await program.account.vault.fetch(vaultPda);
        console.log("\n📊 Updated vault state:");
        console.log("New total shares:", updatedVault.totalShares.toString());
        
        const shareBalance = await connection.getTokenAccountBalance(recipientSharesToken);
        console.log("Recipient's new share balance:", shareBalance.value.amount);
        
    } catch (error) {
        console.error("❌ Transaction failed:", error);
        if (error.logs) {
            console.error("Transaction logs:", error.logs);
        }
    }
}

// Helper function to calculate shares based on USDC amount
function calculateSharesFromUSDC(usdcAmount: number, navPerShare: number): anchor.BN {
    // Convert USDC to micro-USDC (6 decimals)
    const microUsdc = usdcAmount * 1_000_000;
    
    // Calculate shares (shares have 6 decimals too)
    const shares = microUsdc / navPerShare;
    
    return new anchor.BN(Math.floor(shares));
}

// Run the script
adminMintShares().catch(console.error); 