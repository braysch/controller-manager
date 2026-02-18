import { Settings } from 'lucide-react'

interface TopBarProps {
  onSettingsClick: () => void
  wsConnected: boolean
}

export default function TopBar({ onSettingsClick }: TopBarProps): JSX.Element {
  return (
    <div className="flex items-center justify-end px-4 py-2">
      <button
        onClick={onSettingsClick}
        className="p-2 rounded-lg hover:bg-gray-700 transition-colors"
        title="Settings"
      >
        <Settings className='hover:rotate-[90deg] transition-all duration-300' size={32} />
      </button>
    </div>
  )
}