import React from 'react'
import Image from 'next/image';
import Navbar from './Navbar';
import ActionButtons from './ActionButtons';
import BalanceSection from './BalanceSection';

const Main = () => {
  return (
    <div className="w-full max-w-7xl mx-auto bg-black/85 py-8 px-8 rounded-lg relative">
      <Navbar />
      <div className="flex flex-col my-8">
        <p className='text-white text-[20px]'>
            Welcome, <span className="text-[#B73E15]">{'Whale'}</span>. You have access to deposit into Calvin's private vault.
        </p>
      </div>
      <ActionButtons />
      <BalanceSection />
      
      {/* Calvin Character */}
      <div className="absolute bottom-0 -right-20 md:-bottom-20 md:-right-30 translate-x-8 translate-y-8">
        <Image 
          src="/calvin.png" 
          alt="Calvin Character" 
          width={300} 
          height={300}
          priority
          className="pointer-events-none select-none"
        />
      </div>
    </div>
  )
}

export default Main