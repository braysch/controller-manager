import type { CustomMappingEntry, InputConfigFocusResponse, RawBinding } from '../types'

const API_BASE = 'http://127.0.0.1:8000/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  })
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${await res.text()}`)
  }
  return res.json()
}

export const api = {
  getConnected: () => request<unknown[]>('/controllers/connected'),
  getReady: () => request<unknown[]>('/controllers/ready'),
  moveToReady: (unique_id: string) =>
    request('/controllers/ready', {
      method: 'POST',
      body: JSON.stringify({ unique_id })
    }),
  clearReady: () => request('/controllers/ready', { method: 'DELETE' }),

  getProfiles: () => request<unknown[]>('/profiles'),
  updateProfile: (unique_id: string, data: Record<string, unknown>) =>
    request(`/profiles/${encodeURIComponent(unique_id)}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),
  deleteProfile: (unique_id: string) =>
    request(`/profiles/${encodeURIComponent(unique_id)}`, {
      method: 'DELETE'
    }),

  startBluetoothScan: () => request('/bluetooth/scan', { method: 'POST' }),
  stopBluetoothScan: () => request('/bluetooth/stop-scan', { method: 'POST' }),
  pairBluetoothDevice: (address: string) =>
    request('/bluetooth/pair', {
      method: 'POST',
      body: JSON.stringify({ address })
    }),
  disconnectBluetoothDevice: (address: string) =>
    request('/bluetooth/disconnect', {
      method: 'POST',
      body: JSON.stringify({ address })
    }),
  removeBluetoothDevice: (address: string) =>
    request('/bluetooth/remove', {
      method: 'POST',
      body: JSON.stringify({ address })
    }),
  disconnectAllControllers: () => request('/controllers/disconnect-all', { method: 'POST' }),
  removeAllControllers: () => request('/controllers/remove-all', { method: 'POST' }),

  getEmulators: () => request<unknown[]>('/emulators'),
  updateEmulator: (name: string, data: Record<string, unknown>) =>
    request(`/emulators/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),
  applyConfig: (emulator?: string | null, force?: boolean, gameName?: string | null, system?: string | null) =>
    request('/emulators/apply', {
      method: 'POST',
      body: JSON.stringify({
        emulator: emulator ?? null,
        force: force ?? false,
        game_name: gameName ?? null,
        system: system ?? null
      }),
    }),

  getControllerSignature: (unique_id: string) =>
    request<{ signature?: string; error?: string }>(`/mesen/controller-signature/${encodeURIComponent(unique_id)}`),

  getDefaultBindings: (controllerSignature: string, system: string) =>
    request<{ bindings: Record<string, RawBinding> }>(
      `/mesen/default-bindings?controller_signature=${encodeURIComponent(controllerSignature)}&system=${encodeURIComponent(system)}`
    ),

  getCustomMappings: (controllerSignature: string, system: string) =>
    request<{ mappings: CustomMappingEntry[] }>(
      `/custom-mappings?controller_signature=${encodeURIComponent(controllerSignature)}&system=${encodeURIComponent(system)}`
    ),

  saveCustomMapping: (gameName: string, controllerSignature: string, system: string, bindings: Record<string, RawBinding | null>) =>
    request('/custom-mappings', {
      method: 'PUT',
      body: JSON.stringify({ game_name: gameName, controller_signature: controllerSignature, system, bindings })
    }),

  resetCustomMapping: (gameName: string, controllerSignature: string, system: string) =>
    request('/custom-mappings', {
      method: 'DELETE',
      body: JSON.stringify({ game_name: gameName, controller_signature: controllerSignature, system })
    }),

  forceConnectController: (unique_id: string) =>
    request<{ status?: string; error?: string }>('/bluetooth/force-connect', {
      method: 'POST',
      body: JSON.stringify({ unique_id })
    }),

  getImages: () => request<string[]>('/assets/images'),
  getSounds: () => request<string[]>('/assets/sounds'),

  setInputConfigFocus: (unique_id: string | null) =>
    request<InputConfigFocusResponse>('/input-config/focus', {
      method: 'POST',
      body: JSON.stringify({ unique_id })
    }),

  sessionLaunched: () => request('/session/launched', { method: 'POST' })
}
