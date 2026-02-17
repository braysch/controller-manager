import { useState, useEffect } from 'react'
import { api } from '../lib/api'
import type { EmulatorConfig } from '../types'

export default function EmulatorPathConfig(): JSX.Element {
  const [emulators, setEmulators] = useState<EmulatorConfig[]>([])
  const [editingPath, setEditingPath] = useState<Record<string, string>>({})

  useEffect(() => {
    api.getEmulators().then((e) => setEmulators(e as EmulatorConfig[])).catch(console.error)
  }, [])

  const savePath = async (name: string) => {
    const path = editingPath[name]
    if (path === undefined) return
    await api.updateEmulator(name, { config_path: path })
    setEmulators(
      emulators.map((e) => (e.emulator_name === name ? { ...e, config_path: path } : e))
    )
    setEditingPath((prev) => {
      const next = { ...prev }
      delete next[name]
      return next
    })
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Emulator Paths
      </h3>
      <div className="space-y-2">
        {emulators.map((emu) => (
          <div key={emu.emulator_name} className="bg-gray-900 rounded-lg p-3">
            <div className="text-sm font-medium mb-1 capitalize">{emu.emulator_name}</div>
            <div className="flex gap-2">
              <input
                value={editingPath[emu.emulator_name] ?? emu.config_path}
                onChange={(e) =>
                  setEditingPath((prev) => ({ ...prev, [emu.emulator_name]: e.target.value }))
                }
                className="flex-1 bg-gray-700 rounded px-2 py-1 text-xs font-mono"
              />
              {editingPath[emu.emulator_name] !== undefined && (
                <button
                  onClick={() => savePath(emu.emulator_name)}
                  className="px-2 py-1 text-xs bg-blue-600 rounded hover:bg-blue-500"
                >
                  Save
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
