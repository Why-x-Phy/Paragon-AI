import * as anchor from "@coral-xyz/anchor";
import { Program, BN } from "@coral-xyz/anchor";
import { Vault } from "../target/types/vault";
import { CalvinStaking } from "../target/types/calvin_staking";
import { 
  PublicKey, 
  Keypair, 
  SystemProgram, 
  SYSVAR_RENT_PUBKEY,
  Transaction,
  sendAndConfirmTransaction
} from "@solana/web3.js";
import { 
  TOKEN_PROGRAM_ID, 
  ASSOCIATED_TOKEN_PROGRAM_ID,
  createMint,
  createAccount,
  mintTo,
  getAccount,
  getAssociatedTokenAddressSync
} from "@solana/spl-token";
import { expect } from "chai";

describe("Calvin Trade Instruction Tests", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const vaultProgram = anchor.workspace.Vault as Program<Vault>;
  const stakingProgram = anchor.workspace.CalvinStaking as Program<CalvinStaking>;

  // Test wallets
  const payer = provider.wallet as anchor.Wallet;
  const calvinAuthority = Keypair.generate(); // Calvin AI trading authority
  const unauthorizedUser = Keypair.generate(); // Should be rejected
  
  // Test state
  let usdcMint: PublicKey;
  let calvinMint: PublicKey;
  let testTokenMint: PublicKey; // For SOL-like token testing
  let vault: PublicKey;
  let vaultAuthority: PublicKey;
  let usdcVault: PublicKey;
  let sharesMint: PublicKey;
  let vaultTestTokenAccount: PublicKey;

  before(async () => {
    console.log("🔧 Setting up Trade Instruction Test Environment");
    console.log(`Payer: ${payer.publicKey.toString()}`);
    console.log(`Calvin Authority: ${calvinAuthority.publicKey.toString()}`);
    
    try {
      // Create test tokens
      console.log("  Creating test token mints...");
      
      usdcMint = await createMint(
        provider.connection,
        payer.payer,
        payer.publicKey,
        null,
        6 // USDC decimals
      );
      
      calvinMint = await createMint(
        provider.connection,
        payer.payer,
        payer.publicKey,
        null,
        9 // CALVIN decimals
      );
      
      testTokenMint = await createMint(
        provider.connection,
        payer.payer,
        payer.publicKey,
        null,
        9 // Test token decimals (SOL-like)
      );

      console.log(`  USDC Mint: ${usdcMint.toString()}`);
      console.log(`  CALVIN Mint: ${calvinMint.toString()}`);
      console.log(`  Test Token Mint: ${testTokenMint.toString()}`);

      // Derive vault PDAs using correct seeds (but different test accounts)
      [vault] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault")], // Use correct seed from constants
        vaultProgram.programId
      );

      [vaultAuthority] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_authority")],
        vaultProgram.programId
      );

      // Use proper ATA derivation for vault's USDC account
      usdcVault = getAssociatedTokenAddressSync(
        usdcMint,
        vaultAuthority,
        true // allowOwnerOffCurve for PDA
      );

      [sharesMint] = PublicKey.findProgramAddressSync(
        [Buffer.from("shares_mint")],
        vaultProgram.programId
      );

      // Derive test token account for vault
      vaultTestTokenAccount = getAssociatedTokenAddressSync(
        testTokenMint,
        vaultAuthority,
        true // allowOwnerOffCurve for PDA
      );

      console.log(`Vault: ${vault.toString()}`);
      console.log(`Vault Authority: ${vaultAuthority.toString()}`);
      console.log(`USDC Vault: ${usdcVault.toString()}`);
      console.log(`Shares Mint: ${sharesMint.toString()}`);
      
    } catch (error) {
      console.error("❌ Setup failed:", error);
      throw error;
    }
  });

  it("Should initialize vault with Calvin authority", async () => {
    try {
      console.log("  Initializing vault...");
      
      await vaultProgram.methods
        .initialize(
          payer.publicKey, // emergencyOwner
          calvinAuthority.publicKey, // calvinAuthority
          stakingProgram.programId, // stakingProgramId
          new BN(10000 * 1e6), // perNftCap (10K USDC in micro-USDC)
          new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4") // jupiterProgramId
        )
        .accounts({
          initializer: payer.publicKey,
          usdcMint: usdcMint,
          calvinMint: calvinMint,
          vault: vault,
          usdcVault: usdcVault,
          vaultAuthority: vaultAuthority,
          sharesMint: sharesMint,
          treasury: payer.publicKey, // Treasury wallet
          systemProgram: SystemProgram.programId,
          tokenProgram: TOKEN_PROGRAM_ID,
          associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
          rent: SYSVAR_RENT_PUBKEY,
        })
        .rpc({ skipPreflight: true });

      console.log("✅ Vault initialized successfully");
      
      // Verify vault state
      const vaultAccount = await vaultProgram.account.vault.fetch(vault);
      expect(vaultAccount.calvinAuthority.toString()).to.equal(calvinAuthority.publicKey.toString());
      expect(vaultAccount.emergencyOwners[0].toString()).to.equal(payer.publicKey.toString());
      expect(vaultAccount.emergencyOwnersCount).to.equal(1);
      
    } catch (error) {
      if (error.message?.includes("already in use")) {
        console.log("ℹ️ Vault already initialized, checking state...");
        
        try {
          const vaultAccount = await vaultProgram.account.vault.fetch(vault);
          console.log("✅ Vault state is valid, continuing with tests");
        } catch (fetchError) {
          console.error("❌ Vault exists but data is corrupted:", fetchError);
          throw new Error("Vault account is corrupted - please run reset script first");
        }
      } else {
        console.error("❌ Vault initialization failed:", error);
        throw error;
      }
    }
  });

  it("Should create vault token accounts", async () => {
    try {
      console.log("  Creating vault token accounts...");

      // Create vault's test token account using initializeTokenAccounts
      await vaultProgram.methods
        .initializeTokenAccounts()
        .accounts({
          payer: payer.publicKey,
          vault: vault,
          vaultAuthority: vaultAuthority,
          tokenMint: testTokenMint,
          vaultTokenAccount: vaultTestTokenAccount,
          systemProgram: SystemProgram.programId,
          tokenProgram: TOKEN_PROGRAM_ID,
          associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
        })
        .rpc();

      console.log("  Funding vault accounts with test tokens...");

      // Fund vault USDC account (this should already exist from initialization)
      await mintTo(
        provider.connection,
        payer.payer,
        usdcMint,
        usdcVault,
        payer.publicKey,
        1000000000 // 1000 USDC (6 decimals)
      );

      // Fund vault test token account
      await mintTo(
        provider.connection,
        payer.payer,
        testTokenMint,
        vaultTestTokenAccount,
        payer.publicKey,
        1000000000 // 1 test token (9 decimals)
      );

      console.log("✅ Vault token accounts created and funded");
      console.log(`  USDC Account: ${usdcVault.toString()}`);
      console.log(`  Test Token Account: ${vaultTestTokenAccount.toString()}`);
      
    } catch (error) {
      console.error("❌ Token account creation failed:", error);
      throw error;
    }
  });

  it("Should whitelist test tokens", async () => {
    try {
      console.log("  Whitelisting USDC...");
      
      // Whitelist USDC
      const [usdcWhitelist] = PublicKey.findProgramAddressSync(
        [Buffer.from("token_whitelist"), vault.toBuffer(), usdcMint.toBuffer()],
        vaultProgram.programId
      );

      await vaultProgram.methods
        .addWhitelistedToken(
          usdcMint,
          "USDC",
          new PublicKey("Gnt27xtC473ZT2Mw5u8wZ68Z3gULkSTb5DuxJy7eJotD"), // Dummy Pyth oracle
          null, // No Switchboard oracle
          8000 // 80% max allocation
        )
        .accounts({
          authority: payer.publicKey,
          vault: vault,
          tokenWhitelist: usdcWhitelist,
          tokenMint: usdcMint,
          pythOracleAccount: new PublicKey("Gnt27xtC473ZT2Mw5u8wZ68Z3gULkSTb5DuxJy7eJotD"),
          switchboardOracleAccount: null, // Explicitly provide null for optional account
          systemProgram: SystemProgram.programId,
        })
        .rpc();

      console.log("  Whitelisting test token...");

      // Whitelist test token
      const [testTokenWhitelist] = PublicKey.findProgramAddressSync(
        [Buffer.from("token_whitelist"), vault.toBuffer(), testTokenMint.toBuffer()],
        vaultProgram.programId
      );

      await vaultProgram.methods
        .addWhitelistedToken(
          testTokenMint,
          "TEST",
          new PublicKey("H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG"), // Dummy Pyth oracle
          null, // No Switchboard oracle
          2000 // 20% max allocation
        )
        .accounts({
          authority: payer.publicKey,
          vault: vault,
          tokenWhitelist: testTokenWhitelist,
          tokenMint: testTokenMint,
          pythOracleAccount: new PublicKey("H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG"),
          // Note: switchboardOracleAccount is optional and not provided
          systemProgram: SystemProgram.programId,
        })
        .rpc();

      console.log("✅ Test tokens whitelisted successfully");
      
    } catch (error) {
      console.error("❌ Token whitelisting failed:", error);
      throw error;
    }
  });

  it("Should reject trade from unauthorized user", async () => {
    try {
      console.log("  Testing unauthorized user rejection...");
      
      // Fund unauthorized user with SOL for transaction fees
      const transferTx = new Transaction().add(
        SystemProgram.transfer({
          fromPubkey: payer.publicKey,
          toPubkey: unauthorizedUser.publicKey,
          lamports: 100000000, // 0.1 SOL
        })
      );
      await sendAndConfirmTransaction(provider.connection, transferTx, [payer.payer]);

      const [usdcWhitelist] = PublicKey.findProgramAddressSync(
        [Buffer.from("token_whitelist"), vault.toBuffer(), usdcMint.toBuffer()],
        vaultProgram.programId
      );

      const [testTokenWhitelist] = PublicKey.findProgramAddressSync(
        [Buffer.from("token_whitelist"), vault.toBuffer(), testTokenMint.toBuffer()],
        vaultProgram.programId
      );

      // Attempt trade with unauthorized user (should fail)
      try {
        await vaultProgram.methods
          .trade(Buffer.from([1, 2, 3, 4])) // Dummy Jupiter data as Buffer
          .accounts({
            authority: unauthorizedUser.publicKey, // ❌ Not Calvin authority
            vault: vault,
            vaultUsdcToken: usdcVault,
            sourceMint: usdcMint,
            destinationMint: testTokenMint,
            sourceTokenAccount: usdcVault,
            destinationTokenAccount: vaultTestTokenAccount,
            vaultAuthority: vaultAuthority,
            sourceTokenWhitelist: usdcWhitelist,
            destinationTokenWhitelist: testTokenWhitelist,
            sourcePriceAccount: new PublicKey("Gnt27xtC473ZT2Mw5u8wZ68Z3gULkSTb5DuxJy7eJotD"),
            destinationPriceAccount: new PublicKey("H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG"),
            jupiterProgram: new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"),
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([unauthorizedUser])
          .rpc();

        // If we get here, the test failed
        expect.fail("Trade should have been rejected for unauthorized user");
        
      } catch (error) {
        // This is expected - unauthorized user should be rejected
        console.log(`  Trade rejected with error: ${error.message}`);
        // The specific error might vary, but it should be an authorization error
        expect(error.message).to.satisfy((msg: string) => 
          msg.includes("UnauthorizedCalvin") || 
          msg.includes("unauthorized") || 
          msg.includes("constraint") ||
          msg.includes("ConstraintViolation")
        );
        console.log("✅ Unauthorized user correctly rejected");
      }
      
    } catch (error) {
      console.error("❌ Unauthorized test setup failed:", error);
      throw error;
    }
  });

  it("Should accept trade from Calvin authority (but Jupiter will fail)", async () => {
    try {
      console.log("  Testing Calvin authority trade...");
      
      // Fund Calvin authority with SOL for transaction fees
      const transferTx = new Transaction().add(
        SystemProgram.transfer({
          fromPubkey: payer.publicKey,
          toPubkey: calvinAuthority.publicKey,
          lamports: 100000000, // 0.1 SOL
        })
      );
      await sendAndConfirmTransaction(provider.connection, transferTx, [payer.payer]);

      const [usdcWhitelist] = PublicKey.findProgramAddressSync(
        [Buffer.from("token_whitelist"), vault.toBuffer(), usdcMint.toBuffer()],
        vaultProgram.programId
      );

      const [testTokenWhitelist] = PublicKey.findProgramAddressSync(
        [Buffer.from("token_whitelist"), vault.toBuffer(), testTokenMint.toBuffer()],
        vaultProgram.programId
      );

      // Attempt trade with Calvin authority
      try {
        await vaultProgram.methods
          .trade(Buffer.from([1, 2, 3, 4])) // Dummy Jupiter data as Buffer
          .accounts({
            authority: calvinAuthority.publicKey, // ✅ Correct Calvin authority
            vault: vault,
            vaultUsdcToken: usdcVault,
            sourceMint: usdcMint,
            destinationMint: testTokenMint,
            sourceTokenAccount: usdcVault,
            destinationTokenAccount: vaultTestTokenAccount,
            vaultAuthority: vaultAuthority,
            sourceTokenWhitelist: usdcWhitelist,
            destinationTokenWhitelist: testTokenWhitelist,
            sourcePriceAccount: new PublicKey("Gnt27xtC473ZT2Mw5u8wZ68Z3gULkSTb5DuxJy7eJotD"),
            destinationPriceAccount: new PublicKey("H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG"),
            jupiterProgram: new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"),
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([calvinAuthority])
          .rpc();

        // If we get here, either Jupiter worked (unlikely) or there's an issue
        console.log("🤔 Trade succeeded - Jupiter might have worked?");
        
      } catch (error) {
        // Expected: Jupiter will fail, but we should pass all vault security checks
        console.log(`  Trade failed with error: ${error.message}`);
        
        if (error.message.includes("JupiterSwapFailed") || 
            error.message.includes("Jupiter") ||
            error.message.includes("InvalidPriceData") ||
            error.message.includes("PriceNotTrading") ||
            error.message.includes("AccountNotInitialized")) {
          console.log("✅ Calvin authority passed vault security checks, Jupiter/Oracle failed as expected");
        } else {
          // Unexpected error - our vault logic might have failed
          console.error("❌ Unexpected vault error:", error.message);
          throw error;
        }
      }
      
    } catch (error) {
      console.error("❌ Calvin authority test failed:", error);
      throw error;
    }
  });

  it("Should validate vault state after trade attempts", async () => {
    try {
      console.log("  Validating final vault state...");
      
      // Check vault state is still consistent
      const vaultAccount = await vaultProgram.account.vault.fetch(vault);
      
      // Verify basic vault properties
      expect(vaultAccount.calvinAuthority.toString()).to.equal(calvinAuthority.publicKey.toString());
      expect(vaultAccount.emergencyOwners[0].toString()).to.equal(payer.publicKey.toString());
      expect(vaultAccount.emergencyOwnersCount).to.equal(1);
      
      // Verify vault is operational
      expect(vaultAccount.paused).to.be.false;
      expect(vaultAccount.tradingPaused).to.be.false;
      expect(vaultAccount.depositsPaused).to.be.false;
      expect(vaultAccount.withdrawalsPaused).to.be.false;
      
      console.log("✅ Vault state is consistent after trade attempts");
      console.log(`  Total Shares: ${vaultAccount.totalShares.toString()}`);
      
    } catch (error) {
      console.error("❌ Vault state validation failed:", error);
      throw error;
    }
  });
}); 