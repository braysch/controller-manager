import type { ReadyController } from '../types'
import ReadySlot from './ReadySlot'

interface ReadyGridProps {
  controllers: ReadyController[]
}

const TOTAL_SLOTS = 8

export default function ReadyGrid({ controllers }: ReadyGridProps): JSX.Element {
  const slots = Array.from({ length: TOTAL_SLOTS }, (_, i) => controllers[i] ?? null)

  return (
    <div className="flex-1">
      <div className="grid grid-cols-4 grid-rows-2 gap-y-3 gap-x-9 h-full">
        {slots.map((controller, index) => (
          <ReadySlot key={index} controller={controller} slotIndex={index} />
        ))}
      </div>
    </div>
  )
}