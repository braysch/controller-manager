import { useEffect, useRef, useState, useCallback, type MutableRefObject } from 'react'
import { X } from 'lucide-react'
import { api } from '../lib/api'
import type { Controller, ReadyController, RawInputEvent } from '../types'

type ButtonId =
  | 'north'
  | 'south'
  | 'east'
  | 'west'
  | 'select'
  | 'start'
  | 'home'
  | 'camera'
  | 'dpad_up'
  | 'dpad_down'
  | 'dpad_left'
  | 'dpad_right'
  | 'left_stick'
  | 'right_stick'
  | 'left_trigger'
  | 'right_trigger'
  | 'left_bumper'
  | 'right_bumper'

const BUTTONS: { id: ButtonId; label: string }[] = [
  { id: 'north', label: 'North Button' },
  { id: 'south', label: 'South Button' },
  { id: 'east', label: 'East Button' },
  { id: 'west', label: 'West Button' },
  { id: 'select', label: 'Select Button' },
  { id: 'start', label: 'Start Button' },
  { id: 'home', label: 'Home Button' },
  { id: 'camera', label: 'Camera Button' },
  { id: 'dpad_up', label: 'D-Up' },
  { id: 'dpad_down', label: 'D-Down' },
  { id: 'dpad_left', label: 'D-Left' },
  { id: 'dpad_right', label: 'D-Right' },
  { id: 'left_stick', label: 'Left Joystick' },
  { id: 'right_stick', label: 'Right Joystick' },
  { id: 'left_trigger', label: 'Left Trigger' },
  { id: 'right_trigger', label: 'Right Trigger' },
  { id: 'left_bumper', label: 'Left Bumper' },
  { id: 'right_bumper', label: 'Right Bumper' }
]

// evdev exposes several historical aliases for the same button code (e.g. BTN_A
// and BTN_SOUTH share a value) - the backend forwards every alias it knows about
// so any of them can match here regardless of which name a given driver reports.
const KEY_MAP: Record<string, ButtonId> = {
  BTN_SOUTH: 'south',
  BTN_A: 'south',
  BTN_GAMEPAD: 'south',
  BTN_EAST: 'east',
  BTN_B: 'east',
  BTN_NORTH: 'north',
  BTN_X: 'north',
  BTN_WEST: 'west',
  BTN_Y: 'west',
  BTN_TL: 'left_bumper',
  BTN_TR: 'right_bumper',
  BTN_TL2: 'left_trigger',
  BTN_TR2: 'right_trigger',
  BTN_THUMBL: 'left_stick',
  BTN_THUMBR: 'right_stick',
  BTN_SELECT: 'select',
  BTN_START: 'start',
  BTN_MODE: 'home',
  BTN_DPAD_UP: 'dpad_up',
  BTN_DPAD_DOWN: 'dpad_down',
  BTN_DPAD_LEFT: 'dpad_left',
  BTN_DPAD_RIGHT: 'dpad_right',
  KEY_CAMERA: 'camera',
  // Wii Remote: hid-wiimote reports these as plain keyboard-style keys/misc
  // joystick buttons rather than standard gamepad codes, so they need their
  // own aliases here to show up at all.
  KEY_UP: 'dpad_up',
  KEY_DOWN: 'dpad_down',
  KEY_LEFT: 'dpad_left',
  KEY_RIGHT: 'dpad_right',
  KEY_NEXT: 'start', // "+"
  KEY_PREVIOUS: 'select', // "-"
  BTN_1: 'north',
  BTN_2: 'west'
}

const AXIS_STICK: Record<string, ButtonId> = {
  ABS_X: 'left_stick',
  ABS_Y: 'left_stick',
  ABS_RX: 'right_stick',
  ABS_RY: 'right_stick'
}

const AXIS_TRIGGER: Record<string, ButtonId> = {
  ABS_Z: 'left_trigger',
  ABS_GAS: 'left_trigger',
  ABS_RZ: 'right_trigger',
  ABS_BRAKE: 'right_trigger'
}

const STICK_DEADZONE = 0.3
const TRIGGER_THRESHOLD = 0.2
const FLASH_MS = 300
const MAX_LOG_ENTRIES = 24

function matchButtons(event: RawInputEvent): ButtonId[] {
  if (event.kind === 'key') {
    if (event.value !== 1) return []
    return event.codes.map((c) => KEY_MAP[c]).filter((b): b is ButtonId => Boolean(b))
  }

  const matches: ButtonId[] = []
  for (const code of event.codes) {
    if (code === 'ABS_HAT0X') {
      if (event.value < 0) matches.push('dpad_left')
      else if (event.value > 0) matches.push('dpad_right')
    } else if (code === 'ABS_HAT0Y') {
      if (event.value < 0) matches.push('dpad_up')
      else if (event.value > 0) matches.push('dpad_down')
    } else if (code in AXIS_STICK && event.min !== undefined && event.max !== undefined) {
      const center = (event.min + event.max) / 2
      const range = (event.max - event.min) / 2 || 1
      if (Math.abs(event.value - center) / range > STICK_DEADZONE) matches.push(AXIS_STICK[code])
    } else if (code in AXIS_TRIGGER && event.min !== undefined && event.max !== undefined) {
      const threshold = event.min + (event.max - event.min) * TRIGGER_THRESHOLD
      if (event.value > threshold) matches.push(AXIS_TRIGGER[code])
    }
  }
  return matches
}

function describeEvent(event: RawInputEvent): string {
  const name = event.codes[0]
  if (event.kind === 'key') return `${name}  ${event.value === 1 ? 'pressed' : 'released'}`
  return `${name}  = ${event.value}`
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
  const [active, setActive] = useState<Set<ButtonId>>(new Set())
  const [log, setLog] = useState<{ id: number; text: string }[]>([])
  const timers = useRef<Map<ButtonId, ReturnType<typeof setTimeout>>>(new Map())
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

  const flash = useCallback((id: ButtonId) => {
    setActive((prev) => new Set(prev).add(id))
    const existing = timers.current.get(id)
    if (existing) clearTimeout(existing)
    const timer = setTimeout(() => {
      setActive((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      timers.current.delete(id)
    }, FLASH_MS)
    timers.current.set(id, timer)
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
      for (const id of matchButtons(event)) flash(id)
    }
    return () => {
      rawInputHandlerRef.current = null
    }
  }, [open, focusedId, flash, rawInputHandlerRef])

  // Tell the backend which device to stream raw events for; stop streaming on close.
  useEffect(() => {
    api.setInputConfigFocus(open ? focusedId || null : null).catch(console.error)
  }, [open, focusedId])

  useEffect(() => {
    if (open) return
    setActive(new Set())
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
        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {BUTTONS.map((btn) => (
              <div
                key={btn.id}
                className={`rounded-lg border p-4 text-center text-sm font-medium transition-colors duration-150 ${
                  active.has(btn.id)
                    ? 'bg-green-600 border-green-400 text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-300'
                }`}
              >
                {btn.label}
              </div>
            ))}
          </div>
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
