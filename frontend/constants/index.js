// Smart Contract Configuration - Using environment variables for deployed programs
export const CONTRACTS = {
  // Calvin Staking Program (deployed) - FRESH DEVNET DEPLOYMENT
  CALVIN_STAKING_PROGRAM: process.env.NEXT_PUBLIC_CALVIN_STAKING_PROGRAM || 'FH8te8ebpGLRUc32pZHj4q6DUwzt3KykQYZyA4NQPsod',
  
  // Calvin Vault Program (deployed) - FRESH DEVNET DEPLOYMENT
  CALVIN_VAULT_PROGRAM: process.env.NEXT_PUBLIC_CALVIN_VAULT_PROGRAM || 'Evdjoh1AHQb6Ls1n7Td7buAiDA5ty7Ec8NCYt8eWEXFp',
  
  // Token Addresses
  CALVIN_TOKEN: process.env.NEXT_PUBLIC_CALVIN_TOKEN || 'CrWbUJ4kMgduYDVRK8bDXhNBHr8cScixi79nGdGejnb1',
  USDC: process.env.NEXT_PUBLIC_USDC_TOKEN || '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU',
  
  // Devnet Configuration
  RPC_ENDPOINT: process.env.NEXT_PUBLIC_RPC_ENDPOINT || 'https://api.devnet.solana.com',
  COMMITMENT: 'confirmed',
};

// Tier Configuration
export const TIERS = {
  VAULT_KEEPER: {
    name: 'Vault Keeper',
    minStake: 10_000_000,
    depositCap: null, // unlimited
    role: '@Vault Keeper'
  },
  TIER_2: {
    name: 'Tier 2',
    minStake: 2_000_000,
    depositCap: 5_000, // USDC
    role: '@Chain Warden'
  },
  TIER_3: {
    name: 'Tier 3',
    minStake: 500_000,
    depositCap: 1_000, // USDC
    role: '@Echo Cell'
  },
  LEGENDARY: {
    name: 'Legendary',
    minStake: 0,
    depositCap: null, // unlimited
    role: '@Founder'
  }
};

// Fee Configuration
export const FEES = {
  PERFORMANCE_FEE_BPS: 750, // 7.5%
  DEPOSIT_FEE_BPS: 250,     // 2.5%
  WITHDRAWAL_FEE_BPS: 0,    // 0%
};

// Action constants
export const ACTIONS = {
  STAKE: 'STAKE',
  UNSTAKE: 'UNSTAKE',
  DEPOSIT: 'DEPOSIT',
  WITHDRAW: 'WITHDRAW',
};

// UI Constants
export const UI = {
  MIN_STAKE_AMOUNT: 100,
  MIN_DEPOSIT_AMOUNT: 10,
  REFRESH_INTERVAL: 15000, // 15 seconds
  
  // Transaction States
  TX_PENDING: 'pending',
  TX_SUCCESS: 'success',
  TX_ERROR: 'error',
  TX_IDLE: 'idle',
}; 