'use client';

import { useState } from 'react';
import Modal from '@/components/UI/Modal';
import BalanceCard from '@/components/BalanceCard';
import Button from '@/components/UI/Button';
import { useVaultData } from '@/hooks/useVaultData';

export default function WithdrawModal({ isOpen, onClose }) {
  const [amount, setAmount] = useState('');
  const { vaultData } = useVaultData();
  
  const balances = {
    title: 'Your Balance',
    balances: [
      { label: '$USDC Locked', amount: vaultData.userBalance.balances[1].amount },
      { label: '$USDC in Wallet', amount: 5643 }
    ]
  };

  const handleWithdraw = async () => {
    try {
      // TODO: Add validation
      if (!amount || Number(amount) <= 0) {
        alert('Please enter a valid amount');
        return;
      }

      // TODO: Replace with actual contract call
      console.log('Withdrawing:', amount, 'USDC');
      // const tx = await vaultContract.withdraw(amount);
      // await tx.wait();
      
      setAmount('');
      onClose();
    } catch (error) {
      console.error('Withdrawal failed:', error);
      alert('Failed to withdraw. Please try again.');
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
                >
                Withdraw USDC
                </Button>
            </div>
        </div>
    </Modal>
  );
} 