interface ButtonProps {
    onClick: () => void
    disabled?: boolean
    variant?: 'primary' | 'secondary'
    children: React.ReactNode
    className?: string
  }
  
  export default function Button({
    onClick,
    disabled = false,
    variant = 'secondary',
    children,
    className = ''
  }: ButtonProps): JSX.Element {
    const baseClasses = 'px-4 py-2 text-sm rounded-lg transition-colors'
    const variantClasses = {
      primary: 'bg-blue-600 hover:bg-blue-500 font-medium',
      secondary: 'bg-gray-700 hover:bg-gray-600'
    }
    const disabledClasses = 'disabled:opacity-40 disabled:cursor-not-allowed'
  
    return (
      <button
        onClick={onClick}
        disabled={disabled}
        className={`text-xl rounded-sm text-nowrap ${baseClasses} ${variantClasses[variant]} ${disabledClasses} ${className}`}
      >
          <div className="p-2">
        {children}
        </div>
      </button>
    )
  }