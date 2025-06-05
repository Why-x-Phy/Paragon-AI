import Image from 'next/image';

export default function Button({ 
  children,
  variant = 'primary',
  icon,
  className = '',
  textSize = 'text-md',
  ...props 
}) {
  const baseStyles = "text-black rounded-[4px] px-6 py-2 hover:opacity-90 transition-colors flex items-center justify-center gap-2 cursor-pointer";
  
  const variants = {
    primary: "bg-[#B73E15]",
    secondary: "bg-[#6B6969]"
  };

  return (
    <button 
      className={`${baseStyles} ${variants[variant]} ${className}`}
      {...props}
    >
      {icon && (
        <Image 
          src={icon} 
          alt={typeof children === 'string' ? children : 'button icon'} 
          width={24} 
          height={24} 
        />
      )}
      <p className={`${textSize} font-bold`}>{children}</p>
    </button>
  );
}
