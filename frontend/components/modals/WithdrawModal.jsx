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
  
  // Calculate available shares to withdraw
  const availableShares = userVaultPosition ? parseFloat(userVaultPosition.sharesFormatted) : 0;
  const availableUsdc = userVaultPosition ? parseFloat(userVaultPosition.usdcValueFormatted) : 0;
  const walletUsdc = userTokenBalances ? parseFloat(userTokenBalances.usdcFormatted) : 0;
  
  // Helper function to format very small numbers with appropriate precision
  const formatSmallNumber = (num) => {
    if (num === 0) return '0.000';
    if (num < 0.000001) return '< 0.000001';
    if (num < 0.001) return num.toFixed(6);
    return num.toFixed(3);
  };
  
  const balances = {
    title: 'Your Balance',
    balances: [
      { label: 'vCALVIN Shares', amount: formatSmallNumber(availableShares) },
      { label: 'USDC Value', amount: `$${availableUsdc.toFixed(2)}` },
      { label: 'USDC in Wallet', amount: `$${walletUsdc.toFixed(2)}` }
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
      
      // Use a small epsilon for floating point comparison
      const epsilon = 0.000001;
      if (withdrawAmount > (availableShares + epsilon)) {
        toast.error(`Cannot withdraw more than ${formatSmallNumber(availableShares)} shares`);
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

  // Function to set maximum available shares
  const setMaxShares = () => {
    // Use the raw shares value with full precision to avoid rounding issues
    const rawShares = userVaultPosition?.shares ? (parseFloat(userVaultPosition.shares) / 1000000).toString() : '0';
    setAmount(rawShares);
  };

  // Check if user has any shares (even very small amounts)
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
                            Max: {formatSmallNumber(availableShares)} shares
                        </button>
                    </div>
                <input
                    type="number"
                        step="0.000001"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="Please enter amount here"
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