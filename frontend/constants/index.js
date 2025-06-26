// Smart Contract Configuration - Using environment variables for deployed programs
export const CONTRACTS = {
  // Calvin Staking Program (deployed) - MAINNET DEPLOYMENT
  CALVIN_STAKING_PROGRAM: process.env.NEXT_PUBLIC_CALVIN_STAKING_PROGRAM || '8kMj6gYFVUC3Ya6qwu3tyaZweyXUUuR8t8aCtA47aX7W',
  
  // Calvin Vault Program (deployed) - MAINNET DEPLOYMENT
  CALVIN_VAULT_PROGRAM: process.env.NEXT_PUBLIC_CALVIN_VAULT_PROGRAM || 'tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z',
  
  // Token Addresses
  CALVIN_TOKEN: process.env.NEXT_PUBLIC_CALVIN_TOKEN || '229vWzBTiUNdraYpVtSH9usTwwVxcyPDbBWf1zEPpump',
  USDC: process.env.NEXT_PUBLIC_USDC_TOKEN || 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
  
  // Mainnet Configuration
  RPC_ENDPOINT: process.env.NEXT_PUBLIC_RPC_ENDPOINT || 'https://api.mainnet-beta.solana.com',
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
  REFRESH_INTERVAL: 30000, // 30 seconds to reduce Helius rate limits
  
  // Transaction States
  TX_PENDING: 'pending',
  TX_SUCCESS: 'success',
  TX_ERROR: 'error',
  TX_IDLE: 'idle',
}; 