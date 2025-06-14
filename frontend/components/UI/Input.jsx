'use client';

import React from 'react';

const Input = React.forwardRef(({ 
  className = '', 
  type = 'text', 
  disabled = false,
  ...props 
}, ref) => {
  return (
    <input
      type={type}
      className={`
        w-full 
        bg-black/75 
        rounded-[4px] 
        p-3 
        text-white 
        border 
        border-white/20 
        focus:border-[#B73E15] 
        focus:outline-none 
        focus:ring-1 
        focus:ring-[#B73E15] 
        disabled:opacity-50 
        disabled:cursor-not-allowed
        placeholder:text-white/40
        no-spinner
        ${className}
      `}
      disabled={disabled}
      ref={ref}
      {...props}
    />
  );
});

Input.displayName = 'Input';

export default Input; 