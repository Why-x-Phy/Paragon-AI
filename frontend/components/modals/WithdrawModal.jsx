'use client';

import { useState } from 'react';
import Modal from '@/components/UI/Modal';
import BalanceCard from '@/components/BalanceCard';
import Button from '@/components/UI/Button';
import { useVault } from '@/hooks/useVault';
import { toast } from 'sonner';

export default function WithdrawModal({ isOpen, onClose }) {
  const [amount, setAmount] = useState('');
  const { 
    userVaultPosition, 
    userTokenBalances, 
    vaultClient, 
    txStates, 
    refreshData 
  } = useVault();
  
  // Use formatted values with consistent precision
  const availableShares = userVaultPosition ? parseFloat(userVaultPosition.sharesFormatted) : 0;
  const availableUsdc = userVaultPosition ? parseFloat(userVaultPosition.usdcValueFormatted) : 0;
  const walletUsdc = userTokenBalances ? parseFloat(userTokenBalances.usdcFormatted) : 0;
  
  // Consistent formatting function for all share amounts (6 decimal places)
  const formatShares = (num) => {
    if (num === 0) return '0.000000';
    if (num < 0.000001) return '< 0.000001';
    return num.toFixed(6);
  };

  // Consistent formatting function for USDC amounts (2 decimal places)
  const formatUsdc = (num) => {
    if (num === 0) return '0.00';
    return num.toFixed(2);
  };
  
  const balances = {
    title: 'Your Balance',
    balances: [
      { label: 'vCALVIN Shares', amount: formatShares(availableShares) },
      { label: 'USDC Value', amount: `$${formatUsdc(availableUsdc)}` },
      { label: 'USDC in Wallet', amount: `$${formatUsdc(walletUsdc)}` }
    ]
  };

  const handleWithdraw = async () => {
    try {
      console.log('🏦 Withdraw button clicked, amount:', amount);
      
      // Validation
      if (!amount || Number(amount) <= 0) {
        toast.error('Please enter a valid amount');
        return;
      }

      const withdrawAmount = Number(amount);
      
      // Use appropriate epsilon for 6 decimal place precision
      const epsilon = 0.000001;
      if (withdrawAmount > (availableShares + epsilon)) {
        toast.error(`Cannot withdraw more than ${formatShares(availableShares)} shares`);
        return;
      }

      if (!vaultClient) {
        toast.error('Vault client not initialized');
        return;
      }

      console.log('🚀 Calling vaultClient.withdrawUsdc with:', withdrawAmount);
      
      // Call the actual withdraw function
      const signature = await vaultClient.withdrawUsdc(withdrawAmount);
      
      toast.success(`Withdrawal successful! Transaction: ${signature.slice(0, 8)}...`);
      
      // Refresh data and close modal
      await refreshData();
      setAmount('');
      onClose();
      
    } catch (error) {
      console.error('❌ Withdrawal failed:', error);
      toast.error(`Withdrawal failed: ${error.message || 'Unknown error'}`);
    }
  };

  // Function to set maximum available shares using the raw precision value
  const setMaxShares = () => {
    // Use the raw shares value and format it to 6 decimal places for maximum precision
    const rawShares = userVaultPosition?.shares || '0';
    const maxShares = (parseFloat(rawShares) / 1000000).toFixed(6); // Convert from raw to decimal with 6 places
    setAmount(maxShares);
  };

  // Check if user has any shares (use raw shares to detect even tiny amounts)
  const hasShares = userVaultPosition && parseFloat(userVaultPosition.shares || '0') > 0;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Withdraw USDC"
      icon="/usdc.svg"
    >
        <div className="flex flex-col gap-8">
            <BalanceCard {...balances} className="bg-black" />
            
            <div className="space-y-4">
                <div>
                    <div className="flex justify-between items-center mb-2">
                        <label className="block text-sm font-medium text-white">
                            Shares to Withdraw
                        </label>
                        <button
                            type="button"
                            onClick={setMaxShares}
                            className="text-[#B73E15] text-sm hover:underline"
                            disabled={!hasShares}
                        >
                            Max: {formatShares(availableShares)} shares
                        </button>
                    </div>
                <input
                    type="number"
                    step="0.000001"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="0.000000"
                    className="w-full bg-black/75 rounded-[4px] p-3 text-white no-spinner"
                />
                </div>
                
                <Button 
                    variant="secondary" 
                    className="w-full" 
                    icon="/withdraw.svg"
                    textSize="text-lg"
                    onClick={handleWithdraw}
                    loading={txStates.withdraw === 'pending'}
                    disabled={txStates.withdraw === 'pending' || !hasShares}
                >
                    {txStates.withdraw === 'pending' ? 'Withdrawing...' : 'Withdraw USDC'}
                </Button>
            </div>
        </div>
    </Modal>
  );
} 