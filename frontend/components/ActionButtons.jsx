'use client';

import { useState } from 'react';
import DepositModal from '@/components/modals/DepositModal';
import WithdrawModal from '@/components/modals/WithdrawModal';
import Button from '@/components/ui/Button';

export default function ActionButtons() {
    const [isDepositModalOpen, setIsDepositModalOpen] = useState(false);
    const [isWithdrawModalOpen, setIsWithdrawModalOpen] = useState(false);

    const handleDeposit = () => {
        setIsDepositModalOpen(true);
    }

    const handleWithdraw = () => {
        setIsWithdrawModalOpen(true);
    }

  return (
    <>
        <div className="flex gap-4 justify-between w-full mb-8">
            <Button className="flex-1" variant="primary" icon="/deposit.svg" textSize="sm:text-lg" onClick={handleDeposit}>
                Deposit USDC
            </Button>
            <Button className="flex-1" variant="secondary" icon="/withdraw.svg" textSize="sm:text-lg" onClick={handleWithdraw}>
                Withdraw USDC
            </Button>
        </div>
        <DepositModal isOpen={isDepositModalOpen} onClose={() => setIsDepositModalOpen(false)} />
        <WithdrawModal isOpen={isWithdrawModalOpen} onClose={() => setIsWithdrawModalOpen(false)} />
    </>
  );
} 