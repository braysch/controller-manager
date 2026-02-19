import Button from './Button'

interface BottomButtonsProps {
  onBack: () => void
  onReassign: () => void
  onOkay: () => void
  hasReady: boolean
}

export default function BottomButtons({
  onBack,
  onReassign,
  onOkay,
  hasReady
}: BottomButtonsProps): JSX.Element {
  return (
    <div className="flex items-center justify-center px-4 py-3 bg-gray-800 border-t border-gray-700">
      <div className="flex flex-1 w-full">
        <Button onClick={onBack}>Exit</Button>
      </div>

      <div className='text-xl px-8 w-full flex justify-center flex-1'>
        <div className='flex justify-center gap-x-4 h-[75px]'>
          <img className='h-full' src='local://home/brayschway/Server Media/Games/Video Games/Stardew Valley/logo.png' alt='Game Logo'></img>
          <img className='h-full' src='local://home/brayschway/Server Media/Games/Emulators/Yuzu/logo.png' alt='Yuzu Logo'></img>
        </div>
      </div>

      <div className="flex gap-2 flex-1 justify-end">
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