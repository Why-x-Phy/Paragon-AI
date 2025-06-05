'use client';

import Image from 'next/image';
import { useClickOutside } from '@/hooks/useClickOutside';

export default function Modal({ 
  isOpen, 
  onClose, 
  title, 
  icon,
  children 
}) {
  const modalRef = useClickOutside(onClose);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center">
      <div ref={modalRef} className="bg-[#0A2519] p-10 gap-8 rounded-lg w-full max-w-md">
        {/* Header */}
        <div className="flex items-center justify-between gap-3 p-4">
            <Image src={icon} alt={title} width={32} height={32} />

            <h2 className="text-white text-2xl font-['Orbitron'] font-bold">{title}</h2>
            <button 
                onClick={onClose}
                className="ml-auto text-white/60 hover:text-white cursor-pointer"
            >
                <Image src="/close.svg" alt="Close" width={24} height={24} />
            </button>
        </div>

        {/* Content */}
        <div className="p-4">
          {children}
        </div>
      </div>
    </div>
  );
} 