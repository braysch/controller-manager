import { useState } from 'react'
import Button from './Button'

const EMULATOR_OPTIONS = [
  { value: 'yuzu', label: 'Yuzu' },
  { value: 'dolphin_gc', label: 'Dolphin (GC)' },
  { value: 'dolphin_wii', label: 'Dolphin (Wii)' },
  { value: 'desmume', label: 'DeSmuME' },
  { value: 'mesen', label: 'Mesen' },
  { value: 'parallel', label: 'Parallel' },
]

interface BottomButtonsProps {
  onBack: () => void
  onReassign: () => void
  onOkay: (force?: boolean) => void
  hasReady: boolean
  gameFolder: string | null
  emulatorFolder: string | null
  manualEmulator: string | null
  onManualEmulatorChange: (value: string) => void
  manualGame: string | null
  onManualGameSelect: () => void
}

export default function BottomButtons({
  onBack,
  onReassign,
  onOkay,
  hasReady,
  gameFolder,
  emulatorFolder,
  manualEmulator,
  onManualEmulatorChange,
  manualGame,
  onManualGameSelect
}: BottomButtonsProps): JSX.Element {
  const [startContextMenu, setStartContextMenu] = useState<{ x: number; y: number } | null>(null)

  const handleStartContextMenu = (e: React.MouseEvent): void => {
    e.preventDefault()
    setStartContextMenu({ x: e.clientX, y: e.clientY })
  }

  return (
    <div className="flex items-center justify-center px-4 py-3 bg-gray-800 border-t border-gray-700">
      <div className="flex flex-1 w-full">
        <Button onClick={onBack}>Exit</Button>
      </div>

      <div className='text-xl px-8 w-full flex justify-center flex-1'>
        <div className='flex justify-center gap-x-4 h-[75px]'>
          {gameFolder && (
            <img className='h-full' src={`local://${gameFolder}/logo.png`} alt='Game Logo' />
          )}
          {emulatorFolder && (
            <img className='h-full' src={`local://${emulatorFolder}/logo.png`} alt='Emulator Logo' />
          )}
        </div>
      </div>

      <div className="flex gap-2 flex-1 justify-end items-center">
        {manualEmulator !== null && (
          <>
            <Button onClick={onManualGameSelect}>
              {manualGame ? manualGame.split('/').pop() : 'Choose Game'}
            </Button>
            <select
              value={manualEmulator}
              onChange={(e) => onManualEmulatorChange(e.target.value)}
              className="bg-gray-700 text-white text-xl rounded-sm px-3 py-2 border border-gray-600 cursor-pointer"
            >
              {EMULATOR_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </>
        )}
        <Button onClick={onReassign} disabled={!hasReady}>
          Reset Grip/Order
        </Button>
        <div onContextMenu={handleStartContextMenu}>
          <Button onClick={() => onOkay()} disabled={!hasReady} variant="primary">
            Start Software
          </Button>
        </div>
      </div>

      {startContextMenu && (
        <div
          className="fixed inset-0 z-50"
          onClick={() => setStartContextMenu(null)}
          onContextMenu={(e) => {
            e.preventDefault()
            setStartContextMenu(null)
          }}
        >
          <div
            className="absolute bg-gray-800 border border-gray-600 rounded shadow-lg py-1"
            style={{ left: startContextMenu.x, top: startContextMenu.y }}
          >
            <button
              onClick={() => {
                onOkay(true)
                setStartContextMenu(null)
              }}
              className="w-full px-4 py-1.5 text-sm text-left text-nowrap hover:bg-gray-700 text-yellow-400"
            >
              Force Start Software
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
