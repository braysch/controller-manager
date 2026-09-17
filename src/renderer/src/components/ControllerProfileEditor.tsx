import { useState, useEffect } from 'react'
import { api } from '../lib/api'
import type { ControllerProfile } from '../types'

interface ControllerProfileEditorProps {
  open: boolean
}

export default function ControllerProfileEditor({ open }: ControllerProfileEditorProps): JSX.Element {
  const [profiles, setProfiles] = useState<ControllerProfile[]>([])
  const [images, setImages] = useState<string[]>([])
  const [sounds, setSounds] = useState<string[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editImg, setEditImg] = useState('')
  const [editSnd, setEditSnd] = useState('')
  const [editGuid, setEditGuid] = useState('')
  const [connecting, setConnecting] = useState<string | null>(null)
  const [connectResult, setConnectResult] = useState<Record<string, 'ok' | 'fail'>>({})

  const MAC_RE = /^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$/i
  const resolveMac = (profile: ControllerProfile) =>
    profile.bluetooth_address ||
    (MAC_RE.test(profile.unique_id) ? profile.unique_id : null)

  useEffect(() => {
    if (!open) return
    api.getProfiles().then((p) => setProfiles(p as ControllerProfile[])).catch(console.error)
    api.getImages().then(setImages).catch(console.error)
    api.getSounds().then(setSounds).catch(console.error)
  }, [open])

  const startEdit = (profile: ControllerProfile) => {
    setEditing(profile.unique_id)
    setEditName(profile.custom_name || '')
    setEditImg(profile.img_src)
    setEditSnd(profile.snd_src)
    setEditGuid(profile.guid_override || '')
  }

  const saveEdit = async () => {
    if (!editing) return
    await api.updateProfile(editing, {
      custom_name: editName || null,
      img_src: editImg,
      snd_src: editSnd,
      guid_override: editGuid || null
    })
    setProfiles(
      profiles.map((p) =>
        p.unique_id === editing
          ? {
              ...p,
              custom_name: editName || undefined,
              img_src: editImg,
              snd_src: editSnd,
              guid_override: editGuid || undefined
            }
          : p
      )
    )
    setEditing(null)
  }

  const forceConnect = async (profile: ControllerProfile, e: React.MouseEvent) => {
    e.stopPropagation()
    if (connecting) return
    setConnecting(profile.unique_id)
    setConnectResult((prev) => {
      const next = { ...prev }
      delete next[profile.unique_id]
      return next
    })
    try {
      const res = await api.forceConnectController(profile.unique_id)
      setConnectResult((prev) => ({
        ...prev,
        [profile.unique_id]: res.status === 'connected' ? 'ok' : 'fail'
      }))
    } catch {
      setConnectResult((prev) => ({ ...prev, [profile.unique_id]: 'fail' }))
    }
    setConnecting(null)
  }

  const deleteProfile = async (uniqueId: string) => {
    if (!window.confirm('Are you sure you want to delete this profile? If the controller is connected, it will be reset to defaults.')) {
      return
    }
    await api.deleteProfile(uniqueId)
    const p = await api.getProfiles()
    setProfiles(p as ControllerProfile[])
    setEditing(null)
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Controller Profiles
      </h3>
      {profiles.length === 0 ? (
        <p className="text-gray-500 text-sm italic">No saved profiles yet</p>
      ) : (
        <div className="space-y-2">
          {profiles.map((profile) => (
            <div key={profile.unique_id} className="bg-gray-900 rounded-lg p-3">
              {editing === profile.unique_id ? (
                <div className="space-y-2">
                  <input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder={profile.default_name}
                    className="w-full bg-gray-700 rounded px-2 py-1 text-sm"
                  />
                  <select
                    value={editImg}
                    onChange={(e) => setEditImg(e.target.value)}
                    className="w-full bg-gray-700 rounded px-2 py-1 text-sm"
                  >
                    {images.map((img) => (
                      <option key={img} value={img}>
                        {img}
                      </option>
                    ))}
                  </select>
                  <select
                    value={editSnd}
                    onChange={(e) => setEditSnd(e.target.value)}
                    className="w-full bg-gray-700 rounded px-2 py-1 text-sm"
                  >
                    {sounds.map((snd) => (
                      <option key={snd} value={snd}>
                        {snd}
                      </option>
                    ))}
                  </select>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">GUID Override</label>
                    <input
                      value={editGuid}
                      onChange={(e) => setEditGuid(e.target.value)}
                      placeholder="Leave blank to use auto-detected GUID"
                      className="w-full bg-gray-700 rounded px-2 py-1 text-xs font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">MAC Address</label>
                    <input
                      readOnly
                      value={resolveMac(profile) ?? ''}
                      placeholder="Reconnect controller to capture"
                      className="w-full bg-gray-800 rounded px-2 py-1 text-xs font-mono text-gray-400 cursor-default placeholder-gray-600"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={saveEdit}
                      className="px-3 py-1 text-xs bg-blue-600 rounded hover:bg-blue-500"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => setEditing(null)}
                      className="px-3 py-1 text-xs bg-gray-700 rounded hover:bg-gray-600"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => deleteProfile(profile.unique_id)}
                      className="px-3 py-1 text-xs bg-red-600 rounded hover:bg-red-500 ml-auto"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ) : (
                <div
                  className="flex items-center gap-2 cursor-pointer"
                  onClick={() => startEdit(profile)}
                >
                  <img
                    src={`http://127.0.0.1:8000/assets/images/${profile.img_src}`}
                    alt={profile.default_name}
                    className="w-8 h-8 object-contain"
                  />
                  <div>
                    <div className="text-sm">
                      {profile.custom_name || profile.default_name}
                    </div>
                    <div className="text-xs text-gray-500">{profile.unique_id}</div>
                    {resolveMac(profile) !== profile.unique_id && resolveMac(profile) && (
                      <div className="text-xs text-gray-500 font-mono">MAC: {resolveMac(profile)}</div>
                    )}
                    {profile.guid_override && (
                      <div className="text-xs text-yellow-500 font-mono">GUID: {profile.guid_override}</div>
                    )}
                  </div>
                  <div className="ml-auto flex items-center gap-2">
                    {connectResult[profile.unique_id] === 'ok' && (
                      <span className="text-[10px] text-green-400 uppercase font-bold tracking-tighter">Connected</span>
                    )}
                    {connectResult[profile.unique_id] === 'fail' && (
                      <span className="text-[10px] text-red-400 uppercase font-bold tracking-tighter">Failed</span>
                    )}
                    <button
                      onClick={(e) => forceConnect(profile, e)}
                      disabled={!resolveMac(profile) || connecting !== null}
                      title={
                        resolveMac(profile)
                          ? 'Attempt a Bluetooth connection even if the controller is not discoverable'
                          : 'No Bluetooth address stored for this controller'
                      }
                      className="px-2 py-1 text-xs bg-indigo-600 rounded hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 disabled:cursor-not-allowed"
                    >
                      {connecting === profile.unique_id ? 'Connecting…' : 'Force Connect'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
