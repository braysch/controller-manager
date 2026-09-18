export interface Controller {
  unique_id: string
  name: string
  custom_name?: string
  img_src: string
  snd_src: string
  connection_type: 'usb' | 'bluetooth'
  battery_percent?: number
  vendor_id?: number
  product_id?: number
  paired_but_disconnected?: boolean
  guid?: string
  port?: number
  has_nunchuk?: boolean
}

export interface ReadyController extends Controller {
  slot_index: number
  component_unique_ids?: string[]
  component_names?: string[]
  component_imgs?: string[]
}

export interface ControllerProfile {
  unique_id: string
  default_name: string
  custom_name?: string
  img_src: string
  snd_src: string
  vendor_id?: number
  product_id?: number
  guid_override?: string
  bluetooth_address?: string
  start_button?: number
}

export interface EmulatorConfig {
  id: number
  emulator_name: string
  config_path: string
  enabled: boolean
}

export interface BluetoothDevice {
  name: string
  address: string
}

export interface RawInputEvent {
  unique_id: string
  kind: 'key' | 'abs'
  codes: string[]
  value: number
  min?: number
  max?: number
  // "" (or omitted) for the main device itself; otherwise the attached
  // extension's label (e.g. "Nunchuk", "Accelerometer") - a Nunchuk and the
  // Wii Remote's own Accelerometer can report identical axis codes, so this
  // is what distinguishes which sub-device an event actually came from.
  source?: string
}

export interface InputConfigAxis {
  code: string
  min: number
  max: number
}

export interface InputConfigDevice {
  // Matching key exactly matching RawInputEvent.source (empty for the main
  // device) - use `name` instead for anything user-visible.
  label: string
  name: string
  keys: string[]
  axes: InputConfigAxis[]
}

export interface InputConfigFocusResponse {
  status: string
  focused: string | null
  devices: InputConfigDevice[]
}

// A physical binding captured from Input Config's raw-input stream for one
// canonical Mesen role - label/code match RawInputEvent.source/codes[0]
// exactly, since that's how it's captured.
export interface RawBinding {
  label: string
  code: string
  kind: 'key'
}

export interface CustomMappingEntry {
  game_name: string
  controller_signature: string
  system: string
  bindings: Record<string, RawBinding>
}

export type WSEvent =
  | { type: 'controller_connected'; data: Controller }
  | { type: 'controller_disconnected'; data: { unique_id: string } }
  | { type: 'controller_ready'; data: ReadyController & { snd_src: string } }
  | { type: 'controller_unready'; data: { unique_id: string } }
  | { type: 'controller_input'; data: { unique_id: string } }
  | { type: 'start_pressed'; data: Record<string, never> }
  | { type: 'battery_update'; data: { unique_id: string; battery_percent: number } }
  | { type: 'bluetooth_scan_started'; data: Record<string, never> }
  | { type: 'bluetooth_device_found'; data: { name: string; address: string } }
  | { type: 'bluetooth_scan_complete'; data: Record<string, never> }
  | { type: 'state_snapshot'; data: { connected: Controller[]; ready: ReadyController[] } }
  | { type: 'raw_input'; data: RawInputEvent }

export type ControllerAction =
  | { type: 'SET_STATE'; connected: Controller[]; ready: ReadyController[] }
  | { type: 'CONTROLLER_CONNECTED'; controller: Controller }
  | { type: 'CONTROLLER_DISCONNECTED'; unique_id: string }
  | { type: 'CONTROLLER_READY'; controller: ReadyController }
  | { type: 'CONTROLLER_UNREADY'; unique_id: string }
  | { type: 'BATTERY_UPDATE'; unique_id: string; battery_percent: number }
  | { type: 'REASSIGN' }
  | {
      type: 'APPLY_CONFIG'
      emulatorTarget?: string | null
      gamePath?: string | null
      gameName?: string | null
      system?: string | null
      force?: boolean
    }
