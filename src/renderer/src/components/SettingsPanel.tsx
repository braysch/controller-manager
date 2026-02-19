import { X } from 'lucide-react'
import ControllerProfileEditor from './ControllerProfileEditor'
import EmulatorPathConfig from './EmulatorPathConfig'

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
}

export default function SettingsPanel({ open, onClose }: SettingsPanelProps): JSX.Element {
  return (
    <>
      {/* Backdrop */}
      {open && (
        <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      )}

      {/* Panel */}
      <div
        className={`fixed top-0 right-0 h-full w-96 bg-gray-800 border-l border-gray-700 z-50 transform transition-transform duration-200 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h2 className="text-lg font-bold">Settings</h2>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-gray-700 transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        <div className="overflow-y-auto h-[calc(100%-4rem)] p-4 space-y-6">
          <EmulatorPathConfig />
          <ControllerProfileEditor open={open} />
        </div>
      </div>
    </>
  )
}
