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

export type WSEvent =
  | { type: 'controller_connected'; data: Controller }
  | { type: 'controller_disconnected'; data: { unique_id: string } }
  | { type: 'controller_ready'; data: ReadyController & { snd_src: string } }
  | { type: 'controller_unready'; data: { unique_id: string } }
  | { type: 'battery_update'; data: { unique_id: string; battery_percent: number } }
  | { type: 'bluetooth_scan_started'; data: Record<string, never> }
  | { type: 'bluetooth_device_found'; data: { name: string; address: string } }
  | { type: 'bluetooth_scan_complete'; data: Record<string, never> }
  | { type: 'state_snapshot'; data: { connected: Controller[]; ready: ReadyController[] } }

export type ControllerAction =
  | { type: 'SET_STATE'; connected: Controller[]; ready: ReadyController[] }
  | { type: 'CONTROLLER_CONNECTED'; controller: Controller }
  | { type: 'CONTROLLER_DISCONNECTED'; unique_id: string }
  | { type: 'CONTROLLER_READY'; controller: ReadyController }
  | { type: 'CONTROLLER_UNREADY'; unique_id: string }
  | { type: 'BATTERY_UPDATE'; unique_id: string; battery_percent: number }
  | { type: 'REASSIGN' }
  | { type: 'APPLY_CONFIG' }
