'use client';

import { useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { useVault } from '@/hooks/useVault';
import DepositModal from '@/components/modals/DepositModal';
import WithdrawModal from '@/components/modals/WithdrawModal';
import StakeModal from '@/components/modals/StakeModal';
import Button from '@/components/UI/Button';

export default function ActionButtons() {
    const { connected } = useWallet();
    const { 
        userStakeInfo, 
        userVaultPosition, 
        tierInfo, 
        txStates 
    } = useVault();
    
    const [isDepositModalOpen, setIsDepositModalOpen] = useState(false);
    const [isWithdrawModalOpen, setIsWithdrawModalOpen] = useState(false);
    const [isStakeModalOpen, setIsStakeModalOpen] = useState(false);

    const handleDeposit = () => {
        setIsDepositModalOpen(true);
    }

    const handleWithdraw = () => {
        setIsWithdrawModalOpen(true);
    }

    const handleStake = () => {
        setIsStakeModalOpen(true);
    }

    // Show wallet connection message if not connected
    if (!connected) {
        return (
            <div className="flex flex-col gap-4 justify-center w-full mb-8">
                <div className="text-center text-white/60 py-8">
                    <p className="text-lg mb-2">Connect your wallet to access Calvin's vault</p>
                    <p className="text-sm">You'll need CALVIN tokens staked to deposit USDC</p>
                </div>
            </div>
        );
    }

    // Show staking requirement if user has no stake
    if (!userStakeInfo?.tier) {
        return (
            <div className="flex flex-col gap-4 w-full mb-8">
                <div className="text-center text-white/60 py-4">
                    <p className="text-lg mb-2">Stake CALVIN tokens to unlock vault access</p>
                    <p className="text-sm">Minimum 500K CALVIN required for Tier 3 access</p>
                </div>
                <Button 
                    className="w-full" 
                    variant="primary" 
                    icon="/stake.svg" 
                    textSize="sm:text-lg" 
                    onClick={handleStake}
                    loading={txStates.stake === 'pending'}
                    disabled={txStates.stake === 'pending'}
                >
                    {txStates.stake === 'pending' ? 'Staking...' : 'Stake CALVIN'}
                </Button>
                
                <StakeModal isOpen={isStakeModalOpen} onClose={() => setIsStakeModalOpen(false)} />
            </div>
        );
    }

    // Show main action buttons for qualified users
    const hasVaultShares = userVaultPosition && parseFloat(userVaultPosition.sharesFormatted) > 0;
    
    return (
        <>
            {/* Tier Info Display */}
            {tierInfo && (
                <div className="bg-[#B73E15]/20 border border-[#B73E15]/30 rounded-lg p-4 mb-6">
                    <div className="flex justify-between items-center">
                        <div>
                            <h3 className="text-white font-semibold">{tierInfo.name}</h3>
                            <p className="text-white/60 text-sm">{tierInfo.role}</p>
                        </div>
                        <div className="text-right">
                            <p className="text-white text-sm">
                                Deposits: ${tierInfo.currentDeposits.toFixed(2)}
                                {tierInfo.depositCap && ` / $${tierInfo.depositCap.toLocaleString()}`}
                            </p>
                            {tierInfo.remainingCap !== null && (
                                <p className="text-[#B73E15] text-xs">
                                    ${tierInfo.remainingCap.toFixed(2)} remaining
                                </p>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Primary Actions - Vault Operations */}
            <div className="flex gap-4 justify-between w-full mb-6">
                <Button 
                    className="flex-1" 
                    variant="primary" 
                    icon="/deposit.svg" 
                    textSize="sm:text-lg" 
                    onClick={handleDeposit}
                    loading={txStates.deposit === 'pending'}
                    disabled={txStates.deposit === 'pending' || !tierInfo}
                >
                    {txStates.deposit === 'pending' ? 'Depositing...' : 'Deposit USDC'}
                </Button>
                <Button 
                    className="flex-1" 
                    variant="secondary" 
                    icon="/withdraw.svg" 
                    textSize="sm:text-lg" 
                    onClick={handleWithdraw}
                    loading={txStates.withdraw === 'pending'}
                    disabled={txStates.withdraw === 'pending' || !hasVaultShares}
                >
                    {txStates.withdraw === 'pending' ? 'Withdrawing...' : 'Withdraw USDC'}
                </Button>
            </div>

            {/* Secondary Actions - Staking Operations */}
            <div className="flex gap-4 justify-between w-full mb-8">
                <Button 
                    className="flex-1" 
                    variant="outline" 
                    icon="/stake.svg" 
                    textSize="sm:text-base" 
                    onClick={handleStake}
                    loading={txStates.stake === 'pending' || txStates.unstake === 'pending'}
                    disabled={txStates.stake === 'pending' || txStates.unstake === 'pending'}
                >
                    {(txStates.stake === 'pending' || txStates.unstake === 'pending') ? 'Processing...' : 'Manage CALVIN'}
                </Button>
            </div>

            {/* Warning for unstaking constraint */}
            {hasVaultShares && (
                <div className="bg-yellow-500/20 border border-yellow-500/30 rounded-lg p-3 mb-4">
                    <p className="text-yellow-200 text-sm">
                        ⚠️ You must withdraw all vault shares before unstaking CALVIN tokens
                    </p>
                </div>
            )}
            
            {/* Modals */}
            <DepositModal isOpen={isDepositModalOpen} onClose={() => setIsDepositModalOpen(false)} />
            <WithdrawModal isOpen={isWithdrawModalOpen} onClose={() => setIsWithdrawModalOpen(false)} />
            <StakeModal isOpen={isStakeModalOpen} onClose={() => setIsStakeModalOpen(false)} />
        </>
    );
} 