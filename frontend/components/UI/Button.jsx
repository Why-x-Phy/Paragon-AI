import Image from 'next/image';

export default function Button({ 
  children,
  variant = 'primary',
  icon,
  className = '',
  textSize = 'text-md',
  loading = false,
  disabled = false,
  ...props 
}) {
  const baseStyles = "text-black rounded-[4px] px-6 py-2 hover:opacity-90 transition-colors flex items-center justify-center gap-2 cursor-pointer";
  
  const variants = {
    primary: "bg-[#B73E15]",
    secondary: "bg-[#6B6969]",
    outline: "bg-transparent border-2 border-[#B73E15] text-[#B73E15]"
  };

  const isDisabled = loading || disabled;

  return (
    <button 
      className={`${baseStyles} ${variants[variant]} ${className} ${isDisabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      disabled={isDisabled}
      {...props}
    >
      {loading ? (
        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-current"></div>
      ) : (
        icon && (
          <Image 
            src={icon} 
            alt={typeof children === 'string' ? children : 'button icon'} 
            width={24} 
            height={24} 
          />
        )
      )}
      <p className={`${textSize} font-bold`}>{children}</p>
    </button>
  );
}
