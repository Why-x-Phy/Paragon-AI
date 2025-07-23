/**
 * useVault Hook - React hook for Calvin Vault integration
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { Connection } from '@solana/web3.js';
import { VaultClient } from '@/lib/vault-client';
import { CONTRACTS, UI } from '@/constants';
import { toast } from 'sonner';

export const useVault = () => {
  const wallet = useWallet();
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  
  // User data state
  const [userStakeInfo, setUserStakeInfo] = useState(null);
  const [userVaultPosition, setUserVaultPosition] = useState(null);
  const [userTokenBalances, setUserTokenBalances] = useState(null);
  const [vaultStats, setVaultStats] = useState(null);
  const [totalStakedCalvin, setTotalStakedCalvin] = useState(null);
  
  // Transaction states
  const [txStates, setTxStates] = useState({
    stake: UI.TX_IDLE,
    unstake: UI.TX_IDLE,
    deposit: UI.TX_IDLE,
    withdraw: UI.TX_IDLE,
  });

  // Create vault client instance
  const vaultClient = useMemo(() => {
    if (!wallet) return null;
    // Create connection with versioned transaction support
    // This is critical for Pyth price feeds to work correctly
    const connection = new Connection(CONTRACTS.RPC_ENDPOINT, {
      commitment: CONTRACTS.COMMITMENT,
      maxSupportedTransactionVersion: 0,
    });
    return new VaultClient(wallet, connection);
  }, [wallet]);

  // Helper to update transaction state
  const updateTxState = useCallback((action, state) => {
    setTxStates(prev => ({ ...prev, [action]: state }));
  }, []);

  // Fetch user data
  const fetchUserData = useCallback(async () => {
    if (!vaultClient || !wallet.connected) {
      setUserStakeInfo(null);
      setUserVaultPosition(null);
      setUserTokenBalances(null);
      return;
    }

    try {
      setError(null);
      const [stakeInfo, vaultPosition, tokenBalances] = await Promise.all([
        vaultClient.getUserStakeInfo(),
        vaultClient.getUserVaultPosition(),
        vaultClient.getUserTokenBalances(),
      ]);

      setUserStakeInfo(stakeInfo);
      setUserVaultPosition(vaultPosition);
      setUserTokenBalances(tokenBalances);
    } catch (err) {
      console.error('Error fetching user data:', err);
      setError(err.message);
    }
  }, [vaultClient, wallet.connected]);

  // Fetch vault statistics
  const fetchVaultStats = useCallback(async () => {
    if (!vaultClient) return;

    try {
      const stats = await vaultClient.getVaultStats();
      setVaultStats(stats);
    } catch (err) {
      console.error('Error fetching vault stats:', err);
      // Don't set error for vault stats as it's less critical
    }
  }, [vaultClient]);

  // Fetch total staked Calvin tokens
  const fetchTotalStakedCalvin = useCallback(async () => {
    if (!vaultClient) return;

    try {
      const totalStaked = await vaultClient.getTotalStakedCalvin();
      setTotalStakedCalvin(totalStaked);
    } catch (err) {
      console.error('Error fetching total staked Calvin:', err);
      // Don't set error for total staked as it's less critical
    }
  }, [vaultClient]);

  // Refresh all data
  const refreshData = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([fetchUserData(), fetchVaultStats(), fetchTotalStakedCalvin()]);
    } finally {
      setRefreshing(false);
    }
  }, [fetchUserData, fetchVaultStats, fetchTotalStakedCalvin]);

  // Stake CALVIN tokens
  const stakeCalvin = useCallback(async (amount) => {
    if (!vaultClient || !wallet.connected) {
      throw new Error('Wallet not connected');
    }

    // Only check for token balance data (needed for staking validation)
    // We don't need vault state since staking only uses the Staking Program
    if (!userTokenBalances) {
      throw new Error('Token balance data not loaded yet - please wait');
    }

    updateTxState('stake', UI.TX_PENDING);
    try {
      const signature = await vaultClient.stakeCalvin(amount);
      updateTxState('stake', UI.TX_SUCCESS);
      
      toast.success('CALVIN tokens staked successfully!', {
        description: `Staked ${amount} CALVIN tokens`,
        action: signature ? {
          label: 'View Transaction',
          onClick: () => window.open(`https://explorer.solana.com/tx/${signature}?cluster=mainnet`, '_blank')
        } : undefined
      });

      // Refresh data after successful transaction
      await fetchUserData();
      return signature;
    } catch (err) {
      updateTxState('stake', UI.TX_ERROR);
      console.error('Error staking CALVIN:', err);
      
      toast.error('Failed to stake CALVIN tokens', {
        description: err.message || 'Transaction failed'
      });
      
      throw err;
    } finally {
      // Reset state after delay
      setTimeout(() => updateTxState('stake', UI.TX_IDLE), 3000);
    }
  }, [vaultClient, wallet.connected, fetchUserData, updateTxState, userTokenBalances]);

  // Unstake CALVIN tokens
  const unstakeCalvin = useCallback(async (amount) => {
    if (!vaultClient || !wallet.connected) {
      throw new Error('Wallet not connected');
    }

    updateTxState('unstake', UI.TX_PENDING);
    try {
      const signature = await vaultClient.unstakeCalvin(amount);
      updateTxState('unstake', UI.TX_SUCCESS);
      
      toast.success('CALVIN tokens unstaked successfully!', {
        description: `Unstaked ${amount} CALVIN tokens`,
        action: signature ? {
          label: 'View Transaction',
          onClick: () => window.open(`https://explorer.solana.com/tx/${signature}?cluster=mainnet`, '_blank')
        } : undefined
      });

      // Refresh data after successful transaction
      await fetchUserData();
      return signature;
    } catch (err) {
      updateTxState('unstake', UI.TX_ERROR);
      console.error('Error unstaking CALVIN:', err);
      
      toast.error('Failed to unstake CALVIN tokens', {
        description: err.message || 'Transaction failed'
      });
      
      throw err;
    } finally {
      // Reset state after delay
      setTimeout(() => updateTxState('unstake', UI.TX_IDLE), 3000);
    }
  }, [vaultClient, wallet.connected, fetchUserData, updateTxState]);

  // Deposit USDC to vault
  const depositUsdc = useCallback(async (amount) => {
    if (!vaultClient || !wallet.connected) {
      throw new Error('Wallet not connected');
    }

    updateTxState('deposit', UI.TX_PENDING);
    try {
      const signature = await vaultClient.depositUsdc(amount);
      updateTxState('deposit', UI.TX_SUCCESS);
      
      toast.success('USDC deposited successfully!', {
        description: `Deposited ${amount} USDC to vault`,
        action: signature ? {
          label: 'View Transaction',
          onClick: () => window.open(`https://explorer.solana.com/tx/${signature}?cluster=mainnet`, '_blank')
        } : undefined
      });

      // Refresh data after successful transaction
      await Promise.all([fetchUserData(), fetchVaultStats()]);
      return signature;
    } catch (err) {
      updateTxState('deposit', UI.TX_ERROR);
      console.error('Error depositing USDC:', err);
      
      toast.error('Failed to deposit USDC', {
        description: err.message || 'Transaction failed'
      });
      
      throw err;
    } finally {
      // Reset state after delay
      setTimeout(() => updateTxState('deposit', UI.TX_IDLE), 3000);
    }
  }, [vaultClient, wallet.connected, fetchUserData, fetchVaultStats, updateTxState]);

  // Withdraw USDC from vault
  const withdrawUsdc = useCallback(async (shares) => {
    if (!vaultClient || !wallet.connected) {
      throw new Error('Wallet not connected');
    }

    updateTxState('withdraw', UI.TX_PENDING);
    try {
      const signature = await vaultClient.withdrawUsdc(shares);
      updateTxState('withdraw', UI.TX_SUCCESS);
      
      toast.success('USDC withdrawn successfully!', {
        description: `Withdrew ${shares} shares from vault`,
        action: signature ? {
          label: 'View Transaction',
          onClick: () => window.open(`https://explorer.solana.com/tx/${signature}?cluster=mainnet`, '_blank')
        } : undefined
      });

      // Refresh data after successful transaction
      await Promise.all([fetchUserData(), fetchVaultStats()]);
      return signature;
    } catch (err) {
      updateTxState('withdraw', UI.TX_ERROR);
      console.error('Error withdrawing USDC:', err);
      
      toast.error('Failed to withdraw USDC', {
        description: err.message || 'Transaction failed'
      });
      
      throw err;
    } finally {
      // Reset state after delay
      setTimeout(() => updateTxState('withdraw', UI.TX_IDLE), 3000);
    }
  }, [vaultClient, wallet.connected, fetchUserData, fetchVaultStats, updateTxState]);

  // Check if user can deposit based on tier and current position
  const canDeposit = useMemo(() => {
    if (!userStakeInfo?.tier || !userVaultPosition) return false;
    
    if (!vaultClient) return false;
    
    const currentUsdcValue = parseFloat(userVaultPosition.usdcValueFormatted);
    return (newAmount) => vaultClient.canUserDeposit(userStakeInfo.tier, currentUsdcValue, newAmount);
  }, [userStakeInfo, userVaultPosition, vaultClient]);

  // Check if user can unstake (must have zero vault shares)
  const canUnstake = useMemo(() => {
    if (!userVaultPosition) return false;
    // Use raw shares value to avoid precision issues with very small amounts
    return parseFloat(userVaultPosition.shares || '0') === 0;
  }, [userVaultPosition]);

  // Calculate user's tier info
  const tierInfo = useMemo(() => {
    if (!userStakeInfo?.tier) return null;
    
    return {
      name: userStakeInfo.tier.name,
      role: userStakeInfo.tier.role,
      depositCap: userStakeInfo.tier.depositCap,
      currentDeposits: userVaultPosition ? parseFloat(userVaultPosition.usdcValueFormatted) : 0,
      remainingCap: userStakeInfo.tier.depositCap ? 
        Math.max(0, userStakeInfo.tier.depositCap - (userVaultPosition ? parseFloat(userVaultPosition.usdcValueFormatted) : 0)) :
        null
    };
  }, [userStakeInfo, userVaultPosition]);

  // Auto-fetch data when wallet connects
  useEffect(() => {
    if (wallet.connected && vaultClient) {
      fetchUserData();
      fetchVaultStats();
      fetchTotalStakedCalvin();
      
      // Don't auto-refresh NAV - users would have to pay fees
      // Instead, NAV will be refreshed automatically when needed (on deposits/withdrawals)
    }
  }, [wallet.connected, vaultClient, fetchUserData, fetchVaultStats, fetchTotalStakedCalvin]);

  // Auto-refresh data periodically
  useEffect(() => {
    if (!wallet.connected || !vaultClient) return;

    const interval = setInterval(refreshData, UI.REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [wallet.connected, vaultClient, refreshData]);

  return {
    // Connection state
    connected: wallet.connected,
    loading,
    refreshing,
    error,
    
    // Data
    userStakeInfo,
    userVaultPosition,
    userTokenBalances,
    vaultStats,
    totalStakedCalvin,
    tierInfo,
    
    // Actions
    stakeCalvin,
    unstakeCalvin,
    depositUsdc,
    withdrawUsdc,
    refreshData,
    
    // Transaction states
    txStates,
    
    // Validation helpers
    canDeposit,
    canUnstake,
    
    // Utilities
    vaultClient
  };
}; 