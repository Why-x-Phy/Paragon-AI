'use client';

import { useState } from 'react';
import Image from 'next/image';
import Button from './ui/Button';
import StakeModal from './modals/StakeModal';
import WalletButton from './WalletButton';

export default function Navbar() {
    const [isStakeModalOpen, setIsStakeModalOpen] = useState(false);

    const handleStake = () => {
        setIsStakeModalOpen(true);
    }

  return (
    <nav className="w-full flex flex-col md:flex-row justify-between items-center gap-8 lg:gap-16">
      <div className="flex items-center gap-2">
        <Image src="/logo.svg" alt="Calvin's Vault" width={54} height={54} />
        <span className="text-white text-[32px] font-bold font-['Orbitron']">Calvin's Vault</span>
      </div>
      
      <div className="flex gap-2">
        <Button variant="secondary" icon="/stake.svg" onClick={handleStake}>
          Stake $CALVIN
        </Button>
        <WalletButton />
      </div>
      <StakeModal isOpen={isStakeModalOpen} onClose={() => setIsStakeModalOpen(false)} />
    </nav>
  );
} 