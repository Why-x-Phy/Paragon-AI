'use client';

import { useWallet } from '@solana/wallet-adapter-react';
import BalanceCard from './BalanceCard';
import { useVault } from '@/hooks/useVault';

export default function BalanceSection() {
  const { connected } = useWallet();
  const { 
    userStakeInfo,
    userVaultPosition,
    userTokenBalances,
    vaultStats,
    loading,
    refreshing,
    error
  } = useVault();

  if (!connected) {
    return (
      <div className="flex flex-col gap-8 w-full max-w-4xl justify-center">
        <div className="text-center text-white/60 py-12">
          <p className="text-lg">Connect your wallet to view balances</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-8 w-full max-w-4xl justify-center">
        <div className="text-center text-white py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#B73E15] mx-auto"></div>
          <p className="mt-4">Loading vault data...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col gap-8 w-full max-w-4xl justify-center">
        <div className="text-center text-red-400 py-12">
          <p className="text-lg">Error loading vault data</p>
          <p className="text-sm mt-2">{error}</p>
        </div>
      </div>
    );
  }

  // Prepare vault balance data
  const vaultBalanceData = {
    title: "Vault's Balance",
    balances: [
      { 
        label: 'Total USDC Locked', 
        amount: vaultStats ? `${vaultStats.totalUsdcFormatted}` : '0.000'
      },
      { 
        label: 'Total vCALVIN Shares', 
        amount: vaultStats ? `${vaultStats.totalSharesFormatted}` : '0.000'
      }
    ]
  };

  // Prepare user balance data
  const userBalanceData = {
    title: 'Your Balances',
    balances: [
      { 
        label: 'CALVIN Staked', 
        amount: userStakeInfo ? `${userStakeInfo.totalStakedFormatted}` : '0.000'
      },
      { 
        label: 'USDC in Vault', 
        amount: userVaultPosition ? `${userVaultPosition.usdcValueFormatted}` : '0.000'
      }
    ]
  };

  // Prepare wallet balance data
  const walletBalanceData = {
    title: 'Your Wallet',
    balances: [
      { 
        label: 'CALVIN Balance', 
        amount: userTokenBalances ? `${userTokenBalances.calvinFormatted}` : '0.000'
      },
      { 
        label: 'USDC Balance', 
        amount: userTokenBalances ? `${userTokenBalances.usdcFormatted}` : '0.000'
      },
      { 
        label: 'Vault Pass Tokens', 
        amount: userTokenBalances ? `${userTokenBalances.vaultPassFormatted}` : '0'
      }
    ]
  };

  // Prepare vault shares data
  const vaultSharesData = {
    title: 'Your Vault Position',
    balances: [
      { 
        label: 'vCALVIN Shares', 
        amount: userVaultPosition ? `${userVaultPosition.sharesFormatted}` : '0.000'
      },
      { 
        label: 'Share Price (USDC)', 
        amount: vaultStats ? `${vaultStats.sharePriceFormatted}` : '1.000'
      }
    ]
  };

  return (
    <div className="flex flex-col gap-8 w-full max-w-4xl justify-center">
      {/* Refresh indicator */}
      {refreshing && (
        <div className="text-center text-white/60 py-2">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-[#B73E15] mx-auto"></div>
          <p className="text-xs mt-1">Refreshing data...</p>
        </div>
      )}

      {/* Vault Overview */}
      <div className="flex flex-col md:flex-row gap-8 w-full max-w-4xl justify-center">
        <BalanceCard {...vaultBalanceData} />
        <BalanceCard {...userBalanceData} />
      </div>

      {/* Detailed Balances */}
      <div className="flex flex-col md:flex-row gap-8 w-full max-w-4xl justify-center">
        <BalanceCard {...walletBalanceData} />
        <BalanceCard {...vaultSharesData} />
      </div>

      {/* Additional Info */}
      {userStakeInfo?.tier && (
        <div className="text-center text-white/60 text-sm">
          <p>Tier: {userStakeInfo.tier.name} • Role: {userStakeInfo.tier.role}</p>
          {userStakeInfo.tier.depositCap && (
            <p>Deposit Cap: ${userStakeInfo.tier.depositCap.toLocaleString()} USDC</p>
          )}
        </div>
      )}
    </div>
  );
} 