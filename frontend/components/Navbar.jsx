'use client';

import { useState } from 'react';
import Image from 'next/image';
import Button from './UI/Button';
import StakeModal from './modals/StakeModal';
import WalletButton from './WalletButton';
import DiscordAuthButton from './DiscordAuthButton';

export default function Navbar() {
    const [isStakeModalOpen, setIsStakeModalOpen] = useState(false);

    const handleStake = () => {
        setIsStakeModalOpen(true);
    }

  return (
    <nav className="w-full flex flex-col lg:flex-row justify-between items-center gap-4">
      <div className="flex items-center gap-2">
        <Image src="/logo.svg" alt="Calvin's Vault" width={54} height={54} />
        <span className="text-white text-[32px] lg:text-[24px] xl:text-[32px] font-bold font-['Orbitron']">Calvin's Vault</span>
      </div>
      
      <div className="flex flex-col lg:flex-row gap-4 lg:gap-2 items-center">
        {/* Discord Authentication */}
        <div className="order-1 lg:order-1">
          <DiscordAuthButton />
        </div>
        
        {/* Stake & Wallet Controls */}
        <div className="flex gap-2 order-2 lg:order-2">
          <Button variant="secondary" icon="/stake.svg" onClick={handleStake}>
            Stake $CALVIN
          </Button>
          <WalletButton />
        </div>
      </div>
      
      <StakeModal isOpen={isStakeModalOpen} onClose={() => setIsStakeModalOpen(false)} />
    </nav>
  );
} 