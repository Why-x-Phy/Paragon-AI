'use client';

import { useWallet } from '@solana/wallet-adapter-react';
import BalanceCard from './BalanceCard';
import { useVault } from '@/hooks/useVault';
import { toast } from 'sonner';

export default function BalanceSection() {
  const { connected } = useWallet();
  const { 
    userStakeInfo,
    userVaultPosition,
    userTokenBalances,
    vaultStats,
    loading,
    refreshing,
    error,
    vaultClient,
    refreshData
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

  // Calculate NAV age for display
  const formatNavAge = (seconds) => {
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  };

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

      {/* NAV Status Indicator */}
      {vaultStats && (
        <div className="flex items-center justify-center gap-2 text-sm">
          <div className={`flex items-center gap-2 px-3 py-1 rounded-full ${
            vaultStats.navIsStale 
              ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' 
              : 'bg-green-500/20 text-green-400 border border-green-500/30'
          }`}>
            <div className={`w-2 h-2 rounded-full ${
              vaultStats.navIsStale ? 'bg-yellow-400' : 'bg-green-400'
            } animate-pulse`}></div>
            <span>
              NAV: {vaultStats.navIsStale ? 'Stale' : 'Fresh'} 
              ({formatNavAge(vaultStats.navAge)})
            </span>
          </div>
          {vaultStats.navIsStale && (
            <div className="flex items-center gap-2">
              <p className="text-yellow-400 text-xs">
                Auto-updates on deposit/withdraw
              </p>
              <button
                onClick={async () => {
                  try {
                    await vaultClient?.refreshNav();
                    await refreshData();
                    toast.success('NAV refreshed!');
                  } catch (error) {
                    toast.error('Failed to refresh NAV');
                  }
                }}
                className="text-xs px-2 py-0.5 bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-400 rounded transition-colors"
                title="Manually refresh NAV (costs transaction fees)"
              >
                Refresh Now
              </button>
            </div>
          )}
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