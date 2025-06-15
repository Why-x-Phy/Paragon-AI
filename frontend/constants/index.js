// Mock data - will be replaced with smart contract calls
export const MOCK_DATA = {
  vaultBalance: {
    title: "Vault's Balance",
    balances: [
      { label: '$CALVIN Staked', amount: '1,000,000,000.000' },
      { label: '$USDC Locked', amount: '1,000,000.000' }
    ]
  },
  userBalance: {
    title: 'Your Balance',
    balances: [
      { label: '$CALVIN Staked', amount: '10,000.000' },
      { label: '$USDC Locked', amount: '10.000' }
    ]
  },
  vaultProfit: {
    title: 'Vault Pnl (Monthly)',
    profit: {
        label: '$USDC:',
        value: 2456000,
        percentage: 40
    }
  },
  userProfit: {
    title: 'Your Pnl (Monthly)',
    profit: {
        label: '$USDC:',
        value: 2654,
        percentage: 40
    }
  }
};

// Smart Contract Configuration - Using environment variables for deployed programs
export const CONTRACTS = {
  // Calvin Staking Program (deployed)
  CALVIN_STAKING_PROGRAM: process.env.NEXT_PUBLIC_CALVIN_STAKING_PROGRAM || 'GocZdo1RPcsQnbiQrFp6Ybgd3bWUp48Jd4wytN3QN3Vw',
  
  // Calvin Vault Program (deployed)
  CALVIN_VAULT_PROGRAM: process.env.NEXT_PUBLIC_CALVIN_VAULT_PROGRAM || '2nLsDVW67Qw5LXGvaTzUQ7xRxytY52APWJAz2c7aqqyJ',
  
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