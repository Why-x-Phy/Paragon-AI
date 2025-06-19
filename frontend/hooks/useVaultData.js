'use client';

import { useState, useEffect } from 'react';
import { UI } from '@/constants';
import { VaultClient } from '@/lib/vault-client';
import { useWallet } from '@solana/wallet-adapter-react';

// Real vault data hook - replaces mock data with smart contract calls
export const useVaultData = () => {
  const { wallet, connected } = useWallet();
  const [vaultData, setVaultData] = useState({
    vaultBalance: {
      title: "Vault's Balance",
      balances: [
        { label: '$CALVIN Staked', amount: '0.000' },
        { label: '$USDC Locked', amount: '0.000' }
      ]
    },
    userBalance: {
      title: 'Your Balance',
      balances: [
        { label: '$CALVIN Staked', amount: '0.000' },
        { label: '$USDC Locked', amount: '0.000' }
      ]
    },
    vaultProfit: {
      title: 'Vault Pnl (Monthly)',
      profit: {
        label: '$USDC:',
        value: 0,
        percentage: 0
      }
    },
    userProfit: {
      title: 'Your Pnl (Monthly)',
      profit: {
        label: '$USDC:',
        value: 0,
        percentage: 0
      }
    }
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async () => {
    try {
      setIsLoading(true);
      setError(null);

      if (!connected || !wallet?.adapter?.publicKey) {
        // If wallet not connected, show default values
        setVaultData(prev => ({
          ...prev,
          userBalance: {
            title: 'Your Balance',
            balances: [
              { label: '$CALVIN Staked', amount: '0.000' },
              { label: '$USDC Locked', amount: '0.000' }
            ]
          },
          userProfit: {
            title: 'Your Pnl (Monthly)',
            profit: {
              label: '$USDC:',
              value: 0,
              percentage: 0
            }
          }
        }));
        return;
      }

      // Initialize vault client
      const vaultClient = new VaultClient(wallet.adapter, null);
      await vaultClient.initialize();

      // Fetch vault statistics (total staked CALVIN and USDC)
      const vaultStats = await vaultClient.getVaultStats();
      
      // Fetch user's staking information
      const userStakeInfo = await vaultClient.getUserStakeInfo();
      
      // Fetch user's vault position
      const userVaultPosition = await vaultClient.getUserVaultPosition();

      // Calculate vault balance data
      const vaultBalance = {
        title: "Vault's Balance",
        balances: [
          { 
            label: '$CALVIN Staked', 
            amount: formatNumber(parseFloat(vaultStats.totalSharesFormatted || '0'))
          },
          { 
            label: '$USDC Locked', 
            amount: formatNumber(parseFloat(vaultStats.totalUsdcFormatted || '0'))
          }
        ]
      };

      // Calculate user balance data
      const userBalance = {
        title: 'Your Balance',
        balances: [
          { 
            label: '$CALVIN Staked', 
            amount: formatNumber(parseFloat(userStakeInfo?.totalStakedFormatted || '0'))
          },
          { 
            label: '$USDC Locked', 
            amount: formatNumber(parseFloat(userVaultPosition?.usdcValueFormatted || '0'))
          }
        ]
      };

      // Calculate vault profit (simplified - based on share price vs 1.0)
      const sharePrice = parseFloat(vaultStats.sharePriceFormatted || '1.0');
      const vaultProfitPct = ((sharePrice - 1.0) / 1.0) * 100;
      const vaultProfitUsdc = parseFloat(vaultStats.totalUsdcFormatted || '0') * (vaultProfitPct / 100);

      const vaultProfit = {
        title: 'Vault Pnl (Monthly)',
        profit: {
          label: '$USDC:',
          value: Math.round(vaultProfitUsdc),
          percentage: Math.round(vaultProfitPct * 100) / 100
        }
      };

      // Calculate user profit (based on user's position and vault performance)
      const userUsdcValue = parseFloat(userVaultPosition?.usdcValueFormatted || '0');
      const userProfitUsdc = userUsdcValue * (vaultProfitPct / 100);
      const userProfitPct = vaultProfitPct; // Same as vault performance

      const userProfit = {
        title: 'Your Pnl (Monthly)',
        profit: {
          label: '$USDC:',
          value: Math.round(userProfitUsdc),
          percentage: Math.round(userProfitPct * 100) / 100
        }
      };

      // Update state with real data
      setVaultData({
        vaultBalance,
        userBalance,
        vaultProfit,
        userProfit
      });

      console.log('✅ Vault data fetched successfully:', {
        vaultStats,
        userStakeInfo,
        userVaultPosition
      });

    } catch (err) {
      console.error('❌ Error fetching vault data:', err);
      setError(err.message);
      
      // On error, keep existing data but show error state
      // Don't reset to zeros to avoid UI flashing
    } finally {
      setIsLoading(false);
    }
  };

  // Helper function to format numbers with proper decimals
  const formatNumber = (num) => {
    if (num === 0) return '0.000';
    if (num < 0.001) return '< 0.001';
    if (num >= 1000000) return (num / 1000000).toFixed(2) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(2) + 'K';
    return num.toFixed(3);
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, UI.REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [connected, wallet?.adapter?.publicKey?.toString()]);

  return { vaultData, isLoading, error, refetch: fetchData };
}; 