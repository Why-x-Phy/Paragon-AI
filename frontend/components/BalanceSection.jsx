'use client';

import BalanceCard from './BalanceCard';
import { useVaultData } from '@/hooks/useVaultData';

export default function BalanceSection() {
  const { vaultData, isLoading, error } = useVaultData();

  if (isLoading) return <div className="text-white">Loading...</div>;
  if (error) return <div className="text-red-500">{error}</div>;

  return (
    <div className="flex flex-col gap-8 w-full max-w-4xl justify-center">
        <div className="flex flex-col md:flex-row gap-8 w-full max-w-4xl justify-center">
            <BalanceCard {...vaultData.vaultBalance} />
            <BalanceCard {...vaultData.userBalance} />
        </div>
        <div className="flex flex-col md:flex-row gap-8 w-full max-w-4xl justify-center">
            <BalanceCard {...vaultData.vaultProfit} />
            <BalanceCard {...vaultData.userProfit} />
        </div>
    </div>
  );
} 