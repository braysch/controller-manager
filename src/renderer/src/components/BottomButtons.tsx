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
  onOkay: () => void
  hasReady: boolean
  gameFolder: string | null
  emulatorFolder: string | null
  manualEmulator: string | null
  onManualEmulatorChange: (value: string) => void
}

export default function BottomButtons({
  onBack,
  onReassign,
  onOkay,
  hasReady,
  gameFolder,
  emulatorFolder,
  manualEmulator,
  onManualEmulatorChange
}: BottomButtonsProps): JSX.Element {
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
        )}
        <Button onClick={onReassign} disabled={!hasReady}>
          Reset Grip/Order
        </Button>
        <Button onClick={onOkay} disabled={!hasReady} variant="primary">
          Start Software
        </Button>
      </div>
    </div>
  )
}