'use client';

export default function BalanceCard({ title, balances, profit, className = '' }) {
  return (
    <div className={`rounded-[4px] border-[1px] border-white/10 p-5 w-full max-w-lg flex flex-col gap-5 ${className}`}>
        <div className="flex flex-col border-b-[1px] border-white/10 pb-3">
            <h3 className="text-white/40 text-[16px] font-bold">{title}</h3>
        </div>
      
        {balances?.map((balance, index) => (
            <div key={index} className="flex justify-start items-center mb-2 gap-2">
            <p className="text-white text-[16px] font-bold">{balance.label}:</p>
            <p className="text-white text-[16px] font-normal">{balance.amount}</p>
            </div>
        ))}

        {profit && (
            <div className="flex justify-start items-center gap-2">
                <p className="text-white font-bold text-[16px]">{profit.label}</p>
                <p className={`font-normal text-[16px] ${profit.value >= 0 ? 'text-[#42F014]' : 'text-red-500'}`}>
                +{profit.value} <span className="bg-[#42F01426]/50 py-0.5 px-2 gap-2">+{profit.percentage}%</span>
                </p>
            </div>
        )}
    </div>
  );
} 