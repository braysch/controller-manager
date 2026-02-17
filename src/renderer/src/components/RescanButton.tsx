import { useState } from 'react'
import { Bluetooth } from 'lucide-react'
import { api } from '../lib/api'
import type { BluetoothDevice } from '../types'

interface RescanButtonProps {
  bluetoothDevices: BluetoothDevice[]
  bluetoothScanning: boolean
  onClearDevices: () => void
}

export default function RescanButton({
  bluetoothDevices,
  bluetoothScanning,
  onClearDevices
}: RescanButtonProps): JSX.Element {
  const [scanning, setScanning] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [pairing, setPairing] = useState<string | null>(null)

  const isScanning = scanning || bluetoothScanning

  const handleScan = async () => {
    if (isScanning) {
      await api.stopBluetoothScan()
      setScanning(false)
    } else {
      onClearDevices()
      setScanning(true)
      setShowDropdown(true)
      try {
        await api.startBluetoothScan()
      } catch {
        // scan request failed
      } finally {
        setScanning(false)
      }
    }
  }

  const handlePair = async (address: string) => {
    setPairing(address)
    try {
      await api.pairBluetoothDevice(address)
    } catch {
      // pairing failed
    } finally {
      setPairing(null)
    }
  }

  return (
    <div className="relative">
      <button
        onClick={handleScan}
        className={`flex items-center gap-1 px-3 py-1 text-xs rounded-md transition-colors ${
          isScanning
            ? 'bg-blue-600 text-white animate-pulse'
            : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
        }`}
      >
        <Bluetooth size={14} />
        {isScanning ? 'Scanning...' : 'Rescan'}
      </button>

      {showDropdown && bluetoothDevices.length > 0 && (
        <div className="absolute right-0 top-full mt-1 w-64 bg-gray-800 border border-gray-600 rounded-lg shadow-lg z-30 overflow-hidden">
          <div className="p-2 border-b border-gray-700 flex items-center justify-between">
            <span className="text-xs text-gray-400">Found Devices</span>
            <button
              onClick={() => setShowDropdown(false)}
              className="text-xs text-gray-500 hover:text-gray-300"
            >
              Close
            </button>
          </div>
          {bluetoothDevices.map((d) => (
            <div
              key={d.address}
              className="flex items-center justify-between px-3 py-2 hover:bg-gray-700"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm truncate">{d.name}</p>
                <p className="text-[10px] text-gray-500">{d.address}</p>
              </div>
              <button
                onClick={() => handlePair(d.address)}
                disabled={pairing === d.address}
                className="ml-2 px-2 py-1 text-xs rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {pairing === d.address ? 'Pairing...' : 'Pair'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
