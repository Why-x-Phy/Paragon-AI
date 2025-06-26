'use client';

import { useState } from 'react';
import { useVault } from '@/hooks/useVault';
import Modal from '@/components/UI/Modal';
import Button from '@/components/UI/Button';
import Input from '@/components/UI/Input';

export default function StakeModal({ isOpen, onClose }) {
  const { 
    userStakeInfo, 
    userVaultPosition,
    userTokenBalances,
    stakeCalvin, 
    unstakeCalvin,
    txStates,
    canUnstake,
    tierInfo
  } = useVault();
  
  const [amount, setAmount] = useState('');
  const [operation, setOperation] = useState('stake'); // 'stake' or 'unstake'
  const [error, setError] = useState('');

  const handleStake = async () => {
    setError('');
    try {
      const amountNum = parseFloat(amount);
      
      // Validation
      if (!amountNum || amountNum <= 0) {
        setError('Please enter a valid amount');
        return;
      }

      const walletCalvin = userTokenBalances ? parseFloat(userTokenBalances.calvinFormatted) : 0;
      if (amountNum > walletCalvin) {
        setError(`Insufficient CALVIN balance. You have ${walletCalvin.toFixed(3)} CALVIN`);
        return;
      }

      // Execute stake transaction
      await stakeCalvin(amountNum);
      
      // Close modal on success
      setAmount('');
      onClose();
      
    } catch (err) {
      setError(err.message || 'Transaction failed');
    }
  };

  const handleUnstake = async () => {
    setError('');
    try {
      const amountNum = parseFloat(amount);
      
      // Validation
      if (!amountNum || amountNum <= 0) {
        setError('Please enter a valid amount');
        return;
      }

      const stakedCalvin = userStakeInfo ? parseFloat(userStakeInfo.totalStakedFormatted) : 0;
      if (amountNum > stakedCalvin) {
        setError(`Maximum unstake amount is ${stakedCalvin.toFixed(3)} CALVIN`);
        return;
      }

      if (!canUnstake) {
        setError('You must withdraw all vault shares before unstaking CALVIN');
        return;
      }

      // Execute unstake transaction
      await unstakeCalvin(amountNum);
      
      // Close modal on success
      setAmount('');
      onClose();
      
    } catch (err) {
      setError(err.message || 'Transaction failed');
    }
  };

  const handleClose = () => {
    setAmount('');
    setError('');
    setOperation('stake');
    onClose();
  };

  const setMaxStake = () => {
    if (userTokenBalances) {
      setAmount(userTokenBalances.calvinFormatted);
    }
  };

  const setMaxUnstake = () => {
    if (userStakeInfo) {
      setAmount(userStakeInfo.totalStakedFormatted);
    }
  };

  const walletCalvin = userTokenBalances ? parseFloat(userTokenBalances.calvinFormatted) : 0;
  const stakedCalvin = userStakeInfo ? parseFloat(userStakeInfo.totalStakedFormatted) : 0;
  // Use raw shares value to detect even very small amounts
  const hasVaultShares = userVaultPosition && parseFloat(userVaultPosition.shares || '0') > 0;

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={operation === 'stake' ? 'Stake CALVIN' : 'Unstake CALVIN'}
      icon="/steak.svg"
    >
      <div className="flex flex-col gap-6">
        {/* Operation Selector */}
        <div className="flex gap-2 bg-black/50 rounded-lg p-1">
          <button
            className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
              operation === 'stake' 
                ? 'bg-[#B73E15] text-white' 
                : 'text-white/60 hover:text-white'
            }`}
            onClick={() => setOperation('stake')}
          >
            Stake
          </button>
          <button
            className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
              operation === 'unstake' 
                ? 'bg-[#B73E15] text-white' 
                : 'text-white/60 hover:text-white'
            }`}
            onClick={() => setOperation('unstake')}
          >
            Unstake
          </button>
        </div>

        {/* Balance Information */}
        <div className="bg-[#0A2519]/50 rounded-lg p-4 space-y-3">
          <h3 className="text-white font-semibold">Your Balances</h3>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-white/60">CALVIN in Wallet:</span>
              <span className="text-white">{walletCalvin.toFixed(3)} CALVIN</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/60">CALVIN Staked:</span>
              <span className="text-white">{stakedCalvin.toFixed(3)} CALVIN</span>
            </div>
            {tierInfo && (
              <div className="flex justify-between">
                <span className="text-white/60">Current Tier:</span>
                <span className="text-[#B73E15]">{tierInfo.name}</span>
              </div>
            )}
          </div>
        </div>

        {/* Vault shares warning for unstaking */}
        {operation === 'unstake' && hasVaultShares && (
          <div className="bg-yellow-500/20 border border-yellow-500/30 rounded-lg p-4">
            <div className="flex items-start gap-3">
              <div className="text-yellow-400 text-xl">⚠️</div>
              <div>
                <h4 className="text-yellow-200 font-semibold">Cannot Unstake</h4>
                <p className="text-yellow-200/80 text-sm mt-1">
                  You have {userVaultPosition.sharesFormatted} vCALVIN shares. 
                  You must withdraw all vault shares before unstaking CALVIN tokens.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Amount Input */}
        <div className="space-y-4">
          <div>
            <div className="flex justify-between items-center mb-2">
              <label className="block text-sm font-medium text-white">
                Amount to {operation === 'stake' ? 'Stake' : 'Unstake'}
              </label>
              <button
                type="button"
                onClick={operation === 'stake' ? setMaxStake : setMaxUnstake}
                className="text-[#B73E15] text-sm hover:underline"
                disabled={operation === 'unstake' && !canUnstake}
              >
                Max: {operation === 'stake' ? walletCalvin.toFixed(3) : stakedCalvin.toFixed(3)} CALVIN
              </button>
            </div>
            <Input
              type="number"
              step="0.000001"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.000000"
              disabled={operation === 'unstake' && !canUnstake}
              className="w-full"
            />
          </div>

          {/* Transaction Preview */}
          {amount && parseFloat(amount) > 0 && (
            <div className="bg-[#0A2519]/50 rounded-lg p-4 space-y-2">
              <h4 className="text-white font-semibold">Transaction Preview</h4>
              <div className="flex justify-between text-sm">
                <span className="text-white/60">{operation === 'stake' ? 'Staking' : 'Unstaking'}:</span>
                <span className="text-white">{parseFloat(amount).toFixed(6)} CALVIN</span>
              </div>
              {operation === 'stake' && (
                <div className="flex justify-between text-sm">
                  <span className="text-white/60">New Total Staked:</span>
                  <span className="text-white">{(stakedCalvin + parseFloat(amount)).toFixed(6)} CALVIN</span>
                </div>
              )}
              {operation === 'unstake' && (
                <div className="flex justify-between text-sm">
                  <span className="text-white/60">Remaining Staked:</span>
                  <span className="text-white">{(stakedCalvin - parseFloat(amount)).toFixed(6)} CALVIN</span>
                </div>
              )}
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="bg-red-500/20 border border-red-500/30 rounded-lg p-3">
              <p className="text-red-200 text-sm">{error}</p>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex gap-3">
            <Button
              variant="secondary"
              className="flex-1"
              onClick={handleClose}
              disabled={txStates[operation] === 'pending'}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              className="flex-1"
              onClick={operation === 'stake' ? handleStake : handleUnstake}
              loading={txStates[operation] === 'pending'}
              disabled={
                !amount || 
                parseFloat(amount) <= 0 || 
                txStates[operation] === 'pending' ||
                (operation === 'unstake' && !canUnstake)
              }
            >
              {txStates[operation] === 'pending' 
                ? `${operation === 'stake' ? 'Staking' : 'Unstaking'}...` 
                : `${operation === 'stake' ? 'Stake' : 'Unstake'} CALVIN`
              }
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
} 