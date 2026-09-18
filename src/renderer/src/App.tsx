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
import { baseNameNoExt, parseGameTitle, systemForGamePath } from './lib/gameInfo'
import type { RawInputEvent } from './types'

function App(): JSX.Element {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [inputConfigOpen, setInputConfigOpen] = useState(false)
  const [gameFolder, setGameFolder] = useState<string | null>(null)
  const [emulatorFolder, setEmulatorFolder] = useState<string | null>(null)
  const [emulatorTarget, setEmulatorTarget] = useState<string | null>(null)
  const [manualEmulator, setManualEmulator] = useState<string>('yuzu')
  const [manualGame, setManualGame] = useState<string | null>(null)
  // Derived once per selected game (from Pegasus metadata when available,
  // else the filename) so Input Config's "Configure controls" and the
  // apply-config launch flow always agree on the same lookup key for custom
  // mappings - editable via Input Config in case metadata parsing is wrong
  // or missing.
  const [gameName, setGameName] = useState<string | null>(null)
  const gameSystem = manualGame ? systemForGamePath(manualGame) : null

  // Raw input events are only consumed by InputConfigScreen while it's open;
  // routing them through a ref avoids re-rendering the whole app on every press.
  const rawInputHandlerRef = useRef<((event: RawInputEvent) => void) | null>(null)
  const handleRawInput = useCallback((event: RawInputEvent) => {
    rawInputHandlerRef.current?.(event)
  }, [])

  useEffect(() => {
    window.api.getLaunchPaths().then(({ gameFolder, gamePath, emulatorFolder, emulatorTarget }) => {
      setGameFolder(gameFolder)
      setEmulatorFolder(emulatorFolder)
      setEmulatorTarget(emulatorTarget)
      // When launched normally (via an emulate.sh wrapper, e.g. from
      // Pegasus), the real game path IS available here - without this, only
      // the manual "Choose Game" testing dialog ever set manualGame, so
      // gameSystem/gameName (and therefore custom mapping lookup) never
      // resolved during a real launch.
      if (gamePath) setManualGame(gamePath)
    })
  }, [])

  useEffect(() => {
    if (!manualGame) {
      setGameName(null)
      return
    }
    const fallback = baseNameNoExt(manualGame)
    if (!gameFolder) {
      setGameName(fallback)
      return
    }
    window.electron
      .readMetadata(gameFolder)
      .then((result) => {
        const title = result.success ? parseGameTitle(result.content, manualGame) : null
        setGameName(title ?? fallback)
      })
      .catch(() => setGameName(fallback))
  }, [manualGame, gameFolder])

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
      if (ready.length > 0)
        dispatch({
          type: 'APPLY_CONFIG',
          emulatorTarget: activeEmulatorTarget,
          gamePath: manualGame,
          gameName,
          system: gameSystem
        })
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
            gameName,
            system: gameSystem,
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
        gameName={gameName}
        gameSystem={gameSystem}
        onGameNameChange={setGameName}
      />
    </div>
  )
}

export default App