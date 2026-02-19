import { useState, useEffect } from 'react'
import TopBar from './components/TopBar'
import ConnectedArea from './components/ConnectedArea'
import ReadyGrid from './components/ReadyGrid'
import BottomButtons from './components/BottomButtons'
import SettingsPanel from './components/SettingsPanel'
import { useWebSocket } from './hooks/useWebSocket'
import { useControllers } from './hooks/useControllers'

function App(): JSX.Element {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [gameFolder, setGameFolder] = useState<string | null>(null)
  const [emulatorFolder, setEmulatorFolder] = useState<string | null>(null)

  useEffect(() => {
    window.api.getLaunchPaths().then(({ gameFolder, emulatorFolder }) => {
      setGameFolder(gameFolder)
      setEmulatorFolder(emulatorFolder)
    })
  }, [])
  const { connected, ready, dispatch } = useControllers()
  const {
    connected: wsConnected,
    bluetoothDevices,
    bluetoothScanning,
    clearBluetoothDevices,
    poppingControllers
  } = useWebSocket(dispatch)

  return (
    <div className="flex flex-col h-screen">
      <TopBar onSettingsClick={() => setSettingsOpen(true)} wsConnected={wsConnected} />

      <div className="flex-1 flex flex-col overflow-hidden px-4 pb-4 gap-4">
        <ConnectedArea
          controllers={connected}
          bluetoothDevices={bluetoothDevices}
          bluetoothScanning={bluetoothScanning}
          onClearBluetoothDevices={clearBluetoothDevices}
          poppingControllers={poppingControllers}
        />
        <div className='flex h-full justify-center items-center w-full'>
          <div className='w-[1200px]'>
        <ReadyGrid controllers={ready} poppingControllers={poppingControllers} />
        </div>
        </div>
      </div>

      <BottomButtons
        onReassign={() => dispatch({ type: 'REASSIGN' })}
        onOkay={() => dispatch({ type: 'APPLY_CONFIG' })}
        onBack={() => window.close()}
        hasReady={ready.length > 0}
        gameFolder={gameFolder}
        emulatorFolder={emulatorFolder}
      />

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  )
}

export default App