import { useState } from 'react'
import { Bluetooth } from 'lucide-react'
import { api } from '../lib/api'
import type { BluetoothDevice } from '../types'
import Button from './Button'

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
  const [contextMenu, setContextMenu] = useState<{ address: string; x: number; y: number } | null>(null)

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

  const handleForcePair = async (address: string) => {
    setContextMenu(null)
    setPairing(address)
    try {
      await api.forcePairBluetoothDevice(address)
    } catch {
      // force pairing failed
    } finally {
      setPairing(null)
    }
  }

  const handleContextMenu = (e: React.MouseEvent, address: string) => {
    e.preventDefault()
    setContextMenu({ address, x: e.clientX, y: e.clientY })
  }

  return (
    <div className="relative">
      <Button
        onClick={handleScan}
        className={`flex items-center gap-1 px-3 py-1 text-xs rounded-md transition-colors ${
          isScanning
            ? 'bg-blue-600 text-white animate-pulse'
            : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
        }`}
      >
        <div className='flex flex-row text-xl gap-x-2 justify-center items-center -ml-2'>
        <Bluetooth height={24} />
        {isScanning ? 'Scanning...' : 'Rescan'}
        </div>
      </Button>


      {contextMenu && (
        <div
          className="fixed inset-0 z-50"
          onClick={() => setContextMenu(null)}
        >
          <div
            className="absolute bg-gray-800 border border-gray-600 rounded shadow-lg py-1"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <button
              onClick={() => handleForcePair(contextMenu.address)}
              className="w-full px-4 py-1.5 text-sm text-left hover:bg-gray-700 text-orange-400"
            >
              Force Pair
            </button>
          </div>
        </div>
      )}

      {showDropdown && (isScanning || bluetoothDevices.length > 0) && (
        <div className="absolute right-0 top-full mt-1 w-64 bg-gray-800 border border-gray-600 rounded-lg shadow-lg z-30 overflow-hidden">
          <div className="p-2 border-b border-gray-700 flex items-center justify-between">
            <span className="text-xs text-gray-400">
              {isScanning ? 'Scanning...' : 'Found Devices'}
            </span>
            <button
              onClick={() => setShowDropdown(false)}
              className="text-xs text-gray-500 hover:text-gray-300"
            >
              Close
            </button>
          </div>
          {bluetoothDevices.length === 0 ? (
            <p className="px-3 py-4 text-xs text-gray-500 text-center italic">
              Searching for controllers...
            </p>
          ) : (
            bluetoothDevices.map((d) => (
              <div
                key={d.address}
                className="flex items-center justify-between px-3 py-2 hover:bg-gray-700"
                onContextMenu={(e) => handleContextMenu(e, d.address)}
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
            ))
          )}
        </div>
      )}
    </div>
  )
}