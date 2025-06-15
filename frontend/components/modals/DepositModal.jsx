'use client';

import { useState } from 'react';
import Modal from '@/components/UI/Modal';
import BalanceCard from '@/components/BalanceCard';
import Button from '@/components/UI/Button';
import { useVault } from '@/hooks/useVault';

export default function DepositModal({ isOpen, onClose }) {
  const [amount, setAmount] = useState('');
  const { userTokenBalances, userVaultPosition, depositUsdc, txStates } = useVault();
  
  const balances = {
    title: 'Your Balance',
    balances: [
      { label: '$USDC Locked', amount: userVaultPosition?.usdcDepositedFormatted || '0' },
      { label: '$USDC in Wallet', amount: userTokenBalances?.usdcFormatted || '0' }
    ]
  };

  const handleDeposit = async () => {
    try {
      if (!amount || Number(amount) <= 0) {
        alert('Please enter a valid amount');
        return;
      }

      // Check if user has enough USDC
      const userUsdcBalance = parseFloat(userTokenBalances?.usdcFormatted || '0');
      if (userUsdcBalance < Number(amount)) {
        alert(`Insufficient USDC balance. You have ${userUsdcBalance} USDC`);
        return;
      }

      await depositUsdc(Number(amount));
      
      setAmount('');
      onClose();
    } catch (error) {
      console.error('Deposit failed:', error);
      // Error handling is done in the hook with toast notifications
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
                    disabled={txStates.deposit === 'pending'}
                >
                {txStates.deposit === 'pending' ? 'Depositing...' : 'Deposit USDC'}
                </Button>
            </div>
        </div>
    </Modal>
  );
} 