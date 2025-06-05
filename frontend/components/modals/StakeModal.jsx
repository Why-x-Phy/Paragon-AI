'use client';

import { useState } from 'react';
import Modal from '@/components/ui/Modal';
import BalanceCard from '@/components/BalanceCard';
import Button from '@/components/ui/Button';
import { useVaultData } from '@/hooks/useVaultData';

export default function StakeModal({ isOpen, onClose }) {
  const [amount, setAmount] = useState('');
  const { vaultData } = useVaultData();
  
  const balances = {
    title: 'Your Balance',
    balances: [
      { label: '$CALVIN Staked', amount: vaultData.userBalance.balances[0].amount },
      { label: '$CALVIN in Wallet', amount: '5,000,000' }
    ],
    extraInfo: 'Private vault unlocked!'
  };

  const handleStake = async () => {
    try {
      if (!amount || Number(amount) <= 0) {
        alert('Please enter a valid amount');
        return;
      }

      // TODO: Replace with actual contract call
      console.log('Staking:', amount, 'CALVIN');
      // const tx = await vaultContract.stake(amount);
      // await tx.wait();
      
      setAmount('');
      onClose();
    } catch (error) {
      console.error('Staking failed:', error);
      alert('Failed to stake. Please try again.');
    }
  };

  const handleUnstake = async () => {
    try {
      if (!amount || Number(amount) <= 0) {
        alert('Please enter a valid amount');
        return;
      }

      // TODO: Replace with actual contract call
      console.log('Unstaking:', amount, 'CALVIN');
      // const tx = await vaultContract.unstake(amount);
      // await tx.wait();
      
      setAmount('');
      onClose();
    } catch (error) {
      console.error('Unstaking failed:', error);
      alert('Failed to unstake. Please try again.');
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Stake $CALVIN"
      icon="/steak.svg"
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
                
                <div className="flex gap-2">
                    <Button 
                        variant="primary" 
                        className="flex-1 py-3"
                        textSize="text-lg"
                        onClick={handleStake}
                    >
                        Stake
                    </Button>
                    <Button 
                        variant="secondary" 
                        className="flex-1 py-3"
                        textSize="text-lg"
                        onClick={handleUnstake}
                    >
                        Unstake
                    </Button>
                </div>
            </div>
        </div>
    </Modal>
  );
} 