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
    <div className="flex items-center justify-between px-4 py-3 bg-gray-800 border-t border-gray-700">
      <button
        onClick={onBack}
        className="px-4 py-2 text-sm rounded-lg bg-gray-700 hover:bg-gray-600 transition-colors"
      >
        Back
      </button>
      <div className="flex gap-2">
        <button
          onClick={onReassign}
          disabled={!hasReady}
          className="px-4 py-2 text-sm rounded-lg bg-gray-700 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Reassign
        </button>
        <button
          onClick={onOkay}
          disabled={!hasReady}
          className="px-4 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
        >
          Okay
        </button>
      </div>
    </div>
  )
}
