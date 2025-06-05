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

// Contract addresses - to be updated with actual addresses
export const CONTRACTS = {
  CALVIN_TOKEN: '229vWzBTiUNdraYpVtSH9usTwwVxcyPDbBWf1zEPpump',
  VAULT: '0x...',
  USDC: 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
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
}; 