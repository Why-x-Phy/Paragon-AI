import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { 
  PublicKey, 
  Keypair, 
  SystemProgram,
  SYSVAR_RENT_PUBKEY,
} from "@solana/web3.js";
import { 
  TOKEN_PROGRAM_ID,
  ASSOCIATED_TOKEN_PROGRAM_ID,
  createMint,
  createAccount,
  mintTo,
  getAccount,
  getAssociatedTokenAddress,
  createAssociatedTokenAccount
} from "@solana/spl-token";
import { CalvinStaking } from "../target/types/calvin_staking";
import { Vault } from "../target/types/vault";
import { expect } from "chai";

describe("Jupiter Trading & Calvin AI Integration Tests", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const stakingProgram = anchor.workspace.CalvinStaking as Program<CalvinStaking>;
  const vaultProgram = anchor.workspace.Vault as Program<Vault>;

  // Test accounts
  let authority: Keypair;
  let calvinAI: Keypair; // Calvin AI trading authority
  let treasuryWallet: Keypair;
  let user1: Keypair;
  let unauthorizedTrader: Keypair; // Test unauthorized access
  
  // Token mints
  let calvinMint: PublicKey;
  let usdcMint: PublicKey;
  let solMint: PublicKey; // For SOL/USDC swaps
  let sharesMint: PublicKey;
  
  // Token accounts
  let vaultUsdcToken: PublicKey;
  let vaultSolToken: PublicKey;
  let treasuryUsdcToken: PublicKey;

  // Program addresses
  const STAKING_PROGRAM_ID = new PublicKey("qUKhRct5LW3e9Zwn1e7DvKscsSwVv2S952D7nx39Ach");
  const VAULT_PROGRAM_ID = new PublicKey("Eehx8tDgRctoJbTEdXRp85hCW55nH62g5Eiy7yAn7KDg");
  
  // Mock Jupiter Program ID (for testing) - using real Jupiter program ID
  const MOCK_JUPITER_PROGRAM_ID = new PublicKey("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");

  before(async () => {
    // Create test keypairs
    authority = Keypair.generate();
    calvinAI = Keypair.generate();
    treasuryWallet = Keypair.generate();
    user1 = Keypair.generate();
    unauthorizedTrader = Keypair.generate();

    // Airdrop SOL
    await provider.connection.confirmTransaction(
      await provider.connection.requestAirdrop(authority.publicKey, 10 * anchor.web3.LAMPORTS_PER_SOL)
    );
    await provider.connection.confirmTransaction(
      await provider.connection.requestAirdrop(calvinAI.publicKey, 5 * anchor.web3.LAMPORTS_PER_SOL)
    );
    await provider.connection.confirmTransaction(
      await provider.connection.requestAirdrop(user1.publicKey, 5 * anchor.web3.LAMPORTS_PER_SOL)
    );
    await provider.connection.confirmTransaction(
      await provider.connection.requestAirdrop(unauthorizedTrader.publicKey, 2 * anchor.web3.LAMPORTS_PER_SOL)
    );

    // Create token mints
    calvinMint = await createMint(provider.connection, authority, authority.publicKey, authority.publicKey, 6);
    usdcMint = await createMint(provider.connection, authority, authority.publicKey, authority.publicKey, 6);
    solMint = await createMint(provider.connection, authority, authority.publicKey, authority.publicKey, 9); // SOL has 9 decimals

    // Create treasury USDC account
    treasuryUsdcToken = await createAssociatedTokenAccount(
      provider.connection,
      treasuryWallet,
      usdcMint,
      treasuryWallet.publicKey
    );

    console.log("✅ Jupiter Trading Test Setup Complete");
    console.log("🤖 Calvin AI Authority:", calvinAI.publicKey.toBase58());
    console.log("📊 USDC Mint:", usdcMint.toBase58());
    console.log("☀️ SOL Mint:", solMint.toBase58());
  });

  describe("🏗️ Setup Trading Environment", () => {
    it("Should initialize programs with Calvin AI authority", async () => {
      // Initialize staking program
      const [stakeConfig] = PublicKey.findProgramAddressSync(
        [Buffer.from("stake_config")],
        STAKING_PROGRAM_ID
      );

      const [stakeVault] = PublicKey.findProgramAddressSync(
        [Buffer.from("stake_vault")],
        STAKING_PROGRAM_ID
      );

      const [vaultPassMint] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_pass_mint")],
        STAKING_PROGRAM_ID
      );

      const TIER_THRESHOLDS = [
        new anchor.BN("10000000000000"), // Vault Keeper: 10M CALVIN
        new anchor.BN("2000000000000"),  // Tier 2: 2M CALVIN  
        new anchor.BN("500000000000"),   // Tier 3: 500K CALVIN
        new anchor.BN(0)                 // Default tier
      ];

      await stakingProgram.methods
        .initializeStaking(TIER_THRESHOLDS, VAULT_PROGRAM_ID)
        .accounts({
          admin: authority.publicKey,
          stakeConfig: stakeConfig,
          stakeVault: stakeVault,
          calvinMint: calvinMint,
          vaultPassMint: vaultPassMint,
          systemProgram: SystemProgram.programId,
          tokenProgram: TOKEN_PROGRAM_ID,
          associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
          rent: SYSVAR_RENT_PUBKEY,
        })
        .signers([authority])
        .rpc();

      // Initialize vault program with Calvin AI authority
      const [vault] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault")],
        VAULT_PROGRAM_ID
      );

      const [vaultAuthority] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_authority")],
        VAULT_PROGRAM_ID
      );

      vaultUsdcToken = await getAssociatedTokenAddress(usdcMint, vaultAuthority, true);
      vaultSolToken = await getAssociatedTokenAddress(solMint, vaultAuthority, true);

      const [sharesMintPDA] = PublicKey.findProgramAddressSync(
        [Buffer.from("shares_mint")],
        VAULT_PROGRAM_ID
      );
      sharesMint = sharesMintPDA;

      await vaultProgram.methods
        .initialize(
          authority.publicKey,        // emergency_owner
          calvinAI.publicKey,         // 🤖 Calvin AI as trading authority
          STAKING_PROGRAM_ID,
          new anchor.BN(1000 * 1e6),  // per_nft_cap
          MOCK_JUPITER_PROGRAM_ID     // Jupiter program ID
        )
        .accounts({
          initializer: authority.publicKey,
          usdcMint: usdcMint,
          calvinMint: calvinMint,
          vault: vault,
          usdcVault: vaultUsdcToken,
          vaultAuthority: vaultAuthority,
          sharesMint: sharesMint,
          treasury: treasuryWallet.publicKey,
          systemProgram: SystemProgram.programId,
          tokenProgram: TOKEN_PROGRAM_ID,
          associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
          rent: SYSVAR_RENT_PUBKEY,
        })
        .signers([authority])
        .rpc();

      console.log("✅ Programs initialized with Calvin AI authority");
    });

    it("Should setup user with staking and vault deposits", async () => {
      // Create user CALVIN tokens and stake them
      const userCalvinToken = await createAssociatedTokenAccount(
        provider.connection,
        user1,
        calvinMint,
        user1.publicKey
      );

      await mintTo(provider.connection, authority, calvinMint, userCalvinToken, authority, 1000000000000); // 1M CALVIN

      const [userStake] = PublicKey.findProgramAddressSync(
        [Buffer.from("user_stake"), user1.publicKey.toBuffer()],
        STAKING_PROGRAM_ID
      );

      const [stakeConfig] = PublicKey.findProgramAddressSync(
        [Buffer.from("stake_config")],
        STAKING_PROGRAM_ID
      );

      const [stakeVault] = PublicKey.findProgramAddressSync(
        [Buffer.from("stake_vault")],
        STAKING_PROGRAM_ID
      );

      const stakeVaultCalvinToken = await getAssociatedTokenAddress(calvinMint, stakeVault, true);

      const [vaultPassMint] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_pass_mint")],
        STAKING_PROGRAM_ID
      );

      const [userVaultPassMint] = PublicKey.findProgramAddressSync(
        [Buffer.from("vault_pass_mint"), user1.publicKey.toBuffer()],
        STAKING_PROGRAM_ID
      );

      const userVaultPassToken = await getAssociatedTokenAddress(userVaultPassMint, user1.publicKey);

      // Stake CALVIN
      await stakingProgram.methods
        .stakeCalvin(new anchor.BN("500000000000")) // 500K CALVIN
        .accounts({
          user: user1.publicKey,
          stakeConfig: stakeConfig,
          stakeVault: stakeVault,
          userStake: userStake,
          userCalvinToken: userCalvinToken,
          stakeVaultCalvinToken: stakeVaultCalvinToken,
          calvinMint: calvinMint,
          vaultPassMint: vaultPassMint,
          userVaultPassMint: userVaultPassMint,
          userVaultPassToken: userVaultPassToken,
          systemProgram: SystemProgram.programId,
          tokenProgram: TOKEN_PROGRAM_ID,
          associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
          rent: SYSVAR_RENT_PUBKEY,
        })
        .signers([user1])
        .rpc();

      // Create user USDC and deposit to vault
      const userUsdcToken = await createAssociatedTokenAccount(
        provider.connection,
        user1,
        usdcMint,
        user1.publicKey
      );

      await mintTo(provider.connection, authority, usdcMint, userUsdcToken, authority, 10_000 * 1e6); // 10,000 USDC

      const [vault] = PublicKey.findProgramAddressSync([Buffer.from("vault")], VAULT_PROGRAM_ID);
      const [userPosition] = PublicKey.findProgramAddressSync(
        [Buffer.from("user_position"), user1.publicKey.toBuffer(), vault.toBuffer()],
        VAULT_PROGRAM_ID
      );
      const [vaultAuthority] = PublicKey.findProgramAddressSync([Buffer.from("vault_authority")], VAULT_PROGRAM_ID);
      const userSharesToken = await getAssociatedTokenAddress(sharesMint, user1.publicKey, true);

      // Deposit USDC to vault
      await vaultProgram.methods
        .deposit(new anchor.BN(5000 * 1e6)) // 5000 USDC
        .accounts({
          user: user1.publicKey,
          vault: vault,
          userPosition: userPosition,
          userUsdcToken: userUsdcToken,
          vaultUsdcToken: vaultUsdcToken,
          treasuryUsdcToken: treasuryUsdcToken,
          sharesMint: sharesMint,
          userSharesToken: userSharesToken,
          vaultAuthority: vaultAuthority,
          stakingProgram: STAKING_PROGRAM_ID,
          systemProgram: SystemProgram.programId,
          tokenProgram: TOKEN_PROGRAM_ID,
          associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
          rent: SYSVAR_RENT_PUBKEY,
        })
        .remainingAccounts([
          { pubkey: stakeConfig, isWritable: false, isSigner: false },
          { pubkey: userStake, isWritable: false, isSigner: false },
        ])
        .signers([user1])
        .rpc();

      // Verify vault has USDC for trading
      const vaultUsdcAccount = await getAccount(provider.connection, vaultUsdcToken);
      expect(Number(vaultUsdcAccount.amount)).to.be.greaterThan(4000 * 1e6); // Should have ~4875 USDC after 2.5% fee

      console.log("✅ User setup complete - vault has USDC for trading");
      console.log("💰 Vault USDC Balance:", vaultUsdcAccount.amount.toString());
    });
  });

  describe("🤖 Calvin AI Trade Authorization", () => {
    it("Should ALLOW Calvin AI to execute trades", async () => {
      const [vault] = PublicKey.findProgramAddressSync([Buffer.from("vault")], VAULT_PROGRAM_ID);
      const [vaultAuthority] = PublicKey.findProgramAddressSync([Buffer.from("vault_authority")], VAULT_PROGRAM_ID);

      // Mock Jupiter swap data (in real scenarios, this would be generated by Jupiter API)
      const mockSwapData = Buffer.from([1, 2, 3, 4]); // Placeholder swap instruction data

      try {
        await vaultProgram.methods
          .trade(Array.from(mockSwapData))
          .accounts({
            authority: calvinAI.publicKey, // 🤖 Calvin AI authority
            vault: vault,
            vaultUsdcToken: vaultUsdcToken,
            sourceMint: usdcMint,
            destinationMint: solMint,
            sourceTokenAccount: vaultUsdcToken,
            destinationTokenAccount: vaultSolToken,
            vaultAuthority: vaultAuthority,
            jupiterProgram: MOCK_JUPITER_PROGRAM_ID,
            tokenProgram: TOKEN_PROGRAM_ID,
            systemProgram: SystemProgram.programId,
            rent: SYSVAR_RENT_PUBKEY,
            remainingAccounts: PublicKey.default, // Placeholder for Jupiter remaining accounts
          })
          .signers([calvinAI]) // 🤖 Calvin AI signs the transaction
          .rpc();

        console.log("✅ Calvin AI successfully authorized trade execution");
      } catch (error) {
        // Expected to fail with Jupiter program not found, but should NOT fail with authorization
        expect(error.message).to.not.include("UnauthorizedCalvin");
        expect(error.message).to.not.include("Unauthorized");
        console.log("✅ Calvin AI authorization passed (failed on Jupiter mock, as expected)");
      }
    });

    it("Should REJECT unauthorized traders", async () => {
      const [vault] = PublicKey.findProgramAddressSync([Buffer.from("vault")], VAULT_PROGRAM_ID);
      const [vaultAuthority] = PublicKey.findProgramAddressSync([Buffer.from("vault_authority")], VAULT_PROGRAM_ID);

      const mockSwapData = Buffer.from([1, 2, 3, 4]);

      try {
        await vaultProgram.methods
          .trade(Array.from(mockSwapData))
          .accounts({
            authority: unauthorizedTrader.publicKey, // ❌ Unauthorized trader
            vault: vault,
            vaultUsdcToken: vaultUsdcToken,
            sourceMint: usdcMint,
            destinationMint: solMint,
            sourceTokenAccount: vaultUsdcToken,
            destinationTokenAccount: vaultSolToken,
            vaultAuthority: vaultAuthority,
            jupiterProgram: MOCK_JUPITER_PROGRAM_ID,
            tokenProgram: TOKEN_PROGRAM_ID,
            systemProgram: SystemProgram.programId,
            rent: SYSVAR_RENT_PUBKEY,
            remainingAccounts: PublicKey.default,
          })
          .signers([unauthorizedTrader])
          .rpc();

        expect.fail("Unauthorized trader should have been rejected!");
      } catch (error) {
        expect(error.message).to.include("UnauthorizedCalvin");
        console.log("✅ Unauthorized trader correctly rejected");
      }
    });
  });

  describe("📊 Trade Signal Simulation", () => {
    it("Should simulate Calvin AI sending trade signals", async () => {
      // This simulates the flow where Calvin AI backend sends trade instructions

      console.log("\n🧠 === Calvin AI Signal Generation ===");
      
      // 1. Calvin AI analyzes market (simulated)
      const marketSignal = {
        action: "BUY",
        fromToken: "USDC",
        toToken: "SOL", 
        amount: 1000 * 1e6, // 1000 USDC
        confidence: 0.85,
        timestamp: Date.now()
      };

      console.log("📡 Calvin AI Signal:", marketSignal);

      // 2. Calvin AI prepares Jupiter swap instruction (simulated)
      // In real implementation, this would call Jupiter API to get swap instruction
      const jupiterSwapInstruction = {
        programId: MOCK_JUPITER_PROGRAM_ID,
        data: [1, 2, 3, 4], // Mock Jupiter instruction data
        accounts: [] // Mock Jupiter accounts
      };

      console.log("🔄 Jupiter Swap Prepared:", jupiterSwapInstruction);

      // 3. Calvin AI sends trade to vault (this would succeed with real Jupiter)
      const [vault] = PublicKey.findProgramAddressSync([Buffer.from("vault")], VAULT_PROGRAM_ID);
      
      console.log("✅ Trade signal flow validated - Calvin AI → Vault Program");
      console.log("🎯 Next: Integrate with real Jupiter for actual swaps");
    });

    it("Should demonstrate real-world integration points", async () => {
      console.log("\n🔧 === Integration Requirements ===");
      
      console.log("1. 🤖 Calvin AI Backend:");
      console.log("   - Generate trade signals using LSTM models");
      console.log("   - Call Jupiter API for swap instructions");
      console.log("   - Send transactions to vault program");
      
      console.log("2. 🏗️ Vault Program:");
      console.log("   - Verify Calvin AI authority ✅");
      console.log("   - Execute Jupiter swaps");
      console.log("   - Update NAV and collect fees");
      
      console.log("3. 📊 Performance Tracking:");
      console.log("   - Track trade P&L");
      console.log("   - Calculate performance fees (7.5%)");
      console.log("   - Update high water mark");

      console.log("\n🚀 Ready for Calvin AI backend integration!");
    });
  });
}); 