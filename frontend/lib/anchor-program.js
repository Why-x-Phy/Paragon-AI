/**
 * Anchor Program Interfaces for Calvin Staking and Vault Programs
 */

import { PublicKey } from '@solana/web3.js';
import { Program, AnchorProvider, BN } from '@coral-xyz/anchor';
import { CONTRACTS } from '@/constants';

// Import the actual generated IDLs
import CalvinStakingIDL from '../../onchain/target/idl/calvin_staking.json';
import CalvinVaultIDL from '../../onchain/target/idl/vault.json';

// Use the actual generated IDLs
export const CALVIN_STAKING_IDL = CalvinStakingIDL;
export const CALVIN_VAULT_IDL = CalvinVaultIDL;

// Helper functions to create program instances
export const getStakingProgram = (provider) => {
  return new Program(CALVIN_STAKING_IDL, provider);
};

export const getVaultProgram = (provider) => {
  return new Program(CALVIN_VAULT_IDL, provider);
};

// PDA derivation helpers
export const getStakeConfigPDA = () => {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("stake_config")],
    new PublicKey(CONTRACTS.CALVIN_STAKING_PROGRAM)
  );
};

export const getUserStakePDA = (userPublicKey) => {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("user_stake"), userPublicKey.toBuffer()],
    new PublicKey(CONTRACTS.CALVIN_STAKING_PROGRAM)
  );
};

export const getVaultPDA = (usdcMint) => {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("vault")],
    new PublicKey(CONTRACTS.CALVIN_VAULT_PROGRAM)
  );
};

export const getUserPositionPDA = (vaultPDA, userPublicKey) => {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("user_position"), userPublicKey.toBuffer(), vaultPDA.toBuffer()],
    new PublicKey(CONTRACTS.CALVIN_VAULT_PROGRAM)
  );
};

export const getGlobalVaultPassMintPDA = () => {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("vault_pass_mint")],
    new PublicKey(CONTRACTS.CALVIN_STAKING_PROGRAM)
  );
};

export const getUserVaultPassMintPDA = (userPublicKey) => {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("vault_pass_mint"), userPublicKey.toBuffer()],
    new PublicKey(CONTRACTS.CALVIN_STAKING_PROGRAM)
  );
}; 
