import React from 'react'

const PerformanceBox = () => {
  return (
    <div className="flex flex-col items-start max-w-[365px] sm:max-w-[482px] w-full p-3 sm:p-8 bg-black/85 rounded-[4px]">
        <h1 className="text-2xl font-bold font-orbitron text-white mb-1">Performance</h1>
        <div className="mb-8 flex flex-col gap-1 sm:gap-3 w-full">
          <div className="text-md text-white mb-8">Statistics on Calvin’s Vault return on investment</div>
          <div className="flex flex-row gap-1 sm:gap-3 text-white w-full">
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-1'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">24 H</div>
              <div className="text-green-400">+4%</div>
            </div>
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-1'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">7 Days</div>
              <div className="text-green-400">+13%</div>
            </div>
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-[3]'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">Total $Calvin Locked</div>
              <div className="text-white">400M</div>
            </div>
          </div>
          <div className="flex flex-row gap-1 sm:gap-3 text-white w-full">
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-1'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">Month</div>
              <div className="text-green-400">+24%</div>
            </div>
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-1'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">YTD</div>
              <div className="text-green-400">+256%</div>
            </div>
            <div className='flex flex-col items-center border-1 border-white/10 p-3 gap-2 rounded-[4px] flex-[3]'>
              <div className="text-[16px] text-gray-400 border-b-1 border-white/10">Total $USDC Locked</div>
              <div className="text-white">$104,000</div>
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