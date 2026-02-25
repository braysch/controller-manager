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
  applyConfig: (emulator?: string | null) =>
    request('/emulators/apply', {
      method: 'POST',
      body: JSON.stringify({ emulator: emulator ?? null }),
    }),

  updateProfileStartButton: (unique_id: string, tr2IsStart: boolean) =>
    request(`/profiles/${encodeURIComponent(unique_id)}/start-button`, {
      method: 'PUT',
      body: JSON.stringify({ tr2_is_start: tr2IsStart })
    }),

  getImages: () => request<string[]>('/assets/images'),
  getSounds: () => request<string[]>('/assets/sounds')
}
