'use client';

import { useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import Button from '@/components/UI/Button';
import { useClickOutside } from '@/hooks/useClickOutside';

require('@solana/wallet-adapter-react-ui/styles.css');

export default function WalletButton() {
  const { connected, publicKey, disconnect } = useWallet();
  const { setVisible } = useWalletModal();
  const [showDropdown, setShowDropdown] = useState(false);

  const dropdownRef = useClickOutside(() => setShowDropdown(false));

  const shortenAddress = (address) => {
    if (!address) return '';
    return `${address.toString().slice(0, 4)}...${address.toString().slice(-4)}`;
  };

  const handleButtonClick = () => {
    if (connected) {
      setShowDropdown(!showDropdown);
    } else {
      setVisible(true);
    }
  };

  const handleDisconnect = () => {
    disconnect();
    setShowDropdown(false);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <Button 
        variant={connected ? "secondary" : "primary"}
        icon="/wallet.svg"
        onClick={handleButtonClick}
      >
        {connected ? shortenAddress(publicKey) : 'Select Wallet'}
      </Button>

      {showDropdown && connected && (
        <div className="absolute right-0 mt-2 w-40 rounded-[4px] bg-[#0A2519] z-50 cursor-pointer">
          <div className="py-1">
            <button
              onClick={handleDisconnect}
              className="block w-full px-4 py-2 text-sm text-white hover:opacity-80 text-left cursor-pointer"
            >
              Disconnect
            </button>
          </div>
        </div>
      )}
    </div>
  );
}