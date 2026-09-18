import { useEffect, useRef, useState, useCallback, type MutableRefObject } from 'react'
import { X } from 'lucide-react'
import { api } from '../lib/api'
import type { Controller, ReadyController, RawInputEvent, InputConfigDevice } from '../types'

const FLASH_MS = 300
const MAX_LOG_ENTRIES = 24

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
}

export default function InputConfigScreen({
  open,
  onClose,
  connected,
  ready,
  rawInputHandlerRef
}: InputConfigScreenProps): JSX.Element | null {
  const controllers: (Controller | ReadyController)[] = [...connected, ...ready]
  const [focusedId, setFocusedId] = useState<string>('')
  const [devices, setDevices] = useState<InputConfigDevice[]>([])
  const [active, setActive] = useState<Set<string>>(new Set())
  const [axisValues, setAxisValues] = useState<Record<string, number>>({})
  const [log, setLog] = useState<{ id: number; text: string }[]>([])
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const logIdRef = useRef(0)

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
  }, [open])

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
    </div>
  )
}
