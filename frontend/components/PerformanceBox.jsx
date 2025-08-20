import React, { useState, useEffect } from 'react'
import { usePerformance } from '../hooks/usePerformance'
import { usePublicVaultStats } from '../hooks/usePublicVaultStats'

const PerformanceBox = () => {
  const { performance, stats, loading: performanceLoading, error: performanceError } = usePerformance();
  const { vaultStats, totalStakedCalvin, loading: vaultLoading, error: vaultError } = usePublicVaultStats();

  // Combined loading state
  const loading = performanceLoading || vaultLoading;
  const error = performanceError || vaultError;

  // Check if vault data is still loading based on actual values being 0
  const isVaultStatsLoading = !vaultStats || vaultStats.totalUsdcFormatted === '0';
  const isTotalStakedLoading = !totalStakedCalvin || totalStakedCalvin.totalStakedFormatted === '0';

  // Helper function to format numbers with commas
  const formatNumber = (num) => {
    if (!num) return '0';
    return Number(num).toLocaleString();
  };

  // Animated loading component with Calvin AI themed messages
  const CalvinLoadingText = () => {
    const [messageIndex, setMessageIndex] = useState(0);
    const [dots, setDots] = useState('');

    const messages = [
      "gathering intel",
      "calculating attack vectors", 
      "decrypting cabal communications",
      "analyzing market patterns",
      "scanning blockchain data",
      "processing neural networks",
      "infiltrating data streams",
      "compiling intelligence reports"
    ];

    // Cycle through messages every 3.5 seconds
    useEffect(() => {
      const messageInterval = setInterval(() => {
        setMessageIndex((prev) => (prev + 1) % messages.length);
      }, 3500);

      return () => clearInterval(messageInterval);
    }, [messages.length]);

    // Animate dots every 500ms
    useEffect(() => {
      const dotsInterval = setInterval(() => {
        setDots((prev) => {
          if (prev === '...') return '';
          return prev + '.';
        });
      }, 500);

      return () => clearInterval(dotsInterval);
    }, []);

    return (
      <div className="flex items-center justify-center text-xs text-gray-400 font-mono text-center">
        <span className="animate-pulse">
          {messages[messageIndex]}{dots}
        </span>
      </div>
    );
  };

  return (
    <div className="flex flex-col items-start max-w-[400px] sm:max-w-[520px] w-full p-3 sm:p-8 bg-black/85 rounded-[4px]">
        <h1 className="text-2xl font-bold font-orbitron text-white mb-1">
          Performance
          {performanceLoading && <span className="text-sm text-gray-400 ml-2">Loading...</span>}
          {error && <span className="text-sm text-red-400 ml-2">Error</span>}
        </h1>
        <div className="mb-8 flex flex-col gap-1 sm:gap-3 w-full">
          <div className="text-md text-white mb-8">Statistics on Calvin's Vault return on investment</div>
          <div className="flex flex-row gap-1 sm:gap-3 text-white w-full">
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-1'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">24 H</div>
              <div className="text-yellow-400 text-xs">
                under maintenance
              </div>
            </div>
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-1'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">7 Days</div>
              <div className="text-yellow-400 text-xs">
                under maintenance
              </div>
            </div>
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-[3]'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">Total $Calvin Locked</div>
              <div className="text-white">
                {isTotalStakedLoading ? <CalvinLoadingText /> : formatNumber(totalStakedCalvin.totalStakedFormatted)}
              </div>
            </div>
          </div>
          <div className="flex flex-row gap-1 sm:gap-3 text-white w-full">
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-1'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">Month</div>
              <div className="text-yellow-400 text-xs">
                under maintenance
              </div>
            </div>
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-1'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">YTD</div>
              <div className="text-yellow-400 text-xs">
                under maintenance
              </div>
            </div>
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-[3]'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">Total $USDC Locked</div>
              <div className="text-white">
                {isVaultStatsLoading ? <CalvinLoadingText /> : `$${formatNumber(vaultStats.totalUsdcFormatted)}`}
              </div>
            </div>
          </div>
        </div>
        <div className="text-gray-300">
          <span>Connect your Discord account to access the Calvin vault system.</span>
        </div>
    </div>
  )
}

export default PerformanceBox
