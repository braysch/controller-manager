import { useEffect, useRef, useState, useCallback, type MutableRefObject } from 'react'
import { X } from 'lucide-react'
import { api } from '../lib/api'
import type {
  Controller,
  ReadyController,
  RawInputEvent,
  InputConfigDevice,
  RawBinding,
  CustomMappingEntry
} from '../types'

const FLASH_MS = 300
const MAX_LOG_ENTRIES = 24

// Canonical Mesen face-button roles offered for custom per-game mapping,
// per console (mirrors MesenConfigWriter.VIRTUAL_LAYOUTS minus the D-pad -
// D-pad remapping is an axis-based problem with its own separate mechanism,
// out of scope here). Up/Down/Left/Right aren't included: every controller
// already has a working default D-pad, and this screen only lets you
// reassign face buttons.
const ROLES_BY_SYSTEM: Record<string, string[]> = {
  Nes: ['A', 'B', 'Select', 'Start'],
  Gameboy: ['A', 'B', 'Select', 'Start'],
  Snes: ['A', 'B', 'X', 'Y', 'L', 'R', 'Select', 'Start'],
  Gba: ['A', 'B', 'X', 'Y', 'L', 'R', 'Select', 'Start']
}

function describeBinding(binding: RawBinding | null | undefined): string {
  if (binding === null) return '(no mapping)'
  if (!binding) return 'unset'
  return binding.label ? `[${binding.label}] ${binding.code}` : binding.code
}

// Groups tiles by which physical device reported them (main controller vs. an
// attached extension like a Nunchuk) - some devices report identical raw code
// names for entirely different things (e.g. a Nunchuk and the Wii Remote's own
// Accelerometer both use ABS_RX/RY/RZ), so a plain code name alone can't be
// used as a unique key across the whole screen.
function tileKey(source: string | undefined, code: string): string {
  return `${source ?? ''}::${code}`
}

function describeEvent(event: RawInputEvent): string {
  const name = event.codes[0]
  const prefix = event.source ? `[${event.source}] ` : ''
  if (event.kind === 'key') return `${prefix}${name}  ${event.value === 1 ? 'pressed' : 'released'}`
  return `${prefix}${name}  = ${event.value}`
}

interface InputConfigScreenProps {
  open: boolean
  onClose: () => void
  connected: Controller[]
  ready: ReadyController[]
  rawInputHandlerRef: MutableRefObject<((event: RawInputEvent) => void) | null>
  gameName: string | null
  gameSystem: string | null
  onGameNameChange: (name: string) => void
}

export default function InputConfigScreen({
  open,
  onClose,
  connected,
  ready,
  rawInputHandlerRef,
  gameName,
  gameSystem,
  onGameNameChange
}: InputConfigScreenProps): JSX.Element | null {
  const controllers: (Controller | ReadyController)[] = [...connected, ...ready]
  const [focusedId, setFocusedId] = useState<string>('')
  const [devices, setDevices] = useState<InputConfigDevice[]>([])
  const [active, setActive] = useState<Set<string>>(new Set())
  const [axisValues, setAxisValues] = useState<Record<string, number>>({})
  const [log, setLog] = useState<{ id: number; text: string }[]>([])
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const logIdRef = useRef(0)

  // Per-game custom control mapping ("Configure controller to game") state.
  const [gameConfigOpen, setGameConfigOpen] = useState(false)
  const [signature, setSignature] = useState<string | null>(null)
  const [bindings, setBindings] = useState<Record<string, RawBinding | null>>({})
  const [existingMappings, setExistingMappings] = useState<CustomMappingEntry[]>([])
  const [localGameName, setLocalGameName] = useState('')
  const [capturingRole, setCapturingRole] = useState<string | null>(null)
  const [saveStatus, setSaveStatus] = useState<string | null>(null)
  // Raw input events fire from a ref-based handler set up in an effect below
  // (see its own comment) - a plain state variable would go stale inside
  // that closure, so capture-in-progress is tracked via a ref, mirrored into
  // state only so the UI can re-render to show "press a button...".
  const capturingRoleRef = useRef<string | null>(null)
  const startCapture = (role: string) => {
    capturingRoleRef.current = role
    setCapturingRole(role)
  }

  // Default to the first available controller when the screen opens, or when
  // the previously focused one disconnects.
  useEffect(() => {
    if (!open) return
    if (!controllers.some((c) => c.unique_id === focusedId)) {
      setFocusedId(controllers[0]?.unique_id ?? '')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, connected, ready])

  const flash = useCallback((key: string) => {
    setActive((prev) => new Set(prev).add(key))
    const existing = timers.current.get(key)
    if (existing) clearTimeout(existing)
    const timer = setTimeout(() => {
      setActive((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
      timers.current.delete(key)
    }, FLASH_MS)
    timers.current.set(key, timer)
  }, [])

  // Wire ourselves up to receive raw input events for the focused controller only.
  useEffect(() => {
    if (!open) {
      rawInputHandlerRef.current = null
      return
    }
    rawInputHandlerRef.current = (event: RawInputEvent) => {
      if (event.unique_id !== focusedId) return
      if (capturingRoleRef.current && event.kind === 'key' && event.value === 1) {
        const role = capturingRoleRef.current
        setBindings((prev) => ({ ...prev, [role]: { label: event.source ?? '', code: event.codes[0], kind: 'key' } }))
        capturingRoleRef.current = null
        setCapturingRole(null)
        return
      }
      setLog((prev) => [{ id: logIdRef.current++, text: describeEvent(event) }, ...prev].slice(0, MAX_LOG_ENTRIES))
      const key = tileKey(event.source, event.codes[0])
      if (event.kind === 'key') {
        if (event.value === 1) flash(key)
      } else {
        setAxisValues((prev) => ({ ...prev, [key]: event.value }))
        flash(key)
      }
    }
    return () => {
      rawInputHandlerRef.current = null
    }
  }, [open, focusedId, flash, rawInputHandlerRef])

  // Tell the backend which device to stream raw events for, and pick up its
  // (and any attached extension's) actual capabilities to build the grid from.
  useEffect(() => {
    if (!open) {
      api.setInputConfigFocus(null).catch(console.error)
      return
    }
    if (!focusedId) {
      setDevices([])
      return
    }
    api
      .setInputConfigFocus(focusedId)
      .then((res) => setDevices(res.devices))
      .catch(console.error)
  }, [open, focusedId])

  useEffect(() => {
    if (open) return
    setDevices([])
    setActive(new Set())
    setAxisValues({})
    setLog([])
    Array.from(timers.current.values()).forEach(clearTimeout)
    timers.current.clear()
    setGameConfigOpen(false)
    capturingRoleRef.current = null
    setCapturingRole(null)
  }, [open])

  const focusedController = controllers.find((c) => c.unique_id === focusedId)
  const roles = gameSystem ? ROLES_BY_SYSTEM[gameSystem] ?? [] : []

  // What's already in effect with no custom mapping - kept separately from
  // `bindings` (the editable/displayed set) so RESET TO DEFAULT can restore
  // it without a re-fetch.
  const [defaultBindings, setDefaultBindings] = useState<Record<string, RawBinding>>({})

  const openGameConfig = useCallback(async () => {
    if (!focusedId || !gameSystem) return
    setSaveStatus(null)
    setLocalGameName(gameName ?? '')
    setBindings({})
    setDefaultBindings({})
    setSignature(null)
    setExistingMappings([])
    setGameConfigOpen(true)
    try {
      const sigRes = await api.getControllerSignature(focusedId)
      if (!sigRes.signature) return
      setSignature(sigRes.signature)
      const [{ bindings: defaults }, { mappings }] = await Promise.all([
        api.getDefaultBindings(sigRes.signature, gameSystem),
        api.getCustomMappings(sigRes.signature, gameSystem)
      ])
      setDefaultBindings(defaults)
      setExistingMappings(mappings)
      const current = mappings.find((m) => m.game_name === (gameName ?? ''))
      // A saved mapping only needs to record what it customizes - any role
      // it doesn't mention still falls back to the real default here too.
      setBindings({ ...defaults, ...(current?.bindings ?? {}) })
    } catch (err) {
      console.error(err)
    }
  }, [focusedId, gameSystem, gameName])

  const closeGameConfig = () => {
    setGameConfigOpen(false)
    capturingRoleRef.current = null
    setCapturingRole(null)
  }

  const saveGameConfig = async () => {
    if (!signature || !gameSystem || !localGameName.trim()) return
    try {
      await api.saveCustomMapping(localGameName.trim(), signature, gameSystem, bindings)
      onGameNameChange(localGameName.trim())
      setSaveStatus('Saved.')
    } catch (err) {
      console.error(err)
      setSaveStatus('Failed to save.')
    }
  }

  const resetGameConfig = async () => {
    if (!signature || !gameSystem || !localGameName.trim()) return
    try {
      await api.resetCustomMapping(localGameName.trim(), signature, gameSystem)
      setBindings(defaultBindings)
      setSaveStatus('Reset to default.')
    } catch (err) {
      console.error(err)
      setSaveStatus('Failed to reset.')
    }
  }

  const copyFromMapping = (otherGameName: string) => {
    const other = existingMappings.find((m) => m.game_name === otherGameName)
    // Merge over defaultBindings too: an older mapping saved before this
    // only recorded the roles it explicitly customized.
    if (other) setBindings({ ...defaultBindings, ...other.bindings })
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 bg-gray-900 z-[60] flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-gray-700">
        <h2 className="text-lg font-bold">Input Config</h2>
        <button onClick={onClose} className="p-1 rounded-lg hover:bg-gray-700 transition-colors">
          <X size={20} />
        </button>
      </div>

      <div className="p-4 border-b border-gray-700 flex items-center gap-3">
        <label className="text-sm text-gray-400">Focused Controller</label>
        <select
          value={focusedId}
          onChange={(e) => setFocusedId(e.target.value)}
          className="bg-gray-800 rounded px-2 py-1 text-sm"
        >
          {controllers.length === 0 && <option value="">No controllers connected</option>}
          {controllers.map((c) => (
            <option key={c.unique_id} value={c.unique_id}>
              {c.custom_name || c.name}
            </option>
          ))}
        </select>

        <button
          onClick={openGameConfig}
          disabled={!focusedId || !gameSystem}
          title={!gameSystem ? 'Select a supported ROM (Nes/Snes/Gameboy/Gba) to configure custom controls' : undefined}
          className="ml-auto px-3 py-1.5 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 disabled:cursor-not-allowed transition-colors"
        >
          Configure {focusedController?.custom_name || focusedController?.name || 'controller'} to{' '}
          {gameName || 'selected game'}
        </button>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {devices.length === 0 ? (
            <p className="text-gray-500 text-sm italic">No input capabilities found for this controller</p>
          ) : (
            devices.map((device) => (
              <div key={device.label || device.name}>
                {devices.length > 1 && (
                  <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                    {device.name}
                  </h3>
                )}
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                  {device.keys.map((code) => {
                    const key = tileKey(device.label, code)
                    return (
                      <div
                        key={key}
                        className={`rounded-lg border p-4 text-center text-sm font-medium font-mono transition-colors duration-150 ${
                          active.has(key)
                            ? 'bg-green-600 border-green-400 text-white'
                            : 'bg-gray-800 border-gray-700 text-gray-300'
                        }`}
                      >
                        {code}
                      </div>
                    )
                  })}
                  {device.axes.map((axis) => {
                    const key = tileKey(device.label, axis.code)
                    return (
                      <div
                        key={key}
                        className={`rounded-lg border p-4 text-center transition-colors duration-150 ${
                          active.has(key)
                            ? 'bg-green-600 border-green-400 text-white'
                            : 'bg-gray-800 border-gray-700 text-gray-300'
                        }`}
                      >
                        <div className="text-sm font-medium font-mono">{axis.code}</div>
                        <div className="text-xs mt-1 opacity-80">
                          {axisValues[key] ?? 0} <span className="opacity-60">[{axis.min}, {axis.max}]</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="w-80 border-l border-gray-700 p-4 overflow-y-auto">
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Raw Input</h3>
          {log.length === 0 ? (
            <p className="text-gray-500 text-sm italic">Press a button to see its raw input here</p>
          ) : (
            <div className="space-y-1 font-mono text-xs">
              {log.map((entry) => (
                <div key={entry.id} className="text-gray-300">
                  {entry.text}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {gameConfigOpen && (
        <div className="fixed inset-0 bg-black/70 z-[70] flex items-center justify-center p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg max-h-[85vh] overflow-y-auto p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold">Configure Controls</h3>
              <button onClick={closeGameConfig} className="p-1 rounded-lg hover:bg-gray-700 transition-colors">
                <X size={18} />
              </button>
            </div>

            <div className="space-y-1">
              <label className="text-sm text-gray-400">Game name</label>
              <input
                value={localGameName}
                onChange={(e) => setLocalGameName(e.target.value)}
                className="w-full bg-gray-800 rounded px-2 py-1.5 text-sm"
                placeholder="e.g. Super Mario Kart"
              />
              <p className="text-xs text-gray-500">
                Saving under the same name here as another emulator's mapping lets them share it.
              </p>
            </div>

            {existingMappings.filter((m) => m.game_name !== localGameName).length > 0 && (
              <div className="space-y-1">
                <label className="text-sm text-gray-400">Copy bindings from an existing mapping</label>
                <select
                  defaultValue=""
                  onChange={(e) => {
                    if (e.target.value) copyFromMapping(e.target.value)
                    e.target.value = ''
                  }}
                  className="w-full bg-gray-800 rounded px-2 py-1.5 text-sm"
                >
                  <option value="">Select a game...</option>
                  {existingMappings
                    .filter((m) => m.game_name !== localGameName)
                    .map((m) => (
                      <option key={m.game_name} value={m.game_name}>
                        {m.game_name}
                      </option>
                    ))}
                </select>
              </div>
            )}

            <div className="space-y-2">
              {roles.map((role) => (
                <div key={role} className="flex items-center justify-between gap-3 bg-gray-800 rounded-lg px-3 py-2">
                  <span className="font-mono text-sm font-semibold w-16">{role}</span>
                  <span className="flex-1 text-sm text-gray-400 truncate">
                    {capturingRole === role ? 'Press a button...' : describeBinding(bindings[role])}
                  </span>
                  <button
                    onClick={() => startCapture(role)}
                    disabled={capturingRole !== null}
                    className="px-2 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-50 transition-colors"
                  >
                    Set
                  </button>
                  <button
                    onClick={() => setBindings((prev) => ({ ...prev, [role]: null }))}
                    disabled={capturingRole !== null || bindings[role] === null}
                    title="Leave this button unmapped"
                    className="px-2 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-50 transition-colors"
                  >
                    Clear
                  </button>
                </div>
              ))}
            </div>

            {saveStatus && <p className="text-xs text-gray-400">{saveStatus}</p>}

            <div className="flex items-center justify-between gap-3 pt-2">
              <button
                onClick={resetGameConfig}
                className="px-3 py-1.5 rounded-lg text-sm bg-red-900 hover:bg-red-800 transition-colors"
              >
                RESET TO DEFAULT
              </button>
              <button
                onClick={saveGameConfig}
                disabled={!signature || !localGameName.trim()}
                className="px-3 py-1.5 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 disabled:cursor-not-allowed transition-colors"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
