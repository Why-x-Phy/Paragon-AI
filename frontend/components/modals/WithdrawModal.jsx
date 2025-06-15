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
  
  const balances = {
    title: 'Your Balance',
    balances: [
      { label: 'vCALVIN Shares', amount: availableShares.toFixed(3) },
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
      if (withdrawAmount > availableShares) {
        toast.error(`Cannot withdraw more than ${availableShares.toFixed(3)} shares`);
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
                <input
                    type="number"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="Please enter amount here"
                    className="w-full bg-black/75 rounded-[4px] p-3 text-white no-spinner"
                />
                
                <Button 
                    variant="secondary" 
                    className="w-full" 
                    icon="/withdraw.svg"
                    textSize="text-lg"
                    onClick={handleWithdraw}
                    loading={txStates.withdraw === 'pending'}
                    disabled={txStates.withdraw === 'pending' || availableShares === 0}
                >
                    {txStates.withdraw === 'pending' ? 'Withdrawing...' : 'Withdraw USDC'}
                </Button>
            </div>
        </div>
    </Modal>
  );
} 