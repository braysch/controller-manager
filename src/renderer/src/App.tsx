import { useState, useEffect, useRef, useCallback } from 'react'
import TopBar from './components/TopBar'
import ConnectedArea from './components/ConnectedArea'
import ReadyGrid from './components/ReadyGrid'
import BottomButtons from './components/BottomButtons'
import SettingsPanel from './components/SettingsPanel'
import InputConfigScreen from './components/InputConfigScreen'
import { useWebSocket } from './hooks/useWebSocket'
import { useControllers } from './hooks/useControllers'
import { api } from './lib/api'
import type { RawInputEvent } from './types'

function App(): JSX.Element {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [inputConfigOpen, setInputConfigOpen] = useState(false)
  const [gameFolder, setGameFolder] = useState<string | null>(null)
  const [emulatorFolder, setEmulatorFolder] = useState<string | null>(null)
  const [emulatorTarget, setEmulatorTarget] = useState<string | null>(null)
  const [manualEmulator, setManualEmulator] = useState<string>('yuzu')
  const [manualGame, setManualGame] = useState<string | null>(null)

  // Raw input events are only consumed by InputConfigScreen while it's open;
  // routing them through a ref avoids re-rendering the whole app on every press.
  const rawInputHandlerRef = useRef<((event: RawInputEvent) => void) | null>(null)
  const handleRawInput = useCallback((event: RawInputEvent) => {
    rawInputHandlerRef.current?.(event)
  }, [])

  useEffect(() => {
    window.api.getLaunchPaths().then(({ gameFolder, emulatorFolder, emulatorTarget }) => {
      setGameFolder(gameFolder)
      setEmulatorFolder(emulatorFolder)
      setEmulatorTarget(emulatorTarget)
    })
  }, [])

  // Both Shift keys held together ready the virtual keyboard controller.
  // Disabled while Input Config is open so testing the keyboard's buttons
  // there doesn't ready it, same as any other controller being tested.
  useEffect(() => {
    if (inputConfigOpen) return
    const heldShifts = new Set<string>()
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== 'ShiftLeft' && e.code !== 'ShiftRight') return
      if (heldShifts.has(e.code)) return // ignore key auto-repeat
      heldShifts.add(e.code)
      if (heldShifts.size === 2) {
        api.moveToReady('keyboard').catch(console.error)
      }
    }
    const onKeyUp = (e: KeyboardEvent) => heldShifts.delete(e.code)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [inputConfigOpen])

  const selectManualGame = async () => {
    const result = await window.api.selectGame()
    if (result) {
      setManualGame(result.gamePath)
      setGameFolder(result.gameFolder)
    }
  }

  const activeEmulatorTarget = emulatorTarget ?? manualEmulator
  const { connected, ready, dispatch } = useControllers()
  const {
    connected: wsConnected,
    bluetoothDevices,
    bluetoothScanning,
    clearBluetoothDevices,
    poppingControllers
  } = useWebSocket(
    dispatch,
    () => {
      if (ready.length > 0) dispatch({ type: 'APPLY_CONFIG', emulatorTarget: activeEmulatorTarget, gamePath: manualGame })
    },
    handleRawInput
  )

  return (
    <div className="flex flex-col h-screen">
      <TopBar onSettingsClick={() => setSettingsOpen(true)} wsConnected={wsConnected} />

      <div className="flex-1 flex flex-col overflow-hidden px-4 pb-4 gap-4">
        <ConnectedArea
          controllers={connected}
          readyControllers={ready}
          bluetoothDevices={bluetoothDevices}
          bluetoothScanning={bluetoothScanning}
          onClearBluetoothDevices={clearBluetoothDevices}
          poppingControllers={poppingControllers}
        />
        <div className='flex h-full justify-center items-center w-full'>
          <div className='w-[1200px]'>
        <ReadyGrid controllers={ready} poppingControllers={poppingControllers} gameFolder={gameFolder} />
        </div>
        </div>
      </div>

      <BottomButtons
        onReassign={() => dispatch({ type: 'REASSIGN' })}
        onOkay={(force) =>
          dispatch({
            type: 'APPLY_CONFIG',
            emulatorTarget: activeEmulatorTarget,
            gamePath: manualGame,
            force
          })
        }
        onBack={() => window.close()}
        hasReady={ready.length > 0}
        gameFolder={gameFolder}
        emulatorFolder={emulatorFolder}
        manualEmulator={emulatorTarget === null ? manualEmulator : null}
        onManualEmulatorChange={setManualEmulator}
        manualGame={manualGame}
        onManualGameSelect={selectManualGame}
      />

      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onOpenInputConfig={() => {
          setSettingsOpen(false)
          setInputConfigOpen(true)
        }}
      />

      <InputConfigScreen
        open={inputConfigOpen}
        onClose={() => setInputConfigOpen(false)}
        connected={connected}
        ready={ready}
        rawInputHandlerRef={rawInputHandlerRef}
      />
    </div>
  )
}

export default App