'use client';

import { useState } from 'react';
import Modal from '@/components/UI/Modal';
import BalanceCard from '@/components/BalanceCard';
import Button from '@/components/UI/Button';
import { useVaultData } from '@/hooks/useVaultData';

export default function DepositModal({ isOpen, onClose }) {
  const [amount, setAmount] = useState('');
  const { vaultData } = useVaultData();
  
  const balances = {
    title: 'Your Balance',
    balances: [
      { label: '$USDC Locked', amount: vaultData.userBalance.balances[1].amount },
      { label: '$USDC in Wallet', amount: 5643 }
    ]
  };

  const handleDeposit = async () => {
    try {
      // TODO: Add validation
      if (!amount || Number(amount) <= 0) {
        alert('Please enter a valid amount');
        return;
      }

      // TODO: Replace with actual contract call
      console.log('Depositing:', amount, 'USDC');
      // const tx = await vaultContract.deposit(amount);
      // await tx.wait();
      
      setAmount('');
      onClose();
    } catch (error) {
      console.error('Deposit failed:', error);
      alert('Failed to deposit. Please try again.');
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Deposit USDC"
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
                    variant="primary" 
                    className="w-full" 
                    icon="/deposit.svg"
                    textSize="text-lg"
                    onClick={handleDeposit}
                >
                Deposit USDC
                </Button>
            </div>
        </div>
    </Modal>
  );
} 