import type { ReadyController } from '../types'
import PlayerIndicator from './PlayerIndicator'
import ConnectionTypeIcon from './ConnectionTypeIcon'
import BatteryIndicator from './BatteryIndicator'

interface ReadySlotProps {
  controller: ReadyController | null
  slotIndex: number
}

export default function ReadySlot({ controller, slotIndex }: ReadySlotProps): JSX.Element {
  if (!controller) {
    return (
      <div className="flex flex-col items-center mb-8">
        <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-gray-700 bg-gray-800/30 w-full aspect-square">
          <span className="text-gray-600 text-lg font-bold">P{slotIndex + 1}</span>
        </div>
      </div>
    )
  }

  const isCombined = controller.component_unique_ids && controller.component_unique_ids.length > 0
  const displayName = isCombined && controller.component_names && controller.component_names.length > 0
    ? controller.component_names.join(' + ')
    : controller.custom_name || controller.name

  return (
    <div className="flex flex-col items-center">
      <div className="flex flex-col items-center justify-between rounded-xl border-2 border-blue-500/50 bg-gray-800 p-3 w-full aspect-square">
        <PlayerIndicator playerNumber={slotIndex + 1} />
        {isCombined && controller.component_imgs ? (
          <div className="flex items-center justify-center flex-1 w-full py-1 min-h-0">
            {controller.component_imgs.map((img, i) => (
              <img
                key={controller.component_unique_ids![i] || i}
                src={`http://127.0.0.1:8000/assets/images/${img}`}
                alt={controller.component_names?.[i] || controller.name}
                className="h-full max-w-[45%] object-contain"
                style={{ transform: i === 0 ? 'rotate(90deg)' : 'rotate(-90deg)' }}
              />
            ))}
          </div>
        ) : (
          <img
            src={`http://127.0.0.1:8000/assets/images/${controller.img_src}`}
            alt={controller.name}
            className="flex-1 w-3/4 object-contain py-1 min-h-0"
          />
        )}
        <div className="flex items-center gap-1 flex-shrink-0">
          {controller.battery_percent !== undefined && (
            <BatteryIndicator percent={controller.battery_percent} />
          )}
          <ConnectionTypeIcon type={controller.connection_type} />
        </div>
      </div>
      <span className="text-xs text-center truncate w-full mt-1 text-gray-300">
        {displayName}
      </span>
    </div>
  )
}