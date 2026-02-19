import type { Controller, BluetoothDevice } from '../types'
import RescanButton from './RescanButton'

interface ConnectedAreaProps {
  controllers: Controller[]
  bluetoothDevices: BluetoothDevice[]
  bluetoothScanning: boolean
  onClearBluetoothDevices: () => void
  poppingControllers: Set<string>
}

export default function ConnectedArea({
  controllers,
  bluetoothDevices,
  bluetoothScanning,
  onClearBluetoothDevices,
  poppingControllers
}: ConnectedAreaProps): JSX.Element {
  return (
    <div className="flex-shrink-0">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 flex-1 min-h-[3rem] px-2">
          {controllers.length === 0 ? (
            <p className="text-gray-500 text-sm italic">No controllers available</p>
          ) : (
            controllers.map((c) => (
              <img
                key={c.unique_id}
                src={`http://127.0.0.1:8000/assets/images/${c.img_src}`}
                alt={c.custom_name || c.name}
                title={c.custom_name || c.name}
                className={`w-10 h-10 object-contain ${
                  c.paired_but_disconnected ? 'opacity-50' : ''
                } ${poppingControllers.has(c.unique_id) ? 'controller-pop' : ''}`}
              />
            ))
          )}
        </div>
        <RescanButton
          bluetoothDevices={bluetoothDevices}
          bluetoothScanning={bluetoothScanning}
          onClearDevices={onClearBluetoothDevices}
          connectedControllers={controllers}
        />
      </div>
    </div>
  )
}
